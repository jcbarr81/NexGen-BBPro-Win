"""Release 3 second fix round: bullpen.

* Owner decision 7: an emergency outing by a rested starter is relief and
  never pushes back his next start, however long it ran -- engine clock and
  tracker turn alike. The outing still leaves its trace, blocks a second
  emergency for two days and costs his next start a short-rest penalty.
* An injured (or spent) pitcher with every reliever used and no rested
  reserve is replaced by a reserve arm who fails only the rest-day rule.
* The last-resort tier takes an available (or merely rest-flagged) arm, the
  closer included, before it breaks a hard block.
* At most one emergency (reserve starter) arm per club per game.
"""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as eng
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine import (
    PitcherState,
    TeamPitchingState,
    _build_team_pitching_state,
    _restore_emergency_clocks,
    _select_reliever,
)
from physics_sim.models import PitcherRatings
from physics_sim.usage import UsageState

REPO = Path(__file__).resolve().parents[1]
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"


def _pr(pid: str, role: str = "RP", *, endurance: float = 40.0) -> PitcherRatings:
    return PitcherRatings(
        player_id=pid, bats="R", throws="R", role=role, preferred_role=role,
        velocity=90.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=endurance, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0},
    )


def _ps(pid: str, role: str, *, available=True, used=False, hard=False,
        penalty=0.0, pitches=0, limit=30.0) -> PitcherState:
    return PitcherState(
        pitcher=_pr(pid), staff_role=role, rest_role=role, available=available,
        used=used, hard_blocked=hard, pregame_penalty=penalty, pitches=pitches,
        fatigue_start=limit - 20.0, fatigue_limit=limit,
    )


def _staff(bullpen, reserve=(), current=None):
    starter = current or _ps("sp", "SP", used=True, limit=95.0)
    starter.used = True
    return TeamPitchingState(starter=starter, bullpen=list(bullpen), current=starter,
                             reserve=list(reserve))


def _started(usage, pid, day, pitches=92):
    wl = usage.workload_for(pid)
    wl.last_used_day, wl.last_pitches, wl.consecutive_days_used = day, pitches, 1
    wl.appearances += 1
    return wl


def _reserve_staff(usage, day, roles):
    return _build_team_pitching_state(
        [_pr(pid) for pid in roles], tuning=load_tuning(), usage_state=usage,
        game_day=day, postseason=False, roles_by_id=roles,
    )


def _emergency_game(usage, day, pitches):
    tuning = load_tuning()
    staff = _reserve_staff(usage, day, {"s": "SP1", "r": "SP2", "m": "MR"})
    reserve = next(p for p in staff.reserve if p.pitcher.player_id == "r")
    assert reserve.available
    reserve.used, reserve.pitches, reserve.emergency = True, pitches, True
    usage.record_outing(pitcher_id="r", pitches=pitches, day=day, multiplier=1.0,
                        tuning=tuning)
    _restore_emergency_clocks([staff], usage, tuning)
    return usage.workload_for("r")


# ------------------------------- 1. owner decision 7: the turn is always kept
@pytest.mark.parametrize("pitches", [18, 36, 44, 60])
def test_every_emergency_keeps_his_turn(pitches):
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    wl = _emergency_game(usage, 10, pitches)
    assert (wl.last_used_day, wl.last_pitches, wl.consecutive_days_used) == (7, 92, 1)
    assert (wl.emergency_day, wl.emergency_pitches) == (10, pitches)


def test_a_long_emergency_costs_his_next_start_but_does_not_move_it():
    tuning = load_tuning()
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    _emergency_game(usage, 10, 44)
    # Day 11 is his turn (four days' rest from day 7).
    state = PitcherState(pitcher=_pr("r"), fatigue_start=60.0, fatigue_limit=90.0,
                         staff_role="SP", rest_role="SP2")
    eng._apply_usage_state(state, usage, 11, tuning)
    assert state.available is True
    assert state.pregame_penalty > 0.0


