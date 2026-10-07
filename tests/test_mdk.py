from datetime import date

from sources.mdk import parse_item, parse_items, ticket_urls

CONTENT = (
    '<a href="https://www.bilety24.pl/koncert/1546-x?id=1&amp;utm_source=a">k</a>'
    '<a href="https://biletyna.pl/koncert/Y?eid=2&amp;gclid=zzz#bilety">k</a>'
    '<a href="https://facebook.com/mdk">fb</a>'
    '<a href="https://www.bilety24.pl/koncert/1546-x?id=1">dup</a>'
)


def test_ticket_urls_filters_hosts_tracking_and_duplicates():
    assert ticket_urls(CONTENT) == [
        "https://www.bilety24.pl/koncert/1546-x?id=1",
        "https://biletyna.pl/koncert/Y?eid=2",
    ]


def test_parse_item_basic_fields(fixture_json):
    items = fixture_json("mdk/pec-events.json")
    ev = parse_item(items[0], items[0]["_ticket_urls"])
    assert ev.title == "Koncert Sylwestrowy Kasi Dąbrowskiej z zespołem"
    assert ev.start.isoformat() == "2026-12-31T20:00:00"
    assert not ev.all_day
    assert ev.category == "scena"  # kategoria 36 Muzyka
    assert ev.venue == "MDK Radomsko" and ev.place == "Radomsko"
    assert ev.ticket_url.startswith("https://www.bilety24.pl/")
    assert ev.source == "mdk" and ev.confidence == "high"


def test_midnight_without_end_time_means_no_time():
    item = {"id": 1, "title": {"rendered": "Test"}, "pec_date": "2026-11-15 00:00:00",
            "pec_all_day": "", "pec_end_time_hh": "", "pec_events_category": [39]}
    assert parse_item(item).all_day is True


def test_end_time_builds_end(fixture_json):
    item = {"id": 1, "title": {"rendered": "Test"}, "pec_date": "2026-11-15 18:00:00",
            "pec_end_time_hh": "19", "pec_end_time_mm": "30", "pec_events_category": [33]}
    ev = parse_item(item)
    assert ev.end.isoformat() == "2026-11-15T19:30:00" and not ev.all_day


def test_cinema_category_and_recurring_flag():
    item = {"id": 2, "title": {"rendered": "Film"}, "pec_date": "2026-11-15 17:00:00",
            "pec_events_category": [32], "pec_recurring_frecuency": "1"}
    ev = parse_item(item)
    assert ev.category == "kino" and ev.confidence == "low"


def test_parse_items_drops_past_events(fixture_json):
    items = fixture_json("mdk/pec-events.json")
    assert len(parse_items(items, date(2026, 10, 7))) == 3
    assert len(parse_items(items, date(2027, 1, 1))) == 1  # zostaje tylko 2027-01-30
    assert parse_items(items, date(2027, 2, 1)) == []


def test_missing_date_or_title_is_skipped():
    assert parse_item({"id": 3, "title": {"rendered": "X"}, "pec_date": ""}) is None
    assert parse_item({"id": 4, "title": {"rendered": ""}, "pec_date": "2026-11-15 18:00:00"}) is None
