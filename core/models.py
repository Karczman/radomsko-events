"""Modele danych: RawEvent (z adaptera) i Event (po normalizacji, zapisywany do events.json)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["scena", "kino", "biblioteka", "edukacja", "okolice", "inne"]
Status = Literal["active", "cancelled"]
Confidence = Literal["high", "low"]


class RawEvent(BaseModel):
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


class Event(BaseModel):
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
    source: str
    sources: list[str] = Field(default_factory=list)
    first_seen: str
    last_seen: str
    status: Status = "active"
    confidence: Confidence = "high"
