"""Phase A multi-owner permission gates: season progression is commissioner-only
in owner leagues, and trade actions are ownership-enforced (closing the hole
where any authenticated user could accept any trade)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.routers.season as season
import api.routers.trades as trades


def _tr(from_team="AAA", to_team="BBB"):
    return SimpleNamespace(from_team=from_team, to_team=to_team)


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
