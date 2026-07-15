"""S2-05: fatigue-aware pre-game position-player rest swaps."""
from pathlib import Path

import physics_sim.engine as engine
from physics_sim.config import load_tuning
from physics_sim.engine import _apply_rest_days
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.usage import UsageState

CAL = Path("data/calibration")


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


def _threshold(dur=50):
    return 35.0 + dur * 0.45  # 57.5 at durability 50


def test_fatigued_starter_is_benched():
    lineup = [_b("s1", "1B"), _b("s2", "2B")]
    bench = [_b("r1", "1B")]
    us = UsageState()
    us.batter_workload_for("s1").fatigue_debt = 60.0  # > 0.85 * 57.5
    lu, be, po = _apply_rest_days(
        lineup, bench, {"s1": "1B", "s2": "2B"}, opposing_starter=_pitcher(),
        usage_state=us, game_day=10, tuning=load_tuning(),
    )
    assert [b.player_id for b in lu] == ["r1", "s2"]  # inherits slot 0
    assert po[lu[0].player_id] == "1B"
    assert "s1" not in {b.player_id for b in be}  # true day off
    wl = us.batter_workload_for("s1")
    assert wl.last_rest_day == 10 and wl.rests == 1


def test_consecutive_limit_benches_catcher_not_first_baseman():
    lineup = [_b("c1", "C"), _b("f1", "1B")]
    bench = [_b("bc", "C"), _b("b1", "1B")]
    us = UsageState()
    us.batter_workload_for("c1").consecutive_days_used = 3  # catcher limit
    us.batter_workload_for("f1").consecutive_days_used = 3  # under 1B limit (9)
    lu, be, po = _apply_rest_days(
        lineup, bench, {"c1": "C", "f1": "1B"}, opposing_starter=_pitcher(),
        usage_state=us, game_day=10, tuning=load_tuning(),
    )
    assert lu[0].player_id == "bc"  # catcher swapped
    assert lu[1].player_id == "f1"  # 1B not swapped


def test_no_eligible_replacement_no_swap():
    lineup = [_b("c1", "C")]
    bench = [_b("b1", "1B")]  # no backup C
    us = UsageState()
    us.batter_workload_for("c1").consecutive_days_used = 5
    lu, _be, _po = _apply_rest_days(
        lineup, bench, {"c1": "C"}, opposing_starter=_pitcher(),
        usage_state=us, game_day=10, tuning=load_tuning(),
    )
    assert lu[0].player_id == "c1"


def test_min_gap_prevents_repeat_rest():
    def run(debt):
        us = UsageState()
        wl = us.batter_workload_for("s1")
        wl.fatigue_debt = debt
        wl.last_rest_day = 8  # 2 game days ago (< min_gap 5)
        lu, _be, _po = _apply_rest_days(
            [_b("s1", "1B")], [_b("r1", "1B")], {"s1": "1B"},
            opposing_starter=_pitcher(), usage_state=us, game_day=10,
            tuning=load_tuning(),
        )
        return lu[0].player_id
    assert run(0.9 * _threshold()) == "s1"       # soft-fatigued + recently rested -> stays
    assert run(1.3 * _threshold()) == "r1"       # hard-fatigued overrides the gap


def test_max_two_swaps_per_game():
    lineup = [_b("s1", "1B"), _b("s2", "2B"), _b("s3", "3B")]
    bench = [_b("r1", "1B"), _b("r2", "2B"), _b("r3", "3B")]
    us = UsageState()
    for p in ("s1", "s2", "s3"):
        us.batter_workload_for(p).fatigue_debt = 60.0
    lu, be, _po = _apply_rest_days(
        lineup, bench, {"s1": "1B", "s2": "2B", "s3": "3B"},
        opposing_starter=_pitcher(), usage_state=us, game_day=10,
        tuning=load_tuning(),
    )
    swapped = sum(1 for b in lu if b.player_id.startswith("r"))
    assert swapped == 2


def test_noop_without_usage_state():
    lineup = [_b("s1", "1B")]
    bench = [_b("r1", "1B")]
    pos = {"s1": "1B"}
    lu, be, po = _apply_rest_days(
        lineup, bench, pos, opposing_starter=_pitcher(),
        usage_state=None, game_day=None, tuning=load_tuning(),
    )
    assert lu is lineup and be is bench and po is pos


def test_replacement_gets_gs_credit():
    us = UsageState()
    # Force the CAL01 leadoff catcher fatigued so the backup starts.
    from physics_sim.team_data import load_lineup
    slots = load_lineup("CAL01", "rhp", base_dir=CAL)
    tired = slots[0].player_id
    us.batter_workload_for(tired).fatigue_debt = 200.0
    r = engine.simulate_matchup_from_files(
        away_team="CAL02", home_team="CAL01",
        players_path=CAL / "players.csv", base_dir=CAL,
        park_name="Fenway Park", seed=5, usage_state=us, game_day=3,
    )
    home_ids = {
        line["player_id"] for line in (r.metadata["batting_lines"] or {}).get("home", [])
        if int(line.get("gs", 0) or 0) == 1
    }
    assert tired not in home_ids  # rested starter did not start
