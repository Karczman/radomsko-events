"""Ręczne wydarzenia z `data/manual_events.yaml`. Źródło o najwyższym zaufaniu (nadpisuje automaty)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from core.models import RawEvent
from core.normalize import clean_url
from sources.base import Source

_FIELDS = ("title", "start", "venue", "place", "url", "ticket_url", "price_text")


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "year"):  # date
        return datetime(value.year, value.month, value.day)  # noqa: DTZ001
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError(f"nieprawidłowa data: {value!r} (oczekiwano RRRR-MM-DD [GG:MM])")


def parse_manual(data: dict | None) -> list[RawEvent]:
    out = []
    for i, item in enumerate((data or {}).get("events") or []):
        missing = [f for f in ("title", "start", "place") if not item.get(f)]
        if missing:
            raise ValueError(f"manual_events.yaml, pozycja {i + 1}: brak pól {missing}")
        start = _as_datetime(item["start"])
        end = _as_datetime(item["end"]) if item.get("end") else None
        raw_start = item["start"]
        date_only = (isinstance(raw_start, str) and len(raw_start.strip()) <= 10) or (
            hasattr(raw_start, "year") and not isinstance(raw_start, datetime)
        )
        out.append(RawEvent(
            title=str(item["title"]).strip(), start=start, end=end, all_day=bool(item.get("all_day", date_only)),
            venue=item.get("venue"), place=item["place"], category=item.get("category", "inne"),
            url=item.get("url"), ticket_url=clean_url(item.get("ticket_url")), price_text=item.get("price_text"),
            source="manual",
        ))
    return out


class ManualSource(Source):
    name = "manual"

    def __init__(self, path: Path):
        self.path = path

    def fetch(self, fetcher=None) -> list[RawEvent]:
        if not self.path.exists():
            return []
        return parse_manual(yaml.safe_load(self.path.read_text("utf-8")))
