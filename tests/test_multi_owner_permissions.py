"""Phase A multi-owner permission gates: season progression is commissioner-only
in owner leagues, and trade actions are ownership-enforced (closing the hole
where any authenticated user could accept any trade)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.routers.season as season
import api.routers.trades as trades
from models.trade import Trade


def _tr(from_team="AAA", to_team="BBB"):
    return SimpleNamespace(from_team=from_team, to_team=to_team)


def _roster(*, act=(), aaa=(), low=(), dl=(), ir=()):
    return SimpleNamespace(
        act=list(act), aaa=list(aaa), low=list(low), dl=list(dl), ir=list(ir)
    )


# --- season progression gate ---

def test_progression_gate_allows_admin_blocks_owner(monkeypatch):
    monkeypatch.setattr(
        "utils.league_settings.can_run_season_progression",
        lambda role: role == "admin",
    )
    season._require_season_progression({"r": "admin"})  # commissioner: no raise
    with pytest.raises(HTTPException) as exc:
        season._require_season_progression({"r": "owner"})
    assert exc.value.status_code == 403


def test_progression_gate_solo_league_allows_everyone(monkeypatch):
    # Solo leagues: can_run_season_progression returns True for any role.
    monkeypatch.setattr(
        "utils.league_settings.can_run_season_progression", lambda role: True
    )
    season._require_season_progression({"r": "owner"})  # no raise


# --- trade admin gate ---

def test_require_admin(monkeypatch):
    trades._require_admin({"r": "admin"})  # no raise
    with pytest.raises(HTTPException) as exc:
        trades._require_admin({"r": "owner"})
    assert exc.value.status_code == 403


# --- trade party gate (reject: either side or commissioner) ---

def test_require_trade_party():
    tr = _tr("AAA", "BBB")
    trades._require_trade_party({"r": "admin", "t": ""}, tr)  # commissioner
    trades._require_trade_party({"r": "owner", "t": "AAA"}, tr)  # from side
    trades._require_trade_party({"r": "owner", "t": "BBB"}, tr)  # to side
    with pytest.raises(HTTPException) as exc:
        trades._require_trade_party({"r": "owner", "t": "CCC"}, tr)  # outsider
    assert exc.value.status_code == 403


# --- accept ownership: receiving (to_team) owner or admin ---

def test_accept_requires_receiving_owner(monkeypatch):
    tr = SimpleNamespace(
        trade_id="t1", from_team="AAA", to_team="BBB", status="pending"
    )
    monkeypatch.setattr(trades, "_find_trade", lambda tid: tr)
    monkeypatch.setattr(trades, "_commit_trade", lambda t: None)
    monkeypatch.setattr(trades, "save_trade", lambda t: None)

    # The FROM-team owner cannot accept their own proposal for the other side.
    with pytest.raises(HTTPException) as exc:
        trades.accept_trade("t1", identity={"r": "owner", "t": "AAA"})
    assert exc.value.status_code == 403

    # The receiving (to_team) owner can.
    out = trades.accept_trade("t1", identity={"r": "owner", "t": "BBB"})
    assert out["status"] == "accepted"


# --- readiness aggregation ---

def test_league_readiness_aggregates(monkeypatch):
    monkeypatch.setattr(season, "_human_team_ids", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(
        season, "_team_roster_compliance_errors",
        lambda t: ["BBB: over the ACT cap"] if t == "BBB" else [],
    )
    monkeypatch.setattr(season, "_team_lineup_issues", lambda t: [])
    monkeypatch.setattr(season, "_team_solvency_issues", lambda t: [])

    r = season._league_readiness()
    assert r["human_team_count"] == 2
    assert r["all_ready"] is False
    assert r["unready"] == ["BBB"]
    aaa = next(t for t in r["teams"] if t["team_id"] == "AAA")
    bbb = next(t for t in r["teams"] if t["team_id"] == "BBB")
    assert aaa["ready"] is True and bbb["ready"] is False
    assert bbb["issues"] == ["BBB: over the ACT cap"]


# --- trade reverse (commissioner undo of a committed trade) ---

def test_reverse_requires_admin():
    with pytest.raises(HTTPException) as exc:
        trades.reverse_trade("t1", payload={}, identity={"r": "owner", "t": "AAA"})
    assert exc.value.status_code == 403


def test_reverse_only_accepted(monkeypatch):
    tr = Trade(
        trade_id="t1", from_team="AAA", to_team="BBB",
        give_player_ids=["p1"], receive_player_ids=["p2"], status="pending",
    )
    monkeypatch.setattr(trades, "_find_trade", lambda tid: tr)
    with pytest.raises(HTTPException) as exc:
        trades.reverse_trade("t1", payload={}, identity={"r": "admin"})
    assert exc.value.status_code == 409


def test_reverse_blocks_when_asset_moved(monkeypatch):
    # p1 went AAA->BBB, p2 went BBB->AAA. But p1 is no longer on BBB.
    tr = Trade(
        trade_id="t1", from_team="AAA", to_team="BBB",
        give_player_ids=["p1"], receive_player_ids=["p2"], status="accepted",
    )
    monkeypatch.setattr(trades, "_find_trade", lambda tid: tr)
    rosters = {"AAA": _roster(act=["p2"]), "BBB": _roster(act=[])}
    monkeypatch.setattr(trades, "load_roster", lambda tid: rosters[tid])
    with pytest.raises(HTTPException) as exc:
        trades.reverse_trade("t1", payload={}, identity={"r": "admin"})
    assert exc.value.status_code == 409
    assert "blockers" in exc.value.detail


def test_reverse_success_flips_and_marks(monkeypatch):
    tr = Trade(
        trade_id="t1", from_team="AAA", to_team="BBB",
        give_player_ids=["p1"], receive_player_ids=["p2"], status="accepted",
    )
    monkeypatch.setattr(trades, "_find_trade", lambda tid: tr)
    # Assets in place: p1 on BBB (received it), p2 on AAA (received it).
    rosters = {"AAA": _roster(act=["p2"]), "BBB": _roster(act=["p1"])}
    monkeypatch.setattr(trades, "load_roster", lambda tid: rosters[tid])

    committed = {}
    monkeypatch.setattr(
        trades, "_commit_trade",
        lambda t: committed.update(from_team=t.from_team, to_team=t.to_team),
    )
    monkeypatch.setattr(trades, "save_trade", lambda t: None)
    monkeypatch.setattr(trades, "_persist_reversal", lambda tid, rec: None)

    out = trades.reverse_trade(
        "t1", payload={"note": "lopsided"}, identity={"r": "admin", "u": "boss"}
    )
    assert out["status"] == "reversed"
    assert tr.status == "reversed"
    # The mirror trade swaps proposing/receiving teams.
    assert committed == {"from_team": "BBB", "to_team": "AAA"}


# --- per-owner action-items feed (Phase E) ---

def test_action_items_team_none(monkeypatch):
    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    out = season.season_action_items(identity={"r": "admin", "t": ""})
    assert out["team_id"] is None
    assert out["items"] == [] and out["count"] == 0


def test_action_items_flags_incoming_trade(monkeypatch):
    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    monkeypatch.setattr(
        season, "SeasonManager",
        lambda: SimpleNamespace(phase=SimpleNamespace(value="REGULAR_SEASON")),
    )
    monkeypatch.setattr("services.fa_window.window_status", lambda: {"status": None})
    pend = Trade(
        trade_id="t1", from_team="BBB", to_team="AAA",
        give_player_ids=["p1"], receive_player_ids=["p2"], status="pending",
    )
    other = Trade(
        trade_id="t2", from_team="AAA", to_team="CCC",
        give_player_ids=["p3"], receive_player_ids=["p4"], status="pending",
    )
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [pend, other])

    out = season.season_action_items(identity={"r": "owner", "t": "AAA"})
    kinds = [i["kind"] for i in out["items"]]
    assert "trade_offer" in kinds
    offer = next(i for i in out["items"] if i["kind"] == "trade_offer")
    assert offer["count"] == 1 and offer["href"] == "/trades"


def test_action_items_fa_waiting(monkeypatch):
    monkeypatch.setattr(season, "_read_season_deadline", lambda: "2026-03-01")
    monkeypatch.setattr(
        season, "SeasonManager",
        lambda: SimpleNamespace(phase=SimpleNamespace(value="OFFSEASON")),
    )
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [])
    monkeypatch.setattr(
        "services.fa_window.window_status",
        lambda: {"status": "open", "day": 3, "total_days": 14, "waiting": ["AAA"]},
    )
    out = season.season_action_items(identity={"r": "owner", "t": "AAA"})
    assert any(i["kind"] == "fa_bid_needed" for i in out["items"])
    assert out["deadline"] == "2026-03-01"


def test_league_readiness_all_ready(monkeypatch):
    monkeypatch.setattr(season, "_human_team_ids", lambda: ["AAA"])
    monkeypatch.setattr(season, "_team_roster_compliance_errors", lambda t: [])
    monkeypatch.setattr(season, "_team_lineup_issues", lambda t: [])
    monkeypatch.setattr(season, "_team_solvency_issues", lambda t: [])
    r = season._league_readiness()
    assert r["all_ready"] is True and r["unready"] == []
