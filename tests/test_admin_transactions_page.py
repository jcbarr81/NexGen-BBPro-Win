from __future__ import annotations

from ui.admin_dashboard.pages.transactions import _format_gm_finance_status


def test_format_gm_finance_status_single_player_message():
    text = _format_gm_finance_status({}, owner_mode=False)
    assert "Single-player league" in text


def test_format_gm_finance_status_owner_mode_counts():
    text = _format_gm_finance_status(
        {
            "pending": 3,
            "approved_unapplied": 2,
            "approved_applied": 5,
            "rejected": 1,
        },
        owner_mode=True,
    )
    assert "Pending: 3" in text
    assert "Approved not applied: 2" in text
    assert "Applied: 5" in text
    assert "Rejected: 1" in text
