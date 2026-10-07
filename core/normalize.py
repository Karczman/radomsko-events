"""Normalizacja tytułów, dat i adresów URL."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date, datetime, time
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


_LIBRARY = re.compile(r"bibliotek|spotkanie autorskie", re.I)
_EDUCATION = re.compile(r"konkurs|warsztat|lekcj|wykład|wyklad|prelekcj", re.I)


def guess_category(title: str) -> str:
    """Zgadywanie kategorii dla źródeł bez własnej (tylko gdy adapter dał `inne`)."""
    if _LIBRARY.search(title):
        return "biblioteka"
    if _EDUCATION.search(title):
        return "edukacja"
    return "inne"


def localize(value: datetime) -> datetime:
    """Naiwny czas traktuje jako lokalny (Europe/Warsaw), aware przelicza na Europe/Warsaw."""
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def make_id(title: str, start: datetime, venue: str | None) -> str:
    key = f"{fold(title)}|{localize(start).isoformat()}|{fold(venue or '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


MAX_URL_LEN = 2000
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def safe_url(url: str | None) -> str | None:
    """Bezpieczny link albo None. Tylko http(s) z hostem, bez danych logowania w adresie i znaków kontrolnych.

    Dane pochodzą z obcych stron: `javascript:`/`data:`/`vbscript:` w `href` na stronie albo w `URL:` w ICS
    to wykonanie kodu u odbiorcy (XSS), więc odrzucamy wszystko poza http/https."""
    if not url or not isinstance(url, str):
        return None
    url = html.unescape(url).strip()
    if len(url) > MAX_URL_LEN or _CONTROL.search(url) or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port  # noqa: F841 - waliduje port (ValueError dla nonsensu)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")  # bez user:hasło@
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))


def clean_text(value: str | None, limit: int) -> str | None:
    """Tekst z obcego źródła: bez znaków kontrolnych i bidi (spoofing), ze ściśniętymi spacjami i limitem długości."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", str(value))).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or None


def clean_url(url: str | None) -> str | None:
    """Bezpieczny link bez parametrów śledzących (utm_*, gclid itd.) i bez fragmentu `#bilety`."""
    safe = safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _TRACKING.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def safe_time(hour, minute) -> time | None:
    """Godzina z tekstu źródła albo None dla nonsensu („25:00”, „17:61”)."""
    try:
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None


def event_end_date(start: datetime, end: datetime | None) -> date:
    """Data, po której wydarzenie znika z wyników (end, a gdy brak, start)."""
    return localize(end or start).date()
