import json
from datetime import date, datetime, timedelta

import httpx
import pytest

from core.digest import Message, build_digest, send, source_alerts
from core.models import Event
from core.normalize import TZ

TODAY = date(2026, 10, 7)


def ev(i, title, day, hour=18, **kw):
    start = datetime(2026, 10, day, hour, 0, tzinfo=TZ)
    base = dict(id=f"id{i}", title=title, start=start, place="Radomsko", venue="MDK", source="mdk", sources=["mdk"],
                first_seen="2026-10-07", last_seen="2026-10-07")
    return Event(**{**base, **kw})


def test_title_counts_today_and_week_and_sections():
    events = [ev(1, "Dziś A", 7, 19), ev(2, "Jutro B", 8), ev(3, "Za tydzień C", 14), ev(4, "Później D", 20)]
    msg = build_digest(events, TODAY, ["id2"], "https://site/")
    assert msg.title == "Radomsko: dziś 1, w tygodniu 2"
    assert "Dziś:\n• 19:00 Dziś A (MDK)" in msg.body
    assert "Najbliższe 7 dni:\n• cz 8.10 18:00 Jutro B\n• śr 14.10 18:00 Za tydzień C" in msg.body
    assert "Później D" not in msg.body
    assert "Nowe:\n• cz 8.10 18:00 Jutro B" in msg.body
    assert msg.click == "https://site/"


def test_week_is_capped_at_eight_and_new_at_five():
    events = [ev(i, f"E{i}", 8 + (i % 7)) for i in range(12)]
    msg = build_digest(events, TODAY, [e.id for e in events], None)
    week = msg.body.split("Najbliższe 7 dni:\n")[1].split("\n\n")[0].split("\n")
    assert len(week) == 9 and week[-1] == "… i 4 więcej"
    assert len(msg.body.split("Nowe:\n")[1].split("\n")) == 5


def test_cancelled_events_are_not_announced_and_multiday_counts_as_today():
    events = [
        ev(1, "Odwołane", 7, status="cancelled"),
        ev(2, "Wystawa", 5, end=datetime(2026, 10, 9, tzinfo=TZ), all_day=True),
    ]
    msg = build_digest(events, TODAY, [], None)
    assert "Odwołane" not in msg.body and "Wystawa" in msg.body and msg.title.startswith("Radomsko: dziś 1")


def test_empty_day_short_or_skip():
    events = [ev(1, "A", 9), ev(2, "B", 10), ev(3, "C", 11), ev(4, "D", 12)]
    short = build_digest(events, TODAY, [], None, when_empty="short")
    assert short.title == "Radomsko: dziś 0, w tygodniu 4" and short.body.count("•") == 3
    assert build_digest(events, TODAY, [], None, when_empty="skip") is None
    assert "Brak wydarzeń" in build_digest([], TODAY, [], None, "short").body


def test_source_alert_after_three_days_and_for_circuit_breaker():
    status = {"sources": {
        "a": {"ok": False, "first_failure": (TODAY - timedelta(days=4)).isoformat()},
        "b": {"ok": False, "first_failure": (TODAY - timedelta(days=3)).isoformat()},
        "c": {"ok": True, "stale": True, "reason": "0 wydarzeń"},
        "d": {"ok": True},
    }}
    msg = source_alerts(status, TODAY)
    assert msg.priority == 4 and "a: nie działa od 4 dni" in msg.body and "c: bezpiecznik" in msg.body
    assert "b:" not in msg.body and "d:" not in msg.body  # 3 dni to jeszcze nie alert
    assert source_alerts({"sources": {"d": {"ok": True}}}, TODAY) is None


def test_send_posts_json_with_utf8_and_optional_token():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), auth=req.headers.get("authorization"), json=json.loads(req.content))
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    send(Message("Radomsko: dziś 1", "• Łódź", "https://site/"), "sekretny-temat", "tok", client=client)
    assert seen["url"] == "https://ntfy.sh" and seen["auth"] == "Bearer tok"
    assert seen["json"]["topic"] == "sekretny-temat" and seen["json"]["message"] == "• Łódź"
    assert seen["json"]["click"] == "https://site/"
    send(Message("t", "b"), "x", None, client=client)
    assert seen["auth"] is None and "click" not in seen["json"]


def test_send_raises_on_error():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(httpx.HTTPStatusError):
        send(Message("t", "b"), "x", client=client)


def test_cinema_is_announced_only_on_screening_days():
    # Film grany 7.10, 13.10 i 14.10: w zakresie 7-14.10, ale 8-12.10 bez seansów
    film = ev(1, "Lalka / 2D", 7, 17, end=datetime(2026, 10, 14, 20, tzinfo=TZ), category="kino",
              dates=["2026-10-07", "2026-10-13", "2026-10-14"], times=["17:00", "20:00"])
    assert build_digest([film], date(2026, 10, 7), [], None).title == "Radomsko: dziś 1, w tygodniu 0"
    mid = build_digest([film], date(2026, 10, 9), [], None, when_empty="short")
    assert mid.title == "Radomsko: dziś 0, w tygodniu 1" and "wt 13.10" in mid.body  # najbliższy seans, nie 7.10
    after = build_digest([film], date(2026, 10, 14), [], None)
    assert after.title.startswith("Radomsko: dziś 1")
    assert build_digest([film], date(2026, 10, 15), [], None, when_empty="skip") is None


def test_body_fits_ntfy_limit_even_with_many_long_events():
    from core.digest import MAX_BODY
    today = [ev(i, "Ż" * 290 + str(i), 7, 10) for i in range(40)]
    week = [ev(100 + i, "Ą" * 290, 8 + i % 6) for i in range(20)]
    msg = build_digest(today + week, TODAY, [e.id for e in week], None)
    assert len(msg.body.encode()) <= MAX_BODY and msg.body.endswith("…")
    short = build_digest([ev(i, f"Krótki {i}", 7, 10) for i in range(15)], TODAY, [], None)
    assert short.body.count("•") == 10 and "… i 5 więcej" in short.body  # limit pozycji „Dziś”


def test_send_includes_scheduled_delivery_when_given():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    send(Message("t", "b"), "x", client=client, delay="1791608400")
    assert seen["delay"] == "1791608400"
    seen.clear()
    send(Message("t", "b"), "x", client=client)
    assert "delay" not in seen
