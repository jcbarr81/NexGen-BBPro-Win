"""Release 5, situational modifiers (plan section 2.4; owner decisions 3, 4, 8).

Six knobs, every one off by default:

- ``pitch_objective_fbo_requires_risp``: the first-base-open pitch-objective
  modifier applies only with a runner in scoring position.
- ``pitch_objective_late_close_strength``: scales the late-and-close table's
  distance from 1.0 (1.0 = the table untouched, 0.0 = no change late).
- ``reliever_fresh_bonus`` (+ ``_bf_full`` / ``_bf_end``): control and
  movement for a pitcher who did not start the game, by batters faced.
- ``home_field_edge`` (+ ``home_field_power_ratio``): zero-sum, home batters
  up and road batters down.
- ``tto_pass2_weight`` / ``tto_pass3_weight``: per-pass weights on the
  times-through-the-order bonuses (the defaults are the old linear count).
- ``foul_territory_scale`` 0 is a profile value, not a new knob.

The switched-on values live in ``scripts/kpi_profiles/r5_situational.json``.
With no overrides the engine must play exactly as before this work: the
pinned digests below were taken on the commit before it (``r5a-merge``).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.data_loader import load_players_by_id
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.usage import UsageState
from scripts import physics_sim_season_kpis as kpis

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r5_situational.json"

# Every key this work registered, with the value that leaves the engine as
# it was.
OFF_VALUES = {
    "pitch_objective_fbo_requires_risp": 0.0,
    "pitch_objective_late_close_strength": 1.0,
    "reliever_fresh_bonus": 0.0,
    "reliever_fresh_bf_full": 4.0,
    "reliever_fresh_bf_end": 7.0,
    "home_field_edge": 0.0,
    "home_field_power_ratio": 0.6,
    "tto_pass2_weight": 1.0,
    "tto_pass3_weight": 2.0,
}
# One switched-on override per switch, for the "it reaches the engine" check.
SWITCHES = {
    "fbo": {"pitch_objective_fbo_requires_risp": 1.0},
    "late_close": {"pitch_objective_late_close_strength": 0.0},
    "reliever": {"reliever_fresh_bonus": 1.0},
    "home": {"home_field_edge": 0.8},
    "tto": {"tto_pass2_weight": 4.5},
    "foul": {"foul_territory_scale": 0.0},
}


# --- registration and the profile ---------------------------------------------


def test_new_knobs_are_registered_with_their_off_values():
    # from_overrides silently drops a key that is not in DEFAULT_TUNING.
    for key, value in OFF_VALUES.items():
        assert DEFAULT_TUNING[key] == value, key
    assert DEFAULT_TUNING["foul_territory_scale"] == 1.0
    tuning = load_tuning({key: 3.0 for key in OFF_VALUES})
    for key in OFF_VALUES:
        assert tuning.get(key) == 3.0, key


def test_profile_holds_registered_switched_on_values():
    raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    loaded = kpis.load_tuning_overrides_file(PROFILE_PATH)
    assert set(loaded) == set(raw)
    assert set(raw) <= set(DEFAULT_TUNING)
    assert raw["foul_territory_scale"] == 0.0  # owner decision 8
    assert raw["pitch_objective_fbo_requires_risp"] == 1.0
    assert raw["pitch_objective_late_close_strength"] == 0.0
    assert raw["reliever_fresh_bonus"] > 0.0
    assert raw["home_field_edge"] > 0.0
    assert raw["tto_pass2_weight"] > 1.0
    # Held until Release 6 (the plan): the third pass keeps today's weight.
    assert raw["tto_pass3_weight"] == DEFAULT_TUNING["tto_pass3_weight"]
    tuning = load_tuning(loaded)
    for key, value in raw.items():
        assert tuning.get(key) == float(value), key


# --- pitch objectives ----------------------------------------------------------


def _legacy_objective_weights(balls, strikes, tuning, context):
    """``choose_pitch_objective``'s weights before Release 5, frozen."""
    weights = dict(
        physics._objective_weight_table(tuning)[(min(balls, 3), min(strikes, 2))]
    )
    bases = context.get("bases") or {}
    if bases.get("second") or bases.get("third"):
        for key, value in tuning.values["pitch_objective_risp_mod"].items():
            weights[key] *= value
    if not bases.get("first"):
        for key, value in tuning.values["pitch_objective_first_base_open_mod"].items():
            weights[key] *= value
    inning = int(context.get("inning", 1) or 1)
    score_diff = int(context.get("score_diff", 0) or 0)
    if inning >= 7 and abs(score_diff) <= 2:
        for key, value in tuning.values["pitch_objective_late_close_mod"].items():
            weights[key] *= value
    return weights


