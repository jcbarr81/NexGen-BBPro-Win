"""Release 3 item F (audit M16): batter fatigue that accrues, tiered rest
substitutes and the owner's per-team rest settings.

* fatigue builds over a run of games and a day on the bench clears it;
* a catcher rests on his 4th straight game;
* rest substitutes: listed position, then a one-swap chain, then -- on a hard
  rest only, at most one per team per game, and only where the team allows
  it -- a similar position; never a non-catcher at C;
* an owner can turn automatic rest days off.
"""

from pathlib import Path

import pytest

from physics_sim.config import load_tuning
from physics_sim.engine import _apply_rest_days, simulate_matchup_from_files
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.usage import (
    UsageState,
    batter_fatigue_threshold,
    batter_game_cost,
)

CAL = Path("data/calibration")
TUNING = load_tuning()


def _b(pid: str, pos: str, *, dur: int = 50, other: str = "", ch: int = 55) -> BatterRatings:
    return BatterRatings.from_row(
        {"player_id": pid, "bats": "R", "primary_position": pos,
         "other_positions": other, "ch": str(ch), "ph": "55", "vl": "50",
         "eye": "50", "gf": "50", "pl": "50", "fa": "50", "arm": "50",
         "sp": "50", "durability": str(dur)}
    )


def _pitcher() -> PitcherRatings:
    return PitcherRatings.from_row(
        {"player_id": "p", "bats": "L", "throws": "L", "control": "50", "fb": "60"}
    )


def _play_days(state: UsageState, batter: BatterRatings, days, *, position="1B"):
    for day in days:
        state.advance_day(day=day, pitchers=[], batters=[batter], tuning=TUNING)
        state.record_batter_game(
            player_id=batter.player_id, day=day, durability=batter.durability,
            tuning=TUNING, position=position,
        )


def _rest(lineup, bench, positions, state, *, day=20, **kw):
    return _apply_rest_days(
        lineup, bench, positions, opposing_starter=_pitcher(),
        usage_state=state, game_day=day, tuning=TUNING, **kw,
    )


# --- fatigue accrues ----------------------------------------------------------


def test_an_everyday_regular_reaches_the_rest_trigger_after_a_long_run():
    trigger = TUNING.get("batter_rest_fatigue_ratio") * batter_fatigue_threshold(50, TUNING)
    state = UsageState()
    player = _b("r", "1B")
    _play_days(state, player, range(12))
    assert state.batter_workload_for("r").fatigue_debt < trigger  # not after 12
    _play_days(state, player, range(12, 60))
    assert state.batter_workload_for("r").fatigue_debt >= trigger  # it builds


def test_a_day_on_the_bench_clears_more_than_a_team_off_day():
    def debt_after(skip_kind: str) -> float:
        state = UsageState()
        player = _b("r", "1B")
        _play_days(state, player, range(20))
        if skip_kind == "bench":
            # The team played day 20 and he sat (advanced, not charged).
            state.advance_day(day=20, pitchers=[], batters=[player], tuning=TUNING)
        _play_days(state, player, [21])
        return state.batter_workload_for("r").fatigue_debt

    played_through = UsageState()
    p = _b("r", "1B")
    _play_days(played_through, p, range(22))
    straight = played_through.batter_workload_for("r").fatigue_debt
    off_day = debt_after("off")      # day 20 had no game for his team
    benched = debt_after("bench")    # day 20 was a game he sat out
    assert benched < off_day < straight


def test_game_cost_depends_on_the_position_started():
    c = batter_game_cost(50, TUNING, position="C")
    field = batter_game_cost(50, TUNING, position="SS")
    dh = batter_game_cost(50, TUNING, position="DH")
    sub = batter_game_cost(50, TUNING, position="LF", started=False)
    assert c > field > dh > sub > 0
    assert batter_game_cost(30, TUNING, position="SS") > field  # fragile pays more


def test_a_substitute_appearance_does_not_extend_the_streak():
    state = UsageState()
    player = _b("r", "C")
    _play_days(state, player, range(3), position="C")
    assert state.batter_workload_for("r").consecutive_days_used == 3
    state.advance_day(day=3, pitchers=[], batters=[player], tuning=TUNING)
    state.record_batter_game(
        player_id="r", day=3, durability=50, tuning=TUNING, position="C", started=False
    )
    state.advance_day(day=4, pitchers=[], batters=[player], tuning=TUNING)
    assert state.batter_workload_for("r").consecutive_days_used == 0  # streak broken


def test_fatigue_level_accessor_for_the_injury_model():
    state = UsageState()
    assert state.batter_fatigue_level("nobody", 50, TUNING) == 0.0
    assert "nobody" not in state.batter_workloads  # read-only
    state.batter_workload_for("r").fatigue_debt = batter_fatigue_threshold(50, TUNING)
    assert state.batter_fatigue_level("r", 50, TUNING) == pytest.approx(1.0)


# --- catchers ---------------------------------------------------------------


def test_a_catcher_rests_on_his_fourth_straight_game_not_his_third():
    def swapped(streak: int) -> bool:
        state = UsageState()
        state.batter_workload_for("c1").consecutive_days_used = streak
        lineup, _bench, _pos = _rest([_b("c1", "C")], [_b("c2", "C")], {"c1": "C"}, state)
        return lineup[0].player_id == "c2"

    assert not swapped(2)   # going for his 3rd straight game: plays
    assert swapped(3)       # 4th straight: rests


