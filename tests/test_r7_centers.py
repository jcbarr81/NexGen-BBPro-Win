"""Release 6b: generation 7's centres reach a generation 7 game.

``hitter_pull_center`` (the regulars' mean pull rating, read by spray
widening) and ``pitcher_gf_usage_center`` (the pitchers' workload-weighted
ground-ball rating, read by the pitcher's launch-angle term) were worked out
for the KPI harness only. Generation 7 stores them in a season's
``rating_centers.json`` entry and delivers them to its games, the way
generation 6 stores the fielder centres and ``hitter_gf_center``; a season
on generation 6 or earlier never holds them. No league can be given
generation 7, so the stored path is tested with a hand-written entry, as
generation 6's was before 8.0.0. A game with the switches that read them
on refuses to start without them.
"""

from __future__ import annotations

import json

import pytest

from physics_sim.centred_ratings import (
    RatingCenterMissing,
    batted_ball_center_needs,
    require_batted_ball_centers,
)
from physics_sim.config import load_tuning
from physics_sim.engine_generation import engine_profile
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    league,
    write_schedule,
)

NEW = ("hitter_pull_center", "pitcher_gf_usage_center")


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _start_season_on(data, generation: int, season: int = 2026) -> None:
    write_schedule(data, season)
    (data / centers.RATING_CENTERS_FILENAME).write_text(
        json.dumps(
            {"version": 1, "seasons": {str(season): {"engine_generation": generation}}}
        ),
        encoding="utf-8",
    )


def _entry(data, season="2026") -> dict:
    stored = json.loads((data / centers.RATING_CENTERS_FILENAME).read_text())
    return stored["seasons"][season]


def test_they_are_generation_7_centres():
    assert centers.GENERATION_CENTER_KEYS[7] == NEW
    assert not set(NEW) & set(centers.generation_center_keys(6))
    assert centers.generation_center_keys(7) == (
        centers.generation_center_keys(6) + NEW
    )
    for key in NEW:
        assert key in centers.UNSTORED_CENTER_KEYS
        assert key not in centers.RATING_CENTER_KEYS


def test_a_generation_7_season_stores_them_and_is_given_them(league):
    _start_season_on(league, 7)
    expected = centers.unstored_rating_centers(league)
    given = centers.get_rating_center_overrides()
    entry = _entry(league)
    for key in NEW:
        assert given[key] == expected[key], key
        assert entry[key] == expected[key], key
    assert set(given) == set(centers.RATING_CENTER_KEYS) | set(
        centers.generation_center_keys(7)
    )
    assert set(NEW) <= load_tuning(given).delivered


def test_a_generation_6_season_is_not_given_them(league):
    _start_season_on(league, 6)
    given = centers.get_rating_center_overrides()
    assert not set(NEW) & set(given)
    assert not set(NEW) & set(_entry(league))


def test_a_game_with_the_switches_on_needs_them():
    require_batted_ball_centers(load_tuning({}))
    require_batted_ball_centers(load_tuning(engine_profile(5)))
    # Generation 6 reads hitter_gf_center only (its doubles credit).
    assert set(
        batted_ball_center_needs(load_tuning(engine_profile(6, development=True)))
    ) == {"hitter_gf_center"}
    on = {
        "batted_ball_model": 1.0, "spray_model": 1.0,
        "pitcher_gb_launch_scale": 0.2,
    }
    assert set(batted_ball_center_needs(load_tuning(on))) == {
        "hitter_gf_center", *NEW,
    }
    for missing in ("hitter_gf_center", *NEW):
        delivered = {k: 50.0 for k in ("hitter_gf_center", *NEW) if k != missing}
        with pytest.raises(RatingCenterMissing, match=missing):
            require_batted_ball_centers(load_tuning({**on, **delivered}))
    require_batted_ball_centers(
        load_tuning({**on, **{k: 50.0 for k in ("hitter_gf_center", *NEW)}})
    )
    # Generation 7's profile reads all three.
    profile = engine_profile(7, development=True)
    needs = batted_ball_center_needs(load_tuning(profile))
    if profile.get("batted_ball_model"):
        assert "hitter_gf_center" in needs
