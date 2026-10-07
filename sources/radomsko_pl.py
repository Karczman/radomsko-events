"""radomsko.pl: widżet „Kalendarz wydarzeń” (Joomla, mod_rdkcal). Odpowiedź to fragment HTML.

Karta daty nie zawiera roku, więc rok wyprowadzamy z zakresu zapytania (miesiące rosnąco).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta

from selectolax.lexbor import LexborHTMLParser

from core.models import RawEvent
from core.normalize import clean_title, safe_time
from sources.base import Fetcher, Source

log = logging.getLogger(__name__)
ENDPOINT = "https://www.radomsko.pl/component/ajax/"
TAG_ID = 1424  # tag kalendarza miejskiego (z konfiguracji widżetu)
_MONTHS = {
    "STY": 1, "LUT": 2, "MAR": 3, "KWI": 4, "MAJ": 5, "CZE": 6,
    "LIP": 7, "SIE": 8, "WRZ": 9, "PAŹ": 10, "LIS": 11, "GRU": 12,
}
_TIMES = re.compile(r"(\d{1,2}):(\d{2})")


def parse_range(html_text: str, range_start: date) -> list[RawEvent]:
    out: list[RawEvent] = []
    year, last_month = range_start.year, range_start.month
    for art in LexborHTMLParser(html_text).css("article.re-event-item"):
        day_node, mon_node = art.css_first(".re-date-card-day"), art.css_first(".re-date-card-month")
        title_node = art.css_first(".re-event-title")
        if not (day_node and mon_node and title_node):
            continue
        month = _MONTHS.get(mon_node.text(strip=True).upper())
        if not month:
            continue
        if month < last_month:  # przejście przez styczeń
            year += 1
        last_month = month
        try:
            day = date(year, month, int(day_node.text(strip=True)))
        except ValueError:
            continue
        dur_node = art.css_first(".re-date-card-duration")
        clocks = [t for t in (safe_time(h, m) for h, m in _TIMES.findall(dur_node.text() if dur_node else "")) if t]
        start = datetime.combine(day, clocks[0] if clocks else time(0, 0))  # noqa: DTZ001
        end = datetime.combine(day, clocks[1]) if len(clocks) > 1 else None  # noqa: DTZ001
        if end and end <= start:
            end = None
        try:
            out.append(RawEvent(
                title=clean_title(title_node.text(strip=True)), start=start, end=end, all_day=not clocks,
                venue=None, place="Radomsko", category="inne", url="https://www.radomsko.pl/",
                source="radomsko_pl", confidence="high" if clocks else "low",
            ))
        except ValueError as exc:  # pydantic: np. pusty tytuł; rok liczymy dalej, więc bez each_safely
            log.warning("radomsko_pl: pominięto rekord (%s)", exc)
    return out


class RadomskoPlSource(Source):
    name = "radomsko_pl"

    def __init__(self, days_ahead: int = 120):
        self.days_ahead = days_ahead

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        today = today or date.today()
        params = {
            "module": "rdkcal", "format": "raw", "method": "getEventsByRange", "start": today.isoformat(),
            "end": (today + timedelta(days=self.days_ahead)).isoformat(), "label": "x", "tag_id": TAG_ID,
        }
        return parse_range(fetcher.get(ENDPOINT, params=params).text, today)
