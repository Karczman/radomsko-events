import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


@pytest.fixture
def fixture_json():
    def load(rel: str):
        return json.loads((FIX / rel).read_text("utf-8"))
    return load


@pytest.fixture(scope="session")
def geo():
    from core.geo import Geo
    return Geo.load(ROOT / "data/venues.yaml")
