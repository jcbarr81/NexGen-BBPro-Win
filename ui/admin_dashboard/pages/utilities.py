"""Utility actions page migrated from the legacy admin dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QPushButton, QVBoxLayout, QHBoxLayout

from ...components import Card, section_title
from .base import DashboardPage


class UtilitiesPage(DashboardPage):
    """Asset generation and export utilities."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        assets = Card()
        assets.layout().addWidget(section_title("Assets"))

        self.generate_logos_button = QPushButton("Generate Team Logos")
        self.generate_logos_button.setToolTip("Generate or refresh logo images for all teams")
        self.logo_tutorial_button = QPushButton("Logo Tutorial")
        self.logo_tutorial_button.setToolTip("Open the step-by-step team logo guide")
        logos_row = QHBoxLayout()
        logos_row.addStretch(1)
        logos_row.addWidget(self.generate_logos_button)
        logos_row.addWidget(self.logo_tutorial_button)
        logos_row.addStretch(1)
        assets.layout().addLayout(logos_row)

        self.generate_avatars_button = QPushButton("Generate Player Avatars")
        self.generate_avatars_button.setToolTip("Generate player avatar images")
        self.avatar_tutorial_button = QPushButton("Avatar Tutorial")
        self.avatar_tutorial_button.setToolTip("Open the step-by-step avatar guide")
        avatars_row = QHBoxLayout()
        avatars_row.addStretch(1)
        avatars_row.addWidget(self.generate_avatars_button)
        avatars_row.addWidget(self.avatar_tutorial_button)
        avatars_row.addStretch(1)
        assets.layout().addLayout(avatars_row)
        assets.layout().addStretch()

        exports = Card()
        exports.layout().addWidget(section_title("Exports & Sharing"))

        self.export_reports_button = QPushButton("Export Reports (CSV/PDF)")
        self.export_reports_button.setToolTip("Export league history and analytics to CSV/PDF")
        exports.layout().addWidget(
            self.export_reports_button,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        self.export_snapshot_button = QPushButton("Export Owner Snapshot Zip")
        self.export_snapshot_button.setToolTip("Export a zip owners can import to sync league data")
        exports.layout().addWidget(
            self.export_snapshot_button,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        exports.layout().addStretch()

        layout.addWidget(assets)
        layout.addWidget(exports)
        layout.addStretch()

    def on_attached(self) -> None:
        super().on_attached()
        if self.export_reports_button is not None:
            self.export_reports_button.clicked.connect(self._handle_export_reports)
        if self.export_snapshot_button is not None:
            self.export_snapshot_button.clicked.connect(self._handle_export_snapshot)

    def _handle_export_reports(self) -> None:
        from ..actions.reports import export_reports_action

        try:
            export_reports_action(self.context, self)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Export Reports", str(exc))

    def _handle_export_snapshot(self) -> None:
        from ..actions.league_snapshot import export_league_snapshot_action

        try:
            export_league_snapshot_action(self.context, self)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Export League Snapshot", str(exc))


__all__ = ["UtilitiesPage"]
