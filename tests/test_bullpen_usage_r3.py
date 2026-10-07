"""Release 3 (audit H1, item R3-B): bullpen usage and staff roles.

Covers the role normaliser in the engine, starter limits for every starter,
the gated empty-bullpen fallback (never the closer), the inning-start hook
reasons, the non-closer appearance cap keyed on the game-date index, the
removed closer rest bypass, the mop-up emergency starter (owner decision Q6)
and the one shared rotation builder on the harness and live paths.
"""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as eng
from physics_sim.config import load_tuning
from physics_sim.engine import (
    PitcherLine,
    PitcherState,
    TeamPitchingState,
    _build_team_pitching_state,
    _forced_hook,
    _hook_reason,
    _pitcher_usage_limits,
    _restore_emergency_clocks,
    _select_reliever,
)
from physics_sim.models import PitcherRatings
from physics_sim.team_data import PitcherAssignment, build_staff
from physics_sim.usage import UsageState
from utils.rotation import game_staff_roles

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"


def _pr(pid: str, role: str = "RP", *, endurance: float = 40.0) -> PitcherRatings:
    return PitcherRatings(
        player_id=pid, bats="R", throws="R", role=role, preferred_role=role,
        velocity=90.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=endurance, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 60.0},
    )


def _ps(pid: str, role: str, *, available=True, used=False, hard=False,
        penalty=0.0) -> PitcherState:
    return PitcherState(
        pitcher=_pr(pid), staff_role=role, rest_role=role, available=available,
        used=used, hard_blocked=hard, pregame_penalty=penalty,
        fatigue_start=10.0, fatigue_limit=30.0,
    )


# ------------------------------------------------------------ role normaliser
@pytest.mark.parametrize("label", ["MR1", "MR3", "MR4", "MR5", "RP", "R", "P", "mr2 "])
def test_every_middle_relief_label_gets_mr_limits(label):
    tuning = load_tuning()
    pitcher = _pr("x", endurance=55.0)
    assert _pitcher_usage_limits(pitcher, tuning, role=label) == _pitcher_usage_limits(
        pitcher, tuning, role="MR"
    )
    # ...which are a reliever's window, not a starter's.
    assert _pitcher_usage_limits(pitcher, tuning, role=label)[1] < _pitcher_usage_limits(
        pitcher, tuning, role="SP"
    )[1]


def test_staff_built_with_canonical_roles_and_raw_slots():
    tuning = load_tuning()
    pitchers = [_pr("st"), _pr("a"), _pr("b"), _pr("c"), _pr("d"), _pr("e")]
    roles = {"st": "MR1", "a": "MR4", "b": "RP", "c": "", "d": "SP3", "e": "CL"}
    staff = _build_team_pitching_state(
        pitchers, tuning=tuning, usage_state=None, game_day=None,
        postseason=False, roles_by_id=roles,
    )
    # The starter is a starter whatever his label: SP limits, no outs cap.
    assert staff.starter.staff_role == "SP"
    assert staff.starter.staff_slot == "MR1"
    assert staff.starter.rest_role == "MR"
    assert (staff.starter.fatigue_start, staff.starter.fatigue_limit) == (
        _pitcher_usage_limits(pitchers[0], tuning, role="SP")
    )
    by_id = {p.pitcher.player_id: p for p in staff.bullpen}
    assert set(by_id) == {"a", "b", "c", "e"}
    assert {by_id[k].staff_role for k in "abc"} == {"MR"}
    assert by_id["a"].staff_slot == "MR4"
    assert by_id["e"].staff_role == "CL"
    # Today's other rotation arm waits in reserve, never in the pen.
    assert [p.pitcher.player_id for p in staff.reserve] == ["d"]
    assert staff.all_pitchers() == [staff.starter] + staff.bullpen


def test_mr_slots_pitch_exactly_like_mr():
    tuning = load_tuning()
    a = _build_team_pitching_state(
        [_pr("s"), _pr("r")], tuning=tuning, usage_state=None, game_day=None,
        postseason=False, roles_by_id={"s": "SP1", "r": "MR4"},
    ).bullpen[0]
    b = _build_team_pitching_state(
        [_pr("s"), _pr("r")], tuning=tuning, usage_state=None, game_day=None,
        postseason=False, roles_by_id={"s": "SP1", "r": "MR"},
    ).bullpen[0]
    for attr in ("staff_role", "rest_role", "fatigue_start", "fatigue_limit", "available"):
        assert getattr(a, attr) == getattr(b, attr)


# --------------------------------------------------------- hooks and fallback
def _line(outs=0, bf=0):
    line = PitcherLine(pitcher_id="x")
    line.outs = outs
    line.batters_faced = bf
    return line


