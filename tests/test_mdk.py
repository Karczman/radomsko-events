from datetime import date, datetime

import pytest

from sources.mdk import MdkSource, has_upcoming, occurrences, parse_item, parse_items, ticket_urls

TODAY = date(2026, 10, 7)

CONTENT = (
    '<a href="https://www.bilety24.pl/koncert/1546-x?id=1&amp;utm_source=a">k</a>'
    '<a href="https://biletyna.pl/koncert/Y?eid=2&amp;gclid=zzz#bilety">k</a>'
    '<a href="https://facebook.com/mdk">fb</a>'
    '<a href="https://www.bilety24.pl/koncert/1546-x?id=1">dup</a>'
)


@pytest.fixture
def cinema(fixture_json):
    """Prawdziwe wpisy MDK z 2026-10-07: kino z pec_extra_dates, daty-śmieci, cykle."""
    items = fixture_json("mdk/cinema-and-recurring.json")
    return {i["id"]: i for i in items}


def starts(events):
    return [e.start for e in events]


def item(**kw):
    base = {"id": 1, "title": {"rendered": "Test"}, "pec_date": "2026-11-15 18:00:00", "pec_events_category": [33]}
    return {**base, **kw}


def test_ticket_urls_filters_hosts_tracking_and_duplicates():
    assert ticket_urls(CONTENT) == [
        "https://www.bilety24.pl/koncert/1546-x?id=1",
        "https://biletyna.pl/koncert/Y?eid=2",
    ]


def test_parse_item_basic_fields(fixture_json):
    items = fixture_json("mdk/pec-events.json")
    (ev,) = parse_item(items[0], items[0]["_ticket_urls"], TODAY)
    assert ev.title == "Koncert Sylwestrowy Kasi Dąbrowskiej z zespołem"
    assert ev.start.isoformat() == "2026-12-31T20:00:00"
    assert not ev.all_day
    assert ev.category == "scena"  # kategoria 36 Muzyka
    assert ev.venue == "MDK Radomsko" and ev.place == "Radomsko"
    assert ev.ticket_url.startswith("https://www.bilety24.pl/")
    assert ev.source == "mdk" and ev.confidence == "high"


def test_midnight_without_end_time_means_no_time():
    (ev,) = parse_item(item(pec_date="2026-11-15 00:00:00", pec_all_day="", pec_end_time_hh=""), today=TODAY)
    assert ev.all_day is True


def test_end_time_builds_end():
    (ev,) = parse_item(item(pec_end_time_hh="19", pec_end_time_mm="30"), today=TODAY)
    assert ev.end.isoformat() == "2026-11-15T19:30:00" and not ev.all_day


def test_missing_date_or_title_is_skipped():
    assert parse_item(item(pec_date=""), today=TODAY) == []
    assert parse_item(item(title={"rendered": ""}), today=TODAY) == []


def test_parse_items_drops_past_events(fixture_json):
    items = fixture_json("mdk/pec-events.json")
    assert len(parse_items(items, date(2026, 10, 7))) == 3
    assert len(parse_items(items, date(2027, 1, 1))) == 1  # zostaje tylko 2027-01-30
    assert parse_items(items, date(2027, 2, 1)) == []


# --- regresja: repertuar kina siedzi w pec_extra_dates, a nie w pec_date ---------------------------

def test_regression_future_screenings_come_from_extra_dates_not_from_past_pec_date(cinema):
    """André Rieu: pec_date = 25.09 (minął), seanse 18.10 i 25.10 tylko w pec_extra_dates."""
    events = parse_items([cinema[55374]], TODAY)
    assert starts(events) == [datetime(2026, 10, 18, 17, 0), datetime(2026, 10, 25, 17, 0)]
    assert all(e.category == "kino" and not e.all_day and e.confidence == "high" for e in events)
    assert has_upcoming(cinema[55374], TODAY) and not has_upcoming(cinema[55374], date(2026, 10, 26))


def test_all_extra_dates_become_separate_screenings_with_times(cinema):
    lalka = parse_items([cinema[55517]], TODAY)
    assert datetime(2026, 10, 7, 17, 0) in starts(lalka) or len(lalka) >= 1
    assert all(e.title == "LALKA / 2D" for e in lalka)
    assert starts(lalka) == sorted(starts(lalka)) and len({e.start for e in lalka}) == len(lalka)
    assert all(e.start.date() >= TODAY for e in lalka)


def test_junk_pec_date_is_ignored_and_series_dates_are_used(cinema):
    """WAJDA ma pec_date 1978-05-27 00:00, a seanse w extra_dates."""
    events = parse_items([cinema[52283]], TODAY)
    assert starts(events) == [datetime(2026, 10, 19, 17), datetime(2026, 11, 16, 17), datetime(2026, 12, 7, 17)]
    occs, approx = occurrences(cinema[52283], TODAY)
    assert not approx and all(o.start.year == 2026 for o in occs)  # nic z roku 1978
    fellini = parse_items([cinema[52321]], date(2026, 8, 1))  # 1700-05-29 w pec_date; seanse sierpień-wrzesień 2026
    assert [e.start.date() for e in fellini][:2] == [date(2026, 8, 3), date(2026, 9, 3)]
    assert all(e.start.year == 2026 for e in fellini)
    assert parse_items([cinema[52321]], TODAY) != fellini  # po 7.10 zostają tylko późniejsze seanse


