"""League management page migrated from the legacy admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QVBoxLayout

from ...components import Card, section_title
from .base import DashboardPage


class LeaguePage(DashboardPage):
    """Actions related to league-wide management, grouped by intent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        control = Card()
        control.layout().addWidget(section_title("Season Control"))

        self.season_progress_button = QPushButton("Season Progress")
        self.season_progress_button.setToolTip("Open the season progress window")
        control.layout().addWidget(self.season_progress_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.reset_opening_day_button = QPushButton("Reset to Opening Day")
        self.reset_opening_day_button.setObjectName("Danger")
        self.reset_opening_day_button.setToolTip("Clear results/standings and rewind season to Opening Day")
        control.layout().addWidget(self.reset_opening_day_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.exhibition_button = QPushButton("Simulate Exhibition Game")
        self.exhibition_button.setToolTip("Run a quick exhibition between two teams")
        control.layout().addWidget(self.exhibition_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.playoffs_view_button = QPushButton("Open Playoffs Viewer")
        self.playoffs_view_button.setToolTip("View current playoff bracket and results")
        control.layout().addWidget(self.playoffs_view_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        control.layout().addStretch()

        ops = Card()
        ops.layout().addWidget(section_title("Operations"))

        self.review_button = QPushButton("Review Trades")
        self.review_button.setToolTip("Approve or reject pending trades")
        ops.layout().addWidget(self.review_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.create_league_button = QPushButton("Create League")
        self.create_league_button.setToolTip("Generate a new league structure (destructive)")
        ops.layout().addWidget(self.create_league_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.playbalance_button = QPushButton("Physics Tuning")
        self.playbalance_button.setToolTip("Tune physics engine sliders")
        ops.layout().addWidget(self.playbalance_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.free_agency_hub_button = QPushButton("Open Free Agency Hub")
        self.free_agency_hub_button.setToolTip("Browse unsigned players and simulate AI bids")
        ops.layout().addWidget(self.free_agency_hub_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.injury_center_button = QPushButton("Open Injury Center")
        self.injury_center_button.setToolTip("View league-wide injuries (read-only)")
        ops.layout().addWidget(self.injury_center_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.injury_settings_button = QPushButton("Injury Settings")
        self.injury_settings_button.setToolTip("Configure injury frequency for the league")
        ops.layout().addWidget(self.injury_settings_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        ops.layout().addStretch()

        history = Card()
        history.layout().addWidget(section_title("History & Archives"))

        self.league_history_button = QPushButton("League History")
        self.league_history_button.setToolTip("Browse archived seasons and awards")
        history.layout().addWidget(self.league_history_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        history.layout().addStretch()

        layout.addWidget(control)
        layout.addWidget(ops)
        layout.addWidget(history)
        layout.addStretch()


__all__ = ["LeaguePage"]
