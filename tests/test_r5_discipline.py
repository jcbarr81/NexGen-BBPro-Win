"""Release 5, plate discipline (plan 2.1): the swing, command, umpire, HBP and
IBB models, the eye/control blend knob and the rebased commissioner sliders.

Every model is behind a switch that is OFF at the defaults. Three kinds of
test:

* identity: with the switches off a game is the game it was before any of
  this code existed (``PINNED_DIGESTS``, captured on the Release 5a tree);
* each model switched on: bounded, monotonic in the rating it reads, and
  blind to the knobs it replaces;
* the sliders (owner decision 9): which keys a league's sliders move in each
  state, and the one-time conversion of stored values when a league moves to
  ``swing_model`` 1.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, TuningConfig
from physics_sim.engine import BaseState, _batter_context, _should_intentional_walk
from physics_sim.models import BatterRatings, PitcherRatings
from scripts import physics_sim_season_kpis as kpis
from services import physics_tuning_settings as settings
from services.physics_tuning_spec import (
    _SWING_MODEL_SLIDERS,
    _TUNING_SECTIONS,
    tuning_sections,
)

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "scripts" / "kpi_profiles" / "r5_discipline.json"
SWITCHES = ("swing_model", "command_model", "umpire_model", "hbp_model", "ibb_model")
COUNTS = [(balls, strikes) for balls in range(4) for strikes in range(3)]
# Plan 2.1's starting table (MLB 2023 zone swing / chase by count).
PLAN_TABLE = {
    "0-0": (0.444, 0.158), "0-1": (0.744, 0.280), "0-2": (0.871, 0.341),
    "1-0": (0.597, 0.223), "1-1": (0.777, 0.317), "1-2": (0.886, 0.386),
    "2-0": (0.582, 0.209), "2-1": (0.778, 0.325), "2-2": (0.893, 0.425),
    "3-0": (0.135, 0.036), "3-1": (0.719, 0.258), "3-2": (0.890, 0.449),
}
NEW_KEYS = {
    "swing_model": 0.0,
    "swing_eye_chase_logit": 0.035,
    "swing_eye_zone_logit": -0.005,
    "swing_platoon_chase_logit": 5.0,
    "swing_two_strike_contact_logit": 0.0,
    "swing_prob_floor": 0.01,
    "swing_prob_cap": 0.99,
    "swing_zone_scale": 1.0,
    "swing_chase_scale": 1.0,
    "swing_walk_scale": 1.0,
    "swing_two_strike_scale": 1.0,
    "swing_walk_logit_gain": 1.33,
    "eye_control_blend": 0.2,
    "command_model": 0.0,
    "command_error_ref_mult": 2.55,
    "command_error_control_log_slope": 0.02,
    "umpire_model": 0.0,
    "umpire_edge_offset_ft": -0.055,
    "umpire_edge_width_ft": 0.07,
    "umpire_framing_offset_ft": 0.045,
    "umpire_count_offset_ft": 0.012,
    "hbp_model": 0.0,
    "hbp_inside_min_ft": 0.35,
    "hbp_inside_span_ft": 0.6,
    "hbp_inside_rate": 0.2,
    "ibb_model": 0.0,
    "ibb_gap_min": 2.0,
    "ibb_gap_full": 7.0,
    "ibb_early_scale": 0.1,
    "ibb_no_out_scale": 0.3,
}


def _tuning(**overrides) -> TuningConfig:
    return TuningConfig.from_overrides(overrides=overrides)


def _batter(pid="b", bats="R", contact=50.0, power=50.0, eye=50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats=bats, primary_position="CF", other_positions=[],
        contact=contact, power=power, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0, eye=eye,
        height=72.0, durability=50.0,
    )


def _pitcher(control=50.0, throws="R") -> PitcherRatings:
    return PitcherRatings(
        player_id="p", bats="R", throws=throws, role="SP", preferred_role="SP",
        velocity=50.0, control=control, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=50.0, durability=50.0,
        fielding=50.0, arm=50.0,
        repertoire={"fb": 55.0, "sl": 55.0, "cu": 55.0, "cb": 55.0},
    )


# --- registration and the profile ---------------------------------------------------


def test_new_keys_are_registered_with_the_design_values():
    for key, value in NEW_KEYS.items():
        assert key in DEFAULT_TUNING, key
        assert DEFAULT_TUNING[key] == pytest.approx(value), key
    table = DEFAULT_TUNING["swing_count_table"]
    assert set(table) == set(PLAN_TABLE)
    for count, (zone, chase) in PLAN_TABLE.items():
        assert table[count] == {"zone": zone, "chase": chase}, count
    # Every switch ships off.
    assert all(DEFAULT_TUNING[key] == 0.0 for key in SWITCHES)


def test_new_keys_round_trip_through_from_overrides():
    overrides = {key: value + 0.37 for key, value in NEW_KEYS.items()}
    tuning = TuningConfig.from_overrides(overrides=overrides)
    for key, value in overrides.items():
        assert tuning.get(key) == pytest.approx(value), key


def test_profile_switches_everything_on_and_loads_through_the_harness():
    raw = json.loads(PROFILE.read_text(encoding="utf-8"))
    loaded = kpis.load_tuning_overrides_file(PROFILE)
    assert set(loaded) == set(raw)
    for key in SWITCHES:
        assert loaded[key] == 1.0, key
    # Designed against neutral parks, with control acting through location.
    assert loaded["foul_territory_scale"] == 0.0
    assert loaded["eye_control_blend"] == 0.0
    # The foul trim is values only; the two-strike counts go flat.
    assert loaded["foul_rate"] == pytest.approx(0.385)
    assert loaded["two_strike_foul_scale"] == 1.0
    assert set(loaded["count_foul_scale"].values()) == {1.0}
    assert set(loaded["count_foul_scale"]) == set(DEFAULT_TUNING["count_foul_scale"])
    # None of it is a default: the defaults are still today's engine.
    assert DEFAULT_TUNING["foul_rate"] == pytest.approx(0.41)
    assert DEFAULT_TUNING["two_strike_foul_scale"] == pytest.approx(1.02)
    assert DEFAULT_TUNING["count_foul_scale"]["0-2"] == pytest.approx(1.2)
    assert DEFAULT_TUNING["batter_fatigue_eye_scale"] == pytest.approx(0.7)
    assert DEFAULT_TUNING["zone_target_control_scale"] == pytest.approx(0.0009)
    assert DEFAULT_TUNING["ibb_chance"] == pytest.approx(0.35)


def test_swing_table_is_tunable_through_the_harness_overrides(tmp_path):
    path = tmp_path / "table.json"
    path.write_text(json.dumps({"swing_count_table": {"3-0": {"zone": 0.3}}}))
    loaded = kpis.load_tuning_overrides_file(path)
    table = loaded["swing_count_table"]
    # The whole table comes back, with the one entry changed.
    assert set(table) == set(PLAN_TABLE)
    assert table["3-0"] == {"zone": 0.3, "chase": 0.036}
    assert table["0-0"] == {"zone": 0.444, "chase": 0.158}
    assert DEFAULT_TUNING["swing_count_table"]["3-0"]["zone"] == 0.135
    tuning = TuningConfig.from_overrides(overrides=loaded)
    logits, _center = physics._swing_logit_table(tuning)
    assert logits[(3, 0)][0] == pytest.approx(math.log(0.3 / 0.7))
    path.write_text(json.dumps({"swing_count_table": {"4-0": {"zone": 0.3}}}))
    with pytest.raises(ValueError, match="swing_count_table.4-0"):
        kpis.load_tuning_overrides_file(path)


# --- identity: the switches off ------------------------------------------------------

# sha256 of the canonical JSON (floats rounded to 6 places) of pitch_log +
# totals + metadata for one game, at the DEFAULT tuning. Captured on the
# Release 5a tree (2b1a37952) BEFORE any Release 5 discipline code was
# written, so they pin "switches off = the engine as it was": a changed
# value, an extra random draw or a reordered draw in any off path moves
# every digest after it. The last three force the legacy intentional-walk
# rule to fire (it never does at the defaults: the threshold is above every
# lineup hitter), so its off path is pinned too.
#
# RE-BASELINE only when the default stream changes on purpose. At the
# Release 5b flip the defaults change: keep these digests and play the games
# with the legacy profile instead (as tests/test_r4_tagups_ground_outs.py
# does with r4a_legacy.json).
LEGACY_IBB = {"ibb_batter_threshold": 40.0, "ibb_inning": 1.0, "ibb_chance": 0.9}
PINNED_DIGESTS = {
    ("calibration", "CAL01", "CAL02", 1, None):
        "a74f3920a28b3b6589f74ced75ba12b3ad0b98681a928ff924b7586905fb4e2f",
    ("calibration", "CAL01", "CAL02", 2, None):
        "f27b5ba688c103312440e7ed694147965f94af776bf270cc0b01c3f32b7c7b85",
    ("calibration", "CAL01", "CAL02", 3, None):
        "9e36981f6bf7e785daed3b13cabba1861c212ae5f9db73ab158a9f105366c667",
    ("calibration", "CAL01", "CAL02", 4, None):
        "0b4b350d548c44b5de04bd31e23fedfd873cfd17e2168d9f0d3ec983c732e5b5",
    ("calibration", "CAL07", "CAL12", 5, None):
        "01a944355f4964361845c017aa94131a615ee3dec4073fd11432f91204af3852",
    ("calibration", "CAL07", "CAL12", 6, None):
        "4590f63af5589a2b395b94ce741847d014ede9130c2af8eb6c6d1afaeb2dfc90",
    ("calibration_league", "ALB", "DET", 1, None):
        "8be3e546564b8e9c1bc8e5ca2240a0cd0ff4f8f11d85c3f7986ec14c9739ff03",
    ("calibration_league", "ALB", "DET", 2, None):
        "b5d2899b207a54aace444aba732f0068a3b389d27a10897bc2fbc2a0c09db3da",
    ("calibration", "CAL03", "CAL04", 1, "legacy_ibb"):
        "2d530988048f9a83013f1cf95dca630036925f87c0b22504ded2b5ba6a3e5200",
    ("calibration", "CAL03", "CAL04", 2, "legacy_ibb"):
        "e5428319a055348af682c5963a05de51de4eeda2915416dd5cecd2ca7751953a",
    ("calibration", "CAL03", "CAL04", 3, "legacy_ibb"):
        "f793f0180f4606507aaea2f97f9125488f621c52372fa209a48b5bead26dc852",
}


def _canon(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def _digest(result) -> str:
    blob = json.dumps(
        _canon(
            {
                "pitch_log": result.pitch_log,
                "totals": result.totals,
                "meta": result.metadata,
            }
        ),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _play(fixture, away, home, seed, overrides=None):
    base = REPO / "data" / fixture
    return engine.simulate_matchup_from_files(
        away_team=away, home_team=home, base_dir=base,
        players_path=base / "players.csv", seed=seed,
        tuning_overrides=dict(overrides) if overrides else None,
    )


def test_switches_off_games_match_the_pinned_digests():
    got = {}
    hbp = ibb = 0
    for key in PINNED_DIGESTS:
        fixture, away, home, seed, variant = key
        result = _play(fixture, away, home, seed, LEGACY_IBB if variant else None)
        got[key] = _digest(result)
        hbp += result.totals["hbp"]
        ibb += result.totals["ibb"]
    assert got == PINNED_DIGESTS, f"got {got}"
    # The pinned games reach the old hit-by-pitch roll and the old
    # intentional-walk rule.
    assert hbp >= 10 and ibb >= 5


def test_knobs_a_switched_off_model_owns_are_not_read():
    # Everything read only by a switched-on model, set to something wild,
    # plus each switch spelled out as 0: still the pinned game.
    key = ("calibration", "CAL01", "CAL02", 2, None)
    wild = {
        "swing_count_table": {
            f"{b}-{s}": {"zone": 0.99, "chase": 0.9} for b, s in COUNTS
        },
        "swing_eye_chase_logit": 0.5,
        "swing_eye_zone_logit": 0.5,
        "swing_platoon_chase_logit": 50.0,
        "swing_two_strike_contact_logit": 0.5,
        "swing_prob_floor": 0.4,
        "swing_prob_cap": 0.6,
        "swing_zone_scale": 3.0,
        "swing_chase_scale": 3.0,
        "swing_walk_scale": 3.0,
        "swing_two_strike_scale": 3.0,
        "swing_walk_logit_gain": 4.0,
        "command_error_ref_mult": 9.0,
        "command_error_control_log_slope": 0.2,
        "umpire_edge_offset_ft": 0.3,
        "umpire_edge_width_ft": 0.5,
        "umpire_framing_offset_ft": 2.0,
        "umpire_count_offset_ft": 0.2,
        "hbp_inside_min_ft": 0.0,
        "hbp_inside_span_ft": 0.1,
        "hbp_inside_rate": 0.9,
        "ibb_gap_min": -50.0,
        "ibb_gap_full": -40.0,
        "ibb_early_scale": 1.0,
        "ibb_no_out_scale": 1.0,
        "hitter_eye_center": 70.0,
        "hitter_contact_center": 70.0,
    }
    wild.update({switch: 0.0 for switch in SWITCHES})
    wild["eye_control_blend"] = 0.2
    assert _digest(_play(*key[:4], wild)) == PINNED_DIGESTS[key]


@pytest.mark.parametrize("switch", SWITCHES)
def test_each_switch_changes_the_game(switch):
    # Guards the identity tests against a switch nothing reads. The ibb
    # switch only matters where a walk is on offer, so several games.
    seeds = (1, 2, 3, 4) if switch == "ibb_model" else (2,)
    changed = False
    for seed in seeds:
        key = ("calibration", "CAL01", "CAL02", seed, None)
        overrides = {switch: 1.0}
        if switch == "ibb_model":
            overrides.update(ibb_chance=1.0, ibb_gap_min=-5.0, ibb_inning=1.0)
        changed |= _digest(_play(*key[:4], overrides)) != PINNED_DIGESTS[key]
    assert changed


def test_eye_blend_default_is_the_old_hard_coded_blend():
    tuning = _tuning()
    for eye, control in ((50.0, 50.0), (37.0, 71.0), (83.5, 22.25), (61.0, 99.0)):
        batter, pitcher = _batter(eye=eye), _pitcher(control=control)
        legacy = eye * 0.8 + (100.0 - control) * 0.2
        legacy += -1.0 * tuning.get("handedness_eye_bonus")  # R vs R
        assert _batter_context(batter, pitcher, tuning)["eye"] == legacy


def test_eye_blend_zero_takes_the_pitcher_out_of_the_eye():
    tuning = _tuning(eye_control_blend=0.0)
    wild = _batter_context(_batter(eye=60.0), _pitcher(control=30.0), tuning)["eye"]
    sharp = _batter_context(_batter(eye=60.0), _pitcher(control=80.0), tuning)["eye"]
    assert wild == sharp == 60.0 - tuning.get("handedness_eye_bonus")
    # At the default blend a wild pitcher still lifts it.
    default = _tuning()
    assert (
        _batter_context(_batter(eye=60.0), _pitcher(control=30.0), default)["eye"]
        > _batter_context(_batter(eye=60.0), _pitcher(control=80.0), default)["eye"]
    )


# --- swing model -------------------------------------------------------------------


def _swing(tuning, *, in_zone, balls=0, strikes=0, eye=50.0, contact=50.0, chase=0.0):
    return physics._swing_probability(
        eye=eye, contact=contact, platoon_chase=chase, in_zone=in_zone,
        balls=balls, strikes=strikes, tuning=tuning,
    )


def test_average_hitter_swings_at_the_table_rate_in_every_count():
    tuning = _tuning(swing_model=1.0, eye_control_blend=0.0)
    for balls, strikes in COUNTS:
        zone, chase = PLAN_TABLE[f"{balls}-{strikes}"]
        assert _swing(tuning, in_zone=True, balls=balls, strikes=strikes) == (
            pytest.approx(zone)
        )
        assert _swing(tuning, in_zone=False, balls=balls, strikes=strikes) == (
            pytest.approx(chase)
        )
    # 3-2 has its own row, well above 3-1 and 3-0.
    assert PLAN_TABLE["3-2"] != PLAN_TABLE["3-1"]
    assert _swing(tuning, in_zone=False, balls=3, strikes=2) > 10 * _swing(
        tuning, in_zone=False, balls=3, strikes=0
    )


def test_swing_chance_is_monotonic_in_eye_and_bounded():
    tuning = _tuning(swing_model=1.0, eye_control_blend=0.0)
    eyes = [float(e) for e in range(1, 101)]
    for balls, strikes in COUNTS:
        chase = [
            _swing(tuning, in_zone=False, balls=balls, strikes=strikes, eye=e)
            for e in eyes
        ]
        zone = [
            _swing(tuning, in_zone=True, balls=balls, strikes=strikes, eye=e)
            for e in eyes
        ]
        # A better eye chases less, and gives up almost nothing in the zone.
        assert all(a > b for a, b in zip(chase, chase[1:]) if a > 0.01)
        assert all(a >= b for a, b in zip(zone, zone[1:]))
        assert all(0.01 <= p <= 0.99 for p in chase + zone)
        if (balls, strikes) != (3, 0):
            assert zone[39] - zone[59] < 0.03  # 40 eye vs 60 eye
    # Extremes hit the clamp, never 0 or 1.
    steep = _tuning(swing_model=1.0, swing_eye_chase_logit=5.0)
    assert _swing(steep, in_zone=False, eye=100.0) == 0.01
    assert _swing(steep, in_zone=False, eye=1.0) == 0.99


def test_eye_slope_is_the_design_log_odds_per_point():
    tuning = _tuning(swing_model=1.0, eye_control_blend=0.0)

    def logit(p):
        return math.log(p / (1.0 - p))

    lo = _swing(tuning, in_zone=False, balls=1, strikes=1, eye=45.0)
    hi = _swing(tuning, in_zone=False, balls=1, strikes=1, eye=55.0)
    assert logit(lo) - logit(hi) == pytest.approx(10 * 0.035)
    lo = _swing(tuning, in_zone=True, balls=1, strikes=1, eye=45.0)
    hi = _swing(tuning, in_zone=True, balls=1, strikes=1, eye=55.0)
    assert logit(lo) - logit(hi) == pytest.approx(10 * 0.005)


def test_eye_is_read_against_the_league_centre():
    # A league whose hitters average 58 eye: its 58 hitter is the table.
    tuning = _tuning(swing_model=1.0, eye_control_blend=0.0, hitter_eye_center=58.0)
    assert _swing(tuning, in_zone=False, eye=58.0) == pytest.approx(0.158)
    assert _swing(tuning, in_zone=False, eye=50.0) > 0.158
    # With the pitcher still blended into the eye, the centre is blended the
    # same way: the average hitter against the average pitcher is the table.
    blended = _tuning(
        swing_model=1.0, hitter_eye_center=58.0, pitcher_control_center=61.0
    )
    context_eye = 58.0 * 0.8 + (100.0 - 61.0) * 0.2
    assert _swing(blended, in_zone=False, eye=context_eye) == pytest.approx(0.158)


def test_platoon_chase_moves_only_the_chase_rate():
    tuning = _tuning(swing_model=1.0, eye_control_blend=0.0)
    base = _swing(tuning, in_zone=False, balls=1, strikes=1)
    assert _swing(tuning, in_zone=False, balls=1, strikes=1, chase=0.02) > base
    assert _swing(tuning, in_zone=False, balls=1, strikes=1, chase=-0.02) < base
    assert _swing(tuning, in_zone=True, balls=1, strikes=1, chase=0.02) == (
        _swing(tuning, in_zone=True, balls=1, strikes=1)
    )


def test_two_strike_contact_hook():
    off = _tuning(swing_model=1.0, eye_control_blend=0.0)
    on = _tuning(
        swing_model=1.0, eye_control_blend=0.0, swing_two_strike_contact_logit=0.06,
        hitter_contact_center=52.0,
    )
    # Off at the default: Contact does not move the swing decision at all.
    assert DEFAULT_TUNING["swing_two_strike_contact_logit"] == 0.0
    for strikes in (0, 1, 2):
        assert _swing(off, in_zone=True, strikes=strikes, contact=80.0) == (
            _swing(off, in_zone=True, strikes=strikes, contact=30.0)
        )
    # On: two strikes and in the zone only, read against the league centre.
    rates = [
        _swing(on, in_zone=True, balls=1, strikes=2, contact=float(c))
        for c in range(20, 96, 5)
    ]
    assert all(a < b for a, b in zip(rates, rates[1:]))
    assert _swing(on, in_zone=True, balls=1, strikes=2, contact=52.0) == (
        pytest.approx(PLAN_TABLE["1-2"][0])
    )
    assert _swing(on, in_zone=True, balls=1, strikes=1, contact=80.0) == (
        _swing(on, in_zone=True, balls=1, strikes=1, contact=30.0)
    )
    assert _swing(on, in_zone=False, balls=1, strikes=2, contact=80.0) == (
        _swing(on, in_zone=False, balls=1, strikes=2, contact=30.0)
    )


def test_swing_model_does_not_read_the_knobs_it_replaces():
    replaced = {
        "zone_swing_scale": 0.5, "chase_scale": 0.3, "walk_scale": 1.9,
        "two_strike_aggression_scale": 3.0, "two_strike_zone_protect": 0.0,
        "two_strike_chase_protect": 0.9, "take_on_3_0_scale": 0.01,
        "take_on_3_1_scale": 0.01,
        "count_swing_bonus": {"0-2": {"zone": 0.5, "chase": 0.5}},
    }
    plain = _tuning(swing_model=1.0)
    moved = _tuning(swing_model=1.0, **replaced)
    pitcher = {"repertoire": {"fb": 55.0, "sl": 55.0}, "control": 50.0}
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    for count in ((0, 0), (0, 2), (3, 0), (3, 1), (3, 2)):
        results = []
        for tuning in (plain, moved):
            random.seed(20261012)
            results.append(
                [
                    physics.simulate_pitch(
                        batter=batter, pitcher=pitcher, tuning=tuning, count=count
                    )
                    for _ in range(300)
                ]
            )
        assert results[0] == results[1], count


def _count_rolls(monkeypatch):
    """Count ``random.random()`` calls made by the kernel from here on."""
    calls = []
    real = random.random

    def spy():
        calls.append(1)
        return real()

    monkeypatch.setattr(physics.random, "random", spy)
    return calls


def test_swing_model_makes_one_swing_roll_at_two_strikes(monkeypatch):
    # The old model rolls again ("protect") after a two-strike take; the new
    # one decides once. Same seed = same pitch up to the swing decision, so
    # a pitch both models take in the zone costs the old model one roll more.
    calls = _count_rolls(monkeypatch)
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    pitcher = {"repertoire": {"fb": 55.0}, "control": 50.0}
    old_tuning = _tuning(two_strike_zone_protect=0.01)
    new_tuning = _tuning(swing_model=1.0, two_strike_zone_protect=0.01)
    compared = 0
    for seed in range(600):
        taken = []
        for tuning in (old_tuning, new_tuning):
            random.seed(seed)
            del calls[:]
            res = physics.simulate_pitch(
                batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 2)
            )
            taken.append((res, len(calls)))
        (old, old_rolls), (new, new_rolls) = taken
        assert old.location == new.location
        if any(r.swing or not r.in_zone or r.outcome == "hbp" for r in (old, new)):
            continue
        compared += 1
        assert old_rolls == new_rolls + 1
    assert compared >= 10


def test_swing_rates_in_the_kernel_follow_the_table():
    tuning = _tuning(swing_model=1.0, eye_control_blend=0.0)
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    pitcher = {"repertoire": {"fb": 55.0, "sl": 55.0, "cu": 55.0}, "control": 50.0}
    random.seed(5)
    for count in ((0, 0), (3, 0), (2, 2)):
        tally = {True: [0, 0], False: [0, 0]}
        for _ in range(12000):
            res = physics.simulate_pitch(
                batter=batter, pitcher=pitcher, tuning=tuning, count=count
            )
            if res.outcome == "hbp":
                continue
            tally[res.in_zone][0] += 1
            tally[res.in_zone][1] += res.swing
        zone, chase = PLAN_TABLE[f"{count[0]}-{count[1]}"]
        assert tally[True][1] / tally[True][0] == pytest.approx(zone, abs=0.02)
        assert tally[False][1] / tally[False][0] == pytest.approx(chase, abs=0.02)


def test_swing_table_is_cached_per_tuning_and_dropped_on_invalidate():
    tuning = _tuning(swing_model=1.0)
    first = physics._swing_logit_table(tuning)
    assert physics._swing_logit_table(tuning) is first
    assert physics._swing_logit_table(_tuning(swing_model=1.0)) is not first
    tuning.values["swing_count_table"] = {"0-0": {"zone": 0.9, "chase": 0.5}}
    tuning.invalidate_cache()
    logits, _center = physics._swing_logit_table(tuning)
    assert logits[(0, 0)][0] == pytest.approx(math.log(9.0))
    # A count (or a column) the table lacks reads the default table.
    assert logits[(1, 1)][1] == pytest.approx(math.log(0.317 / 0.683))


# --- command model ------------------------------------------------------------------


def test_command_model_off_is_the_old_formula():
    tuning = _tuning()
    for control in (20.0, 50.0, 65.0, 99.0, 120.0):
        for movement in (30.0, 50.0, 80.0):
            miss = max(0.0, (100.0 - control) / 100.0)
            mult = 1.0 + miss * 3.1 + max(0.0, (movement - 50.0) / 50.0) * 0.4
            assert physics._command_error(
                control=control, movement=movement, tuning=tuning
            ) == (0.09 * mult, 0.12 * mult)


def test_command_model_is_log_linear_monotonic_and_matches_at_the_centre():
    off = _tuning()
    on = _tuning(command_model=1.0)
    # 2.55 is the old multiplier at control 50: an average pitcher is unchanged.
    assert physics._command_error(control=50.0, movement=50.0, tuning=on) == (
        pytest.approx(physics._command_error(control=50.0, movement=50.0, tuning=off))
    )
    errors = [
        physics._command_error(control=float(c), movement=50.0, tuning=on)[0]
        for c in range(1, 101)
    ]
    assert all(a > b > 0.0 for a, b in zip(errors, errors[1:]))
    # A fixed share per point: e^(-0.02) per control point, 10 points = 18%.
    assert errors[10] / errors[0] == pytest.approx(math.exp(-0.2))
    assert errors[90] / errors[80] == pytest.approx(math.exp(-0.2))
    # Steeper than the old line for a good pitcher, wilder for a bad one.
    assert errors[79] < physics._command_error(control=80.0, movement=50.0, tuning=off)[0]
    assert errors[19] > physics._command_error(control=20.0, movement=50.0, tuning=off)[0]
    # The movement penalty and the commissioner's Command Variance still apply.
    assert physics._command_error(control=50.0, movement=80.0, tuning=on)[0] > errors[49]
    wide = _tuning(command_model=1.0, command_variance_scale=1.3)
    assert physics._command_error(control=50.0, movement=50.0, tuning=wide)[0] == (
        pytest.approx(errors[49] * 1.3)
    )


def test_command_model_reads_control_against_the_league_centre():
    centred = _tuning(command_model=1.0, pitcher_control_center=58.0)
    plain = _tuning(command_model=1.0)
    assert physics._command_error(control=58.0, movement=50.0, tuning=centred) == (
        pytest.approx(physics._command_error(control=50.0, movement=50.0, tuning=plain))
    )
    # Off, the centre is not read.
    off = _tuning(pitcher_control_center=58.0)
    assert physics._command_error(control=58.0, movement=50.0, tuning=off) == (
        physics._command_error(control=58.0, movement=50.0, tuning=_tuning())
    )


def _zone_rate(tuning, control, n=20000):
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    pitcher = {"repertoire": {"fb": 55.0, "sl": 55.0}, "control": control}
    random.seed(11)
    hits = 0
    for _ in range(n):
        hits += physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1)
        ).in_zone
    return hits / n


def test_fatigued_control_drives_the_zone_rate_under_the_command_model():
    # The kernel is handed the FATIGUED control (engine: control x command
    # factor); with the profile's stronger zone-target slope a pitcher who
    # has lost 30 points throws clearly fewer strikes (about 6 points of
    # zone rate, against 3 in the old model).
    tuning = _tuning(command_model=1.0, zone_target_control_scale=0.004)
    fresh, tired = _zone_rate(tuning, 70.0), _zone_rate(tuning, 40.0)
    assert fresh - tired > 0.04
    off = _tuning()
    assert fresh - tired > (_zone_rate(off, 70.0) - _zone_rate(off, 40.0)) + 0.015


# --- umpire model -------------------------------------------------------------------


def test_signed_edge_distance():
    box = dict(zone_bottom=1.5, zone_top=3.5, plate_half_width=0.8)
    dist = physics._signed_edge_distance
    assert dist(location=(0.0, 2.5), **box) == pytest.approx(-0.8)
    assert dist(location=(0.7, 2.5), **box) == pytest.approx(-0.1)
    assert dist(location=(-0.7, 2.5), **box) == pytest.approx(-0.1)
    assert dist(location=(0.0, 3.4), **box) == pytest.approx(-0.1)
    assert dist(location=(0.8, 2.5), **box) == pytest.approx(0.0)
    assert dist(location=(1.0, 2.5), **box) == pytest.approx(0.2)
    assert dist(location=(0.0, 1.2), **box) == pytest.approx(0.3)
    assert dist(location=(-1.0, 4.0), **box) == pytest.approx(0.5)
    # Outside it is the old edge distance.
    tuning = _tuning()
    for loc in ((1.0, 2.5), (0.0, 1.2), (-1.0, 4.0), (0.9, 3.6)):
        assert dist(location=loc, **box) == pytest.approx(
            physics._edge_distance(
                location=loc, zone_bottom=1.5, zone_top=3.5, tuning=tuning,
                plate_half_width=0.8,
            )
        )


def test_called_strike_chance_is_a_bounded_falling_curve():
    tuning = _tuning(umpire_model=1.0)
    even = physics._umpire_even_distance(
        catcher_fielding=50.0, balls=0, strikes=0, tuning=tuning
    )
    # The 50/50 point sits just INSIDE the rulebook edge (plan 2.1).
    assert even == pytest.approx(-0.055)
    assert physics._umpire_strike_probability(even, even, tuning) == pytest.approx(0.5)
    distances = [d / 100.0 for d in range(-80, 81)]
    chances = [
        physics._umpire_strike_probability(d, even, tuning) for d in distances
    ]
    assert all(a > b for a, b in zip(chances, chances[1:]))
    assert all(0.0 <= p <= 1.0 for p in chances)
    assert chances[0] > 0.999 and chances[-1] < 0.001
    # Absurd distances do not overflow.
    assert physics._umpire_strike_probability(1e6, even, tuning) == 0.0
    assert physics._umpire_strike_probability(-1e6, even, tuning) == 1.0


def test_framing_and_the_count_move_the_edge():
    tuning = _tuning(umpire_model=1.0, catcher_fa_center=55.0)

    def even(fa=55.0, balls=0, strikes=0):
        return physics._umpire_even_distance(
            catcher_fielding=fa, balls=balls, strikes=strikes, tuning=tuning
        )

    # Monotonic in catcher fielding, read against the league's catchers.
    edges = [even(fa=float(fa)) for fa in range(20, 96, 5)]
    assert all(a < b for a, b in zip(edges, edges[1:]))
    assert even(fa=55.0) == pytest.approx(-0.055)
    # Modest (owner decision 6): 10 points move the edge 0.0045 ft, under
    # two points of called-strike chance on a pitch right at the edge.
    assert even(fa=65.0) - even(fa=55.0) == pytest.approx(0.0045)
    at_edge = physics._umpire_strike_probability(even(), even(fa=65.0), tuning)
    assert 0.5 < at_edge < 0.52
    # The zone grows in a hitter's count and shrinks in a pitcher's.
    assert even(balls=3, strikes=0) > even() > even(balls=0, strikes=2)
    assert even(balls=3, strikes=0) - even() == pytest.approx(3 * 0.012)
    # The offset stays negative in every count for an average catcher.
    assert all(even(balls=b, strikes=s) < 0.0 for b, s in COUNTS)


def test_umpire_model_calls_takes_by_distance_in_the_kernel():
    tuning = _tuning(umpire_model=1.0)
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    pitcher = {"repertoire": {"fb": 55.0, "sl": 55.0}, "control": 50.0}
    random.seed(3)
    deep = {True: [0, 0], False: [0, 0]}
    near = [0, 0]
    for _ in range(40000):
        res = physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1)
        )
        if res.swing or res.outcome == "hbp":
            continue
        assert res.outcome in ("strike", "ball")
        signed = physics._signed_edge_distance(
            location=res.location, zone_bottom=1.5 - 0.12, zone_top=3.5 + 0.12,
            plate_half_width=0.708 + 0.12,
        )
        # called_in_zone: more likely a strike than a ball.
        assert res.called_in_zone == (signed <= -0.055)
        if abs(signed) > 0.4:
            deep[signed < 0][0] += 1
            deep[signed < 0][1] += res.outcome == "strike"
        elif abs(signed + 0.055) < 0.03:
            near[0] += 1
            near[1] += res.outcome == "strike"
    # Middle-middle is a strike, well outside is a ball, the edge is a coin.
    assert deep[True][0] > 200 and deep[True][1] / deep[True][0] > 0.98
    assert deep[False][0] > 200 and deep[False][1] / deep[False][0] < 0.02
    assert near[0] > 200 and near[1] / near[0] == pytest.approx(0.5, abs=0.1)


def test_umpire_model_does_not_read_the_knobs_it_replaces():
    replaced = {
        "called_zone_shrink_ft": 0.3, "umpire_margin_ft": 0.5,
        "framing_margin_scale": 0.5, "framing_strike_chance": 0.9,
        "framing_prob_scale": 0.9,
    }
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    pitcher = {"repertoire": {"fb": 55.0, "sl": 55.0}, "control": 50.0}
    context = {"catcher_fielding": 70.0}
    results = []
    for tuning in (_tuning(umpire_model=1.0), _tuning(umpire_model=1.0, **replaced)):
        random.seed(8)
        results.append(
            [
                physics.simulate_pitch(
                    batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1),
                    context=context,
                )
                for _ in range(500)
            ]
        )
    assert results[0] == results[1]


# --- hit by pitch -------------------------------------------------------------------


def test_inside_is_plus_x_for_a_right_handed_batter():
    # The kernel's only handed x: a right-hander's arm-side pitches (fb, si,
    # cu) break toward +x, his glove-side pitches toward -x, and a
    # left-hander's the other way. Arm-side run moves IN on a same-handed
    # batter, so +x is the right-handed batter's side of the plate.
    tuning = _tuning(pitch_break_sd=0.0)
    for pitch in ("fb", "si", "cu"):
        assert physics._pitch_break(
            pitch_type=pitch, movement=50.0, pitch_quality=50.0, pitcher_hand="R",
            tuning=tuning,
        )[0] > 0.0
        assert physics._pitch_break(
            pitch_type=pitch, movement=50.0, pitch_quality=50.0, pitcher_hand="L",
            tuning=tuning,
        )[0] < 0.0
    for pitch in ("sl", "cb"):
        assert physics._pitch_break(
            pitch_type=pitch, movement=50.0, pitch_quality=50.0, pitcher_hand="R",
            tuning=tuning,
        )[0] < 0.0
    edge = 0.708 + 0.12
    tuning = _tuning(hbp_model=1.0)

    def chance(x, side):
        return physics._hbp_inside_chance(
            x=x, batter_side=side, zone_half_width=edge, tuning=tuning
        )

    assert chance(edge + 0.8, "R") > 0.0 and chance(-(edge + 0.8), "R") == 0.0
    assert chance(-(edge + 0.8), "L") > 0.0 and chance(edge + 0.8, "L") == 0.0
    assert chance(edge + 0.8, "R") == chance(-(edge + 0.8), "L")


def test_hbp_chance_ramps_with_distance_inside_and_is_bounded():
    tuning = _tuning(hbp_model=1.0)
    edge = 0.708 + 0.12
    chances = [
        physics._hbp_inside_chance(
            x=edge + step / 100.0, batter_side="R", zone_half_width=edge,
            tuning=tuning,
        )
        for step in range(0, 200)
    ]
    assert all(a <= b for a, b in zip(chances, chances[1:]))
    assert all(0.0 <= p <= 0.2 for p in chances)
    # Nothing in the zone or within 0.35 ft of its edge; the full rate from
    # 0.95 ft (min + span) on.
    assert chances[35] == 0.0 and chances[36] > 0.0
    assert chances[95] == pytest.approx(0.2) and chances[-1] == pytest.approx(0.2)
    assert physics._hbp_inside_chance(
        x=0.0, batter_side="R", zone_half_width=edge, tuning=tuning
    ) == 0.0


def _hbp_sample(tuning, *, control, bats, n=25000, seed=17, hand="R"):
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": bats}
    pitcher = {
        "repertoire": {"fb": 55.0, "sl": 55.0, "cu": 55.0}, "control": control,
        "hand": hand,
    }
    random.seed(seed)
    hit = []
    for _ in range(n):
        res = physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1)
        )
        if res.outcome == "hbp":
            hit.append(res)
    return hit


def test_hbp_model_only_hits_batters_with_pitches_well_inside():
    tuning = _tuning(hbp_model=1.0)
    reach = 0.708 + 0.12 + 0.35
    right = _hbp_sample(tuning, control=35.0, bats="R")
    left = _hbp_sample(tuning, control=35.0, bats="L")
    assert len(right) > 30 and len(left) > 30
    assert all(not res.in_zone and not res.swing for res in right + left)
    assert all(res.location[0] > reach for res in right)
    assert all(res.location[0] < -reach for res in left)
    # A switch hitter stands opposite the pitcher's hand.
    switch = _hbp_sample(tuning, control=35.0, bats="S", hand="R")
    assert switch and all(res.location[0] < -reach for res in switch)
    # The old model hits batters with pitches in the strike zone.
    old = _hbp_sample(_tuning(), control=35.0, bats="R")
    assert any(res.in_zone for res in old)


def test_hbp_rate_falls_with_control_through_location_alone():
    tuning = _tuning(hbp_model=1.0, command_model=1.0)
    wild = len(_hbp_sample(tuning, control=35.0, bats="R", n=40000))
    sharp = len(_hbp_sample(tuning, control=65.0, bats="R", n=40000))
    assert wild > 1.3 * sharp > 0


def test_hbp_model_rolls_only_for_a_pitch_that_can_reach_the_batter(monkeypatch):
    # Between the HBP check and the swing decision the kernel draws once if
    # the pitch can reach the batter and not at all if it cannot.
    tuning = _tuning(hbp_model=1.0, swing_model=1.0, hbp_inside_rate=0.5)
    calls = _count_rolls(monkeypatch)
    marks = {}
    real_chance, real_swing = physics._hbp_inside_chance, physics._swing_probability

    def chance_spy(**kwargs):
        marks["chance"] = real_chance(**kwargs)
        marks["at_hbp"] = len(calls)
        return marks["chance"]

    def swing_spy(**kwargs):
        marks["at_swing"] = len(calls)
        return real_swing(**kwargs)

    monkeypatch.setattr(physics, "_hbp_inside_chance", chance_spy)
    monkeypatch.setattr(physics, "_swing_probability", swing_spy)
    batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
    pitcher = {"repertoire": {"fb": 55.0, "sl": 55.0}, "control": 30.0}
    seen = {"out_of_reach": 0, "missed": 0, "hit": 0}
    random.seed(23)
    for _ in range(6000):
        marks.clear()
        del calls[:]
        res = physics.simulate_pitch(
            batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 1)
        )
        if res.outcome == "hbp":
            seen["hit"] += 1
            assert marks["chance"] > 0.0 and "at_swing" not in marks
            assert len(calls) == marks["at_hbp"] + 1
        elif marks["chance"] > 0.0:
            seen["missed"] += 1
            assert marks["at_swing"] == marks["at_hbp"] + 1
        else:
            seen["out_of_reach"] += 1
            assert marks["at_swing"] == marks["at_hbp"]
    assert seen["out_of_reach"] > 5000 and seen["missed"] > 10 and seen["hit"] > 5


# --- intentional walk ---------------------------------------------------------------


def _ibb(tuning, *, batter, on_deck, bases=None, inning=8, outs=1, score_diff=0):
    return _should_intentional_walk(
        bases=bases or BaseState(second=_batter("r2")),
        batter=batter, pitcher=_pitcher(), inning=inning, outs=outs,
        score_diff=score_diff, tuning=tuning, on_deck=on_deck,
    )


def _ibb_chance(monkeypatch, tuning, **kwargs) -> float:
    """The chance the rule rolls against (0.0 when it does not roll)."""
    seen = []

    class Recorder:
        def __lt__(self, chance):
            seen.append(chance)
            return False

    monkeypatch.setattr(engine.random, "random", lambda: Recorder())
    assert _ibb(tuning, **kwargs) is False
    return seen[0] if seen else 0.0


def test_ibb_model_off_ignores_the_on_deck_hitter(monkeypatch):
    tuning = _tuning()
    star, scrub = _batter("star", contact=90.0, power=90.0), _batter("scrub")
    monkeypatch.setattr(engine.random, "random", lambda: 0.0)
    # The old rule: an absolute threshold, late and close only.
    assert _ibb(tuning, batter=star, on_deck=scrub) is True
    assert _ibb(tuning, batter=star, on_deck=star) is True
    assert _ibb(tuning, batter=star, on_deck=None) is True
    assert _ibb(tuning, batter=star, on_deck=scrub, inning=3) is False
    assert _ibb(tuning, batter=_batter("avg"), on_deck=scrub) is False


def test_ibb_chance_follows_the_gap_to_the_on_deck_hitter(monkeypatch):
    tuning = _tuning(ibb_model=1.0)
    on_deck = _batter("next", contact=50.0, power=50.0)
    chances = [
        _ibb_chance(
            monkeypatch, tuning, on_deck=on_deck,
            batter=_batter("b", contact=50.0 + gap, power=50.0 + gap),
        )
        for gap in range(-10, 21)
    ]
    assert all(a <= b for a, b in zip(chances, chances[1:]))
    assert all(0.0 <= p <= 0.35 for p in chances)
    # No chance (and no roll) up to a 2-point gap, the full chance from 7.
    assert chances[10 + 2] == 0.0 and chances[10 + 3] > 0.0
    assert chances[10 + 7] == pytest.approx(0.35)
    assert chances[-1] == pytest.approx(0.35)
    assert chances[10 + 4] == pytest.approx(0.35 * (4 - 2) / (7 - 2))
    # A star with another star behind him is pitched to; so is anyone when
    # the on-deck hitter is unknown.
    star = _batter("star", contact=90.0, power=90.0)
    assert _ibb_chance(monkeypatch, tuning, batter=star, on_deck=star) == 0.0
    assert _ibb_chance(monkeypatch, tuning, batter=star, on_deck=None) == 0.0
    # The absolute threshold of the old rule is not read: a modest hitter
    # with a weak one behind him can be walked.
    modest = _batter("modest", contact=55.0, power=55.0)
    weak = _batter("weak", contact=40.0, power=40.0)
    assert _ibb_chance(monkeypatch, tuning, batter=modest, on_deck=weak) == (
        pytest.approx(0.35)
    )


def test_ibb_needs_first_base_open_and_a_runner_in_scoring_position(monkeypatch):
    tuning = _tuning(ibb_model=1.0)
    star, weak = _batter("star", contact=90.0, power=90.0), _batter("weak")
    runner = _batter("r")
    monkeypatch.setattr(engine.random, "random", lambda: 0.0)
    assert _ibb(tuning, batter=star, on_deck=weak, bases=BaseState(second=runner))
    assert _ibb(tuning, batter=star, on_deck=weak, bases=BaseState(third=runner))
    assert not _ibb(tuning, batter=star, on_deck=weak, bases=BaseState())
    assert not _ibb(
        tuning, batter=star, on_deck=weak,
        bases=BaseState(first=runner, second=runner),
    )
    # Two outs with a runner on second: the old rule never walked him.
    two_out = dict(batter=star, on_deck=weak, outs=2, bases=BaseState(second=runner))
    assert _ibb(tuning, **two_out)
    assert not _ibb(_tuning(ibb_batter_threshold=40.0), **two_out)


def test_ibb_is_mostly_late_and_close_and_rare_with_nobody_out(monkeypatch):
    tuning = _tuning(ibb_model=1.0)
    star, weak = _batter("star", contact=90.0, power=90.0), _batter("weak")

    def chance(**kwargs):
        return _ibb_chance(monkeypatch, tuning, batter=star, on_deck=weak, **kwargs)

    late = chance(inning=8, score_diff=1)
    assert late == pytest.approx(0.35)
    assert chance(inning=3, score_diff=0) == pytest.approx(0.035)
    assert chance(inning=8, score_diff=5) == pytest.approx(0.035)
    assert chance(inning=8, outs=0) == pytest.approx(0.35 * 0.3)
    assert chance(inning=2, outs=0) == pytest.approx(0.35 * 0.1 * 0.3)


def test_the_engine_hands_the_rule_the_real_on_deck_hitter(monkeypatch):
    calls = []
    real = engine._should_intentional_walk

    def spy(**kwargs):
        calls.append((kwargs["batter"].player_id, kwargs["on_deck"].player_id))
        return real(**kwargs)

    monkeypatch.setattr(engine, "_should_intentional_walk", spy)
    result = _play("calibration", "CAL01", "CAL02", 3, {"ibb_model": 1.0})
    assert len(calls) == result.totals["pa"]
    assert all(batter != on_deck for batter, on_deck in calls)
    # Each club's plate appearances in order: the on-deck hitter of one is
    # the batter of the next, innings apart or not. The only misses are
    # pinch hitters (the man on deck was replaced before he batted). The
    # hitter two spots down -- the off-by-one this guards -- never matches.
    side_of = {
        line["player_id"]: side
        for side, lines in result.metadata["batting_lines"].items()
        for line in lines
    }
    for side in ("away", "home"):
        club = [call for call in calls if side_of[call[0]] == side]
        assert len(club) >= 27
        assert all(side_of[on_deck] == side for _batter_id, on_deck in club)
        misses = sum(
            on_deck != nxt[0] for (_b, on_deck), nxt in zip(club, club[1:])
        )
        assert misses <= 3, (side, misses)


# --- commissioner sliders (owner decision 9) -----------------------------------------

LEGACY_SLIDER_KEYS = (
    "walk_scale", "zone_swing_scale", "chase_scale",
    "two_strike_aggression_scale", "two_strike_zone_protect",
)
MODEL1_SLIDER_KEYS = (
    "swing_walk_scale", "swing_zone_scale", "swing_chase_scale",
    "swing_two_strike_scale",
)


def _slider_keys(sections):
    return [spec.key for _label, specs in sections for spec in specs]


def test_sliders_are_untouched_while_a_league_runs_the_old_model():
    assert tuning_sections() is _TUNING_SECTIONS
    assert tuning_sections(0.0) is _TUNING_SECTIONS
    keys = _slider_keys(_TUNING_SECTIONS)
    assert all(key in keys for key in LEGACY_SLIDER_KEYS)
    assert not any(key in keys for key in MODEL1_SLIDER_KEYS)
    by_key = {s.key: s for _l, specs in _TUNING_SECTIONS for s in specs}
    assert by_key["walk_scale"].label == "Walk Rate"
    assert (by_key["walk_scale"].min_value, by_key["walk_scale"].max_value) == (0.6, 1.2)
    assert by_key["two_strike_zone_protect"].label == "Two-Strike Protect"


def test_model_1_sliders_are_rebased_and_the_two_strike_pair_is_merged():
    sections = tuning_sections(1.0)
    assert [label for label, _ in sections] == [label for label, _ in _TUNING_SECTIONS]
    keys = _slider_keys(sections)
    assert not any(key in keys for key in LEGACY_SLIDER_KEYS)
    assert sorted(k for k in keys if k.startswith("swing_")) == sorted(MODEL1_SLIDER_KEYS)
    # One slider fewer (the merge), every other slider the same object.
    old_keys = _slider_keys(_TUNING_SECTIONS)
    assert len(keys) == len(old_keys) - 1
    old = {s.key: s for _l, specs in _TUNING_SECTIONS for s in specs}
    new = {s.key: s for _l, specs in sections for s in specs}
    for key in set(old_keys) - set(LEGACY_SLIDER_KEYS):
        assert new[key] is old[key]
    # Same slots, same labels for the three that keep working.
    swapped = [
        _SWING_MODEL_SLIDERS[k].key if _SWING_MODEL_SLIDERS.get(k) else k
        for k in old_keys if k != "two_strike_zone_protect"
    ]
    assert keys == swapped
    assert new["swing_walk_scale"].label == "Walk Rate"
    assert new["swing_zone_scale"].label == "Zone Swing"
    assert new["swing_chase_scale"].label == "Chase"
    assert _SWING_MODEL_SLIDERS["two_strike_zone_protect"] is None
    # 1.0 = MLB: a registered numeric knob whose default is 1.0, inside range.
    for key in MODEL1_SLIDER_KEYS:
        assert DEFAULT_TUNING[key] == 1.0
        assert new[key].min_value < 1.0 < new[key].max_value
        assert "1.0 = MLB" in new[key].description
        assert settings._sanitize_overrides({key: 1.2}) == {key: 1.2}
    # The catalog itself was not edited in place.
    assert _slider_keys(_TUNING_SECTIONS) == old_keys


def test_model_1_sliders_move_the_swing_model():
    def rates(**sliders):
        tuning = _tuning(swing_model=1.0, eye_control_blend=0.0, **sliders)
        return {
            (zone, strikes): _swing(tuning, in_zone=zone, balls=1, strikes=strikes)
            for zone in (True, False) for strikes in (1, 2)
        }

    base = rates()
    assert base[(True, 1)] == pytest.approx(PLAN_TABLE["1-1"][0])

    def odds(p):
        return p / (1.0 - p)

    zone = rates(swing_zone_scale=1.2)
    assert odds(zone[(True, 1)]) == pytest.approx(1.2 * odds(base[(True, 1)]))
    assert zone[(False, 1)] == base[(False, 1)]
    chase = rates(swing_chase_scale=0.8)
    assert odds(chase[(False, 2)]) == pytest.approx(0.8 * odds(base[(False, 2)]))
    assert chase[(True, 2)] == base[(True, 2)]
    # More walks = fewer chases, by the gain; strikes in the zone untouched.
    walk = rates(swing_walk_scale=1.1)
    assert odds(walk[(False, 1)]) == pytest.approx(
        odds(base[(False, 1)]) / 1.1 ** 1.33
    )
    assert walk[(True, 1)] == base[(True, 1)]
    assert rates(swing_walk_scale=0.9)[(False, 1)] > base[(False, 1)]
    # The merged two-strike slider: both columns, two strikes only.
    two = rates(swing_two_strike_scale=1.5)
    assert odds(two[(True, 2)]) == pytest.approx(1.5 * odds(base[(True, 2)]))
    assert odds(two[(False, 2)]) == pytest.approx(1.5 * odds(base[(False, 2)]))
    assert two[(True, 1)] == base[(True, 1)] and two[(False, 1)] == base[(False, 1)]
    # Monotonic over each slider's whole range, never out of bounds.
    specs = {s.key: s for s in _SWING_MODEL_SLIDERS.values() if s}
    for key, cell, rising in (
        ("swing_zone_scale", (True, 1), True),
        ("swing_chase_scale", (False, 1), True),
        ("swing_walk_scale", (False, 1), False),
        ("swing_two_strike_scale", (True, 2), True),
    ):
        steps = 30
        span = specs[key].max_value - specs[key].min_value
        values = [
            rates(**{key: specs[key].min_value + span * i / steps})[cell]
            for i in range(steps + 1)
        ]
        ordered = values if rising else values[::-1]
        assert all(a < b for a, b in zip(ordered, ordered[1:])), key
        assert all(0.01 <= v <= 0.99 for v in values), key


def test_conversion_leaves_defaults_and_unrelated_keys_alone():
    convert = settings.convert_swing_slider_overrides
    assert convert({}) == {}
    assert convert({"hr_scale": 1.1}) == {"hr_scale": 1.1}
    at_default = {
        "walk_scale": 0.83, "zone_swing_scale": 0.91, "chase_scale": 0.69,
        "two_strike_aggression_scale": 1.05, "two_strike_zone_protect": 0.63,
    }
    # The frozen legacy defaults are today's defaults.
    assert at_default == {k: DEFAULT_TUNING[k] for k in at_default}
    assert at_default == settings._LEGACY_SWING_DEFAULTS
    # A slider stored at its old default is 1.0 = not stored.
    assert convert(at_default) == at_default


def test_conversion_maps_each_legacy_slider_to_its_odds_ratio():
    convert = settings.convert_swing_slider_overrides
    specs = {s.key: s for s in _SWING_MODEL_SLIDERS.values() if s}

    def one(legacy_key, value, new_key):
        stored = {legacy_key: value, "hr_scale": 1.1}
        out = convert(stored)
        # The legacy key is kept, nothing else is touched, the input is not
        # mutated.
        assert stored == {legacy_key: value, "hr_scale": 1.1}
        assert {k: v for k, v in out.items() if k != new_key} == stored
        return out.get(new_key, 1.0)

    def odds(p):
        return p / (1.0 - p)

    # Zone Swing: the old slider scaled a 0.62 swing chance.
    got = one("zone_swing_scale", 1.0, "swing_zone_scale")
    assert got == pytest.approx(odds(0.62) / odds(0.62 * 0.91), abs=0.006)
    assert got > 1.0 > one("zone_swing_scale", 0.8, "swing_zone_scale")
    # Chase: it scaled the chase chance (0.28 x 0.69 / 0.83 at the defaults).
    ref = 0.28 * 0.69 / 0.83
    got = one("chase_scale", 0.9, "swing_chase_scale")
    assert got == pytest.approx(odds(0.28 * 0.9 / 0.83) / odds(ref), abs=0.006)
    assert one("chase_scale", 0.5, "swing_chase_scale") < 1.0
    # Walk Rate: it DIVIDED the chase chance, so more walk = fewer chases;
    # the new slider divides the chase odds by slider ** gain.
    got = one("walk_scale", 1.0, "swing_walk_scale")
    assert got > 1.0 > one("walk_scale", 0.7, "swing_walk_scale")
    chase_odds_ratio = odds(0.28 * 0.69 / 1.0) / odds(ref)
    assert got ** -1.33 == pytest.approx(chase_odds_ratio, abs=0.01)
    # Monotonic over each old slider's range, and inside the new range.
    for legacy_key, lo, hi in (
        ("walk_scale", 0.6, 1.2), ("zone_swing_scale", 0.6, 1.2),
        ("chase_scale", 0.4, 1.0),
    ):
        spec = _SWING_MODEL_SLIDERS[legacy_key]
        values = [
            one(legacy_key, lo + (hi - lo) * i / 30, spec.key) for i in range(31)
        ]
        assert all(a <= b for a, b in zip(values, values[1:])), legacy_key
        assert values[0] < 1.0 < values[-1], legacy_key
        assert all(spec.min_value <= v <= spec.max_value for v in values)
    # Out-of-range and nonsense values are held inside the slider.
    assert one("zone_swing_scale", 50.0, "swing_zone_scale") == specs[
        "swing_zone_scale"
    ].max_value
    assert one("chase_scale", 0.0, "swing_chase_scale") == specs[
        "swing_chase_scale"
    ].min_value
    # A walk_scale of 0 was "no division" in the old model = walk_scale 1.0.
    assert one("walk_scale", 0.0, "swing_walk_scale") == one(
        "walk_scale", 1.0, "swing_walk_scale"
    )


def test_conversion_reproduces_the_old_swing_chance_in_the_new_model():
    # The point of the mapping: the converted slider gives the average
    # hitter the swing chance the stored slider gave him, relative to the
    # default. Checked on a count whose table rate is the old default rate.
    for stored in (0.7, 0.85, 1.0, 1.15):
        new = settings.convert_swing_slider_overrides({"zone_swing_scale": stored})
        old_default = 0.62 * 0.91
        table = {"0-0": {"zone": old_default, "chase": 0.2}}
        tuning = _tuning(
            swing_model=1.0, swing_count_table=table,
            swing_zone_scale=new.get("swing_zone_scale", 1.0),
        )
        assert _swing(tuning, in_zone=True) == pytest.approx(0.62 * stored, abs=0.004)


def test_two_strike_sliders_merge_into_one():
    convert = settings.convert_swing_slider_overrides
    key = "swing_two_strike_scale"
    more_aggressive = convert({"two_strike_aggression_scale": 1.3})
    more_protect = convert({"two_strike_zone_protect": 0.8})
    both = convert({"two_strike_aggression_scale": 1.3, "two_strike_zone_protect": 0.8})
    assert more_aggressive[key] > 1.0 and more_protect[key] > 1.0
    assert both[key] > max(more_aggressive[key], more_protect[key])
    assert convert({"two_strike_zone_protect": 0.45})[key] < 1.0
    assert convert({"two_strike_aggression_scale": 0.8})[key] < 1.0
    # One value from the pair, and only that one new key.
    assert set(both) == {
        "two_strike_aggression_scale", "two_strike_zone_protect", key,
    }
    # Opposite moves partly cancel.
    mixed = convert({"two_strike_aggression_scale": 1.3, "two_strike_zone_protect": 0.5})
    assert convert({"two_strike_zone_protect": 0.5})[key] < mixed.get(key, 1.0) < (
        more_aggressive[key]
    )
    # Both old sliders at their maximum is still inside the new slider (it
    # is not clipped); only values from outside the old ranges are held.
    spec = _SWING_MODEL_SLIDERS["two_strike_aggression_scale"]
    extreme = convert({"two_strike_aggression_scale": 1.4, "two_strike_zone_protect": 0.9})
    assert both[key] < extreme[key] < spec.max_value
    beyond = convert({"two_strike_aggression_scale": 9.0, "two_strike_zone_protect": 1.0})
    assert beyond[key] == spec.max_value


def test_conversion_never_overwrites_a_value_already_on_the_new_scale():
    convert = settings.convert_swing_slider_overrides
    stored = {"walk_scale": 1.1, "swing_walk_scale": 0.95, "chase_scale": 0.5}
    out = convert(stored)
    assert out["swing_walk_scale"] == 0.95
    assert out["swing_chase_scale"] < 1.0


# The tests of the stored overrides file -- when a league's sliders are
# converted, what a save keeps, the slider set the API serves -- are in
# tests/test_r5_flip_sliders.py: all of that follows the league's ENGINE
# GENERATION, not a ``swing_model`` key in the file.
