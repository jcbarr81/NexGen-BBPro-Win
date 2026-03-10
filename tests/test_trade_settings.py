import importlib
import json

import pytest


@pytest.fixture()
def trade_settings_module(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None

    import services.trade_settings as trade_settings

    importlib.reload(trade_settings)
    return trade_settings


def test_load_trade_settings_defaults(trade_settings_module):
    settings = trade_settings_module.load_trade_settings()
    assert settings.trades_enabled is True
    assert settings.draft_pick_trading_enabled is False
    assert settings.require_commissioner_approval is False
    assert settings.cpu_initiated_trades_enabled is True
    assert settings.cpu_proposal_cadence == "normal"
    assert settings.max_pick_trade_years == 3


def test_update_trade_settings_persists_and_clamps(trade_settings_module):
    trade_settings_module.update_trade_settings(
        trades_enabled=False,
        draft_pick_trading_enabled=True,
        require_commissioner_approval=True,
        cpu_initiated_trades_enabled=False,
        cpu_proposal_cadence="high",
        max_pick_trade_years=99,
    )
    settings = trade_settings_module.load_trade_settings()
    assert settings.trades_enabled is False
    assert settings.draft_pick_trading_enabled is True
    assert settings.require_commissioner_approval is True
    assert settings.cpu_initiated_trades_enabled is False
    assert settings.cpu_proposal_cadence == "high"
    assert settings.max_pick_trade_years == trade_settings_module.MAX_ALLOWED_PICK_TRADE_YEARS


def test_update_trade_settings_supports_explicit_path_and_league_id(
    trade_settings_module,
    tmp_path,
):
    settings_path = tmp_path / "custom" / "trade_settings.json"

    trade_settings_module.update_trade_settings(
        trades_enabled=False,
        draft_pick_trading_enabled=True,
        require_commissioner_approval=True,
        cpu_initiated_trades_enabled=False,
        cpu_proposal_cadence="off",
        max_pick_trade_years=4,
        path=settings_path,
        league_id="alpha",
    )
    settings = trade_settings_module.load_trade_settings(
        path=settings_path,
        league_id="alpha",
    )
    assert settings.league_id == "alpha"
    assert settings.trades_enabled is False
    assert settings.draft_pick_trading_enabled is True
    assert settings.require_commissioner_approval is True
    assert settings.cpu_initiated_trades_enabled is False
    assert settings.cpu_proposal_cadence == "off"
    assert settings.max_pick_trade_years == 4

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["leagues"]["alpha"]["trades_enabled"] is False
    assert payload["leagues"]["alpha"]["cpu_initiated_trades_enabled"] is False
    assert payload["leagues"]["alpha"]["cpu_proposal_cadence"] == "off"
