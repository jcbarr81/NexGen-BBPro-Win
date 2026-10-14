"""Release 6a (fielding): the error models (audit M9, owner decision 9).

``error_model`` 1 re-shapes the error roll the engine already makes on a
ball ruled an out: a base rate by position times ``exp`` of the fielder's
rating and arm, on the same draw. ``error_model`` 2 adds the errors that
need a roll of their own -- the pitcher on a comebacker, the catcher's
throw on a stolen base, an outfielder letting a hit through, a pickoff
throw that gets away and the relay on a force play -- and draws for them
only while it is on.

The second half plays scripted innings (the pitches, the out rolls and the
steal and pickoff attempts are dictated) and reads the box score: who is
charged, which runs are earned, who reached on an error and who gets the
run batted in.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.fielding as fielding
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.outputs import serialize_game_result
from physics_sim.physics import PitchResult
from tests.test_r5_discipline import _digest, _play

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"
BASES = {
    "1B": 0.029, "2B": 0.020, "3B": 0.049, "SS": 0.036, "LF": 0.0069,
    "CF": 0.0037, "RF": 0.0068,
}
EXTRA_RATES = (
    "error_steal_throw_rate", "error_of_hit_rate", "error_pickoff_throw_rate",
    "error_relay_throw_rate",
)


def _tuning(**overrides):
    return load_tuning(overrides)


def _chance(tuning, position, *, out_type="groundout", fa=50.0, arm=50.0):
    return fielding.error_probability(
        out_type=out_type, infield_play=out_type != "flyout", fielding=fa, arm=arm,
        tuning=tuning, position=position,
    )


# --- error_model 1: the shape --------------------------------------------------------


def test_the_model_is_off_and_its_numbers_are_the_plan_s():
    assert DEFAULT_TUNING["error_model"] == 0.0
    for pos, base in BASES.items():
        assert DEFAULT_TUNING[f"error_base_{pos.lower()}"] == base
    assert DEFAULT_TUNING["error_base_p"] == 0.045
    assert DEFAULT_TUNING["error_fa_log_slope"] == 0.025
    assert DEFAULT_TUNING["error_arm_log_slope"] == 0.02
    assert DEFAULT_TUNING["error_infield_liner_scale"] == 0.25


def test_an_average_fielder_makes_his_position_s_base_rate():
    tuning = _tuning(error_model=1.0)
    for pos, base in BASES.items():
        out_type = "flyout" if pos in ("LF", "CF", "RF") else "groundout"
        assert _chance(tuning, pos, out_type=out_type) == pytest.approx(base)
    # Third base and short make the most, centre field the fewest.
    assert BASES["3B"] > BASES["SS"] > BASES["1B"] > BASES["2B"] > BASES["LF"]
    assert min(BASES, key=BASES.get) == "CF"


def test_the_ratings_scale_the_rate_in_log_space():
    tuning = _tuning(error_model=1.0)
    base = _chance(tuning, "SS")
    assert _chance(tuning, "SS", fa=60.0) == pytest.approx(base * math.exp(-0.25))
    assert _chance(tuning, "SS", fa=40.0) == pytest.approx(base * math.exp(0.25))
    assert _chance(tuning, "SS", arm=60.0) == pytest.approx(base * math.exp(-0.2))
    assert _chance(tuning, "SS", fa=60.0, arm=40.0) == pytest.approx(
        base * math.exp(-0.25 + 0.2)
    )
    # Monotonic in both, and about three to one from two SDs worse to two
    # better (fa SD 8, the arm at its mean).
    rates = [_chance(tuning, "SS", fa=fa) for fa in range(20, 91, 5)]
    assert rates == sorted(rates, reverse=True)
    arms = [_chance(tuning, "3B", arm=arm) for arm in range(20, 91, 5)]
    assert arms == sorted(arms, reverse=True)
    spread = _chance(tuning, "SS", fa=34.0) / _chance(tuning, "SS", fa=66.0)
    assert 2.0 < spread < 2.5
    assert rating_factor(tuning) == 1.0


def rating_factor(tuning, **kwargs):
    return fielding.rating_error_factor(tuning=tuning, **kwargs)


def test_an_infielder_s_chance_in_the_air_is_a_quarter():
    tuning = _tuning(error_model=1.0)
    for pos in ("1B", "2B", "3B", "SS"):
        for out_type in ("lineout", "flyout"):
            assert _chance(tuning, pos, out_type=out_type) == pytest.approx(
                BASES[pos] * 0.25
            )
    # An outfielder's is his base whatever the ball.
    for out_type in ("lineout", "flyout", "groundout"):
        assert _chance(tuning, "CF", out_type=out_type) == pytest.approx(BASES["CF"])
    half = _tuning(error_model=1.0, error_infield_liner_scale=0.5)
    assert _chance(half, "SS", out_type="lineout") == pytest.approx(0.018)


def test_the_chance_is_kept_within_its_bounds_and_follows_the_slider():
    tuning = _tuning(error_model=1.0)
    assert _chance(tuning, "CF", fa=99.0, arm=99.0) == pytest.approx(
        max(0.0005, 0.0037 * math.exp(-0.025 * 49 - 0.02 * 49))
    )
    assert _chance(tuning, "CF", fa=5000.0) == 0.0005
    assert _chance(tuning, "3B", fa=-5000.0) == 0.15
    doubled = _tuning(error_model=1.0, error_rate_scale=2.0)
    assert _chance(doubled, "SS") == pytest.approx(0.072)
    # A position with no base of its own.
    assert _chance(tuning, "C") == pytest.approx(0.01)


def test_the_pitcher_makes_errors_only_under_model_2():
    assert _chance(_tuning(error_model=1.0), "P", fa=20.0) == 0.0
    two = _tuning(error_model=2.0)
    assert _chance(two, "P") == pytest.approx(0.045)
    assert _chance(two, "P", out_type="lineout") == pytest.approx(0.045 * 0.25)
    # Model 2 leaves the seven positions' rates as model 1 has them.
    one = _tuning(error_model=1.0)
    for pos in BASES:
        assert _chance(two, pos, fa=61.0, arm=44.0) == _chance(one, pos, fa=61.0, arm=44.0)


def test_the_old_formula_without_a_position_or_with_the_model_off():
    """No position (nobody could be found for the ball): the additive
    chance, as before, whatever the model."""
    for model in (0.0, 1.0, 2.0):
        tuning = _tuning(error_model=model)
        got = fielding.error_probability(
            out_type="groundout", infield_play=True, fielding=40.0, arm=50.0,
            tuning=tuning,
        )
        assert got == pytest.approx(0.018 + 10 / 500)


def test_the_roll_reads_the_fielder_as_he_plays_the_position():
    """Under the model the roll gets the fielder's rating at the position
    (the out-of-position table, the league's regulars there) and his arm
    against the regulars' there; a ball nobody is at reads an average."""
    centres = {key: 50.0 for key in fielding.FIELDER_FA_CENTER_KEYS.values()}
    centres.update({key: 50.0 for key in fielding.FIELDER_ARM_CENTER_KEYS.values()})
    centres.update(fielder_fa_center_3b=54.0, fielder_arm_center_3b=57.0,
                   fielder_fa_center_p=46.0)
    tuning = _tuning(
        error_model=2.0, fielder_centred_ratings=1.0, position_fit_model=1.0, **centres
    )
    third = BatterRatings(
        player_id="T", bats="R", primary_position="2B", other_positions=["3B"],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=60.0, arm=62.0, speed=50.0, eye=50.0,
        height=72.0, durability=50.0,
    )
    fa, arm = engine._error_roll_ratings(fielder=third, position="3B", tuning=tuning)
    assert fa == pytest.approx(60.0 - 1.0 - 4.0) and arm == pytest.approx(55.0)
    assert engine._error_roll_ratings(fielder=None, position="3B", tuning=tuning) == (
        50.0, 50.0
    )
    pitcher = PitcherRatings(
        player_id="P", bats="R", throws="R", role="SP", preferred_role="SP",
        velocity=97.0, control=50.0, movement=50.0, gb_tendency=50.0, vs_left=50.0,
        hold_runner=50.0, endurance=50.0, durability=50.0, fielding=40.0, arm=97.0,
        repertoire={"fb": 50.0},
    )
    # His fa against the league's pitchers; his arm (velocity) is not read.
    assert engine._error_roll_ratings(fielder=pitcher, position="P", tuning=tuning) == (
        44.0, 50.0
    )
    assert fielding.average_error_probability(
        out_type="groundout", infield_play=True, position="3B", tuning=tuning
    ) == pytest.approx(0.049)


# --- error_model 2: the extra rolls --------------------------------------------------


def test_the_extra_rates_are_zero_below_model_2():
    for model in (0.0, 1.0):
        tuning = _tuning(error_model=model)
        for key in EXTRA_RATES:
            assert fielding.extra_error_probability(key, tuning=tuning) == 0.0
    tuning = _tuning(error_model=2.0)
    assert fielding.extra_error_probability(
        "error_steal_throw_rate", tuning=tuning
    ) == pytest.approx(0.04)
    assert fielding.extra_error_probability(
        "error_of_hit_rate", fielding=60.0, tuning=tuning
    ) == pytest.approx(0.009 * math.exp(-0.25))
    assert fielding.extra_error_probability(
        "error_relay_throw_rate", arm=40.0, tuning=tuning
    ) == pytest.approx(0.03 * math.exp(0.2))
    assert fielding.extra_error_probability(
        "error_pickoff_throw_rate", fielding=-9000.0, tuning=tuning
    ) == 0.15


def _stored(extra):
    return kpis.with_rating_centers(extra, PLAYERS, CAL)


def test_model_1_draws_exactly_as_the_old_roll_does():
    """With every error chance at its floor (``error_rate_scale`` 0: .001
    before, .0005 under the model) a game in which no roll falls under
    either floor is the same game to the last bit -- one more or one fewer
    random number anywhere and it could not be."""
    same = 0
    for seed in range(1, 9):
        key = ("calibration", "CAL01", "CAL02", seed)
        old = _play(*key, _stored({"error_rate_scale": 0.0}))
        new = _play(*key, _stored({"error_rate_scale": 0.0, "error_model": 1.0}))
        if old.totals["roe"] or new.totals["roe"]:
            continue
        assert _digest(new) == _digest(old), seed
        same += 1
    assert same >= 5


def test_model_2_s_draws_happen_only_under_model_2(monkeypatch):
    asked = []
    real = engine.extra_error_probability

    def spy(rate_key, **kwargs):
        asked.append(rate_key)
        return real(rate_key, **kwargs)

    monkeypatch.setattr(engine, "extra_error_probability", spy)
    key = ("calibration", "CAL01", "CAL02", 3)
    zero = {rate: 0.0 for rate in EXTRA_RATES}
    quiet = {"error_rate_scale": 0.0, **zero}
    one = _play(*key, _stored({**quiet, "error_model": 1.0}))
    assert asked == []
    two = _play(*key, _stored({**quiet, "error_model": 2.0}))
    # Asked for on hits to the outfield, steals, failed pickoffs and force
    # plays -- and, with every rate at zero, never an error from them: what
    # moves the game is the draws themselves.
    assert set(asked) >= {"error_of_hit_rate", "error_relay_throw_rate"}
    assert all(row[1] in ("roe", "advance", "tag_up") for row in two.play_records["errors"])
    assert _digest(two) != _digest(one)


def test_the_new_errors_show_up_by_source_in_real_games():
    """A handful of games at raised rates: every source appears, charged to
    the position it belongs to, and the box score's errors are the totals."""
    overrides = _stored({
        "error_model": 2.0, "spray_direction_model": 1.0, "infield_band_model": 1.0,
        "error_steal_throw_rate": 0.6, "error_of_hit_rate": 0.1,
        "error_pickoff_throw_rate": 0.9, "error_relay_throw_rate": 0.5,
        "error_base_p": 0.5, "pickoff_freq_scale": 8.0,
    })
    where = {}
    for seed in range(1, 13):
        game = _play("calibration", "CAL05", "CAL06", seed, overrides)
        box = serialize_game_result(game)["boxscore"]
        charged = sum(line["e"] for side in box.values() for line in side["fielding"])
        assert charged == game.totals["e"] == len(game.play_records["errors"])
        assert game.totals["e_throw"] + game.totals["e_field"] == game.totals["e"]
        starting = game.play_records["starting_positions"]
        for _index, source, pos, pid, side in game.play_records["errors"]:
            where.setdefault(source, set()).add(pos)
            if pos == "P":
                arms = {l["player_id"] for l in game.metadata["pitcher_lines"][side]}
                assert pid in arms
            elif pid in starting[side]:
                assert starting[side][pid] == pos
    assert where["steal"] == {"C"}
    assert where["pickoff"] == {"P"}
    assert where["of_hit"] <= {"LF", "CF", "RF"} and len(where["of_hit"]) >= 2
    assert where["relay"] <= {"2B", "SS"}
    assert "P" in where["roe"]


# --- scripted innings: the box score -------------------------------------------------


def _pitch(outcome, *, ev=None, la=None, spray=None) -> PitchResult:
    in_play = outcome == "in_play"
    return PitchResult(
        pitch_type="fb", pitch_quality=50.0, velocity=92.0, location=(0.0, 2.5),
        in_zone=outcome != "ball", swing=in_play, contact=in_play, foul=False,
        in_play=in_play, outcome=outcome, called_in_zone=outcome != "ball",
        exit_velo=ev, launch_angle=la, spray_angle=spray,
    )


# What a step of a script throws: a liner to right for a hit, a ground ball
# to short, one back to the mound, a home run.
BALLS = {
    "single": dict(ev=95.0, la=12.0, spray=25.0),
    "grounder": dict(ev=85.0, la=-5.0, spray=-8.0),
    "comebacker": dict(ev=85.0, la=-5.0, spray=0.0),
    "homer": dict(ev=112.0, la=28.0, spray=0.0),
}


def _scripted_game(monkeypatch, plan, *, seed, extra=None, half=(1, "away"),
                   ground_out=None):
    """A calibration game whose top of the first (or the ``half`` given:
    inning, batting side) follows ``plan`` pitch by pitch; every other
    pitch of the game is a called strike. ``ground_out`` replaces the
    scripted force play at second.

    A step is a dict: ``pitch`` ("ball", "strike" or a key of ``BALLS``),
    and optionally ``pickoff`` (the event a pickoff attempt after the pitch
    returns), ``steal`` (the runner on first takes second on the pitch),
    ``out`` (the out chance of the ball: 1.0 an out, 0.0 a hit), ``roe``
    (the error chance if it is an out) and ``forced`` (the ``error_model``
    2 rates whose roll comes up an error on this pitch). The hit and error
    rolls themselves are the engine's (a hit is 95% at best), so the
    caller checks the inning went as scripted.
    """
    steps = list(plan)
    state = {"step": {}}

    def fake_pitch(**_kwargs):
        frame = sys._getframe(1).f_locals
        scripted = (frame["inning"], frame["batting_team"]) == half and steps
        state["step"] = steps.pop(0) if scripted else {"pitch": "strike"}
        kind = state["step"]["pitch"]
        if kind in BALLS:
            return _pitch("in_play", **BALLS[kind])
        return _pitch(kind)

    def fake_out_probability(**_kwargs):
        return 2.0 if state["step"].get("out", 1.0) >= 0.5 else -1.0

    def fake_error_probability(**_kwargs):
        return state["step"].get("roe", 0.0)

    def fake_extra(rate_key, **_kwargs):
        return 1.0 if rate_key in state["step"].get("forced", ()) else 0.0

    def fake_pickoff(**_kwargs):
        event = state["step"].get("pickoff")
        return (event, 0, True) if event else (None, 0, False)

    def fake_steal(*, bases, **_kwargs):
        if state["step"].get("steal") and bases.first and not bases.second:
            runner = bases.first
            bases.second, bases.first = runner, None
            return [(runner, "sb2")], 0, 0, []
        return [], 0, 0, []

    def fake_ground_out(*, bases, batter, **_kwargs):
        # The force at second: lead runner out, the batter safe at first.
        bases.first = batter
        return 0, 1, ["fc"], []

    for name, fake in (
        ("simulate_pitch", fake_pitch),
        ("out_probability", fake_out_probability),
        ("error_probability", fake_error_probability),
        ("extra_error_probability", fake_extra),
        ("_attempt_pickoff", fake_pickoff),
        ("_attempt_steal", fake_steal),
        ("_resolve_ground_out", ground_out or fake_ground_out),
        ("_attempt_extra_base", lambda **_k: "hold"),
        ("_missed_pitch_type", lambda **_k: None),
        ("_should_bunt", lambda **_k: False),
        ("_should_intentional_walk", lambda **_k: False),
        ("_select_pinch_hitter", lambda **_k: None),
        ("_maybe_pinch_run", lambda **_k: None),
        ("_maybe_defensive_sub", lambda **_k: None),
        ("_maybe_injure_player", lambda **_k: None),
        (
            "_resolve_dropped_third_strike",
            lambda **_k: (False, 1, 0, None, [], False),
        ),
    ):
        monkeypatch.setattr(engine, name, fake)
    overrides = _stored({
        "error_model": 2.0, "spray_direction_model": 1.0, "balk_rate": 0.0,
        **(extra or {}),
    })
    game = engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=PLAYERS, base_dir=CAL,
        seed=seed, tuning_overrides=overrides,
    )
    assert not steps, "the script was not played out"
    return game


