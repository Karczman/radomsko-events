from datetime import datetime

from core.dedupe import dedupe
from core.models import Event
from core.normalize import TZ
from core.rollup_cinema import rollup_cinema


def ev(title, day, hour, source, *, minute=0, all_day=False, place="Radomsko", category="scena", **kw):
    start = datetime(2026, 11, day, hour, minute, tzinfo=TZ)
    return Event(
        id=f"{source}-{title}-{day}-{hour}", title=title, start=start, all_day=all_day, place=place,
        category=category, source=source, sources=[source], first_seen="2026-10-07", last_seen="2026-10-07", **kw,
    )


def test_merge_prefers_organizer_and_fills_gaps_from_ticket_site():
    mdk = ev("Kabaret Smile", 7, 0, "mdk", all_day=True)
    bil = ev("Kabaret Smile - CONTRA", 7, 16, "biletyna", ticket_url="https://t/1", price_text="138 zł", venue="MDK")
    (merged,) = dedupe([bil, mdk])
    assert merged.source == "mdk" and merged.sources == ["mdk", "biletyna"]
    assert merged.ticket_url == "https://t/1" and merged.price_text == "138 zł" and merged.venue == "MDK"
    assert not merged.all_day and merged.start.hour == 16  # godzina z agregatora zamiast „00:00” MDK


def test_manual_beats_everything():
    m = ev("Koncert Jana", 7, 18, "manual", price_text="20 zł")
    a = ev("Koncert Jana", 7, 18, "biletyna", price_text="30 zł")
    (merged,) = dedupe([a, m])
    assert merged.source == "manual" and merged.price_text == "20 zł"


def test_different_day_place_or_distant_time_are_not_merged():
    base = ev("Koncert Jana", 7, 18, "mdk")
    assert len(dedupe([base, ev("Koncert Jana", 8, 18, "biletyna")])) == 2
    assert len(dedupe([base, ev("Koncert Jana", 7, 18, "biletyna", place="Kamieńsk")])) == 2
    assert len(dedupe([base, ev("Koncert Jana", 7, 22, "biletyna")])) == 2


def test_same_minute_and_shared_distinctive_word_merges_despite_different_titles():
    a = ev("MATKA / 3xRóżewicz", 12, 18, "mdk", venue="MDK Radomsko")
    b = ev('Teatr Polonia "MATKA"', 12, 18, "radomsko_pl")
    assert len(dedupe([a, b])) == 1
    generic = ev("Kabaret Nowaki", 12, 18, "radomsko_pl")  # tylko słowo ogólne wspólne z „Kabaret Smile”
    assert len(dedupe([ev("Kabaret Smile", 12, 18, "mdk"), generic])) == 2
    other_venue = ev("Teatr Polonia MATKA", 12, 18, "radomsko_pl", venue="Inna sala")
    assert len(dedupe([a, other_venue])) == 2


def test_same_source_events_never_merge():
    a = ev("Spektakl", 7, 16, "biletyna")
    b = ev("Spektakl", 7, 19, "biletyna")
    assert len(dedupe([a, b])) == 2


def test_threshold_is_configurable():
    a, b = ev("Gala Operetkowa 2026", 7, 18, "mdk"), ev("Gala Operetkowa 2027", 7, 19, "biletyna")  # podobieństwo 95
    assert len(dedupe([a, b], threshold=90)) == 1
    assert len(dedupe([a, b], threshold=99)) == 2


def film(day, hour, **kw):
    return ev("Film Testowy", day, hour, "mdk", category="kino", **kw)


def test_cinema_rollup_one_entry_per_film_with_times():
    out = rollup_cinema([film(7, 17), film(7, 19, minute=30), film(8, 17), ev("Koncert", 7, 20, "mdk")])
    kino = [e for e in out if e.category == "kino"]
    assert len(kino) == 1 and len(out) == 2
    k = kino[0]
    assert k.start.day == 7 and k.end.day == 8
    assert k.times == ["17:00", "19:30"]
    assert k.dates == ["2026-11-07", "2026-11-08"]


def test_cinema_rollup_id_stable_when_first_screening_expires():
    before = rollup_cinema([film(7, 17), film(8, 17), film(9, 17)])[0].id
    after = rollup_cinema([film(8, 17), film(9, 17)])[0].id
    assert before == after


def test_cinema_single_day_has_no_end_and_returns_split_runs():
    single = rollup_cinema([film(7, 17), film(7, 20)])[0]
    assert single.end is None and single.times == ["17:00", "20:00"] and single.dates == []
    runs = [e for e in rollup_cinema([film(1, 17), film(28, 17)]) if e.category == "kino"]
    assert len(runs) == 2 and runs[0].id != runs[1].id
