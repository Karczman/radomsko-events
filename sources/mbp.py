"""MBP Radomsko (Joomla K2): RSS z aktualnościami. Daty w tekście, więc heurystyka i `confidence=low`."""

from __future__ import annotations

import html
import re
from datetime import date

import defusedxml.ElementTree as DefusedET

from core.models import RawEvent
from core.normalize import clean_title
from sources.base import Fetcher, Source, each_safely
from sources.textdates import first_upcoming, looks_like_report

FEED = "https://mbp-radomsko.pl/?format=feed&type=rss"
VENUE = "Miejska Biblioteka Publiczna w Radomsku"


def _plain(fragment: str) -> str:
    text = re.sub(r"\{gallery[^}]*\}.*?\{/gallery\}", " ", fragment, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def parse_feed(xml_text: str, today: date) -> list[RawEvent]:
    # defusedxml: obcy XML nie może użyć encji (XXE, „billion laughs”) przeciw runnerowi
    return each_safely("mbp", DefusedET.fromstring(xml_text).iter("item"), lambda item: _item(item, today))


def _item(item, today: date) -> RawEvent | None:
    title = clean_title(item.findtext("title") or "")
    body = _plain(item.findtext("description") or "")
    if not title or looks_like_report(f"{title} {body[:200]}"):
        return None
    start = first_upcoming(f"{title}. {body}", today)
    if not start:
        return None
    return RawEvent(
        title=title, start=start, all_day=start.hour == 0 and start.minute == 0, venue=VENUE,
        place="Radomsko", category="biblioteka", url=item.findtext("link"), source="mbp", confidence="low",
    )


class MbpSource(Source):
    name = "mbp"

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        return parse_feed(fetcher.get(FEED).text, today or date.today())
