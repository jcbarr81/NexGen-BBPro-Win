"""Release 3 rules (audit L15, M8, L17; decision 11 extra innings).

- L15: no run scores on a double play that ends the inning.
- M8: a runner advancing from 1st never overwrites the runner on 2nd.
- Decision 11: the automatic runner on 2nd from the 10th, regular season only;
  past the safety guard every game gets one; only the hard stop ties.
- The postseason flag reaches the engine; the league can turn the runner off.
"""

from __future__ import annotations

import functools
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as engine
from physics_sim.config import load_tuning
from physics_sim.engine import BaseState, _resolve_ground_out
from physics_sim.fielding import compute_defense_ratings
from physics_sim.models import BatterRatings

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"


def _batter(pid: str, pos: str = "CF", speed: float = 50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position=pos, other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=speed, eye=50.0,
        height=72.0, durability=50.0,
    )


def _defense():
    defense = {pos: _batter(f"F{pos}", pos) for pos in ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")}
    return defense


class _Script:
    """Stands in for the ``random`` module: draws come from a fixed list."""

    def __init__(self, draws):
        self._draws = list(draws)

    def random(self):
        assert self._draws, "the play drew more numbers than scripted"
        return self._draws.pop(0)


def _ground_out(monkeypatch, bases: BaseState, outs: int, draws):
    monkeypatch.setattr(engine, "random", _Script(draws))
    tuning = load_tuning()
    defense = _defense()
    return _resolve_ground_out(
        bases=bases,
        outs=outs,
        batter=_batter("BAT"),
        defense_map=defense,
        defense_ratings=compute_defense_ratings(defense, tuning),
        spray_angle=0.0,
        batter_side="R",
        tuning=tuning,
    )


# --- L15 ----------------------------------------------------------------------


def test_inning_ending_double_play_scores_nobody(monkeypatch):
    r1, r3 = _batter("R1"), _batter("R3")
    bases = BaseState(first=r1, third=r3)
    # Draws: R3 would score (0.0), double play (0.0).
    runs, outs_added, events, scored = _ground_out(monkeypatch, bases, 1, [0.0, 0.0])
    assert events == ["dp"]
    assert outs_added == 2
    assert runs == 0 and scored == []


def test_double_play_with_nobody_out_still_scores_the_runner(monkeypatch):
    r1, r3 = _batter("R1"), _batter("R3")
    bases = BaseState(first=r1, third=r3)
    runs, outs_added, events, scored = _ground_out(monkeypatch, bases, 0, [0.0, 0.0])
    assert events == ["dp"]
    assert outs_added == 2
    assert runs == 1 and [r.player_id for r in scored] == ["R3"]
    assert bases.third is None


def test_ground_ball_rbi_without_a_double_play_counts(monkeypatch):
    r1, r3 = _batter("R1"), _batter("R3")
    bases = BaseState(first=r1, third=r3)
    # R3 scores, no double play (0.99), fielder's choice at 2nd (0.0).
    runs, outs_added, events, _ = _ground_out(monkeypatch, bases, 1, [0.0, 0.99, 0.0])
    assert (runs, outs_added, events) == (1, 1, ["fc"])
    assert bases.first.player_id == "BAT"


def test_draw_sequence_is_unchanged(monkeypatch):
    """The fix keeps the RNG stream: same draws, in the same order."""
    bases = BaseState(first=_batter("R1"), third=_batter("R3"))
    script = _Script([0.99, 0.99, 0.99, 0.99])
    monkeypatch.setattr(engine, "random", script)
    tuning = load_tuning()
    defense = _defense()
    _resolve_ground_out(
        bases=bases, outs=0, batter=_batter("BAT"), defense_map=defense,
        defense_ratings=compute_defense_ratings(defense, tuning),
        spray_angle=0.0, batter_side="R", tuning=tuning,
    )
    # rbi, dp, force, advance
    assert script._draws == []


# --- M8 -----------------------------------------------------------------------


def test_runner_on_second_moves_up_instead_of_being_overwritten(monkeypatch):
    r1, r2 = _batter("R1"), _batter("R2")
    bases = BaseState(first=r1, second=r2)
    # No triple play, no double play, no force, R1 advances.
    runs, outs_added, events, _ = _ground_out(monkeypatch, bases, 1, [0.99, 0.99, 0.99, 0.0])
    assert (runs, outs_added, events) == (0, 1, [])
    assert bases.first is None
    assert bases.second.player_id == "R1"
    assert bases.third.player_id == "R2"


def test_bases_loaded_runner_on_first_holds(monkeypatch):
    r1, r2, r3 = _batter("R1"), _batter("R2"), _batter("R3")
    bases = BaseState(first=r1, second=r2, third=r3)
    # No triple play, R3 stays, no double play, no force, R1 tries to advance.
    _ground_out(monkeypatch, bases, 0, [0.99, 0.99, 0.99, 0.99, 0.0])
    assert [bases.first.player_id, bases.second.player_id, bases.third.player_id] == [
        "R1", "R2", "R3",
    ]


def test_ground_outs_conserve_runners():
    """20,000 random base-out states: every runner is still on base, scored or out."""
    tuning = load_tuning()
    defense = _defense()
    ratings = compute_defense_ratings(defense, tuning)
    rng = random.Random(20261007)
    for i in range(20000):
        outs = rng.randrange(3)
        bases = BaseState(
            first=_batter(f"A{i}", speed=rng.uniform(20, 80)) if rng.random() < 0.6 else None,
            second=_batter(f"B{i}", speed=rng.uniform(20, 80)) if rng.random() < 0.5 else None,
            third=_batter(f"C{i}", speed=rng.uniform(20, 80)) if rng.random() < 0.4 else None,
        )
        before = {r.player_id for r in (bases.first, bases.second, bases.third) if r}
        batter = _batter(f"BAT{i}")
        runs, outs_added, events, scored = _resolve_ground_out(
            bases=bases, outs=outs, batter=batter, defense_map=defense,
            defense_ratings=ratings, spray_angle=rng.uniform(-45, 45),
            batter_side=rng.choice("LR"), tuning=tuning,
        )
        after = [r.player_id for r in (bases.first, bases.second, bases.third) if r]
        assert len(after) == len(set(after)), events
        assert runs == len(scored)
        assert len(before) + 1 == len(after) + runs + outs_added, (events, outs)
        if "dp" in events and outs == 1:
            assert runs == 0


# --- extra innings (engine) ---------------------------------------------------


def _play(seed, *, postseason=False, overrides=None):
    return engine.simulate_matchup_from_files(
        away_team="CAL01",
        home_team="CAL02",
        base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv",
        seed=seed,
        tuning_overrides=dict(overrides) if overrides else None,
        postseason=postseason,
    )


@functools.lru_cache(maxsize=None)
def _extra_inning_seeds(postseason: bool) -> tuple[int, ...]:
    """Seeds whose game between two calibration clubs went past the 9th.

    The extra-inning knobs are not read before the 10th, so the same seeds go
    to extras under any of them (postseason games differ from the 1st on).
    """
    seeds = tuple(s for s in range(1, 61) if _play(s, postseason=postseason).metadata["innings"] > 9)
    assert seeds, "no extra-inning game in the sample"
    return seeds


@functools.lru_cache(maxsize=None)
def _games(postseason: bool = False, overrides: tuple = ()):
    games = [
        _play(seed, postseason=postseason, overrides=overrides)
        for seed in _extra_inning_seeds(postseason)
    ]
    assert all(g.metadata["innings"] > 9 for g in games)
    return games


def _calibration_games(*, postseason=False, overrides=None):
    """Extra-inning games between two calibration clubs."""
    return _games(postseason, tuple(sorted((overrides or {}).items())))


def _extra_half_starts(result):
    """First PA of every extra half: (inning, half, bases mask, pitcher id)."""
    starts = []
    seen = set()
    for entry in result.pitch_log:
        if not entry.get("pa_start"):
            continue
        key = (entry["inning"], entry["half"])
        if key in seen or entry["inning"] < 10:
            continue
        seen.add(key)
        starts.append((entry["inning"], entry["half"], entry["bases_before"], entry["pitcher_id"]))
    return starts


def _check_innings(result):
    meta = result.metadata
    played = max(len(meta["inning_runs"]["away"]), len(meta["inning_runs"]["home"]))
    assert meta["innings"] == played
    assert meta["ended_in_tie"] is False
    assert meta["score"]["away"] != meta["score"]["home"]


def test_regular_season_extra_halves_start_with_a_runner_on_second():
    for result in _calibration_games():
        _check_innings(result)
        starts = _extra_half_starts(result)
        assert starts
        assert all(mask == 2 for _, _, mask, _ in starts), starts


def test_postseason_extra_halves_start_with_the_bases_empty():
    for result in _calibration_games(postseason=True):
        _check_innings(result)
        starts = _extra_half_starts(result)
        assert all(mask == 0 for _, _, mask, _ in starts), starts


def test_league_opt_out_turns_the_runner_off():
    for result in _calibration_games(overrides={"extra_innings_runner": 0.0}):
        assert all(mask == 0 for _, _, mask, _ in _extra_half_starts(result))


def test_past_the_guard_every_game_gets_the_runner():
    # Guard at 9: from the 10th on, even a postseason game gets the runner.
    for result in _calibration_games(postseason=True, overrides={"max_innings": 9.0}):
        _check_innings(result)
        assert all(mask == 2 for _, _, mask, _ in _extra_half_starts(result))


def test_hard_stop_is_the_only_tie_and_innings_are_counted_once():
    ties = 0
    for result in _calibration_games(
        overrides={"extra_innings_runner": 0.0, "max_innings": 10.0, "max_innings_hard_stop": 10.0},
    ):
        meta = result.metadata
        played = max(len(meta["inning_runs"]["away"]), len(meta["inning_runs"]["home"]))
        assert meta["innings"] == played <= 10
        if meta["ended_in_tie"]:
            ties += 1
            assert played == 10
            assert meta["score"]["away"] == meta["score"]["home"]
    assert ties


def test_pitcher_entering_an_extra_half_inherits_no_automatic_runner():
    checked = 0
    for result in _calibration_games():
        lines = {
            line["player_id"]: line
            for side in ("away", "home")
            for line in result.metadata["pitcher_lines"][side]
        }
        previous_pitcher = {}
        for entry in result.pitch_log:
            if not entry.get("pa_start"):
                continue
            half = entry["half"]
            pid = entry["pitcher_id"]
            first_pa_of_half = previous_pitcher.get(half, (None, None))[1] != entry["inning"]
            if (
                first_pa_of_half
                and entry["inning"] >= 10
                and previous_pitcher.get(half, (None, None))[0] not in (None, pid)
            ):
                # A new pitcher started this extra half: the only runner on
                # base was the automatic runner, who is not his.
                assert lines[pid]["ir"] == 0, (entry["inning"], half, pid)
                checked += 1
            previous_pitcher[half] = (pid, entry["inning"])
    assert checked


# --- league setting and plumbing ------------------------------------------------


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    from utils import league_settings as ls

    path = tmp_path / "league_settings.json"
    monkeypatch.setattr(ls, "_settings_path", lambda p=None: path)
    return path


def test_runner_setting_defaults_on_and_round_trips(settings_file):
    from utils import league_settings as ls

    assert ls.extra_innings_runner_enabled() is True
    assert ls.extra_innings_runner_enabled({}) is True
    ls.set_extra_innings_runner(False)
    assert ls.extra_innings_runner_enabled() is False
    ls.set_extra_innings_runner(True)
    assert ls.extra_innings_runner_enabled() is True


class _Captured(Exception):
    pass


def _capture_physics_call(monkeypatch, *, runner_on: bool, stored_overrides: dict):
    import playbalance.game_runner as gr
    import physics_sim.data_loader as loader
    from utils import league_settings as ls

    batters = {f"B{i}": SimpleNamespace(player_id=f"B{i}") for i in range(18)}
    arms = {f"P{i}": SimpleNamespace(player_id=f"P{i}") for i in range(2)}
    monkeypatch.setattr(loader, "load_players_by_id", lambda path: (batters, arms))
    monkeypatch.setattr(gr, "get_physics_tuning_overrides", lambda: dict(stored_overrides))
    monkeypatch.setattr(gr, "get_injury_tuning_overrides", lambda: {})
    monkeypatch.setattr(ls, "load_league_settings", lambda path=None: {"extra_innings_runner": runner_on})
    seen = {}

    def fake_simulate_game(**kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(engine, "simulate_game", fake_simulate_game)

    def state(offset):
        return SimpleNamespace(
            lineup=[SimpleNamespace(player_id=f"B{i + offset}", position="CF") for i in range(9)],
            bench=[],
            pitchers=[SimpleNamespace(player_id=f"P{offset // 9}", assigned_pitching_role="SP1")],
            team=None,
        )

    return gr, state, seen


@pytest.mark.parametrize("runner_on", [True, False])
def test_league_runner_setting_is_written_last(monkeypatch, runner_on):
    gr, state, seen = _capture_physics_call(
        monkeypatch, runner_on=runner_on, stored_overrides={"extra_innings_runner": 1.0, "hr_scale": 1.0},
    )
    with pytest.raises(_Captured):
        gr._run_physics_game(
            home_id="H", away_id="A", home_state=state(0), away_state=state(9),
            players_file=str(CALIBRATION / "players.csv"), roster_dir="rosters",
            seed=1, date_token=None, tracker=None, players_lookup={},
            persist_stats=False, postseason=True,
        )
    assert seen["tuning_overrides"]["extra_innings_runner"] == (1.0 if runner_on else 0.0)
    assert seen["tuning_overrides"]["hr_scale"] == 1.0
    assert seen["postseason"] is True


def test_simulate_game_scores_passes_the_postseason_flag(monkeypatch):
    import playbalance.game_runner as gr

    seen = {}

    def fake_run_single_game(home_id, away_id, **kwargs):
        seen.update(kwargs)
        team = SimpleNamespace(runs=0)
        return team, team, {}, "", {}

    monkeypatch.setattr(gr, "run_single_game", fake_run_single_game)
    gr.simulate_game_scores("H", "A", seed=1, postseason=True)
    assert seen["postseason"] is True
    gr.simulate_game_scores("H", "A", seed=1)
    assert seen["postseason"] is False
