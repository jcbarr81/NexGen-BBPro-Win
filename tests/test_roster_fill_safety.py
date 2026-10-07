"""Safety rails on automatic roster moves (audit H9 hotfix, review round 3).

* never option a club's last healthy catcher, and a CPU club with no active
  catcher calls one up;
* send-downs follow the roster's composition, not the returner's type;
* ownership that can't be read means "unknown" -- no CPU-only automation;
* one pitcher tracker per league, with its retry markers saved to disk;
* an emergency option is not labelled an "emergency call-up".
"""

from types import SimpleNamespace

import pytest

from models.roster import Roster
from services.roster_fill import (
    HITTER_FLOOR,
    ForcedMove,
    choose_send_down,
    is_pitcher,
    maintain_cpu_active_roster,
)
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
)


def _p(pid, pos, score=50, injured=False):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=[], injured=injured,
        is_pitcher=(pos == "P"), ch=score, ph=score, first_name=pid, last_name="",
    )


def _team(n_hitters, n_pitchers, catchers=1):
    players = {}
    act = []
    for i in range(n_hitters):
        pos = "C" if i < catchers else "LF"
        players[f"h{i}"] = _p(f"h{i}", pos, score=40 if pos == "C" else 60)
        act.append(f"h{i}")
    for i in range(n_pitchers):
        players[f"p{i}"] = _p(f"p{i}", "P", score=55)
        act.append(f"p{i}")
    return players, Roster("CPU", act=act)


# A full roster with one hitter too many: 14 hitters / 12 pitchers today.
_HITTER_HEAVY = (ACT_HITTER_TARGET + 1, ACTIVE_ROSTER_SIZE - ACT_HITTER_TARGET - 1)


def test_the_last_healthy_catcher_is_never_optioned():
    players, roster = _team(*_HITTER_HEAVY, catchers=1)   # the catcher is the weakest hitter
    assert choose_send_down(roster, players) != "h0"


def test_a_second_catcher_stays_while_another_hitter_can_go():
    """Release 3 (decision 10): CPU clubs carry two catchers, so the weaker
    catcher is kept while any other position player may go down."""
    players, roster = _team(*_HITTER_HEAVY, catchers=2)
    assert choose_send_down(roster, players) not in {"h0", "h1"}


def test_a_second_catcher_can_go_when_nobody_else_may():
    players, roster = _team(*_HITTER_HEAVY, catchers=2)
    only_catchers = choose_send_down(roster, players, allowed=lambda pid: pid in {"h0", "h1"})
    assert only_catchers in {"h0", "h1"}
    assert choose_send_down(roster, players, keep_catchers=1) in {"h0", "h1"}


def test_send_down_follows_composition_not_the_returners_type():
    """Hitters at the floor: a pitcher goes, even if a hitter just returned."""
    players, roster = _team(HITTER_FLOOR, MAX_ACTIVE_PITCHERS + 1)
    victim = choose_send_down(roster, players)
    assert is_pitcher(players[victim])


def test_a_returning_pitcher_on_a_full_staff_sends_a_pitcher_down():
    """13 hitters / 13 pitchers plus a pitcher back from the IL (his
    replacement gone): counting the returner, the staff is the surplus."""
    players, roster = _team(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS)
    players["back"] = _p("back", "P", score=10)
    roster.act.append("back")
    victim = choose_send_down(roster, players, exclude={"back"})
    assert victim != "back" and is_pitcher(players[victim])


def test_a_returning_hitter_on_a_full_roster_sends_a_hitter_down():
    players, roster = _team(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS)
    players["back"] = _p("back", "LF", score=10)
    roster.act.append("back")
    victim = choose_send_down(roster, players, exclude={"back"})
    assert victim != "back" and not is_pitcher(players[victim])


def test_september_staff_of_14_is_within_the_limit():
    hitters = SEPTEMBER_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS + 1
    players, roster = _team(hitters, SEPTEMBER_MAX_ACTIVE_PITCHERS)
    victim = choose_send_down(roster, players, pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS)
    assert not is_pitcher(players[victim])


