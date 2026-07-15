"""S2-10: FastAPI-free trade commit extracted from the trades router."""
from __future__ import annotations

import pytest

from models.roster import Roster
from models.trade import Trade
from services.trade_execution import commit_trade
from utils.roster_loader import load_roster, save_roster


def test_commit_trade_parity_with_router(tmp_path, monkeypatch):
    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    save_roster("AAA", Roster("AAA", act=["a1", "a2", "a3"]), roster_dir=roster_dir)
    save_roster("BBB", Roster("BBB", act=["b1", "b2", "b3"]), roster_dir=roster_dir)

    recorded: list[dict] = []
    monkeypatch.setattr(
        "services.trade_execution.record_transaction",
        lambda **kwargs: recorded.append(kwargs),
    )

    commit_trade(
        Trade("t1", "AAA", "BBB", ["a1"], ["b1"]), data_dir=tmp_path
    )

    aaa = load_roster("AAA", roster_dir=roster_dir)
    bbb = load_roster("BBB", roster_dir=roster_dir)
    assert "b1" in aaa.act and "a1" not in aaa.act
    assert "a1" in bbb.act and "b1" not in bbb.act

    actions = [r["action"] for r in recorded]
    assert actions.count("trade_out") == 2
    assert actions.count("trade_in") == 2


def test_commit_trade_bad_pick_raises_valueerror(tmp_path, monkeypatch):
    roster_dir = tmp_path / "rosters"
    roster_dir.mkdir()
    save_roster("AAA", Roster("AAA", act=["a1"]), roster_dir=roster_dir)
    save_roster("BBB", Roster("BBB", act=["b1"]), roster_dir=roster_dir)

    def _raise(*_args, **_kwargs):
        raise ValueError("2099|1|ZZZ is owned by ZZZ, not AAA.")

    monkeypatch.setattr("services.trade_execution.transfer_pick", _raise)

    trade = Trade("t2", "AAA", "BBB", ["a1"], ["b1"], give_pick_ids=["2099|1|ZZZ"])
    with pytest.raises(ValueError):
        commit_trade(trade, data_dir=tmp_path)
