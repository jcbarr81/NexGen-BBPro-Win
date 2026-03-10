"""League setup and policy settings page for the admin dashboard."""
from __future__ import annotations

from PyQt6.QtWidgets import QPushButton, QVBoxLayout

from ...components import ActionButtonPanel, Card, section_title
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
        setup_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.create_league_button = QPushButton("Create League")
        self.create_league_button.setToolTip("Generate a new league structure (destructive)")
        setup_actions.add_button(self.create_league_button)

        self.league_manager_button = QPushButton("League Manager")
        self.league_manager_button.setToolTip("Switch active league and manage archive state")
        setup_actions.add_button(self.league_manager_button)
        setup.layout().addWidget(setup_actions)
        setup.layout().addStretch()

        rules = Card()
        rules.layout().addWidget(section_title("Rules & Balancing"))
        rules_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.playbalance_button = QPushButton("Physics Tuning")
        self.playbalance_button.setToolTip("Tune physics engine sliders")
        rules_actions.add_button(self.playbalance_button)

        self.injury_settings_button = QPushButton("Injury Settings")
        self.injury_settings_button.setToolTip("Configure injury frequency for the league")
        rules_actions.add_button(self.injury_settings_button)

        self.financial_settings_button = QPushButton("Financial System Settings")
        self.financial_settings_button.setToolTip(
            "Configure global finance mode, presets, and per-module levels"
        )
        rules_actions.add_button(self.financial_settings_button)

        self.team_strategy_profiles_button = QPushButton("Team Strategy Profiles")
        self.team_strategy_profiles_button.setToolTip(
            "Set league/team strategy profiles for automation behavior"
        )
        rules_actions.add_button(self.team_strategy_profiles_button)

        self.finance_stability_button = QPushButton("Finance Stability Simulation")
        self.finance_stability_button.setToolTip(
            "Run multi-season financial stability simulations and export reports"
        )
        rules_actions.add_button(self.finance_stability_button)

        self.hall_of_fame_settings_button = QPushButton("Hall of Fame Settings")
        self.hall_of_fame_settings_button.setToolTip(
            "Adjust Hall of Fame eligibility and scoring thresholds"
        )
        rules_actions.add_button(self.hall_of_fame_settings_button)
        rules.layout().addWidget(rules_actions)
        rules.layout().addStretch()

        hubs = Card()
        hubs.layout().addWidget(section_title("Operations Hubs"))
        hub_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.free_agency_hub_button = QPushButton("Open Free Agency Hub")
        self.free_agency_hub_button.setToolTip("Browse unsigned players and simulate AI bids")
        hub_actions.add_button(self.free_agency_hub_button)

        self.injury_center_button = QPushButton("Open Injury Center")
        self.injury_center_button.setToolTip("View league-wide injuries (read-only)")
        hub_actions.add_button(self.injury_center_button)
        hubs.layout().addWidget(hub_actions)
        hubs.layout().addStretch()

        layout.addWidget(setup)
        layout.addWidget(rules)
        layout.addWidget(hubs)
        layout.addStretch()


__all__ = ["LeagueSettingsPage"]