def test_hook_reasons():
    tuning = load_tuning()
    mr = _ps("m", "MR")
    kw = dict(lineup_size=9, score_diff=0, postseason=False, tuning=tuning)
    cap = int(tuning.get("middle_reliever_max_outs"))
    assert _hook_reason(pitcher_state=mr, line=_line(cap, cap), **kw) == "outs_cap"
    # Mop-up: every reliever used, so the one in the game finishes it.
    assert _hook_reason(pitcher_state=mr, line=_line(cap, cap), mop_up=True, **kw) is None
    mr.pitches = 40  # past fatigue_limit 30
    assert _hook_reason(pitcher_state=mr, line=_line(1, 3), **kw) == "pitch_cap"
    tired = _ps("t", "MR")
    tired.last_penalty = 0.95
    assert _hook_reason(pitcher_state=tired, line=_line(1, 3), hard_only=True, **kw) == "fatigue"
    assert _forced_hook("pitch_cap", mr, tuning) and _forced_hook("fatigue", mr, tuning)
    assert not _forced_hook("outs_cap", _ps("f", "MR"), tuning)
    assert not _forced_hook("score", _ps("f", "MR"), tuning)
    assert _forced_hook("outs_cap", tired, tuning)  # already at the hard penalty
    # A spot starter is not held to a reliever's outs cap.
    sp = _ps("s", "SP")
    assert _hook_reason(pitcher_state=sp, line=_line(cap, cap), **kw) is None


def _staff(bullpen, reserve=()):
    starter = _ps("sp", "SP", used=True)
    return TeamPitchingState(starter=starter, bullpen=list(bullpen), current=starter,
                             reserve=list(reserve))


def test_forced_change_takes_the_freshest_rest_flagged_arm_never_the_closer():
    tuning = load_tuning()
    team = _staff([
        _ps("cl", "CL", available=False),
        _ps("su", "SU", available=False, penalty=0.3),
        _ps("mr", "MR", available=False, penalty=0.1),
        _ps("blk", "MR", available=False, hard=True),
    ])
    kw = dict(inning=9, score_diff=1, tuning=tuning)
    assert _select_reliever(team, "high", **kw) is team.current
    pick = _select_reliever(team, "high", forced=True, **kw)
    assert pick.pitcher.player_id == "mr"
    assert pick.fallback is True


def test_with_only_the_closer_or_blocked_arms_left_the_pitcher_stays():
    tuning = load_tuning({"mop_up": 0.0})
    team = _staff([_ps("cl", "CL", available=False), _ps("b", "MR", available=False, hard=True)])
    assert _select_reliever(team, "mid", inning=6, score_diff=0, tuning=tuning,
                            forced=True) is team.current


def test_fallback_and_mop_up_are_gated_by_their_knobs():
    team = _staff([_ps("mr", "MR", available=False)], reserve=[_ps("r", "SP")])
    off = load_tuning({"bullpen_fallback": 0.0, "mop_up": 0.0})
    assert _select_reliever(team, "mid", inning=6, score_diff=0, tuning=off,
                            forced=True) is team.current


def test_mop_up_brings_in_a_rested_starter():
    tuning = load_tuning()
    rested = _ps("rested", "SP")
    tired = _ps("tired", "SP", available=False)
    team = _staff([_ps("mr", "MR", used=True)], reserve=[tired, rested])
    pick = _select_reliever(team, "long", inning=12, score_diff=0, tuning=tuning, forced=True)
    assert pick is rested and pick.emergency is True


def test_reserve_needs_two_days_off():
    tuning = load_tuning()
    usage = UsageState(current_day=10, game_index=10)
    for pid, last in (("yesterday", 9), ("two_days", 8)):
        wl = usage.workload_for(pid)
        wl.last_used_day, wl.last_pitches, wl.appearances = last, 95, 2
    staff = _build_team_pitching_state(
        [_pr("s"), _pr("yesterday"), _pr("two_days"), _pr("cl")], tuning=tuning,
        usage_state=usage, game_day=10, postseason=False,
        roles_by_id={"s": "SP1", "yesterday": "SP2", "two_days": "SP3", "cl": "CL"},
    )
    avail = {p.pitcher.player_id: p.available for p in staff.reserve}
    assert avail == {"yesterday": False, "two_days": True}


