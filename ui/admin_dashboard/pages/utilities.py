"""Utility actions page migrated from the legacy admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QPushButton, QVBoxLayout, QHBoxLayout

from ...components import Card, section_title
from ..actions.league import regenerate_schedule_action
from .base import DashboardPage


class UtilitiesPage(DashboardPage):
    """Miscellaneous utilities for data management."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        card = Card()
        card.layout().addWidget(section_title("Utilities"))

        self.generate_logos_button = QPushButton("Generate Team Logos")
        self.logo_tutorial_button = QPushButton("Logo Tutorial")
        logos_row = QHBoxLayout()
        logos_row.addStretch(1)
        logos_row.addWidget(self.generate_logos_button)
        logos_row.addWidget(self.logo_tutorial_button)
        logos_row.addStretch(1)
        card.layout().addLayout(logos_row)

        self.generate_avatars_button = QPushButton("Generate Player Avatars")
        self.avatar_tutorial_button = QPushButton("Avatar Tutorial")
        avatars_row = QHBoxLayout()
        avatars_row.addStretch(1)
        avatars_row.addWidget(self.generate_avatars_button)
        avatars_row.addWidget(self.avatar_tutorial_button)
        avatars_row.addStretch(1)
        card.layout().addLayout(avatars_row)

        self.regenerate_schedule_button = QPushButton("Regenerate Regular Season Schedule")
        self.regenerate_schedule_button.setEnabled(False)
        card.layout().addWidget(
            self.regenerate_schedule_button,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()

    def on_attached(self) -> None:
        super().on_attached()
        self.regenerate_schedule_button.setEnabled(True)
        self.regenerate_schedule_button.clicked.connect(self._handle_regenerate_schedule)

    def _handle_regenerate_schedule(self) -> None:
        try:
            regenerate_schedule_action(self.context, self)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Schedule Error", str(exc))


__all__ = ["UtilitiesPage"]
