"""Review fix 3: a generation 7 league can pick the two parks only generation
7 knows (Sutter Health Park SAC01, George M. Steinbrenner Field TAM02) and
its Parks catalog shows the dimensions generation 7 plays; every other
league reads and sees exactly what it did."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers import parks as parks_router
from api.routers import team_settings
from physics_sim import ballflight
from physics_sim.config import load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.park import load_park
from utils import park_utils

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _pinned_parks(monkeypatch):
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(REPO / "data"))
    ballflight.clear_fence_cache()
    yield
    ballflight.clear_fence_cache()


def _generation(monkeypatch, seven: bool) -> None:
    monkeypatch.setattr(parks_router, "_ballflight_league", lambda: seven)
    monkeypatch.setattr(team_settings, "_ballflight_league", lambda: seven)


def _catalog_as_before() -> list:
    """What /parks served before generation 7 existed (its code, inline)."""
    return [
        {
            "park_id": info.park_id or "", "name": info.name, "year": info.year,
            "lf": info.lf, "cf": info.cf, "rf": info.rf,
            "foul_territory": info.foul_territory,
            "has_preview": bool(info.park_id and info.year > 0),
        }
        for info in sorted(park_utils._load_latest_parks().values(), key=lambda p: p.name)
    ]


def test_below_generation_7_the_catalog_and_choices_are_unchanged(monkeypatch):
    _generation(monkeypatch, False)
    payload = parks_router.list_parks()
    assert json.dumps(payload["parks"]) == json.dumps(_catalog_as_before())
    assert team_settings._ballpark_names() == park_utils.list_ballpark_names()
    names = set(team_settings._ballpark_names())
    assert "Sutter Health Park" not in names
    team = SimpleNamespace(park_id="", stadium="Old Park")
    with pytest.raises(HTTPException):
        team_settings._resolve_park_id(team, "Sutter Health Park", {"park_id": "SAC01"})
    assert team_settings._resolve_park_id(team, "Sutter Health Park", {}) == ""


def test_a_generation_7_league_sees_what_it_plays_and_can_pick_the_two_parks(monkeypatch):
    _generation(monkeypatch, True)
    parks = {p["park_id"]: p for p in parks_router.list_parks()["parks"] if p["park_id"]}
    assert parks["DET05"]["cf"] == 412.0  # ParkConfig says 420
    assert parks["DET05"]["walls"] == [7.0] * 5
    assert (parks["SAC01"]["lf"], parks["SAC01"]["cf"], parks["SAC01"]["rf"]) == (330.0, 403.0, 325.0)
    assert (parks["TAM02"]["lf"], parks["TAM02"]["cf"], parks["TAM02"]["rf"]) == (318.0, 408.0, 314.0)
    assert not parks["SAC01"]["has_preview"]
    names = set(team_settings._ballpark_names())
    assert {"Sutter Health Park", "George M. Steinbrenner Field"} <= names
    team = SimpleNamespace(park_id="", stadium="Old Park")
    assert team_settings._resolve_park_id(
        team, "Sutter Health Park", {"park_id": "SAC01"}
    ) == "SAC01"
    assert team_settings._resolve_park_id(team, "George M. Steinbrenner Field", {}) == "TAM02"
    summary = team_settings._park_summary(SimpleNamespace(park_id="SAC01", stadium="x"))
    assert summary == {"park_id": "SAC01", "name": "Sutter Health Park", "year": 2025}


def test_a_picked_park_plays_its_fences_on_7_and_the_generic_park_earlier():
    name = park_utils.park_lookup_name("Sutter Health Park", "SAC01")
    assert name == "Sutter Health Park"
    assert park_utils.park_lookup_name("x", "TAM02") == "George M. Steinbrenner Field"
    seven = load_tuning(engine_profile(7, development=True))
    fence = ballflight.park_fence(load_park(name), seven)
    assert fence.park_id == "SAC01"
    # An earlier engine reads none of ParkFences.csv: the park it builds is
    # the generic one in everything it reads.
    picked, generic = load_park(name), load_park(None)
    for attr in ("stadium", "park_factor", "foul_territory_scale", "altitude_ft"):
        assert getattr(picked, attr) == getattr(generic, attr), attr
    # Ids the catalog knows resolve exactly as before.
    assert park_utils.park_lookup_name("Comerica Park", "DET05") == "Comerica Park"
    assert park_utils.park_lookup_name("x", "") is None
    assert park_utils.park_lookup_name("x", "NOPE1") is None
