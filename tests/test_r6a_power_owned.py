"""Release 6a (power): the switches belong to the generation, and they are
bounded.

- The six keys of this work are generation-owned
  (``services.physics_tuning_settings.GENERATION_OWNED_KEYS``): a league's
  stored overrides cannot switch part of generation 6 on or off, the way
  Release 5's model switches are kept out (tests/test_r5_flip_sliders.py).
- The double line has a floor (``physics.DOUBLE_THRESHOLD_FLOOR`` of the
  park's distance): a large line-drive credit once made it negative, so a
  40 mph ball that carried 49 feet was a double. The floor never binds on
  today's engines or on generation 6.
- The line-drive credit reads the league's own ``hitter_gf_center`` in a
  generation 6 game, not the 50.0 default.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
import scripts.physics_sim_season_kpis as kpis
import services.physics_tuning_settings as S
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.park import load_park
from services import league_rating_centers as centers
from tests.r5_flip_support import league, write_schedule  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_power.json"
PARK = load_park(None)
OWNED = (
    "power_curve_model",
    "bat_speed_power_table",
    "double_gap_power_weight",
    "double_line_drive_scale",
    "double_line_drive_span",
    "contact_logit_power",
)


def _generation_6_overrides() -> dict:
    base = engine_profile(6, development=True)
    return {**base, **kpis.load_tuning_overrides_file(PROFILE_PATH, base=base)}


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    monkeypatch.setattr(S, "TUNING_OVERRIDES_PATH", path)
    return path


# --- generation-owned ------------------------------------------------------------


def test_the_switches_are_generation_owned():
    assert set(OWNED) <= set(S.GENERATION_OWNED_KEYS)
    for key in OWNED:
        assert key in DEFAULT_TUNING
        assert S._sanitize_overrides({key: 1.0}) == {}
        assert S._sanitize_overrides({key: 1.0}, strict=True) == {}
    # The Release 5 switches are still there.
    assert {"swing_model", "contact_model"} <= set(S.GENERATION_OWNED_KEYS)


@pytest.mark.parametrize("generation", [4, 5])
def test_a_stored_switch_decides_nothing_and_is_not_saved(overrides_file, generation):
    stored = {
        "hr_scale": 1.1,
        "power_curve_model": 1.0,
        "double_gap_power_weight": 0.0,
        "double_line_drive_scale": 0.3,
        "double_line_drive_span": 3.0,
        "contact_logit_power": 0.05,
        "bat_speed_power_table": {"0": 9.0, "100": 9.0},
    }
    overrides_file.write_text(json.dumps(stored))
    loaded = S.load_physics_tuning_overrides(generation)
    assert not set(OWNED) & set(loaded)
    assert loaded["hr_scale"] == 1.1
    # Posting them through the API stores none of them.
    S.save_physics_tuning_overrides(stored, generation)
    saved = json.loads(overrides_file.read_text(encoding="utf-8"))
    assert not set(OWNED) & set(saved)
    assert saved["hr_scale"] == 1.1


def test_a_preset_multiplier_cannot_reach_them():
    """Rule-preset multipliers scale numeric defaults; never an owned key."""
    multipliers = {key: 2.0 for key in OWNED if key != "bat_speed_power_table"}
    for generation in (4, 5):
        applied = S.rule_preset_overrides({**multipliers, "hr_scale": 1.02}, generation)
        assert not set(OWNED) & set(applied)
        assert "hr_scale" in applied


# --- the floor on the double line --------------------------------------------------


def test_a_huge_credit_cannot_make_a_flare_a_double():
    """The review's case: 40 mph at 20 degrees carries about 49 ft."""
    bad = load_tuning({"double_line_drive_scale": 1.5, "hitter_gf_center": 50.0})
    dist, is_hr, _bt, hit_type = physics.resolve_batted_ball(
        exit_velo=40.0, launch_angle=20.0, spray_angle=0.0, park=PARK, tuning=bad,
        batter_speed=50.0, batter_contact=50.0, batter_power=50.0,
        batter_gb_tendency=50.0,
    )
    assert dist < 60.0 and not is_hr
    assert hit_type == "single"
    # However large the credits, the line is the floor's share of the park.
    angle = physics.spray_to_field_angle(0.0)
    floor = (
        PARK.stadium.double_distance(angle)
        * bad.get("double_distance_scale")
        * physics.DOUBLE_THRESHOLD_FLOOR
    )
    for velo in range(40, 120):
        dist, is_hr, _bt, hit_type = physics.resolve_batted_ball(
            exit_velo=float(velo), launch_angle=20.0, spray_angle=0.0, park=PARK,
            tuning=bad, batter_speed=99.0, batter_contact=99.0, batter_power=99.0,
            batter_gb_tendency=50.0,
        )
        if hit_type in ("double", "triple"):
            assert dist >= floor - 1e-9