def test_a_long_emergency_still_blocks_a_second_for_two_days():
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    _emergency_game(usage, 10, 44)
    for day, expected in ((11, False), (12, True)):
        staff = _reserve_staff(usage, day, {"s": "SP1", "r": "SP2", "m": "MR"})
        assert staff.reserve[0].available is expected, day


def test_no_keep_turn_threshold_is_left():
    import utils.rotation as rotation

    assert "emergency_keep_turn_pitches" not in DEFAULT_TUNING
    assert not hasattr(rotation, "EMERGENCY_KEEP_TURN_PITCHES")


def _tracker(tmp_path, monkeypatch):
    from utils import roster_loader
    from utils.pitcher_recovery import PitcherRecoveryTracker

    rosters = tmp_path / "rosters"
    rosters.mkdir()
    for name in ("ALB.csv", "ALB_pitching.csv"):
        shutil.copy(CALIBRATION_LEAGUE / "rosters" / name, rosters / name)
    players = CALIBRATION_LEAGUE / "players.csv"
    monkeypatch.setattr(roster_loader, "_placeholder_registry_path",
                        lambda: tmp_path / "_placeholder_registry.json")
    monkeypatch.setattr(roster_loader, "_PLACEHOLDER_PLAYERS_FILE", str(players))
    roster_loader.load_roster.cache_clear()
    tracker = PitcherRecoveryTracker(path=tmp_path / "recovery.json")
    player = SimpleNamespace(player_id="ZZ-SP", role="SP", assigned_pitching_role="SP3")

    def record(day, pitches, relief):
        from utils.pitcher_recovery import _parse_date

        tracker.record_game(
            "ALB", day,
            [SimpleNamespace(player=player, pitches_thrown=pitches, relief_outing=relief)],
            players, rosters,
        )
        status = tracker.data["teams"]["ALB"]["pitchers"]["ZZ-SP"]
        return _parse_date(status["available_on"])

    return record


@pytest.mark.parametrize("pitches", [40, 45, 70])
def test_tracker_a_long_emergency_keeps_his_turn(tmp_path, monkeypatch, pitches):
    record = _tracker(tmp_path, monkeypatch)
    turn = record("2025-04-01", 95, False)
    assert record("2025-04-04", pitches, True) == turn


def test_tracker_an_emergency_on_his_turn_day_clears_him_the_next_day(
    tmp_path, monkeypatch
):
    record = _tracker(tmp_path, monkeypatch)
    turn = record("2025-04-01", 95, False)
    # Already rested on the day of the emergency: the next day is his.
    assert record(turn.isoformat(), 44, True) == turn + timedelta(days=1)


# ------------------------- 2. an empty pen still replaces the injured pitcher
def _rest_blocked_reserve(usage, pid, last_day, *, debt=0.0):
    wl = _started(usage, pid, last_day)
    wl.fatigue_debt = debt


def _empty_pen_staff(day=10):
    """Every reliever used; every reserve arm pitched in the last two days."""
    usage = UsageState(current_day=day, game_index=day)
    _rest_blocked_reserve(usage, "yday", day - 1)
    _rest_blocked_reserve(usage, "today", day)  # doubleheader opener
    _rest_blocked_reserve(usage, "worn", day - 1, debt=500.0)
    staff = _reserve_staff(
        usage, day,
        {"s": "SP1", "today": "SP2", "yday": "SP3", "worn": "SP4", "m": "MR", "c": "CL"},
    )
    assert not any(p.available for p in staff.reserve)
    for p in staff.bullpen:
        p.used = True
    return staff


def test_an_injured_pitcher_with_an_empty_pen_is_replaced():
    staff = _empty_pen_staff()
    pick = _select_reliever(staff, "mid", inning=7, score_diff=0, tuning=load_tuning(),
                            must_replace=True)
    assert pick is not staff.current
    # The least recent arm who fails only the rest-day rule.
    assert pick.pitcher.player_id == "yday"
    assert pick.emergency


