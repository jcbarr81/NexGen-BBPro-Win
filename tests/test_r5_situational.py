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
from types import SimpleNamespace

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


# The edge in the cases where "who started" and "how many batters has he
# faced" could go wrong: a reliever who starts the game, an emergency or
# rest-flagged arm, a pitcher who comes in for an injured one, a plate
# appearance cut short, and a bunt or intentional walk as a reliever's first
# batter. Each game is replayed from its pitch log alone -- who started is
# the box score's GS, batters faced is the count of plate appearances the
# pitcher was charged with -- and every pitch must have been given exactly
# the bonus that replay says.

def _plate_appearances(pitch_log):
    """The log split at each ``pa_start`` entry."""
    groups = []
    for entry in pitch_log:
        if entry.get("pa_start"):
            groups.append([entry])
        else:
            groups[-1].append(entry)
    return groups


def _cut_short(pa) -> bool:
    """Ended by the third out on the bases or a walk-off run, not by the
    batter: no result (catcher's interference has none either)."""
    return (
        not any(entry.get("pa_result") for entry in pa)
        and pa[-1].get("outcome") != "interference"
    )


def _pitch_trace(monkeypatch, play):
    """``play()``'s result and the control and movement each pitch was
    thrown with."""
    given: list[tuple[float, float]] = []
    real = engine.simulate_pitch

    def pitch(**kwargs):
        given.append((kwargs["pitcher"]["control"], kwargs["pitcher"]["movement"]))
        return real(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(engine, "simulate_pitch", pitch)
        result = play()
    return result, given


def _replay_fresh_edge(result, given, ratings, bonus=1.0):
    """Check every pitch against the fresh-arm bonus the pitch log implies.

    Returns one row per plate appearance: ``(pitcher_id, started, batters
    faced, kind, cut short, bonus)``, ``kind`` being "ibb", "bunt" or
    "pitch".
    """
    starters = {
        line["player_id"]
        for side in ("away", "home")
        for line in result.metadata["pitcher_lines"][side]
        if line["gs"] >= 1
    }
    assert len(starters) == 2
    thrown = iter(given)
    faced: dict[str, int] = {}
    rows = []
    for pa in _plate_appearances(result.pitch_log):
        pid = pa[0]["pitcher_id"]
        # Batters faced counts this batter; a plate appearance cut short is
        # not charged, so it does not use up one of the fresh batters.
        batters_faced = faced.get(pid, 0) + 1
        cut = _cut_short(pa)
        if not cut:
            faced[pid] = batters_faced
        started = pid in starters
        expected = 0.0
        if not started:
            expected = bonus * max(0.0, min(1.0, (7.0 - batters_faced) / 3.0))
        kind = "pitch" if "pitch_type" in pa[0] else pa[0]["outcome"]
        rows.append((pid, started, batters_faced, kind, cut, expected))
        for entry in pa:
            if "pitch_type" not in entry:
                continue
            control, movement = next(thrown)
            # The pitcher never changes inside a plate appearance.
            assert entry["pitcher_id"] == pid
            _velo, command_factor, movement_factor = engine._fatigue_factors(
                entry["fatigue_penalty"]
            )
            rating = ratings[pid]
            assert control == pytest.approx(
                (rating.control + expected) * command_factor
            ), (pid, batters_faced, kind)
            assert movement == pytest.approx(
                (rating.movement + expected) * movement_factor
            ), (pid, batters_faced, kind)
    assert next(thrown, None) is None
    # The replay's count is the box score's.
    for side in ("away", "home"):
        for line in result.metadata["pitcher_lines"][side]:
            assert line["bf"] == faced.get(line["player_id"], 0)
    return rows


RELIEVER_ON = SWITCHES["reliever"]


def test_a_reliever_who_starts_the_game_gets_no_fresh_edge(monkeypatch):
    _batters, ratings = load_players_by_id(CALIBRATION / "players.csv")
    opener: list[str] = []
    real_game = engine.simulate_game

    def game(**kwargs):
        # The home club starts a middle reliever (an opener): the rotation
        # tracker's assigned starter is not one of the five.
        roles = kwargs["home_pitcher_roles"]
        opener.append(
            next(p.player_id for p in kwargs["home_pitchers"]
                 if roles.get(p.player_id, "").upper().startswith("MR"))
        )
        return real_game(**{**kwargs, "home_starter_id": opener[0]})

    monkeypatch.setattr(engine, "simulate_game", game)
    result, given = _pitch_trace(monkeypatch, lambda: _play_cal(1, RELIEVER_ON))
    rows = _replay_fresh_edge(result, given, ratings)
    home = {line["player_id"]: line for line in result.metadata["pitcher_lines"]["home"]}
    assert home[opener[0]]["gs"] == 1
    opener_rows = [row for row in rows if row[0] == opener[0]]
    # He faced batters, the first of them included, with no bonus...
    assert len(opener_rows) >= 3 and opener_rows[0][2] == 1
    assert all(started and bonus == 0.0 for _p, started, _bf, _k, _c, bonus in opener_rows)
    # ...and the men who followed him got theirs.
    followers = [row for row in rows if row[0] in home and row[0] != opener[0]]
    assert any(bonus == 1.0 and bf == 1 for _p, _s, bf, _k, _c, bonus in followers)


def test_emergency_and_rest_flagged_arms_get_the_fresh_edge(monkeypatch):
    # Four games on one usage state empty the bullpens: on the fourth day
    # the road club uses a rest-flagged reliever and a rested starter out of
    # the pen. Neither started this game, so both get the edge.
    _batters, ratings = load_players_by_id(CALIBRATION / "players.csv")
    usage_state = UsageState()
    flagged = {}
    for day in range(4):
        def play(day=day):
            return engine.simulate_matchup_from_files(
                away_team="CAL03", home_team="CAL04", base_dir=CALIBRATION,
                players_path=CALIBRATION / "players.csv", seed=100 + day,
                tuning_overrides=dict(RELIEVER_ON), usage_state=usage_state,
                game_day=day,
            )

        result, given = _pitch_trace(monkeypatch, play)
        rows = _replay_fresh_edge(result, given, ratings)
        for side in ("away", "home"):
            for arm in result.metadata["pitcher_usage"][side]:
                if not arm["pitches"] or not (arm["fallback"] or arm["emergency"]):
                    continue
                kind = "emergency" if arm["emergency"] else "fallback"
                first = next(row for row in rows if row[0] == arm["player_id"])
                assert first[1] is False and first[2] == 1 and first[5] == 1.0
                flagged.setdefault(kind, []).append((day, arm["staff_role"]))
    assert flagged.get("fallback") and flagged.get("emergency"), flagged
    # The emergency arm is a starter by role, pitching in relief.
    assert all(role.upper().startswith("SP") for _day, role in flagged["emergency"])


def test_the_man_who_replaces_an_injured_pitcher_gets_the_fresh_edge(monkeypatch):
    _batters, ratings = load_players_by_id(CALIBRATION_LEAGUE / "players.csv")
    result, given = _pitch_trace(monkeypatch, lambda: _play_league(26, RELIEVER_ON))
    rows = _replay_fresh_edge(result, given, ratings)
    hurt = [
        event for event in result.metadata["injury_events"]
        if event.get("trigger") == "pitcher_overuse"
    ]
    assert len(hurt) == 1
    injured = hurt[0]["player_id"]
    order = [row[0] for row in rows]
    last = len(order) - 1 - order[::-1].index(injured)
    side = hurt[0]["team"]
    staff = {line["player_id"] for line in result.metadata["pitcher_lines"][side]}
    relief = next(row for row in rows[last + 1:] if row[0] in staff)
    # The injured man started; his replacement's first batter is batter one
    # of a fresh arm.
    assert rows[last][1] is True
    assert relief[0] != injured and relief[1] is False
    assert relief[2] == 1 and relief[5] == 1.0


def test_a_plate_appearance_cut_short_does_not_use_up_a_fresh_batter(monkeypatch):
    _batters, ratings = load_players_by_id(CALIBRATION / "players.csv")
    checked = 0
    # Seed 39: a reliever's fourth batter; seed 16 (with intentional walks
    # switched on and eager): a reliever's first.
    for seed, overrides in ((39, RELIEVER_ON), (16, EAGER_IBB)):
        result, given = _pitch_trace(monkeypatch, lambda: _play_cal(seed, overrides))
        rows = _replay_fresh_edge(result, given, ratings)
        cut = [
            (index, row) for index, row in enumerate(rows)
            if row[4] and not row[1] and row[2] <= 6
        ]
        assert cut, f"seed {seed}: no plate appearance cut short on a fresh reliever"
        for index, (pid, _started, batters_faced, _kind, _cut, bonus) in cut:
            assert bonus > 0.0
            # The next batter he faces has the same number and the same bonus.
            later = next((row for row in rows[index + 1:] if row[0] == pid), None)
            if later is not None:
                assert later[2] == batters_faced and later[5] == bonus
                checked += 1
    assert checked


# The Release 5 intentional walk made eager, with the reliever edge on.
EAGER_IBB = {
    **RELIEVER_ON, "ibb_model": 1.0, "ibb_chance": 0.9, "ibb_gap_min": 0.0,
    "ibb_gap_full": 1.0, "ibb_early_scale": 1.0, "ibb_no_out_scale": 1.0,
}


def test_a_bunt_or_intentional_walk_counts_as_a_reliever_s_first_batter(monkeypatch):
    # No pitch is thrown on either, so no pitch gets the bonus; the batter
    # still counts, and the next one is the reliever's second.
    _batters, ratings = load_players_by_id(CALIBRATION / "players.csv")
    eager = EAGER_IBB
    seen = set()
    for seed in (16, 30):
        result, given = _pitch_trace(monkeypatch, lambda: _play_cal(seed, eager))
        rows = _replay_fresh_edge(result, given, ratings)
        for index, (pid, started, batters_faced, kind, _cut, _bonus) in enumerate(rows):
            if started or batters_faced != 1 or kind == "pitch":
                continue
            seen.add(kind)
            later = next((row for row in rows[index + 1:] if row[0] == pid), None)
            if later is not None:
                assert later[2] == 2 and later[5] == 1.0
    assert seen == {"ibb", "bunt"}


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


class _Captured(Exception):
    pass


def test_playoff_games_reach_the_engine_with_the_home_club_at_home(monkeypatch):
    """Owner decision 3: the same edge in the playoffs.

    A playoff game is the regular game runner flagged ``postseason``; it
    hands the engine the home club as ``home_lineup`` and the stored tuning,
    so the edge applies there exactly as in the regular season.
    """
    import physics_sim.data_loader as loader
    import playbalance.game_runner as gr
    import playbalance.playoffs as playoffs
    from utils import league_settings as ls

    playoff_sim = playoffs._default_simulate_game()
    assert playoff_sim.func is gr.simulate_game_scores
    assert playoff_sim.keywords == {"postseason": True}

    batters = {f"B{i}": SimpleNamespace(player_id=f"B{i}") for i in range(18)}
    arms = {f"P{i}": SimpleNamespace(player_id=f"P{i}") for i in range(2)}
    monkeypatch.setattr(loader, "load_players_by_id", lambda path: (batters, arms))
    monkeypatch.setattr(
        gr, "get_physics_tuning_overrides", lambda *_a, **_k: {"home_field_edge": 0.8}
    )
    monkeypatch.setattr(gr, "get_injury_tuning_overrides", lambda: {})
    monkeypatch.setattr(gr, "get_rating_center_overrides", lambda: {})
    monkeypatch.setattr(
        ls, "load_league_settings", lambda path=None: {"extra_innings_runner": True}
    )
    seen = {}

    def fake_simulate_game(**kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(engine, "simulate_game", fake_simulate_game)

    def state(offset):
        return SimpleNamespace(
            lineup=[
                SimpleNamespace(player_id=f"B{i + offset}", position="CF")
                for i in range(9)
            ],
            bench=[],
            pitchers=[
                SimpleNamespace(
                    player_id=f"P{offset // 9}", assigned_pitching_role="SP1"
                )
            ],
            team=None,
        )

    with pytest.raises(_Captured):
        gr._run_physics_game(
            home_id="H", away_id="A", home_state=state(0), away_state=state(9),
            players_file=str(CALIBRATION / "players.csv"), roster_dir="rosters",
            seed=1, date_token=None, tracker=None, players_lookup={},
            persist_stats=False, postseason=True,
        )
    assert seen["postseason"] is True
    assert [b.player_id for b in seen["home_lineup"]] == [f"B{i}" for i in range(9)]
    assert [b.player_id for b in seen["away_lineup"]] == [f"B{i}" for i in range(9, 18)]
    assert seen["tuning_overrides"]["home_field_edge"] == 0.8


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
        # Full precision: a rating moved in its last bit changes the digest.
        return float.__repr__(value)
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
    for name, extra in EXTRA_INNING_GAMES.items():
        digests[name] = _digest(
            _play_cal(EXTRA_INNING_SEED, {**(overrides or {}), **extra})
        )
    return digests


# One seed that goes past the ninth three ways: a regular-season game (the
# automatic runner from the 10th), a postseason game (no runner) and a league
# that switched the runner off.
EXTRA_INNING_SEED = 6
EXTRA_INNING_GAMES = {
    "cal_extras": {},
    "cal_postseason_extras": {"_postseason": True},
    "cal_extras_no_runner": {"extra_innings_runner": 0.0},
}


# sha256 of the canonical JSON (every float at full precision, as its repr)
# of the pitch log, totals and metadata of seeded games at the default
# tuning, computed on the Release 5a tree (2b1a37952, 7.50.2; exported with
# git archive), which has no Release 5 situational code. They
# are the check that every new knob's default reproduces the old engine and
# draws no extra random number. RE-BASELINE only when the default-tuning
# stream changes on purpose (run this file and copy the "got" digests from
# the failure message); at the Release 5 switch-on, pass the legacy profile
# to ``_all_digests`` instead, as Release 4 did with r4a_legacy.json.
PINNED_DIGESTS = {
    "cal1": "1cde32343e485050a6d5208955d4d69f5e39c9b9e9c147629e88244dfdaf5f4b",
    "cal2": "81e435e3f0935ed4415db2fc7bdbaaedce464da1e7e541436bcf63ff900ef5a8",
    "cal3": "141c531deb229125ad35ac8524381337f0e48c45193955b856bf6db730c54161",
    "cal_postseason": "ce55ca4eae740a3ca0ec84713d642f0d2fbc3e4c8a43ff552537afafec9f3805",
    "cal_series": "47c90108f37807c19a8bb8fa67c1cf7f4a76a8bfb01037ae99bdd0b22884ad80",
    "league1": "c9c2b7741a7eb3317c66d3e00c1324855f6b68797d023d46324913f01fcc404e",
    "league2": "e99b8b674c36e29854670ff2dd1d20d0fbd6a2f7b30012c7bbdf385921c02593",
    "cal_extras": "7d607d110776d28313863dfc606ae62be6ea2329ed9ea6fd627257cffec4128d",
    "cal_postseason_extras":
        "81a68f4f0f99421a1f504aad2e15bb521c5b88a7e60bec1399f6af891758a1fd",
    "cal_extras_no_runner":
        "59328bb5e310e0cfe1a3043dfea4d07010db8e1128bd47581ec14b2ed487cfa2",
}


def test_default_tuning_games_match_the_pinned_digests():
    got = _all_digests()
    assert got == PINNED_DIGESTS, f"got {got}"


def test_the_extra_inning_pins_are_extra_inning_games():
    # The automatic runner, the postseason hooks and the tied-game closer
    # rules are only reached past the ninth.
    expected = {"cal_extras": 2, "cal_postseason_extras": 0, "cal_extras_no_runner": 0}
    for name, extra in EXTRA_INNING_GAMES.items():
        result = _play_cal(EXTRA_INNING_SEED, extra)
        assert result.metadata["innings"] >= 11, name
        firsts = {}
        for entry in result.pitch_log:
            if entry.get("pa_start") and entry["inning"] >= 10:
                firsts.setdefault((entry["inning"], entry["half"]), entry)
        assert len(firsts) >= 3, name
        # Runner on second to open every extra half, or nobody on.
        assert {e["bases_before"] for e in firsts.values()} == {expected[name]}, name


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
        assert changed == {
            "cal1", "cal2", "cal3", "cal_postseason", *EXTRA_INNING_GAMES
        }
    else:
        assert {"cal1", "cal2", "cal3"} & changed, name
        assert changed & {"league1", "league2"}, name
