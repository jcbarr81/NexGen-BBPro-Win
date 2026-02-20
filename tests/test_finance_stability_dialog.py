from __future__ import annotations


def test_import_finance_stability_dialog_headless():
    from ui.finance_stability_dialog import FinanceStabilityDialog  # noqa: F401

    assert FinanceStabilityDialog is not None
