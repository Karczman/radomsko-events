"""MDK Radomsko: WordPress + Pro Event Calendar (`pec-events`), REST `wp-json/wp/v2/pec-events`.

Terminy w tej wtyczce są rozproszone po kilku polach i `pec_date` NIE wystarcza:

- `pec_date`: pierwszy termin, ale w seriach kinowych bywa datą-śmieciem (1700, 1978, 1988) albo dawno
  minionym pierwszym seansem (np. 25.09 przy seansach 18.10 i 25.10).
- `pec_extra_dates`: lista dodatkowych terminów „2026-10-18 17.00, 2026-10-25 17.00” (czas z kropką,
  zdarzają się literówki jak „2026-11-23.17.00” i wpisy bez godziny). W kinie to jest właściwy repertuar.
- `pec_recurring_frecuency` (1 = dzienny, ...) z `pec_end_date` jako datą końca cyklu.

Brak filtra po dacie wydarzenia w REST, więc pobieramy najnowsze wg `modified` i filtrujemy po stronie
klienta, na podstawie najbliższego terminu ze WSZYSTKICH pól. Treść (`content`) pobieramy tylko dla
kwalifikujących się wpisów, żeby wyciągnąć linki do biletów.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.models import Category, RawEvent
from core.normalize import clean_title, clean_url
from sources.base import Fetcher, Source

log = logging.getLogger(__name__)

BASE = "https://mdkradomsko.pl/wp-json/wp/v2/pec-events"
LIST_FIELDS = (
    "id,link,title,modified,pec_date,pec_end_date,pec_end_time_hh,pec_end_time_mm,pec_all_day,"
    "pec_hide_time,pec_tbc,pec_location,pec_link,pec_events_category,pec_recurring_frecuency,"
    "pec_extra_dates,pec_exceptions,pec_daily_every,pec_daily_working_days"
)
VENUE = "MDK Radomsko"
PLACE = "Radomsko"

# id kategorii pec_events_category -> nasza kategoria (stan z 2026-10-07)
CATEGORY_BY_ID: dict[int, Category] = {
    32: "kino",
    33: "scena", 36: "scena", 35: "scena", 31: "scena",
    37: "edukacja", 108: "edukacja",
    38: "inne", 34: "inne", 77: "inne", 39: "inne", 62: "inne", 76: "inne",
}
_TICKET_HOSTS = ("bilety24.pl", "biletyna.pl", "kulturalnykoneser.pl", "ebilet.pl", "kupbilecik.pl")
_HREF = re.compile(r'href="([^"]+)"')


def _truthy(value) -> bool:
    return str(value).strip().lower() not in ("", "0", "false", "none", "null")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def ticket_urls(content_html: str) -> list[str]:
    """Linki do biletów z treści wpisu (bez parametrów śledzących, bez duplikatów)."""
    found: list[str] = []
    for href in _HREF.findall(content_html or ""):
        cleaned = clean_url(href)
        if cleaned and any(h in cleaned for h in _TICKET_HOSTS) and cleaned not in found:
            found.append(cleaned)
    return found


_TOKEN = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T.]+(\d{1,2})[.:](\d{2}))?")
MIN_YEAR = 2000          # `pec_date` z rokiem 1700/1978/1988 to dane-śmieci, nie termin
MAX_EXPANSION_DAYS = 366


@dataclass(frozen=True)
class Occurrence:
    start: datetime
    timed: bool                       # False = znana tylko data (brak godziny)
    end: datetime | None = None


def _tokens(text: str | None) -> list[tuple[datetime, bool]]:
    """Terminy z tekstu „2026-10-18 17.00, 2026-11-23.17.00, 2021-01-30”. Błędne tokeny pomija."""
    out = []
    for y, m, d, hh, mm in _TOKEN.findall(text or ""):
        try:
            day = datetime(int(y), int(m), int(d))  # noqa: DTZ001 - czas lokalny, strefę dodaje to_event
            timed = bool(hh)
            out.append((day.replace(hour=int(hh), minute=int(mm)) if timed else day, timed))
        except ValueError:
            log.warning("MDK: nieprawidłowy termin %r", f"{y}-{m}-{d} {hh}.{mm}")
    return out


def _recurrence(item: dict, base: datetime, today: date) -> tuple[list[datetime], bool]:
    """Rozwija cykl. Obsługujemy dzienny (zweryfikowany w danych); inne cykle zwracają sam termin bazowy
    i flagę `approximate`. `pec_end_date` w cyklu to data końca cyklu."""
    freq = str(item.get("pec_recurring_frecuency") or "0").strip()
    if freq in ("", "0"):
        return [base], False
    if freq != "1":
        log.warning("MDK: cykl typu %s (wpis %s) nieobsługiwany, tylko termin bazowy", freq, item.get("id"))
        return [base], True
    until = _parse_dt(item.get("pec_end_date"))
    last = min(until.date() if until else base.date(), today + timedelta(days=MAX_EXPANSION_DAYS))
    step = max(int(item.get("pec_daily_every") or 1), 1)
    weekdays_only = _truthy(item.get("pec_daily_working_days"))
    out, day = [], base
    while day.date() <= last:
        if not (weekdays_only and day.weekday() >= 5):
            out.append(day)
        day += timedelta(days=step)
    return out, False


def occurrences(item: dict, today: date) -> tuple[list[Occurrence], bool]:
    """Wszystkie terminy wpisu (baza, cykl, `pec_extra_dates`, minus `pec_exceptions`).
    Zwraca (terminy posortowane, czy_przybliżone)."""
    base = _parse_dt(item.get("pec_date"))
    if base is not None and base.year < MIN_YEAR:
        base = None
    has_end_time = _truthy(item.get("pec_end_time_hh"))
    base_timed = base is not None and not (
        _truthy(item.get("pec_all_day")) or (base.hour == 0 and base.minute == 0 and not has_end_time)
    )
    found: dict[datetime, bool] = {}
    approximate = False
    if base is not None:
        days, approximate = _recurrence(item, base, today)
        for d in days:
            found[d] = base_timed
    for when, timed in _tokens(item.get("pec_extra_dates")):
        found.setdefault(when, timed)
    skipped = {w.date() for w, _ in _tokens(item.get("pec_exceptions"))}
    multiday_end = _parse_dt(item.get("pec_end_date")) if str(item.get("pec_recurring_frecuency") or "0") in ("", "0") \
        else None
    out = []
    for when in sorted(found):
        if when.date() in skipped:
            continue
        end = None
        if has_end_time and found[when]:
            end = when.replace(hour=int(item["pec_end_time_hh"]), minute=int(item.get("pec_end_time_mm") or 0))
            end = end if end > when else None
        elif multiday_end and when == base and multiday_end.date() > when.date():
            end = multiday_end
        out.append(Occurrence(when, found[when], end))
    return out, approximate


def parse_item(item: dict, tickets: list[str] | None = None, today: date | None = None) -> list[RawEvent]:
    """Jeden wpis REST -> RawEvent na każdy termin. `tickets`: linki z treści (opcjonalnie)."""
    title = clean_title(html.unescape((item.get("title") or {}).get("rendered", "")))
    if not title:
        return []
    occs, approximate = occurrences(item, today or date.today())
    cats = item.get("pec_events_category") or []
    category: Category = next((CATEGORY_BY_ID[c] for c in cats if c in CATEGORY_BY_ID), "inne")
    urls = list(tickets or [])
    if item.get("pec_link"):
        cleaned = clean_url(item["pec_link"])
        if cleaned and cleaned not in urls:
            urls.insert(0, cleaned)
    uncertain = approximate or _truthy(item.get("pec_tbc"))
    return [
        RawEvent(
            title=title, start=o.start, end=o.end, all_day=not o.timed,
            venue=(item.get("pec_location") or "").strip() or VENUE, place=PLACE, category=category,
            url=item.get("link"), ticket_url=urls[0] if urls else None, source="mdk",
            confidence="low" if uncertain else "high",
        )
        for o in occs
    ]


def parse_items(items: list[dict], today: date, contents: dict[int, str] | None = None) -> list[RawEvent]:
    out = []
    for item in items:
        for raw in parse_item(item, ticket_urls((contents or {}).get(item["id"], "")), today):
            if (raw.end or raw.start).date() >= today:
                out.append(raw)
    return out


def has_upcoming(item: dict, today: date) -> bool:
    occs, _ = occurrences(item, today)
    return any((o.end or o.start).date() >= today for o in occs)


class MdkSource(Source):
    name = "mdk"
    EMPTY_PAGES_TO_STOP = 2   # dwie kolejne strony bez przyszłych terminów = dalej tylko historia
    MIN_PAGES = 3

    def __init__(self, max_pages: int = 5, per_page: int = 100):
        self.max_pages = max_pages
        self.per_page = per_page

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        today = today or date.today()
        upcoming: list[dict] = []
        empty_streak = 0
        for page in range(1, self.max_pages + 1):
            resp = fetcher.get(
                BASE,
                params={"per_page": self.per_page, "page": page, "orderby": "modified",
                        "order": "desc", "_fields": LIST_FIELDS},
            )
            items = resp.json()
            fresh = [i for i in items if has_upcoming(i, today)]
            upcoming += fresh
            empty_streak = 0 if fresh else empty_streak + 1
            if len(items) < self.per_page or (page >= self.MIN_PAGES and empty_streak >= self.EMPTY_PAGES_TO_STOP):
                break
        contents: dict[int, str] = {}
        ids = [i["id"] for i in upcoming]
        for k in range(0, len(ids), 50):
            chunk = ids[k:k + 50]
            resp = fetcher.get(BASE, params={"include": ",".join(map(str, chunk)),
                                             "per_page": len(chunk), "_fields": "id,content"})
            contents.update({r["id"]: r["content"]["rendered"] for r in resp.json()})
        return parse_items(upcoming, today, contents)
