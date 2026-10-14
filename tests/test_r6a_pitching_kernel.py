"""Release 6a, pitching (plan 2.1): the pitch itself.

Stuff (A), velocity (B) and the single pitch-quality path into exit velocity
(C), all in ``physics_sim.physics``. Every key is registered at the number
the engine hard-coded, so at the defaults a pitch is the pitch it was and
draws the same random numbers.

* off: the defaults spelled out, and every knob that is read only under a
  switch set to something wild, leave a seeded stream of pitches and the
  random state untouched;
* on: each formula's direction and size on one fixed pitch -- a fastball in
  the zone, swung at and hit, with the random draws pinned (``_fixed_pitch``).

Fatigue (D) is tests/test_r6a_pitching_fatigue.py; the profile, whole games
and the manager are tests/test_r6a_pitching_group.py.
"""

from __future__ import annotations

import math
import random

import pytest

import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine_generation import engine_profile

# Every kernel key this work registered, with the value that leaves the
# pitch as it was.
OFF_VALUES = {
    "pq_weight_control": 0.4,
    "pq_weight_movement": 0.4,
    "pq_weight_grade": 0.2,
    "swing_pq_chase_logit": 0.0,
    "ev_velocity_model": 0.0,
    "difficulty_velocity_scale": 1.0,
    "ev_pq_contact_base_weight": 0.4,
    "ev_pq_slope": 0.004,
    "difficulty_pq_scale": 1.0,
}
# The group's two switches: the chase term is read only while both are on.
GROUP_ON = {"ev_velocity_model": 1.0, "fatigue_model": 1.0}
# Read only under ``ev_velocity_model`` 1: the design's values.
SWITCHED_VALUES = {"ev_velo_dev_weight": 0.10, "ev_base_offset_mph": 20.0}
WILD = {"ev_velo_dev_weight": 3.0, "ev_base_offset_mph": -40.0}
# The rating centres a generation 5 pitch asks for, all 50: the test's
# pitchers and hitters are read as their ratings say.
CENTRES = {
    key: 50.0
    for key in (
        "hitter_contact_center", "hitter_eye_center", "hitter_power_center",
        "hitter_speed_center", "pitcher_control_center",
        "pitcher_movement_center", "pitcher_arm_center", "pitcher_grade_center",
        "pitcher_control_usage_center", "pitcher_movement_usage_center",
        "pitcher_arm_usage_center", "pitcher_grade_usage_center",
        "catcher_fa_center", "pitcher_hold_center", "catcher_arm_center",
        "hitter_vl_center_l", "hitter_vl_center_r", "hitter_vl_center_s",
    )
}
BATTER = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
PITCHER = {
    "repertoire": {"fb": 50.0}, "control": 50.0, "movement": 50.0,
    "velocity": 93.0, "hand": "R",
}


def _legacy(**overrides) -> TuningConfig:
    return TuningConfig.from_overrides(overrides=overrides)


def _g5(**overrides) -> TuningConfig:
    return load_tuning({**engine_profile(5), **CENTRES, **overrides})


def _g5ev(**overrides) -> TuningConfig:
    """Generation 5 with the exit-velocity soft cap off, so that on the
    fixed pitch a mile per hour of ``ev_base`` is a mile per hour times the
    contact-quality factor."""
    return _g5(exit_velo_softcap=0.0, **overrides)


def _stream(tuning, *, n=3000, seed=11, pitcher=None, batter=None):
    """``n`` seeded pitches over the counts, and the random state after."""
    pitcher = pitcher or dict(
        PITCHER, repertoire={"fb": 58.0, "sl": 52.0, "cu": 47.0},
        control=57.0, movement=44.0,
    )
    batter = batter or BATTER
    random.seed(seed)
    out = []
    for i in range(n):
        res = physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(i % 4, i % 3)
        )
        out.append(tuple(sorted(res.__dict__.items(), key=lambda kv: kv[0])))
    return out, random.getstate()


class _Pinned:
    """A stand-in for the kernel's ``random``: every chance roll comes up
    ``roll``, every uniform is its midpoint and every normal draw is its
    mean plus ``sigmas`` standard deviations."""

    def __init__(self, roll: float, sigmas: float) -> None:
        self.roll = roll
        self.sigmas = sigmas
        self.rolls = 0

    def random(self) -> float:
        self.rolls += 1
        return self.roll

    def uniform(self, low: float, high: float) -> float:
        return (low + high) / 2.0

    def gauss(self, mu: float, sigma: float) -> float:
        return mu + self.sigmas * sigma


