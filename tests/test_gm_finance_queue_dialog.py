from __future__ import annotations


def test_import_gm_finance_queue_dialog_headless():
    from ui.gm_finance_queue_dialog import GmFinanceQueueDialog  # noqa: F401

    assert GmFinanceQueueDialog is not None
