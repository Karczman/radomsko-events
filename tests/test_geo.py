from core.geo import haversine_km


def test_haversine_known_distance():
    # Radomsko – Piotrków Trybunalski ok. 40 km
    assert 38 < haversine_km(51.067, 19.445, 51.405, 19.703) < 45
    assert haversine_km(51.0, 19.0, 51.0, 19.0) == 0


def test_resolve_known_venue_and_distance(geo):
    loc = geo.resolve("Klub Bogart", None)
    assert loc.municipality == "Gomunice"
    assert 10 < loc.distance_km < 13  # CLAUDE.md: ok. 12 km
    assert geo.in_range(loc)


def test_przedborz_force_included_but_przyrow_is_not(geo):
    przedborz = geo.resolve(None, "Przedbórz")
    assert przedborz.distance_km > 30 and geo.in_range(przedborz)
    przyrow = geo.resolve(None, "Przyrów")
    assert 30 < przyrow.distance_km < 31 and not geo.in_range(przyrow)


def test_unknown_place_is_unresolved(geo):
    assert geo.resolve("Nieznany Dom", "Nibylandia") is None


def test_ambiguous_venue_name_follows_the_given_town(geo):
    """„Miejski Dom Kultury” to alias MDK Radomsko, ale biletyna używa tej nazwy też dla MDK w Przedborzu."""
    loc = geo.resolve("Miejski Dom Kultury", "Przedbórz")
    assert loc.municipality == "Przedbórz" and loc.distance_km > 30
    assert geo.resolve("Miejski Dom Kultury", "Radomsko").municipality == "Radomsko"
    assert geo.resolve("Miejski Dom Kultury", None).municipality == "Radomsko"  # bez miejscowości: alias
    assert geo.resolve("Klub Muzyczny BOGART", "Gomunice").municipality == "Gomunice"
