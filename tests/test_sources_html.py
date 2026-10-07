from datetime import date, datetime
from pathlib import Path

from sources.kamiensk import parse_day
from sources.manual import parse_manual
from sources.mbp import parse_feed
from sources.muzeum import parse_posts
from sources.przedborz import event_links, parse_event
from sources.radomsko_pl import parse_range
from sources.textdates import find_dates, find_time, first_upcoming, looks_like_report

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 7)


def read(rel: str) -> str:
    return (FIX / rel).read_text("utf-8")


def test_radomsko_pl_range_has_year_times_and_all_day_flag():
    events = parse_range(read("radomsko_pl/range.html"), date(2026, 10, 1))
    assert len(events) == 8
    first = events[0]
    assert first.title.startswith("Czytanie performatywne")
    assert first.start == datetime(2026, 10, 9, 18, 0) and first.end == datetime(2026, 10, 9, 19, 0)
    assert first.place == "Radomsko" and first.source == "radomsko_pl"


def test_radomsko_pl_year_rolls_over_in_december():
    html = "".join(
        f'<article class="re-event-item"><div class="re-date-card-day">{d}</div>'
        f'<div class="re-date-card-month">{m}</div><div class="re-date-card-duration">10:00–11:00</div>'
        f'<h4 class="re-event-title">E{d}</h4></article>' for d, m in ((20, "GRU"), (5, "STY"))
    )
    events = parse_range(html, date(2026, 12, 1))
    assert [e.start.date() for e in events] == [date(2026, 12, 20), date(2027, 1, 5)]


def test_kamiensk_empty_day_and_day_with_event():
    assert parse_day(read("kamiensk/kalendarz_dzien.html"), date(2026, 10, 7)) == []
    (ev,) = parse_day(read("kamiensk/kalendarz_dzien_z_wydarzeniem.html"), date(2026, 10, 11))
    assert ev.title == "II Festiwal Muzyki Organowej i Kameralnej w Kamieńsku"
    assert ev.start == datetime(2026, 10, 11, 17, 0) and ev.place == "Kamieńsk" and not ev.all_day
    assert ev.url == "https://kamiensk.pl/kalendarz/11-10-2026/76"


def test_przedborz_links_and_two_event_layouts():
    assert event_links(read("przedborz/home.html")) == ["/kalendarz/2026-10-13/301", "/kalendarz/2026-11-15/299"]
    a = parse_event(read("przedborz/kalendarz_event.html"), "https://x/301")
    assert a.title == "Spotkanie autorskie" and a.venue == "MDK w Przedborzu"
    assert a.start == datetime(2026, 10, 13, 10, 0)
    b = parse_event(read("przedborz/kalendarz_event_2.html"), "https://x/299")
    assert b.title == "Sklep z facetami"
    assert b.venue == "MDK w Przedborzu"  # „Bilety: www.kupbilecik.pl” nie jest miejscem


def test_muzeum_takes_date_from_title_and_skips_posts_without_one():
    posts = [
        {"id": 1, "link": "https://m/1",
         "title": {"rendered": "WYKŁAD &#8222;ZARYS&#8221; &#8211; 11.10.2026 R. (NIEDZIELA)"}},
        {"id": 2, "link": "https://m/2", "title": {"rendered": "Podziękowania z okazji 15-lecia"}},
    ]
    (ev,) = parse_posts(posts, TODAY)
    assert ev.start == datetime(2026, 10, 11) and ev.all_day and ev.confidence == "low"
    assert ev.title == "WYKŁAD „ZARYS”" and ev.category == "edukacja"
    assert parse_posts(posts, date(2026, 10, 12)) == []


def test_mbp_feed_skips_reports_and_finds_announcement():
    events = parse_feed(read("mbp/feed.xml"), TODAY)
    assert [(e.title, e.start) for e in events] == [("Radomszczańska Barwoteka", datetime(2026, 10, 10, 11, 0))]
    assert events[0].category == "biblioteka" and events[0].confidence == "low"


def test_text_date_heuristics():
    assert find_dates("Spotkanie 10 października 2026 r.", TODAY) == [date(2026, 10, 10)]
    assert find_dates("5 stycznia", date(2026, 12, 20)) == [date(2027, 1, 5)]
    assert find_dates("12.11.26", TODAY) == [date(2026, 11, 12)]
    assert find_time("godz. 11:00") and find_time("o godzinie 9.30").hour == 9
    assert find_time("brak godziny") is None
    assert looks_like_report("W piątek odbyło się spotkanie")
    assert first_upcoming("1 października odbyła się lekcja", TODAY) is None


def test_manual_events_validation_and_date_only():
    events = parse_manual({"events": [
        {"title": "Dożynki", "start": "2026-09-05 14:00", "place": "Gomunice", "category": "okolice"},
        {"title": "Jarmark", "start": date(2026, 12, 6), "place": "Przedbórz"},
    ]})
    assert events[0].start == datetime(2026, 9, 5, 14, 0) and not events[0].all_day
    assert events[1].all_day and events[1].source == "manual"
    assert parse_manual(None) == [] and parse_manual({"events": []}) == []
    import pytest
    with pytest.raises(ValueError, match="brak pól"):
        parse_manual({"events": [{"title": "X", "start": "2026-01-01"}]})
