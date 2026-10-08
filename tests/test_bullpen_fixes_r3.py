"""Release 3 fix round for item B (bullpen usage).

Regressions from the item-B reviews:

* the emergency starter's outing leaves a trace (``emergency_day`` /
  ``emergency_pitches``), blocks a second emergency for two days and costs his
  next start a short-rest penalty;
* the emergency arm is the reserve furthest from his next turn and pitches
  under a relief ceiling; no outing moves his turn (owner decision 7, second
  fix round -- engine and tracker);
* the closer is not brought into a non-save game before the 9th just because
  he is the last arm standing;
* a forced change with a fully blocked pen has a last-resort tier, and an
  injured pitcher is always replaced when anyone is left;
* an outs-capped CL/SU at an inning start is a forced change;
* one rotation: the tracker, the default lineup builder and the harness staff
  builder pick the same five.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as eng
from physics_sim.config import load_tuning
from physics_sim.engine import (
    BaseState,
    LineupState,
    PitcherLine,
    PitcherState,
    TeamPitchingState,
    _build_team_pitching_state,
    _inning_start_hook,
    _maybe_pitcher_overuse_injury,
    _restore_emergency_clocks,
    _select_reliever,
)
from physics_sim.models import PitcherRatings
from physics_sim.usage import UsageState

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
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


def _reserve_staff(usage, day, roles):
    pids = list(roles)
    return _build_team_pitching_state(
        [_pr(pid) for pid in pids], tuning=load_tuning(), usage_state=usage,
        game_day=day, postseason=False, roles_by_id=roles,
    )


# ------------------------------------------------- 1. the emergency's trace
def _emergency_game(usage, day, pitches):
    """Play an emergency outing of ``pitches`` by reserve arm ``r`` on ``day``."""
    tuning = load_tuning()
    staff = _reserve_staff(usage, day, {"s": "SP1", "r": "SP2", "m": "MR"})
    reserve = next(p for p in staff.reserve if p.pitcher.player_id == "r")
    assert reserve.available
    reserve.used, reserve.pitches, reserve.emergency = True, pitches, True
    usage.record_outing(pitcher_id="r", pitches=pitches, day=day, multiplier=1.0,
                        tuning=tuning)
    _restore_emergency_clocks([staff], usage, tuning)
    return usage.workload_for("r")


def _started(usage, pid, day, pitches=92):
    wl = usage.workload_for(pid)
    wl.last_used_day, wl.last_pitches, wl.consecutive_days_used = day, pitches, 1
    wl.appearances += 1
    return wl


def test_a_short_emergency_keeps_his_turn_but_is_recorded():
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    wl = _emergency_game(usage, 10, 18)
    # The start clock is put back (owner decision Q6) ...
    assert (wl.last_used_day, wl.last_pitches) == (7, 92)
    # ... but the outing is on the record.
    assert (wl.emergency_day, wl.emergency_pitches) == (10, 18)


def test_a_long_emergency_keeps_his_turn_too():
    """Owner decision 7: the outing is relief however long it ran."""
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    wl = _emergency_game(usage, 10, 40)
    assert (wl.last_used_day, wl.last_pitches) == (7, 92)
    assert (wl.emergency_day, wl.emergency_pitches) == (10, 40)


def test_no_second_emergency_within_two_days():
    """Back-to-back emergencies: CAL-0043 threw 97 and then 83 relief pitches
    on consecutive days because the restored clock hid the first outing."""
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    _emergency_game(usage, 10, 18)
    for day, expected in ((11, False), (12, True)):
        staff = _reserve_staff(usage, day, {"s": "SP1", "r": "SP2", "m": "MR"})
        assert staff.reserve[0].available is expected, day


def test_the_next_start_sees_a_short_emergency():
    tuning = load_tuning()
    usage = UsageState(current_day=11, game_index=11)
    wl = _started(usage, "r", 7)
    wl.emergency_day, wl.emergency_pitches = 10, 20
    state = PitcherState(pitcher=_pr("r"), fatigue_start=60.0, fatigue_limit=90.0,
                         staff_role="SP", rest_role="SP2")
    eng._apply_usage_state(state, usage, 11, tuning)
    assert state.pregame_penalty > 0.0
    # Rested properly since the emergency: no penalty.
    rested = PitcherState(pitcher=_pr("r"), fatigue_start=60.0, fatigue_limit=90.0,
                          staff_role="SP", rest_role="SP2")
    eng._apply_usage_state(rested, usage, 14, tuning)
    assert rested.pregame_penalty == 0.0


# ------------------------------------- 2. which reserve arm, and his ceiling
def test_the_emergency_arm_is_the_one_furthest_from_his_next_turn():
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "next_up", 6)   # starts tomorrow
    _started(usage, "just_went", 8)  # started two days ago: four days to his turn
    _started(usage, "middle", 7)
    for pid in ("next_up", "just_went", "middle"):
        usage.workload_for(pid).fatigue_debt = 0.0
    staff = _reserve_staff(
        usage, 10,
        {"s": "SP1", "next_up": "SP2", "middle": "SP3", "just_went": "SP4", "m": "MR"},
    )
    staff.bullpen[0].used = True
    pick = _select_reliever(staff, "long", inning=12, score_diff=0,
                            tuning=load_tuning(), forced=True)
    assert pick.pitcher.player_id == "just_went"
    assert pick.emergency


def test_the_emergency_arm_pitches_under_a_relief_ceiling():
    tuning = load_tuning()
    usage = UsageState(current_day=10, game_index=10)
    _started(usage, "r", 7)
    staff = _reserve_staff(usage, 10, {"s": "SP1", "r": "SP2", "m": "MR"})
    reserve = staff.reserve[0]
    assert reserve.fatigue_limit <= tuning.get("emergency_max_pitches")
    assert reserve.fatigue_start < reserve.fatigue_limit
    # His pitch cap is a forced hook like anyone else's.
    reserve.pitches = int(reserve.fatigue_limit)
    line = PitcherLine(pitcher_id="r")
    line.outs, line.batters_faced = 6, 9
    reason = eng._hook_reason(pitcher_state=reserve, line=line, lineup_size=9,
                              score_diff=0, postseason=False, tuning=tuning)
    assert reason == "pitch_cap" and eng._forced_hook(reason, reserve, tuning)


def _calibration_staffs():
    staff = {}
    for team in ("CAL01", "CAL02"):
        path = CALIBRATION / "rosters" / f"{team}_pitching.csv"
        for row in path.read_text(encoding="utf-8").splitlines():
            pid, role = row.split(",")[:2]
            staff[pid.strip()] = role.strip()
    return staff


def _seeded_usage(day, spec):
    tuning = load_tuning()
    usage = UsageState()
    usage.advance_day(day=day, pitchers=[], tuning=tuning)
    usage.game_index = 100  # SP1 starts (100 % 5 == 0)
    for pid, role in _calibration_staffs().items():
        wl = usage.workload_for(pid)
        wl.last_update_day, wl.appearances = day, 20
        spec(wl, role)
    return usage


def _game(seed, usage, day):
    return eng.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=CALIBRATION / "players.csv",
        base_dir=CALIBRATION, seed=seed, usage_state=usage, game_day=day,
    )


def _pen_on_third_day(day, *, reserve_rested):
    def spec(wl, role):
        if role == "SP1":
            wl.last_used_day, wl.last_pitches = day - 5, 95
        elif role.startswith("SP"):
            k = int(role[2:])
            wl.last_used_day = day - k if reserve_rested else day - 1
            wl.last_pitches, wl.consecutive_days_used = 95, 1
            wl.fatigue_debt = 0.0 if reserve_rested else 60.0
        else:
            wl.last_used_day, wl.last_pitches, wl.consecutive_days_used = day - 1, 10, 2
            wl.fatigue_debt = 10.0
    return spec


@pytest.mark.parametrize("seed", range(8))
def test_emergency_outings_stop_at_their_ceiling(seed):
    """Emergency outings ran to 90-103 pitches with no relief ceiling.

    Second fix round: a club uses one emergency arm per game, so at his cap
    he stays on until the last-resort margin (then a hard-blocked reliever
    takes over) instead of handing the ball to a second starter.
    """
    day = 200
    usage = _seeded_usage(day, _pen_on_third_day(day, reserve_rested=True))
    result = _game(seed, usage, day)
    tuning = load_tuning()
    ceiling = (
        tuning.get("emergency_max_pitches") + tuning.get("bullpen_last_resort_margin")
    )
    for side in ("away", "home"):
        usage_rows = {u["player_id"]: u for u in result.metadata["pitcher_usage"][side]}
        emergencies = 0
        for line in result.metadata["pitcher_lines"][side]:
            if usage_rows[line["player_id"]]["emergency"]:
                emergencies += 1
                # The hook runs after each plate appearance: one PA of slack.
                assert line["pitches"] <= ceiling + 12, line
        assert emergencies <= 1, side


# ------------------------------- 3. the closer before the 9th, non-save game
def test_the_closer_is_not_the_answer_in_the_fifth():
    tuning = load_tuning({"mop_up": 0.0})
    team = _staff([
        _ps("cl", "CL"),
        _ps("mr", "MR", available=False, hard=True),
    ])
    kw = dict(inning=5, score_diff=0, tuning=tuning)
    # A soft hook keeps the pitcher in rather than burn the closer.
    assert _select_reliever(team, "long", **kw) is team.current
    # A forced change goes to the fallback, which has nobody: he stays too.
    assert _select_reliever(team, "long", forced=True, **kw) is team.current


def test_a_forced_change_in_the_sixth_takes_the_tired_arm_not_the_closer():
    tuning = load_tuning()
    team = _staff([_ps("cl", "CL"), _ps("mr", "MR", available=False, penalty=0.2)])
    pick = _select_reliever(team, "mid", inning=6, score_diff=-1, tuning=tuning,
                            forced=True)
    assert pick.pitcher.player_id == "mr" and pick.fallback


def test_the_closer_still_closes_a_save_in_the_ninth():
    tuning = load_tuning()
    team = _staff([_ps("cl", "CL"), _ps("mr", "MR", available=False, hard=True)])
    pick = _select_reliever(team, "high", inning=9, score_diff=1, tuning=tuning)
    assert pick.pitcher.player_id == "cl"


@pytest.mark.parametrize("seed", range(10))
def test_with_every_other_reliever_blocked_the_closer_waits(seed):
    """Branch probe: CL entries before the 7th were 9.2% of his outings
    (base 3.1%) because the cap and hard blocks left him the only arm.

    Second fix round: the one early entry left is the last resort -- the
    pitcher he relieves is ``bullpen_last_resort_margin`` past his limit (or
    hurt), and the rested closer comes before a third-straight-day arm.
    """
    day = 200
    usage = _seeded_usage(day, _pen_on_third_day(day, reserve_rested=False))
    closers = set()
    for pid, role in _calibration_staffs().items():
        if role == "CL":
            closers.add(pid)
            wl = usage.workload_for(pid)
            wl.last_used_day, wl.consecutive_days_used, wl.fatigue_debt = day - 4, 1, 0.0
    result = _game(seed, usage, day)
    margin = load_tuning().get("bullpen_last_resort_margin")
    rows, side_of = {}, {}
    for side in ("away", "home"):
        for row in result.metadata["pitcher_usage"][side]:
            rows[row["player_id"]] = row
            side_of[row["player_id"]] = side
    hurt = {e.get("pitcher_id") for e in result.metadata.get("injury_events") or []}
    first_inning, order = {}, []
    for entry in result.pitch_log:
        pid = entry.get("pitcher_id")
        if pid and "inning" in entry and pid not in first_inning:
            first_inning[pid] = int(entry["inning"])
            order.append(pid)
    for pid in closers:
        if pid in first_inning and first_inning[pid] < 7:
            mates = [p for p in order[: order.index(pid)] if side_of[p] == side_of[pid]]
            prev = rows[mates[-1]]
            # His final count: nobody he relieved came back in.
            spent = prev["pitches"] >= prev["fatigue_limit"] + margin
            assert spent or prev["player_id"] in hurt, (pid, first_inning[pid], prev)


# ------------------------------------------- 4. the last-resort tier
def _blocked_pen():
    return [
        _ps("cl", "CL", available=False, hard=True),
        _ps("worn", "MR", available=False, hard=True, penalty=0.4),
        _ps("fresh", "SU", available=False, hard=True, penalty=0.1),
    ]


def test_a_fully_blocked_pen_has_a_last_resort():
    tuning = load_tuning()
    margin = tuning.get("bullpen_last_resort_margin")
    starter = _ps("sp", "SP", used=True, limit=95.0, pitches=100)
    team = _staff(_blocked_pen(), current=starter)
    kw = dict(inning=6, score_diff=0, tuning=tuning, forced=True)
    # Not yet far enough past his limit: he stays in.
    assert _select_reliever(team, "mid", **kw) is starter
    starter.pitches = int(95 + margin)
    pick = _select_reliever(team, "mid", **kw)
    assert pick.pitcher.player_id == "fresh"
    # With every non-closer used, the closer is the very last resort.
    for state in team.bullpen:
        if state.pitcher.player_id != "cl":
            state.used = True
    assert _select_reliever(team, "mid", **kw).pitcher.player_id == "cl"


def test_a_soft_hook_never_reaches_the_last_resort():
    tuning = load_tuning()
    starter = _ps("sp", "SP", used=True, limit=95.0, pitches=200)
    team = _staff(_blocked_pen(), current=starter)
    assert _select_reliever(team, "mid", inning=6, score_diff=0, tuning=tuning) is starter


@pytest.mark.parametrize("seed", range(6))
def test_a_blocked_pen_cannot_leave_a_starter_in_forever(seed):
    """Edge probe: starters went 120+ in 283 of 300 such games, up to 261."""
    day = 200
    usage = _seeded_usage(day, _pen_on_third_day(day, reserve_rested=False))
    result = _game(seed, usage, day)
    for side in ("away", "home"):
        for line in result.metadata["pitcher_lines"][side]:
            assert line["pitches"] < 160, line


# --------------------------------- 5. outs-capped CL/SU at an inning start
def _inning_start(current, bullpen):
    tuning = load_tuning()
    team = _staff(bullpen, current=current)
    team.current = current
    current.used = True
    line = eng._line_for_pitcher(team, current, 9)
    line.outs, line.batters_faced = 3, 4
    current.pitches = 15
    _inning_start_hook(
        pitching_state=team, defense_state=LineupState(lineup=[], positions={}),
        offense_state=LineupState(lineup=[], positions={}), batter_index=0, inning=10,
        defense_score=3, offense_score=3, defense_team="home", bases=BaseState(),
        lineup_size=9, postseason=False, tuning=tuning,
    )
    return team


@pytest.mark.parametrize("role", ["CL", "SU"])
def test_an_outs_capped_late_arm_leaves_at_the_inning_start(role):
    current = _ps("late", role, limit=30.0)
    team = _inning_start(current, [_ps("mr", "MR", available=False, penalty=0.2)])
    assert team.current.pitcher.player_id == "mr"


def test_an_outs_capped_middle_man_is_still_a_soft_hook():
    current = _ps("mid", "MR", limit=40.0)
    team = _staff([_ps("mr2", "MR", available=False)], current=current)
    team.current = current
    current.used = True
    line = eng._line_for_pitcher(team, current, 7)
    line.outs, line.batters_faced = 4, 5
    _inning_start_hook(
        pitching_state=team, defense_state=LineupState(lineup=[], positions={}),
        offense_state=LineupState(lineup=[], positions={}), batter_index=0, inning=8,
        defense_score=3, offense_score=1, defense_team="home", bases=BaseState(),
        lineup_size=9, postseason=False, tuning=load_tuning(),
    )
    assert team.current is current


# ------------------------------------- 7. an injury with an empty pen
class _Injuries:
    def maybe_create_injury(self, trigger, pitcher, context=None, is_pitcher=False):
        return SimpleNamespace(severity="minor", days=10, dl_tier="dl15",
                               description="forearm tightness")


def _injure(team, monkeypatch):
    monkeypatch.setattr(eng.random, "random", lambda: 0.0)
    current = team.current
    current.pitches, current.last_penalty = 100, 1.0
    events = []
    hurt = _maybe_pitcher_overuse_injury(
        injury_sim=_Injuries(), injured_players=set(), injury_events=events,
        pitching_state=team, lineup_state=LineupState(lineup=[], positions={}),
        bases=BaseState(), inning=6, outs=1, score_diff=0, defense_score=2,
        offense_score=2, upcoming_batters=[], team="home", tuning=load_tuning(),
        postseason=False,
    )
    assert hurt
    return events[0]


def test_an_injured_pitcher_is_replaced_from_a_rest_flagged_pen(monkeypatch):
    team = _staff([_ps("cl", "CL", available=False),
                   _ps("mr", "MR", available=False, penalty=0.2)])
    event = _injure(team, monkeypatch)
    assert team.current.pitcher.player_id == "mr"
    assert event["replacement_id"] == "mr"


def test_an_injured_pitcher_is_replaced_even_from_a_blocked_pen(monkeypatch):
    team = _staff(_blocked_pen())
    event = _injure(team, monkeypatch)
    assert event["replacement_id"] == "fresh"
    assert team.current.pitcher.player_id == "fresh"


# ------------------------------------------ 6. one rotation, everywhere
def _sandbox_rosters(monkeypatch, tmp_path, players):
    """Keep the roster loader off the active league: its placeholder registry
    and pitcher-depth check read and write ``get_data_dir()`` otherwise."""
    from utils import roster_loader

    monkeypatch.setattr(roster_loader, "_placeholder_registry_path",
                        lambda: tmp_path / "_placeholder_registry.json")
    monkeypatch.setattr(roster_loader, "_PLACEHOLDER_PLAYERS_FILE", str(players))
    roster_loader.load_roster.cache_clear()


def _write_league(tmp_path, monkeypatch, *, staff_rows, act_ids, extra_players=()):
    players_src = CALIBRATION_LEAGUE / "players.csv"
    with players_src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    by_id = {row["player_id"]: row for row in rows}
    for new_id, clone_of, endurance in extra_players:
        row = dict(by_id[clone_of])
        row["player_id"], row["endurance"] = new_id, str(endurance)
        rows.append(row)
    players = tmp_path / "players.csv"
    with players.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    rosters = tmp_path / "rosters"
    rosters.mkdir(exist_ok=True)
    (rosters / "ALB.csv").write_text(
        "".join(f"{pid},ACT\n" for pid in act_ids), encoding="utf-8"
    )
    (rosters / "ALB_pitching.csv").write_text(
        "".join(f"{pid},{role}\n" for pid, role in staff_rows), encoding="utf-8"
    )
    _sandbox_rosters(monkeypatch, tmp_path, players)
    return players, rosters


def _alb_act():
    rows = (CALIBRATION_LEAGUE / "rosters" / "ALB.csv").read_text(encoding="utf-8")
    return [line.split(",")[0] for line in rows.splitlines() if line.endswith(",ACT")]


ALB_STAFF = [
    ("P8336", "SP1"), ("P1179", "SP2"), ("P4355", "SP3"), ("P9046", "SP4"),
    ("P1173", "SP5"), ("P6186", "LR"), ("P3083", "CL"), ("P1156", "SU"),
    ("P1195", "MR1"), ("P2088", "MR2"), ("P6912", "MR3"),
]


def _loader_rotation(players, rosters):
    from utils.lineup_loader import _default_pitchers
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster

    all_players = {p.player_id: p for p in load_players_from_csv(str(players))}
    roster = load_roster("ALB", rosters)
    pitchers = _default_pitchers("ALB", str(rosters), roster, all_players)
    labels = {p.player_id: p.assigned_pitching_role for p in pitchers}
    return sorted(
        (pid for pid, role in labels.items() if role.startswith("SP")),
        key=lambda pid: int(labels[pid][2:]),
    )


def _harness_rotation(players, rosters):
    from physics_sim.data_loader import load_players_by_id
    from physics_sim.team_data import PitcherAssignment, build_staff

    _, pitchers_by_id = load_players_by_id(players)
    assignments = [
        PitcherAssignment(*row.split(",")[:2])
        for row in (rosters / "ALB_pitching.csv").read_text().splitlines()
    ]
    act = {line.split(",")[0] for line in (rosters / "ALB.csv").read_text().splitlines()}
    _, roles, _ = build_staff(assignments, pitchers_by_id,
                              active_ids={pid for pid in act if pid in pitchers_by_id})
    return sorted(
        (pid for pid, role in roles.items() if role.startswith("SP")),
        key=lambda pid: int(roles[pid][2:]),
    )


def _tracker_rotation(tracker, players, rosters):
    return list(tracker._ensure_team("ALB", players, rosters)["rotation"])


def _assert_one_rotation(tmp_path, players, rosters, tracker=None):
    from utils.pitcher_recovery import PitcherRecoveryTracker

    tracker = tracker or PitcherRecoveryTracker(path=tmp_path / "recovery.json")
    rotation = _tracker_rotation(tracker, players, rosters)
    assert len(rotation) == 5
    assert _loader_rotation(players, rosters) == rotation
    assert _harness_rotation(players, rosters) == rotation
    return rotation


def test_one_rotation_with_the_owners_five(tmp_path, monkeypatch):
    players, rosters = _write_league(tmp_path, monkeypatch, staff_rows=ALB_STAFF, act_ids=_alb_act())
    rotation = _assert_one_rotation(tmp_path, players, rosters)
    assert rotation == ["P8336", "P1179", "P4355", "P9046", "P1173"]


def test_one_rotation_on_a_thin_staff_without_sp5(tmp_path, monkeypatch):
    """The reviewer's ALB case: SP5 gone, the file ordered SP1-4, CL, SU,
    MR1-3, LR. lineup_loader labelled the setup man (endurance 27) SP5 while
    the tracker started the long man (endurance 45)."""
    staff = [row for row in ALB_STAFF if row[1].startswith("SP") and row[1] != "SP5"]
    staff += [("P3083", "CL"), ("P1156", "SU"), ("P1195", "MR1"), ("P2088", "MR2"),
              ("P6912", "MR3"), ("P6186", "LR")]
    act = [pid for pid in _alb_act() if pid != "P1173"]
    players, rosters = _write_league(tmp_path, monkeypatch, staff_rows=staff, act_ids=act)
    rotation = _assert_one_rotation(tmp_path, players, rosters)
    assert rotation[-1] == "P6186"
    assert "P1156" not in rotation and "P3083" not in rotation


def test_one_rotation_when_a_stronger_starter_arrives(tmp_path, monkeypatch):
    """The tracker kept yesterday's backfill X while a stronger free starter Y
    was active; lineup_loader labelled Y SP5, so X started as an 'MR'."""
    from utils.pitcher_recovery import PitcherRecoveryTracker

    staff = [row for row in ALB_STAFF if row[1] != "SP5"]
    act = _alb_act()  # P1173 (endurance 44) is active, unlisted: the backfill
    players, rosters = _write_league(tmp_path, monkeypatch, staff_rows=staff, act_ids=act)
    tracker = PitcherRecoveryTracker(path=tmp_path / "recovery.json")
    assert _tracker_rotation(tracker, players, rosters)[-1] == "P1173"
    # A stronger free starter is called up for an unlisted reliever (the
    # active roster is full at 26). A fresh folder: the loaders cache by file.
    later = tmp_path / "later"
    later.mkdir()
    players, rosters = _write_league(
        later, monkeypatch, staff_rows=staff, act_ids=[pid for pid in act if pid != "P3017"] + ["PNEW"],
        extra_players=[("PNEW", "P1173", 52)],
    )
    rotation = _assert_one_rotation(tmp_path, players, rosters, tracker)
    assert rotation[-1] == "PNEW"


def test_the_live_role_map_follows_the_tracker_rotation():
    from playbalance.game_runner import _physics_pitcher_roles

    def arm(pid, assigned):
        return SimpleNamespace(player_id=pid, assigned_pitching_role=assigned, role="RP")

    state = SimpleNamespace(pitchers=[
        arm("a", "SP1"), arm("b", "SP2"), arm("x", "LR"), arm("c", "CL"),
    ])
    roles = _physics_pitcher_roles(state, rotation=["b", "x", "a"])
    assert roles == {"b": "SP1", "x": "SP2", "a": "SP3", "c": "CL"}


# ----------------------------------------------- tracker: kept turn or not
def _tracker_with_starter(tmp_path, monkeypatch):
    from utils.pitcher_recovery import PitcherRecoveryTracker

    rosters = tmp_path / "rosters"
    rosters.mkdir()
    for name in ("ALB.csv", "ALB_pitching.csv"):
        shutil.copy(CALIBRATION_LEAGUE / "rosters" / name, rosters / name)
    _sandbox_rosters(monkeypatch, tmp_path, CALIBRATION_LEAGUE / "players.csv")
    tracker = PitcherRecoveryTracker(path=tmp_path / "recovery.json")
    return tracker, CALIBRATION_LEAGUE / "players.csv", rosters


def _record(tracker, players, rosters, day, pitches, relief):
    from utils.pitcher_recovery import _parse_date

    player = SimpleNamespace(player_id="ZZ-SP", role="SP", assigned_pitching_role="SP3")
    tracker.record_game(
        "ALB", day,
        [SimpleNamespace(player=player, pitches_thrown=pitches, relief_outing=relief)],
        players, rosters,
    )
    return _parse_date(tracker.data["teams"]["ALB"]["pitchers"]["ZZ-SP"]["available_on"])


def test_tracker_a_long_emergency_keeps_his_turn(tmp_path, monkeypatch):
    tracker, players, rosters = _tracker_with_starter(tmp_path, monkeypatch)
    turn = _record(tracker, players, rosters, "2025-04-01", 95, False)
    assert _record(tracker, players, rosters, "2025-04-04", 40, True) == turn


def test_tracker_a_short_emergency_keeps_his_turn(tmp_path, monkeypatch):
    tracker, players, rosters = _tracker_with_starter(tmp_path, monkeypatch)
    turn = _record(tracker, players, rosters, "2025-04-01", 95, False)
    assert _record(tracker, players, rosters, "2025-04-03", 15, True) == turn
