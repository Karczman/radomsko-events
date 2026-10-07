"""Bezpiecznik: gdy źródło zwraca 0 wydarzeń albo ponad 50% mniej niż poprzednio (lub rzuca wyjątek),
używamy ostatnich dobrych danych tego źródła z `data/source_cache/`, oznaczamy źródło jako `stale`
i wysyłamy alert (core/digest.py). Cache zawiera surowe wydarzenia z adaptera (bez znaczników czasu),
więc zmienia się w git tylko razem ze źródłem.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core.models import RawEvent
from core.normalize import event_end_date, localize

MIN_PREVIOUS = 5   # poniżej tylu wydarzeń spadek do zera bywa normalny (np. jedno wydarzenie się odbyło)
DROP_RATIO = 0.5


def trip_reason(previous: dict | None, count: int, min_previous: int = MIN_PREVIOUS,
                ratio: float = DROP_RATIO) -> str | None:
    """Powód zadziałania bezpiecznika albo None. `previous` = wpis źródła z poprzedniego status.json.
    `count` to liczba RÓŻNYCH TYTUŁÓW (nie terminów), bo seanse i terminy wygasają codziennie i dawałyby
    fałszywe alarmy; starsze statusy bez `titles` porównujemy po `count`."""
    if not previous or previous.get("titles", previous.get("count")) is None:
        return None
    before = previous.get("titles", previous.get("count"))
    if before < min_previous:
        return None
    if count == 0:
        return f"0 wydarzeń (poprzednio {before} tytułów)"
    if count < before * ratio:
        return f"{count} tytułów zamiast {before}"
    return None


def cache_path(directory: Path, name: str) -> Path:
    return directory / f"{name}.json"


def save_cache(directory: Path, name: str, raws: list[RawEvent]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = [r.model_dump(mode="json", exclude_none=True) for r in raws]
    cache_path(directory, name).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")


def load_cache(directory: Path, name: str, today: date) -> list[RawEvent] | None:
    """Ostatnie dobre dane źródła bez wydarzeń z przeszłości. Brak pliku = None."""
    path = cache_path(directory, name)
    if not path.exists():
        return None
    raws = [RawEvent.model_validate(r) for r in json.loads(path.read_text("utf-8"))]
    return [r for r in raws if event_end_date(localize(r.start), localize(r.end) if r.end else None) >= today]
