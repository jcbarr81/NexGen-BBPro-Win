from __future__ import annotations

import importlib

from tests.qt_stubs import patch_qt

patch_qt()

import ui.league_command_center_window as command_center_window

importlib.reload(command_center_window)


def test_command_center_window_refresh_populates_snapshot(monkeypatch):
    payload = {
        "league_id": "alpha",
        "phase": "REGULAR_SEASON",
        "sim_date": "2026-07-20",
        "generated_at_utc": "2026-03-02T18:00:00Z",
        "overview": {
            "critical_cards": 1,
            "warning_cards": 2,
            "total_attention_items": 9,
        },
        "cards": [
            {
                "card_id": "injuries",
                "title": "Injuries",
                "severity": "warning",
                "summary": "2 injuries.",
                "count": 2,
                "items": [{"team_id": "AAA", "injury_count": 2}],
                "actions": ["Open Injury Center"],
            },
            {
                "card_id": "pending_approvals",
                "title": "Pending Approvals",
                "severity": "critical",
                "summary": "7 approvals pending.",
                "count": 7,
                "items": [{"label": "Pending Trades", "count": 3}],
                "actions": ["Review Pending Trades"],
            },
        ],
    }
    monkeypatch.setattr(
        command_center_window,
        "build_league_command_center_snapshot",
        lambda **_: payload,
    )

    win = command_center_window.LeagueCommandCenterWindow()

    assert win._snapshot_payload.get("league_id") == "alpha"
    assert len(win._card_states) == 2
    assert win._card_states[0]["card_id"] == "injuries"
    assert win._card_states[1]["severity"] == "critical"


def test_command_center_window_formats_item_rows():
    formatter = command_center_window.LeagueCommandCenterWindow._format_item_row

    assert formatter({"label": "Pending Trades", "count": 4}) == "Pending Trades: 4"
    assert formatter({"team_id": "AAA", "injury_count": 3}) == "AAA: 3 injuries"
    assert (
        formatter({"team_id": "BBB", "missing_positions": ["SS", "C"]})
        == "BBB: missing SS, C"
    )
    assert (
        formatter({"title": "AAA: Cash Risk", "severity": "critical"})
        == "[CRITICAL] AAA: Cash Risk"
    )
    assert (
        formatter(
            {
                "label": "Trade Deadline",
                "date": "2026-07-31",
                "days_remaining": 3,
                "status": "near",
            }
        )
        == "Trade Deadline: near | date 2026-07-31 | 3d remaining"
    )
    assert (
        formatter(
            {
                "severity": "warning",
                "title": "AAA: Payroll Near Threshold",
                "message": "Payroll is at 92% of threshold.",
                "next_step": "Review pending arbitration decisions.",
            }
        )
        == "[WARNING] AAA: Payroll Near Threshold | Payroll is at 92% of threshold. | Next: Review pending arbitration decisions."
    )


def test_command_center_window_resolves_action_handlers(monkeypatch):
    monkeypatch.setattr(
        command_center_window,
        "build_league_command_center_snapshot",
        lambda **_: {"cards": []},
    )
    calls: list[str] = []

    class _Parent:
        def open_team_injury_center(self):
            calls.append("injury")

        def open_trade_dialog(self):
            calls.append("trade")

        def open_finance_hub(self):
            calls.append("finance")

    win = command_center_window.LeagueCommandCenterWindow(parent=_Parent())

    injury = win._resolve_action_handler("Open Injury Center")
    trade = win._resolve_action_handler("Review Pending Trades")
    finance = win._resolve_action_handler("Open Offseason Finance Workflow")
    missing = win._resolve_action_handler("Does Not Exist")

    assert callable(injury)
    assert callable(trade)
    assert callable(finance)
    assert missing is None

    injury()
    trade()
    finance()
    assert calls == ["injury", "trade", "finance"]
