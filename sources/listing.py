"""Cienka nakładka na parser JSON-LD: lista adresów listingów (biletyna, ebilet) z jedną nazwą źródła."""

from __future__ import annotations

from core.models import RawEvent
from sources.base import Fetcher, Source
from sources.jsonld import parse_jsonld_html


class JsonLdListingSource(Source):
    def __init__(self, name: str, urls: list[str]):
        self.name = name
        self.urls = urls

    def fetch(self, fetcher: Fetcher) -> list[RawEvent]:
        events: list[RawEvent] = []
        for url in self.urls:
            events += parse_jsonld_html(fetcher.get(url).text, self.name)
        return events
