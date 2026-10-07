"""MDK Przedbórz: strona główna linkuje wydarzenia `/kalendarz/RRRR-MM-DD/<id>`, każde ma własną stronę."""

from __future__ import annotations

import re
from datetime import date, datetime, time

from selectolax.lexbor import LexborHTMLParser

from core.models import RawEvent
from core.normalize import clean_title, safe_time
from sources.base import Fetcher, Source, each_safely

BASE = "https://www.mdk.przedborz.pl"
_LINK = re.compile(r'href="(/kalendarz/\d{4}-\d{2}-\d{2}/\d+)"')


def event_links(home_html: str) -> list[str]:
    return sorted(set(_LINK.findall(home_html)))


def parse_event(html_text: str, url: str) -> RawEvent | None:
    tree = LexborHTMLParser(html_text)
    title = tree.css_first("#event-details h3")
    day = tree.css_first("#event-details .news-author strong")
    if not (title and day):
        return None
    try:
        d = date.fromisoformat(day.text(strip=True))
    except ValueError:
        return None
    clock = tree.css_first("#event-details .news-date strong")
    m = re.search(r"(\d{1,2}):(\d{2})", clock.text() if clock else "")
    clock_time = safe_time(m.group(1), m.group(2)) if m else None
    place = None
    for span in tree.css("#event-content span"):  # etykiety „Miejsce:”, „Bilety:” (host serwisu biletowego)
        if span.text(strip=True).startswith("Miejsce:") and (node := span.css_first("strong")):
            place = node
    start = datetime.combine(d, clock_time or time(0, 0))  # noqa: DTZ001
    return RawEvent(
        title=clean_title(title.text(strip=True)), start=start, all_day=clock_time is None,
        venue=place.text(strip=True) if place else "MDK w Przedborzu", place="Przedbórz",
        category="inne", url=url, source="przedborz", confidence="high" if clock_time else "low",
    )


class PrzedborzSource(Source):
    name = "przedborz"

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        today = today or date.today()
        out = []
        def one(path: str) -> RawEvent | None:
            ev = parse_event(fetcher.get(BASE + path).text, BASE + path)
            return ev if ev and ev.start.date() >= today else None
        out += each_safely("przedborz", event_links(fetcher.get(BASE + "/").text), one)
        return out