def _objective_weights(monkeypatch, tuning, context, count=(1, 1)):
    seen = {}

    def capture(weights):
        seen.update(weights)
        return next(iter(weights))

    monkeypatch.setattr(physics, "_weighted_choice", capture)
    physics.choose_pitch_objective(
        balls=count[0], strikes=count[1], tuning=tuning, context=context
    )
    return seen


def _context(first=False, second=False, third=False, inning=1, score_diff=0):
    return {
        "inning": inning,
        "score_diff": score_diff,
        "bases": {"first": first, "second": second, "third": third},
    }


def _table(tuning, count=(1, 1)):
    return dict(physics._objective_weight_table(tuning)[count])


def test_objective_weights_are_unchanged_at_the_defaults(monkeypatch):
    tuning = load_tuning()
    for mask in range(8):
        for inning in (1, 6, 7, 9, 11):
            for score_diff in (-3, -2, 0, 1, 2, 3):
                for count in ((0, 0), (1, 1), (0, 2), (3, 0), (3, 2)):
                    context = _context(
                        bool(mask & 1), bool(mask & 2), bool(mask & 4),
                        inning, score_diff,
                    )
                    got = _objective_weights(monkeypatch, tuning, context, count)
                    # Exact: the off path must be bit-identical.
                    assert got == _legacy_objective_weights(*count, tuning, context)


def test_first_base_open_needs_a_runner_in_scoring_position(monkeypatch):
    off = load_tuning()
    on = load_tuning(SWITCHES["fbo"])
    fbo = DEFAULT_TUNING["pitch_objective_first_base_open_mod"]
    risp = DEFAULT_TUNING["pitch_objective_risp_mod"]
    table = _table(on)

    # Bases empty: no modifier at all with the switch on.
    empty = _context()
    assert _objective_weights(monkeypatch, on, empty) == table
    assert _objective_weights(monkeypatch, off, empty) == {
        key: table[key] * fbo[key] for key in table
    }
    # Runner on first only: nothing either way (first base is not open).
    assert _objective_weights(monkeypatch, on, _context(first=True)) == table
    assert _objective_weights(monkeypatch, off, _context(first=True)) == table
    # First base open with a runner on second and/or third: unchanged.
    for second, third in ((True, False), (False, True), (True, True)):
        context = _context(second=second, third=third)
        expected = {key: table[key] * risp[key] * fbo[key] for key in table}
        assert _objective_weights(monkeypatch, on, context) == expected
        assert _objective_weights(monkeypatch, off, context) == expected
    # First and second: scoring position, but no open base.
    context = _context(first=True, second=True)
    expected = {key: table[key] * risp[key] for key in table}
    assert _objective_weights(monkeypatch, on, context) == expected


def test_late_close_strength_scales_the_table(monkeypatch):
    late = DEFAULT_TUNING["pitch_objective_late_close_mod"]
    context = _context(first=True, inning=8, score_diff=1)
    table = _table(load_tuning())

    full = _objective_weights(monkeypatch, load_tuning(), context)
    assert full == {key: table[key] * late[key] for key in table}  # exact
    off = load_tuning(SWITCHES["late_close"])
    assert _objective_weights(monkeypatch, off, context) == table  # exact
    half = _objective_weights(
        monkeypatch, load_tuning({"pitch_objective_late_close_strength": 0.5}), context
    )
    for key in table:
        assert half[key] == pytest.approx(table[key] * (1.0 + (late[key] - 1.0) * 0.5))
    assert any(half[key] != full[key] for key in table)

    # Not late, or not close: the strength is never read.
    for inning, score_diff in ((6, 0), (8, 3), (9, -3)):
        context = _context(first=True, inning=inning, score_diff=score_diff)
        assert _objective_weights(monkeypatch, off, context) == table


