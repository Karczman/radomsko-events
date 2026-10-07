"""Geografia: haversine i wyszukiwanie miejsc w data/venues.yaml (bez geokodowania w locie)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.normalize import fold

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    distance_km: float
    municipality: str


class Geo:
    def __init__(self, data: dict):
        self.center = (data["center"]["lat"], data["center"]["lon"])
        self.radius_km = float(data.get("radius_km", 30))
        self.municipalities = {fold(m["name"]): m for m in data.get("municipalities", [])}
        self.venues: dict[str, dict] = {}
        for v in data.get("venues", []):
            for name in [v["name"], *v.get("aliases", [])]:
                self.venues[fold(name)] = v

    @classmethod
    def load(cls, path: str | Path = "data/venues.yaml") -> Geo:
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def resolve(self, venue: str | None, place: str | None) -> Location | None:
        """Obiekt z venues.yaml, a gdy brak, siedziba gminy z `place`. Brak = None (do uzupełnienia)."""
        v = self.venues.get(fold(venue or ""))
        if v and v.get("lat") is not None:
            return self._loc(v["lat"], v["lon"], v["municipality"])
        m = self.municipalities.get(fold(place or (v or {}).get("municipality") or ""))
        if m:
            return self._loc(m["seat_lat"], m["seat_lon"], m["name"])
        return None

    def _loc(self, lat: float, lon: float, municipality: str) -> Location:
        d = haversine_km(*self.center, lat, lon)
        return Location(lat, lon, round(d, 1), municipality)

    def in_range(self, loc: Location) -> bool:
        m = self.municipalities.get(fold(loc.municipality), {})
        return loc.distance_km <= self.radius_km or bool(m.get("force_include"))
