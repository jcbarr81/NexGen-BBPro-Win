"""Transactions and approvals page for the admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from services.gm_finance_queue import summarize_queue_decisions
from utils.league_settings import is_owner_league, load_league_settings
from utils.path_utils import get_data_dir
from ...components import ActionButtonPanel, Card, section_title
from .base import DashboardPage


def _format_gm_finance_status(summary: dict[str, int], *, owner_mode: bool) -> str:
    if not owner_mode:
        return "Single-player league: GM finance recommendations auto-apply after owner action."
    return (
        f"Pending: {int(summary.get('pending', 0) or 0)} | "
        f"Approved not applied: {int(summary.get('approved_unapplied', 0) or 0)} | "
        f"Applied: {int(summary.get('approved_applied', 0) or 0)} | "
        f"Rejected: {int(summary.get('rejected', 0) or 0)}"
    )


class TransactionsPage(DashboardPage):
    """Central hub for trade and owner-approval workflows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        trades = Card()
        trades.layout().addWidget(section_title("Trade Queue"))
        trade_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.review_button = QPushButton("Review Pending Trades")
        self.review_button.setToolTip("Approve or reject pending and owner-accepted trades")
        trade_actions.add_button(self.review_button)

        self.trade_settings_button = QPushButton("Open Trade Settings")
        self.trade_settings_button.setToolTip(
            "Configure trade enablement, commissioner approval, and draft-pick rules"
        )
        trade_actions.add_button(self.trade_settings_button)
        trades.layout().addWidget(trade_actions)

        trade_note = QLabel("Use settings to control whether trades auto-execute or require commissioner approval.")
        trade_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        trades.layout().addWidget(trade_note)
        trades.layout().addStretch()

        owner_flow = Card()
        owner_flow.layout().addWidget(section_title("Owner Change Queue"))
        owner_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.change_requests_button = QPushButton("Review Change Requests")
        self.change_requests_button.setToolTip("Import and approve owner change requests")
        owner_actions.add_button(self.change_requests_button)
        owner_flow.layout().addWidget(owner_actions)

        owner_note = QLabel("Use this queue to process incoming owner updates in one place.")
        owner_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        owner_flow.layout().addWidget(owner_note)
        owner_flow.layout().addStretch()

        gm_finance = Card()
        gm_finance.layout().addWidget(section_title("GM Finance Queue"))
        gm_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.gm_finance_queue_button = QPushButton("Review GM Finance Queue")
        self.gm_finance_queue_button.setToolTip(
            "Approve or reject pending owner arbitration/free-agency queue decisions"
        )
        gm_actions.add_button(self.gm_finance_queue_button)
        gm_finance.layout().addWidget(gm_actions)

        gm_finance_note = QLabel(
            "In multi-owner mode, owner finance decisions require commissioner review."
        )
        gm_finance_note.setWordWrap(True)
        gm_finance_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        gm_finance.layout().addWidget(gm_finance_note)
        self.gm_finance_status_label = QLabel("")
        self.gm_finance_status_label.setWordWrap(True)
        self.gm_finance_status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        gm_finance.layout().addWidget(self.gm_finance_status_label)
        gm_finance.layout().addStretch()

        layout.addWidget(trades)
        layout.addWidget(owner_flow)
        layout.addWidget(gm_finance)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        data_dir = get_data_dir()
        league_settings = load_league_settings(data_dir / "league_settings.json")
        owner_mode = bool(is_owner_league(league_settings))
        summary = summarize_queue_decisions(data_dir=data_dir)
        self.gm_finance_status_label.setText(
            _format_gm_finance_status(summary, owner_mode=owner_mode)
        )


__all__ = ["TransactionsPage", "_format_gm_finance_status"]
