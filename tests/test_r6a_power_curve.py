"""Release 6a (power): the Power curve as a table (plan 2.2; decisions 4, 6).

``power_curve_model`` 0 (the default) is the knee formula, untouched. With
it on, bat speed from Power is the straight-line interpolation of
``bat_speed_power_table``; the registered table is the knee formula itself,
and ``scripts/kpi_profiles/r6_power.json`` holds generation 6's values:

- about 0.55 mph a point below 50 (today 0.15): 0.5 from 30 to 40, 0.55
  from 40 to 45, 0.6 from 45 to 50, so a Power 40 hitter stays inside the
  5-to-10 home run band;
- a slope that keeps rising through the middle of the scale (0.6 from 50
  to 52, 0.65 to 55, 0.8 to 57, then about 1.55 to 60; the first build had
  today's 0.15 from 50 to 52, a flat spot where most regulars sit), with
  the centre set so league home runs are held;
- the top anchors solved on the generation 5 kernel for home runs per 650
  PA at the Power ratings the 1-99 stored scale can reach (engine 60 /
  61.67 / 63.33 / 66.33 = stored 80 / 85 / 90 / 99): 35 / 40 / 45 with
  average Contact, and at 66.33 about 48 with average Contact and 57 with
  Contact 60 (stored 80) (owner decisions 6 and 16);
- rising slowly above 66.33, which no stored rating can exceed.

The home run numbers are Monte Carlo and season work (the report); what is
pinned here is the curve itself.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import physics_sim.physics as physics
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_power.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
ANCHORS = (
    "30", "40", "45", "50", "52", "55", "57", "60", "61.67", "63.33", "65",
    "66.33", "80",
)
EVERY_POWER = [float(p) for p in range(1, 100)]


def _knee_formula(power: float, scale=0.15, knee=52.0, knee_scale=0.8) -> float:
    """The curve as the engine has computed it since 7.45.0, written out
    again here so the test does not compare the function with itself."""
    delta = (float(power) - 50.0) * scale
    if power > knee:
        delta += (float(power) - knee) * knee_scale
    return delta


def _generation_6() -> object:
    overrides = kpis.load_tuning_overrides_file(
        PROFILE_PATH, base=engine_profile(6, development=True)
    )
    return load_tuning({**engine_profile(6, development=True), **overrides})


# --- registered, off ---


def test_the_switch_is_registered_off_and_the_table_is_todays_curve():
    assert DEFAULT_TUNING["power_curve_model"] == 0.0
    table = DEFAULT_TUNING["bat_speed_power_table"]
    assert tuple(table) == ANCHORS
    for level, mph in table.items():
        assert mph == pytest.approx(_knee_formula(float(level)), abs=1e-9), level
    # from_overrides drops an unregistered key without a word.
    tuning = load_tuning({"power_curve_model": 1.0, "bat_speed_power_table": {"0": 1}})
    assert tuning.get("power_curve_model") == 1.0
    assert tuning.values["bat_speed_power_table"] == {"0": 1}
    for generation in (5, 6):
        profile = engine_profile(generation, development=True)
        assert "power_curve_model" not in profile
        assert "bat_speed_power_table" not in profile


@pytest.mark.parametrize("profile", [{}, engine_profile(5)], ids=["legacy", "gen5"])
def test_off_every_integer_power_reads_the_knee_formula_exactly(profile):
    tuning = load_tuning(profile)
    assert tuning.get("power_curve_model") == 0.0
    for power in EVERY_POWER:
        assert physics._power_bat_speed(power, tuning) == _knee_formula(power), power
    # Off, the table is not even parsed, whatever it holds.
    assert "_power_table" not in tuning.__dict__
    wild = load_tuning({**profile, "bat_speed_power_table": {"0": 40, "100": -40}})
    for power in EVERY_POWER:
        assert physics._power_bat_speed(power, wild) == _knee_formula(power), power


def test_off_the_other_knee_knobs_still_work():
    tuning = load_tuning(
        {"bat_speed_power_scale": 0.3, "bat_speed_power_knee": 60.0,
         "bat_speed_power_knee_scale": 0.5}
    )
    for power in (20.0, 50.0, 60.0, 61.0, 90.0):
        assert physics._power_bat_speed(power, tuning) == _knee_formula(
            power, 0.3, 60.0, 0.5
        )


# --- on: the registered table is the knee formula ---


def test_on_with_the_registered_table_every_power_reads_todays_bat_speed():
    tuning = load_tuning({"power_curve_model": 1.0})
    for power in EVERY_POWER + [0.5, 49.99, 52.0, 52.01, 63.333333333, 99.5, 120.0]:
        assert physics._power_bat_speed(power, tuning) == pytest.approx(
            _knee_formula(power), abs=1e-9
        ), power


def test_the_table_is_interpolated_and_its_end_segments_carried_on():
    tuning = load_tuning(
        {"power_curve_model": 1.0,
         "bat_speed_power_table": {"60": 6.0, "40": -4.0, "50": 0.0, "70": 8.0}}
    )
    speed = lambda power: physics._power_bat_speed(power, tuning)  # noqa: E731
    assert speed(40.0) == -4.0 and speed(50.0) == 0.0 and speed(70.0) == 8.0
    assert speed(45.0) == pytest.approx(-2.0)  # 0.4 a point between 40 and 50
    assert speed(55.0) == pytest.approx(3.0)  # 0.6 a point between 50 and 60
    assert speed(65.0) == pytest.approx(7.0)  # 0.2 a point between 60 and 70
    assert speed(30.0) == pytest.approx(-8.0)  # the first segment, carried on
    assert speed(90.0) == pytest.approx(12.0)  # the last segment, carried on
    # A whole number comes in as an int from some callers.
    assert physics._power_bat_speed(45, tuning) == speed(45.0)


def test_the_table_is_read_once_per_tuning_and_a_bad_one_is_never_played():
    tuning = load_tuning({"power_curve_model": 1.0})
    first = physics._bat_speed_power_table(tuning)
    assert physics._bat_speed_power_table(tuning) is first
    assert first == tuple(
        (float(level), mph)
        for level, mph in DEFAULT_TUNING["bat_speed_power_table"].items()
    )
    tuning.values["bat_speed_power_table"] = {"0": 2.0, "100": 2.0}
    assert physics._power_bat_speed(50.0, tuning) == pytest.approx(0.0)  # cached
    tuning.invalidate_cache()
    assert physics._power_bat_speed(50.0, tuning) == 2.0
    # Fewer than two usable anchors is no curve: today's is read instead.
    for bad in ({}, {"50": 3.0}, {"x": 1.0, "50": "fast", "60": float("nan")}, None, 7):
        broken = load_tuning({"power_curve_model": 1.0})
        broken.values["bat_speed_power_table"] = bad
        for power in (30.0, 50.0, 64.0):
            assert physics._power_bat_speed(power, broken) == pytest.approx(
                _knee_formula(power), abs=1e-9
            ), bad


def test_neither_path_draws_a_random_number():
    for tuning in (load_tuning(), load_tuning(engine_profile(5)), _generation_6()):
        random.seed(99)
        state = random.getstate()
        for power in EVERY_POWER:
            physics._power_bat_speed(power, tuning)
        assert random.getstate() == state


# --- generation 6's table ---


def test_the_profile_switches_the_table_on_and_names_every_anchor():
    assert PROFILE["power_curve_model"] == 1
    assert tuple(PROFILE["bat_speed_power_table"]) == ANCHORS
    for key in PROFILE:
        assert key in DEFAULT_TUNING, key
    tuning = _generation_6()
    assert tuning.get("power_curve_model") == 1.0
    assert physics._bat_speed_power_table(tuning) == tuple(
        (float(level), float(mph))
        for level, mph in PROFILE["bat_speed_power_table"].items()
    )
    # The rest of generation 6 is generation 5: hr_scale is not the lever.
    assert tuning.get("hr_scale") == load_tuning(engine_profile(5)).get("hr_scale")


def test_a_profile_cannot_add_an_anchor(tmp_path):
    """Why every anchor a fit may need is in the registered table."""
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"bat_speed_power_table": {"58": 6.0}}))
    with pytest.raises(ValueError, match="bat_speed_power_table"):
        kpis.load_tuning_overrides_file(path)
    path.write_text(json.dumps({"bat_speed_power_table": {"60": 9.5}}))
    table = kpis.load_tuning_overrides_file(path)["bat_speed_power_table"]
    assert table["60"] == 9.5
    assert {k: v for k, v in table.items() if k != "60"} == {
        k: v for k, v in DEFAULT_TUNING["bat_speed_power_table"].items() if k != "60"
    }


def test_generation_6_rises_with_every_point_of_power():
    tuning = _generation_6()
    speeds = [physics._power_bat_speed(power, tuning) for power in EVERY_POWER]
    assert all(b > a for a, b in zip(speeds, speeds[1:]))
    # Bounded at both ends of anything a league can hold.
    assert -30.0 < speeds[0] and speeds[-1] < 21.0


def test_generation_6_weak_bats_lose_about_055_mph_a_point_below_50():
    """Owner decision 4 (0.15 today): 0.5 a point from 30 to 40, 0.55 from
    40 to 45 and 0.6 from 45 to 50, so a Power 40 hitter is inside the
    home run band and the weakest fifth of the regulars at three quarters
    of the middle fifth or less."""
    tuning = _generation_6()
    speed = lambda power: physics._power_bat_speed(power, tuning)  # noqa: E731
    assert 0.5 <= (speed(50.0) - speed(30.0)) / 20.0 <= 0.6
    for power in range(30, 50):
        step = speed(power + 1.0) - speed(float(power))
        assert 0.45 <= step <= 0.65, power
    # Against today: a 30 is about 7.4 mph slower, a 45 about 1.9.
    assert speed(30.0) - _knee_formula(30.0) == pytest.approx(-7.4, abs=0.5)
    assert speed(45.0) - _knee_formula(45.0) == pytest.approx(-1.9, abs=0.5)
    # The centre holds league home runs with the middle of the scale lifted.
    assert 0.0 <= speed(50.0) <= 1.0


def test_generation_6_slope_rises_smoothly_through_the_middle():
    """No flat spot where most regulars sit (the review found 0.15 mph a
    point from 50 to 52, inherited from today's knee): from 45 to 57 every
    point is worth at least 0.5 mph, and a point is never worth less than
    the point below it, up to stored 80 (engine 60)."""
    tuning = _generation_6()
    speed = lambda power: physics._power_bat_speed(power, tuning)  # noqa: E731
    steps = [speed(p + 1.0) - speed(float(p)) for p in range(45, 60)]
    assert min(steps[:12]) >= 0.5, steps
    assert all(b >= a - 1e-9 for a, b in zip(steps, steps[1:])), steps
    # Through the middle of the scale it is above today's curve.
    for power in (52.0, 55.0, 57.0):
        assert speed(power) > _knee_formula(power)


def test_generation_6_top_anchors_and_the_top_that_keeps_paying():
    """Owner decisions 6 and 16: stored 80 / 85 / 90 lifted above today's
    curve, stored 99 clearly above 90, and a safe, flat-ish slope past 99."""
    tuning = _generation_6()
    speed = lambda power: physics._power_bat_speed(power, tuning)  # noqa: E731
    lifts = {
        level: speed(level) - _knee_formula(level) for level in (60.0, 61.67, 63.33)
    }
    assert 1.0 <= lifts[60.0] <= 2.5
    assert 1.8 <= lifts[61.67] <= 3.2
    assert 2.4 <= lifts[63.33] <= 4.0
    assert lifts[60.0] < lifts[61.67] < lifts[63.33]
    # No cliff on the way up: never more than twice today's slope.
    for power in range(57, 64):
        assert 0.0 < speed(power + 1.0) - speed(float(power)) <= 1.9, power
    # Stored 90 to 99 (engine 63.33 to 66.33): 1 to 2 mph (decision 16;
    # about three home runs a season at equal Contact).
    assert 1.0 <= speed(66.33) - speed(63.33) <= 2.0
    # Above anything the stored scale can hold: rising, flat-ish, and far
    # below the knee formula (which gives a Power 80 hitter 26.9 mph).
    assert 0.0 < (speed(80.0) - speed(66.33)) / (80.0 - 66.33) <= 0.2
    assert speed(80.0) < 18.5 and speed(99.0) < 21.0
    assert speed(66.33) > _knee_formula(66.33)


def test_the_platoon_bonus_stays_flat_on_top_of_the_table():
    """Generation 5's rule (H7): the curve reads the hitter's own Power and
    a bonus point is worth the same bat speed whatever his Power."""
    tuning = _generation_6()
    per_point = tuning.get("platoon_bat_speed_per_point")
    assert tuning.get("platoon_power_after_knee") == 1.0
    for base in (35.0, 50.0, 60.0, 66.0):
        batter = {"power": base + 2.0, "power_base": base}
        assert physics._batter_power_bat_speed(batter, tuning) == pytest.approx(
            physics._power_bat_speed(base, tuning) + 2.0 * per_point
        )


# --- it reaches the ball ---


def _mean_exit_velo(tuning, power, n=4000, seed=3):
    batter = {
        "contact": 50.0, "power": power, "power_base": power, "eye": 50.0,
        "gb_tendency": 50.0, "pull_tendency": 50.0, "bats": "R",
        "batter_side": "R", "platoon_chase": 0.0, "height": 73.0,
        "zone_bottom": None, "zone_top": None,
    }
    pitcher = {
        "repertoire": {"fb": 55.0, "sl": 55.0}, "velocity": 93.0, "control": 50.0,
        "movement": 50.0, "fatigue_factor": 1.0, "hand": "R", "vs_left": 50.0,
    }
    random.seed(seed)
    total = count = 0
    for _ in range(n):
        result = physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1), context=None
        )
        if result.exit_velo is not None:
            total += result.exit_velo
            count += 1
    assert count > 500
    return total / count


def test_on_a_weak_bat_hits_the_ball_softer_and_a_90_power_bat_harder():
    centres = {key: 50.0 for key in DEFAULT_TUNING if key.endswith("_center")}
    today = load_tuning({**engine_profile(5), **centres})
    built = load_tuning({**_generation_6().values, **centres})
    assert _mean_exit_velo(built, 35.0) < _mean_exit_velo(today, 35.0) - 2.0
    assert _mean_exit_velo(built, 63.33) > _mean_exit_velo(today, 63.33) + 0.8
    # The average hitter's bat is half a mph quicker (the centre that holds
    # league home runs); his ball comes off about a third of a mph harder.
    lift = _mean_exit_velo(built, 50.0) - _mean_exit_velo(today, 50.0)
    assert 0.0 < lift < 0.6
