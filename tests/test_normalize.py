from datetime import datetime

from core.normalize import TZ, clean_title, clean_url, fold, localize, make_id


def test_clean_title_strips_date_prefix_and_entities():
    assert clean_title("31.12.2026r.- Koncert Sylwestrowy") == "Koncert Sylwestrowy"
    assert clean_title("07.11.26 r. &#8211; KLUBIK BRZDĄCÓW") == "KLUBIK BRZDĄCÓW"
    assert clean_title("15-01-2027- Kabaret Ani Mru Mru") == "Kabaret Ani Mru Mru"
    assert clean_title("DZIEŃ DZIECKA / 2D") == "DZIEŃ DZIECKA / 2D"


def test_fold_removes_diacritics_and_noise_words():
    assert fold("Koncert: Wiedeński – BILETY!") == "wiedenski"
    assert fold("Łódź") == "lodz"


def test_localize_naive_is_warsaw_and_aware_is_converted():
    assert localize(datetime(2026, 7, 1, 20, 0)).utcoffset().total_seconds() == 7200  # CEST
    assert localize(datetime(2026, 12, 1, 20, 0)).utcoffset().total_seconds() == 3600  # CET
    utc = datetime.fromisoformat("2026-10-25T00:30:00+00:00")  # tuż przed zmianą czasu
    assert localize(utc).hour == 2 and localize(utc).utcoffset().total_seconds() == 7200


def test_dst_change_day_keeps_wall_clock():
    after = localize(datetime(2026, 10, 25, 20, 0))
    assert after.utcoffset().total_seconds() == 3600
    assert after.tzinfo == TZ


def test_make_id_is_stable_and_ignores_cosmetics():
    a = make_id("Koncert Sylwestrowy", datetime(2026, 12, 31, 20), "MDK Radomsko")
    b = make_id("Koncert  sylwestrowy BILETY", datetime(2026, 12, 31, 20), "mdk radomsko")
    assert a == b and len(a) == 16
    assert a != make_id("Koncert Sylwestrowy", datetime(2026, 12, 30, 20), "MDK Radomsko")


def test_clean_url_drops_tracking_and_fragment():
    url = "https://biletyna.pl/koncert/X?eid=1&amp;utm_source=google&amp;gclid=abc&srsltid=zzz#bilety"
    assert clean_url(url) == "https://biletyna.pl/koncert/X?eid=1"
    assert clean_url(None) is None
