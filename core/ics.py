"""Eksport ICS (RFC 5545): stabilny UID, rosnący SEQUENCE przy zmianie, VTIMEZONE Europe/Warsaw.

Stan (`data/ics_state.json`) trzyma hash treści, numer SEQUENCE, datę ostatniej zmiany i datę odwołania.
Odwołane wydarzenia zostają w kalendarzu jako `STATUS:CANCELLED` przez 7 dni, potem znikają.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from icalendar import Calendar, Timezone, TimezoneDaylight, TimezoneStandard
from icalendar import Event as IEvent

from core.models import Event
from core.normalize import TZ

CANCELLED_KEEP_DAYS = 7
PRODID = "-//radomsko-events//PL"
_HASHED = ("title", "start", "end", "all_day", "venue", "place", "category", "url", "ticket_url", "price_text",
           "times", "status")


def event_hash(e: Event) -> str:
    payload = json.dumps(e.model_dump(mode="json", include=set(_HASHED)), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def track(events: list[Event], state: dict, today: date) -> tuple[list[Event], dict]:
    """Aktualizuje stan i zwraca (wydarzenia do publikacji, nowy stan). Czyści stan z zakończonych."""
    new_state: dict[str, dict] = {}
    kept: list[Event] = []
    for e in events:
        h = event_hash(e)
        old = state.get(e.id)
        entry = {"h": h, "seq": 0, "stamp": today.isoformat()} if old is None else dict(old)
        if old is not None and old["h"] != h:
            entry.update(h=h, seq=old["seq"] + 1, stamp=today.isoformat())
        if e.status == "cancelled":
            entry.setdefault("cancelled_since", today.isoformat())
            if (today - date.fromisoformat(entry["cancelled_since"])).days > CANCELLED_KEEP_DAYS:
                continue
        else:
            entry.pop("cancelled_since", None)
        new_state[e.id] = entry
        kept.append(e)
    return kept, new_state


def _timezone() -> Timezone:
    tz = Timezone()
    tz.add("tzid", "Europe/Warsaw")
    tz.add("x-lic-location", "Europe/Warsaw")
    dst = {"freq": "yearly", "bymonth": 3, "byday": "-1SU"}
    std = {"freq": "yearly", "bymonth": 10, "byday": "-1SU"}
    for cls, start, frm, to, name, rule in (
        (TimezoneDaylight, datetime(1970, 3, 29, 2), "+0100", "+0200", "CEST", dst),
        (TimezoneStandard, datetime(1970, 10, 25, 3), "+0200", "+0100", "CET", std),
    ):
        part = cls()
        part.add("dtstart", start)
        part.add("tzoffsetfrom", _offset(frm))
        part.add("tzoffsetto", _offset(to))
        part.add("tzname", name)
        part.add("rrule", rule)
        tz.add_component(part)
    return tz


def _offset(text: str) -> timedelta:
    sign = -1 if text[0] == "-" else 1
    return sign * timedelta(hours=int(text[1:3]), minutes=int(text[3:5]))


def _description(e: Event) -> str:
    lines = []
    if e.dates:
        days = [f"{int(d[8:10])}.{d[5:7]}" for d in e.dates]
        lines.append("Dni seansów: " + ", ".join(days))
    if e.times:
        lines.append("Godziny seansów: " + ", ".join(e.times))
    if e.price_text:
        lines.append(f"Cena: {e.price_text}")
    if e.ticket_url:
        lines.append(f"Bilety: {e.ticket_url}")
    if e.url:
        lines.append(f"Szczegóły: {e.url}")
    if e.confidence == "low":
        lines.append("Termin ustalony automatycznie, sprawdź u organizatora.")
    return "\n".join(lines)


def to_vevent(e: Event, entry: dict) -> IEvent:
    v = IEvent()
    v.add("uid", f"{e.id}@radomsko-events")
    stamp = datetime.fromisoformat(entry["stamp"]).replace(hour=5, tzinfo=UTC)
    v.add("dtstamp", stamp)
    v.add("last-modified", stamp)
    v.add("sequence", entry["seq"])
    v.add("summary", e.title)
    start = e.start.astimezone(TZ)
    end = e.end.astimezone(TZ) if e.end else None
    if e.all_day or (e.times and end):  # dzień bez godziny albo zakres dni kina (godziny w opisie)
        last = (end or start).date()
        v.add("dtstart", start.date())
        v.add("dtend", last + timedelta(days=1))
    else:
        v.add("dtstart", start)
        v.add("dtend", end if end and end > start else start + timedelta(hours=2))
    if e.venue and e.place and e.place.lower() not in e.venue.lower():
        location = f"{e.venue}, {e.place}"
    else:
        location = e.venue or e.place or ""
    if location:
        v.add("location", location)
    if e.lat is not None and e.lon is not None:
        v.add("geo", (e.lat, e.lon))
    v.add("categories", [e.category])
    v.add("status", "CANCELLED" if e.status == "cancelled" else "CONFIRMED")
    if e.url or e.ticket_url:
        v.add("url", e.url or e.ticket_url)
    if desc := _description(e):
        v.add("description", desc)
    return v


def build_ics(events: list[Event], state: dict) -> bytes:
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Radomsko: wydarzenia")
    cal.add("x-wr-timezone", "Europe/Warsaw")
    cal.add("refresh-interval;value=duration", "PT12H")
    cal.add("x-published-ttl", "PT12H")
    cal.add_component(_timezone())
    for e in events:
        cal.add_component(to_vevent(e, state[e.id]))
    return cal.to_ical()