def test_a_spent_pitcher_with_an_empty_pen_is_replaced():
    tuning = load_tuning()
    staff = _empty_pen_staff()
    current = staff.current
    current.pitches = int(current.fatigue_limit + tuning.get("bullpen_last_resort_margin"))
    pick = _select_reliever(staff, "mid", inning=7, score_diff=0, tuning=tuning,
                            forced=True)
    assert pick.pitcher.player_id == "yday"


def test_with_mop_up_off_a_spent_pitcher_keeps_the_ball():
    """mop_up is the switch for starters out of the pen: off, an empty pen
    leaves a spent (not hurt) pitcher in rather than taking yesterday's starter."""
    tuning = load_tuning({"mop_up": 0.0})
    staff = _empty_pen_staff()
    current = staff.current
    current.pitches = int(current.fatigue_limit + tuning.get("bullpen_last_resort_margin"))
    pick = _select_reliever(staff, "mid", inning=7, score_diff=0, tuning=tuning, forced=True)
    assert pick is current
    # A hurt pitcher is still replaced.
    hurt = _select_reliever(staff, "mid", inning=7, score_diff=0, tuning=tuning,
                            must_replace=True)
    assert hurt is not current


def test_a_tiring_pitcher_with_an_empty_pen_is_not_yet_replaced():
    staff = _empty_pen_staff()
    staff.current.pitches = int(staff.current.fatigue_limit)
    assert _select_reliever(staff, "mid", inning=7, score_diff=0, tuning=load_tuning(),
                            forced=True) is staff.current


def test_an_injury_replacement_reaches_a_worn_arm_as_the_very_last_resort():
    staff = _empty_pen_staff()
    staff.reserve = [p for p in staff.reserve if p.pitcher.player_id == "worn"]
    pick = _select_reliever(staff, "mid", inning=7, score_diff=0, tuning=load_tuning(),
                            must_replace=True)
    assert pick.pitcher.player_id == "worn"


# --------------------- 3. the last resort takes a legal arm before a block
def test_the_last_resort_takes_the_rested_closer_before_a_hard_block():
    tuning = load_tuning({"mop_up": 0.0})
    starter = _ps("sp", "SP", used=True, limit=95.0, pitches=200)
    team = _staff([
        _ps("blk", "MR", available=False, hard=True),
        _ps("cl", "CL"),
        _ps("blk_cl", "CL", available=False, hard=True),
    ], current=starter)
    # The 6th, no save: the closer is held back -- until the last resort.
    pick = _select_reliever(team, "mid", inning=6, score_diff=0, tuning=tuning,
                            forced=True)
    assert pick.pitcher.player_id == "cl"


def test_the_last_resort_takes_a_rest_flagged_closer_before_a_hard_block():
    tuning = load_tuning({"mop_up": 0.0})
    starter = _ps("sp", "SP", used=True, limit=95.0, pitches=200)
    team = _staff([
        _ps("blk", "MR", available=False, hard=True),
        _ps("cl", "CL", available=False, penalty=0.2),
    ], current=starter)
    pick = _select_reliever(team, "mid", inning=6, score_diff=0, tuning=tuning,
                            must_replace=True)
    assert pick.pitcher.player_id == "cl"


def test_the_last_resort_order_ends_with_the_blocked_closer():
    tuning = load_tuning({"mop_up": 0.0})
    starter = _ps("sp", "SP", used=True, limit=95.0, pitches=200)
    team = _staff([
        _ps("blk_cl", "CL", available=False, hard=True),
        _ps("blk", "MR", available=False, hard=True),
    ], current=starter)
    kw = dict(inning=6, score_diff=0, tuning=tuning, forced=True)
    assert _select_reliever(team, "mid", **kw).pitcher.player_id == "blk"
    team.bullpen[1].used = True
    assert _select_reliever(team, "mid", **kw).pitcher.player_id == "blk_cl"