def _fixed_pitch(monkeypatch, tuning, *, pitcher=None, batter=None, sigmas=0.0,
                 roll=0.3, count=(1, 1)):
    """One pitch with the draws pinned: a fastball aimed at the middle of
    the zone, swung at and met. ``sigmas`` 0 takes all the noise out (the
    exit velocity is the formula's centre); 1 makes every miss -- command,
    timing, barrel -- one standard deviation."""
    pinned = _Pinned(roll, sigmas)
    monkeypatch.setattr(physics, "random", pinned)
    try:
        res = physics.simulate_pitch(
            batter=batter or BATTER, pitcher=pitcher or PITCHER, tuning=tuning,
            count=count,
        )
    finally:
        monkeypatch.undo()
    res.rolls = pinned.rolls
    return res


# --- registration ---------------------------------------------------------------


def test_new_keys_are_registered_at_the_old_hard_coded_values():
    for key, value in {**OFF_VALUES, **SWITCHED_VALUES}.items():
        assert DEFAULT_TUNING[key] == value, key
    assert (
        DEFAULT_TUNING["pq_weight_control"]
        + DEFAULT_TUNING["pq_weight_movement"]
        + DEFAULT_TUNING["pq_weight_grade"]
    ) == pytest.approx(1.0)


def test_new_keys_round_trip_through_from_overrides():
    # from_overrides drops an unregistered key without a word.
    wild = {key: 7.5 for key in {**OFF_VALUES, **SWITCHED_VALUES}}
    tuning = TuningConfig.from_overrides(overrides=wild)
    assert {key: tuning.get(key) for key in wild} == wild


# --- off: the pitch is the pitch it was -----------------------------------------


@pytest.mark.parametrize("make", [_legacy, _g5], ids=["legacy", "generation5"])
def test_explicit_off_values_leave_the_pitch_stream_alone(make):
    plain, plain_state = _stream(make())
    spelled, spelled_state = _stream(make(**OFF_VALUES, **WILD))
    assert spelled == plain
    # No extra random number either: the generator ends where it ended.
    assert spelled_state == plain_state
    swings = sum(dict(row)["swing"] for row in plain)
    contacts = sum(dict(row)["contact"] for row in plain)
    assert swings > 800 and contacts > 500  # the stream reaches every path


def test_the_composite_is_worked_out_before_the_swing_with_no_draw(monkeypatch):
    """A take's result still reports the pitch's own grade; a swing's the
    composite, the same number the old code worked out after the swing."""
    pitcher = dict(PITCHER, repertoire={"fb": 70.0}, control=60.0, movement=40.0)
    for make in (_legacy, _g5):
        took = _fixed_pitch(monkeypatch, make(), pitcher=pitcher, roll=0.995)
        assert not took.swing and took.pitch_quality == 70.0
        swung = _fixed_pitch(monkeypatch, make(), pitcher=pitcher)
        assert swung.swing and swung.contact
        assert swung.pitch_quality == 60.0 * 0.4 + 40.0 * 0.4 + 70.0 * 0.2


def test_the_chase_term_draws_no_random_number(monkeypatch):
    """An out-of-zone pitch (the chase branch runs) with the term on and
    off, the whole group on: the same chance rolls, the same take."""
    pitcher = dict(PITCHER, repertoire={"fb": 70.0}, control=60.0, movement=40.0)
    centre_reads = []
    real_centre = physics._pitch_quality_center

    def centre(tuning):
        centre_reads.append(1)
        return real_centre(tuning)

    results = {}
    for slope in (0.0, 0.02):
        monkeypatch.setattr(physics, "_pitch_quality_center", centre)
        del centre_reads[:]
        # roll .6: the pitch is aimed out of the zone and taken.
        res = _fixed_pitch(
            monkeypatch, _g5(**GROUP_ON, swing_pq_chase_logit=slope),
            pitcher=pitcher, roll=0.6,
        )
        results[slope] = (res, len(centre_reads))
    (off, off_reads), (on, on_reads) = results[0.0], results[0.02]
    assert not off.in_zone and not on.in_zone
    assert not off.swing and not on.swing
    # The chase branch ran with the term on (it reads the pq centre) ...
    assert on_reads > off_reads == 0
    # ... and drew nothing: the same rolls, the same pitch.
    assert on.rolls == off.rolls
    assert (on.location, on.outcome) == (off.location, off.outcome)