@pytest.mark.parametrize(
    "profile", ["legacy", "gen5", "gen6"],
)
def test_the_floor_never_binds_on_the_shipped_engines(profile, monkeypatch):
    """Every ball, every rating 1-99: the same answer with the floor at 0."""
    overrides = {
        "legacy": {},
        "gen5": engine_profile(5),
        "gen6": {**_generation_6_overrides(), "hitter_gf_center": 50.0},
    }[profile]
    tuning = load_tuning(overrides)
    rng = random.Random(31)
    calls = []
    for _ in range(6000):
        calls.append(dict(
            exit_velo=rng.uniform(40.0, 115.0), launch_angle=rng.uniform(-15.0, 55.0),
            spray_angle=rng.uniform(-45.0, 45.0), park=PARK, tuning=tuning,
            batter_speed=rng.choice([1.0, 99.0, rng.uniform(1.0, 99.0)]),
            batter_contact=rng.choice([1.0, 99.0, rng.uniform(1.0, 99.0)]),
            batter_power=rng.choice([1.0, 99.0, rng.uniform(1.0, 99.0)]),
            batter_gb_tendency=rng.uniform(1.0, 99.0),
        ))
    with_floor = [physics.resolve_batted_ball(**call) for call in calls]
    monkeypatch.setattr(physics, "DOUBLE_THRESHOLD_FLOOR", 0.0)
    without = [physics.resolve_batted_ball(**call) for call in calls]
    assert with_floor == without
    assert sum(result[3] == "double" for result in with_floor) > 200


# --- the line-drive credit reads the league's centre in a game ---------------------


def _shift_ground_ball_ratings(data: Path, points: float) -> None:
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


def test_a_generation_6_game_reads_the_leagues_ground_ball_centre(league, monkeypatch):
    """A league whose regulars' ground-ball ratings average about 65: the
    centre its generation 6 season stores is delivered to the game, every
    ball in play is resolved against it, and the doubles credit follows it
    -- read against the 50.0 default instead, the same balls would lose it
    (nobody in this league is within the span of 50)."""
    centers.clear_rating_center_cache()
    _shift_ground_ball_ratings(league, 15.0)
    write_schedule(league, 2026)
    (league / centers.RATING_CENTERS_FILENAME).write_text(
        json.dumps({"version": 1, "seasons": {"2026": {"engine_generation": 6}}}),
        encoding="utf-8",
    )
    delivered = centers.get_rating_center_overrides()
    centre = delivered["hitter_gf_center"]
    assert 62.0 < centre < 68.0
    overrides = {**_generation_6_overrides(), **delivered}
    assert load_tuning(overrides).get("double_line_drive_scale") > 0.0
    default_centre = load_tuning({**overrides, "hitter_gf_center": 50.0})
    seen = []
    moved = []
    real = engine.resolve_batted_ball

    def spy(**kwargs):
        seen.append(
            (kwargs["tuning"].get("hitter_gf_center"), kwargs["batter_gb_tendency"])
        )
        result = real(**kwargs)
        other = real(**{**kwargs, "tuning": default_centre})
        if other[3] != result[3]:
            moved.append((other[3], result[3]))
        return result

    monkeypatch.setattr(engine, "resolve_batted_ball", spy)
    for seed in (4, 5, 6):
        engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL02", base_dir=league,
            players_path=league / "players.csv", seed=seed,
            tuning_overrides=overrides,
        )
    assert seen and {c for c, _gf in seen} == {centre}
    # The hitters sit near the league's centre, so most get the credit;
    # against 50 hardly anyone would.
    near = [gf for _c, gf in seen if abs(gf - centre) < 8.0]
    assert len(near) > len(seen) / 2
    assert sum(abs(gf - 50.0) < 8.0 for _c, gf in seen) < len(near) / 4
    # Balls that are doubles only because the league's centre was read.
    assert moved and set(moved) == {("single", "double")}
    centers.clear_rating_center_cache()
