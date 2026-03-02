from __future__ import annotations

from services.finance_settings import PRESET_CUSTOM

def test_import_financial_settings_dialog_headless():
    from ui.financial_settings_dialog import FinancialSettingsDialog  # noqa: F401

    assert FinancialSettingsDialog is not None


def test_financial_settings_dialog_formats_alert_preview():
    from ui.financial_settings_dialog import FinancialSettingsDialog

    text = FinancialSettingsDialog._format_alert_preview(
        [
            {
                "severity": "critical",
                "title": "AAA: Payroll Over Threshold",
                "message": "Payroll exceeds threshold.",
                "next_step": "Move salary.",
            }
        ]
    )

    assert "Prioritized Alerts" in text
    assert "[CRITICAL] AAA: Payroll Over Threshold" in text
    assert "Next: Move salary." in text


def test_financial_settings_dialog_formats_workflow_preview():
    from ui.financial_settings_dialog import FinancialSettingsDialog

    text = FinancialSettingsDialog._format_workflow_preview(
        {
            "offseason": {
                "phase": "OFFSEASON",
                "next_stage_label": "Review Contract Expirations",
                "requires_commissioner_finance_review": True,
            }
        }
    )

    assert "Saved Settings Workflow" in text
    assert "Current phase: OFFSEASON" in text
    assert "Review Contract Expirations" in text


def test_financial_settings_dialog_summarizes_module_levels():
    from ui.financial_settings_dialog import FinancialSettingsDialog

    modules = {
        "owner_revenue": "basic",
        "owner_market_model": "off",
        "owner_budgets": "off",
        "owner_expenses": "off",
        "gm_contracts": "advanced",
        "gm_payroll_rules": "mlb_like",
        "gm_arbitration": "off",
        "gm_free_agency": "off",
        "gm_roster_cost_enforcement": "block",
        "gm_finance_ai": "off",
    }
    text = FinancialSettingsDialog._summarize_module_levels(modules)

    assert "Module coverage: 4/10 enabled" in text
    assert "Basic: 1" in text
    assert "Advanced/MLB-Like: 2" in text
    assert "Enforcement Block: 1" in text


def test_preset_changed_custom_enables_finance_controls():
    from ui.financial_settings_dialog import FinancialSettingsDialog

    class _FakeCheckBox:
        def __init__(self) -> None:
            self._checked = False

        def isChecked(self) -> bool:
            return self._checked

        def setChecked(self, value: bool) -> None:
            self._checked = bool(value)

    dialog = FinancialSettingsDialog.__new__(FinancialSettingsDialog)
    dialog._updating = False
    dialog.enabled_checkbox = _FakeCheckBox()
    dialog._preset_value = lambda: PRESET_CUSTOM
    dialog._apply_preset_to_controls = lambda _preset: None
    dialog._sync_enabled_state = lambda: None
    dialog._refresh_mode_guidance = lambda: None

    dialog._on_preset_changed()

    assert dialog.enabled_checkbox.isChecked() is True


def test_financial_settings_dialog_collects_and_clamps_scouting_tuning():
    from ui.financial_settings_dialog import FinancialSettingsDialog

    class _FakeField:
        def __init__(self, value: str) -> None:
            self._value = value

        def text(self) -> str:
            return self._value

    dialog = FinancialSettingsDialog.__new__(FinancialSettingsDialog)
    dialog._scouting_tuning_inputs = {
        "base_monthly_credits": _FakeField("1200"),
        "finance_off_multiplier": _FakeField("9.0"),
        "monthly_decay": _FakeField("-1"),
        "passive_gain": _FakeField("0.015"),
        "max_banked_credits": _FakeField("20"),
        "auto_spend_cap": _FakeField("bad"),
    }

    values = dialog._collect_scouting_tuning()

    assert values["base_monthly_credits"] == 1200.0
    assert values["finance_off_multiplier"] == 1.5
    assert values["monthly_decay"] == 0.0
    assert values["passive_gain"] == 0.015
    assert values["max_banked_credits"] == 50.0
    assert values["auto_spend_cap"] == 80.0
