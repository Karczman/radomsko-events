"""Przebieg: adaptery -> normalizacja -> geo -> filtr -> events.json (+ status.json, public/)."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from core.geo import Geo
from core.models import Event, RawEvent
from core.normalize import TZ, event_end_date, localize, make_id
from sources.base import USER_AGENT, Fetcher, Source
from sources.mdk import MdkSource

log = logging.getLogger("build")
ROOT = Path(__file__).resolve().parent.parent


def to_event(raw: RawEvent, geo: Geo, today: date, previous: dict[str, Event]) -> tuple[Event | None, str | None]:
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
    old = previous.get(event_id)
    category = "okolice" if loc.municipality != "Radomsko" and raw.category != "kino" else raw.category
    return Event(
        id=event_id, title=raw.title, start=start, end=end, all_day=raw.all_day, venue=raw.venue,
        place=raw.place or loc.municipality, lat=loc.lat, lon=loc.lon, distance_km=loc.distance_km,
        category=category, url=raw.url, ticket_url=raw.ticket_url, price_text=raw.price_text,
        times=raw.times, source=raw.source, sources=[raw.source],
        first_seen=old.first_seen if old else today.isoformat(), last_seen=today.isoformat(),
        confidence=raw.confidence,
    ), None


def build_sources(config: dict) -> list[Source]:
    cfg = config.get("sources", {})
    sources: list[Source] = []
    if cfg.get("mdk", {}).get("enabled"):
        sources.append(MdkSource(max_pages=cfg["mdk"].get("max_pages", 3)))
    return sources


def load_previous(path: Path) -> dict[str, Event]:
    if not path.exists():
        return {}
    return {e["id"]: Event.model_validate(e) for e in json.loads(path.read_text("utf-8"))["events"]}


def run(config_path: Path = ROOT / "config.yaml", today: date | None = None) -> dict:
    config = yaml.safe_load(config_path.read_text("utf-8"))
    today = today or datetime.now(TZ).date()
    geo = Geo.load(ROOT / config["paths"]["venues"])
    events_path = ROOT / config["paths"]["events"]
    previous = load_previous(events_path)
    fetcher = Fetcher(user_agent=config.get("user_agent", USER_AGENT))
    events: dict[str, Event] = {}
    status: dict[str, dict] = {}
    todo: list[dict] = []
    now = datetime.now(TZ).isoformat(timespec="seconds")
    for source in build_sources(config):
        try:
            raws = source.fetch(fetcher)
        except Exception as exc:  # błąd jednego adaptera nie przerywa przebiegu
            log.exception("źródło %s nie działa", source.name)
            status[source.name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "checked": now}
            continue
        kept = 0
        for raw in raws:
            event, reason = to_event(raw, geo, today, previous)
            if event:
                events.setdefault(event.id, event)
                kept += 1
            elif reason == "no-coordinates":
                todo.append({"source": source.name, "title": raw.title, "venue": raw.venue, "place": raw.place})
        status[source.name] = {"ok": True, "last_success": now, "count": kept, "fetched": len(raws)}
    ordered = sorted(events.values(), key=lambda e: (e.start, e.title))
    payload = {"generated": now, "events": [e.model_dump(mode="json", exclude_none=True) for e in ordered]}
    out = json.dumps(payload, ensure_ascii=False, indent=1)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(out + "\n", "utf-8")
    (ROOT / "data/status.json").write_text(
        json.dumps({"generated": now, "sources": status, "to_complete": todo}, ensure_ascii=False, indent=1) + "\n",
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