def test_typo_in_extra_date_separator_is_tolerated(cinema):
    """KONWICKI: „2026-11-23.17.00” (kropka zamiast spacji)."""
    events = parse_items([cinema[52251]], TODAY)
    assert datetime(2026, 11, 23, 17, 0) in starts(events)
    assert starts(events) == [datetime(2026, 10, 26, 17), datetime(2026, 11, 23, 17), datetime(2026, 12, 14, 17)]


def test_extra_dates_without_time_are_all_day(cinema):
    events = parse_items([cinema[5751]], date(2021, 1, 1))
    assert [(e.start.date(), e.all_day) for e in events] == [(date(2021, 1, 29), True), (date(2021, 1, 30), True),
                                                              (date(2021, 1, 31), True)]


def test_daily_recurrence_runs_every_day_until_end_date_inclusive(cinema):
    """KINO FAMILIJNE / WAKACJE: cykl dzienny 2025-07-07..2025-08-03 (bez ograniczenia do dni roboczych)."""
    events = parse_items([cinema[47164]], date(2025, 7, 1))
    assert events[0].start == datetime(2025, 7, 7, 12, 0) and events[-1].start == datetime(2025, 8, 3, 12, 0)
    assert len(events) == 28 and any(e.start.weekday() >= 5 for e in events)
    assert all(e.confidence == "high" and e.category == "kino" for e in events)
    assert parse_items([cinema[47164]], TODAY) == []  # po zakończeniu cyklu nic nie zostaje


def test_daily_recurrence_working_days_flag_and_step_are_respected():
    base = item(pec_date="2026-11-14 10:00:00", pec_recurring_frecuency="1", pec_end_date="2026-11-20",
                pec_daily_working_days="1", pec_daily_every="1")  # sobota..piątek
    assert [e.start.day for e in parse_item(base, today=TODAY)] == [16, 17, 18, 19, 20]
    every_other = {**base, "pec_daily_working_days": "", "pec_daily_every": "2"}
    assert [e.start.day for e in parse_item(every_other, today=TODAY)] == [14, 16, 18, 20]


def test_daily_recurrence_every_day_range(cinema):
    events = parse_items([cinema[29391]], date(2023, 7, 1))  # 10-14.07, dni robocze (pn-pt)
    assert [e.start.day for e in events] == [10, 11, 12, 13, 14]


def test_unsupported_recurrence_is_flagged_low_confidence(cinema):
    occs, approx = occurrences(cinema[347], date(2020, 6, 1))  # cykl miesięczny
    assert approx and len(occs) == 1
    (ev,) = parse_items([cinema[347]], date(2020, 6, 1))
    assert ev.confidence == "low"


def test_exceptions_and_invalid_tokens_are_handled():
    it = item(pec_extra_dates="2026-11-16 18.00, 2026-13-45 10.00, nonsens, 2026-11-17 18.00",
              pec_exceptions="2026-11-16")
    assert starts(parse_item(it, today=TODAY)) == [datetime(2026, 11, 15, 18), datetime(2026, 11, 17, 18)]


def test_tbc_flag_lowers_confidence():
    (ev,) = parse_item(item(pec_tbc="1"), today=TODAY)
    assert ev.confidence == "low"


# --- pobieranie: stronicowanie decyduje o najbliższym terminie ze wszystkich pól --------------------

class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class PagedFetcher:
    def __init__(self, pages, contents=None):
        self.pages, self.contents, self.requested = pages, contents or {}, []

    def get(self, url, params=None, **kw):
        params = params or {}
        if "include" in params:
            ids = [int(i) for i in params["include"].split(",")]
            return Resp([{"id": i, "content": {"rendered": ""}} for i in ids])
        self.requested.append(params["page"])
        return Resp(self.pages.get(params["page"], []))


def test_fetch_includes_old_entry_with_future_extra_dates_found_on_page_two(cinema):
    """Wpis o dawnym `modified` i przyszłych extra_dates (tak jak Rieu/Wajda) musi trafić do wyników."""
    plain = item(id=7, pec_date="2024-01-01 10:00:00")  # historia, bez przyszłości
    pages = {1: [plain] * 3 + [item(id=8)], 2: [cinema[55374]], 3: [plain], 4: [plain], 5: [plain]}
    events = MdkSource(per_page=4).fetch(PagedFetcher(pages), TODAY)
    assert {e.start for e in events} >= {datetime(2026, 10, 18, 17), datetime(2026, 10, 25, 17)}


def test_fetch_stops_after_two_consecutive_empty_pages_but_not_before_page_three():
    plain = item(id=7, pec_date="2024-01-01 10:00:00")
    full = {p: [plain] * 4 for p in range(1, 8)}
    fetcher = PagedFetcher(full)
    MdkSource(max_pages=7, per_page=4).fetch(fetcher, TODAY)
    assert fetcher.requested == [1, 2, 3]  # min. 3 strony, potem 2 puste z rzędu = koniec
    fresh_late = {**full, 3: [item(id=9)] + [plain] * 3}
    fetcher = PagedFetcher(fresh_late)
    MdkSource(max_pages=7, per_page=4).fetch(fetcher, TODAY)
    assert fetcher.requested == [1, 2, 3, 4, 5]  # świeży wpis na stronie 3 przedłuża pobieranie
