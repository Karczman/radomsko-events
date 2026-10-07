import json
from datetime import date, datetime

import httpx
import jsonschema
import pytest

from core.build import ROOT, to_event, write_schema
from core.models import Event, RawEvent
from sources.base import Fetcher, RobotsDisallowed

TODAY = date(2026, 10, 7)


def raw(**kw):
    base = dict(title="Test", start=datetime(2026, 11, 1, 18), venue="MDK Radomsko", place="Radomsko", source="mdk")
    return RawEvent(**{**base, **kw})


def test_past_event_removed_by_end_date_then_start(geo):
    assert to_event(raw(start=datetime(2026, 10, 6, 18)), geo, TODAY, {})[1] == "past"
    # trwająca wystawa: start w przeszłości, end w przyszłości, zostaje
    assert to_event(raw(start=datetime(2026, 9, 1), end=datetime(2026, 10, 7, 20)), geo, TODAY, {})[0]
    assert to_event(raw(start=datetime(2026, 10, 7, 9)), geo, TODAY, {})[0]  # dziś zostaje


def test_okolice_category_and_distance(geo):
    ev, _ = to_event(raw(venue="Klub Bogart", place="Gomunice"), geo, TODAY, {})
    assert ev.category == "okolice" and 10 < ev.distance_km < 13
    ev, _ = to_event(raw(), geo, TODAY, {})
    assert ev.category == "scena" or ev.category == "inne"  # Radomsko zachowuje kategorię adaptera
    assert ev.start.utcoffset().total_seconds() == 3600


def test_cinema_outside_radomsko_keeps_category(geo):
    ev, _ = to_event(raw(venue="Klub Bogart", place="Gomunice", category="kino"), geo, TODAY, {})
    assert ev.category == "kino"


def test_unknown_place_goes_to_todo_and_far_place_is_dropped(geo):
    assert to_event(raw(venue="Nieznany", place="Nibylandia"), geo, TODAY, {})[1] == "no-coordinates"
    assert to_event(raw(venue=None, place="Przyrów"), geo, TODAY, {})[1] == "out-of-range"
    assert to_event(raw(venue=None, place="Przedbórz"), geo, TODAY, {})[0] is not None


def test_first_seen_preserved_from_previous_run(geo):
    first, _ = to_event(raw(), geo, date(2026, 10, 1), {})
    again, _ = to_event(raw(), geo, TODAY, {first.id: first})
    assert again.first_seen == "2026-10-01" and again.last_seen == "2026-10-07"


def test_events_json_matches_schema(geo, tmp_path):
    ev, _ = to_event(raw(ticket_url="https://x.pl/t", times=["18:00"]), geo, TODAY, {})
    payload = {"generated": "2026-10-07T05:00:00+02:00", "events": [ev.model_dump(mode="json", exclude_none=True)]}
    write_schema(tmp_path / "schema.json")
    jsonschema.validate(payload, json.loads((tmp_path / "schema.json").read_text("utf-8")))
    bad = {**payload, "events": [{**payload["events"][0], "category": "nieznana"}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, json.loads((tmp_path / "schema.json").read_text("utf-8")))


def test_committed_schema_is_current(tmp_path):
    write_schema(tmp_path / "schema.json")
    fresh = json.loads((tmp_path / "schema.json").read_text("utf-8"))
    assert fresh == json.loads((ROOT / "data/schema.json").read_text("utf-8"))
    assert Event.model_json_schema()["title"] == "Event"


def _fetcher(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "radomsko-events/1.0"})
    return Fetcher(user_agent="radomsko-events/1.0", min_interval=0, retries=2, client=client)


def test_fetcher_respects_robots_txt():
    def handler(req):
        if req.url.path == "/robots.txt":
            rules = "User-agent: *\nDisallow: /private/"
            return httpx.Response(200, text=rules, headers={"content-type": "text/plain"})
        return httpx.Response(200, json={"ok": True})
    f = _fetcher(handler)
    assert f.get("https://example.pl/public").json() == {"ok": True}
    with pytest.raises(RobotsDisallowed):
        f.get("https://example.pl/private/x")


def test_fetcher_missing_robots_means_allowed_and_retries_5xx(monkeypatch):
    monkeypatch.setattr("sources.base.time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404, text="<html>nie ma</html>")
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json={"ok": 1})
    assert _fetcher(handler).get("https://example.pl/data").json() == {"ok": 1}
    assert calls["n"] == 2
