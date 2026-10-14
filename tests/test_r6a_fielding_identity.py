"""Release 6a (fielding): every switch off is the engine as it was.

The fielding work (RELEASE6_PLAN.md 2.3 and 2.4) sits behind seven switches
registered in ``DEFAULT_TUNING`` at 0: the chance log, the fielder centres,
the out-of-position table, the spray direction fix, the infield bands, the
range model and the error model. With all of them off -- the legacy engine
and generation 5 -- a seeded game is the game it was before this code
existed, to the last bit of every float and with every random draw where it
was:

* legacy games against the digests pinned on the Release 5a tree
  (``tests.test_r5_discipline.PINNED_DIGESTS``);
* generation 5 games against digests taken on the 7.51.3 tree (3abbbc251,
  exported with ``git archive``: no fielding code) and equal on this one;
* the helpers the switches replace, value for value against the old code.

And each switch does change a game, so none of the identities above holds
only because nothing reads the switch.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.fielding as fielding
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.models import BatterRatings
from tests.test_r5_discipline import PINNED_DIGESTS, _digest, _play

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "scripts" / "kpi_profiles" / "r6_fielding.json"

# Every switch, at the value that is "off".
SWITCHES = {
    "fielding_chance_log": 0.0,
    "fielder_centred_ratings": 0.0,
    "position_fit_model": 0.0,
    "spray_direction_model": 0.0,
    "infield_band_model": 0.0,
    "range_model": 0.0,
    "error_model": 0.0,
}
# The knobs only a switched-on model reads, at their registered defaults.
KNOBS = {
    "position_secondary_penalty_scale": 0.25,
    "infield_band_3b_min_deg": 16.0,
    "infield_band_ss_min_deg": 1.5,
    "infield_band_p_min_deg": -1.5,
    "infield_band_2b_min_deg": -19.5,
    "range_logit_slope_1b": 0.0078,
    "range_logit_slope_2b": 0.0050,
    "range_logit_slope_3b": 0.0081,
    "range_logit_slope_ss": 0.0064,
    "range_logit_slope_lf": 0.0068,
    "range_logit_slope_cf": 0.0060,
    "range_logit_slope_rf": 0.0066,
    "range_ld_ratio": 0.6,
    "error_base_1b": 0.029,
    "error_base_2b": 0.020,
    "error_base_3b": 0.049,
    "error_base_ss": 0.036,
    "error_base_lf": 0.0069,
    "error_base_cf": 0.0037,
    "error_base_rf": 0.0068,
    "error_base_p": 0.045,
    "error_fa_log_slope": 0.025,
    "error_arm_log_slope": 0.02,
    "error_infield_liner_scale": 0.25,
    "error_steal_throw_rate": 0.04,
    "error_of_hit_rate": 0.009,
    "error_pickoff_throw_rate": 0.01,
    "error_relay_throw_rate": 0.03,
}
# The same knobs set to something wild: no off path may read one.
WILD = {key: 9.0 for key in KNOBS}
# The centres the fielding switches read, wild too.
WILD_CENTERS = {
    f"fielder_{kind}_center_{pos}": 73.0
    for kind in ("fa", "arm")
    for pos in ("1b", "2b", "3b", "ss", "lf", "cf", "rf")
}
WILD_CENTERS["fielder_fa_center_p"] = 73.0

# Generation 5 games: sha256 as tests.test_r5_discipline._digest takes it
# (pitch log + totals + metadata, every float at full precision), played
# with the generation 5 profile and the fixture's centres. Taken on the
# 7.51.3 tree (3abbbc251, exported with git archive), which has none of
# this release's fielding code, and equal on this branch.
GENERATION_5_DIGESTS = {
    ("calibration", "CAL01", "CAL02", 1):
        "ae207bbf85cecbca180b270b4fbeb884edb18e1cd7ea1d7e02e53efb5dd85182",
    ("calibration", "CAL01", "CAL02", 2):
        "11f807f5d043c297552db41c765b22cb73a0d748d945e1b5a2947d2630dfa2ea",
    ("calibration", "CAL07", "CAL12", 5):
        "58306cce1a8af09c45cf53eaf6dee1bf7b82b0883262a4cdbe9ea2351e1d9efd",
    ("calibration", "CAL19", "CAL04", 8):
        "347a576451195485956f2be2b56cecc3a1c968d4267a54c67ee74ea0da0b25c3",
    ("calibration_league", "ALB", "DET", 1):
        "2b8bdb2e01dc5256a799b75c1ec95fb190104fd8c65c1fe49d5df539c2f39942",
    ("calibration_league", "ALB", "DET", 2):
        "d527f323e142643e94a9e2731fd99a77e2b1afadab97267dd7a5f6562d14ac1f",
    ("calibration_flat", "ALB", "BOI", 3):
        "d5210d49d9da08e9c4e52e41acd23579742f18335f8afee1f441c0aa04503ab4",
}
LEGACY_KEYS = [key for key in PINNED_DIGESTS if key[4] is None]


def _generation_5(fixture, extra=None):
    base = REPO / "data" / fixture
    overrides = kpis.with_rating_centers(engine_profile(5), base / "players.csv", base)
    overrides.update(extra or {})
    return overrides


# --- registered, and off ------------------------------------------------------------


def test_every_key_is_registered_at_its_off_value():
    for key, value in {**SWITCHES, **KNOBS}.items():
        assert DEFAULT_TUNING[key] == value, key
    assert DEFAULT_TUNING["fielder_fa_center_p"] == 50.0
    # from_overrides drops an unregistered key without a word: every key of
    # the generation 6 fielding values is one it keeps.
    import json

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert set(SWITCHES) - {"fielding_chance_log"} <= set(profile)
    tuning = load_tuning(profile)
    for key, value in profile.items():
        assert key in DEFAULT_TUNING, key
        assert tuning.get(key) == float(value), key


def test_no_generation_a_league_plays_turns_a_switch_on():
    for profile in ({}, engine_profile(5), engine_profile(6, development=True)):
        tuning = load_tuning(profile)
        for key in SWITCHES:
            assert tuning.get(key) == 0.0, key
        for key, value in KNOBS.items():
            assert tuning.get(key) == value, key
        # The knobs generation 6's fielding values move are where they were.
        assert tuning.get("spray_center_band_deg") == 8.0
        assert tuning.get("double_play_range_scale") == 1.2
        assert tuning.get("double_play_arm_scale") == 1.2
        assert tuning.get("double_play_base") == 0.38


# --- seeded games --------------------------------------------------------------------


def test_legacy_games_are_the_pinned_games():
    """The default engine against the digests pinned before Release 5."""
    assert len(LEGACY_KEYS) >= 6
    for key in LEGACY_KEYS:
        assert _digest(_play(*key[:4])) == PINNED_DIGESTS[key], key


@pytest.mark.parametrize("key", LEGACY_KEYS[:3] + LEGACY_KEYS[-1:])
def test_a_legacy_game_reads_no_fielding_knob(key):
    """Every switch spelled out as 0 and everything only a switched-on
    model reads set to something wild: still the pinned game."""
    overrides = {**SWITCHES, **WILD, **WILD_CENTERS}
    assert _digest(_play(*key[:4], overrides)) == PINNED_DIGESTS[key]


def test_generation_5_games_are_the_games_they_were():
    for key, digest in GENERATION_5_DIGESTS.items():
        fixture, away, home, seed = key
        result = _play(fixture, away, home, seed, _generation_5(fixture))
        assert _digest(result) == digest, key


@pytest.mark.parametrize("key", list(GENERATION_5_DIGESTS)[:2] + list(GENERATION_5_DIGESTS)[4:5])
def test_a_generation_5_game_reads_no_fielding_knob(key):
    fixture, away, home, seed = key
    overrides = _generation_5(fixture, {**SWITCHES, **WILD, **WILD_CENTERS})
    assert _digest(_play(fixture, away, home, seed, overrides)) == GENERATION_5_DIGESTS[key]


def test_generation_6_without_the_fielding_values_is_generation_5():
    key = ("calibration", "CAL01", "CAL02", 1)
    base = REPO / "data" / key[0]
    overrides = kpis.with_rating_centers(
        engine_profile(6, development=True), base / "players.csv", base
    )
    assert _digest(_play(*key, overrides)) == GENERATION_5_DIGESTS[key]


def test_the_chance_log_is_passive():
    """A game with the log on is the game with it off -- the pitch log, the
    totals and the metadata -- on both engines; the records are beside it."""
    key = ("calibration", "CAL01", "CAL02", 2)
    logged = _play(*key, {"fielding_chance_log": 1.0})
    assert _digest(logged) == PINNED_DIGESTS[(*key, None)]
    logged5 = _play(*key, _generation_5(key[0], {"fielding_chance_log": 1.0}))
    assert _digest(logged5) == GENERATION_5_DIGESTS[key]
    for result in (logged, logged5):
        records = result.play_records
        balls = [
            index for index, entry in enumerate(result.pitch_log)
            if entry.get("outcome") == "in_play" and entry.get("hit_type") != "hr"
        ]
        assert [row[0] for row in records["bip_chances"]] == balls
        assert len(balls) > 30
        outs = [i for i in balls if result.pitch_log[i].get("out_type") is not None]
        assert [row[0] for row in records["error_chances"]] == outs
        assert records["babip_scale"] in (0.925, 0.92)
        for row in records["bip_chances"]:
            _index, side, ball_type, positions, fielders, used, average, hit = row
            assert side in ("away", "home") and ball_type in ("gb", "ld", "fb")
            assert len(positions) == len(fielders) == (2 if ball_type == "gb" else 1)
            assert 0.02 <= used <= 0.98 and 0.02 <= average <= 0.98
            assert 0.02 <= hit <= 0.95
    # Off: no chance rows, and the errors list is there on every game.
    plain = _play(*key)
    assert plain.play_records["bip_chances"] is None
    assert plain.play_records["error_chances"] is None
    assert plain.play_records["babip_scale"] is None
    assert plain.play_records["errors"] == logged.play_records["errors"]
    assert len(plain.play_records["errors"]) == plain.totals["e"]
    for entry in logged.pitch_log:
        assert "bip_chances" not in entry and "chance" not in entry


@pytest.mark.parametrize(
    "switch",
    ["fielder_centred_ratings", "position_fit_model", "spray_direction_model",
     "infield_band_model", "range_model", "error_model"],
)
def test_each_switch_changes_a_game(switch):
    """Guards the identities above against a switch nothing reads: the
    game, or at least the chances its balls in play were given, moves. (The
    out-of-position table shows only where somebody plays out of position,
    and a chance can move without turning one roll: the league fixture's
    games, read through the chance log.)"""
    changed = False
    for key in LEGACY_KEYS:
        base = REPO / "data" / key[0]
        # The same centres both times (the legacy engine reads the Release
        # 4 ones): only the switch differs.
        plain = kpis.with_rating_centers(
            {"fielding_chance_log": 1.0}, base / "players.csv", base
        )
        before = _play(*key[:4], plain)
        after = _play(*key[:4], {**plain, switch: 1.0})
        changed |= _digest(after) != _digest(before)
        changed |= after.play_records != before.play_records
    assert changed


def test_the_harness_centres_change_nothing_while_the_switches_are_off():
    """The KPI harness delivers the fielder centres on every engine; a
    legacy game with them is the game with the stored centres alone."""
    key = LEGACY_KEYS[0]
    base = REPO / "data" / key[0]
    stored = kpis.fixture_rating_centers(base / "players.csv", base)
    overrides = kpis.with_rating_centers({}, base / "players.csv", base)
    assert "fielder_fa_center_ss" in overrides and "fielder_fa_center_p" in overrides
    assert not set(stored) & set(WILD_CENTERS)
    plain = _digest(_play(*key[:4], stored))
    assert _digest(_play(*key[:4], overrides)) == plain
    assert _digest(_play(*key[:4], {**stored, **WILD_CENTERS})) == plain


# --- the helpers, value for value ----------------------------------------------------


def _fielder(primary="SS", other=(), fa=55.0, arm=50.0) -> BatterRatings:
    return BatterRatings(
        player_id="X", bats="R", primary_position=primary,
        other_positions=list(other), contact=50.0, power=50.0, gb_tendency=50.0,
        pull_tendency=50.0, vs_left=50.0, fielding=fa, arm=arm, speed=50.0,
        eye=50.0, height=72.0, durability=50.0,
    )


def _old_error_probability(out_type, fielding_rating, arm, tuning):
    """``fielding.error_probability`` as it was."""
    if out_type == "groundout":
        base = tuning.get("error_rate_gb", 0.018)
    elif out_type == "flyout":
        base = tuning.get("error_rate_fb", 0.008)
    else:
        base = tuning.get("error_rate_ld", 0.012)
    adj = (50.0 - fielding_rating) / 500.0
    adj += (50.0 - arm) / 900.0
    prob = (base + adj) * tuning.get("error_rate_scale", 1.0)
    return max(0.001, min(0.12, prob))


@pytest.mark.parametrize("profile", [{}, {"error_rate_scale": 1.4}])
def test_the_error_chance_is_the_old_formula_with_the_model_off(profile):
    tuning = load_tuning(profile)
    rng = random.Random(3)
    for _ in range(500):
        out_type = rng.choice(["groundout", "flyout", "lineout"])
        fa, arm = rng.uniform(20, 90), rng.uniform(20, 90)
        expected = _old_error_probability(out_type, fa, arm, tuning)
        got = fielding.error_probability(
            out_type=out_type, infield_play=True, fielding=fa, arm=arm, tuning=tuning
        )
        assert got == expected
        # A position handed in is not read while the model is off.
        assert fielding.error_probability(
            out_type=out_type, infield_play=True, fielding=fa, arm=arm,
            tuning=tuning, position="3B",
        ) == expected


def test_the_fielder_helpers_answer_as_before_with_the_switches_off():
    tuning = load_tuning({**WILD_CENTERS})
    for primary, other, position, scale in (
        ("SS", ["2B"], "SS", 1.0), ("SS", ["2B"], "2B", 0.9), ("SS", ["2B"], "CF", 0.75),
    ):
        player = _fielder(primary, other, fa=57.3, arm=44.0)
        assert fielding.adjusted_fielding_rating(player, position, tuning) == 57.3 * scale
        assert fielding.fielder_arm_rating(player, position, tuning) == 44.0
        assert fielding.adjusted_arm_rating(player, tuning) == 44.0
        assert engine._error_roll_ratings(
            fielder=player, position=position, tuning=tuning
        ) == (57.3 * scale, 44.0)
    defense = {
        pos: _fielder(pos, fa=40.0 + 3 * i, arm=45.0 + i)
        for i, pos in enumerate(("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"))
    }
    ratings = fielding.compute_defense_ratings(defense, tuning)
    fas = {pos: 40.0 + 3 * i for i, pos in enumerate(defense)}
    assert ratings.infield == sum(fas[p] for p in ("C", "1B", "2B", "3B", "SS")) / 5
    assert ratings.outfield == sum(fas[p] for p in ("LF", "CF", "RF")) / 3
    assert ratings.infield_left == (fas["3B"] + fas["SS"]) / 2
    assert ratings.infield_right == (fas["1B"] + fas["2B"]) / 2
    assert (ratings.outfield_left, ratings.outfield_center, ratings.outfield_right) == (
        fas["LF"], fas["CF"], fas["RF"]
    )
    # The per-position ratings ride along and do not change equality.
    assert ratings.positions == fas
    assert ratings == fielding.DefenseRatings(
        ratings.infield, ratings.outfield, ratings.arm, ratings.infield_left,
        ratings.infield_right, ratings.outfield_left, ratings.outfield_center,
        ratings.outfield_right,
    )


def test_no_draw_is_added_while_the_error_model_is_off(monkeypatch):
    """The four rolls ``error_model`` 2 adds are never asked for below it."""
    asked = []
    real = engine.extra_error_probability

    def spy(rate_key, **kwargs):
        asked.append(rate_key)
        return real(rate_key, **kwargs)

    monkeypatch.setattr(engine, "extra_error_probability", spy)
    key = LEGACY_KEYS[0]
    for extra in ({}, {"error_model": 1.0}):
        base = REPO / "data" / key[0]
        _play(*key[:4], kpis.with_rating_centers(extra, base / "players.csv", base))
        assert asked == [], extra
    _play(*key[:4], {"error_model": 2.0})
    assert set(asked) >= {"error_of_hit_rate"}