def test_cpu_upkeep_calls_up_a_catcher_when_none_is_active():
    players, roster = _team(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS - 1, catchers=0)
    players["aaa_c"] = _p("aaa_c", "C")
    roster.aaa.append("aaa_c")
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE
    )
    assert "aaa_c" in roster.act


def test_cpu_trim_keeps_the_only_catcher():
    players, roster = _team(*_HITTER_HEAVY, catchers=1)
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE
    )
    assert "h0" in roster.act and len(roster.act) == ACTIVE_ROSTER_SIZE


# --- the 26-man shape (decision 8): 13 pitchers / 13 hitters ----------------


def _counts(roster, players):
    arms = sum(is_pitcher(players[p]) for p in roster.act)
    return arms, len(roster.act) - arms


def _with_minors(players, roster, *, arms=0, bats=0, score=50):
    for i in range(arms):
        players[f"ap{i}"] = _p(f"ap{i}", "P", score=score + i)
        roster.aaa.append(f"ap{i}")
    for i in range(bats):
        players[f"ah{i}"] = _p(f"ah{i}", "CF", score=score + i)
        roster.aaa.append(f"ah{i}")


def test_a_creator_built_cpu_roster_converges_to_13_and_13():
    """The creator's 25-man shape (11 pitchers / 14 hitters) stopped at
    12/14 under the old upkeep."""
    arms = MAX_ACTIVE_PITCHERS - 2
    players, roster = _team(ACTIVE_ROSTER_SIZE - 1 - arms, arms, catchers=2)
    _with_minors(players, roster, arms=4, bats=2)
    # A better free agent pitcher is never signed: own organisation only.
    players["fa_ace"] = _p("fa_ace", "P", score=99)
    before_org = set(roster.act + roster.aaa + roster.low)
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE
    )
    assert _counts(roster, players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)
    assert len(roster.act) == ACTIVE_ROSTER_SIZE
    assert set(roster.act + roster.aaa + roster.low) == before_org
    assert {"h0", "h1"} & set(roster.act)        # a catcher is kept


def test_a_pitcher_heavy_cpu_roster_is_trimmed_to_the_limit():
    hitters = ACT_HITTER_TARGET - 1
    players, roster = _team(hitters, ACTIVE_ROSTER_SIZE - hitters)   # 12 / 14
    _with_minors(players, roster, bats=1)
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE
    )
    assert _counts(roster, players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)


def test_upkeep_leaves_the_roster_short_rather_than_add_a_14th_pitcher():
    hitters = ACT_HITTER_TARGET - 3
    players, roster = _team(hitters, MAX_ACTIVE_PITCHERS)
    _with_minors(players, roster, arms=5)          # no hitters left in the minors
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE
    )
    assert _counts(roster, players) == (MAX_ACTIVE_PITCHERS, hitters)


def test_september_upkeep_allows_14_pitchers_but_never_rebalances_past_13():
    hitters = SEPTEMBER_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS
    players, roster = _team(hitters, SEPTEMBER_MAX_ACTIVE_PITCHERS)   # 14 / 14
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=SEPTEMBER_ROSTER_SIZE
    )
    assert _counts(roster, players) == (SEPTEMBER_MAX_ACTIVE_PITCHERS, hitters)
    # 15 / 13 (a September call-up of a bat) is not swapped for an arm.
    players, roster = _team(hitters + 1, MAX_ACTIVE_PITCHERS)
    _with_minors(players, roster, arms=3)
    maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=SEPTEMBER_ROSTER_SIZE
    )
    assert _counts(roster, players) == (MAX_ACTIVE_PITCHERS, hitters + 1)


