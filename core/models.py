"""Modele danych: RawEvent (z adaptera) i Event (po normalizacji, zapisywany do events.json)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.normalize import clean_text, safe_url

Category = Literal["scena", "kino", "biblioteka", "edukacja", "okolice", "inne"]
Status = Literal["active", "cancelled"]
Confidence = Literal["high", "low"]

# Limity długości tekstów z obcych źródeł (ochrona przed śmieciami i nadużyciami, np. 1 MB „tytułu”).
TEXT_LIMITS = {"title": 300, "venue": 200, "place": 100, "price_text": 100}
_TIME = r"^\d{2}:\d{2}$"


class _Sanitized(BaseModel):
    """Sanityzacja w modelu, więc żaden adapter (także przyszły) nie przepchnie niebezpiecznych danych."""

    @field_validator("url", "ticket_url", mode="before", check_fields=False)
    @classmethod
    def _safe_links(cls, v):
        return safe_url(v)

    @field_validator("title", "venue", "place", "price_text", mode="before", check_fields=False)
    @classmethod
    def _clean_texts(cls, v, info):
        cleaned = clean_text(v, TEXT_LIMITS[info.field_name])
        if info.field_name == "title" and not cleaned:
            raise ValueError("pusty tytuł")
        return cleaned

    @field_validator("times", mode="after", check_fields=False)
    @classmethod
    def _times(cls, v):
        import re
        return [t for t in v if re.match(_TIME, t)][:50]


class RawEvent(_Sanitized):
    """Wydarzenie tak, jak zwraca je adapter. Daty mogą być naiwne (czas lokalny Europe/Warsaw)."""

    title: str
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    venue: str | None = None
    place: str | None = None
    category: Category = "inne"
    url: str | None = None
    ticket_url: str | None = None
    price_text: str | None = None
    times: list[str] = Field(default_factory=list)
    source: str
    confidence: Confidence = "high"
    status: Status = "active"


class Event(_Sanitized):
    """Wydarzenie w `events.json`. Przechowujemy tylko fakty (bez opisów i obrazów)."""

    id: str
    title: str
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    venue: str | None = None
    place: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_km: float | None = None
    category: Category = "inne"
    url: str | None = None
    ticket_url: str | None = None
    price_text: str | None = None
    times: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)  # dni seansów (RRRR-MM-DD) dla zwiniętych pozycji kina
    source: str
    sources: list[str] = Field(default_factory=list)
    first_seen: str
    last_seen: str
    status: Status = "active"
    confidence: Confidence = "high"
