"""Testy bezpieczeństwa: dane z obcych stron są niezaufane (XSS, wstrzyknięcia w ICS, DoS parserów)."""

import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest

from core.build import to_event
from core.ics import build_ics, track
from core.models import Event, RawEvent
from core.normalize import clean_text, clean_url, safe_url
from sources.base import Fetcher, ResponseTooLarge, RobotsDisallowed
from sources.jsonld import parse_jsonld_events
from sources.kamiensk import parse_day
from sources.mbp import parse_feed
from sources.mdk import parse_items, ticket_urls
from sources.radomsko_pl import parse_range

TODAY = date(2026, 10, 7)
WEB = Path(__file__).parent.parent / "web"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "java\tscript:alert(1)",
    "java&#x09;script:alert(1)", "data:text/html,<script>alert(1)</script>", "vbscript:msgbox(1)",
    "file:///etc/passwd", "//evil.example/x", "https://", "http://exa mple.pl/", "https://a.pl/‮exe.fdp",
    "https://a.pl/" + "x" * 3000, "https://a.pl:99999/", "", None, 123,
])
def test_unsafe_urls_are_rejected(url):
    assert safe_url(url) is None and clean_url(url) is None


def test_safe_urls_are_kept_and_credentials_stripped():
    assert safe_url("https://mdkradomsko.pl/a?b=1#c") == "https://mdkradomsko.pl/a?b=1#c"
    assert safe_url("HTTP://Example.PL:8080/x") == "http://example.pl:8080/x"
    assert safe_url("https://user:secret@evil.pl/") == "https://evil.pl/"
    assert safe_url("https://bilety.pl/a?x=1&amp;y=2") == "https://bilety.pl/a?x=1&y=2"


def test_models_sanitize_every_adapter_including_future_ones():
    raw = RawEvent(title="  Koncert‮\x00\r\nX-INJECT:1 ", start="2026-11-01T18:00", source="x",
                   url="javascript:alert(1)", ticket_url="data:text/html,x", venue="A" * 1000,
                   times=["17:00", "<script>", "25"])
    assert raw.url is None and raw.ticket_url is None
    assert raw.title == "Koncert X-INJECT:1"  # bez CR/LF, znaków kontrolnych i bidi
    assert len(raw.venue) == 200 and raw.times == ["17:00"]
    with pytest.raises(ValueError):
        RawEvent(title="\x00 ​", start="2026-11-01T18:00", source="x")
    ev = Event(id="1", title="t", start="2026-11-01T18:00:00+01:00", source="x", first_seen="a", last_seen="a",
               url="javascript:alert(1)")
    assert ev.url is None  # także przy wczytywaniu starego events.json


def test_malicious_jsonld_cannot_reach_page_or_calendar(geo):
    evil = [{"@type": "Event", "name": "Koncert<img src=x onerror=alert(1)>\r\nX-INJECT:1",
             "startDate": "2026-11-01T18:00:00+01:00", "url": "javascript:alert(document.domain)",
             "location": {"name": "MDK", "address": {"addressLocality": "Radomsko"}},
             "offers": {"url": "data:text/html,<script>alert(1)</script>", "price": "10"}}]
    (raw,) = parse_jsonld_events(evil, "biletyna")
    ev, _ = to_event(raw, geo, TODAY)
    dumped = json.dumps(ev.model_dump(mode="json"))
    assert "javascript:" not in dumped and "data:text" not in dumped
    kept, state = track([ev], {}, TODAY)
    ics = build_ics(kept, state).decode()
    assert "javascript:" not in ics and "data:text" not in ics
    assert not any(line.startswith("X-INJECT") for line in ics.splitlines())  # brak wstrzyknięcia właściwości ICS
    assert "<img src=x onerror=alert(1)>" in ev.title  # tytuł zostaje tekstem; strona wstawia go przez textContent


def test_text_limits_and_control_characters():
    assert clean_text("a\x07b⁦c", 100) == "a b c"
    assert clean_text("x" * 500, 300).endswith("…") and len(clean_text("x" * 500, 300)) == 300


def test_one_broken_record_does_not_disable_a_source():
    objs = [
        {"@type": "Event", "name": "Zła cena", "startDate": "2026-11-01T18:00:00", "offers": {"price": "od 50 zł"}},
        {"@type": "Event", "name": "Zła data", "startDate": "2026-13-45T18:00:00"},
        {"@type": "Event", "name": "Dobre", "startDate": "2026-11-02T18:00:00", "offers": {"lowPrice": "40,5"}},
        {"@type": "Event", "name": "Śmieci", "startDate": "2026-11-03T18:00:00", "location": ["nie", "dict"]},
    ]
    events = parse_jsonld_events(objs, "x")
    assert [e.title for e in events] == ["Zła cena", "Dobre", "Śmieci"]
    assert events[0].price_text is None and events[1].price_text == "40.5 zł"
    mdk = [{"id": 1, "title": {"rendered": "Dobre"}, "pec_date": "2026-11-15 18:00:00"},
           {"id": 2, "title": {"rendered": "Złe"}, "pec_date": "2026-11-15 18:00:00", "pec_end_time_hh": "19:00",
            "pec_daily_every": "co tydzień", "pec_recurring_frecuency": "1", "pec_end_date": "2026-11-16"},
           {"id": 3, "title": None, "pec_date": "2026-11-15 18:00:00"}]
    assert {e.title for e in parse_items(mdk, TODAY)} == {"Dobre", "Złe"}


