"""Release 5, contact, whiffs and strikeouts (plan 2.2): the log-odds contact
model, the Contact-dependent called third strike and the contact BABIP edge.

All of it is OFF at the defaults (``contact_model`` 0 and two knobs at 0.0).
Three kinds of test:

* identity: switched off, a game is the game it was before this code existed
  (``PINNED_DIGESTS`` from tests/test_r5_discipline.py), and with only the
  plate-discipline profile on it is the plate-discipline branch's game
  (``DISCIPLINE_DIGESTS``);
* the contact model switched on: monotonic in Contact and in pitch quality,
  no ceiling, the pitcher's effect the same size against every hitter
  (log5), and blind to the knobs it replaces;
* the two knobs outside the switch: the two-strike protect term in both
  swing models and the BABIP edge.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.models import BatterRatings
from physics_sim.park import load_park
from scripts import kpi_extras as kx
from scripts import physics_sim_season_kpis as kpis
from tests.test_r5_discipline import PINNED_DIGESTS, _digest, _play

REPO = Path(__file__).resolve().parents[1]
PROFILES = REPO / "scripts" / "kpi_profiles"
CONTACT_PROFILE = PROFILES / "r5_contact.json"
DISCIPLINE_PROFILE = PROFILES / "r5_discipline.json"
COMBINED_PROFILE = PROFILES / "r5_discipline_contact.json"
# The registered intercepts: K-neutral on today's swing model with the
# ratings read against the league's own centres (r5_contact.json).
ZONE, CHASE = 1.74, 0.48
NEW_KEYS = {
    "contact_model": 0.0,
    "contact_logit_zone": ZONE,
    "contact_logit_chase": CHASE,
    "contact_logit_ch": 0.09,
    "contact_logit_pq": 0.04,
    "contact_logit_break": 0.4,
    "contact_logit_two_strike": 0.22,
    "contact_logit_velo": 0.0,
    "contact_velo_ref": 93.0,
    "two_strike_protect_contact": 0.0,
    "two_strike_protect_eye": 0.0,
    "contact_babip_per10": 0.0,
}
# Everything this area may set in a profile (the hook is registered by the
# plate-discipline branch and tuned here).
CONTACT_AREA_KEYS = set(NEW_KEYS) | {"swing_two_strike_contact_logit"}
# The knobs contact_model 1 replaces.
REPLACED = {
    "k_scale": 0.9, "contact_prob_scale": 0.4, "chase_contact_scale": 0.2,
    "count_contact_scale": {"0-2": 0.5, "1-2": 0.5, "2-2": 0.5, "3-2": 0.5},
    "whiff_base": 0.3, "whiff_quality_scale": 0.5, "whiff_velocity_scale": 0.5,
    "whiff_break_scale": 0.5, "whiff_location_scale": 0.5, "whiff_chase_scale": 2.0,
}
BATTER = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
PITCHER = {
    "repertoire": {"fb": 55.0, "sl": 55.0, "cu": 55.0},
    "control": 50.0, "movement": 50.0,
}


def _tuning(**overrides) -> TuningConfig:
    return TuningConfig.from_overrides(overrides=overrides)


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _p(tuning, *, contact=50.0, pq=50.0, break_mag=0.0, velocity=93.0,
       pitch_type="fb", in_zone=True, strikes=0) -> float:
    return physics._contact_probability(
        contact=contact, pitch_quality=pq, break_mag=break_mag,
        velocity=velocity, pitch_type=pitch_type, in_zone=in_zone,
        strikes=strikes, tuning=tuning,
    )


def _pitches(tuning, *, contact=50.0, level=50.0, count=(1, 1), n=4000, seed=7):
    """``n`` pitches from the kernel, one seeded stream."""
    batter = dict(BATTER, contact=contact)
    pitcher = dict(PITCHER, control=level, movement=level)
    random.seed(seed)
    return [
        physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=count
        )
        for _ in range(n)
    ]


def _pitch_per_seed(tuning, *, contact=50.0, count=(1, 2), seeds=range(600)):
    """One pitch per seed: the same pitch for every tuning and hitter up to
    the first roll that depends on them."""
    batter = dict(BATTER, contact=contact)
    out = []
    for seed in seeds:
        random.seed(seed)
        out.append(
            physics.simulate_pitch(
                batter=batter, pitcher=PITCHER, tuning=tuning, count=count
            )
        )
    return out


def _contact_rate(results, in_zone=None) -> float:
    swings = [
        r for r in results
        if r.swing and r.outcome != "interference"
        and (in_zone is None or r.in_zone == in_zone)
    ]
    assert len(swings) >= 200
    return sum(r.contact for r in swings) / len(swings)


# --- registration and the profiles ---------------------------------------------------


def test_new_keys_are_registered_off_with_the_design_values():
    for key, value in NEW_KEYS.items():
        assert key in DEFAULT_TUNING, key
        assert DEFAULT_TUNING[key] == pytest.approx(value), key
    # Off: the switch, the two knobs outside it and the plate-discipline hook.
    for key in ("contact_model", "two_strike_protect_contact",
                "two_strike_protect_eye", "contact_babip_per10",
                "contact_logit_velo", "swing_two_strike_contact_logit"):
        assert DEFAULT_TUNING[key] == 0.0, key


def test_new_keys_round_trip_through_from_overrides():
    overrides = {key: value + 0.37 for key, value in NEW_KEYS.items()}
    tuning = TuningConfig.from_overrides(overrides=overrides)
    for key, value in overrides.items():
        assert tuning.get(key) == pytest.approx(value), key


def test_contact_profile_is_this_area_alone():
    raw = json.loads(CONTACT_PROFILE.read_text(encoding="utf-8"))
    loaded = kpis.load_tuning_overrides_file(CONTACT_PROFILE)
    assert set(loaded) == set(raw)
    assert set(loaded) <= CONTACT_AREA_KEYS | {"foul_territory_scale"}
    assert loaded["contact_model"] == 1.0
    assert loaded["foul_territory_scale"] == 0.0
    # Today's swing model, so the looking strikeout rides the protect roll.
    assert "swing_two_strike_contact_logit" not in loaded
    assert loaded["two_strike_protect_contact"] == pytest.approx(0.06)
    assert loaded["two_strike_protect_eye"] == 0.0
    _assert_owner_slopes(loaded)


def test_combined_profile_is_the_discipline_profile_plus_this_area():
    discipline = kpis.load_tuning_overrides_file(DISCIPLINE_PROFILE)
    combined = kpis.load_tuning_overrides_file(COMBINED_PROFILE)
    # Nothing of plate discipline's is retuned, and nothing outside the two
    # areas (no offense_scale, babip_scale or swing table) is set.
    for key, value in discipline.items():
        assert combined[key] == value, key
    assert set(combined) - set(discipline) <= CONTACT_AREA_KEYS
    assert combined["contact_model"] == 1.0 and combined["swing_model"] == 1.0
    # No protect roll under swing_model 1: the looking strikeout rides the
    # two-strike zone-swing hook instead.
    assert "two_strike_protect_contact" not in combined
    assert 0.0 < combined["swing_two_strike_contact_logit"] <= 0.09
    _assert_owner_slopes(combined)


def _assert_owner_slopes(profile):
    # Owner decision 1 and "taken as recommended": not refitted to today's
    # surface (the slope trap), and the two-strike term stays positive.
    assert profile["contact_logit_ch"] == pytest.approx(0.09)
    assert profile["contact_logit_pq"] == pytest.approx(0.04)
    assert profile["contact_logit_velo"] == 0.0
    assert profile["contact_logit_two_strike"] > 0.0
    assert profile["contact_logit_zone"] > profile["contact_logit_chase"]
    assert profile["contact_babip_per10"] == pytest.approx(0.01)


# --- identity: everything off --------------------------------------------------------

# Every knob this area reads only while a switch is on, set to something
# wild, with the three off-values spelled out.
WILD_OFF = {
    "contact_model": 0.0,
    "two_strike_protect_contact": 0.0,
    "two_strike_protect_eye": 0.0,
    "contact_babip_per10": 0.0,
    "contact_logit_zone": -3.0,
    "contact_logit_chase": 4.0,
    "contact_logit_ch": 0.9,
    "contact_logit_pq": 0.9,
    "contact_logit_break": 9.0,
    "contact_logit_two_strike": -5.0,
    "contact_logit_velo": 0.7,
    "contact_velo_ref": 60.0,
    "hitter_contact_center": 70.0,
    "pitcher_movement_center": 20.0,
    "pitcher_grade_center": 90.0,
}
# The plate-discipline profile's games, computed on the plate-discipline
# branch (a7fedea0e, exported with git archive; its own r5_discipline.json)
# where no contact code exists: with only that profile on, this branch must
# still play them. Same recipe as PINNED_DIGESTS (full-precision floats).
# RE-BASELINE only when plate discipline changes on purpose.
#
# The profile has since gained the hit-batter hand scales (same-hand batters
# hit about twice as often as opposite-hand ones); HBP_LOCATION_ALONE sets
# them back to 1.0, which is the profile these digests were taken with.
HBP_LOCATION_ALONE = {"hbp_same_hand_scale": 1.0, "hbp_opposite_hand_scale": 1.0}
DISCIPLINE_DIGESTS = {
    ("calibration", "CAL01", "CAL02", 1):
        "7a9ef462c73f4efd9cd0d7e6bcd285495a6e4dfee17e801aabccfc1857eebe6e",
    ("calibration", "CAL01", "CAL02", 2):
        "d14e53917e70e037a17d931be5b51579304fa7084d7bf6fe121c6debbbedc92f",
    ("calibration", "CAL07", "CAL12", 5):
        "76fd80fd7c9eab837f64ba11cba1d2bd4ac89fb50ed9b2299e908691acc071fc",
    ("calibration_league", "ALB", "DET", 1):
        "0ea54964123395677bc701eb22a1857890fcd82485c549cde5b26db1b7dbf9fb",
    ("calibration_league", "ALB", "DET", 2):
        "c977e4136cf516e24e81e17947423231caa50e07cdcf0690efbf65d32ba68ac5",
}
IDENTITY_GAMES = (
    ("calibration", "CAL01", "CAL02", 2, None),
    ("calibration_league", "ALB", "DET", 1, None),
)


def test_switched_off_the_game_is_the_pinned_game_whatever_the_knobs_hold():
    for key in IDENTITY_GAMES:
        assert _digest(_play(*key[:4], WILD_OFF)) == PINNED_DIGESTS[key], key


def test_discipline_profile_alone_still_plays_the_discipline_branch_games():
    tuned = kpis.load_tuning_overrides_file(DISCIPLINE_PROFILE)
    profile = {**tuned, **HBP_LOCATION_ALONE}
    got = {key: _digest(_play(*key, profile)) for key in DISCIPLINE_DIGESTS}
    assert got == DISCIPLINE_DIGESTS, f"got {got}"
    # The hand scales are the only thing the profile has changed since, and
    # they do change who is hit.
    assert set(HBP_LOCATION_ALONE) <= set(tuned)
    assert any(
        _digest(_play(*key, tuned)) != digest
        for key, digest in DISCIPLINE_DIGESTS.items()
    )
    # ... and, under swing_model 1, whatever the switched-off knobs hold
    # (the hook is this area's, so it is spelled out as off).
    key = ("calibration", "CAL01", "CAL02", 2)
    wild = {**profile, **WILD_OFF, "swing_two_strike_contact_logit": 0.0}
    wild.pop("hitter_contact_center")
    assert _digest(_play(*key, wild)) == DISCIPLINE_DIGESTS[key]


@pytest.mark.parametrize(
    "overrides",
    [
        {"contact_model": 1.0},
        {"two_strike_protect_contact": 0.06},
        {"two_strike_protect_eye": 0.06},
        {"contact_babip_per10": 0.03},
    ],
    ids=lambda o: next(iter(o)),
)
def test_each_switch_changes_the_game(overrides):
    # Guards the identity tests against a switch nothing reads. The protect
    # term only matters on a two-strike take in the zone whose roll lands
    # between the old chance and the new one, so several games.
    changed = False
    for seed in (1, 2, 3, 4):
        key = ("calibration", "CAL01", "CAL02", seed, None)
        changed |= _digest(_play(*key[:4], overrides)) != PINNED_DIGESTS[key]
    assert changed


def test_the_hook_changes_the_game_under_the_discipline_profile():
    profile = {
        **kpis.load_tuning_overrides_file(DISCIPLINE_PROFILE), **HBP_LOCATION_ALONE
    }
    hooked = {**profile, "swing_two_strike_contact_logit": 0.06}
    assert any(
        _digest(_play(*key, hooked)) != digest
        for key, digest in DISCIPLINE_DIGESTS.items()
    )


# --- the contact model: the formula --------------------------------------------------


def test_contact_chance_at_the_league_average_is_the_intercept():
    tuning = _tuning(contact_model=1.0)
    assert _p(tuning) == pytest.approx(1.0 / (1.0 + math.exp(-ZONE)))
    assert _p(tuning, in_zone=False) == pytest.approx(1.0 / (1.0 + math.exp(-CHASE)))
    # Break is in feet and is not centred; two strikes add their term.
    assert _logit(_p(tuning, break_mag=0.25)) == pytest.approx(ZONE - 0.4 * 0.25)
    assert _logit(_p(tuning, strikes=2)) == pytest.approx(ZONE + 0.22)
    assert _logit(_p(tuning, strikes=1)) == pytest.approx(ZONE)
    assert _logit(_p(tuning, in_zone=False, strikes=2)) == pytest.approx(CHASE + 0.22)


def test_contact_chance_is_monotonic_in_contact_and_in_pitch_quality():
    tuning = _tuning(contact_model=1.0)
    by_contact = [_p(tuning, contact=float(c)) for c in range(1, 101)]
    assert all(a < b for a, b in zip(by_contact, by_contact[1:]))
    by_quality = [_p(tuning, pq=float(q)) for q in range(1, 101)]
    assert all(a > b for a, b in zip(by_quality, by_quality[1:]))
    by_break = [_p(tuning, break_mag=b / 20.0) for b in range(12)]
    assert all(a > b for a, b in zip(by_break, by_break[1:]))
    assert all(0.0 < p < 1.0 for p in by_contact + by_quality + by_break)


def test_contact_chance_has_no_ceiling():
    # The old roll stopped at 0.95 less the whiff chance: above about 65
    # Contact, more Contact bought nothing. Here every point is worth the
    # same in log-odds all the way up, and the elite hitter passes 0.99.
    tuning = _tuning(contact_model=1.0)
    steps = [
        _logit(_p(tuning, contact=c + 5.0)) - _logit(_p(tuning, contact=float(c)))
        for c in range(20, 95, 5)
    ]
    assert steps == pytest.approx([0.45] * len(steps))
    assert _p(tuning, contact=95.0) > 0.99
    assert _p(tuning, contact=95.0, pq=80.0, in_zone=False, break_mag=0.3) < (
        _p(tuning, contact=95.0, pq=50.0, in_zone=False, break_mag=0.3)
    )


def test_pitcher_effect_is_the_same_log_odds_against_every_hitter():
    # log5: the ace takes the same factor off the odds of contact whoever is
    # at the plate, and the hitter adds the same factor against every arm.
    tuning = _tuning(contact_model=1.0)
    for in_zone in (True, False):
        for strikes in (0, 2):
            where = dict(in_zone=in_zone, strikes=strikes)
            effects = [
                _logit(_p(tuning, contact=c, pq=35.0, **where))
                - _logit(_p(tuning, contact=c, pq=80.0, **where))
                for c in (20.0, 35.0, 50.0, 65.0, 80.0, 95.0)
            ]
            assert effects == pytest.approx([0.04 * 45.0] * len(effects))


def test_ratings_are_read_against_the_league_centres():
    centred = _tuning(
        contact_model=1.0, hitter_contact_center=53.0, pitcher_control_center=60.0,
        pitcher_movement_center=40.0, pitcher_grade_center=70.0,
    )
    # The pitch-quality centre is the composite's own 0.4 / 0.4 / 0.2 mix.
    quality_center = 0.4 * 60.0 + 0.4 * 40.0 + 0.2 * 70.0
    assert _logit(_p(centred, contact=53.0, pq=quality_center)) == pytest.approx(ZONE)
    assert _logit(_p(centred, contact=63.0, pq=quality_center)) == pytest.approx(
        ZONE + 0.9
    )
    assert _logit(_p(centred, contact=53.0, pq=quality_center + 10.0)) == (
        pytest.approx(ZONE - 0.4)
    )


def test_velocity_term_is_off_and_reads_the_pitch_types_own_speed():
    off = _tuning(contact_model=1.0)
    assert _p(off, velocity=80.0) == _p(off, velocity=101.0)
    on = _tuning(contact_model=1.0, contact_logit_velo=0.05)
    assert _logit(_p(on, velocity=93.0)) == pytest.approx(ZONE)
    assert _logit(_p(on, velocity=97.0)) == pytest.approx(ZONE - 0.2)
    assert _logit(_p(on, velocity=89.0)) == pytest.approx(ZONE + 0.2)
    # A slider at a slider's speed (6 mph under the fastball) is average.
    assert _logit(_p(on, velocity=87.0, pitch_type="sl")) == pytest.approx(ZONE)


# --- the contact model: in the kernel ------------------------------------------------


def test_kernel_contact_rate_follows_contact_and_the_pitcher():
    tuning = _tuning(contact_model=1.0)
    by_contact = [
        _contact_rate(_pitches(tuning, contact=c))
        for c in (35.0, 50.0, 65.0, 80.0, 95.0)
    ]
    assert all(a < b for a, b in zip(by_contact, by_contact[1:]))
    # No ceiling: the old roll could not put the best hitter above 0.95.
    assert by_contact[-1] > 0.97
    by_pitcher = [
        _contact_rate(_pitches(tuning, level=p)) for p in (35.0, 50.0, 65.0, 80.0)
    ]
    assert all(a > b for a, b in zip(by_pitcher, by_pitcher[1:]))
    results = _pitches(tuning)
    assert _contact_rate(results, in_zone=True) > _contact_rate(results, in_zone=False)
    # Two strikes: contact goes up (a positive term), not down.
    assert _contact_rate(_pitches(tuning, count=(1, 2), n=6000)) > (
        _contact_rate(_pitches(tuning, count=(1, 1), n=6000))
    )


def test_contact_model_does_not_read_the_knobs_it_replaces():
    plain = _tuning(contact_model=1.0)
    moved = _tuning(contact_model=1.0, **REPLACED)
    for count in ((0, 0), (1, 2), (3, 2)):
        assert _pitches(plain, count=count, n=400) == (
            _pitches(moved, count=count, n=400)
        ), count
    # The same knobs do move the old roll.
    assert _pitches(_tuning(), n=400) != _pitches(_tuning(**REPLACED), n=400)


def test_contact_model_makes_one_roll_where_the_old_one_made_two(monkeypatch):
    calls = []
    real = random.random

    def spy():
        calls.append(1)
        return real()

    monkeypatch.setattr(physics.random, "random", spy)
    old_tuning, new_tuning = _tuning(), _tuning(contact_model=1.0)
    fewer = compared = 0
    for seed in range(1500):
        rolls = []
        for tuning in (old_tuning, new_tuning):
            random.seed(seed)
            del calls[:]
            res = physics.simulate_pitch(
                batter=BATTER, pitcher=PITCHER, tuning=tuning, count=(1, 1)
            )
            rolls.append((res, len(calls)))
        (old, old_rolls), (new, new_rolls) = rolls
        # Same seed = the same pitch and swing decision; a miss ends there.
        assert (old.location, old.swing) == (new.location, new.swing)
        if old.outcome != "swinging_strike" or new.outcome != "swinging_strike":
            continue
        compared += 1
        # Old: the whiff roll, then (unless it whiffed) the contact roll.
        assert old_rolls - new_rolls in (0, 1)
        fewer += old_rolls - new_rolls
    assert compared >= 20 and fewer >= 10


def test_exit_velocity_is_blind_to_the_contact_models_knobs(monkeypatch):
    # contact_base feeds exit velocity; the new hitter term must not reach it
    # (REPORT section 7). With every swing forced to connect, the batted
    # balls are the same whatever the model's slopes and centres hold.
    monkeypatch.setattr(physics, "_contact_probability", lambda **kwargs: 1.0)
    plain = _tuning(contact_model=1.0)
    moved = _tuning(
        contact_model=1.0, contact_logit_ch=0.5, contact_logit_pq=0.5,
        contact_logit_zone=-2.0, contact_logit_two_strike=3.0,
        hitter_contact_center=75.0, pitcher_grade_center=20.0,
    )
    for contact in (35.0, 80.0):
        results = _pitches(plain, contact=contact, n=600)
        assert results == _pitches(moved, contact=contact, n=600)
        assert sum(r.exit_velo is not None for r in results) >= 200


def test_ace_matters_as_much_against_the_elite_contact_hitter():
    # Audit M20 in the real per-PA kernel: from an average pitcher to an ace
    # the strikeout log-odds rise about as much against an 80 Contact hitter
    # as against a 50. Today the contact ceiling gives the 80 about 60% of it.
    park = load_park(None)

    def ace_effect(tuning, contact):
        rates = []
        for level in (50.0, 80.0):
            cell = kx._simulate_cell(
                contact=contact, power=50.0, pitcher_level=level, n=5000,
                seed=20261012, tuning=tuning, park=park,
            )
            assert cell["k"] >= 100
            rates.append(cell["k"] / cell["pa"])
        return _logit(rates[1]) - _logit(rates[0])

    profile = kpis.load_tuning_overrides_file(CONTACT_PROFILE)
    new = load_tuning({**profile, **kx.GRID_RATING_CENTERS})
    assert 0.75 < ace_effect(new, 80.0) / ace_effect(new, 50.0) < 1.25
    old = load_tuning(dict(kx.GRID_RATING_CENTERS))
    assert ace_effect(old, 80.0) / ace_effect(old, 50.0) < 0.75


# --- the called third strike ---------------------------------------------------------


def _protect(tuning, contact=50.0, eye=50.0, protect=0.63) -> float:
    return physics._two_strike_zone_protect(
        protect, contact=contact, eye=eye, tuning=tuning
    )


def test_protect_is_untouched_at_the_defaults():
    tuning = _tuning()
    for contact in (20.0, 50.0, 95.0):
        for eye in (30.0, 80.0):
            for protect in (0.63, 0.19, 1.0, 1.4):
                assert _protect(tuning, contact, eye, protect) == protect


def test_protect_follows_contact_in_log_odds():
    tuning = _tuning(two_strike_protect_contact=0.06)
    # Plan 2.2: .41 / .63 / .81 / .91 at Contact 35 / 50 / 65 / 80.
    got = [_protect(tuning, c) for c in (35.0, 50.0, 65.0, 80.0)]
    assert got == pytest.approx([0.41, 0.63, 0.81, 0.91], abs=0.005)
    assert got[1] == pytest.approx(0.63)
    rates = [_protect(tuning, float(c)) for c in range(1, 101)]
    assert all(a < b for a, b in zip(rates, rates[1:]))
    assert all(0.0 < r < 1.0 for r in rates)
    # Contact only (owner): the eye does nothing unless its own slope is set.
    assert _protect(tuning, 65.0, eye=30.0) == _protect(tuning, 65.0, eye=80.0)
    # Read against the league's average hitter.
    centred = _tuning(two_strike_protect_contact=0.06, hitter_contact_center=56.0)
    assert _protect(centred, 56.0) == pytest.approx(0.63)
    assert _protect(centred, 50.0) < 0.63


def test_protect_eye_slope_reads_the_eye_in_context():
    # The eye the pitch sees is blended with the pitcher's control, so its
    # centre is the swing model's blended one.
    tuning = _tuning(
        two_strike_protect_eye=0.05, hitter_eye_center=54.0,
        pitcher_control_center=60.0,
    )
    eye_center = 54.0 * 0.8 + (100.0 - 60.0) * 0.2
    assert _protect(tuning, eye=eye_center) == pytest.approx(0.63)
    assert _logit(_protect(tuning, eye=eye_center + 10.0)) == pytest.approx(
        _logit(0.63) + 0.5
    )


def _zone_take_rate(results) -> float:
    zone = [r for r in results if r.in_zone and r.outcome != "hbp"]
    assert len(zone) >= 150
    return sum(not r.swing for r in zone) / len(zone)


def test_old_swing_model_takes_fewer_third_strikes_with_more_contact():
    off = _tuning()
    on = _tuning(two_strike_protect_contact=0.06)
    # Off: Contact does not move the swing decision at all.
    assert [r.swing for r in _pitch_per_seed(off, contact=30.0)] == (
        [r.swing for r in _pitch_per_seed(off, contact=85.0)]
    )
    takes = [
        _zone_take_rate(_pitch_per_seed(on, contact=c, seeds=range(2500)))
        for c in (35.0, 50.0, 65.0, 80.0)
    ]
    assert all(a > b for a, b in zip(takes, takes[1:]))
    assert takes[0] > 3.0 * takes[-1]
    # The 50 hitter is the old model's hitter, pitch for pitch.
    assert _pitch_per_seed(on, contact=50.0) == _pitch_per_seed(off, contact=50.0)
    # Only in the zone with two strikes: the chase protect and the earlier
    # counts are as they were.
    for contact in (30.0, 85.0):
        with_term = _pitch_per_seed(on, contact=contact)
        without = _pitch_per_seed(off, contact=contact)
        assert [r.swing for r in with_term if not r.in_zone] == (
            [r.swing for r in without if not r.in_zone]
        )
        assert _pitch_per_seed(on, contact=contact, count=(1, 1)) == (
            _pitch_per_seed(off, contact=contact, count=(1, 1))
        )


def test_new_swing_model_takes_the_term_through_its_hook():
    # swing_model 1 has no protect roll, so the protect knobs are not read...
    plain = _tuning(swing_model=1.0)
    moved = _tuning(
        swing_model=1.0, two_strike_protect_contact=0.5, two_strike_protect_eye=0.5
    )
    for contact in (30.0, 85.0):
        assert _pitch_per_seed(plain, contact=contact) == (
            _pitch_per_seed(moved, contact=contact)
        )
    # ... and the combined profile's hook does the same job.
    profile = kpis.load_tuning_overrides_file(COMBINED_PROFILE)
    tuning = TuningConfig.from_overrides(overrides=profile)
    takes = [
        _zone_take_rate(_pitch_per_seed(tuning, contact=c, seeds=range(4000)))
        for c in (35.0, 50.0, 65.0, 80.0)
    ]
    assert all(a > b for a, b in zip(takes, takes[1:]))
    assert takes[0] > 2.0 * takes[-1]


# --- the BABIP edge ------------------------------------------------------------------


def _hitter(contact, bats="R") -> BatterRatings:
    return BatterRatings(
        player_id="b", bats=bats, primary_position="CF", other_positions=[],
        contact=contact, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0, eye=50.0,
        height=72.0, durability=50.0,
    )


def test_babip_edge_is_off_by_default():
    tuning = _tuning()
    for contact in (20.0, 50.0, 95.0):
        assert engine._contact_babip_edge(_hitter(contact), tuning) == 0.0


def test_babip_edge_is_linear_clipped_and_zero_at_the_centre():
    tuning = _tuning(contact_babip_per10=0.01, hitter_contact_center=52.0)
    edge = engine._contact_babip_edge
    assert edge(_hitter(52.0), tuning) == 0.0
    assert edge(_hitter(62.0), tuning) == pytest.approx(0.010)
    assert edge(_hitter(47.0), tuning) == pytest.approx(-0.005)
    # At most 25 points either way.
    assert edge(_hitter(77.0), tuning) == pytest.approx(0.025)
    assert edge(_hitter(99.0), tuning) == pytest.approx(0.025)
    assert edge(_hitter(27.0), tuning) == pytest.approx(-0.025)
    assert edge(_hitter(1.0), tuning) == pytest.approx(-0.025)
    # The hitter's own rating: the side he bats from changes nothing.
    assert edge(_hitter(62.0, bats="L"), tuning) == edge(_hitter(62.0), tuning)


def test_engine_adds_the_edge_to_every_ball_in_play_that_is_not_a_home_run(
    monkeypatch,
):
    base = REPO / "data" / "calibration"
    batters, _pitchers = engine.load_players_by_id(base / "players.csv")
    seen = []
    real = engine._contact_babip_edge

    def spy(batter, tuning):
        value = real(batter, tuning)
        seen.append((batter.player_id, batter.contact, value))
        return value

    monkeypatch.setattr(engine, "_contact_babip_edge", spy)
    overrides = {"contact_babip_per10": 0.01, "hitter_contact_center": 48.81}
    result = _play("calibration", "CAL01", "CAL02", 2, overrides)
    in_play = [
        row for row in result.pitch_log
        if row.get("outcome") == "in_play" and "ball_type" in row
    ]
    not_hr = [row for row in in_play if row.get("hit_type") != "hr"]
    assert len(seen) == len(not_hr) >= 40
    assert len(not_hr) < len(in_play)
    for player_id, contact, value in seen:
        # The roster rating, not the handedness / times-through-the-order
        # contact the pitch saw.
        assert contact == batters[player_id].contact
        expected = 0.01 * max(-25.0, min(25.0, contact - 48.81)) / 10.0
        assert value == pytest.approx(expected)
    assert len({round(value, 6) for _pid, _contact, value in seen}) >= 5


# --- the matchup grid ----------------------------------------------------------------


def test_matchup_grid_is_its_own_league(monkeypatch):
    seen = []

    def fake_cell(**kwargs):
        seen.append(kwargs["tuning"])
        return Counter()

    monkeypatch.setattr(kx, "_simulate_cell", fake_cell)
    # A fixture's centres, or one pinned in a profile, would move the grid's
    # 50s off the league average under the models that read a centre.
    overrides = {
        "contact_model": 1.0, "umpire_model": 1.0, "hitter_contact_center": 48.81,
        "pitcher_grade_center": 70.0, "catcher_fa_center": 54.67,
    }
    kx.matchup_grid_metrics(
        pa_per_cell=10, players_path=REPO / "data" / "calibration" / "players.csv",
        tuning_overrides=overrides,
    )
    assert len(seen) >= 16
    for tuning in seen:
        assert tuning.get("contact_model") == 1.0
        assert tuning.get("umpire_model") == 1.0
        for key, value in kx.GRID_RATING_CENTERS.items():
            assert tuning.get(key) == value, key
    # The anchor pitcher (control and movement 50, the grid's pitch grade)
    # sits exactly on the contact model's pitch-quality centre, and the
    # grid's catcher on the umpire model's.
    centres = kx.GRID_RATING_CENTERS
    anchor_quality = 0.4 * 50.0 + 0.4 * 50.0 + 0.2 * kx.GRID_PITCH_GRADE
    assert anchor_quality == pytest.approx(
        0.4 * centres["pitcher_control_center"]
        + 0.4 * centres["pitcher_movement_center"]
        + 0.2 * centres["pitcher_grade_center"]
    )
    assert centres["catcher_fa_center"] == kx.GRID_CATCHER_FIELDING
    assert overrides["hitter_contact_center"] == 48.81  # not mutated


def test_grid_centres_change_nothing_with_the_models_off():
    park = load_park(None)
    kwargs = dict(
        contact=65.0, power=50.0, pitcher_level=65.0, n=300, seed=11, park=park
    )
    plain = kx._simulate_cell(**kwargs, tuning=load_tuning(None))
    pinned = kx._simulate_cell(
        **kwargs, tuning=load_tuning(dict(kx.GRID_RATING_CENTERS))
    )
    assert plain == pinned and plain["pa"] == 300