def test_objective_switches_draw_the_same_random_numbers():
    contexts = [
        _context(bool(m & 1), bool(m & 2), bool(m & 4), inning, diff)
        for m in range(8) for inning in (1, 8) for diff in (0, 4)
    ]
    states = []
    for overrides in (None, SWITCHES["fbo"], SWITCHES["late_close"]):
        tuning = load_tuning(overrides)
        random.seed(20261012)
        for context in contexts:
            physics.choose_pitch_objective(
                balls=1, strikes=2, tuning=tuning, context=context
            )
        states.append(random.getstate())
    assert states[0] == states[1] == states[2]


# --- reliever fresh-arm edge ---------------------------------------------------


def test_reliever_fresh_bonus_fades_by_batters_faced():
    tuning = load_tuning(SWITCHES["reliever"])
    values = [
        engine._reliever_fresh_bonus(started=False, batters_faced=bf, tuning=tuning)
        for bf in range(1, 10)
    ]
    assert values[:4] == [1.0, 1.0, 1.0, 1.0]
    assert values[4] == pytest.approx(2.0 / 3.0)
    assert values[5] == pytest.approx(1.0 / 3.0)
    assert values[6:] == [0.0, 0.0, 0.0]
    assert values == sorted(values, reverse=True)
    # Never the pitcher who started the game, whatever his role label.
    for bf in range(1, 10):
        assert engine._reliever_fresh_bonus(
            started=True, batters_faced=bf, tuning=tuning
        ) == 0.0


def test_reliever_fresh_bonus_is_off_by_default_and_follows_its_knobs():
    off = load_tuning()
    for bf in range(1, 10):
        assert engine._reliever_fresh_bonus(
            started=False, batters_faced=bf, tuning=off
        ) == 0.0
    tuning = load_tuning(
        {"reliever_fresh_bonus": 2.0, "reliever_fresh_bf_full": 2.0,
         "reliever_fresh_bf_end": 4.0}
    )
    got = [
        engine._reliever_fresh_bonus(started=False, batters_faced=bf, tuning=tuning)
        for bf in range(1, 6)
    ]
    assert got == [2.0, 2.0, 1.0, 0.0, 0.0]
    # A degenerate window (end <= full) is a step, not a division by zero.
    step = load_tuning(
        {"reliever_fresh_bonus": 1.0, "reliever_fresh_bf_full": 3.0,
         "reliever_fresh_bf_end": 3.0}
    )
    assert [
        engine._reliever_fresh_bonus(started=False, batters_faced=bf, tuning=step)
        for bf in (3, 4)
    ] == [1.0, 0.0]


def _traced_game(monkeypatch, overrides, seed):
    """Play CAL01 at CAL02 recording what each pitch and PA was given."""
    fresh_calls: list[tuple[bool, int, float]] = []
    pitches: list[dict] = []
    contexts: list[tuple[str, object, int]] = []
    real_fresh = engine._reliever_fresh_bonus
    real_pitch = engine.simulate_pitch
    real_context = engine._batter_context

    def fresh(**kwargs):
        value = real_fresh(**kwargs)
        fresh_calls.append((kwargs["started"], kwargs["batters_faced"], value))
        return value

    def pitch(**kwargs):
        pitches.append(
            {
                "pa": len(fresh_calls) - 1,
                "control": kwargs["pitcher"]["control"],
                "movement": kwargs["pitcher"]["movement"],
                "velocity": kwargs["pitcher"]["velocity"],
                "fatigue_factor": kwargs["pitcher"]["fatigue_factor"],
            }
        )
        return real_pitch(**kwargs)

    def context(batter, pitcher, tuning, **kwargs):
        contexts.append((batter.player_id, kwargs.get("home"), kwargs.get("tto")))
        return real_context(batter, pitcher, tuning, **kwargs)

    monkeypatch.setattr(engine, "_reliever_fresh_bonus", fresh)
    monkeypatch.setattr(engine, "simulate_pitch", pitch)
    monkeypatch.setattr(engine, "_batter_context", context)
    result = _play_cal(seed, overrides)
    return result, fresh_calls, pitches, contexts


