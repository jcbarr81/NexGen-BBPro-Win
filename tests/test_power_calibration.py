"""Power hits for power (S3, 7.45.0).

Before this, the Power rating had almost no effect on home runs while Contact
drove them: HR rate vs Power r = 0.08 and vs Contact r = 0.80 on the
calibration fixture, -0.06 / +0.77 on the live alpha-test league. A 19-year-old
with contact 73 and power 52 hit .394 with 20 HR in 198 AB.

These tests pin the mechanism (the knee in the power curve), the knobs that move
contact out of exit velocity (and that they are actually honoured), and the KPI
gate that would have caught the inversion months earlier.
"""

import sys
from collections import Counter
from pathlib import Path

import pytest

from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.physics import _power_bat_speed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import physics_sim_season_kpis as K  # noqa: E402


def _tuning(**over):
    return load_tuning(overrides=over)


# --- the power curve -------------------------------------------------------


def test_average_power_adds_nothing():
    assert _power_bat_speed(50.0, load_tuning()) == pytest.approx(0.0)


def test_below_the_knee_the_curve_is_linear():
    t = _tuning(bat_speed_power_scale=0.15, bat_speed_power_knee=52, bat_speed_power_knee_scale=0.8)
    assert _power_bat_speed(40.0, t) == pytest.approx(-1.5)
    assert _power_bat_speed(52.0, t) == pytest.approx(0.3)


def test_above_the_knee_each_point_is_worth_more():
    """The point of the knee: sluggers separate, average hitters do not."""
    t = _tuning(bat_speed_power_scale=0.15, bat_speed_power_knee=52, bat_speed_power_knee_scale=0.8)
    below = _power_bat_speed(52.0, t) - _power_bat_speed(48.0, t)  # 4 points under the knee
    above = _power_bat_speed(62.0, t) - _power_bat_speed(58.0, t)  # 4 points over it
    assert above > 4 * below


def test_with_no_knee_the_curve_is_the_old_linear_formula():
    """The neutral settings reproduce the pre-S3 engine exactly."""
    t = _tuning(bat_speed_power_scale=0.09, bat_speed_power_knee=100, bat_speed_power_knee_scale=0.0)
    for power in (30.0, 50.0, 64.0, 99.0):
        assert _power_bat_speed(power, t) == pytest.approx((power - 50.0) * 0.09)


def test_the_shipped_curve_rewards_power():
    t = load_tuning()
    assert _power_bat_speed(63.0, t) > _power_bat_speed(52.0, t) + 5.0


# --- contact out of exit velocity ------------------------------------------


def test_contact_no_longer_adds_bat_speed():
    assert load_tuning().get("bat_speed_contact_scale") == 0.0


def test_contact_no_longer_sets_how_hard_the_ball_is_hit():
    assert load_tuning().get("ev_contact_quality_weight") == 0.0


def test_barrel_accuracy_draws_on_power():
    assert load_tuning().get("barrel_power_weight") == 1.0


@pytest.mark.parametrize(
    "key",
    [
        "bat_speed_power_knee",
        "bat_speed_power_knee_scale",
        "ev_contact_quality_weight",
        "skill_contact_scale",
        "barrel_power_weight",
    ],
)
def test_every_new_knob_is_registered(key):
    """TuningConfig.from_overrides silently drops any key not already in
    DEFAULT_TUNING. Calibration runs that tried these knobs before they were
    registered produced identical numbers to the runs without them."""
    assert key in DEFAULT_TUNING
    assert load_tuning(overrides={key: 0.123}).get(key) == pytest.approx(0.123)


# --- the gate that would have caught it ------------------------------------


def _totals(rows):
    """rows: (player_id, pa, ab, hits, hr) -> batter_totals Counters."""
    out = {}
    for pid, pa, ab, hits, hr in rows:
        out[pid] = Counter({"pa": pa, "ab": ab, "h": hits, "hr": hr, "b2": 0, "b3": 0})
    return out


def _league(*, hr_from):
    """Twelve qualified hitters whose HR rate follows one rating. Contact and
    power are spread independently, as on the calibration fixture."""
    ratings, rows = {}, []
    for i in range(12):
        ch = 40 + (i * 7) % 30          # 40..69, shuffled order
        ph = 40 + (i * 11) % 30         # independent of ch
        ratings[f"p{i}"] = (float(ch), float(ph))
        driver = ph if hr_from == "power" else ch
        hr = int((driver - 35) * 0.8)
        rows.append((f"p{i}", 600, 540, 140 + (ch - 40), hr))
    return _totals(rows), ratings


def test_a_power_driven_league_passes_the_gate():
    totals, ratings = _league(hr_from="power")
    m = K._rating_outcome_metrics(batter_totals=totals, ratings=ratings, games_per_team=162)
    assert m["corr_hr_power"] > 0.9
    failures = K.evaluate_tolerances(
        metrics=m, benchmarks={}, tolerances=K.DEFAULT_TOLERANCES,
        targets=K.RATING_OUTCOME_TARGETS,
    )
    assert not [f for f in failures if f["metric"] in ("corr_hr_power", "corr_hr_contact")]


def test_a_contact_driven_league_fails_the_gate():
    """The pre-S3 engine, in miniature."""
    totals, ratings = _league(hr_from="contact")
    m = K._rating_outcome_metrics(batter_totals=totals, ratings=ratings, games_per_team=162)
    failures = K.evaluate_tolerances(
        metrics=m, benchmarks={}, tolerances=K.DEFAULT_TOLERANCES,
        targets=K.RATING_OUTCOME_TARGETS,
    )
    failed = {f["metric"] for f in failures}
    assert "corr_hr_power" in failed
    assert "corr_hr_contact" in failed


def test_too_few_qualified_hitters_report_nothing_rather_than_noise():
    totals, ratings = _league(hr_from="power")
    small = dict(list(totals.items())[:5])
    m = K._rating_outcome_metrics(batter_totals=small, ratings=ratings, games_per_team=162)
    assert all(v is None for v in m.values())


def test_unqualified_hitters_are_left_out():
    totals, ratings = _league(hr_from="power")
    totals["bench"] = Counter({"pa": 20, "ab": 18, "h": 18, "hr": 18, "b2": 0, "b3": 0})
    ratings["bench"] = (30.0, 30.0)  # would wreck the correlation if counted
    m = K._rating_outcome_metrics(batter_totals=totals, ratings=ratings, games_per_team=162)
    assert m["corr_hr_power"] > 0.9


def test_pearson_of_a_constant_is_undefined_not_zero():
    assert K._pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
