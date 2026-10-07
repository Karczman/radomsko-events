import json
from datetime import date
from pathlib import Path

import pytest

from core import smoke

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 7)


class Resp:
    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeFetcher:
    """Zwraca zapisane fixtury zależnie od adresu; brak dopasowania = błąd, jak w sieci."""

    def __init__(self, routes: dict[str, str]):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        for fragment, text in self.routes.items():
            if fragment in url:
                return Resp(text)
        raise ConnectionError(f"brak trasy dla {url}")


def read(rel):
    return (FIX / rel).read_text("utf-8")


def ldjson_html(rel):
    return f'<script type="application/ld+json">{read(rel)}</script>'


def routes():
    return {
        "radomsko.pl/component/ajax": read("radomsko_pl/range.html"),
        "muzeum.radomsko.pl": read("muzeum/posts.json"),
        "mbp-radomsko.pl": read("mbp/feed.xml"),
        "kamiensk.pl/kalendarz": read("kamiensk/kalendarz_dzien.html"),
        "mdk.przedborz.pl/kalendarz": read("przedborz/kalendarz_event.html"),
        "mdk.przedborz.pl/": read("przedborz/home.html"),
        "biletyna.pl": ldjson_html("biletyna/radomsko.jsonld.json"),
        "ebilet.pl": ldjson_html("ebilet/miejsce_bogart.jsonld.json"),
    }


def test_all_non_mdk_checks_pass_on_fixtures():
    checks = {k: v for k, v in smoke.CHECKS.items() if k != "mdk"}
    results = smoke.run_checks(FakeFetcher(routes()), TODAY, checks)
    assert all(ok for ok, _ in results.values()), results
    assert smoke.failure_message(results) is None


@pytest.mark.parametrize(("source", "break_route"), [
    ("radomsko_pl", "radomsko.pl/component/ajax"),
    ("mbp", "mbp-radomsko.pl"),
    ("kamiensk", "kamiensk.pl/kalendarz"),
    ("biletyna", "biletyna.pl"),
])
def test_changed_markup_is_reported(source, break_route):
    broken = routes() | {break_route: "<html><body>Zupełnie inna strona</body></html>"}
    results = smoke.run_checks(FakeFetcher(broken), TODAY, {source: smoke.CHECKS[source]})
    ok, detail = results[source]
    assert not ok and detail


def test_network_error_in_one_source_does_not_stop_the_rest():
    r = routes()
    del r["muzeum.radomsko.pl"]
    checks = {k: smoke.CHECKS[k] for k in ("muzeum", "mbp")}
    results = smoke.run_checks(FakeFetcher(r), TODAY, checks)
    assert results["muzeum"][0] is False and "ConnectionError" in results["muzeum"][1]
    assert results["mbp"][0] is True
    msg = smoke.failure_message(results)
    assert msg.priority == 4 and "• muzeum:" in msg.body and "mbp" not in msg.body


def test_every_configured_source_has_a_smoke_check():
    import yaml
    cfg = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text("utf-8"))
    enabled = {n for n, c in cfg["sources"].items() if c.get("enabled") and n != "manual"}
    assert enabled <= set(smoke.CHECKS), enabled - set(smoke.CHECKS)