def test_engine_gives_the_edge_to_relievers_only(monkeypatch):
    _batters, pitchers_by_id = load_players_by_id(CALIBRATION / "players.csv")
    seen_full = seen_partial = seen_gone = seen_starter = 0
    for seed in (1, 2, 3):
        result, fresh_calls, pitches, _ = _traced_game(
            monkeypatch, SWITCHES["reliever"], seed
        )
        monkeypatch.undo()
        starters = {
            line["player_id"]
            for side in ("away", "home")
            for line in result.metadata["pitcher_lines"][side]
            if line["gs"] >= 1
        }
        assert len(starters) == 2
        entries = [e for e in result.pitch_log if "pitch_count" in e]
        assert len(entries) == len(pitches)
        last_bf: dict[str, int] = {}
        for entry, pitch in zip(entries, pitches):
            pid = entry["pitcher_id"]
            started, bf, bonus = fresh_calls[pitch["pa"]]
            rating = pitchers_by_id[pid]
            velocity_factor, command_factor, movement_factor = engine._fatigue_factors(
                entry["fatigue_penalty"]
            )
            # Batters faced is this appearance's count: it starts at 1 for
            # every pitcher and never goes down.
            assert bf >= last_bf.get(pid, 1) >= 1
            last_bf[pid] = bf
            assert started == (pid in starters)
            if started:
                assert bonus == 0.0
                seen_starter += 1
            else:
                expected = max(0.0, min(1.0, (7.0 - bf) / 3.0))
                assert bonus == pytest.approx(expected)
                seen_full += bonus == 1.0
                seen_partial += 0.0 < bonus < 1.0
                seen_gone += bonus == 0.0
            # Added before the fatigue factors; velocity is left alone.
            assert pitch["control"] == pytest.approx(
                (rating.control + bonus) * command_factor
            )
            assert pitch["movement"] == pytest.approx(
                (rating.movement + bonus) * movement_factor
            )
            assert pitch["velocity"] == 83.0 + rating.arm * 0.2
            assert pitch["fatigue_factor"] == velocity_factor
    assert seen_starter and seen_full and seen_partial and seen_gone


# --- home field ---------------------------------------------------------------


def _batter(**ratings) -> BatterRatings:
    row = {"player_id": "b", "bats": "R", "primary_position": "LF", "ch": "50",
           "ph": "50", "vl": "50", "eye": "50", "gf": "50", "pl": "50",
           "fa": "50", "arm": "50", "sp": "50"}
    row.update({key: str(value) for key, value in ratings.items()})
    return BatterRatings.from_row(row)


def _pitcher() -> PitcherRatings:
    return PitcherRatings.from_row(
        {"player_id": "p", "bats": "R", "throws": "R", "control": "50", "fb": "60"}
    )


def test_home_field_edge_is_zero_sum():
    tuning = load_tuning({"home_field_edge": 0.8, "home_field_power_ratio": 0.6})
    batter, pitcher = _batter(), _pitcher()
    neutral = engine._batter_context(batter, pitcher, tuning)
    home = engine._batter_context(batter, pitcher, tuning, home=True)
    road = engine._batter_context(batter, pitcher, tuning, home=False)
    for key, size in (("contact", 0.8), ("eye", 0.8), ("power", 0.48)):
        assert home[key] - neutral[key] == pytest.approx(size)
        assert road[key] - neutral[key] == pytest.approx(-size)
        assert home[key] + road[key] == pytest.approx(2.0 * neutral[key])
    untouched = set(neutral) - {"contact", "eye", "power"}
    for key in untouched:
        assert home[key] == road[key] == neutral[key]
    # No side given (the KPI helper, any one-off caller): no edge.
    assert engine._batter_context(batter, pitcher, tuning, home=None) == neutral