def test_emergency_outing_leaves_the_starter_clock_alone():
    tuning = load_tuning()
    usage = UsageState(current_day=10, game_index=10)
    wl = usage.workload_for("r")
    wl.last_used_day, wl.last_pitches, wl.consecutive_days_used, wl.appearances = 8, 92, 1, 2
    staff = _build_team_pitching_state(
        [_pr("s"), _pr("r"), _pr("m")], tuning=tuning, usage_state=usage, game_day=10,
        postseason=False, roles_by_id={"s": "SP1", "r": "SP2", "m": "MR"},
    )
    reserve = staff.reserve[0]
    reserve.used, reserve.pitches = True, 35
    assert reserve in staff.all_pitchers()
    debt_before = wl.fatigue_debt
    usage.record_outing(pitcher_id="r", pitches=35, day=10, multiplier=1.0, tuning=tuning)
    _restore_emergency_clocks([staff], usage)
    assert (wl.last_used_day, wl.last_pitches, wl.consecutive_days_used) == (8, 92, 1)
    assert wl.fatigue_debt > debt_before and wl.appearances == 3


# ------------------------------------------------------------ appearance caps
def _cap_state(role, *, game_day, game_index, appearances):
    tuning = load_tuning()
    usage = UsageState(current_day=game_day, game_index=game_index)
    wl = usage.workload_for("p")
    wl.last_used_day, wl.last_pitches, wl.appearances = game_day - 3, 10, appearances
    state = PitcherState(pitcher=_pr("p"), fatigue_start=50.0, fatigue_limit=60.0,
                         staff_role=role, rest_role=role)
    eng._apply_usage_state(state, usage, game_day, tuning)
    return state


def test_non_closer_cap_is_half_the_club_games_on_the_game_index():
    # Game index 99 -> cap int(100 * 0.50) = 50; the calendar day is ignored.
    assert _cap_state("SU", game_day=140, game_index=99, appearances=49).available
    blocked = _cap_state("MR2", game_day=140, game_index=99, appearances=50)
    assert not blocked.available and blocked.hard_blocked
    # The closer keeps his own, tighter ratio (0.45 -> 45).
    assert not _cap_state("CL", game_day=140, game_index=99, appearances=45).available
    assert _cap_state("CL", game_day=140, game_index=99, appearances=44).available


def test_cap_floor_knob_is_registered_and_applies():
    tuning = load_tuning({"appearance_cap_min_apps": "4"})
    assert tuning.get("appearance_cap_min_apps") == pytest.approx(4.0)
    usage = UsageState(current_day=2, game_index=2)
    wl = usage.workload_for("p")
    wl.last_used_day, wl.last_pitches, wl.appearances = 0, 10, 3
    state = PitcherState(pitcher=_pr("p"), fatigue_start=50.0, fatigue_limit=60.0,
                         staff_role="MR", rest_role="MR")
    eng._apply_usage_state(state, usage, 2, tuning)
    assert state.available  # cap int(3 * 0.5) = 1, floored to 4
    wl.appearances = 4
    state = PitcherState(pitcher=_pr("p"), fatigue_start=50.0, fatigue_limit=60.0,
                         staff_role="MR", rest_role="MR")
    eng._apply_usage_state(state, usage, 2, tuning)
    assert not state.available and state.hard_blocked


def test_third_straight_day_is_a_hard_block():
    tuning = load_tuning()
    usage = UsageState(current_day=50, game_index=50)
    wl = usage.workload_for("p")
    wl.last_used_day, wl.last_pitches, wl.consecutive_days_used, wl.appearances = 49, 8, 2, 10
    state = PitcherState(pitcher=_pr("p"), fatigue_start=50.0, fatigue_limit=60.0,
                         staff_role="CL", rest_role="CL")
    eng._apply_usage_state(state, usage, 50, tuning)
    assert not state.available and state.hard_blocked and state.prior_streak == 2


# ------------------------------------------------------- full-game behaviour
def _calibration_game(seed, usage, day):
    return eng.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=CALIBRATION / "players.csv",
        base_dir=CALIBRATION, seed=seed, usage_state=usage, game_day=day,
    )


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_a_blocked_closer_never_pitches(seed):
    """The 9th-inning block used to bring in an unused closer even when he
    was flagged unavailable (51-63% of closer outings)."""
    usage = UsageState()
    staff = {}
    for team in ("CAL01", "CAL02"):
        path = CALIBRATION / "rosters" / f"{team}_pitching.csv"
        for row in path.read_text(encoding="utf-8").splitlines():
            pid, role = row.split(",")[:2]
            staff[pid.strip()] = role.strip()
    closers = [pid for pid, role in staff.items() if role == "CL"]
    usage.advance_day(day=200, pitchers=[], tuning=load_tuning())
    usage.game_index = 120
    for pid in closers:  # pitched the last two days: a third straight day
        wl = usage.workload_for(pid)
        wl.last_used_day, wl.last_pitches, wl.consecutive_days_used = 199, 10, 2
        wl.appearances, wl.last_update_day = 30, 200
    result = _calibration_game(seed, usage, 200)
    pitched = {
        line["player_id"]
        for side in ("away", "home")
        for line in result.metadata["pitcher_lines"][side]
    }
    assert not pitched & set(closers)
    for side in ("away", "home"):
        for u in result.metadata["pitcher_usage"][side]:
            assert u["staff_role"] in {"SP", "CL", "SU", "LR", "MR"}


