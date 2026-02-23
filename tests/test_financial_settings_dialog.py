from __future__ import annotations


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
