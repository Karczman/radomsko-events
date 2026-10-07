"""Wspólny interfejs adapterów i grzeczny klient HTTP (robots.txt, limit 1 żądanie/s na domenę)."""

from __future__ import annotations

import time
import urllib.robotparser
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

import httpx

from core.models import RawEvent

USER_AGENT = "radomsko-events/1.0 (+https://github.com/Karczman/radomsko-events)"


class RobotsDisallowed(Exception):
    """Adres zabroniony przez robots.txt. Nie omijamy blokad."""


class Fetcher:
    def __init__(self, user_agent: str = USER_AGENT, min_interval: float = 1.0,
                 timeout: float = 15.0, retries: int = 3, client: httpx.Client | None = None):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.retries = retries
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True
        )
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _wait(self, host: str) -> None:
        delay = self.min_interval - (time.monotonic() - self._last.get(host, 0.0))
        if delay > 0:
            time.sleep(delay)
        self._last[host] = time.monotonic()

    def _robots_for(self, scheme: str, host: str) -> urllib.robotparser.RobotFileParser | None:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            self._wait(host)
            try:
                resp = self.client.get(f"{scheme}://{host}/robots.txt")
                if resp.status_code == 200 and "text/plain" in resp.headers.get("content-type", "text/plain"):
                    rp.parse(resp.text.splitlines())
                else:
                    rp = None  # brak pliku robots.txt = brak ograniczeń
            except httpx.HTTPError:
                rp = None
            self._robots[host] = rp
        return self._robots[host]

    def get(self, url: str, **kwargs) -> httpx.Response:
        parts = urlsplit(url)
        rp = self._robots_for(parts.scheme, parts.netloc)
        if rp is not None and not rp.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(url)
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._wait(parts.netloc)
            try:
                resp = self.client.get(url, **kwargs)
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    return resp
                last_exc = httpx.HTTPStatusError(str(resp.status_code), request=resp.request, response=resp)
            except httpx.TransportError as exc:
                last_exc = exc
            time.sleep(2**attempt)
        raise last_exc  # type: ignore[misc]


class Source(ABC):
    """Jeden adapter = jedno źródło. `fetch` zwraca RawEvent; błędy propaguje (runner je łapie)."""

    name: str

    @abstractmethod
    def fetch(self, fetcher: Fetcher) -> list[RawEvent]: ...