def test_never_a_non_catcher_behind_the_plate():
    state = UsageState()
    wl = state.batter_workload_for("c1")
    wl.consecutive_days_used = 10
    wl.fatigue_debt = 200.0  # as hard as a rest gets
    bench = [_b("u", "1B", other="3B"), _b("o", "LF")]
    lineup, _bench, _pos = _rest([_b("c1", "C")], bench, {"c1": "C"}, state)
    assert lineup[0].player_id == "c1"


def test_a_catcher_at_dh_moves_behind_the_plate_and_the_bench_takes_dh():
    state = UsageState()
    state.batter_workload_for("c1").consecutive_days_used = 3
    lineup = [_b("c1", "C"), _b("c2", "C")]
    positions = {"c1": "C", "c2": "DH"}
    report: dict = {}
    lu, _be, po = _rest(lineup, [_b("x", "LF")], positions, state, report=report)
    assert [b.player_id for b in lu] == ["x", "c2"]
    assert po["c2"] == "C" and po["x"] == "DH"
    assert report["chain"] == 1


# --- tiers for other positions ------------------------------------------------


def _tired(state: UsageState, pid: str) -> None:
    state.batter_workload_for(pid).fatigue_debt = 0.95 * batter_fatigue_threshold(50, TUNING)


def _hard_tired(state: UsageState, pid: str) -> None:
    # A hard rest: debt at batter_rest_hard_ratio of the threshold (fix round).
    ratio = TUNING.get("batter_rest_hard_ratio") + 0.05
    state.batter_workload_for(pid).fatigue_debt = ratio * batter_fatigue_threshold(50, TUNING)


def test_listed_position_first():
    state = UsageState()
    _tired(state, "s")
    bench = [_b("sim", "SS", ch=90), _b("lst", "LF", other="2B", ch=40)]
    lu, _be, po = _rest([_b("s", "2B")], bench, {"s": "2B"}, state)
    assert lu[0].player_id == "lst" and po["lst"] == "2B"


def test_similar_position_only_on_a_hard_rest():
    bench = [_b("ss", "SS")]
    # A scheduled (streak) rest just reached: no listed 2B, no similar move.
    soft = UsageState()
    soft.batter_workload_for("s").consecutive_days_used = int(
        TUNING.get("batter_rest_consecutive_limit")
    )
    report: dict = {}
    lu, _be, _po = _rest([_b("s", "2B")], bench, {"s": "2B"}, soft, report=report)
    assert lu[0].player_id == "s" and report["blocked"] == 1
    # Hard-tired: the shortstop covers second.
    hard = UsageState()
    _hard_tired(hard, "s")
    lu, _be, po = _rest([_b("s", "2B")], bench, {"s": "2B"}, hard)
    assert lu[0].player_id == "ss" and po["ss"] == "2B"


def test_similar_moves_follow_the_owner_list():
    # Nobody moves to SS or CF; a CF covers a corner; any infielder covers 1B.
    for pos, bench_pos, allowed in (
        ("SS", "2B", False), ("CF", "LF", False), ("RF", "CF", True),
        ("1B", "3B", True), ("3B", "1B", False),
    ):
        state = UsageState()
        _hard_tired(state, "s")
        lu, _be, _po = _rest([_b("s", pos)], [_b("b", bench_pos)], {"s": pos}, state)
        assert (lu[0].player_id == "b") is allowed, (pos, bench_pos)


def test_at_most_one_similar_substitute_per_team_per_game():
    state = UsageState()
    _hard_tired(state, "s1")
    _hard_tired(state, "s2")
    lineup = [_b("s1", "LF"), _b("s2", "1B")]
    bench = [_b("rf", "RF"), _b("ss", "SS")]
    report: dict = {}
    lu, _be, _po = _rest(lineup, bench, {"s1": "LF", "s2": "1B"}, state, report=report)
    assert report["similar"] == 1 and report["blocked"] == 1
    assert sum(1 for b in lu if b.player_id in {"rf", "ss"}) == 1


def test_an_owner_can_turn_similar_substitutes_off():
    state = UsageState()
    _tired(state, "s")
    lu, _be, _po = _rest(
        [_b("s", "LF")], [_b("rf", "RF")], {"s": "LF"}, state, allow_similar=False
    )
    assert lu[0].player_id == "s"


# --- the owner's auto-rest switch reaches the engine --------------------------


def _home_starter_ids(result) -> set[str]:
    return {
        line["player_id"] for line in (result.metadata["batting_lines"] or {}).get("home", [])
        if int(line.get("gs", 0) or 0) == 1
    }


@pytest.mark.parametrize("auto_rest", [True, False])
def test_auto_rest_days_off_keeps_the_saved_lineup(auto_rest, monkeypatch):
    import physics_sim.engine as engine
    from physics_sim.team_data import load_lineup

    slots = load_lineup("CAL01", "rhp", base_dir=CAL)
    tired = slots[0].player_id
    state = UsageState()
    state.batter_workload_for(tired).fatigue_debt = 200.0
    real = engine.simulate_game

    def with_policy(**kw):
        kw["home_rest_policy"] = {"auto_rest_days": auto_rest}
        return real(**kw)

    monkeypatch.setattr(engine, "simulate_game", with_policy)
    result = simulate_matchup_from_files(
        away_team="CAL02", home_team="CAL01",
        players_path=CAL / "players.csv", base_dir=CAL,
        park_name="Fenway Park", seed=5, usage_state=state, game_day=3,
    )
    assert (tired in _home_starter_ids(result)) is (not auto_rest)
    home = result.metadata["bench_usage"]["home"]
    if not auto_rest:
        assert home.get("rests", 0) == 0 and home["starters_tired"] >= 1
