"""M9 (2026-10-06 audit): fielding credit bookkeeping.

Strikeouts no longer give the pitcher an assist, bunt outs are credited by
bunt direction instead of always to the SS, and the double-play pivot man gets
his assist. These are fielding-credit-only changes: game outcomes are
untouched.
"""
from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pytest

from physics_sim.engine import (
    LineupState,
    _BUNT_FIELDER_WEIGHTS_1B_SIDE,
    _BUNT_FIELDER_WEIGHTS_3B_SIDE,
    _bunt_fielder_position,
    _credit_bunt_out,
    _credit_ground_double_play,
    simulate_matchup_from_files,
)
from physics_sim.models import BatterRatings

CAL = Path("data/calibration")


def _fielder(pid: str, pos: str) -> BatterRatings:
    return BatterRatings(
        player_id=pid,
        bats="R",
        primary_position=pos,
        other_positions=[],
        contact=50.0,
        power=50.0,
        gb_tendency=50.0,
        pull_tendency=50.0,
        vs_left=50.0,
        fielding=50.0,
        arm=50.0,
        speed=50.0,
        eye=50.0,
        height=72.0,
        durability=50.0,
    )


def _defense() -> tuple[LineupState, dict[str, BatterRatings]]:
    positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    defense_map = {pos: _fielder(pos.lower(), pos) for pos in positions}
    state = LineupState(lineup=list(defense_map.values()), positions={})
    return state, defense_map


def _credit(state: LineupState, pid: str) -> tuple[int, int, int]:
    line = state.fielding_lines.get(pid)
    if line is None:
        return (0, 0, 0)
    return (line.po, line.a, line.dp)


def _sim(seed: int, **overrides):
    return simulate_matchup_from_files(
        away_team="CAL02",
        home_team="CAL01",
        players_path=CAL / "players.csv",
        base_dir=CAL,
        seed=seed,
        tuning_overrides=overrides or None,
    )


# --- double-play pivot ------------------------------------------------------


def test_six_four_three_gives_the_pivot_an_assist():
    state, defense_map = _defense()
    _credit_ground_double_play(
        defense_state=state,
        defense_map=defense_map,
        primary_pos="SS",
        primary_fielder=defense_map["SS"],
        oneb_fielder=defense_map["1B"],
    )
    # (po, a, dp)
    assert _credit(state, "ss") == (0, 1, 1)
    assert _credit(state, "2b") == (1, 1, 1)
    assert _credit(state, "1b") == (1, 0, 1)


def test_three_six_three_credits_first_baseman_once():
    state, defense_map = _defense()
    _credit_ground_double_play(
        defense_state=state,
        defense_map=defense_map,
        primary_pos="1B",
        primary_fielder=defense_map["1B"],
        oneb_fielder=defense_map["1B"],
    )
    # 1B throws to second (A), takes the relay (PO): one DP, not 2 PO + 2 DP.
    assert _credit(state, "1b") == (1, 1, 1)
    assert _credit(state, "ss") == (1, 1, 1)
    total_po = sum(line.po for line in state.fielding_lines.values())
    assert total_po == 2


# --- bunt direction ---------------------------------------------------------


def test_bunt_fielder_position_is_stable_and_leaves_game_rng_alone():
    random.seed(123)
    before = random.getstate()
    picks = [
        _bunt_fielder_position(runner_on_second=False, key=f"7|3|{i}|P1")
        for i in range(50)
    ]
    assert random.getstate() == before
    again = [
        _bunt_fielder_position(runner_on_second=False, key=f"7|3|{i}|P1")
        for i in range(50)
    ]
    assert picks == again


@pytest.mark.parametrize(
    "runner_on_second, weights",
    [(False, _BUNT_FIELDER_WEIGHTS_1B_SIDE), (True, _BUNT_FIELDER_WEIGHTS_3B_SIDE)],
)
def test_bunt_fielders_follow_the_direction_weights(runner_on_second, weights):
    n = 8000
    counts = Counter(
        _bunt_fielder_position(runner_on_second=runner_on_second, key=f"s|{i}|b")
        for i in range(n)
    )
    assert set(counts) == {"P", "C", "1B", "3B"}  # never the SS/2B
    for pos, weight in weights:
        assert counts[pos] / n == pytest.approx(weight, abs=0.025)


def test_runner_on_second_pushes_bunts_toward_third():
    n = 4000
    to_3b_with_r2 = sum(
        _bunt_fielder_position(runner_on_second=True, key=f"k{i}") == "3B"
        for i in range(n)
    )
    to_3b_r1_only = sum(
        _bunt_fielder_position(runner_on_second=False, key=f"k{i}") == "3B"
        for i in range(n)
    )
    assert to_3b_with_r2 > to_3b_r1_only * 1.4