def _first_inning(game):
    """The plate appearances of the top of the first, as result tokens."""
    tokens = []
    for entry in game.pitch_log:
        if entry.get("inning", 1) != 1 and "inning" in entry:
            break
        if entry.get("pa_result"):
            tokens.append(entry["pa_result"])
    return tokens


def _play_script(monkeypatch, plan, expected, **kwargs):
    """The first seed on which the scripted inning went as ``expected``
    (the result of each plate appearance, the three strikeouts aside)."""
    for seed in range(1, 25):
        with monkeypatch.context() as patch:
            game = _scripted_game(patch, plan, seed=seed, **kwargs)
        tokens = _first_inning(game)
        if tokens[: len(expected)] == expected:
            return game
    raise AssertionError(f"no seed played {expected}")


def _lines(game, kind, side):
    return {line["player_id"]: line for line in game.metadata[kind][side]}


def _fielder(game, position, side="home"):
    starting = game.play_records["starting_positions"][side]
    return next(pid for pid, pos in starting.items() if pos == position)


def _assert_box_score(game, charged):
    """The errors are charged to ``charged`` ({player id: errors}) and to
    nobody else, in the fielding lines and in the box score."""
    box = serialize_game_result(game)["boxscore"]
    for source in (game.metadata["fielding_lines"]["home"], box["home"]["fielding"]):
        got = {line["player_id"]: line["e"] for line in source if line["e"]}
        assert got == charged
    assert not any(line["e"] for line in box["away"]["fielding"])
    assert game.totals["e"] == sum(charged.values()) == len(game.play_records["errors"])
    assert game.totals["e_throw"] + game.totals["e_field"] == game.totals["e"]


