"""Season operations page for the admin dashboard."""
from __future__ import annotations

from PyQt6.QtWidgets import QPushButton, QVBoxLayout

from ...components import ActionButtonPanel, Card, section_title
from .base import DashboardPage


class SeasonPage(DashboardPage):
    """Season timeline controls and archive access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        control = Card()
        control.layout().addWidget(section_title("Season Flow"))
        control_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.season_progress_button = QPushButton("Open Season Progress")
        self.season_progress_button.setToolTip("Open the season progress window")
        control_actions.add_button(self.season_progress_button)

        self.exhibition_button = QPushButton("Run Exhibition Game")
        self.exhibition_button.setToolTip("Run a quick exhibition between two teams")
        control_actions.add_button(self.exhibition_button)

        self.playoffs_view_button = QPushButton("Open Playoffs Viewer")
        self.playoffs_view_button.setToolTip("View current playoff bracket and results")
        control_actions.add_button(self.playoffs_view_button)

        self.command_center_button = QPushButton("Open League Command Center")
        self.command_center_button.setToolTip(
            "Open league-wide command center cards for operations triage"
        )
        control_actions.add_button(self.command_center_button)
        control.layout().addWidget(control_actions)
        control.layout().addStretch()

        ops = Card()
        ops.layout().addWidget(section_title("Schedule Control"))
        ops_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.regenerate_schedule_button = QPushButton("Regenerate Season Schedule")
        self.regenerate_schedule_button.setToolTip("Generate a fresh regular-season schedule and clear prior results")
        ops_actions.add_button(self.regenerate_schedule_button)

        self.reset_opening_day_button = QPushButton("Reset to Opening Day")
        self.reset_opening_day_button.setObjectName("Danger")
        self.reset_opening_day_button.setToolTip("Clear results/standings and rewind season to Opening Day")
        ops_actions.add_button(self.reset_opening_day_button)
        ops.layout().addWidget(ops_actions)
        ops.layout().addStretch()

        history = Card()
        history.layout().addWidget(section_title("Archives"))
        history_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.league_history_button = QPushButton("League History")
        self.league_history_button.setToolTip("Browse archived seasons and awards")
        history_actions.add_button(self.league_history_button)
        history.layout().addWidget(history_actions)
        history.layout().addStretch()

        finance = Card()
        finance.layout().addWidget(section_title("Offseason Finance"))
        finance_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.offseason_finance_button = QPushButton("Open Offseason Finance Workflow")
        self.offseason_finance_button.setToolTip(
            "Review and run offseason finance tasks (snapshot, arbitration, budget reset) and align owners to Owner Ops/GM-Coach Ops finance workflows"
        )
        finance_actions.add_button(self.offseason_finance_button)
        finance.layout().addWidget(finance_actions)
        finance.layout().addStretch()

        layout.addWidget(control)
        layout.addWidget(ops)
        layout.addWidget(history)
        layout.addWidget(finance)
        layout.addStretch()


__all__ = ["SeasonPage"]