# --- A. stuff --------------------------------------------------------------------


def test_pitch_quality_follows_the_registered_weights(monkeypatch):
    pitcher = dict(PITCHER, repertoire={"fb": 70.0}, control=60.0, movement=40.0)
    tuning = _g5(
        pq_weight_control=0.15, pq_weight_movement=0.30, pq_weight_grade=0.55
    )
    res = _fixed_pitch(monkeypatch, tuning, pitcher=pitcher)
    assert res.pitch_quality == pytest.approx(0.15 * 60 + 0.30 * 40 + 0.55 * 70)
    # The grade now moves pitch quality 2.75 times as far as it did.
    better = _fixed_pitch(
        monkeypatch, tuning, pitcher=dict(pitcher, repertoire={"fb": 80.0})
    )
    assert better.pitch_quality - res.pitch_quality == pytest.approx(5.5)
    # A tired pitcher's stuff loss comes straight off it.
    tired = _fixed_pitch(monkeypatch, tuning, pitcher=dict(pitcher, stuff_loss=1.5))
    assert res.pitch_quality - tired.pitch_quality == pytest.approx(1.5)


def test_pitch_quality_centre_is_the_same_mix_of_the_rating_centres():
    plain = load_tuning(
        {"contact_model": 1.0, "pitcher_control_center": 54.0,
         "pitcher_movement_center": 48.0, "pitcher_grade_center": 60.0}
    )
    assert physics._pitch_quality_center(plain) == 54 * 0.4 + 48 * 0.4 + 60 * 0.2
    weighted = load_tuning(
        {"contact_model": 1.0, "pitcher_control_center": 54.0,
         "pitcher_movement_center": 48.0, "pitcher_grade_center": 60.0,
         "pq_weight_control": 0.15, "pq_weight_movement": 0.30,
         "pq_weight_grade": 0.55}
    )
    assert physics._pitch_quality_center(weighted) == pytest.approx(
        54 * 0.15 + 48 * 0.30 + 60 * 0.55
    )
    # So the league's average pitch still sits on the contact intercept.
    average = physics._contact_probability(
        contact=50.0, pitch_quality=physics._pitch_quality_center(weighted),
        break_mag=0.0, velocity=93.0, pitch_type="fb", in_zone=True, strikes=0,
        tuning=weighted,
    )
    assert average == pytest.approx(
        1.0 / (1.0 + math.exp(-weighted.get("contact_logit_zone")))
    )


def _swing_chance(tuning, *, in_zone, pitch_quality):
    return physics._swing_probability(
        eye=50.0, contact=50.0, platoon_chase=0.0, in_zone=in_zone, balls=1,
        strikes=1, tuning=tuning, pitch_quality=pitch_quality,
    )


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def test_chase_term_is_off_by_default_and_blind_to_quality():
    tuning = _g5()
    assert _swing_chance(tuning, in_zone=False, pitch_quality=80.0) == (
        _swing_chance(tuning, in_zone=False, pitch_quality=20.0)
    )


def test_chase_term_moves_the_chase_in_log_odds_and_leaves_the_zone_alone():
    tuning = _g5(**GROUP_ON, swing_pq_chase_logit=0.02)
    base = _swing_chance(tuning, in_zone=False, pitch_quality=50.0)
    assert base == _swing_chance(_g5(), in_zone=False, pitch_quality=50.0)
    good = _swing_chance(tuning, in_zone=False, pitch_quality=60.0)
    poor = _swing_chance(tuning, in_zone=False, pitch_quality=40.0)
    assert _logit(good) - _logit(base) == pytest.approx(0.2)
    assert _logit(poor) - _logit(base) == pytest.approx(-0.2)
    # About 4 points of chase per 10 points of pitch quality at 1-1.
    assert 0.035 < good - base < 0.05
    assert _swing_chance(tuning, in_zone=True, pitch_quality=60.0) == (
        _swing_chance(tuning, in_zone=True, pitch_quality=40.0)
    )
    # No pitch quality handed over: no term.
    assert physics._swing_probability(
        eye=50.0, contact=50.0, platoon_chase=0.0, in_zone=False, balls=1,
        strikes=1, tuning=tuning,
    ) == base


