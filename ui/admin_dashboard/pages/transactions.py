"""Transactions and approvals page for the admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ...components import Card, section_title
from .base import DashboardPage


class TransactionsPage(DashboardPage):
    """Central hub for trade and owner-approval workflows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        trades = Card()
        trades.layout().addWidget(section_title("Trade Queue"))

        self.review_button = QPushButton("Review Pending Trades")
        self.review_button.setToolTip("Approve or reject pending and owner-accepted trades")
        trades.layout().addWidget(self.review_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.trade_settings_button = QPushButton("Open Trade Settings")
        self.trade_settings_button.setToolTip(
            "Configure trade enablement, commissioner approval, and draft-pick rules"
        )
        trades.layout().addWidget(self.trade_settings_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        trade_note = QLabel("Use settings to control whether trades auto-execute or require commissioner approval.")
        trade_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        trades.layout().addWidget(trade_note)
        trades.layout().addStretch()

        owner_flow = Card()
        owner_flow.layout().addWidget(section_title("Owner Change Queue"))

        self.change_requests_button = QPushButton("Review Change Requests")
        self.change_requests_button.setToolTip("Import and approve owner change requests")
        owner_flow.layout().addWidget(self.change_requests_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        owner_note = QLabel("Use this queue to process incoming owner updates in one place.")
        owner_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        owner_flow.layout().addWidget(owner_note)
        owner_flow.layout().addStretch()

        layout.addWidget(trades)
        layout.addWidget(owner_flow)
        layout.addStretch()


__all__ = ["TransactionsPage"]
