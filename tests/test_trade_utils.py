import tempfile
import random
from datetime import timedelta
from types import SimpleNamespace

import pytest

from models.trade import Trade
from utils.trade_utils import get_pending_trades, load_trades, save_trade
from playbalance.season_manager import TRADE_DEADLINE

# Reseed RNG so earlier tests that modify random state don't influence later ones
random.seed()


def test_save_trade_updates_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE - timedelta(days=1)
    )
    path = tmp_path / "trades.csv"
    t = Trade("1", "A", "B", ["p1"], ["p2"])
    save_trade(t, str(path))
    trades = load_trades(str(path))
    assert len(trades) == 1
    assert trades[0].status == "pending"

    t.status = "accepted"
    save_trade(t, str(path))
    trades = load_trades(str(path))
    assert len(trades) == 1
    assert trades[0].status == "accepted"


def test_get_pending_trades(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE - timedelta(days=1)
    )
    path = tmp_path / "trades.csv"
    save_trade(Trade("1", "A", "B", ["p1"], ["p2"]), str(path))
    save_trade(Trade("2", "C", "A", ["p3"], ["p4"]), str(path))
    save_trade(Trade("4", "E", "A", ["p7"], ["p8"], status="owner_accepted"), str(path))
    save_trade(Trade("3", "D", "A", ["p5"], ["p6"], status="accepted"), str(path))
    pending = get_pending_trades("A", str(path))
    assert len(pending) == 1
    assert pending[0].trade_id == "2"


def test_trade_blocked_after_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE + timedelta(days=1)
    )
    path = tmp_path / "trades.csv"
    t = Trade("1", "A", "B", ["p1"], ["p2"])
    with pytest.raises(RuntimeError):
        save_trade(t, str(path))


def test_trade_blocked_when_trading_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE - timedelta(days=1)
    )
    monkeypatch.setattr(
        "utils.trade_utils.load_trade_settings",
        lambda: SimpleNamespace(
            trades_enabled=False,
            draft_pick_trading_enabled=False,
            max_pick_trade_years=3,
        ),
    )
    path = tmp_path / "trades.csv"
    with pytest.raises(RuntimeError, match="disabled"):
        save_trade(Trade("1", "A", "B", ["p1"], ["p2"]), str(path))


def test_trade_pick_window_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE - timedelta(days=1)
    )
    monkeypatch.setattr(
        "utils.trade_utils.load_trade_settings",
        lambda: SimpleNamespace(
            trades_enabled=True,
            draft_pick_trading_enabled=True,
            max_pick_trade_years=2,
        ),
    )
    monkeypatch.setattr("utils.trade_utils.current_league_year", lambda: 2026)
    monkeypatch.setattr(
        "utils.trade_utils.get_pick_owner",
        lambda _year, _round_no, original_team: original_team,
    )

    path = tmp_path / "trades.csv"
    trade = Trade(
        "1",
        "A",
        "B",
        ["p1"],
        ["p2"],
        give_pick_ids=["2030|1|A"],
    )
    with pytest.raises(RuntimeError, match="outside the allowed trade window"):
        save_trade(trade, str(path))


def test_trade_pick_ownership_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE - timedelta(days=1)
    )
    monkeypatch.setattr(
        "utils.trade_utils.load_trade_settings",
        lambda: SimpleNamespace(
            trades_enabled=True,
            draft_pick_trading_enabled=True,
            max_pick_trade_years=3,
        ),
    )
    monkeypatch.setattr("utils.trade_utils.current_league_year", lambda: 2026)

    def _owner(year, round_no, original_team):
        if original_team == "A":
            return "C"
        return "B"

    monkeypatch.setattr("utils.trade_utils.get_pick_owner", _owner)

    path = tmp_path / "trades.csv"
    trade = Trade(
        "1",
        "A",
        "B",
        ["p1"],
        ["p2"],
        give_pick_ids=["2027|1|A"],
    )
    with pytest.raises(RuntimeError, match="owned by C"):
        save_trade(trade, str(path))


def test_trade_roundtrip_preserves_pick_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "utils.trade_utils._today", lambda: TRADE_DEADLINE - timedelta(days=1)
    )
    monkeypatch.setattr(
        "utils.trade_utils.load_trade_settings",
        lambda: SimpleNamespace(
            trades_enabled=True,
            draft_pick_trading_enabled=True,
            max_pick_trade_years=4,
        ),
    )
    monkeypatch.setattr("utils.trade_utils.current_league_year", lambda: 2026)
    monkeypatch.setattr(
        "utils.trade_utils.get_pick_owner",
        lambda _year, _round_no, original_team: original_team,
    )

    path = tmp_path / "trades.csv"
    trade = Trade(
        "1",
        "A",
        "B",
        ["p1"],
        ["p2"],
        give_pick_ids=["2027|1|A"],
        receive_pick_ids=["2027|2|B"],
    )
    save_trade(trade, str(path))
    loaded = load_trades(str(path))
    assert loaded[0].give_pick_ids == ["2027|1|A"]
    assert loaded[0].receive_pick_ids == ["2027|2|B"]
