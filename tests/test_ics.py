from datetime import date, datetime, timedelta

from icalendar import Calendar

from core.ics import build_ics, event_hash, track
from core.models import Event
from core.normalize import TZ


def ev(title="Koncert", start=datetime(2026, 11, 7, 18, 0, tzinfo=TZ), **kw):
    base = dict(id="abc123", title=title, start=start, place="Radomsko", venue="MDK Radomsko", source="mdk",
                sources=["mdk"], first_seen="2026-10-07", last_seen="2026-10-07", lat=51.06667, lon=19.45)
    return Event(**{**base, **kw})


def parse(events, state):
    return Calendar.from_ical(build_ics(events, state))


def vevents(cal):
    return [c for c in cal.walk() if c.name == "VEVENT"]


def test_ics_parses_and_has_timezone_uid_and_fields():
    e = ev(url="https://mdk/e", ticket_url="https://t/1", price_text="50 zł")
    kept, state = track([e], {}, date(2026, 10, 7))
    cal = parse(kept, state)
    tz = [c for c in cal.walk() if c.name == "VTIMEZONE"]
    assert tz and tz[0]["TZID"] == "Europe/Warsaw"
    assert {c.name for c in tz[0].subcomponents} == {"DAYLIGHT", "STANDARD"}
    (v,) = vevents(cal)
    assert v["UID"] == "abc123@radomsko-events" and int(v["SEQUENCE"]) == 0
    assert v["SUMMARY"] == "Koncert" and v["STATUS"] == "CONFIRMED"
    assert v.decoded("DTSTART") == datetime(2026, 11, 7, 18, 0, tzinfo=TZ)
    assert v.decoded("DTEND") - v.decoded("DTSTART") == timedelta(hours=2)
    assert "Cena: 50 zł" in v["DESCRIPTION"] and "Bilety: https://t/1" in v["DESCRIPTION"]
    assert b"TZID=Europe/Warsaw" in build_ics(kept, state)


def test_dst_summer_and_winter_keep_wall_clock():
    summer = ev(id="s", start=datetime(2026, 7, 1, 20, tzinfo=TZ))
    winter = ev(id="w", start=datetime(2026, 12, 1, 20, tzinfo=TZ))
    kept, state = track([summer, winter], {}, date(2026, 6, 1))
    vs = {str(v["UID"]): v.decoded("DTSTART") for v in vevents(parse(kept, state))}
    assert vs["s@radomsko-events"].utcoffset() == timedelta(hours=2)
    assert vs["w@radomsko-events"].utcoffset() == timedelta(hours=1)
    assert vs["s@radomsko-events"].hour == 20 and vs["w@radomsko-events"].hour == 20


def test_all_day_uses_date_values_with_exclusive_end():
    kept, state = track([ev(all_day=True, end=datetime(2026, 11, 9, tzinfo=TZ))], {}, date(2026, 10, 7))
    (v,) = vevents(parse(kept, state))
    assert v.decoded("DTSTART") == date(2026, 11, 7) and v.decoded("DTEND") == date(2026, 11, 10)


def test_cinema_range_becomes_all_day_span_with_times_in_description():
    e = ev(times=["17:00", "19:30"], dates=["2026-11-07", "2026-11-09"], end=datetime(2026, 11, 9, 19, 30, tzinfo=TZ),
           category="kino")
    kept, state = track([e], {}, date(2026, 10, 7))
    (v,) = vevents(parse(kept, state))
    assert v.decoded("DTSTART") == date(2026, 11, 7) and v.decoded("DTEND") == date(2026, 11, 10)
    assert "Godziny seansów: 17:00, 19:30" in v["DESCRIPTION"]
    assert "Dni seansów: 7.11, 9.11" in v["DESCRIPTION"]


def test_sequence_grows_only_when_content_changes():
    d1, d2, d3 = date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)
    _, s1 = track([ev()], {}, d1)
    _, s2 = track([ev()], s1, d2)
    assert s2["abc123"] == s1["abc123"]  # bez zmian: ten sam hash, SEQUENCE i stamp
    _, s3 = track([ev(title="Koncert (nowa godzina)", start=datetime(2026, 11, 7, 19, tzinfo=TZ))], s2, d3)
    assert s3["abc123"]["seq"] == 1 and s3["abc123"]["stamp"] == "2026-10-09"
    assert event_hash(ev()) != event_hash(ev(price_text="10 zł"))


def test_cancelled_stays_seven_days_then_disappears_and_state_is_pruned():
    cancelled = ev(status="cancelled")
    kept, state = track([cancelled], {}, date(2026, 10, 7))
    (v,) = vevents(parse(kept, state))
    assert v["STATUS"] == "CANCELLED"
    kept, state = track([cancelled], state, date(2026, 10, 14))  # dokładnie 7 dni: jeszcze jest
    assert len(kept) == 1
    kept, state = track([cancelled], state, date(2026, 10, 15))
    assert kept == [] and state == {}
    _, state = track([ev()], {"stary": {"h": "x", "seq": 0, "stamp": "2026-01-01"}}, date(2026, 10, 7))
    assert "stary" not in state  # stan zakończonych wydarzeń jest czyszczony


def test_uncancelled_event_resets_cancel_marker():
    _, s1 = track([ev(status="cancelled")], {}, date(2026, 10, 7))
    _, s2 = track([ev()], s1, date(2026, 10, 8))
    assert "cancelled_since" not in s2["abc123"]


def test_rfc5545_wire_format_rules_that_google_and_outlook_enforce():
    """CRLF, linie <= 75 oktetów, unikalne UID, DTSTART/DTEND tego samego typu, strefa zdefiniowana."""
    events = [
        ev(id="a1", title="Bardzo długi tytuł " + "żółć " * 40, url="https://mdkradomsko.pl/" + "x" * 120),
        ev(id="a2", all_day=True, end=datetime(2026, 11, 9, tzinfo=TZ)),
        ev(id="a3", times=["17:00"], dates=["2026-11-07", "2026-11-08"], end=datetime(2026, 11, 8, 17, tzinfo=TZ),
           category="kino"),
        ev(id="a4", status="cancelled"),
    ]
    kept, state = track(events, {}, date(2026, 10, 7))
    raw = build_ics(kept, state)
    assert raw.count(b"\n") == raw.count(b"\r\n"), "linie muszą kończyć się CRLF"
    assert all(len(line) <= 75 for line in raw.split(b"\r\n")), "linia dłuższa niż 75 oktetów (brak zawijania)"
    raw.decode("utf-8")
    cal = Calendar.from_ical(raw)
    vs = vevents(cal)
    assert len({str(v["UID"]) for v in vs}) == len(vs) == 4
    for v in vs:
        start, end = v.decoded("DTSTART"), v.decoded("DTEND")
        assert type(start) is type(end) and end > start
        if isinstance(start, datetime):
            assert v["DTSTART"].params.get("TZID") == "Europe/Warsaw"
        assert "DTSTAMP" in v and "SUMMARY" in v
