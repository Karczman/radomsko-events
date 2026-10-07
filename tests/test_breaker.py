import json
import shutil
from datetime import date, datetime

import pytest
import yaml

import core.build as build
from core.breaker import load_cache, save_cache, trip_reason
from core.digest import source_alerts
from core.models import RawEvent
from sources.base import Source

ROOT = build.ROOT


def test_trip_reason_thresholds():
    assert trip_reason(None, 0) is None
    assert trip_reason({"count": 4}, 0) is None  # za mało, żeby ufać (min 5)
    assert "0 wydarzeń" in trip_reason({"count": 20}, 0)
    assert "9 tytułów zamiast 20" in trip_reason({"count": 20}, 9)
    assert trip_reason({"count": 20}, 10) is None  # dokładnie 50%: jeszcze OK
    assert trip_reason({"count": 60, "titles": 30}, 25) is None  # liczą się tytuły, nie terminy
    assert "9 tytułów zamiast 30" in trip_reason({"count": 60, "titles": 30}, 9)
    assert trip_reason({"count": 20}, 25) is None
    assert trip_reason({"count": 3}, 0, min_previous=2) is not None


def test_cache_roundtrip_drops_past_events(tmp_path):
    raws = [RawEvent(title="Stare", start=datetime(2026, 10, 1, 18), source="mdk"),
            RawEvent(title="Nowe", start=datetime(2026, 11, 1, 18), source="mdk")]
    assert load_cache(tmp_path, "mdk", date(2026, 10, 7)) is None
    save_cache(tmp_path, "mdk", raws)
    assert [r.title for r in load_cache(tmp_path, "mdk", date(2026, 10, 7))] == ["Nowe"]


class Flaky(Source):
    name = "mdk"
    mode = "ok"

    def fetch(self, fetcher, today=None):
        if self.mode == "boom":
            raise RuntimeError("503 Service Unavailable")
        n = 0 if self.mode == "empty" else 10
        return [RawEvent(title=f"Wydarzenie {i}", start=datetime(2026, 11, 1 + i, 18), venue="MDK Radomsko",
                         place="Radomsko", source="mdk") for i in range(n)]


@pytest.fixture
def site(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "web", tmp_path / "web")
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "data/venues.yaml", tmp_path / "data/venues.yaml")
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "paths": {"venues": "data/venues.yaml", "events": "data/events.json", "seen": "data/seen_ids.json"},
        "sources": {}}), "utf-8")
    source = Flaky()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "build_sources", lambda config, root=None: [source])
    monkeypatch.setattr(build, "Fetcher", lambda **kw: None)

    def run(day, mode):
        source.mode = mode
        today = day if isinstance(day, date) else date(2026, 10, day)
        out = build.run(tmp_path / "config.yaml", today=today)
        status = json.loads((tmp_path / "data/status.json").read_text("utf-8"))
        return out, status["sources"]["mdk"], status

    return run, tmp_path


def test_empty_source_keeps_previous_data_and_alerts(site):
    run, root = site
    out, st, _ = run(7, "ok")
    assert len(out["events"]) == 10 and st["ok"] and "stale" not in st
    assert (root / "data/source_cache/mdk.json").exists()
    out, st, full = run(8, "empty")  # bezpiecznik: 0 wydarzeń przy 10 poprzednio
    assert len(out["events"]) == 10  # strona nadal ma dane
    assert st["stale"] and st["stale_since"] == "2026-10-08" and "0 wydarzeń" in st["stale_reason"]
    assert st["count"] == 10  # porównujemy z ostatnim dobrym stanem, nie z zerem
    alert = source_alerts(full, date(2026, 10, 8))
    assert alert is not None and "bezpiecznik" in alert.body and "mdk" in alert.body


def test_failing_source_serves_cache_then_recovers(site):
    run, _ = site
    run(7, "ok")
    out, st, full = run(8, "boom")
    assert len(out["events"]) == 10 and st["ok"] is False and st["stale"] and st["first_failure"] == "2026-10-08"
    assert source_alerts(full, date(2026, 10, 9)).body.count("bezpiecznik") == 1
    out, st, _ = run(10, "boom")
    assert st["first_failure"] == "2026-10-08" and st["stale_since"] == "2026-10-08"  # początek awarii się nie przesuwa
    out, st, full = run(11, "ok")  # źródło wróciło
    assert st["ok"] and "stale" not in st and "first_failure" not in st
    assert source_alerts(full, date(2026, 10, 11)) is None


def test_stale_cache_does_not_resurrect_past_events(site):
    run, _ = site
    run(7, "ok")  # wydarzenia 1..10 listopada
    out, st, _ = run(date(2026, 11, 5), "boom")
    assert st["stale"] and [e["start"][:10] for e in out["events"]][0] == "2026-11-05"
    assert len(out["events"]) == 6  # 5..10 listopada, wcześniejsze usunięte po dacie


def test_failing_source_without_cache_does_not_break_the_page(site):
    run, _ = site
    out, st, _ = run(7, "boom")
    assert out["events"] == [] and st["ok"] is False and not st.get("stale")


def test_manual_source_is_never_cached_or_resurrected(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "web", tmp_path / "web")
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "data/venues.yaml", tmp_path / "data/venues.yaml")
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "paths": {"venues": "data/venues.yaml", "events": "data/events.json", "seen": "data/seen_ids.json"},
        "sources": {}}), "utf-8")

    class Manual(Flaky):
        name = "manual"

    src = Manual()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "build_sources", lambda config, root=None: [src])
    monkeypatch.setattr(build, "Fetcher", lambda **kw: None)
    build.run(tmp_path / "config.yaml", today=date(2026, 10, 7))
    assert not (tmp_path / "data/source_cache/manual.json").exists()
    src.mode = "empty"  # usunąłem wszystkie wpisy ręczne
    out = build.run(tmp_path / "config.yaml", today=date(2026, 10, 8))
    assert out["events"] == []


def test_expiring_screenings_do_not_trip_the_breaker(site, monkeypatch):
    """Seanse jednego filmu wygasają (terminów mniej o 80%), a tytułów tyle samo: bez fałszywego alarmu."""
    run, _ = site
    run(7, "ok")  # 10 różnych tytułów

    def many_then_few(self, fetcher, today=None):
        n_dates = 5 if self.mode == "ok" else 1
        return [RawEvent(title=f"Film {i}", start=datetime(2026, 11, 1 + d, 18), venue="MDK Radomsko",
                         place="Radomsko", source="mdk") for i in range(10) for d in range(n_dates)]
    monkeypatch.setattr(Flaky, "fetch", many_then_few)
    run(8, "ok")            # 50 terminów, 10 tytułów
    _, st, _ = run(9, "few")  # 10 terminów (spadek o 80%), nadal 10 tytułów
    assert "stale" not in st and st["count"] == 10 and st["titles"] == 10