def test_chase_term_acts_only_with_the_whole_pitching_group_on():
    """The term has no switch of its own: it is read only while the group
    is on (both its switches), so generation 5 -- which has the swing model
    it lives in -- cannot turn it on by itself."""
    pitcher = dict(
        PITCHER, repertoire={"fb": 75.0, "sl": 75.0}, control=70.0, movement=70.0
    )

    def chase_rate(tuning):
        rows, _state = _stream(tuning, n=6000, seed=5, pitcher=pitcher)
        out = [dict(row) for row in rows]
        away = [r for r in out if not r["in_zone"] and r["outcome"] != "hbp"]
        assert len(away) > 1500
        return sum(r["swing"] for r in away) / len(away)

    off = chase_rate(_g5(**GROUP_ON))
    on = chase_rate(_g5(**GROUP_ON, swing_pq_chase_logit=0.02))
    assert 0.04 < on - off < 0.14
    # Generation 5 with the slope set and the group off: the pitch stream
    # and the random state are generation 5's.
    assert _stream(_g5(swing_pq_chase_logit=0.5)) == _stream(_g5())
    # Half the group is not the group.
    for half in ({"ev_velocity_model": 1.0}, {"fatigue_model": 1.0}):
        assert _stream(_g5(**half, swing_pq_chase_logit=0.5)) == _stream(_g5(**half))
    assert not physics.pitching_group_on(_g5(ev_velocity_model=1.0))
    assert physics.pitching_group_on(_g5(**GROUP_ON))
    # The legacy swing model does not read it either way.
    assert _stream(_legacy(**GROUP_ON, swing_pq_chase_logit=0.5)) == _stream(
        _legacy(**GROUP_ON)
    )


# --- B. velocity ----------------------------------------------------------------


def test_velocity_reference_is_the_type_s_own_speed():
    tuning = _g5ev()
    assert physics._velocity_reference("fb", tuning) == 93.0
    assert physics._velocity_reference("cb", tuning) == 82.0
    assert physics._velocity_reference("nope", tuning) == 93.0


def test_contact_velocity_term_is_two_sided():
    tuning = _g5ev(contact_logit_velo=0.06)

    def chance(velocity, pitch_type="fb"):
        return physics._contact_probability(
            contact=50.0, pitch_quality=50.0, break_mag=0.0, velocity=velocity,
            pitch_type=pitch_type, in_zone=True, strikes=0, tuning=tuning,
        )

    at_ref = chance(93.0)
    # 0.06 of log-odds per mph, the same size above and below the reference.
    assert _logit(at_ref) - _logit(chance(95.0)) == pytest.approx(0.12)
    assert _logit(chance(91.0)) - _logit(at_ref) == pytest.approx(0.12)
    # A curve at its own reference speed is an average curve, not a slow pitch.
    assert chance(82.0, "cb") == at_ref
    assert _g5().get("contact_logit_velo") == 0.0


def test_velocity_loss_comes_off_after_the_scale_and_factor():
    tuning = _legacy(velocity_scale=1.02)
    assert physics.sample_pitch_velocity(90.0, 0.95, tuning) == 90.0 * 1.02 * 0.95
    assert physics.sample_pitch_velocity(90.0, 1.0, tuning, 1.5) == (
        90.0 * 1.02 - 1.5
    )


def test_a_mistuned_fatigue_knob_cannot_throw_an_absurd_pitch(monkeypatch):
    tuning = _legacy()
    # The loss never takes the fastball below 0.85 of its fresh speed (the
    # old model's floor), and a negative loss is no gain.
    assert physics.sample_pitch_velocity(93.0, 1.0, tuning, 300.0) == 93.0 * 0.85
    assert physics.sample_pitch_velocity(93.0, 1.0, tuning, -5.0) == 93.0
    # The generation 6 losses (2.25 mph at the cap) never reach it.
    assert physics.sample_pitch_velocity(93.0, 1.0, tuning, 2.25) == 93.0 - 2.25
    # The stuff loss leaves pitch quality at the bottom of the scale at
    # worst, and a negative one is ignored.
    pitcher = dict(PITCHER, repertoire={"fb": 70.0}, control=60.0, movement=40.0)
    plain = _fixed_pitch(monkeypatch, tuning, pitcher=pitcher)
    floored = _fixed_pitch(monkeypatch, tuning, pitcher=dict(pitcher, stuff_loss=500.0))
    assert floored.pitch_quality == physics.PITCH_QUALITY_FLOOR
    negative = _fixed_pitch(monkeypatch, tuning, pitcher=dict(pitcher, stuff_loss=-50.0))
    assert negative.pitch_quality == plain.pitch_quality
    absurd = _fixed_pitch(
        monkeypatch, tuning,
        pitcher=dict(pitcher, velocity_loss=200.0, stuff_loss=500.0),
    )
    assert absurd.velocity == pytest.approx(93.0 * 0.85)
    assert absurd.exit_velo is None or absurd.exit_velo > 0.0


