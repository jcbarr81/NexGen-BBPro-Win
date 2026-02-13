"""League setup and policy settings page for the admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QVBoxLayout

from ...components import Card, section_title
from .base import DashboardPage


class LeagueSettingsPage(DashboardPage):
    """League-level setup, balancing, and policy tooling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        setup = Card()
        setup.layout().addWidget(section_title("League Configuration"))

        self.create_league_button = QPushButton("Create League")
        self.create_league_button.setToolTip("Generate a new league structure (destructive)")
        setup.layout().addWidget(self.create_league_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        setup.layout().addStretch()

        rules = Card()
        rules.layout().addWidget(section_title("Rules & Balancing"))

        self.playbalance_button = QPushButton("Physics Tuning")
        self.playbalance_button.setToolTip("Tune physics engine sliders")
        rules.layout().addWidget(self.playbalance_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.injury_settings_button = QPushButton("Injury Settings")
        self.injury_settings_button.setToolTip("Configure injury frequency for the league")
        rules.layout().addWidget(self.injury_settings_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.hall_of_fame_settings_button = QPushButton("Hall of Fame Settings")
        self.hall_of_fame_settings_button.setToolTip(
            "Adjust Hall of Fame eligibility and scoring thresholds"
        )
        rules.layout().addWidget(self.hall_of_fame_settings_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        rules.layout().addStretch()

        hubs = Card()
        hubs.layout().addWidget(section_title("Operations Hubs"))

        self.free_agency_hub_button = QPushButton("Open Free Agency Hub")
        self.free_agency_hub_button.setToolTip("Browse unsigned players and simulate AI bids")
        hubs.layout().addWidget(self.free_agency_hub_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.injury_center_button = QPushButton("Open Injury Center")
        self.injury_center_button.setToolTip("View league-wide injuries (read-only)")
        hubs.layout().addWidget(self.injury_center_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        hubs.layout().addStretch()

        layout.addWidget(setup)
        layout.addWidget(rules)
        layout.addWidget(hubs)
        layout.addStretch()


__all__ = ["LeagueSettingsPage"]
