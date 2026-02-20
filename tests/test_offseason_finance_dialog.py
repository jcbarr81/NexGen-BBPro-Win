from __future__ import annotations


def test_import_offseason_finance_dialog_headless():
    from ui.offseason_finance_dialog import OffseasonFinanceDialog  # noqa: F401

    assert OffseasonFinanceDialog is not None


def test_offseason_finance_dialog_readiness_text_includes_blockers():
    from ui.offseason_finance_dialog import OffseasonFinanceDialog

    text = OffseasonFinanceDialog._build_readiness_text(
        can_run=True,
        next_stage_id="contracts_review",
        run_enabled=False,
        run_reason="Pipeline already executed for this offseason year.",
        stage_enabled=True,
        stage_reason="",
        stages=[
            {"id": "contracts_review", "label": "Review Contract Expirations"},
        ],
    )

    assert "Action Readiness" in text
    assert "Next required stage: Review Contract Expirations" in text
    assert "Pipeline action: Blocked" in text
    assert "Checklist action: Ready" in text


def test_format_gm_queue_hint_single_player_disabled():
    from ui.offseason_finance_dialog import _format_gm_queue_hint

    enabled, text = _format_gm_queue_hint(
        {"requires_commissioner_finance_review": False}
    )
    assert enabled is False
    assert "multi-owner leagues" in text


def test_format_gm_queue_hint_pending_and_clear_states():
    from ui.offseason_finance_dialog import _format_gm_queue_hint

    enabled, text = _format_gm_queue_hint(
        {
            "requires_commissioner_finance_review": True,
            "gm_queue_pending": 2,
            "gm_queue_approved_unapplied": 0,
            "gm_queue_total": 2,
        }
    )
    assert enabled is True
    assert "2 pending" in text

    enabled, text = _format_gm_queue_hint(
        {
            "requires_commissioner_finance_review": True,
            "gm_queue_pending": 0,
            "gm_queue_approved_unapplied": 0,
            "gm_queue_total": 3,
        }
    )
    assert enabled is True
    assert "clear" in text.lower()


def test_gm_inline_action_state_for_pending_selection():
    from ui.offseason_finance_dialog import _gm_inline_action_state

    state = _gm_inline_action_state(
        {
            "requires_commissioner_finance_review": True,
            "gm_queue_pending": 2,
            "gm_queue_approved_unapplied": 1,
            "gm_queue_total": 3,
        },
        selected_status="pending_commissioner",
    )
    assert state["queue_enabled"] is True
    assert state["approve_enabled"] is True
    assert state["reject_enabled"] is True
    assert state["apply_enabled"] is True


def test_gm_inline_action_state_single_player_disables_actions():
    from ui.offseason_finance_dialog import _gm_inline_action_state

    state = _gm_inline_action_state(
        {
            "requires_commissioner_finance_review": False,
            "gm_queue_pending": 0,
            "gm_queue_approved_unapplied": 0,
            "gm_queue_total": 0,
        },
        selected_status="pending_commissioner",
    )
    assert state["queue_enabled"] is False
    assert state["approve_enabled"] is False
    assert state["reject_enabled"] is False
    assert state["apply_enabled"] is False


def test_filter_gm_queue_rows_supports_team_status_and_search():
    from ui.offseason_finance_dialog import _filter_gm_queue_rows

    rows = [
        {
            "team_id": "AAA",
            "queue_type": "arbitration",
            "item_id": "P1",
            "action": "hold",
            "review_status": "pending_commissioner",
            "applied": False,
            "notes": "pending",
        },
        {
            "team_id": "BBB",
            "queue_type": "free_agency",
            "item_id": "P2",
            "action": "target",
            "review_status": "approved_commissioner",
            "applied": False,
            "notes": "approved",
        },
        {
            "team_id": "BBB",
            "queue_type": "free_agency",
            "item_id": "P3",
            "action": "monitor",
            "review_status": "approved_local",
            "applied": True,
            "notes": "applied",
        },
    ]
    filtered = _filter_gm_queue_rows(
        rows,
        team_id="BBB",
        status_filter="approved_unapplied",
    )
    assert len(filtered) == 1
    assert filtered[0]["item_id"] == "P2"

    searched = _filter_gm_queue_rows(rows, query="monitor")
    assert len(searched) == 1
    assert searched[0]["item_id"] == "P3"


def test_offseason_finance_dialog_formats_alert_rows():
    from ui.offseason_finance_dialog import OffseasonFinanceDialog

    text = OffseasonFinanceDialog._format_alerts_text(
        [
            {
                "severity": "warning",
                "title": "AAA: Cashflow Risk",
                "message": "Cash is low.",
                "next_step": "Reduce payroll.",
            }
        ]
    )

    assert "Finance Alerts" in text
    assert "[WARNING] AAA: Cashflow Risk" in text
    assert "Next: Reduce payroll." in text
