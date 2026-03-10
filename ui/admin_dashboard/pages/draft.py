"""Draft tools page migrated from the legacy admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ...components import ActionButtonPanel, Card, section_title
from .base import DashboardPage


class DraftPage(DashboardPage):
    """Amateur draft hub with status messaging."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        card = Card()
        card.layout().addWidget(section_title("Amateur Draft"))

        self.draft_status_label = QLabel("")
        self.draft_status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card.layout().addWidget(self.draft_status_label)
        draft_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.view_draft_pool_button = QPushButton("View Draft Pool")
        self.view_draft_pool_button.setToolTip("Browse the draft pool once Draft Day arrives.")
        draft_actions.add_button(self.view_draft_pool_button)

        self.start_resume_draft_button = QPushButton("Start/Resume Draft")
        self.start_resume_draft_button.setToolTip("Open the Draft Console on or after Draft Day.")
        draft_actions.add_button(self.start_resume_draft_button)

        self.view_results_button = QPushButton("View Draft Results")
        self.view_results_button.setToolTip("Open results for the current season (after completion).")
        draft_actions.add_button(self.view_results_button)

        self.draft_settings_button = QPushButton("Draft Settings")
        self.draft_settings_button.setToolTip("Configure rounds, pool size, and RNG seed (always available).")
        draft_actions.add_button(self.draft_settings_button)
        card.layout().addWidget(draft_actions)

        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()


__all__ = ["DraftPage"]
