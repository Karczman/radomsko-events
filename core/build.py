"""Przebieg: adaptery -> normalizacja -> geo -> filtr -> events.json (+ status.json, public/)."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from core.breaker import MIN_PREVIOUS, load_cache, save_cache, trip_reason
from core.dedupe import dedupe
from core.geo import Geo
from core.ics import build_ics, track
from core.models import Event, RawEvent
from core.normalize import TZ, event_end_date, fold, guess_category, localize, make_id
from core.rollup_cinema import rollup_cinema
from sources.base import USER_AGENT, Fetcher, Source
from sources.kamiensk import KamienskSource
from sources.listing import JsonLdListingSource
from sources.manual import ManualSource
from sources.mbp import MbpSource
from sources.mdk import MdkSource
from sources.muzeum import MuzeumSource
from sources.przedborz import PrzedborzSource
from sources.radomsko_pl import RadomskoPlSource

log = logging.getLogger("build")
ROOT = Path(__file__).resolve().parent.parent


def to_event(raw: RawEvent, geo: Geo, today: date) -> tuple[Event | None, str | None]:
    """Zwraca (Event, None) albo (None, powód odrzucenia)."""
    start = localize(raw.start)
    end = localize(raw.end) if raw.end else None
    if event_end_date(start, end) < today:
        return None, "past"
    loc = geo.resolve(raw.venue, raw.place)
    if loc is None:
        return None, "no-coordinates"
    if not geo.in_range(loc):
        return None, "out-of-range"
    event_id = make_id(raw.title, start, raw.venue)
    category = guess_category(raw.title) if raw.category == "inne" else raw.category
    if loc.municipality != "Radomsko" and category != "kino":
        category = "okolice"
    return Event(
        id=event_id, title=raw.title, start=start, end=end, all_day=raw.all_day, venue=raw.venue,
        place=raw.place or loc.municipality, lat=loc.lat, lon=loc.lon, distance_km=loc.distance_km,
        category=category, url=raw.url, ticket_url=raw.ticket_url, price_text=raw.price_text,
        times=raw.times, source=raw.source, sources=[raw.source],
        first_seen=today.isoformat(), last_seen=today.isoformat(),
        confidence=raw.confidence, status=raw.status,
    ), None


def build_sources(config: dict, root: Path = ROOT) -> list[Source]:
    cfg = config.get("sources", {})
    sources: list[Source] = []

    def on(name: str) -> dict | None:
        c = cfg.get(name)
        return c if c and c.get("enabled") else None

    if c := on("manual"):
        sources.append(ManualSource(root / c.get("path", "data/manual_events.yaml")))
    if c := on("mdk"):
        sources.append(MdkSource(max_pages=c.get("max_pages", 3)))
    if c := on("radomsko_pl"):
        sources.append(RadomskoPlSource(days_ahead=c.get("days_ahead", 120)))
    if on("muzeum"):
        sources.append(MuzeumSource())
    if on("mbp"):
        sources.append(MbpSource())
    if c := on("kamiensk"):
        sources.append(KamienskSource(days_ahead=c.get("days_ahead", 60)))
    if on("przedborz"):
        sources.append(PrzedborzSource())
    for name in ("biletyna", "ebilet"):
        if c := on(name):
            sources.append(JsonLdListingSource(name, c["urls"]))
    return sources


def load_seen(path: Path) -> dict[str, str]:
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def apply_seen(events: list[Event], seen: dict[str, str], today: date) -> tuple[list[Event], list[str]]:
    """first_seen z seen_ids.json; „nowe” = id, którego nie było w poprzednim przebiegu."""
    new_ids = []
    for e in events:
        if e.id in seen:
            e.first_seen = seen[e.id]
        else:
            e.first_seen = today.isoformat()
            if seen:  # pierwszy przebieg (pusty seen) nie ogłasza wszystkiego jako nowe
                new_ids.append(e.id)
    return events, new_ids


def _load_json(path: Path, default):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def _write_json(path: Path, data, sort_keys: bool = False) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=sort_keys) + "\n", "utf-8")


def _convert(raws: list[RawEvent], source: str, geo: Geo, today: date, todo: dict) -> tuple[list[Event], dict]:
    events, dropped = [], {}
    for raw in raws:
        event, reason = to_event(raw, geo, today)
        if event:
            events.append(event)
            continue
        dropped[reason] = dropped.get(reason, 0) + 1
        if reason == "no-coordinates":
            todo[(source, raw.venue, raw.place)] = {"source": source, "venue": raw.venue, "place": raw.place}
    return events, dropped


def run(config_path: Path = ROOT / "config.yaml", today: date | None = None) -> dict:
    """Pełny przebieg. Pliki w `data/` zmieniają się tylko, gdy zmieniła się treść (bez znaczników czasu),
    dzięki czemu workflow nie commituje w dni bez zmian. Czas generowania trafia tylko do `public/`."""
    config = yaml.safe_load(config_path.read_text("utf-8"))
    today = today or datetime.now(TZ).date()
    geo = Geo.load(ROOT / config["paths"]["venues"])
    data = ROOT / "data"
    events_path = ROOT / config["paths"]["events"]
    seen_path = ROOT / config["paths"].get("seen", "data/seen_ids.json")
    prev_status = _load_json(data / "status.json", {}).get("sources", {})
    fetcher = Fetcher(user_agent=config.get("user_agent", USER_AGENT))
    collected: list[Event] = []
    status: dict[str, dict] = {}
    todo: dict[tuple, dict] = {}
    now = datetime.now(TZ).isoformat(timespec="seconds")
    cache_dir = data / "source_cache"
    for source in build_sources(config):
        prev = prev_status.get(source.name)
        entry: dict = {}
        raws: list[RawEvent] | None = None
        guarded = source.name != "manual"  # plik ręczny edytujemy sami, więc bez cache (usunięty wpis nie wraca)
        try:
            raws = source.fetch(fetcher)
        except Exception as exc:  # błąd jednego adaptera nie przerywa przebiegu
            log.exception("źródło %s nie działa", source.name)
            entry = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200],
                     "first_failure": prev.get("first_failure") if prev and not prev.get("ok", True)
                     else today.isoformat()}
        events_src, dropped = (_convert(raws, source.name, geo, today, todo) if raws is not None else ([], {}))
        reason = None
        if raws is not None:
            min_previous = config.get("breaker", {}).get("min_previous", MIN_PREVIOUS)
            titles = len({fold(e.title) for e in events_src})
            reason = trip_reason(prev, titles, min_previous) if guarded else None
            entry = {"ok": True, "count": len(events_src), "titles": titles, "fetched": len(raws),
                     "dropped": dropped}
        if guarded and (raws is None or reason):
            cached = load_cache(cache_dir, source.name, today)
            if cached is not None:  # ostatnie dobre dane zamiast pustki
                events_src, dropped = _convert(cached, source.name, geo, today, todo)
                entry.update(stale=True, stale_reason=reason or "błąd pobierania",
                             stale_since=(prev or {}).get("stale_since") or today.isoformat(),
                             count=(prev or {}).get("count", len(events_src)),
                             titles=(prev or {}).get("titles", len({fold(e.title) for e in events_src})))
                log.warning("źródło %s: bezpiecznik, używam cache (%s)", source.name, entry["stale_reason"])
            elif reason:
                entry["stale_reason"] = f"{reason}, brak cache"
        elif guarded and not entry.get("stale"):
            save_cache(cache_dir, source.name, raws)
        collected += events_src
        status[source.name] = entry
    unique = list({e.id: e for e in collected}.values())  # ten sam wpis z kilku listingów jednego źródła
    merged = dedupe(unique, threshold=config.get("dedupe", {}).get("threshold", 90))
    final, new_ids = apply_seen(rollup_cinema(merged), load_seen(seen_path), today)
    final, ics_state = track(final, _load_json(data / "ics_state.json", {}), today)

    events_list = [e.model_dump(mode="json", exclude_none=True) for e in final]
    previous = _load_json(events_path, {})
    unchanged = previous.get("events") == events_list
    generated = previous["generated"] if unchanged else now  # w data/ czas zmienia się tylko razem z treścią
    events_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(events_path, {"generated": generated, "events": events_list})
    _write_json(seen_path, {e.id: e.first_seen for e in final}, sort_keys=True)
    _write_json(data / "ics_state.json", ics_state, sort_keys=True)
    status_doc = {"sources": status, "new": new_ids, "to_complete": list(todo.values())}
    _write_json(data / "status.json", status_doc)

    public = ROOT / "public"
    live_status = {"generated": now, **status_doc,
                   "sources": {n: {**s, **({"last_success": now} if s["ok"] and not s.get("stale") else {})}
                           for n, s in status.items()}}
    publish(public, {"generated": now, "events": events_list}, live_status, build_ics(final, ics_state))
    return {"generated": now, "events": events_list}


def publish(public: Path, events_doc: dict, status_doc: dict, ics: bytes) -> None:
    """Składa katalog `public/` (strona, dane, ICS), wdrażany na Pages przez workflow."""
    public.mkdir(exist_ok=True)
    for f in (ROOT / "web").iterdir():
        if f.is_file() and f.name != "legacy-dashboard.html":
            shutil.copy2(f, public / f.name)
    static = [public / n for n in ("index.html", "app.js", "style.css", "manifest.json", "icon.svg",
                                   "bricolage-latin.woff2", "bricolage-latin-ext.woff2")]
    version = hashlib.sha1(b"".join(p.read_bytes() for p in static)).hexdigest()[:8]
    sw = public / "sw.js"  # nowa wersja statyki = nowy cache, więc użytkownicy nie utkną na starym kodzie
    sw.write_text(sw.read_text("utf-8").replace("radomsko-static-v1", f"radomsko-static-{version}"), "utf-8")
    (public / "events.json").write_text(json.dumps(events_doc, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (public / "status.json").write_text(json.dumps(status_doc, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (public / "events.ics").write_bytes(ics)


def write_schema(path: Path = ROOT / "data/schema.json") -> None:
    schema = Event.model_json_schema()
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "events.json",
        "type": "object",
        "required": ["generated", "events"],
        "properties": {
            "generated": {"type": "string"},
            "events": {"type": "array", "items": {"$ref": "#/$defs/Event"}},
        },
        "$defs": {"Event": {k: v for k, v in schema.items() if k != "$defs"}, **schema.get("$defs", {})},
    }
    path.write_text(json.dumps(wrapper, ensure_ascii=False, indent=1) + "\n", "utf-8")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if "--schema" in sys.argv:
        write_schema()
    else:
        result = run()
        print(f"{len(result['events'])} wydarzeń")
