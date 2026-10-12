"""Release 5: platoon and handedness (audit H7; decisions 6 and 7; Release 5
owner decisions 5, 10 and 11; RELEASE5_PLAN.md 2.3).

- ``physics_sim.platoon.platoon_shift`` is the one source of the handedness
  advantage ``h`` and the hitter's vl split ``d_hand``. At the default knobs
  it returns exactly what the five readers hard-coded before (frozen copies
  below), and whole default-tuning games match digests pinned before any
  Release 5 platoon code existed.
- Switched on (``scripts/kpi_profiles/r5_platoon.json``): the right-handed
  batter's bonus is sized from the league's mix of batting sides so LHP and
  RHP come out equal, switch hitters take the full bonus of the side they
  bat from, vl is read against the league's own mean for the hitter's side,
  and the situational Power bonuses are added after the bat-speed knee.
- The lineup auto-fill reads the same pair from the same tuning.
- New players' batting sides follow MLB's mix at C / 2B / 3B / SS.
- ``vl`` is labelled as a platoon split, not "Vision".
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine import (
    _batter_context,
    _batter_offense_score,
    _matchup_score,
    _platoon_bonus,
)
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.physics import _batter_power_bat_speed, _power_bat_speed
from physics_sim.platoon import (
    handedness_scales,
    platoon_needs_centers,
    platoon_shift,
    platoon_shift_values,
)
from utils import lineup_autofill
from utils.lineup_autofill import (
    _platoon_adjustment,
    _slot_components,
    auto_fill_lineup_for_team,
    platoon_tuning,
)

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r5_platoon.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

# The value of every knob this area added, which must be the number the
# engine hard-coded before it.
NEW_KNOBS = {
    "handedness_lhb_scale": 1.0,
    "handedness_rhb_scale": 1.0,
    "handedness_balance_strength": 0.0,
    "handedness_balance_bias": 0.0,
    "handedness_balance_min": 0.35,
    "handedness_balance_max": 1.0,
    "platoon_rhp_counter_scale": 0.35,
    "platoon_vl_center_enabled": 0.0,
    "platoon_power_after_knee": 0.0,
}
# A league like the generated fixture: right-handed heavy, vl tilted by side.
LEAGUE = {
    "hitter_bats_share_l": 0.24,
    "hitter_bats_share_r": 0.65,
    "hitter_bats_share_s": 0.11,
    "hitter_vl_center_l": 45.0,
    "hitter_vl_center_r": 53.5,
    "hitter_vl_center_s": 49.25,
}
SIDES = ("L", "R", "S")
HANDS = ("L", "R")


def _batter(bats="R", vl=50.0, *, ch=50.0, ph=50.0, eye=50.0, pid="b1") -> BatterRatings:
    return BatterRatings.from_row(
        {
            "player_id": pid, "bats": bats, "primary_position": "LF",
            "ch": str(ch), "ph": str(ph), "vl": str(vl), "eye": str(eye),
            "gf": "50", "pl": "50", "fa": "50", "arm": "50", "sp": "50",
        }
    )


def _pitcher(throws="R", *, control=50.0, vl=50.0) -> PitcherRatings:
    return PitcherRatings.from_row(
        {
            "player_id": "p1", "bats": throws, "throws": throws,
            "control": str(control), "vl": str(vl), "fb": "60",
        }
    )


# --- registration ----------------------------------------------------------


def test_new_knobs_are_registered_with_the_values_the_engine_hard_coded():
    for key, value in NEW_KNOBS.items():
        assert DEFAULT_TUNING[key] == value, key
    assert "platoon_bat_speed_per_point" in DEFAULT_TUNING
    assert DEFAULT_TUNING["handedness_switch_bonus"] == 0.5
    # from_overrides silently drops a key that is not registered.
    bumped = {key: value + 0.125 for key, value in NEW_KNOBS.items()}
    tuning = load_tuning(bumped)
    for key, value in bumped.items():
        assert tuning.get(key) == value, key


def test_the_profile_switches_every_platoon_term_on():
    for key in PROFILE:
        assert key in DEFAULT_TUNING, key
    assert PROFILE["handedness_balance_strength"] == 1.0  # owner decision 5
    assert PROFILE["handedness_switch_bonus"] == 1.0  # decision 6
    assert PROFILE["platoon_power_after_knee"] == 1
    assert PROFILE["platoon_vl_center_enabled"] == 1
    assert 0.25 <= PROFILE["platoon_bat_speed_per_point"] <= 0.45
    tuning = load_tuning(PROFILE)
    assert platoon_needs_centers(tuning)
    assert not platoon_needs_centers(load_tuning())
    assert not platoon_needs_centers(None)


# --- frozen copies of the code before Release 5 -----------------------------


def _legacy_handedness(batter_hand, pitcher_hand, switch_bonus=0.5):
    if batter_hand == "S":
        return switch_bonus
    if batter_hand == pitcher_hand:
        return -1.0
    return 1.0


def _legacy_vl_delta(vs_left, pitcher_hand):
    d = vs_left - 50.0
    if (pitcher_hand or "R").upper() == "L":
        return d
    return -0.35 * d


def _legacy_platoon_bonus(batter, pitcher):
    hand = (pitcher.throws or "R").upper()
    bats = (batter.bats or "R").upper()
    if bats == "S":
        h = 0.5
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    return 2.0 * h + 0.2275 * _legacy_vl_delta(batter.vs_left, hand)


def _legacy_batter_context(batter, pitcher, tuning, *, tto=1):
    pitcher_hand = (pitcher.throws or "R").upper()
    batter_hand = (batter.bats or "R").upper()
    eye = batter.eye * 0.8 + (100.0 - pitcher.control) * 0.2
    contact = batter.contact
    power = batter.power
    handedness = _legacy_handedness(
        batter_hand, pitcher_hand, tuning.get("handedness_switch_bonus", 0.5)
    )
    contact += handedness * tuning.get("handedness_contact_bonus", 2.0)
    power += handedness * tuning.get("handedness_power_bonus", 2.0)
    eye += handedness * tuning.get("handedness_eye_bonus", 2.0)
    max_passes = int(tuning.get("tto_max_passes", 3.0))
    tto_extra = float(max(0, min(tto, max_passes) - 1))
    if tto_extra:
        contact += tto_extra * tuning.get("tto_contact_bonus", 0.0)
        eye += tto_extra * tuning.get("tto_eye_bonus", 0.0)
        power += tto_extra * tuning.get("tto_power_bonus", 0.0)
    platoon_chase = 0.0
    vs_left_diff = _legacy_vl_delta(batter.vs_left, pitcher_hand)
    contact += vs_left_diff * tuning.get("platoon_contact_scale", 0.25)
    power += vs_left_diff * tuning.get("platoon_power_scale", 0.2)
    eye += vs_left_diff * tuning.get("platoon_eye_scale", 0.3)
    platoon_chase -= vs_left_diff * tuning.get("platoon_chase_scale", 0.0015)
    return {
        "contact": max(1.0, min(100.0, contact)),
        "power": max(1.0, min(100.0, power)),
        "eye": max(1.0, min(100.0, eye)),
        "platoon_chase": platoon_chase,
    }


def _legacy_matchup_score(pitcher, upcoming_batters):
    pitcher_hand = (pitcher.throws or "R").upper()
    score = 0.0
    for batter in upcoming_batters:
        batter_hand = (batter.bats or "R").upper()
        if batter_hand == "S":
            score -= 0.5
            effective_side = "L" if pitcher_hand == "R" else "R"
        else:
            effective_side = batter_hand
            score += 1.0 if batter_hand == pitcher_hand else -1.0
        if effective_side == "L":
            score += (pitcher.vs_left - 50.0) / 25.0
    return score


def _legacy_lineup_shift(player, vs_hand):
    hand = "L" if str(vs_hand or "R").upper().startswith("L") else "R"
    bats = str(getattr(player, "bats", "") or "R").upper()
    if bats == "S":
        h = 0.5
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    d = float(getattr(player, "vl", 50) or 50) - 50.0
    if hand != "L":
        d = -0.35 * d
    return h, d


VL_VALUES = (20.0, 37.0, 45.5, 50.0, 53.6, 61.0, 88.0)


# --- the helper at the defaults: exactly the old constants ------------------


@pytest.mark.parametrize("tuning", [None, load_tuning(), load_tuning(LEAGUE)],
                         ids=["no tuning", "defaults", "league centres supplied"])
def test_default_shift_is_the_pair_the_engine_hard_coded(tuning):
    """Every hand combination, exactly; the rating centres and batting-side
    shares a live game always supplies change nothing while the switches are
    off."""
    for bats in ("L", "R", "S", "", None, "B", "l", "s"):
        for hand in ("L", "R", "", None, "l"):
            for vl in VL_VALUES:
                side = str(bats or "R").upper()
                throws = str(hand or "R").upper()
                h, d = platoon_shift_values(bats, vl, hand, tuning)
                assert h == _legacy_handedness(side, throws), (bats, hand)
                assert d == _legacy_vl_delta(vl, throws), (bats, hand, vl)
                assert platoon_shift(_batter(bats or "R", vl), hand, tuning) == (
                    platoon_shift_values(bats or "R", vl, hand, tuning)
                )


def test_default_batter_context_is_the_old_one():
    for tuning in (load_tuning(), load_tuning(LEAGUE)):
        for bats in SIDES:
            for throws in HANDS:
                for vl in VL_VALUES:
                    for ph in (38.0, 50.0, 51.5, 53.0, 71.0, 99.0):
                        for tto in (1, 2, 3):
                            batter = _batter(bats, vl, ch=44.0, ph=ph, eye=57.0)
                            pitcher = _pitcher(throws, control=61.0)
                            got = _batter_context(batter, pitcher, tuning, tto=tto)
                            old = _legacy_batter_context(batter, pitcher, tuning, tto=tto)
                            for key, value in old.items():
                                assert got[key] == value, (key, bats, throws, vl, ph, tto)
                            assert got["power_base"] == ph


def test_default_offense_and_bullpen_scores_are_the_old_ones():
    tuning = load_tuning(LEAGUE)
    batters = [
        _batter(bats, vl, ch=40.0 + 3 * i, ph=62.0 - 2 * i, pid=f"b{i}")
        for i, (bats, vl) in enumerate(
            (b, v) for b in SIDES for v in (33.0, 50.0, 72.0)
        )
    ]
    for throws in HANDS:
        for pvl in (35.0, 50.0, 68.0):
            pitcher = _pitcher(throws, vl=pvl)
            for batter in batters:
                old = _legacy_platoon_bonus(batter, pitcher)
                assert _platoon_bonus(batter, pitcher) == old
                assert _platoon_bonus(batter, pitcher, tuning) == old
                assert _batter_offense_score(batter, pitcher, tuning) == (
                    batter.contact * 0.55 + batter.power * 0.45 + old
                )
            state = SimpleNamespace(pitcher=pitcher)
            for size in (1, 3, 9):
                assert _matchup_score(state, batters[:size], tuning) == (
                    _legacy_matchup_score(pitcher, batters[:size])
                )


def test_default_lineup_shift_is_the_old_one():
    for tuning in (None, load_tuning(), load_tuning(LEAGUE)):
        for bats in ("L", "R", "S", "", "B"):
            for vl in (0, 30, 46, 50, 54, 90):
                player = SimpleNamespace(
                    bats=bats, vl=vl, ch=47, ph=58, eye=52, sp=61,
                )
                for vs_hand in ("L", "R", "lhp", "", None):
                    h, d = _legacy_lineup_shift(player, vs_hand)
                    assert _platoon_adjustment(
                        player, vs_hand=vs_hand, tuning=tuning
                    ) == 1.2 * h + 0.135 * d
                    comps = _slot_components(player, vs_hand=vs_hand, tuning=tuning)
                    ch = 47.0 + 2.0 * h + 0.25 * d
                    ph = 58.0 + 2.0 * h + 0.20 * d
                    eye = 52.0 + 2.0 * h + 0.30 * d
                    assert comps == {
                        "obp": 0.6 * eye + 0.4 * ch, "power": ph,
                        "contact": ch, "speed": 61.0,
                    }


# --- whole games at the defaults: pinned digests ----------------------------

# sha256 of the canonical JSON (floats rounded to 6 places) of pitch log,
# totals and metadata for default-tuning games on both KPI fixtures, taken on
# the Release 5a tree BEFORE any platoon code changed. A switched-off platoon
# term that draws a random number, or moves a rating in the last bit, changes
# them. RE-BASELINE only when the default random stream changes on purpose
# (another Release 5 area, the 5b flip): run this file and copy the "got"
# digests from the failure message.
PINNED_DIGESTS = {
    ("calibration", "CAL01", "CAL02", 1):
        "101a3c77cd41fefda9ab829557db15cf1b9cdc124d0d7ff073b1447cf0f32b0f",
    ("calibration", "CAL03", "CAL04", 2):
        "7c14d03671c83e50ed72a0710f408e58ce573402eb9e0c4607a185283bb5826a",
    ("calibration", "CAL02", "CAL03", 3):
        "7f9adf6113cc0ac436bf609693b8f592b9c5bfbcc4c509c963682f8847047028",
    ("calibration_league", "ALB", "DET", 1):
        "0880c218022e30b04877bda75f3984b387e22cc549ea8e9faa7ed0d49318da0e",
    ("calibration_league", "LOU", "OKL", 2):
        "849a23407ffc1375d7455680cd2963e95785b581249a37a3b635997848344eb4",
    ("calibration_league", "POR", "ELP", 3):
        "42166aad5eb497de3210aa5c6389a4b36a6b58646d59282657ab0d47ed10d8b7",
    ("calibration_league", "SEA", "DEN", 4):
        "e9904667f18b5530b558b19bdb37204af7db6d653dd88cfada4c09e06d7a5729",
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
        _canon({
            "pitch_log": result.pitch_log, "totals": result.totals,
            "meta": result.metadata,
        }),
        sort_keys=True, default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _play(game, overrides=None):
    fixture, away, home, seed = game
    base = REPO / "data" / fixture
    return engine.simulate_matchup_from_files(
        away_team=away, home_team=home, base_dir=base,
        players_path=base / "players.csv", seed=seed, game_day=seed,
        tuning_overrides=dict(overrides) if overrides else None,
    )


def test_default_games_match_the_digests_pinned_before_release_5():
    got = {game: _digest(_play(game)) for game in PINNED_DIGESTS}
    assert got == PINNED_DIGESTS, f"got {got}"


def test_centres_and_shares_alone_change_no_game():
    """A live game always carries its league's vl centres and batting-side
    shares; with the switches off nothing may read them."""
    for game in list(PINNED_DIGESTS)[3:5]:
        assert _digest(_play(game, LEAGUE)) == PINNED_DIGESTS[game]


def test_the_profile_changes_the_games():
    game = ("calibration_league", "ALB", "DET", 1)
    assert _digest(_play(game, {**LEAGUE, **PROFILE})) != PINNED_DIGESTS[game]


# --- the asymmetric, league-balanced handedness bonus ----------------------


def _rho(left, right, switch, bonus=1.0):
    return (2 * left + bonus * switch) / (2 * right + bonus * switch)


def test_strength_zero_is_a_fixed_right_handed_split():
    tuning = load_tuning({**LEAGUE, "handedness_rhb_scale": 0.6})
    assert handedness_scales(tuning) == (1.0, 0.6)
    assert platoon_shift_values("R", 50, "L", tuning)[0] == 0.6
    assert platoon_shift_values("R", 50, "R", tuning)[0] == -0.6
    assert platoon_shift_values("L", 50, "R", tuning)[0] == 1.0
    assert platoon_shift_values("L", 50, "L", tuning)[0] == -1.0


def test_strength_one_sizes_the_split_from_the_leagues_batting_sides():
    for left, right, switch in ((0.30, 0.57, 0.13), (0.385, 0.513, 0.102)):
        shares = {
            "hitter_bats_share_l": left, "hitter_bats_share_r": right,
            "hitter_bats_share_s": switch,
        }
        tuning = load_tuning({
            **shares, "handedness_rhb_scale": 0.6,
            "handedness_balance_strength": 1.0, "handedness_switch_bonus": 1.0,
        })
        a_left, a_right = handedness_scales(tuning)
        assert a_left == 1.0
        assert a_right == pytest.approx(_rho(left, right, switch))
        half = load_tuning({
            **shares, "handedness_rhb_scale": 0.6,
            "handedness_balance_strength": 0.5, "handedness_switch_bonus": 1.0,
        })
        assert handedness_scales(half)[1] == pytest.approx(
            0.5 * 0.6 + 0.5 * _rho(left, right, switch)
        )


@pytest.mark.parametrize("switch_bonus", [1.0, 0.5])
def test_balanced_bonus_makes_both_pitcher_hands_equal(switch_bonus):
    """The point of owner decision 5: the mean advantage of a league's
    hitters is the same against a left-hander and a right-hander."""
    left, right, switch = 0.30, 0.57, 0.13
    tuning = load_tuning({
        "hitter_bats_share_l": left, "hitter_bats_share_r": right,
        "hitter_bats_share_s": switch, "handedness_balance_strength": 1.0,
        "handedness_switch_bonus": switch_bonus,
    })
    mean = {
        hand: sum(
            share * platoon_shift_values(side, 50, hand, tuning)[0]
            for side, share in (("L", left), ("R", right), ("S", switch))
        )
        for hand in HANDS
    }
    assert mean["L"] == pytest.approx(mean["R"])
    fixed = load_tuning({"handedness_switch_bonus": switch_bonus})
    unbalanced = {
        hand: sum(
            share * platoon_shift_values(side, 50, hand, fixed)[0]
            for side, share in (("L", left), ("R", right), ("S", switch))
        )
        for hand in HANDS
    }
    assert unbalanced["L"] - unbalanced["R"] > 0.5  # LHP face the platoon edge


def test_unknown_shares_use_the_fixed_scale():
    tuning = load_tuning({
        "handedness_rhb_scale": 0.6, "handedness_balance_strength": 1.0,
    })
    assert handedness_scales(tuning) == (1.0, 0.6)
    nobody_right = load_tuning({
        "handedness_rhb_scale": 0.6, "handedness_balance_strength": 1.0,
        "hitter_bats_share_l": 1.0, "handedness_switch_bonus": 0.0,
    })
    assert handedness_scales(nobody_right) == (1.0, 0.6)


def test_the_balance_ratio_is_clamped_and_biased():
    on = {"handedness_balance_strength": 1.0, "handedness_switch_bonus": 1.0}
    righty_league = load_tuning({
        **on, "hitter_bats_share_l": 0.05, "hitter_bats_share_r": 0.90,
        "hitter_bats_share_s": 0.05,
    })
    assert _rho(0.05, 0.90, 0.05) < 0.35
    assert handedness_scales(righty_league) == (1.0, 0.35)
    lefty_league = load_tuning({
        **on, "hitter_bats_share_l": 0.60, "hitter_bats_share_r": 0.30,
        "hitter_bats_share_s": 0.10,
    })
    assert handedness_scales(lefty_league) == (1.0, 1.0)
    wide = load_tuning({
        **on, "hitter_bats_share_l": 0.60, "hitter_bats_share_r": 0.30,
        "hitter_bats_share_s": 0.10, "handedness_balance_max": 2.0,
        "handedness_balance_min": 0.1,
    })
    assert handedness_scales(wide)[1] == pytest.approx(_rho(0.60, 0.30, 0.10))
    biased = load_tuning({
        **on, **LEAGUE, "handedness_balance_bias": 0.07,
    })
    assert handedness_scales(biased)[1] == pytest.approx(
        _rho(0.24, 0.65, 0.11) + 0.07
    )
    scaled = load_tuning({**on, **LEAGUE, "handedness_lhb_scale": 0.9})
    a_left, a_right = handedness_scales(scaled)
    assert a_left == 0.9
    assert a_right == pytest.approx(0.9 * _rho(0.24, 0.65, 0.11))


def test_switch_hitters_take_the_bonus_of_the_side_they_bat_from():
    tuning = load_tuning({
        **LEAGUE, "handedness_balance_strength": 1.0,
        "handedness_switch_bonus": 1.0,
    })
    a_left, a_right = handedness_scales(tuning)
    assert a_right < a_left
    # Left-handed against a right-hander, right-handed against a left-hander.
    assert platoon_shift_values("S", 50, "R", tuning)[0] == a_left
    assert platoon_shift_values("S", 50, "L", tuning)[0] == a_right
    assert platoon_shift_values("L", 50, "R", tuning)[0] == a_left
    assert platoon_shift_values("R", 50, "L", tuning)[0] == a_right
    half = load_tuning({**LEAGUE, "handedness_rhb_scale": 0.6})
    assert platoon_shift_values("S", 50, "R", half)[0] == 0.5
    assert platoon_shift_values("S", 50, "L", half)[0] == pytest.approx(0.3)


def test_every_reader_gets_the_asymmetric_bonus():
    tuning = load_tuning({**LEAGUE, "handedness_rhb_scale": 0.6})
    lefty, righty = _pitcher("L"), _pitcher("R")
    rhb, lhb, switch = _batter("R"), _batter("L"), _batter("S")
    base = _batter_context(rhb, righty, load_tuning({"handedness_contact_bonus": 0.0,
                                                    "handedness_power_bonus": 0.0,
                                                    "handedness_eye_bonus": 0.0}))
    ctx = _batter_context(rhb, lefty, tuning)
    assert ctx["contact"] == pytest.approx(
        base["contact"] + 0.6 * tuning.get("handedness_contact_bonus")
    )
    assert ctx["power"] == pytest.approx(
        base["power"] + 0.6 * tuning.get("handedness_power_bonus")
    )
    ctx = _batter_context(lhb, lefty, tuning)
    assert ctx["contact"] == pytest.approx(
        base["contact"] - tuning.get("handedness_contact_bonus")
    )
    assert _platoon_bonus(rhb, lefty, tuning) == pytest.approx(2.0 * 0.6)
    assert _platoon_bonus(rhb, righty, tuning) == pytest.approx(-2.0 * 0.6)
    assert _platoon_bonus(lhb, righty, tuning) == pytest.approx(2.0)
    state = SimpleNamespace(pitcher=lefty)
    assert _matchup_score(state, [rhb, lhb, switch], tuning) == pytest.approx(
        -0.6 + 1.0 - 0.5 * 0.6
    )
    player = SimpleNamespace(bats="R", vl=50, ch=50, ph=50, eye=50, sp=50)
    assert _platoon_adjustment(player, vs_hand="L", tuning=tuning) == (
        pytest.approx(1.2 * 0.6)
    )


def test_the_counter_scale_is_a_knob():
    tuning = load_tuning({"platoon_rhp_counter_scale": 0.5})
    assert platoon_shift_values("R", 60, "R", tuning)[1] == -5.0
    assert platoon_shift_values("R", 60, "L", tuning)[1] == 10.0


# --- vl against the league's own mean by batting side -----------------------


def test_vl_centres_are_ignored_while_the_switch_is_off():
    for side in SIDES:
        for hand in HANDS:
            assert platoon_shift_values(side, 58, hand, load_tuning(LEAGUE)) == (
                platoon_shift_values(side, 58, hand, load_tuning())
            )


def test_vl_reads_against_the_centre_of_the_hitters_side():
    tuning = load_tuning({**LEAGUE, "platoon_vl_center_enabled": 1.0})
    assert platoon_shift_values("L", 52.0, "L", tuning)[1] == 7.0
    assert platoon_shift_values("R", 52.0, "L", tuning)[1] == -1.5
    assert platoon_shift_values("S", 52.0, "L", tuning)[1] == 2.75
    assert platoon_shift_values("", 52.0, "L", tuning)[1] == -1.5  # bats right
    assert platoon_shift_values("L", 52.0, "R", tuning)[1] == -0.35 * 7.0


def test_a_league_wide_tilt_by_batting_side_has_no_effect_when_on():
    """Two leagues with the same hitters, one with every left-handed batter's
    vl 5 lower and every right-handed batter's 3.5 higher (its centres with
    them): the same batter contexts with the switch on, different with it
    off."""
    tilt = {"L": -5.0, "R": 3.5, "S": -0.75}
    flat = load_tuning({"platoon_vl_center_enabled": 1.0})
    tilted = load_tuning({**LEAGUE, "platoon_vl_center_enabled": 1.0})
    off = load_tuning(LEAGUE)
    for side in SIDES:
        assert LEAGUE[f"hitter_vl_center_{side.lower()}"] == 50.0 + tilt[side]
        for throws in HANDS:
            pitcher = _pitcher(throws)
            for own in (-12.0, 0.0, 9.0):
                plain = _batter(side, 50.0 + own, ph=55.0)
                moved = _batter(side, 50.0 + own + tilt[side], ph=55.0)
                want = _batter_context(plain, pitcher, flat)
                assert _batter_context(moved, pitcher, tilted) == want
                assert _batter_context(moved, pitcher, off) != want
                assert _platoon_bonus(moved, pitcher, tilted) == (
                    _platoon_bonus(plain, pitcher, flat)
                )


# --- the Power bonus after the bat-speed knee -------------------------------


def _swing(ph, tuning, *, bats="R"):
    """Bat speed against the opposite hand minus against the same hand."""
    batter = _batter(bats, 50.0, ph=ph)
    opposite = "L" if bats == "R" else "R"
    return (
        _batter_power_bat_speed(_batter_context(batter, _pitcher(opposite), tuning), tuning)
        - _batter_power_bat_speed(_batter_context(batter, _pitcher(bats), tuning), tuning)
    )


def test_off_the_bonus_still_runs_through_the_knee():
    tuning = load_tuning()
    for power, base in ((48.0, 46.0), (55.0, 53.0), (51.0, 60.0)):
        ctx = {"power": power, "power_base": base}
        assert _batter_power_bat_speed(ctx, tuning) == _power_bat_speed(power, tuning)
    # 0.15 mph a point below the knee (52), 0.95 above: a 4-point platoon
    # swing is 0.6 mph for one hitter and 3.8 for another.
    assert _swing(46.0, tuning) == pytest.approx(0.6)
    assert _swing(56.0, tuning) == pytest.approx(3.8)


def test_on_the_bonus_is_flat_whatever_the_hitters_power():
    k = PROFILE["platoon_bat_speed_per_point"]
    tuning = load_tuning({"platoon_power_after_knee": 1.0,
                          "platoon_bat_speed_per_point": k})
    ctx = {"power": 55.0, "power_base": 53.0}
    assert _batter_power_bat_speed(ctx, tuning) == pytest.approx(
        _power_bat_speed(53.0, tuning) + 2.0 * k
    )
    # No power_base (a context built by hand): the old curve.
    assert _batter_power_bat_speed({"power": 55.0}, tuning) == (
        _power_bat_speed(55.0, tuning)
    )
    swings = [_swing(ph, tuning) for ph in (40.0, 46.0, 50.0, 51.0, 52.0, 53.0,
                                            54.0, 56.0, 66.0, 80.0)]
    assert swings == pytest.approx([4.0 * k] * len(swings))
    # The hitter's own Power still rides the curve.
    low = _batter_context(_batter("R", ph=46.0), _pitcher("R"), tuning)
    high = _batter_context(_batter("R", ph=56.0), _pitcher("R"), tuning)
    assert _batter_power_bat_speed(high, tuning) - _batter_power_bat_speed(
        low, tuning
    ) == pytest.approx(_power_bat_speed(56.0, tuning) - _power_bat_speed(46.0, tuning))


def test_the_times_through_the_order_bonus_shares_the_path():
    k = 0.3
    tuning = load_tuning({"platoon_power_after_knee": 1.0,
                          "platoon_bat_speed_per_point": k})
    batter, pitcher = _batter("R", ph=53.0), _pitcher("R")
    first = _batter_context(batter, pitcher, tuning, tto=1)
    third = _batter_context(batter, pitcher, tuning, tto=3)
    assert third["power"] - first["power"] == pytest.approx(
        2 * tuning.get("tto_power_bonus")
    )
    assert third["power_base"] == first["power_base"] == 53.0
    assert _batter_power_bat_speed(third, tuning) - _batter_power_bat_speed(
        first, tuning
    ) == pytest.approx(2 * tuning.get("tto_power_bonus") * k)


def test_barrel_reads_the_bonus_and_pitch_selection_does_not(monkeypatch):
    seen = {}

    def choice(weights):
        seen.update(weights)
        return next(iter(weights))

    monkeypatch.setattr(physics, "_weighted_choice", choice)
    avoid = DEFAULT_TUNING["pitch_seq_power_avoid_fastball"]
    assert avoid != 1.0

    def fastball_weight(batter, tuning):
        seen.clear()
        physics.choose_pitch_type(
            repertoire={"fb": 60.0, "sl": 60.0}, batter=batter, count=(1, 1),
            objective="neutral", tuning=tuning,
        )
        return seen["fb"]

    # 59 Power with a 2-point platoon edge: over the 60 line only with it.
    edge = _batter_context(_batter("R", ph=59.0), _pitcher("L"), load_tuning())
    assert edge["power"] == 61.0 and edge["power_base"] == 59.0
    plain = {**edge, "power": 59.0}
    off, on = load_tuning(), load_tuning({"platoon_power_after_knee": 1.0})
    assert fastball_weight(edge, off) == pytest.approx(fastball_weight(plain, off) * avoid)
    assert fastball_weight(edge, on) == fastball_weight(plain, on)
    assert fastball_weight(plain, on) == fastball_weight(plain, off)


def _hr_ratio(power, tuning, n=24000):
    """HR against the opposite hand over the same hand, seeded Monte Carlo
    on the real pitch code (the KPI harness's platoon grid cell)."""
    from physics_sim.park import load_park
    from scripts import kpi_extras

    state = random.getstate()
    try:
        cells = {
            hand: kpi_extras._simulate_cell(
                contact=50.0, power=power, pitcher_level=50.0, n=n, seed=20261012,
                tuning=tuning, park=load_park(None), bats="L", throws=hand,
            )
            for hand in HANDS
        }
    finally:
        random.setstate(state)
    assert min(cells["L"]["hr"], cells["R"]["hr"]) >= 150
    return cells["R"]["hr"] / cells["L"]["hr"]


def test_the_platoon_home_run_ratio_does_not_step_at_the_knee():
    """Audit H7: a hitter two points over the knee had a 1.5 home-run ratio
    against the opposite hand and one at 50 a 1.16; after the knee both sit
    near the same ratio."""
    off = load_tuning()
    on = load_tuning({"platoon_power_after_knee": 1.0,
                      "platoon_bat_speed_per_point":
                          PROFILE["platoon_bat_speed_per_point"]})
    assert _hr_ratio(54.0, off) / _hr_ratio(50.0, off) > 1.15
    below, above = _hr_ratio(50.0, on), _hr_ratio(54.0, on)
    assert 0.9 < above / below < 1.1
    assert 1.05 < below < 1.45 and 1.05 < above < 1.45


# --- the lineup auto-fill reads the same values ----------------------------

ON = {**LEAGUE, **PROFILE}


def test_lineup_shift_is_the_engines_for_the_same_tuning():
    tuning = load_tuning(ON)
    for bats in SIDES:
        for vl in (38, 45, 50, 54, 71):
            player = SimpleNamespace(bats=bats, vl=vl, ch=52, ph=49, eye=55, sp=50)
            for vs_hand in HANDS:
                h, d = platoon_shift(_batter(bats, float(vl)), vs_hand, tuning)
                assert _platoon_adjustment(
                    player, vs_hand=vs_hand, tuning=tuning
                ) == 1.2 * h + 0.135 * d
                comps = _slot_components(player, vs_hand=vs_hand, tuning=tuning)
                assert comps["power"] == 49.0 + 2.0 * h + 0.20 * d
                assert comps["contact"] == 52.0 + 2.0 * h + 0.25 * d
                # ... and the in-game offence score uses the same pair.
                assert _platoon_bonus(
                    _batter(bats, float(vl)), _pitcher(vs_hand), tuning
                ) == 2.0 * h + 0.2275 * d


COLUMNS = [
    "player_id", "first_name", "last_name", "birthdate", "height", "weight",
    "bats", "throws", "primary_position", "other_positions", "is_pitcher",
    "role", "ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm",
]


def _row(pid, pos, *, bats="R", vl=50, ch=50, ph=50):
    d = {c: "" for c in COLUMNS}
    d.update(
        player_id=pid, first_name="F", last_name="L", birthdate="1995-05-15",
        height="72", weight="200", bats=bats, throws="R",
        primary_position=pos, other_positions="", is_pitcher="0",
        ch=str(ch), ph=str(ph), sp="50", eye="50", gf="50", pl="50",
        vl=str(vl), sc="50", fa="50", arm="50",
    )
    return d


def _write_league(root: Path, rows: list[dict], team: str = "TST"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "rosters").mkdir()
    (root / "lineups").mkdir()
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with (root / "rosters" / f"{team}.csv").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(f"{row['player_id']},ACT\n")
    return dict(
        players_file=str(root / "players.csv"), roster_dir=str(root / "rosters"),
        lineup_dir=str(root / "lineups"),
    )


def _club(tilt_left=0, tilt_right=0):
    """Eight fixed regulars and two first basemen: A bats right, B bats left
    and is the better raw bat. ``tilt_*`` moves every hitter's vl by side."""
    rows = [
        _row(pid, pos, bats=bats, vl=50 + (tilt_left if bats == "L" else tilt_right))
        for pid, pos, bats in (
            ("C1", "C", "R"), ("SS1", "SS", "R"), ("CF1", "CF", "L"),
            ("TB1", "3B", "R"), ("2B1", "2B", "L"), ("LF1", "LF", "R"),
            ("RF1", "RF", "L"), ("DH1", "DH", "R"),
        )
    ]
    rows.append(_row("A", "1B", bats="R", vl=50 + tilt_right, ch=60, ph=60))
    rows.append(_row("B", "1B", bats="L", vl=50 + tilt_left, ch=62, ph=62))
    return rows


def _first_baseman(paths, **kwargs) -> str:
    lineup_autofill.load_roster.cache_clear()
    lineup = auto_fill_lineup_for_team("TST", vs="lhp", persist=False, **paths, **kwargs)
    return next(pid for pid, pos in lineup if pos == "1B")


def test_auto_fill_reads_the_centred_vl(tmp_path):
    """A league whose data tilts vl against its right-handed batters would
    bench the right-handed first baseman against a LHP; read against the
    league's own means the tilt is nothing and he starts, as in a league
    without it."""
    flat = _write_league(tmp_path / "flat", _club())
    tilted = _write_league(tmp_path / "tilted", _club(tilt_left=12, tilt_right=-12))
    off = load_tuning()
    centred = load_tuning({
        "platoon_vl_center_enabled": 1.0, "hitter_vl_center_l": 62.0,
        "hitter_vl_center_r": 38.0, "hitter_vl_center_s": 50.0,
    })
    assert _first_baseman(flat, tuning=off) == "A"
    assert _first_baseman(tilted, tuning=off) == "B"
    assert _first_baseman(tilted, tuning=centred) == "A"


def test_auto_fill_resolves_the_leagues_tuning_itself(tmp_path, monkeypatch):
    """No tuning passed: the stored physics overrides decide, and only a
    switched-on platoon term makes it read the league's rating centres."""
    import services.league_rating_centers as centers
    import services.physics_tuning_settings as settings

    rows = _club(tilt_left=12, tilt_right=-12)
    # Enough hitters on each side for the side to have its own centre.
    rows += [_row(f"XL{i}", "LF", bats="L", vl=62, ch=30, ph=30) for i in range(8)]
    rows += [_row(f"XR{i}", "RF", bats="R", vl=38, ch=30, ph=30) for i in range(6)]
    paths = _write_league(tmp_path / "league", rows)
    centers.clear_rating_center_cache()
    reads = []
    real = centers.league_rating_centers

    def spy(*args, **kwargs):
        reads.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(centers, "league_rating_centers", spy)
    monkeypatch.setattr(settings, "get_physics_tuning_overrides", lambda: {})
    assert platoon_tuning(tmp_path / "league").get("hitter_vl_center_l") == 50.0
    assert _first_baseman(paths) == "B"
    assert reads == []

    monkeypatch.setattr(
        settings, "get_physics_tuning_overrides",
        lambda: {"platoon_vl_center_enabled": 1.0},
    )
    tuning = platoon_tuning(tmp_path / "league")
    assert tuning.get("hitter_vl_center_l") == 62.0
    assert tuning.get("hitter_vl_center_r") == 38.0
    assert tuning.get("hitter_bats_share_l") == pytest.approx(12 / 24)
    assert all(kwargs.get("store") is False for kwargs in reads)
    assert _first_baseman(paths) == "A"
    assert not (tmp_path / "league" / centers.RATING_CENTERS_FILENAME).exists()


# --- the generator's batting-side mix ---------------------------------------


def test_new_infielders_and_catchers_bat_like_mlb():
    from playbalance import player_generator as pg

    for position in ("C", "2B", "3B", "SS"):
        weights = {(bats, throws): w for bats, throws, w in pg.BATS_THROWS[position]}
        assert weights == {
            ("R", "L"): 0, ("R", "R"): 60, ("L", "L"): 0, ("L", "R"): 27,
            ("S", "L"): 0, ("S", "R"): 13,
        }
        assert pg.BATS_THROWS_PRE_R5[position] == [
            ("R", "L", 0), ("R", "R", 75), ("L", "L", 0), ("L", "R", 15),
            ("S", "L", 0), ("S", "R", 10),
        ]
    # Nothing else moved.
    for position in ("P", "1B", "LF", "CF", "RF"):
        assert pg.BATS_THROWS[position] == pg.BATS_THROWS_PRE_R5[position]
    assert pg.BATS_THROWS["1B"] == [
        ("R", "L", 1), ("R", "R", 40), ("L", "L", 32), ("L", "R", 13),
        ("S", "L", 4), ("S", "R", 10),
    ]
    assert pg.BATS_THROWS["CF"] == [
        ("R", "L", 1), ("R", "R", 50), ("L", "L", 25), ("L", "R", 10),
        ("S", "L", 4), ("S", "R", 10),
    ]


def test_generated_shortstops_follow_the_new_mix():
    from collections import Counter

    from playbalance import player_generator as pg

    state = random.getstate()
    try:
        random.seed(20261012)
        drawn = Counter(pg.assign_bats_throws("SS") for _ in range(20000))
    finally:
        random.setstate(state)
    assert all(throws == "R" for _bats, throws in drawn)
    share = {bats: n / 20000 for (bats, _throws), n in drawn.items()}
    assert share["R"] == pytest.approx(0.60, abs=0.015)
    assert share["L"] == pytest.approx(0.27, abs=0.015)
    assert share["S"] == pytest.approx(0.13, abs=0.015)


# --- the vl label ------------------------------------------------------------


def test_vl_is_labelled_as_a_platoon_split_with_help():
    from services import player_profile_view_model as vm

    labels = {key: label for label, key in vm._HITTER_RATINGS}
    assert labels["vl"] == vm.PLATOON_SPLIT_LABEL == "Platoon vs L"
    assert "Vision" not in labels.values()
    assert "vl" not in {key for _label, key in vm._PITCHER_RATINGS}
    help_text = vm.RATING_HELP[vm.PLATOON_SPLIT_LABEL]
    assert "left-handed pitching" in help_text and "50" in help_text
    assert "bats from his side" in help_text


def test_profile_rows_carry_the_help_for_their_labels(monkeypatch):
    from services import player_profile_view_model as vm

    monkeypatch.setattr(vm, "_display_rating", lambda player, key, **_k: "55")
    hitter = SimpleNamespace(ch=50, ph=50, sp=50, fa=50, arm=50, eye=50, pl=50,
                             vl=61, sc=50, gf=50)
    rows = vm._overview_ratings(hitter, is_pitcher=False)
    assert (vm.PLATOON_SPLIT_LABEL, "55") in rows
    pitcher = SimpleNamespace(control=50, movement=50, endurance=50,
                              hold_runner=50, fa=50, arm=50, fb=60, sl=0,
                              cu=0, si=0, kn=0)
    assert vm.PLATOON_SPLIT_LABEL not in dict(
        vm._overview_ratings(pitcher, is_pitcher=True)
    )


# --- report-only: LHP minus RHP at equal ratings ----------------------------


def _hand_rows(n=12):
    """Left-handers with better control and a 0.4 run handicap for the hand:
    RA9 = 4.5 - 0.05 * (control - 50) + 0.03 * (endurance - 50) + 0.4 * LHP."""
    from collections import Counter

    pitchers, throws, ratings = {}, {}, {}
    for i in range(2 * n):
        pid = f"P{i}"
        left = i % 2 == 0
        control = 44.0 + i + (8.0 if left else 0.0)
        endurance = 30.0 + 3.0 * ((i * 7) % 11)
        ra9 = (
            4.5 - 0.05 * (control - 50.0) + 0.03 * (endurance - 50.0)
            + (0.4 if left else 0.0)
        )
        outs = 300 + 30 * (i % 5)
        pitchers[pid] = Counter(outs=outs, r=ra9 * outs / 27.0)
        throws[pid] = "L" if left else "R"
        ratings[pid] = {
            "control": control, "movement": 50.0 + (i % 3), "arm": 55.0 - (i % 4),
            "endurance": endurance, "pitch_grade": 52.0 + (i % 7),
        }
    return pitchers, throws, ratings


def test_rating_adjusted_hand_gap_removes_the_rating_difference():
    from scripts import kpi_extras as kx

    pitchers, throws, ratings = _hand_rows()
    raw = {
        hand: 27.0 * sum(c["r"] for p, c in pitchers.items() if throws[p] == hand)
        / sum(c["outs"] for p, c in pitchers.items() if throws[p] == hand)
        for hand in HANDS
    }
    assert abs(raw["L"] - raw["R"]) < 0.1  # better control hides the handicap
    out = kx._hand_ra9_rating_adjusted(pitchers, throws, ratings)
    assert out["gap"] == pytest.approx(0.4, abs=1e-6)
    assert out["per10"]["control"] == pytest.approx(-0.5, abs=1e-6)
    assert out["per10"]["endurance"] == pytest.approx(0.3, abs=1e-6)
    assert (out["pitchers"], out["lhp"]) == (24, 12)


def test_rating_adjusted_hand_gap_needs_both_hands_and_enough_outs():
    from scripts import kpi_extras as kx

    pitchers, throws, ratings = _hand_rows()
    few_lefties = {p: ("L" if p in {"P0", "P2"} else "R") for p in throws}
    assert kx._hand_ra9_rating_adjusted(pitchers, few_lefties, ratings)["gap"] is None
    short = {p: type(c)(outs=10, r=c["r"]) for p, c in pitchers.items()}
    assert kx._hand_ra9_rating_adjusted(short, throws, ratings)["pitchers"] == 0
    same = {p: {key: 50.0 for key in kx.HAND_RA9_RATINGS} for p in ratings}
    assert kx._hand_ra9_rating_adjusted(pitchers, throws, same)["gap"] is None


def test_rating_adjusted_hand_gap_is_reported_and_never_gated(tmp_path):
    from scripts import kpi_extras as kx
    from scripts import physics_sim_season_kpis as kpis

    acc = kx.ReportOnlyKpis(players_path=tmp_path / "missing.csv", games_per_team=162)
    report = acc.finalize(kx.load_reference())
    assert report["metrics"]["lhp_minus_rhp_ra9_rating_adj"] is None
    assert "lhp_minus_rhp_ra9_rating_adj" in kx.load_reference()
    assert "lhp_minus_rhp_ra9_rating_adj" not in kpis.DEFAULT_TOLERANCES
    ratings = kx._load_pitcher_ratings(REPO / "data" / "calibration" / "players.csv")
    assert len(ratings) > 100
    assert all(set(row) == set(kx.HAND_RA9_RATINGS) for row in ratings.values())