def _error_entries(game, source):
    rows = [row for row in game.play_records["errors"] if row[1] == source]
    return [(row, game.pitch_log[row[0]]) for row in rows]


def test_an_outfielder_s_error_on_a_hit(monkeypatch):
    """Single; the runner steals second; a single to right on which he
    stops at third -- and the right fielder lets it through. He scores and
    the batter takes second: one error on the right fielder, a hit and no
    run batted in for the batter, an unearned run for the pitcher."""
    plan = [
        {"pitch": "single", "out": 0.0},
        {"pitch": "strike", "steal": True},
        {"pitch": "single", "out": 0.0, "forced": {"error_of_hit_rate"}},
    ]
    game = _play_script(monkeypatch, plan, ["1b", "1b", "so", "so", "so"])
    right = _fielder(game, "RF")
    _assert_box_score(game, {right: 1})
    assert (game.totals["e_field"], game.totals["e_throw"]) == (1, 0)
    assert game.totals["roe"] == 0 and game.totals["h"] == 2
    (row, entry), = _error_entries(game, "of_hit")
    assert row[2:] == ("RF", right, "home")
    assert entry["error_type"] == "fielding" and entry["error_on"] == "of_hit"
    assert entry["runner_event"] == "e_of"
    first, second = game.metadata["batting_lines"]["away"][:2]
    assert sorted(entry["error_runners"]) == sorted(
        [first["player_id"], second["player_id"]]
    )
    # The hit's own advance is what the log's runner row shows: to third.
    assert entry["hit_adv"] == [[first["player_id"], 2, 3, 0]]
    assert (first["r"], first["sb"], first["h"]) == (1, 1, 1)
    assert (second["h"], second["b1"], second["rbi"], second["roe"]) == (1, 1, 0, 0)
    pitcher = game.metadata["pitcher_lines"]["home"][0]
    assert (pitcher["runs"], pitcher["earned_runs"]) == (1, 0)
    assert game.metadata["score"] == {"away": 1, "home": 0}


