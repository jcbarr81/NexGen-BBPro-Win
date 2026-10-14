"""Release 6a (power): ``hitter_gf_center`` reaches a generation 6 game.

The line-drive credit on doubles reads the hitter's ground-ball rating
against the league's mean (``hitter_gf_center``, the lineup regulars'). The
tooling step gave that centre to the KPI harness only. Here it becomes a
GENERATION centre (``services.league_rating_centers.GENERATION_CENTER_KEYS``):
a season played on generation 6 or later stores it in its
``rating_centers.json`` entry and its games are given it, fixed for the
season like every other centre; a legacy or generation 5 season never
holds it, so nothing changes for a league that exists today (no league can
be given generation 6 yet).
"""

from __future__ import annotations

import csv
import json

import pytest

from physics_sim.centred_ratings import (
    CENTRED_RATING_KEYS,
    MODEL_CENTER_KEYS,
    REQUIRED_CENTER_KEYS,
    rating_center,
)
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import known_engine_generations
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    game_tuning,
    league,
    stored_generation,
    write_schedule,
)

KEY = "hitter_gf_center"


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _entry(data, season="2026") -> dict:
    stored = json.loads((data / centers.RATING_CENTERS_FILENAME).read_text())
    return stored["seasons"][season]


def _start_season_on(data, generation: int, season: int = 2026) -> None:
    """A season whose records say it is played on ``generation``, as the
    switch-on will write them: the entry and nothing else."""
    write_schedule(data, season)
    (data / centers.RATING_CENTERS_FILENAME).write_text(
        json.dumps(
            {"version": 1, "seasons": {str(season): {"engine_generation": generation}}}
        ),
        encoding="utf-8",
    )


def _shift_every_gf(data, points: float) -> None:
    path = data / "players.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields, rows = list(reader.fieldnames or []), list(reader)
    for row in rows:
        row["gf"] = str(float(row["gf"] or 50) + points)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# --- what kind of centre it is ---


def test_it_is_a_generation_6_centre_and_nothing_else():
    assert centers.GENERATION_CENTER_KEYS == {6: (KEY,)}
    assert centers.generation_center_keys(4) == ()
    assert centers.generation_center_keys(5) == ()
    assert centers.generation_center_keys(6) == (KEY,)
    assert centers.generation_center_keys(7) == (KEY,)
    assert centers.generation_center_keys("nonsense") == ()
    # Still worked out with the other Release 6a centres (the harness).
    assert KEY in centers.UNSTORED_CENTER_KEYS
    assert KEY not in centers.RATING_CENTER_KEYS
    assert KEY not in centers.RELATIVE_CENTER_KEYS
    # Not a rating the engine shifts, and no game refuses to start without it.
    assert KEY not in MODEL_CENTER_KEYS and KEY not in CENTRED_RATING_KEYS
    assert KEY not in REQUIRED_CENTER_KEYS
    assert DEFAULT_TUNING[KEY] == 50.0
    # No league can be given generation 6 yet.
    assert 6 not in known_engine_generations()


def test_the_engine_reads_the_leagues_own_centre_under_centred_ratings():
    """gf is not shifted at its source, so its centre is never the 50 a
    shifted rating is compared with."""
    for switch in (0.0, 1.0):
        tuning = load_tuning({"centred_ratings": switch, KEY: 53.5})
        assert rating_center(tuning, KEY) == 53.5
    assert rating_center(load_tuning(), KEY) == 50.0


# --- a season below generation 6 ---


def test_a_generation_5_season_is_not_given_it_and_does_not_store_it(
    league, monkeypatch
):
    write_schedule(league, 2026)
    tuning = game_tuning(monkeypatch, "2026-04-01")
    assert tuning["swing_model"] == 1.0  # a generation 5 season
    assert stored_generation(league, 2026) == 5
    assert KEY not in tuning
    before = (league / centers.RATING_CENTERS_FILENAME).read_text()
    assert KEY not in _entry(league)
    for store in (True, False):
        assert KEY not in centers.league_rating_centers(store=store)
        assert KEY not in centers.get_rating_center_overrides(store=store)
    assert set(centers.league_rating_centers()) == set(centers.RATING_CENTER_KEYS)
    assert (league / centers.RATING_CENTERS_FILENAME).read_text() == before


def test_a_legacy_season_is_not_given_it_and_does_not_store_it(league, monkeypatch):
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "4")
    write_schedule(league, 2026)
    tuning = game_tuning(monkeypatch, "2026-04-01")
    assert tuning.get("swing_model", 0.0) == 0.0
    assert KEY not in tuning
    assert KEY not in _entry(league)
    assert "engine_generation" not in _entry(league)
    assert KEY not in centers.league_rating_centers()


# --- a generation 6 season ---


def test_a_generation_6_season_stores_it_and_is_given_it(league):
    _start_season_on(league, 6)
    expected = centers.unstored_rating_centers(league)[KEY]
    assert 45.0 < expected < 55.0
    given = centers.get_rating_center_overrides()
    assert given[KEY] == expected
    # With every centre a generation 5 season is given, unchanged.
    assert set(given) == set(centers.RATING_CENTER_KEYS) | {KEY}
    assert {k: v for k, v in given.items() if k != KEY} == (
        centers.active_rating_centers(league)
    )
    entry = _entry(league)
    assert entry[KEY] == expected
    assert entry["engine_generation"] == 6
    # None of the other Release 6a centres is stored with it.
    assert not (set(centers.UNSTORED_CENTER_KEYS) - {KEY}) & set(entry)
    # The engine is told it was delivered.
    assert KEY in load_tuning(given).delivered


def test_it_is_fixed_for_the_season(league):
    _start_season_on(league, 6)
    first = centers.league_rating_centers()[KEY]
    _shift_every_gf(league, 7.0)
    assert centers.unstored_rating_centers(league)[KEY] == pytest.approx(first + 7.0)
    assert centers.league_rating_centers()[KEY] == first  # the process cache
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers()[KEY] == first  # the file
    assert _entry(league)[KEY] == first


def test_a_game_that_does_not_store_reads_it_without_fixing_it(league):
    """Watch-a-game and page loads (``store`` False)."""
    _start_season_on(league, 6)
    before = (league / centers.RATING_CENTERS_FILENAME).read_text()
    live = centers.league_rating_centers(store=False)
    assert live[KEY] == centers.unstored_rating_centers(league)[KEY]
    assert (league / centers.RATING_CENTERS_FILENAME).read_text() == before
    # Nothing was cached either: the rosters' value today is read again.
    _shift_every_gf(league, 4.0)
    assert centers.league_rating_centers(store=False)[KEY] == pytest.approx(
        live[KEY] + 4.0
    )
    # Once a season game stores it, everyone reads the stored value.
    stored = centers.league_rating_centers()[KEY]
    _shift_every_gf(league, -4.0)
    assert centers.league_rating_centers(store=False)[KEY] == stored


def test_a_stored_value_is_read_back_not_recomputed(league):
    _start_season_on(league, 6)
    centers.league_rating_centers()
    path = league / centers.RATING_CENTERS_FILENAME
    payload = json.loads(path.read_text())
    payload["seasons"]["2026"][KEY] = 61.25
    path.write_text(json.dumps(payload), encoding="utf-8")
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers()[KEY] == 61.25
