"""The roster API speaks the 26-man rules (decision 8, 7.46.0).

- /roster/compliance returns the caps in force on the sim date (26 / 13, or
  28 / 14 from Sept 1 in the regular season), the active pitcher / hitter
  counts and the organisation limit: the contract the Roster page reads.
- /roster/move and /roster/swap check against those same caps and return the
  validator's warnings plus the caps alongside the roster.
- The roster payload carries active_cap / pitcher_cap / act_pitchers /
  act_hitters / org_limit.
- Activating a pitcher onto a full pitching staff is a 409 act_pitchers_full.
- The sim gate (_team_roster_compliance_errors) blocks on the pitcher limit.

Everything runs against a tmp data dir; nothing touches data/leagues.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.routers.injuries as inj
import api.routers.roster as rr
import api.routers.season as season
import api.routers.validation as val
from models.roster import Roster
from utils.roster_rules import (
    AAA_CAP,
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    LOW_CAP,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
)

POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
AUGUST = "2026-08-15"
SEPT_1 = "2026-09-01"
ADMIN = {"u": "commish", "r": "admin", "t": ""}


def _hitter_row(pid, i):
    pos = POSITIONS[i] if i < len(POSITIONS) else "1B"
    return [pid, "First", pid, pos, "", "0", "2000-01-01"]


def _pitcher_row(pid):
    return [pid, "First", pid, "P", "", "1", "2000-01-01"]


@pytest.fixture
def league(tmp_path, monkeypatch):
    """A tmp league with one team "T" and a settable sim date.

    Returns ``build(hitters, pitchers, aaa_hitters=0, aaa_pitchers=0, date=…)``,
    which writes players.csv + rosters/T.csv and returns the Roster.
    """

    from playbalance import season_manager as sm

    class _Mgr:
        phase = sm.SeasonPhase.REGULAR_SEASON

    monkeypatch.setattr(sm, "SeasonManager", lambda *a, **k: _Mgr())
    monkeypatch.setattr(val, "get_data_dir", lambda: tmp_path)
    state = {"date": AUGUST}
    monkeypatch.setattr(
        "utils.sim_date.get_current_sim_date", lambda *a, **k: state["date"]
    )
    (tmp_path / "rosters").mkdir()

    def build(hitters, pitchers, aaa_hitters=0, aaa_pitchers=0, date=AUGUST):
        state["date"] = date
        rows = []
        roster = Roster(team_id="T")
        for i in range(hitters):
            rows.append(_hitter_row(f"H{i}", i))
            roster.act.append(f"H{i}")
        for i in range(pitchers):
            rows.append(_pitcher_row(f"P{i}"))
            roster.act.append(f"P{i}")
        for i in range(aaa_hitters):
            rows.append(_hitter_row(f"AH{i}", 1))
            roster.aaa.append(f"AH{i}")
        for i in range(aaa_pitchers):
            rows.append(_pitcher_row(f"AP{i}"))
            roster.aaa.append(f"AP{i}")
        header = (
            "player_id,first_name,last_name,primary_position,"
            "other_positions,is_pitcher,birthdate"
        )
        (tmp_path / "players.csv").write_text(
            "\n".join([header] + [",".join(r) for r in rows]) + "\n", encoding="utf-8"
        )
        lines = [f"{pid},ACT" for pid in roster.act] + [f"{pid},AAA" for pid in roster.aaa]
        (tmp_path / "rosters" / "T.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return roster

    return build


# --- compliance (the frozen contract) ------------------------------------------


def test_compliance_in_august_is_26_and_13(league):
    league(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS, date=AUGUST)
    out = val.roster_compliance_endpoint("T")
    assert out["ok"] is True, out["errors"]
    assert out["caps"] == {
        "act": ACTIVE_ROSTER_SIZE,
        "aaa": AAA_CAP,
        "low": LOW_CAP,
        "act_pitchers": MAX_ACTIVE_PITCHERS,
    }
    assert out["counts"] == {
        "act": ACTIVE_ROSTER_SIZE,
        "aaa": 0,
        "low": 0,
        "dl": 0,
        "ir": 0,
        "act_pitchers": MAX_ACTIVE_PITCHERS,
        "act_hitters": ACT_HITTER_TARGET,
    }
    assert out["org_limit"] == ORG_LIMIT


def test_compliance_on_sept_1_is_28_and_14(league):
    league(ACT_HITTER_TARGET, SEPTEMBER_MAX_ACTIVE_PITCHERS, date=SEPT_1)
    out = val.roster_compliance_endpoint("T")
    assert out["ok"] is True, out["errors"]
    assert out["caps"]["act"] == SEPTEMBER_ROSTER_SIZE
    assert out["caps"]["act_pitchers"] == SEPTEMBER_MAX_ACTIVE_PITCHERS
    assert out["counts"]["act_pitchers"] == SEPTEMBER_MAX_ACTIVE_PITCHERS


def test_compliance_errors_on_a_fourteenth_pitcher_in_august(league):
    league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS + 1, date=AUGUST)
    out = val.roster_compliance_endpoint("T")
    assert out["ok"] is False
    assert any("pitchers" in e for e in out["errors"])


def test_sim_gate_blocks_on_the_pitcher_limit(league):
    league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS + 1, date=AUGUST)
    errors = season._team_roster_compliance_errors("T")
    assert errors == [
        f"T: Active roster carries {MAX_ACTIVE_PITCHERS + 1} pitchers "
        f"(maximum {MAX_ACTIVE_PITCHERS})."
    ]
    # In September the same staff is legal.
    league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS + 1, date=SEPT_1)
    assert season._team_roster_compliance_errors("T") == []


def test_sim_gate_passes_a_25_man_roster(league):
    """No active-roster minimum: owners at 25 are not blocked on deploy."""
    league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS, date=AUGUST)
    assert season._team_roster_compliance_errors("T") == []


# --- move / swap responses --------------------------------------------------------


@pytest.fixture
def writes(monkeypatch):
    """Capture roster saves; keep transactions and the payload read local."""
    saved = {}
    monkeypatch.setattr(rr, "save_roster", lambda tid, r: saved.update(roster=r))
    monkeypatch.setattr(rr, "record_transaction", lambda **k: None)
    monkeypatch.setattr(rr, "team_roster", lambda tid: {"team_id": tid})
    return saved


def test_move_returns_the_pitcher_warning_and_caps(league, writes, monkeypatch):
    roster = league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS, aaa_pitchers=1)
    monkeypatch.setattr(rr, "load_roster", lambda tid: roster)
    out = rr.move_roster("T", payload={"player_id": "AP0", "to": "ACT"}, identity=ADMIN)
    assert "AP0" in writes["roster"].act  # a warning never blocks a move
    assert out["warnings"] == [
        f"ACT would carry {MAX_ACTIVE_PITCHERS + 1} pitchers "
        f"(max {MAX_ACTIVE_PITCHERS}) — send a pitcher down before the next game."
    ]
    assert out["caps"]["act_pitchers"] == MAX_ACTIVE_PITCHERS
    assert out["caps"]["act"] == ACTIVE_ROSTER_SIZE


def test_swap_in_september_at_27_active_passes(league, writes, monkeypatch):
    roster = league(ACT_HITTER_TARGET + 1, MAX_ACTIVE_PITCHERS, aaa_hitters=1, date=SEPT_1)
    assert len(roster.act) == ACTIVE_ROSTER_SIZE + 1
    monkeypatch.setattr(rr, "load_roster", lambda tid: roster)
    out = rr.swap_roster(
        "T", payload={"player_a_id": "AH0", "player_b_id": "H9"}, identity=ADMIN
    )
    assert out["warnings"] == []
    assert out["caps"]["act"] == SEPTEMBER_ROSTER_SIZE
    assert "AH0" in writes["roster"].act and "H9" in writes["roster"].aaa


def test_swap_that_adds_a_fourteenth_pitcher_is_rejected(league, writes, monkeypatch):
    roster = league(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS, aaa_pitchers=1)
    monkeypatch.setattr(rr, "load_roster", lambda tid: roster)
    with pytest.raises(HTTPException) as exc:
        rr.swap_roster(
            "T", payload={"player_a_id": "AP0", "player_b_id": "H9"}, identity=ADMIN
        )
    assert exc.value.status_code == 422
    assert any("pitchers" in e for e in exc.value.detail["errors"])
    assert "roster" not in writes  # nothing saved


def test_roster_payload_carries_the_limits(monkeypatch, league):
    league(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS)
    act = [f"H{i}" for i in range(ACT_HITTER_TARGET)] + [
        f"P{i}" for i in range(MAX_ACTIVE_PITCHERS)
    ]
    players = [
        SimpleNamespace(player_id=pid, is_pitcher=pid.startswith("P"),
                        primary_position="P" if pid.startswith("P") else "1B")
        for pid in act
    ]
    monkeypatch.setattr(rr, "load_roster", lambda tid: Roster(team_id="T", act=list(act)))
    monkeypatch.setattr(rr, "load_players_from_csv", lambda path: players)
    out = rr.team_roster("T")
    assert out["active_size"] == ACTIVE_ROSTER_SIZE
    assert out["active_cap"] == ACTIVE_ROSTER_SIZE
    assert out["pitcher_cap"] == MAX_ACTIVE_PITCHERS
    assert out["act_pitchers"] == MAX_ACTIVE_PITCHERS
    assert out["act_hitters"] == ACT_HITTER_TARGET
    assert out["org_limit"] == ORG_LIMIT


# --- injured-list activation -------------------------------------------------------


def _activation(monkeypatch, roster, player):
    calls = {}
    monkeypatch.setattr(inj, "_load_team", lambda tid: (roster, lambda *a: None))
    monkeypatch.setattr(inj, "_find_player", lambda pid: player)
    monkeypatch.setattr(
        inj, "recover_from_injury", lambda *a, **k: calls.setdefault("recovered", True)
    )
    monkeypatch.setattr(inj, "_persist", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.lineup_restore.restore_depth_chart_starter", lambda *a, **k: {}
    )
    return calls


def test_activating_a_pitcher_onto_a_full_staff_is_409(league, monkeypatch):
    roster = league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS)  # 25 active: room
    roster.dl.append("HURT_P")
    pitcher = SimpleNamespace(player_id="HURT_P", is_pitcher=True, primary_position="P")
    calls = _activation(monkeypatch, roster, pitcher)
    with pytest.raises(HTTPException) as exc:
        inj.activate_from_list("T", "HURT_P", payload={"destination": "act"}, identity=ADMIN)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "act_pitchers_full"
    assert f"max {MAX_ACTIVE_PITCHERS}" in exc.value.detail["message"]
    assert "recovered" not in calls


def test_activating_a_hitter_onto_a_full_staff_is_fine(league, monkeypatch):
    roster = league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS)
    roster.dl.append("HURT_H")
    hitter = SimpleNamespace(player_id="HURT_H", is_pitcher=False, primary_position="SS")
    calls = _activation(monkeypatch, roster, hitter)
    out = inj.activate_from_list("T", "HURT_H", payload={"destination": "act"}, identity=ADMIN)
    assert out["destination"] == "act" and calls["recovered"]


def test_september_activation_allows_the_fourteenth_arm(league, monkeypatch):
    roster = league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS, date=SEPT_1)
    roster.dl.append("HURT_P")
    pitcher = SimpleNamespace(player_id="HURT_P", is_pitcher=True, primary_position="P")
    calls = _activation(monkeypatch, roster, pitcher)
    inj.activate_from_list("T", "HURT_P", payload={"destination": "act"}, identity=ADMIN)
    assert calls["recovered"]


# --- free-agent signing: warnings only ------------------------------------------


def test_signing_a_pitcher_onto_a_full_staff_warns(league):
    import api.routers.free_agency as fa

    roster = league(ACT_HITTER_TARGET - 1, MAX_ACTIVE_PITCHERS, aaa_pitchers=1)
    roster.aaa.remove("AP0")  # AP0 is the free agent (in players.csv, on no roster)
    warnings, caps = fa._signing_roster_warnings(roster, "AP0", "ACT")
    assert warnings == [
        f"ACT would carry {MAX_ACTIVE_PITCHERS + 1} pitchers "
        f"(max {MAX_ACTIVE_PITCHERS}) — send a pitcher down before the next game."
    ]
    assert caps["act_pitchers"] == MAX_ACTIVE_PITCHERS
    # The same signing to AAA is quiet.
    assert fa._signing_roster_warnings(roster, "AP0", "AAA")[0] == []


def test_signing_past_the_organisation_limit_warns(league):
    import api.routers.free_agency as fa

    roster = league(ACT_HITTER_TARGET, MAX_ACTIVE_PITCHERS, aaa_hitters=1)
    roster.aaa.remove("AH0")
    roster.aaa.extend(f"X{i}" for i in range(AAA_CAP))
    roster.low.extend(f"Y{i}" for i in range(LOW_CAP))
    assert len(roster.act) + len(roster.aaa) + len(roster.low) == ORG_LIMIT
    warnings, _ = fa._signing_roster_warnings(roster, "AH0", "AAA")
    assert any(f"limit {ORG_LIMIT}" in w for w in warnings)


def test_signing_keeps_errors_and_skips_active_composition_for_the_minors(league):
    """A LOW signing past the age limit is reported (the sim gate would reject
    it later), and an active roster already short of hitters is not blamed on
    a minor-league signing."""
    import api.routers.free_agency as fa
    from services import roster_validation

    roster = league(roster_validation.MIN_POSITION_PLAYERS_ACT - 1, MAX_ACTIVE_PITCHERS, aaa_hitters=1)
    roster.aaa.remove("AH0")
    real_move = roster_validation.validate_roster_move

    def _with_age(**kw):
        kw["players"] = dict(kw["players"])
        kw["players"]["AH0"] = dict(kw["players"]["AH0"], age=31)
        return real_move(**kw)

    import pytest

    mp = pytest.MonkeyPatch()
    mp.setattr(roster_validation, "validate_roster_move", _with_age)
    try:
        warnings, _ = fa._signing_roster_warnings(roster, "AH0", "LOW")
    finally:
        mp.undo()
    assert any("LOW" in w and "age" in w for w in warnings), warnings
    assert not any("position player" in w for w in warnings), warnings