def test_nonsense_hours_in_html_sources_are_not_fatal():
    html = ('<article class="re-event-item"><div class="re-date-card-day">9</div><div class="re-date-card-month">PAŹ'
            '</div><div class="re-date-card-duration">25:00–26:61</div><h4 class="re-event-title">A</h4></article>')
    (ev,) = parse_range(html, TODAY)
    assert ev.all_day
    row = ("<table id='events-table'><tbody><tr><td class='event-time'><span>99:99</span></td><td></td>"
           "<td><a href='/kalendarz/1'>B</a></td></tr></tbody></table>")
    (k,) = parse_day(row, TODAY)
    assert k.all_day and k.url == "https://kamiensk.pl/kalendarz/1"


def test_xml_entity_expansion_is_blocked():
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
            "<rss><channel><item><title>&lol2;</title></item></channel></rss>")
    with pytest.raises(Exception, match="(?i)entit|forbidden"):
        parse_feed(bomb, TODAY)


def test_ticket_hosts_are_matched_by_hostname_not_substring():
    html = ('<a href="https://evil.example/?x=biletyna.pl">a</a><a href="https://biletyna.pl.evil.example/">b</a>'
            '<a href="https://mdkradomsko.bilety24.pl/kup/?id=1">c</a><a href="javascript:biletyna.pl">d</a>')
    assert ticket_urls(html) == ["https://mdkradomsko.bilety24.pl/kup/?id=1"]


def _fetcher(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Fetcher(min_interval=0, retries=1, client=client, **kw)


def test_oversized_response_is_refused():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * (Fetcher.MAX_BYTES + 1))
    with pytest.raises(ResponseTooLarge):
        _fetcher(handler).get("https://a.pl/big")


def test_unreachable_robots_txt_means_disallow_rfc9309():
    def handler(req):
        return httpx.Response(503) if req.url.path == "/robots.txt" else httpx.Response(200, text="ok")
    with pytest.raises(RobotsDisallowed):
        _fetcher(handler).get("https://a.pl/x")


def test_redirect_to_other_domain_respects_its_robots_txt():
    def handler(req):
        if req.url.host == "a.pl":
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"location": "https://b.pl/private/x"})
        if req.url.path == "/robots.txt":
            rules = "User-agent: *\nDisallow: /private/"
            return httpx.Response(200, text=rules, headers={"content-type": "text/plain"})
        return httpx.Response(200, text="secret")
    with pytest.raises(RobotsDisallowed):
        _fetcher(handler).get("https://a.pl/go")


def test_frontend_never_uses_html_sinks_and_validates_links():
    js = (WEB / "app.js").read_text("utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function", js)
    hrefs = re.findall(r"link\(([^,]+),", js)
    assert hrefs and all(h.strip() in {"ticket", "details", "gcal(e)", "href"} for h in hrefs), hrefs
    assert "safeHref(e.ticket_url)" in js and "safeHref(e.url)" in js
    html = (WEB / "index.html").read_text("utf-8")
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    assert "script-src 'self'" in csp and "object-src 'none'" in csp and "unsafe-eval" not in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert 'rel: "noopener noreferrer"' in js


def test_workflows_are_pinned_and_least_privilege():
    wf = Path(__file__).parent.parent / ".github/workflows"
    for f in wf.glob("*.yml"):
        text = f.read_text("utf-8")
        for ref in re.findall(r"uses:\s*([^\s#]+)", text):
            assert re.search(r"@[0-9a-f]{40}$", ref), f"{f.name}: {ref} nie jest przypięte do SHA"
        assert "${{ github.event" not in text, f"{f.name}: dane zdarzenia w skrypcie = ryzyko wstrzyknięcia"
        assert "pull_request_target" not in text
        assert "--require-hashes" in text or "pip install" not in text
    daily = (wf / "daily.yml").read_text("utf-8")
    assert "permissions: {}" in daily


def test_compressed_responses_are_decoded_once():
    """Regresja: odpowiedź gzip była dekodowana dwa razy, co blokowało robots.txt i wszystkie źródła."""
    import gzip

    def handler(req):
        if req.url.path == "/robots.txt":
            body, ctype = b"User-agent: *\nDisallow: /private/", "text/plain"
        else:
            body, ctype = "zażółć gęślą jaźń".encode(), "text/html; charset=utf-8"
        return httpx.Response(200, content=gzip.compress(body),
                              headers={"content-encoding": "gzip", "content-type": ctype})
    f = _fetcher(handler)
    assert f.get("https://a.pl/x").text == "zażółć gęślą jaźń"
    with pytest.raises(RobotsDisallowed):
        f.get("https://a.pl/private/y")  # robots.txt odczytany poprawnie, a nie potraktowany jako błąd


def test_page_makes_no_third_party_requests():
    """Prywatność odwiedzających (RODO): strona nie pobiera nic z obcych serwerów (np. Google Fonts)."""
    html = (WEB / "index.html").read_text("utf-8")
    css = (WEB / "style.css").read_text("utf-8")
    assert not re.search(r'(?:src|href)="https?://', html), "zewnętrzny zasób w index.html"
    assert not re.search(r"url\((?:['\"])?https?://|@import", css), "zewnętrzny zasób w style.css"
    for font in re.findall(r"url\(([^)]+\.woff2)\)", css):
        assert (WEB / font).read_bytes()[:4] == b"wOF2", font
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
    assert "googleapis" not in csp and "gstatic" not in csp and "font-src 'self'" in csp
    assert (WEB / "OFL-bricolage-grotesque.txt").exists()  # licencja OFL wymaga dołączenia jej do czcionki