def test_home_field_edge_is_off_by_default_and_stays_clamped():
    off = load_tuning()
    batter, pitcher = _batter(), _pitcher()
    neutral = engine._batter_context(batter, pitcher, off)
    assert engine._batter_context(batter, pitcher, off, home=True) == neutral
    assert engine._batter_context(batter, pitcher, off, home=False) == neutral
    on = load_tuning({"home_field_edge": 5.0})
    top = engine._batter_context(_batter(ch=99, ph=99, eye=99), pitcher, on, home=True)
    low = engine._batter_context(_batter(ch=1, ph=1, eye=1), pitcher, on, home=False)
    for key in ("contact", "power"):
        assert top[key] == 100.0
        assert low[key] == 1.0
    assert 1.0 <= low["eye"] <= top["eye"] <= 100.0


def test_engine_marks_the_home_side_for_every_plate_appearance(monkeypatch):
    for postseason in (False, True):
        result, _fresh, _pitches, contexts = _traced_game(
            monkeypatch, {**SWITCHES["home"], "_postseason": postseason}, 2
        )
        monkeypatch.undo()
        sides = {
            side: {line["player_id"] for line in result.metadata["batting_lines"][side]}
            for side in ("away", "home")
        }
        assert not sides["away"] & sides["home"]
        assert contexts
        for player_id, home, _tto in contexts:
            assert home is (player_id in sides["home"])
        assert {home for _pid, home, _tto in contexts} == {True, False}


# --- times through the order ---------------------------------------------------


def test_tto_pass_weights_default_to_the_linear_count():
    for max_passes in (1.0, 2.0, 3.0, 4.0, 5.0):
        tuning = load_tuning({"tto_max_passes": max_passes})
        for tto in range(0, 8):
            passes = min(tto, int(max_passes))
            legacy = float(max(0, passes - 1))
            assert engine._tto_pass_weight(passes, tuning) == legacy
    # A TuningConfig from before the knobs existed behaves the same.
    bare = load_tuning()
    del bare.values["tto_pass2_weight"], bare.values["tto_pass3_weight"]
    bare.invalidate_cache()
    assert [engine._tto_pass_weight(n, bare) for n in (1, 2, 3)] == [0.0, 1.0, 2.0]


def test_tto_pass_weights_scale_each_pass_separately():
    off = load_tuning()
    on = load_tuning({"tto_pass2_weight": 4.5})
    batter, pitcher = _batter(), _pitcher()
    first = engine._batter_context(batter, pitcher, on, tto=1)
    second = engine._batter_context(batter, pitcher, on, tto=2)
    third = engine._batter_context(batter, pitcher, on, tto=3)
    for key in ("contact", "eye", "power"):
        bonus = on.get(f"tto_{key}_bonus")
        assert second[key] - first[key] == pytest.approx(4.5 * bonus)
        # The third pass is held at today's size.
        assert third[key] - first[key] == pytest.approx(2.0 * bonus)
        assert third[key] == engine._batter_context(batter, pitcher, off, tto=3)[key]
    assert first == engine._batter_context(batter, pitcher, off, tto=1)
    both = load_tuning({"tto_pass2_weight": 3.0, "tto_pass3_weight": 5.0})
    third = engine._batter_context(batter, pitcher, both, tto=3)
    assert third["contact"] - first["contact"] == pytest.approx(
        5.0 * both.get("tto_contact_bonus")
    )


# --- whole games: nothing changes while the switches are off -----------------


def _play_cal(seed, overrides=None):
    overrides = dict(overrides) if overrides else {}
    postseason = bool(overrides.pop("_postseason", False))
    return engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv",
        park_name="New Yankee Stadium", seed=seed,
        tuning_overrides=overrides or None, postseason=postseason,
    )