def test_a_catcher_s_throw_on_a_stolen_base(monkeypatch):
    """Walk; he steals second and the throw goes into centre field: third
    base on the catcher's error. A single scores him -- a run batted in,
    but not an earned run: without the error he stands on second."""
    plan = (
        [{"pitch": "ball"}] * 4
        + [{"pitch": "strike", "steal": True, "forced": {"error_steal_throw_rate"}}]
        + [{"pitch": "single", "out": 0.0}]
    )
    game = _play_script(monkeypatch, plan, ["bb", "1b", "so", "so", "so"])
    catcher = _fielder(game, "C")
    _assert_box_score(game, {catcher: 1})
    assert (game.totals["e_field"], game.totals["e_throw"]) == (0, 1)
    (row, entry), = _error_entries(game, "steal")
    assert row[2:] == ("C", catcher, "home")
    assert entry["runner_event"] == "sb2+e2"
    assert entry["error_type"] == "throwing" and entry["error_on"] == "steal"
    first, second = game.metadata["batting_lines"]["away"][:2]
    assert entry["error_runners"] == [first["player_id"]]
    assert (first["sb"], first["cs"], first["r"]) == (1, 0, 1)
    assert (second["rbi"], second["h"]) == (1, 1)
    behind = _lines(game, "fielding_lines", "home")[catcher]
    assert (behind["sba"], behind["cs"], behind["e"]) == (1, 0, 1)
    pitcher = game.metadata["pitcher_lines"]["home"][0]
    assert (pitcher["runs"], pitcher["earned_runs"]) == (1, 0)
    assert game.totals["sb"] == 1 and game.totals["roe"] == 0


