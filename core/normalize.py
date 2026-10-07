"""Normalizacja tytułów, dat i adresów URL."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")

# Prefiks z datą, np. „31.12.2026r.- ”, „07.11.26 r. – ”, „15-01-2027- ”.
_DATE_PREFIX = re.compile(r"^\s*\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}\s*(?:r\.?)?\s*[–—\-:]*\s*", re.I)
_NOISE_WORDS = re.compile(r"\b(bilety|bilet|koncert|spektakl|spektakle)\b", re.I)
_TRACKING = re.compile(r"^(utm_.*|gclid|gbraid|wbraid|gad_.*|srsltid|fbclid|creative|device|placement)$", re.I)


def clean_title(raw: str) -> str:
    """Odkodowuje encje HTML, usuwa prefiks z datą i nadmiarowe spacje."""
    text = html.unescape(raw)
    text = _DATE_PREFIX.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Tytuł do porównań: małe litery, bez diakrytyków i słów-szumu, bez interpunkcji."""
    text = text.lower().replace("ł", "l")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NOISE_WORDS.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def localize(value: datetime) -> datetime:
    """Naiwny czas traktuje jako lokalny (Europe/Warsaw), aware przelicza na Europe/Warsaw."""
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def make_id(title: str, start: datetime, venue: str | None) -> str:
    key = f"{fold(title)}|{localize(start).isoformat()}|{fold(venue or '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def clean_url(url: str | None) -> str | None:
    """Usuwa parametry śledzące (utm_*, gclid itd.) i fragment `#bilety`."""
    if not url:
        return None
    parts = urlsplit(html.unescape(url.strip()))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _TRACKING.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def event_end_date(start: datetime, end: datetime | None) -> date:
    """Data, po której wydarzenie znika z wyników (end, a gdy brak, start)."""
    return localize(end or start).date()
