"""Przebieg: adaptery -> normalizacja -> geo -> filtr -> events.json (+ status.json, public/)."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from core.dedupe import dedupe
from core.geo import Geo
from core.models import Event, RawEvent
from core.normalize import TZ, event_end_date, guess_category, localize, make_id
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
        confidence=raw.confidence,
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


def run(config_path: Path = ROOT / "config.yaml", today: date | None = None) -> dict:
    config = yaml.safe_load(config_path.read_text("utf-8"))
    today = today or datetime.now(TZ).date()
    geo = Geo.load(ROOT / config["paths"]["venues"])
    events_path = ROOT / config["paths"]["events"]
    seen_path = ROOT / config["paths"].get("seen", "data/seen_ids.json")
    fetcher = Fetcher(user_agent=config.get("user_agent", USER_AGENT))
    collected: list[Event] = []
    status: dict[str, dict] = {}
    todo: dict[tuple, dict] = {}
    now = datetime.now(TZ).isoformat(timespec="seconds")
    for source in build_sources(config):
        try:
            raws = source.fetch(fetcher)
        except Exception as exc:  # błąd jednego adaptera nie przerywa przebiegu
            log.exception("źródło %s nie działa", source.name)
            status[source.name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "checked": now}
            continue
        kept, dropped = 0, {}
        for raw in raws:
            event, reason = to_event(raw, geo, today)
            if event:
                collected.append(event)
                kept += 1
                continue
            dropped[reason] = dropped.get(reason, 0) + 1
            if reason == "no-coordinates":
                key = (source.name, raw.venue, raw.place)
                todo[key] = {"source": source.name, "venue": raw.venue, "place": raw.place}
        status[source.name] = {
            "ok": True, "last_success": now, "count": kept, "fetched": len(raws), "dropped": dropped,
        }
    unique = list({e.id: e for e in collected}.values())  # ten sam wpis z kilku listingów jednego źródła
    merged = dedupe(unique, threshold=config.get("dedupe", {}).get("threshold", 90))
    final, new_ids = apply_seen(rollup_cinema(merged), load_seen(seen_path), today)
    payload = {"generated": now, "events": [e.model_dump(mode="json", exclude_none=True) for e in final]}
    out = json.dumps(payload, ensure_ascii=False, indent=1)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(out + "\n", "utf-8")
    seen_path.write_text(json.dumps({e.id: e.first_seen for e in final}, indent=1, sort_keys=True) + "\n", "utf-8")
    (ROOT / "data/status.json").write_text(
        json.dumps({"generated": now, "sources": status, "new": new_ids, "to_complete": list(todo.values())},
                   ensure_ascii=False, indent=1) + "\n",
        "utf-8",
    )
    publish(ROOT / "public", out)
    return payload


def publish(public: Path, events_json: str) -> None:
    """Składa katalog `public/` (strona + dane). Deploy na Pages dojdzie w etapie 3."""
    public.mkdir(exist_ok=True)
    for f in (ROOT / "web").iterdir():
        if f.is_file() and f.name != "legacy-dashboard.html":
            shutil.copy2(f, public / f.name)
    (public / "events.json").write_text(events_json + "\n", "utf-8")
    status = ROOT / "data/status.json"
    if status.exists():
        shutil.copy2(status, public / "status.json")


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
