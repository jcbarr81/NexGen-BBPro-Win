"""Utility actions page migrated from the legacy admin dashboard."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QPushButton, QVBoxLayout

from ...components import ActionButtonPanel, Card, section_title
from .base import DashboardPage


class UtilitiesPage(DashboardPage):
    """Asset generation and export utilities."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        assets = Card()
        assets.layout().addWidget(section_title("Assets"))
        asset_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.generate_logos_button = QPushButton("Generate Team Logos")
        self.generate_logos_button.setToolTip("Generate or refresh logo images for all teams")
        self.logo_tutorial_button = QPushButton("Logo Tutorial")
        self.logo_tutorial_button.setToolTip("Open the step-by-step team logo guide")
        asset_actions.add_button(self.generate_logos_button)
        asset_actions.add_button(self.logo_tutorial_button)

        self.generate_avatars_button = QPushButton("Generate Player Avatars")
        self.generate_avatars_button.setToolTip("Generate player avatar images")
        self.avatar_tutorial_button = QPushButton("Avatar Tutorial")
        self.avatar_tutorial_button.setToolTip("Open the step-by-step avatar guide")
        asset_actions.add_button(self.generate_avatars_button)
        asset_actions.add_button(self.avatar_tutorial_button)
        assets.layout().addWidget(asset_actions)
        assets.layout().addStretch()

        exports = Card()
        exports.layout().addWidget(section_title("Exports & Sharing"))
        export_actions = ActionButtonPanel(
            min_columns=1,
            max_columns=2,
            target_button_width=220,
            min_button_width=160,
            max_button_width=240,
        )

        self.export_reports_button = QPushButton("Export Reports (HTML)")
        self.export_reports_button.setToolTip(
            "Export league reports as an HTML bundle and open the landing page."
        )
        export_actions.add_button(self.export_reports_button)

        self.export_reports_csv_button = QPushButton("Export Reports (CSV)")
        self.export_reports_csv_button.setToolTip(
            "Export league reports as CSV files (with summary artifacts)."
        )
        export_actions.add_button(self.export_reports_csv_button)

        self.export_almanac_button = QPushButton("Export Almanac (HTML)")
        self.export_almanac_button.setToolTip(
            "Export a multi-page historical league Almanac site."
        )
        export_actions.add_button(self.export_almanac_button)

        self.export_snapshot_button = QPushButton("Export Owner Snapshot Zip")
        self.export_snapshot_button.setToolTip("Export a zip owners can import to sync league data")
        export_actions.add_button(self.export_snapshot_button)
        exports.layout().addWidget(export_actions)
        exports.layout().addStretch()

        layout.addWidget(assets)
        layout.addWidget(exports)
        layout.addStretch()

    def on_attached(self) -> None:
        super().on_attached()
        if self.export_reports_button is not None:
            self.export_reports_button.clicked.connect(self._handle_export_reports_html)
        if self.export_reports_csv_button is not None:
            self.export_reports_csv_button.clicked.connect(self._handle_export_reports_csv)
        if self.export_almanac_button is not None:
            self.export_almanac_button.clicked.connect(self._handle_export_almanac)
        if self.export_snapshot_button is not None:
            self.export_snapshot_button.clicked.connect(self._handle_export_snapshot)

    def _handle_export_reports_html(self) -> None:
        from ..actions.reports import export_reports_action

        try:
            export_reports_action(self.context, self, export_format="html")
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Export Reports", str(exc))

    def _handle_export_reports_csv(self) -> None:
        from ..actions.reports import export_reports_action

        try:
            export_reports_action(self.context, self, export_format="csv")
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Export Reports", str(exc))

    def _handle_export_snapshot(self) -> None:
        from ..actions.league_snapshot import export_league_snapshot_action

        try:
            export_league_snapshot_action(self.context, self)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Export League Snapshot", str(exc))

    def _handle_export_almanac(self) -> None:
        from ..actions.almanac import export_almanac_action

        try:
            export_almanac_action(self.context, self)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            QMessageBox.critical(self, "Export Almanac", str(exc))


__all__ = ["UtilitiesPage"]