def test_an_out_of_options_surplus_pitcher_is_forced_and_labelled(monkeypatch):
    hitters = ACT_HITTER_TARGET - 1
    players, roster = _team(hitters, ACTIVE_ROSTER_SIZE - hitters)
    moves = maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE,
        option_allowed=lambda pid: False,
    )
    forced = [m for m in moves if isinstance(m, ForcedMove)]
    assert len(forced) == 1 and forced[0][1:] == ("act", "aaa")
    assert _counts(roster, players)[0] == MAX_ACTIVE_PITCHERS

    import services.roster_fill as rf

    logged = []
    monkeypatch.setattr(
        "services.transaction_log.record_transaction", lambda **k: logged.append(k)
    )
    rf.record_roster_moves("CPU", moves, players, details="CPU roster upkeep")
    assert "option limit" in logged[0]["details"]


def test_an_optionable_pitcher_goes_before_a_forced_one():
    hitters = ACT_HITTER_TARGET - 1
    players, roster = _team(hitters, ACTIVE_ROSTER_SIZE - hitters)
    moves = maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE,
        option_allowed=lambda pid: pid == "p3",
    )
    assert ("p3", "act", "aaa") in moves
    assert not any(isinstance(m, ForcedMove) for m in moves)


# --- ownership --------------------------------------------------------------


def test_unreadable_users_file_means_ownership_unknown(tmp_path, monkeypatch):
    from services import team_ownership

    (tmp_path / "users.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr("utils.user_manager.load_users", lambda path: (_ for _ in ()).throw(OSError("busy")))
    assert team_ownership.human_owned_team_ids_strict(tmp_path) is None
    # the lenient reader still guesses "nobody" -- which is why it isn't used
    assert team_ownership.human_owned_team_ids(tmp_path) == set()


def test_injury_path_treats_unknown_ownership_as_an_owner(monkeypatch):
    from services import injury_manager

    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None)
    assert injury_manager._team_is_cpu("SEA") is False


# --- pitcher tracker: per league, markers persisted --------------------------


@pytest.fixture
def two_leagues(tmp_path, monkeypatch):
    import utils.pitcher_recovery as pr

    current = {"dir": tmp_path / "a"}
    monkeypatch.setattr(pr, "_resolve_path", lambda p: current["dir"] / "pitcher_recovery.json")
    monkeypatch.setattr(pr.PitcherRecoveryTracker, "_instance", None)
    monkeypatch.setattr(pr.PitcherRecoveryTracker, "_instances", {})
    return pr, current, tmp_path


def test_each_league_gets_its_own_tracker(two_leagues):
    pr, current, root = two_leagues
    a = pr.PitcherRecoveryTracker.instance()
    current["dir"] = root / "b"
    b = pr.PitcherRecoveryTracker.instance()
    assert a is not b and a.path != b.path
    current["dir"] = root / "a"
    assert pr.PitcherRecoveryTracker.instance() is a


def test_retry_markers_survive_a_restart(two_leagues):
    pr, current, root = two_leagues
    t = pr.PitcherRecoveryTracker.instance()
    t.data["teams"] = {"SEA": {"rotation": ["s1", "s2"], "next_index": 1, "pitchers": {},
                               "assigned_date": "2026-05-01", "assigned_pid": "s1"}}
    t.data["last_recovery_date"] = "2026-05-01"
    t.save()
    fresh = pr.PitcherRecoveryTracker()          # a new process
    assert fresh.data.get("last_recovery_date") == "2026-05-01"
    assert fresh.data["teams"]["SEA"]["assigned_pid"] == "s1"


# --- labels -----------------------------------------------------------------


def test_emergency_options_are_not_labelled_call_ups(monkeypatch):
    import services.roster_fill as rf

    calls = []
    monkeypatch.setattr(rf, "record_emergency_callups", lambda t, m, p: calls.append(("up", list(m))))
    monkeypatch.setattr(rf, "record_roster_moves", lambda t, m, p, details, news=False: calls.append((details, list(m))))
    rf.record_emergency_moves("CPU", [("m1", "aaa", "act"), ("p0", "act", "aaa")], {})
    assert ("up", [("m1", "aaa", "act")]) in calls
    assert ("Optioned to make room for an emergency call-up", [("p0", "act", "aaa")]) in calls
