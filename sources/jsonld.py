"""Wspólny parser JSON-LD `Event` (schema.org) dla agregatorów: biletyna, ebilet itd."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

from core.models import Category, RawEvent
from core.normalize import clean_title, clean_url

_CATEGORY_BY_TYPE: dict[str, Category] = {
    "MusicEvent": "scena",
    "TheaterEvent": "scena",
    "ComedyEvent": "scena",
    "DanceEvent": "scena",
    "ScreeningEvent": "kino",
    "EducationEvent": "edukacja",
    "ExhibitionEvent": "inne",
}


def extract_jsonld(html: str) -> list:
    """Wyciąga obiekty z `<script type="application/ld+json">`; uszkodzone bloki pomija."""
    out = []
    for node in LexborHTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            out.append(json.loads(node.text(strip=False)))
        except json.JSONDecodeError:
            continue
    return out


def _walk(obj) -> Iterator[dict]:
    if isinstance(obj, list):
        for item in obj:
            yield from _walk(item)
    elif isinstance(obj, dict):
        types = obj.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        if any(t.endswith("Event") for t in types):
            yield obj
            return
        for value in obj.values():
            if isinstance(value, list | dict):
                yield from _walk(value)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _price_text(offers) -> tuple[str | None, str | None]:
    """Zwraca (price_text, ticket_url) z `offers` (obiekt albo lista)."""
    items = offers if isinstance(offers, list) else [offers] if offers else []
    prices, url = [], None
    for o in items:
        if not isinstance(o, dict):
            continue
        url = url or o.get("url")
        for key in ("price", "lowPrice"):
            if o.get(key) not in (None, ""):
                prices.append((float(o[key]), o.get("priceCurrency", "PLN")))
                break
        if o.get("highPrice") not in (None, ""):
            prices.append((float(o["highPrice"]), o.get("priceCurrency", "PLN")))
    if not prices:
        return None, clean_url(url)
    lo, hi = min(p for p, _ in prices), max(p for p, _ in prices)
    cur = prices[0][1].replace("PLN", "zł")
    fmt = lambda x: f"{x:g}"  # noqa: E731
    text = f"{fmt(lo)} {cur}" if lo == hi else f"{fmt(lo)}–{fmt(hi)} {cur}"
    return text, clean_url(url)


def parse_jsonld_events(objects: Iterable, source: str, default_category: Category = "inne") -> list[RawEvent]:
    events: list[RawEvent] = []
    for obj in _walk(list(objects)):
        start = _dt(obj.get("startDate"))
        title = clean_title(str(obj.get("name") or ""))
        if not start or not title:
            continue
        location = obj.get("location")
        location = location if isinstance(location, dict) else {}
        address = location.get("address") if isinstance(location.get("address"), dict) else {}
        types = obj.get("@type")
        type_name = types if isinstance(types, str) else (types or [""])[0]
        price_text, ticket_url = _price_text(obj.get("offers"))
        cancelled = str(obj.get("eventStatus", "")).endswith("EventCancelled")
        events.append(
            RawEvent(
                title=title,
                start=start,
                end=_dt(obj.get("endDate")),
                venue=location.get("name"),
                place=address.get("addressLocality"),
                category=_CATEGORY_BY_TYPE.get(type_name, default_category),
                url=clean_url(obj.get("url")),
                ticket_url=ticket_url,
                price_text=price_text,
                source=source,
                status="cancelled" if cancelled else "active",
            )
        )
    return events


def parse_jsonld_html(html: str, source: str, default_category: Category = "inne") -> list[RawEvent]:
    return parse_jsonld_events(extract_jsonld(html), source, default_category)