def _ev(monkeypatch, tuning, **pitcher):
    res = _fixed_pitch(monkeypatch, tuning, pitcher=dict(PITCHER, **pitcher))
    assert res.swing and res.contact and res.exit_velo is not None
    return res.exit_velo


# The contact-quality base of the fixed pitch against an average pitcher:
# 0.85, less the fastball's break (pitch_break_base, in feet) times
# break_contact_penalty over 250.
_FIXED_BASE = 0.85 - math.hypot(0.04, 0.06) * 5.0 / 250.0


def _quality_factor(monkeypatch, tuning):
    """Exit velocity over ``ev_base`` for the fixed pitch (model 0)."""
    weight = tuning.get("ev_pitch_weight")
    low = _ev(monkeypatch, tuning, velocity=90.0)
    high = _ev(monkeypatch, tuning, velocity=96.0)
    return (high - low) / (6.0 * weight)


def test_exit_velocity_model_0_weighs_the_whole_pitch_speed(monkeypatch):
    tuning = _g5ev(difficulty_velocity_scale=0.0)
    factor = _quality_factor(monkeypatch, tuning)
    # A squarely met ball: the contact-quality base times 1.3, then the two
    # global scales.
    assert factor == pytest.approx(
        _FIXED_BASE * 1.3 * tuning.get("contact_quality_scale")
        * tuning.get("offense_scale")
    )
    # 0.48 mph of ev_base per mph of pitch speed.
    assert _ev(monkeypatch, tuning, velocity=95.0) - _ev(
        monkeypatch, tuning, velocity=93.0
    ) == pytest.approx(2.0 * 0.48 * factor)


def test_exit_velocity_model_1_weighs_the_reference_and_the_deviation(monkeypatch):
    off = _g5ev(difficulty_velocity_scale=0.0)
    factor = _quality_factor(monkeypatch, off)
    on = _g5ev(
        ev_velocity_model=1.0, ev_pitch_weight=0.25, ev_velo_dev_weight=0.10,
        ev_base_offset_mph=20.0, difficulty_velocity_scale=0.0,
    )
    at_ref = _ev(monkeypatch, on, velocity=93.0)
    # A pitch 2 mph above its type's reference comes off 0.2 mph of ev_base
    # harder, where model 0 gave it 0.96.
    assert _ev(monkeypatch, on, velocity=95.0) - at_ref == pytest.approx(
        0.2 * factor
    )
    assert at_ref - _ev(monkeypatch, on, velocity=91.0) == pytest.approx(
        0.2 * factor
    )
    # The level: 0.25 * 93 + 20 against 0.48 * 93 for the reference fastball.
    assert at_ref - _ev(monkeypatch, off, velocity=93.0) == pytest.approx(
        (0.25 * 93.0 + 20.0 - 0.48 * 93.0) * factor
    )
    # The offset is plain miles per hour of ev_base.
    more = _g5ev(
        ev_velocity_model=1.0, ev_pitch_weight=0.25, ev_velo_dev_weight=0.10,
        ev_base_offset_mph=21.0, difficulty_velocity_scale=0.0,
    )
    assert _ev(monkeypatch, more, velocity=93.0) - at_ref == pytest.approx(factor)


def test_difficulty_velocity_scale_takes_velocity_out_of_the_miss(monkeypatch):
    def ev(scale, velocity):
        tuning = _g5ev(difficulty_velocity_scale=scale)
        res = _fixed_pitch(
            monkeypatch, tuning, pitcher=dict(PITCHER, velocity=velocity),
            sigmas=1.0,
        )
        assert res.contact
        return res.exit_velo

    # At or below 90 mph velocity adds no difficulty either way.
    assert ev(0.0, 90.0) == ev(1.0, 90.0)
    # Above it, the same one-sigma miss costs more exit velocity while the
    # scale is on, on top of the 0.48 mph per mph both carry.
    assert ev(0.0, 98.0) > ev(1.0, 98.0)
    assert ev(0.5, 98.0) > ev(1.0, 98.0)


