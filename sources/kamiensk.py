"""Gmina Kamieńsk: kalendarz dzień po dniu pod `/kalendarz/DD-MM-RRRR` (tabela `#events-table`)."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from selectolax.lexbor import LexborHTMLParser

from core.models import RawEvent
from core.normalize import clean_title
from sources.base import Fetcher, Source

BASE = "https://kamiensk.pl"
_CATEGORY_ICON = {"ico-inne": "inne"}  # inne ikony: dopisać po zobaczeniu w danych


def parse_day(html_text: str, day: date) -> list[RawEvent]:
    out = []
    for row in LexborHTMLParser(html_text).css("#events-table tbody tr"):
        link = row.css_first("td a")
        if link is None:  # wiersz „Brak wydarzeń”
            continue
        time_node = row.css_first("td.event-time")
        m = re.search(r"(\d{1,2}):(\d{2})", time_node.text() if time_node else "")
        start = datetime.combine(day, time(int(m.group(1)), int(m.group(2))) if m else time(0, 0))  # noqa: DTZ001
        cells = row.css("td")
        venue = cells[1].text(strip=True) if len(cells) > 1 else ""
        icon = row.css_first("td div[class*='ico-']")
        classes = (icon.attributes.get("class") or "") if icon else ""
        out.append(RawEvent(
            title=clean_title(link.text(strip=True)), start=start, all_day=m is None, venue=venue or None,
            place="Kamieńsk", category=next((c for k, c in _CATEGORY_ICON.items() if k in classes), "inne"),
            url=BASE + (link.attributes.get("href") or ""), source="kamiensk",
        ))
    return out


class KamienskSource(Source):
    name = "kamiensk"

    def __init__(self, days_ahead: int = 60):
        self.days_ahead = days_ahead

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        today = today or date.today()
        events: list[RawEvent] = []
        for i in range(self.days_ahead):
            day = today + timedelta(days=i)
            events += parse_day(fetcher.get(f"{BASE}/kalendarz/{day:%d-%m-%Y}").text, day)
        return events