def test_a_pickoff_throw_that_gets_away(monkeypatch):
    """Single; three pickoff throws get away, one at each base: the runner
    walks home on the pitcher's three errors. No hit, no run batted in, no
    earned run."""
    plan = [{"pitch": "single", "out": 0.0}] + [
        {"pitch": "ball", "pickoff": event, "forced": {"error_pickoff_throw_rate"}}
        for event in ("poa1", "poa2", "poa3")
    ]
    game = _play_script(monkeypatch, plan, ["1b", "so", "so", "so"])
    pitcher = game.metadata["pitcher_lines"]["home"][0]
    _assert_box_score(game, {pitcher["player_id"]: 3})
    assert (game.totals["e_field"], game.totals["e_throw"]) == (0, 3)
    rows = _error_entries(game, "pickoff")
    assert [entry["runner_event"] for _row, entry in rows] == [
        "poa1+e1", "poa2+e1", "poa3+e1"
    ]
    for row, entry in rows:
        assert row[2:] == ("P", pitcher["player_id"], "home")
        assert entry["error_type"] == "throwing" and entry["error_on"] == "pickoff"
    first, second = game.metadata["batting_lines"]["away"][:2]
    assert (first["r"], first["h"]) == (1, 1)
    # The man at the plate struck out (as he does all game): nothing for him.
    assert (second["rbi"], second["h"], second["bb"]) == (0, 0, 0)
    assert (pitcher["runs"], pitcher["earned_runs"]) == (1, 0)
    assert pitcher.get("pk", 0) == 0
    assert game.totals["po"] == 0  # nobody was picked off
    assert game.metadata["score"]["away"] == 1


