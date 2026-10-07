"""Heurystyczne wyciąganie dat z tekstu (Muzeum, MBP). Wynik zawsze z `confidence=low`."""

from __future__ import annotations

import re
from datetime import date, datetime, time

_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6, "lipca": 7,
    "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10, "pazdziernika": 10,
    "listopada": 11, "grudnia": 12,
}
_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2}|\d{2})\b")
_WORDY = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")(?:\s+(20\d{2}))?", re.I)
_TIME = re.compile(r"(?:godz\.?|o godzinie|o godz\.?|g\.)\s*(\d{1,2})[:.](\d{2})", re.I)
_PAST_HINT = re.compile(
    r"\b(odbył[aoy]?\s+się|odbyło\s+się|odbyła\s+się|zakończył[aoy]?\s+się|relacja|podsumowanie)\b", re.I
)


def looks_like_report(text: str) -> bool:
    """Relacja z wydarzenia, które już się odbyło (nie chcemy jej jako zapowiedzi)."""
    return bool(_PAST_HINT.search(text))


def find_dates(text: str, today: date) -> list[date]:
    """Daty z tekstu (DD.MM.RRRR oraz „12 października [2026]”). Rok domyślnie bieżący lub następny."""
    found: list[date] = []
    for d, m, y in _NUMERIC.findall(text):
        year = int(y) + (2000 if len(y) == 2 else 0)
        try:
            found.append(date(year, int(m), int(d)))
        except ValueError:
            continue
    for d, mon, y in _WORDY.findall(text):
        month = _MONTHS[mon.lower()]
        year = int(y) if y else today.year
        try:
            cand = date(year, month, int(d))
        except ValueError:
            continue
        if not y and (today - cand).days > 180:  # „5 stycznia” widziane w grudniu = przyszły rok
            cand = date(year + 1, month, int(d))
        found.append(cand)
    return found


def find_time(text: str) -> time | None:
    m = _TIME.search(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return time(h, mi) if h < 24 and mi < 60 else None


def first_upcoming(text: str, today: date) -> datetime | None:
    """Najbliższa data >= dziś z tekstu z godziną (jeśli jest). Brak = None."""
    dates = sorted(d for d in set(find_dates(text, today)) if d >= today)
    if not dates:
        return None
    t = find_time(text)
    return datetime.combine(dates[0], t or time(0, 0))  # noqa: DTZ001 - czas lokalny, strefę dodaje to_event
