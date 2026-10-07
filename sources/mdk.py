"""MDK Radomsko: WordPress + Pro Event Calendar (`pec-events`), REST `wp-json/wp/v2/pec-events`.

Brak filtra po `pec_date` w REST, więc pobieramy najnowsze wg `modified` i filtrujemy po stronie
klienta. Próbka z 2026-10-07: strona 1 miała 26 przyszłych wydarzeń, strona 2 jedno, dalsze zero.
Treść (`content`) pobieramy tylko dla przyszłych wpisów, żeby wyciągnąć linki do biletów.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime

from core.models import Category, RawEvent
from core.normalize import clean_title, clean_url
from sources.base import Fetcher, Source

log = logging.getLogger(__name__)

BASE = "https://mdkradomsko.pl/wp-json/wp/v2/pec-events"
LIST_FIELDS = (
    "id,link,title,modified,pec_date,pec_end_date,pec_end_time_hh,pec_end_time_mm,pec_all_day,"
    "pec_hide_time,pec_tbc,pec_location,pec_link,pec_events_category,pec_recurring_frecuency,"
    "pec_extra_dates"
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


def parse_item(item: dict, tickets: list[str] | None = None) -> RawEvent | None:
    """Jeden wpis REST -> RawEvent. `tickets`: linki z treści (opcjonalnie)."""
    start = _parse_dt(item.get("pec_date"))
    title = clean_title(html.unescape((item.get("title") or {}).get("rendered", "")))
    if not start or not title:
        return None
    # Godzina 00:00:00 oznacza w MDK najczęściej „brak godziny”, a nie północ.
    all_day = _truthy(item.get("pec_all_day")) or (
        start.hour == 0 and start.minute == 0 and not _truthy(item.get("pec_end_time_hh"))
    )
    end = _parse_dt(item.get("pec_end_date"))
    if end is None and _truthy(item.get("pec_end_time_hh")) and not all_day:
        hh, mm = int(item["pec_end_time_hh"]), int(item.get("pec_end_time_mm") or 0)
        end = start.replace(hour=hh, minute=mm)
        if end < start:
            end = None
    recurring = _truthy(item.get("pec_recurring_frecuency")) or _truthy(item.get("pec_extra_dates"))
    if recurring:
        log.warning("MDK: wydarzenie cykliczne %s, emitujemy tylko termin bazowy", item.get("id"))
    cats = item.get("pec_events_category") or []
    category: Category = next((CATEGORY_BY_ID[c] for c in cats if c in CATEGORY_BY_ID), "inne")
    urls = list(tickets or [])
    if item.get("pec_link"):
        cleaned = clean_url(item["pec_link"])
        if cleaned and cleaned not in urls:
            urls.insert(0, cleaned)
    return RawEvent(
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        venue=(item.get("pec_location") or "").strip() or VENUE,
        place=PLACE,
        category=category,
        url=item.get("link"),
        ticket_url=urls[0] if urls else None,
        source="mdk",
        confidence="low" if recurring else "high",
    )


def parse_items(items: list[dict], today: date, contents: dict[int, str] | None = None) -> list[RawEvent]:
    out = []
    for item in items:
        raw = parse_item(item, ticket_urls((contents or {}).get(item["id"], "")))
        if raw and (raw.end or raw.start).date() >= today:
            out.append(raw)
    return out


class MdkSource(Source):
    name = "mdk"

    def __init__(self, max_pages: int = 3, per_page: int = 100):
        self.max_pages = max_pages
        self.per_page = per_page

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        today = today or date.today()
        upcoming: list[dict] = []
        for page in range(1, self.max_pages + 1):
            resp = fetcher.get(
                BASE,
                params={"per_page": self.per_page, "page": page, "orderby": "modified",
                        "order": "desc", "_fields": LIST_FIELDS},
            )
            items = resp.json()
            fresh = [i for i in items if (_parse_dt(i.get("pec_date")) or datetime.min).date() >= today
                     or (_parse_dt(i.get("pec_end_date")) or datetime.min).date() >= today]
            upcoming += fresh
            if page >= 2 and not fresh:  # dalsze strony to historia
                break
            if len(items) < self.per_page:
                break
        contents: dict[int, str] = {}
        ids = [i["id"] for i in upcoming]
        for k in range(0, len(ids), 50):
            chunk = ids[k:k + 50]
            resp = fetcher.get(BASE, params={"include": ",".join(map(str, chunk)),
                                             "per_page": len(chunk), "_fields": "id,content"})
            contents.update({r["id"]: r["content"]["rendered"] for r in resp.json()})
        return parse_items(upcoming, today, contents)