def _play_league(seed, overrides=None):
    return engine.simulate_matchup_from_files(
        away_team="ALB", home_team="DET", base_dir=CALIBRATION_LEAGUE,
        players_path=CALIBRATION_LEAGUE / "players.csv", seed=seed,
        tuning_overrides=dict(overrides) if overrides else None,
    )


def _play_series(overrides=None):
    """Three dated games on one usage state (rest, bullpen availability)."""
    usage_state = UsageState()
    return [
        engine.simulate_matchup_from_files(
            away_team="CAL03", home_team="CAL04", base_dir=CALIBRATION,
            players_path=CALIBRATION / "players.csv", seed=100 + day,
            tuning_overrides=dict(overrides) if overrides else None,
            usage_state=usage_state, game_day=day,
        )
        for day in range(3)
    ]


def _canon(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def _digest(*results) -> str:
    blob = json.dumps(
        _canon(
            [
                {"pitch_log": r.pitch_log, "totals": r.totals, "meta": r.metadata}
                for r in results
            ]
        ),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _all_digests(overrides=None) -> dict[str, str]:
    digests = {f"cal{seed}": _digest(_play_cal(seed, overrides)) for seed in (1, 2, 3)}
    digests["cal_postseason"] = _digest(
        _play_cal(4, {**(overrides or {}), "_postseason": True})
    )
    digests["cal_series"] = _digest(*_play_series(overrides))
    for seed in (1, 2):
        digests[f"league{seed}"] = _digest(_play_league(seed, overrides))
    return digests


# sha256 of the canonical JSON (floats rounded to 6 places) of the pitch log,
# totals and metadata of seeded games at the default tuning, taken on
# ``r5a-merge`` (7.50.2) BEFORE any Release 5 situational code existed. They
# are the check that every new knob's default reproduces the old engine and
# draws no extra random number. RE-BASELINE only when the default-tuning
# stream changes on purpose (run this file and copy the "got" digests from
# the failure message); at the Release 5 switch-on, pass the legacy profile
# to ``_all_digests`` instead, as Release 4 did with r4a_legacy.json.
PINNED_DIGESTS = {
    "cal1": "6801d33f08f2371126ce0c650bda44c1561132b5f7bb4919f9a3d2ec6a5f4e09",
    "cal2": "ffc96279b688bb8b6c4888115c9ae2f330ab1045bf6d1f245cf7c7e72935f680",
    "cal3": "66cd7a9dce865fa2daf1ac2494a6a0f1e1590b6f3d3c530a2109212815921445",
    "cal_postseason": "7ce596c86feda4303acacff31ccb1ed4fa323ba40d9587bcc982563961cf0fbf",
    "cal_series": "413893a9cd783120854a6b0573deaefe5fdd57beab18b5a1af3edd49cde3220d",
    "league1": "3bfff8bea99e8b02a2af8e6447c83c12a37b520683ac2306a3b9d0a9ff73553a",
    "league2": "3a04be9e856af0a926ccd2c3a9a126bcd598e7d5da36e04657b4120fdb1c1abf",
}


def test_default_tuning_games_match_the_pinned_digests():
    got = _all_digests()
    assert got == PINNED_DIGESTS, f"got {got}"


def test_explicit_off_values_are_the_defaults():
    assert _all_digests(OFF_VALUES) == PINNED_DIGESTS


@pytest.mark.parametrize("name", sorted(SWITCHES))
def test_each_switch_reaches_the_engine(name):
    # The metadata carries no tuning, so a digest differs only when the
    # games were played differently. The league games use generic parks,
    # so the foul-territory switch must leave them alone.
    got = _all_digests(SWITCHES[name])
    changed = {key for key, value in got.items() if value != PINNED_DIGESTS[key]}
    if name == "foul":
        assert changed == {"cal1", "cal2", "cal3", "cal_postseason"}
    else:
        assert {"cal1", "cal2", "cal3"} & changed, name
        assert changed & {"league1", "league2"}, name