def test_a_relay_that_gets_away_on_a_force_play(monkeypatch):
    """Walk; a ground ball to short, the force at second -- and the second
    baseman's relay to first gets away: the batter is on second by a
    fielder's choice and an error, not a reach on error."""
    plan = [{"pitch": "ball"}] * 4 + [
        {"pitch": "grounder", "out": 1.0, "forced": {"error_relay_throw_rate"}}
    ]
    game = _play_script(monkeypatch, plan, ["bb", "out", "so", "so"])
    second_base, short = _fielder(game, "2B"), _fielder(game, "SS")
    _assert_box_score(game, {second_base: 1})
    assert (game.totals["e_field"], game.totals["e_throw"]) == (0, 1)
    (row, entry), = _error_entries(game, "relay")
    assert row[2:] == ("2B", second_base, "home")
    assert entry["runner_event"] == "fc+e_rel"
    assert entry["error_type"] == "throwing" and entry["error_on"] == "relay"
    lines = _lines(game, "fielding_lines", "home")
    assert (lines[short]["a"], lines[second_base]["po"]) == (1, 1)
    batter = game.metadata["batting_lines"]["away"][1]
    assert entry["error_runners"] == [batter["player_id"]]
    # (He strikes out the rest of the game; these are from this at-bat.)
    assert (batter["fc"], batter["roe"], batter["h"], batter["r"]) == (1, 0, 0, 0)
    assert game.totals["fc"] == 1 and game.totals["roe"] == 0
    assert game.play_records["fld_pos"][row[0]] == "SS"


