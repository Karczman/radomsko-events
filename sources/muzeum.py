"""Muzeum Regionalne w Radomsku: WordPress, wydarzenia jako zwykłe posty z datą w tytule (low confidence)."""

from __future__ import annotations

import html
import re
from datetime import date

from core.models import Category, RawEvent
from core.normalize import clean_title
from sources.base import Fetcher, Source, each_safely
from sources.textdates import first_upcoming, looks_like_report

BASE = "https://muzeum.radomsko.pl/wp-json/wp/v2/posts"
VENUE = "Muzeum Regionalne w Radomsku"
_EDU = ("wykład", "wyklad", "lekcja", "warsztat", "prelekcja", "spotkanie")


def parse_posts(posts: list[dict], today: date) -> list[RawEvent]:
    return each_safely("muzeum", posts, lambda post: _post(post, today))


def _post(post: dict, today: date) -> RawEvent | None:
    title = html.unescape(post["title"]["rendered"])
    if looks_like_report(title):
        return None
    start = first_upcoming(title, today)  # data tylko z tytułu: treść postów jest zbyt szumna
    if not start:
        return None
    category: Category = "edukacja" if any(w in title.lower() for w in _EDU) else "inne"
    return RawEvent(
        title=_strip_date_suffix(clean_title(title)), start=start, all_day=start.hour == 0 and start.minute == 0,
        venue=VENUE, place="Radomsko", category=category, url=post.get("link"), source="muzeum", confidence="low",
    )


def _strip_date_suffix(title: str) -> str:
    """„… – 11.10.2026 R. (NIEDZIELA)” -> „…”. Zostawia resztę tytułu."""
    return re.sub(r"\s*[–—-]\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}\s*r?\.?\s*(\([^)]*\))?\s*$", "", title, flags=re.I).strip()


class MuzeumSource(Source):
    name = "muzeum"

    def fetch(self, fetcher: Fetcher, today: date | None = None) -> list[RawEvent]:
        resp = fetcher.get(BASE, params={"per_page": 30, "_fields": "id,date,link,title"})
        return parse_posts(resp.json(), today or date.today())
