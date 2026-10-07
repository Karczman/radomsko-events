import json
from datetime import date, datetime

import httpx
import jsonschema
import pytest

from core.build import ROOT, apply_seen, to_event, write_schema
from core.models import Event, RawEvent
from sources.base import Fetcher, RobotsDisallowed

TODAY = date(2026, 10, 7)


def raw(**kw):
    base = dict(title="Test", start=datetime(2026, 11, 1, 18), venue="MDK Radomsko", place="Radomsko", source="mdk")
    return RawEvent(**{**base, **kw})


def test_past_event_removed_by_end_date_then_start(geo):
    assert to_event(raw(start=datetime(2026, 10, 6, 18)), geo, TODAY)[1] == "past"
    # trwająca wystawa: start w przeszłości, end w przyszłości, zostaje
    assert to_event(raw(start=datetime(2026, 9, 1), end=datetime(2026, 10, 7, 20)), geo, TODAY)[0]
    assert to_event(raw(start=datetime(2026, 10, 7, 9)), geo, TODAY)[0]  # dziś zostaje


def test_okolice_category_and_distance(geo):
    ev, _ = to_event(raw(venue="Klub Bogart", place="Gomunice"), geo, TODAY)
    assert ev.category == "okolice" and 10 < ev.distance_km < 13
    ev, _ = to_event(raw(), geo, TODAY)
    assert ev.category == "scena" or ev.category == "inne"  # Radomsko zachowuje kategorię adaptera
    assert ev.start.utcoffset().total_seconds() == 3600


def test_cinema_outside_radomsko_keeps_category(geo):
    ev, _ = to_event(raw(venue="Klub Bogart", place="Gomunice", category="kino"), geo, TODAY)
    assert ev.category == "kino"


def test_unknown_place_goes_to_todo_and_far_place_is_dropped(geo):
    assert to_event(raw(venue="Nieznany", place="Nibylandia"), geo, TODAY)[1] == "no-coordinates"
    assert to_event(raw(venue=None, place="Przyrów"), geo, TODAY)[1] == "out-of-range"
    assert to_event(raw(venue=None, place="Przedbórz"), geo, TODAY)[0] is not None


def test_apply_seen_marks_only_new_ids_after_first_run(geo):
    ev, _ = to_event(raw(), geo, TODAY)
    events, new = apply_seen([ev.model_copy()], {}, TODAY)
    assert new == [] and events[0].first_seen == "2026-10-07"  # pierwszy przebieg: nic nie jest „nowe”
    events, new = apply_seen([ev.model_copy()], {ev.id: "2026-10-01"}, TODAY)
    assert new == [] and events[0].first_seen == "2026-10-01"
    other, _ = to_event(raw(title="Inny"), geo, TODAY)
    _, new = apply_seen([ev.model_copy(), other], {ev.id: "2026-10-01"}, TODAY)
    assert new == [other.id]


def test_events_json_matches_schema(geo, tmp_path):
    ev, _ = to_event(raw(ticket_url="https://x.pl/t", times=["18:00"]), geo, TODAY)
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


def test_full_run_removes_past_marks_new_and_survives_failing_source(tmp_path, monkeypatch):
    """Cały `run()` offline: jedno źródło działa, drugie rzuca wyjątek, dane z dnia 1 i 2."""
    import shutil

    import yaml

    import core.build as build
    from core.models import RawEvent
    from sources.base import Source

    class Good(Source):
        name = "mdk"
        rows = [("Stare", datetime(2026, 10, 6, 18)), ("Dzisiaj", datetime(2026, 10, 7, 18)),
                ("Jutro", datetime(2026, 10, 8, 18))]

        def fetch(self, fetcher, today=None):
            return [
                RawEvent(title=t, start=s, venue="MDK Radomsko", place="Radomsko", source="mdk")
                for t, s in self.rows
            ]

    class Broken(Source):
        name = "biletyna"

        def fetch(self, fetcher, today=None):
            raise RuntimeError("503")

    root = tmp_path
    (root / "data").mkdir()
    (root / "web").mkdir()
    shutil.copy(ROOT / "data/venues.yaml", root / "data/venues.yaml")
    (root / "config.yaml").write_text(yaml.safe_dump({
        "paths": {"venues": "data/venues.yaml", "events": "data/events.json", "seen": "data/seen_ids.json"},
        "sources": {}, "dedupe": {"threshold": 90}}), "utf-8")
    monkeypatch.setattr(build, "ROOT", root)
    monkeypatch.setattr(build, "build_sources", lambda config, root=None: [Good(), Broken()])
    monkeypatch.setattr(build, "Fetcher", lambda **kw: None)

    day1 = build.run(root / "config.yaml", today=date(2026, 10, 7))
    assert [e["title"] for e in day1["events"]] == ["Dzisiaj", "Jutro"]  # „Stare” usunięte po dacie
    status = json.loads((root / "data/status.json").read_text("utf-8"))
    assert status["sources"]["biletyna"]["ok"] is False and status["sources"]["mdk"]["count"] == 2
    assert status["new"] == []  # pierwszy przebieg

    Good.rows.append(("Pojutrze", datetime(2026, 10, 9, 18)))
    day2 = build.run(root / "config.yaml", today=date(2026, 10, 8))
    assert [e["title"] for e in day2["events"]] == ["Jutro", "Pojutrze"]  # „Dzisiaj” zniknęło po dacie
    status = json.loads((root / "data/status.json").read_text("utf-8"))
    ids = {e["title"]: e["id"] for e in day2["events"]}
    assert status["new"] == [ids["Pojutrze"]]
    assert set(json.loads((root / "data/seen_ids.json").read_text("utf-8"))) == set(ids.values())
    assert [e for e in day2["events"] if e["title"] == "Jutro"][0]["first_seen"] == "2026-10-07"
