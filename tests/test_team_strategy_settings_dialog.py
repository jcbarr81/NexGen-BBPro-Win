from __future__ import annotations


def test_import_team_strategy_settings_dialog_headless():
    from ui.team_strategy_settings_dialog import TeamStrategySettingsDialog  # noqa: F401

    assert TeamStrategySettingsDialog is not None
