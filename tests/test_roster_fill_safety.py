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
    choose_send_down,
    is_pitcher,
    maintain_cpu_active_roster,
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


def test_the_last_healthy_catcher_is_never_optioned():
    players, roster = _team(14, 12, catchers=1)   # the catcher is the weakest hitter
    assert choose_send_down(roster, players) != "h0"


def test_a_second_catcher_can_go():
    players, roster = _team(14, 12, catchers=2)
    assert choose_send_down(roster, players) in {"h0", "h1"}


def test_send_down_follows_composition_not_the_returners_type():
    """Hitters at the floor: a pitcher goes, even if a hitter just returned."""
    players, roster = _team(HITTER_FLOOR, 14)
    victim = choose_send_down(roster, players)
    assert is_pitcher(players[victim])


def test_cpu_upkeep_calls_up_a_catcher_when_none_is_active():
    players, roster = _team(13, 12, catchers=0)
    players["aaa_c"] = _p("aaa_c", "C")
    roster.aaa.append("aaa_c")
    maintain_cpu_active_roster("CPU", roster, players, target_size=25, cap=25)
    assert "aaa_c" in roster.act


def test_cpu_trim_keeps_the_only_catcher():
    players, roster = _team(14, 12, catchers=1)
    maintain_cpu_active_roster("CPU", roster, players, target_size=25, cap=25)
    assert "h0" in roster.act and len(roster.act) == 25


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
