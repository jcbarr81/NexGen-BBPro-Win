"""Season operations page for the admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QVBoxLayout

from ...components import Card, section_title
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

        self.season_progress_button = QPushButton("Open Season Progress")
        self.season_progress_button.setToolTip("Open the season progress window")
        control.layout().addWidget(self.season_progress_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.exhibition_button = QPushButton("Run Exhibition Game")
        self.exhibition_button.setToolTip("Run a quick exhibition between two teams")
        control.layout().addWidget(self.exhibition_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.playoffs_view_button = QPushButton("Open Playoffs Viewer")
        self.playoffs_view_button.setToolTip("View current playoff bracket and results")
        control.layout().addWidget(self.playoffs_view_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        control.layout().addStretch()

        ops = Card()
        ops.layout().addWidget(section_title("Schedule Control"))

        self.regenerate_schedule_button = QPushButton("Regenerate Season Schedule")
        self.regenerate_schedule_button.setToolTip("Generate a fresh regular-season schedule and clear prior results")
        ops.layout().addWidget(self.regenerate_schedule_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.reset_opening_day_button = QPushButton("Reset to Opening Day")
        self.reset_opening_day_button.setObjectName("Danger")
        self.reset_opening_day_button.setToolTip("Clear results/standings and rewind season to Opening Day")
        ops.layout().addWidget(self.reset_opening_day_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        ops.layout().addStretch()

        history = Card()
        history.layout().addWidget(section_title("Archives"))

        self.league_history_button = QPushButton("League History")
        self.league_history_button.setToolTip("Browse archived seasons and awards")
        history.layout().addWidget(self.league_history_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        history.layout().addStretch()

        layout.addWidget(control)
        layout.addWidget(ops)
        layout.addWidget(history)
        layout.addStretch()


__all__ = ["SeasonPage"]
