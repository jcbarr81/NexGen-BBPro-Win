"""Release 3 (audit M15): a CPU club replaces an injured starter with a
starter-capable arm, not whichever pitcher ranks first in AAA."""

from __future__ import annotations

from types import SimpleNamespace

from models.roster import Roster
from services.depth_chart_manager import handle_injury_replacement
from services.roster_fill import callup_candidates


def _arm(pid: str, role: str) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        is_pitcher=True,
        primary_position="P",
        preferred_pitching_role=role,
        endurance=70 if role == "SP" else 30,
        injured=False,
    )


def _players():
    return {
        "SP_HURT": _arm("SP_HURT", "SP"),
        "RP_HURT": _arm("RP_HURT", "RP"),
        "AAA_RP": _arm("AAA_RP", "RP"),
        "AAA_SP": _arm("AAA_SP", "SP"),
        "LOW_SP": _arm("LOW_SP", "SP"),
    }


def _roster():
    return Roster(
        team_id="CPU", act=["X1", "X2"], aaa=["AAA_RP", "AAA_SP"], low=["LOW_SP"],
        dl=[], ir=[], dl_tiers={},
    )


def test_callup_order_unchanged_without_the_flag():
    order = callup_candidates(_roster(), _players(), want_pitcher=True)
    assert [pid for pid, _ in order] == ["AAA_RP", "AAA_SP", "LOW_SP"]


def test_starter_capable_arms_come_first_for_a_starter():
    order = callup_candidates(_roster(), _players(), want_pitcher=True, want_starter=True)
    assert [pid for pid, _ in order] == ["AAA_SP", "LOW_SP", "AAA_RP"]


def test_flag_is_ignored_for_hitters():
    players = _players()
    players["H1"] = SimpleNamespace(
        player_id="H1", is_pitcher=False, primary_position="CF", other_positions=[],
        injured=False,
    )
    roster = _roster()
    roster.aaa.append("H1")
    order = callup_candidates(roster, players, want_pitcher=False, want_starter=True)
    assert [pid for pid, _ in order] == ["H1"]


def _cpu_replacement(tmp_path, monkeypatch, injured_id: str, staff: str):
    rosters = tmp_path / "rosters"
    rosters.mkdir()
    (rosters / "CPU_pitching.csv").write_text(staff, encoding="utf-8")
    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda: tmp_path)
    players = _players()
    roster = _roster()
    return handle_injury_replacement(
        roster, players[injured_id], players_by_id=players, cpu_owned=True, chart={}
    ), roster


def test_cpu_club_replaces_an_injured_starter_with_a_starter(tmp_path, monkeypatch):
    coverage, roster = _cpu_replacement(
        tmp_path, monkeypatch, "SP_HURT", "SP_HURT,SP2\nRP_HURT,MR1\n"
    )
    assert coverage.promoted_id == "AAA_SP"
    assert "AAA_SP" in roster.act


def test_cpu_club_replaces_an_injured_reliever_as_before(tmp_path, monkeypatch):
    coverage, _ = _cpu_replacement(
        tmp_path, monkeypatch, "RP_HURT", "SP_HURT,SP2\nRP_HURT,MR1\n"
    )
    assert coverage.promoted_id == "AAA_RP"


def test_staff_file_slot_outranks_the_role_guess(tmp_path, monkeypatch):
    # A starter by rating who works out of the bullpen is replaced like a
    # reliever.
    coverage, _ = _cpu_replacement(tmp_path, monkeypatch, "SP_HURT", "SP_HURT,LR\n")
    assert coverage.promoted_id == "AAA_RP"
