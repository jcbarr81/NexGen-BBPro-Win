"""Release 6a (power): ``contact_logit_power``, sluggers swing and miss more.

Under ``contact_model`` 1 the contact log-odds lose ``contact_logit_power``
for every point of the hitter's OWN Power above the league's average hitter
(his Power before the platoon, times-through-the-order and home-field
bonuses). The knob is registered at 0.0 -- no term, the roll it always was
-- and generation 6 leaves it there: alone it only takes r(K%, ISO) from
about -.35 to -.1, so it waits for the generator's Contact-Power
correlation (RELEASE6_PLAN.md 2.2).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.models import BatterRatings, PitcherRatings

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_power.json"
CENTRES = {
    "hitter_contact_center": 51.5,
    "hitter_power_center": 50.25,
    "hitter_eye_center": 49.75,
    "pitcher_control_usage_center": 52.75,
    "pitcher_movement_usage_center": 52.5,
    "pitcher_arm_usage_center": 55.25,
    "pitcher_grade_usage_center": 55.75,
    "pitcher_control_center": 52.5,
    "pitcher_movement_center": 53.25,
    "pitcher_arm_center": 56.0,
    "pitcher_grade_center": 55.5,
    "catcher_fa_center": 54.5,
}
ARGS = dict(
    contact=50.0, pitch_quality=52.0, break_mag=0.25, velocity=93.0,
    pitch_type="fb", in_zone=True, strikes=1,
)


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _generation_5(**extra) -> object:
    return load_tuning({**engine_profile(5), **CENTRES, **extra})


def test_the_knob_is_registered_off():
    assert DEFAULT_TUNING["contact_logit_power"] == 0.0
    # from_overrides drops an unregistered key without a word.
    assert load_tuning({"contact_logit_power": 0.03}).get("contact_logit_power") == 0.03
    assert "contact_logit_power" not in engine_profile(5)


def test_generation_6_leaves_it_off():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert profile.get("contact_logit_power", 0.0) == 0.0


@pytest.mark.parametrize("power", [None, 1.0, 35.0, 50.0, 64.0, 99.0])
def test_off_the_roll_does_not_read_power(power):
    """Legacy contact model 1 profile and generation 5: the probability is
    the one the function gave before it took ``power``, to the last bit."""
    for tuning in (load_tuning({"contact_model": 1.0}), _generation_5()):
        for in_zone in (True, False):
            for strikes in (0, 2):
                args = {**ARGS, "in_zone": in_zone, "strikes": strikes}
                plain = physics._contact_probability(tuning=tuning, **args)
                assert (
                    physics._contact_probability(tuning=tuning, power=power, **args)
                    == plain
                )


def test_on_each_point_of_power_costs_the_slope_in_log_odds():
    tuning = _generation_5(contact_logit_power=0.03)
    base = physics._contact_probability(tuning=tuning, power=50.0, **ARGS)
    assert base == physics._contact_probability(tuning=_generation_5(), **ARGS)
    for power in (30.0, 45.0, 55.0, 60.0, 70.0):
        got = physics._contact_probability(tuning=tuning, power=power, **ARGS)
        assert _logit(got) - _logit(base) == pytest.approx(-0.03 * (power - 50.0))
    slugger = physics._contact_probability(tuning=tuning, power=65.0, **ARGS)
    slap = physics._contact_probability(tuning=tuning, power=40.0, **ARGS)
    assert slugger < base < slap
    # No Power given (a caller outside the pitch kernel): no term.
    assert physics._contact_probability(tuning=tuning, **ARGS) == base


def test_power_is_read_against_the_league_like_contact_is():
    """Centred ratings arrive league-relative (the centre reads 50); without
    the switch the raw rating is read against the league's Power centre."""
    centred = _generation_5(contact_logit_power=0.03)
    at_50 = physics._contact_probability(tuning=centred, power=50.0, **ARGS)
    assert at_50 == physics._contact_probability(tuning=_generation_5(), **ARGS)
    raw = load_tuning(
        {"contact_model": 1.0, "contact_logit_power": 0.03, "hitter_power_center": 54.0}
    )
    plain = load_tuning({"contact_model": 1.0, "hitter_power_center": 54.0})
    at_centre = physics._contact_probability(tuning=raw, power=54.0, **ARGS)
    assert at_centre == physics._contact_probability(tuning=plain, **ARGS)
    above = physics._contact_probability(tuning=raw, power=64.0, **ARGS)
    assert _logit(above) - _logit(at_centre) == pytest.approx(-0.3)


def _contexts(tuning, *, power=60.0, bats="L", throws="R"):
    batter = BatterRatings.from_row(
        {
            "player_id": "b1", "bats": bats, "primary_position": "LF",
            "ch": "50", "ph": str(power), "vl": "50", "eye": "50",
            "gf": "50", "pl": "50", "fa": "50", "arm": "50", "sp": "50",
        }
    )
    pitcher = PitcherRatings.from_row(
        {
            "player_id": "p1", "bats": throws, "throws": throws,
            "control": "50", "movement": "50", "arm": "50", "fb": "60", "sl": "55",
        }
    )
    return (
        engine._batter_context(batter, pitcher, tuning, tto=1),
        engine._pitcher_context(pitcher, tuning),
    )


def test_the_pitch_passes_the_hitters_own_power_not_his_platoon_power(monkeypatch):
    """A left-handed batter against a right-hander carries a Power bonus in
    ``power``; the term reads ``power_base``."""
    tuning = _generation_5(contact_logit_power=0.03)
    batter, pitcher = _contexts(tuning)
    assert batter["power"] != batter["power_base"]
    seen = []
    real = physics._contact_probability

    def spy(**kwargs):
        seen.append(kwargs["power"])
        return real(**kwargs)

    monkeypatch.setattr(physics, "_contact_probability", spy)
    random.seed(11)
    for _ in range(200):
        physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1), context=None
        )
    assert seen and set(seen) == {batter["power_base"]}


def _strikeouts_and_draws(tuning, power, n=3000, seed=5):
    """Swinging misses over ``n`` seeded pitches, and the random state after."""
    batter, pitcher = _contexts(tuning, power=power, bats="R")
    random.seed(seed)
    misses = 0
    for _ in range(n):
        result = physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1), context=None
        )
        misses += result.outcome == "swinging_strike"
    return misses, random.getstate()


def test_on_a_slugger_misses_more_and_off_nothing_moves():
    off = _generation_5()
    on = _generation_5(contact_logit_power=0.05)
    slugger_off, _ = _strikeouts_and_draws(off, 65.0)
    slugger_on, _ = _strikeouts_and_draws(on, 65.0)
    assert slugger_on > slugger_off * 1.15
    # An average-Power hitter is untouched: the same pitches, the same
    # random numbers, switch on or off.
    assert _strikeouts_and_draws(on, 50.0 + CENTRES["hitter_power_center"] - 50.0) == (
        _strikeouts_and_draws(off, 50.0 + CENTRES["hitter_power_center"] - 50.0)
    )
    # And with the knob explicitly at 0 the slugger's stream is the old one.
    zero = _generation_5(contact_logit_power=0.0)
    assert _strikeouts_and_draws(zero, 65.0) == _strikeouts_and_draws(off, 65.0)