@pytest.mark.parametrize("pos", ["C", "3B"])
def test_bunt_out_fielded_in_front_is_assist_plus_first_base_putout(pos):
    state, defense_map = _defense()
    _credit_bunt_out(
        defense_state=state,
        defense_map=defense_map,
        bunt_pos=pos,
        pitcher_id="pit",
        double_play=False,
    )
    assert _credit(state, pos.lower()) == (0, 1, 0)
    assert _credit(state, "1b") == (1, 0, 0)
    assert _credit(state, "ss") == (0, 0, 0)


def test_bunt_out_fielded_by_pitcher_credits_the_pitcher():
    state, defense_map = _defense()
    _credit_bunt_out(
        defense_state=state,
        defense_map=defense_map,
        bunt_pos="P",
        pitcher_id="pit",
        double_play=False,
    )
    assert _credit(state, "pit") == (0, 1, 0)
    assert _credit(state, "1b") == (1, 0, 0)


def test_bunt_out_fielded_by_first_baseman_goes_3_4():
    """The 1B charged it, so the 2B covers first: 1B assist, 2B putout."""
    state, defense_map = _defense()
    _credit_bunt_out(
        defense_state=state,
        defense_map=defense_map,
        bunt_pos="1B",
        pitcher_id="pit",
        double_play=False,
    )
    assert _credit(state, "1b") == (0, 1, 0)
    assert _credit(state, "2b") == (1, 0, 0)


def test_bunt_double_play_credits_pivot_and_cover():
    state, defense_map = _defense()
    _credit_bunt_out(
        defense_state=state,
        defense_map=defense_map,
        bunt_pos="1B",
        pitcher_id="pit",
        double_play=True,
    )
    # 3-6-4: 1B fields, SS covers second and relays, 2B covers first.
    assert _credit(state, "1b") == (0, 1, 1)
    assert _credit(state, "ss") == (1, 1, 1)
    assert _credit(state, "2b") == (1, 0, 1)


# --- whole games ------------------------------------------------------------


def _pitcher_ids(result) -> set[str]:
    lines = result.metadata["pitcher_lines"]
    return {str(p["player_id"]) for side in lines.values() for p in side}


def _fielding_lines(result) -> list[dict]:
    return [line for side in result.metadata["fielding_lines"].values() for line in side]


@pytest.mark.parametrize("seed", [4, 26])
def test_strikeouts_give_the_pitcher_no_assist(seed):
    result = _sim(seed)
    pitchers = _pitcher_ids(result)
    pitcher_assists = sum(
        line["a"] for line in _fielding_lines(result) if line["player_id"] in pitchers
    )
    bunts = sum(1 for entry in result.pitch_log if entry.get("outcome") == "bunt")
    assert result.totals["k"] > 0
    # Pitchers only collect assists on the bunts they field now.
    assert pitcher_assists <= bunts


@pytest.mark.parametrize("seed", [4, 26, 33])
def test_putouts_equal_outs_recorded(seed):
    # Seeds with a 3-6-3 double play, which used to give the 1B a second putout.
    result = _sim(seed)
    putouts = sum(line["po"] for line in _fielding_lines(result))
    outs = sum(
        p["outs"] for side in result.metadata["pitcher_lines"].values() for p in side
    )
    assert putouts == outs


def test_bunt_heavy_game_credits_bunts_and_balances_putouts():
    result = _sim(
        11,
        bunt_attempt_rate=0.5,
        bunt_hit_base=-1.0,
        bunt_close_run_diff=99.0,
        bunt_inning_max=99.0,
    )
    bunt_outs = [
        e
        for e in result.pitch_log
        if e.get("outcome") == "bunt"
        and any(ev in str(e.get("runner_event", "")) for ev in ("sac", "bunt_out"))
    ]
    assert len(bunt_outs) >= 8
    putouts = sum(line["po"] for line in _fielding_lines(result))
    outs = sum(
        p["outs"] for side in result.metadata["pitcher_lines"].values() for p in side
    )
    assert putouts == outs
    pitchers = _pitcher_ids(result)
    pitcher_assists = sum(
        line["a"] for line in _fielding_lines(result) if line["player_id"] in pitchers
    )
    # Roughly a third of bunts go back to the mound; none came from strikeouts.
    assert 0 < pitcher_assists <= len(bunt_outs)