# -------------------------------------------------------- shared rotation
def test_game_staff_roles():
    roles = game_staff_roles(
        {"a": "SP1", "b": "SP2", "c": "SP6", "d": "CL", "e": "MR4", "f": "rp"},
        ["a", "b", "c", "d", "e", "f", "g"],
        ["b", "a", "zz"],
    )
    assert roles == {"b": "SP1", "a": "SP2", "c": "MR", "d": "CL", "e": "MR4",
                     "f": "RP", "g": "MR"}


def test_build_staff_fills_the_rotation_without_the_closer():
    pitchers = {
        pid: _pr(pid, role, endurance=end)
        for pid, role, end in (
            ("s1", "SP", 60), ("s2", "SP", 55), ("lr", "SP", 50), ("cl", "SP", 90),
            ("mr", "RP", 30), ("x", "SP", 45), ("y", "RP", 20),
        )
    }
    assignments = [
        PitcherAssignment("s1", "SP1"), PitcherAssignment("s2", "SP2"),
        PitcherAssignment("lr", "LR"), PitcherAssignment("cl", "CL"),
        PitcherAssignment("mr", "MR2"),
    ]
    ordered, roles, missing = build_staff(
        assignments, pitchers, active_ids=set(pitchers), game_day=0
    )
    assert missing == []
    rotation = [pid for pid, role in roles.items() if role.startswith("SP")]
    # The owner's two, then the unlisted starter, then the long man; the last
    # slot goes to the next arm in staff order -- never the closer.
    assert rotation == ["s1", "s2", "x", "lr", "mr"]
    assert roles["cl"] == "CL"
    # An unlisted arm outside the rotation is a middle reliever.
    assert roles["y"] == "MR"
    assert ordered[0].player_id == "s1"


def test_build_staff_keeps_the_owner_five_unchanged():
    staff = {}
    for row in (CALIBRATION / "rosters" / "CAL01_pitching.csv").read_text().splitlines():
        pid, role = row.split(",")[:2]
        staff[pid] = role
    from physics_sim.data_loader import load_players_by_id

    _, pitchers_by_id = load_players_by_id(CALIBRATION / "players.csv")
    assignments = [PitcherAssignment(pid, role) for pid, role in staff.items()]
    _, roles, _ = build_staff(assignments, pitchers_by_id, active_ids=set(staff))
    assert roles == staff


def test_live_role_map_never_reads_the_stored_role_column():
    from playbalance.game_runner import _physics_pitcher_roles

    def arm(pid, assigned, stored="RP"):
        return SimpleNamespace(player_id=pid, assigned_pitching_role=assigned, role=stored)

    state = SimpleNamespace(pitchers=[
        arm("a", "SP2"), arm("b", "SP1"), arm("c", ""), arm("d", "", stored="SP"),
        arm("e", "MR4"), arm("f", "CL"),
    ])
    assert _physics_pitcher_roles(state) == {
        "b": "SP1", "a": "SP2", "c": "MR", "d": "MR", "e": "MR4", "f": "CL",
    }


def test_tracker_records_a_starters_relief_outing_without_moving_his_turn(tmp_path):
    from utils.path_utils import get_data_dir
    from utils.pitcher_recovery import PitcherRecoveryTracker, _parse_date

    tracker = PitcherRecoveryTracker(path=tmp_path / "pitcher_recovery_test.json")
    players_file = get_data_dir() / "players.csv"
    roster_dir = get_data_dir() / "rosters"
    player = SimpleNamespace(player_id="ZZ-SP", role="SP", assigned_pitching_role="SP3")

    def record(day, pitches, relief):
        tracker.record_game(
            "ATL", day,
            [SimpleNamespace(player=player, pitches_thrown=pitches, relief_outing=relief)],
            players_file, roster_dir,
        )
        return _parse_date(tracker.data["teams"]["ATL"]["pitchers"]["ZZ-SP"]["available_on"])

    start_turn = record("2025-04-01", 95, False)
    assert start_turn > _parse_date("2025-04-03")
    assert record("2025-04-03", 35, True) == start_turn
    # A real start on the same day would have restarted the clock.
    assert record("2025-04-03", 95, False) > start_turn
    assert start_turn - _parse_date("2025-04-01") >= timedelta(days=4)