# --------------------------------------- 4. one emergency arm per game
def _after_one_emergency():
    tuning = load_tuning()
    first = _ps("first", "SP", limit=45.0)
    second = _ps("second", "SP", limit=45.0)
    team = _staff([_ps("m", "MR", used=True)], reserve=[first, second])
    pick = _select_reliever(team, "long", inning=12, score_diff=0, tuning=tuning,
                            forced=True)
    assert pick is first or pick is second
    eng._enter_pitcher(team, pick, inning=12, score_diff=0, postseason=False,
                       tuning=tuning)
    return team, tuning


def test_a_second_emergency_arm_is_not_brought_in_at_the_cap():
    team, tuning = _after_one_emergency()
    current = team.current
    current.pitches = int(current.fatigue_limit)
    assert _select_reliever(team, "long", inning=14, score_diff=0, tuning=tuning,
                            forced=True) is current
    # Past the margin: the last-resort tier, here a hard-blocked reliever.
    team.bullpen.append(_ps("blk", "MR", available=False, hard=True))
    current.pitches = int(current.fatigue_limit + tuning.get("bullpen_last_resort_margin"))
    pick = _select_reliever(team, "long", inning=14, score_diff=0, tuning=tuning,
                            forced=True)
    assert pick.pitcher.player_id == "blk"


def test_a_spent_emergency_arm_with_nobody_else_stays_in():
    team, tuning = _after_one_emergency()
    current = team.current
    current.pitches = int(current.fatigue_limit + tuning.get("bullpen_last_resort_margin"))
    assert _select_reliever(team, "long", inning=15, score_diff=0, tuning=tuning,
                            forced=True) is current


def test_an_injured_emergency_arm_is_still_replaced():
    team, tuning = _after_one_emergency()
    pick = _select_reliever(team, "long", inning=15, score_diff=0, tuning=tuning,
                            must_replace=True)
    assert pick is not team.current and pick in team.reserve


# ------------------------------------------------------------- KPI tallies
def test_kpi_extras_counts_multi_emergency_games_and_per_team_rate():
    import scripts.kpi_extras as kx

    def line(pid, gs, pitches=30):
        return {"player_id": pid, "gs": gs, "pitches": pitches, "outs": 3}

    meta = {
        "inning_runs": {}, "score": {"away": 1, "home": 2}, "innings": 9,
        "batting_lines": {"away": [], "home": []},
        "fielding_lines": {"away": [], "home": []},
        "pitcher_lines": {
            "away": [line("A1", 1), line("A2", 0), line("A3", 0)],
            "home": [line("H1", 1), line("H2", 0), line("CL1", 0), line("CL2", 0)],
        },
        "pitcher_usage": {
            "away": [
                {"player_id": "A1", "staff_role": "SP"},
                {"player_id": "A2", "staff_role": "SP", "emergency": True},
                {"player_id": "A3", "staff_role": "SP", "emergency": True},
            ],
            "home": [
                {"player_id": "H1", "staff_role": "SP"},
                {"player_id": "H2", "staff_role": "SP", "emergency": True},
                {"player_id": "CL1", "staff_role": "CL"},
                {"player_id": "CL2", "staff_role": "CL"},
            ],
        },
    }
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=1)
    log = [
        {"pitcher_id": "H1", "inning": 1},
        {"pitcher_id": "CL1", "inning": 6},
        {"pitcher_id": "CL2", "inning": 9},
    ]
    acc.add_game(SimpleNamespace(totals={}, pitch_log=log, metadata=meta),
                 away="A", home="H")
    m = acc.finalize(kx.load_reference())["metrics"]
    assert m["emergency_starter_relief_apps"] == 3
    # One club used two emergency arms in one game.
    assert m["emergency_multi_games"] == 1
    # Three emergency outings over two clubs, scaled to 162 games each.
    assert m["emergency_apps_per_team_season"] == pytest.approx(3 / 2 * 162)
    # One of the two closer outings began before the 7th.
    assert m["closer_entries_before_7th_share"] == pytest.approx(0.5)