# --- C. one pitch-quality path into exit velocity -------------------------------


def test_the_three_paths_are_the_old_numbers_by_default(monkeypatch):
    # Control moves pitch quality and nothing else on the fixed pitch (the
    # command miss is pinned at zero).
    for make in (_legacy, _g5):
        tuning = make(exit_velo_softcap=0.0)
        avg = _ev(monkeypatch, tuning)
        good = _ev(monkeypatch, tuning, control=75.0)  # pitch quality 60
        # path 1: 0.4 of the 10 points in the contact base; path 2: 10 / 250.
        expected = (_FIXED_BASE - 4.0 / 250.0) * (1.0 - 10.0 / 250.0)
        assert good / avg == pytest.approx(expected / _FIXED_BASE)


def test_one_path_leaves_the_slope_alone(monkeypatch):
    tuning = _g5ev(
        ev_pq_contact_base_weight=0.0, ev_pq_slope=0.0015, difficulty_pq_scale=0.0
    )
    avg = _ev(monkeypatch, tuning)
    good = _ev(monkeypatch, tuning, control=75.0)
    poor = _ev(monkeypatch, tuning, control=25.0)
    assert good / avg == pytest.approx(1.0 - 0.015)
    assert poor / avg == pytest.approx(1.0 + 0.015)
    # 10 points of pitch quality take 1.5% off exit velocity (about 1.3 mph
    # on a 90 mph ball), where the old paths together took 5.8%.
    old = _g5ev()
    assert _ev(monkeypatch, old, control=75.0) / _ev(monkeypatch, old) == (
        pytest.approx(0.9419, abs=2e-4)
    )


def test_each_path_has_its_own_knob(monkeypatch):
    def drop(**overrides):
        tuning = _g5ev(**overrides)
        return _ev(monkeypatch, tuning) - _ev(monkeypatch, tuning, control=75.0)

    both = drop()
    assert drop(ev_pq_contact_base_weight=0.0) < both
    assert drop(ev_pq_slope=0.0015) < both
    assert drop(ev_pq_slope=0.0, ev_pq_contact_base_weight=0.0) == pytest.approx(0.0)
    # The slope's floor is unchanged: no pitcher takes more than a quarter.
    floor = _g5ev(ev_pq_slope=0.05, ev_pq_contact_base_weight=0.0)
    assert _ev(monkeypatch, floor, control=100.0) / _ev(monkeypatch, floor) == (
        pytest.approx(0.75)
    )


def test_difficulty_pq_scale_takes_pitch_quality_out_of_the_miss(monkeypatch):
    def ev(scale, control):
        tuning = _g5ev(
            difficulty_pq_scale=scale, ev_pq_contact_base_weight=0.0,
            ev_pq_slope=0.0,
        )
        res = _fixed_pitch(
            monkeypatch, tuning, pitcher=dict(PITCHER, control=control),
            sigmas=1.0,
        )
        assert res.contact
        return res.exit_velo

    # The term is one-sided: a below-average pitch never added difficulty.
    assert ev(0.0, 25.0) == ev(1.0, 25.0)
    assert ev(0.0, 100.0) > ev(1.0, 100.0)


def test_the_legacy_contact_roll_keeps_its_own_pitch_quality_share():
    """``ev_pq_contact_base_weight`` is an exit-velocity-only copy: with it
    at 0 the legacy contact roll (contact_model 0) is rolled as before, so
    the same swings meet the ball."""
    pitcher = dict(
        PITCHER, repertoire={"fb": 70.0, "sl": 70.0}, control=70.0, movement=70.0
    )
    plain, plain_state = _stream(_legacy(), pitcher=pitcher)
    split, split_state = _stream(
        _legacy(ev_pq_contact_base_weight=0.0), pitcher=pitcher
    )
    keys = ("swing", "contact", "outcome", "location", "pitch_type")
    assert [
        tuple(dict(row)[k] for k in keys) for row in split
    ] == [tuple(dict(row)[k] for k in keys) for row in plain]
    assert split_state == plain_state
    # ... and the balls that were hit come off harder against this pitcher.
    pairs = [
        (dict(a)["exit_velo"], dict(b)["exit_velo"])
        for a, b in zip(plain, split) if dict(a)["contact"]
    ]
    assert len(pairs) > 400
    assert all(new >= old for old, new in pairs)
    assert sum(new > old for old, new in pairs) > 0.9 * len(pairs)
