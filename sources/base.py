"""Wspólny interfejs adapterów i grzeczny klient HTTP (robots.txt, limit 1 żądanie/s na domenę)."""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

import httpx

from core.models import RawEvent

log = logging.getLogger(__name__)
USER_AGENT = "radomsko-events/1.0 (+https://github.com/Karczman/radomsko-events)"


class RobotsDisallowed(Exception):
    """Adres zabroniony przez robots.txt. Nie omijamy blokad."""


class ResponseTooLarge(Exception):
    """Odpowiedź większa niż limit (ochrona runnera przed zapchaniem pamięci przez obcy serwer)."""


_DISALLOW_ALL = "disallow-all"  # robots.txt niedostępny (5xx, błąd sieci) = zakaz, zgodnie z RFC 9309


class Fetcher:
    MAX_BYTES = 5 * 1024 * 1024
    MAX_REDIRECTS = 5

    def __init__(self, user_agent: str = USER_AGENT, min_interval: float = 1.0,
                 timeout: float = 15.0, retries: int = 3, client: httpx.Client | None = None):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.retries = retries
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True,
            max_redirects=self.MAX_REDIRECTS,
        )
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | str | None] = {}

    def _wait(self, host: str) -> None:
        delay = self.min_interval - (time.monotonic() - self._last.get(host, 0.0))
        if delay > 0:
            time.sleep(delay)
        self._last[host] = time.monotonic()

    def _robots_for(self, scheme: str, host: str) -> urllib.robotparser.RobotFileParser | str | None:
        """RobotFileParser, None (brak pliku = brak ograniczeń) albo _DISALLOW_ALL (serwer niedostępny)."""
        if host not in self._robots:
            self._wait(host)
            try:
                resp = self._read(f"{scheme}://{host}/robots.txt")
            except (httpx.HTTPError, ResponseTooLarge):
                self._robots[host] = _DISALLOW_ALL
                return _DISALLOW_ALL
            if resp.status_code >= 500 or resp.status_code == 429:
                result: urllib.robotparser.RobotFileParser | str | None = _DISALLOW_ALL
            elif resp.status_code == 200 and "text/plain" in resp.headers.get("content-type", "text/plain"):
                result = urllib.robotparser.RobotFileParser()
                result.parse(resp.text.splitlines())
            else:
                result = None  # 4xx albo HTML zamiast robots.txt = brak pliku = brak ograniczeń
            self._robots[host] = result
        return self._robots[host]

    def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        rp = self._robots_for(parts.scheme, parts.netloc)
        if rp == _DISALLOW_ALL or (rp is not None and not rp.can_fetch(self.user_agent, url)):
            raise RobotsDisallowed(url)

    def _read(self, url: str, **kwargs) -> httpx.Response:
        """GET z limitem rozmiaru: czytamy strumieniowo i przerywamy po przekroczeniu MAX_BYTES."""
        with self.client.stream("GET", url, **kwargs) as resp:
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.MAX_BYTES:
                raise ResponseTooLarge(f"{url}: {declared} B")
            body = bytearray()
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > self.MAX_BYTES:
                    raise ResponseTooLarge(f"{url}: > {self.MAX_BYTES} B")
            # iter_bytes() zwraca już rozpakowane dane: bez content-encoding/length, inaczej podwójne dekodowanie
            headers = [(k, v) for k, v in resp.headers.multi_items()
                       if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
            return httpx.Response(resp.status_code, headers=headers, content=bytes(body),
                                  request=httpx.Request("GET", resp.url))

    def get(self, url: str, **kwargs) -> httpx.Response:
        self._check_robots(url)
        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._wait(host)
            try:
                resp = self._read(url, **kwargs)
                if str(resp.url) != url and urlsplit(str(resp.url)).netloc != host:
                    self._check_robots(str(resp.url))  # przekierowanie na inną domenę: jej robots.txt też
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    return resp
                last_exc = httpx.HTTPStatusError(str(resp.status_code), request=resp.request, response=resp)
            except httpx.TransportError as exc:
                last_exc = exc
            time.sleep(2**attempt)
        raise last_exc  # type: ignore[misc]


def each_safely(source: str, items: Iterable, parse: Callable) -> list:
    """Parsuje rekordy osobno: jeden zepsuty (np. cena „od 50 zł”, godzina „25:00”) nie wyłącza całego źródła.
    Wynik `parse`: RawEvent, lista RawEvent albo None. Błędy logujemy; systemową awarię (0 wyników) łapie
    bezpiecznik i test dymny."""
    out: list = []
    for i, item in enumerate(items):
        try:
            result = parse(item)
        except Exception as exc:  # noqa: BLE001 - celowo szeroko, izolacja pojedynczego rekordu
            log.warning("%s: pominięto rekord %d (%s: %s)", source, i, type(exc).__name__, str(exc)[:200])
            continue
        if result is None:
            continue
        out.extend(result if isinstance(result, list) else [result])
    return out


class Source(ABC):
    """Jeden adapter = jedno źródło. `fetch` zwraca RawEvent; błędy propaguje (runner je łapie)."""

    name: str

    @abstractmethod
    def fetch(self, fetcher: Fetcher) -> list[RawEvent]: ...
