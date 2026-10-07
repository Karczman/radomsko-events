from sources.jsonld import extract_jsonld, parse_jsonld_events, parse_jsonld_html


def test_biletyna_listing(fixture_json):
    events = parse_jsonld_events([fixture_json("biletyna/radomsko.jsonld.json")], "biletyna")
    assert len(events) == 5
    first = events[0]
    assert first.title == "Kabaret Smile - CONTRA"
    assert first.start.utcoffset().total_seconds() == 7200
    assert first.venue == "Miejski Dom Kultury" and first.place == "Radomsko"
    assert first.category == "scena"
    assert first.price_text == "138.06 zł"
    assert first.ticket_url == "https://biletyna.pl/kabaret/Kabaret-Smile/CONTRA?eid=616180"


def test_ebilet_venue_page_naive_dates_and_offer_list(fixture_json):
    events = parse_jsonld_events([fixture_json("ebilet/miejsce_bogart.jsonld.json")], "ebilet")
    assert len(events) == 1
    ev = events[0]
    assert ev.venue == "Klub Muzyczny Bogart w Gomunicach" and ev.place == "Gomunice"
    assert ev.start.tzinfo is None  # ebilet podaje czas lokalny bez strefy


def test_html_extraction_skips_broken_blocks():
    html = (
        '<script type="application/ld+json">{broken</script>'
        '<script type="application/ld+json">'
        '{"@type":"Event","name":"A","startDate":"2026-11-01T18:00:00+01:00"}</script>'
    )
    assert len(extract_jsonld(html)) == 1
    assert [e.title for e in parse_jsonld_html(html, "x")] == ["A"]


def test_cancelled_event_is_kept_with_status_and_dateless_is_skipped():
    objs = [
        {"@type": "Event", "name": "A", "startDate": "2026-11-01T18:00:00", "eventStatus": "https://schema.org/EventCancelled"},
        {"@type": "Event", "name": "B"},
        {"@type": "MusicEvent", "name": "C", "startDate": "2026-11-02T18:00:00"},
    ]
    events = parse_jsonld_events(objs, "x")
    assert [(e.title, e.status) for e in events] == [("A", "cancelled"), ("C", "active")]
