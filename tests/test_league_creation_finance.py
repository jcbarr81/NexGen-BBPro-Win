from __future__ import annotations

from tests.qt_stubs import patch_qt

patch_qt()

from services.finance_settings import PRESET_CUSTOM, load_financial_settings
from services.league_creation_finance import (
    apply_initial_finance_settings,
    finance_summary_lines,
)
from ui.league_creation_finance_dialog import LeagueCreationFinanceDialog


def test_import_league_creation_finance_dialog_headless():
    assert LeagueCreationFinanceDialog is not None


def test_finance_summary_lines_for_custom_config():
    lines = finance_summary_lines(
        {
            "preset": "custom",
            "enabled": True,
            "enforcement_mode": "block",
            "modules": {
                "owner_budgets": "advanced",
                "gm_contracts": "basic",
                "gm_payroll_rules": "mlb_like",
                "gm_arbitration": "advanced",
                "gm_free_agency": "basic",
                "gm_roster_cost_enforcement": "warn",
            },
        }
    )

    assert "Finance preset: custom" in lines
    assert "Finance enabled: Yes" in lines
    assert "Enforcement mode: block" in lines
    assert "gm_payroll_rules: mlb_like" in lines


def test_apply_initial_finance_settings_applies_preset(tmp_path):
    apply_initial_finance_settings(
        {"preset": "standard", "enabled": True, "enforcement_mode": "warn", "modules": {}},
        data_dir=tmp_path,
        league_id="alpha",
    )

    settings = load_financial_settings(path=tmp_path / "league_financial_settings.json", league_id="alpha")
    assert settings.enabled is True
    assert settings.preset == "standard"
    assert settings.module_level("owner_budgets") == "advanced"


def test_apply_initial_finance_settings_applies_custom_modules(tmp_path):
    apply_initial_finance_settings(
        {
            "preset": PRESET_CUSTOM,
            "enabled": True,
            "enforcement_mode": "block",
            "modules": {
                "owner_budgets": "basic",
                "gm_contracts": "advanced",
                "gm_payroll_rules": "mlb_like",
                "gm_arbitration": "off",
                "gm_free_agency": "advanced",
                "gm_roster_cost_enforcement": "block",
            },
        },
        data_dir=tmp_path,
        league_id="beta",
    )

    settings = load_financial_settings(path=tmp_path / "league_financial_settings.json", league_id="beta")
    assert settings.preset == PRESET_CUSTOM
    assert settings.enabled is True
    assert settings.enforcement_mode == "block"
    assert settings.module_level("owner_budgets") == "basic"
    assert settings.module_level("gm_payroll_rules") == "mlb_like"
    assert settings.module_level("gm_roster_cost_enforcement") == "block"
