"""Test dymny na żywo: lekkie zapytanie do każdego źródła i sprawdzenie, że parser nadal coś rozpoznaje.

Sprawdza strukturę (np. czy odpowiedź ma oczekiwany kontener), a nie liczbę wydarzeń tam, gdzie pusta
lista jest normalna (Kamieńsk, Przedbórz). Kod wyjścia != 0, gdy cokolwiek się zepsuło; z `--notify`
wysyła też alert ntfy. Uruchamiany co tydzień przez `.github/workflows/smoke.yml`.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import yaml

from core.digest import Message, send
from sources import kamiensk, mbp, mdk, muzeum, przedborz, radomsko_pl
from sources.base import USER_AGENT, Fetcher
from sources.jsonld import extract_jsonld, parse_jsonld_html

log = logging.getLogger("smoke")
ROOT = Path(__file__).resolve().parent.parent
Check = Callable[[Fetcher, date], str]  # zwraca opis sukcesu albo rzuca AssertionError / wyjątek sieciowy


def check_mdk(f: Fetcher, today: date) -> str:
    events = mdk.MdkSource(max_pages=1).fetch(f, today)
    assert events, "REST pec-events nie zwrócił przyszłych wydarzeń"
    return f"{len(events)} wydarzeń na stronie 1"


def check_radomsko_pl(f: Fetcher, today: date) -> str:
    resp = f.get(radomsko_pl.ENDPOINT, params={
        "module": "rdkcal", "format": "raw", "method": "getEventsByRange", "start": today.isoformat(),
        "end": (today + timedelta(days=30)).isoformat(), "label": "x", "tag_id": radomsko_pl.TAG_ID})
    assert "re-events-list" in resp.text, "brak kontenera .re-events-list w odpowiedzi widżetu"
    return f"{len(radomsko_pl.parse_range(resp.text, today))} wydarzeń w 30 dni"


def check_muzeum(f: Fetcher, today: date) -> str:
    posts = f.get(muzeum.BASE, params={"per_page": 5, "_fields": "id,date,link,title"}).json()
    assert isinstance(posts, list) and posts and "title" in posts[0], "REST posts bez oczekiwanej struktury"
    return f"{len(posts)} postów"


def check_mbp(f: Fetcher, today: date) -> str:
    xml = f.get(mbp.FEED).text
    assert "<item>" in xml, "RSS bez elementów <item>"
    mbp.parse_feed(xml, today)  # parser nie może się wywrócić
    return "RSS ok"


def check_kamiensk(f: Fetcher, today: date) -> str:
    html = f.get(f"{kamiensk.BASE}/kalendarz/{today:%d-%m-%Y}").text
    assert "events-table" in html, "brak tabeli #events-table"
    return f"{len(kamiensk.parse_day(html, today))} wydarzeń dziś"


def check_przedborz(f: Fetcher, today: date) -> str:
    html = f.get(przedborz.BASE + "/").text
    links = przedborz.event_links(html)
    assert links or "kalendarz" in html.lower(), "strona główna bez kalendarza"
    if links:
        assert przedborz.parse_event(f.get(przedborz.BASE + links[0]).text, przedborz.BASE + links[0]), \
            "nie rozpoznano strony wydarzenia"
    return f"{len(links)} linków do wydarzeń"


def _jsonld_check(url: str, need_events: bool) -> Check:
    def check(f: Fetcher, today: date) -> str:
        html = f.get(url).text
        assert extract_jsonld(html), "brak bloków JSON-LD"
        events = parse_jsonld_html(html, "smoke")
        assert events or not need_events, "JSON-LD bez wydarzeń"
        return f"{len(events)} wydarzeń JSON-LD"
    return check


CHECKS: dict[str, Check] = {
    "mdk": check_mdk,
    "radomsko_pl": check_radomsko_pl,
    "muzeum": check_muzeum,
    "mbp": check_mbp,
    "kamiensk": check_kamiensk,
    "przedborz": check_przedborz,
    "biletyna": _jsonld_check("https://biletyna.pl/Radomsko", need_events=True),
    "ebilet": _jsonld_check("https://www.ebilet.pl/miejsce/klub-muzyczny-bogart-w-gomunicach", need_events=False),
}


def run_checks(fetcher: Fetcher, today: date, checks: dict[str, Check] = CHECKS) -> dict[str, tuple[bool, str]]:
    results: dict[str, tuple[bool, str]] = {}
    for name, check in checks.items():
        try:
            results[name] = (True, check(fetcher, today))
        except Exception as exc:  # jedno źródło nie przerywa reszty
            results[name] = (False, f"{type(exc).__name__}: {exc}"[:200])
    return results


def failure_message(results: dict[str, tuple[bool, str]]) -> Message | None:
    bad = [f"• {n}: {detail}" for n, (ok, detail) in results.items() if not ok]
    if not bad:
        return None
    return Message("Radomsko: test dymny wykrył problem", "\n".join(bad), None, priority=4, tags=("warning",))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    config = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
    results = run_checks(Fetcher(user_agent=config.get("user_agent", USER_AGENT)), date.today())
    for name, (ok, detail) in results.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {detail}")
    msg = failure_message(results)
    if msg and "--notify" in argv and (topic := os.environ.get("NTFY_TOPIC")):
        send(msg, topic, os.environ.get("NTFY_TOKEN"), config.get("digest", {}).get("server", "https://ntfy.sh"))
    return 1 if msg else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