def test_a_pitcher_s_error_on_a_comebacker(monkeypatch):
    """A ground ball back to the mound that the pitcher boots, then a home
    run: the batter reached on the pitcher's error, his run is unearned,
    the home run's is earned."""
    plan = [
        {"pitch": "comebacker", "out": 1.0, "roe": 1.0},
        {"pitch": "homer"},
    ]
    game = _play_script(
        monkeypatch, plan, ["roe", "hr", "so", "so", "so"],
        extra={"infield_band_model": 1.0},
    )
    pitcher = game.metadata["pitcher_lines"]["home"][0]
    _assert_box_score(game, {pitcher["player_id"]: 1})
    (row, entry), = _error_entries(game, "roe")
    assert row[2:] == ("P", pitcher["player_id"], "home")
    assert entry["reached_on_error"] is True
    assert game.play_records["fld_pos"][row[0]] == "P"
    first, second = game.metadata["batting_lines"]["away"][:2]
    assert (first["roe"], first["h"], first["r"]) == (1, 0, 1)
    assert (second["hr"], second["rbi"], second["r"]) == (1, 2, 1)
    assert game.totals["roe"] == 1
    assert (pitcher["runs"], pitcher["earned_runs"]) == (2, 1)
    # Under model 1 the same ball is the pitcher's and he cannot boot it.
    assert _chance(_tuning(error_model=1.0), "P") == 0.0
