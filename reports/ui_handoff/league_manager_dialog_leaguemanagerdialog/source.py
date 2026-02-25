"""League manager dialog for selecting and organizing league entries."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services import league_lifecycle, league_registry
from utils.path_utils import get_active_league_id


class LeagueManagerDialog(QDialog):
    """Simple league registry manager for admin users."""

    _COL_ACTIVE = 0
    _COL_NAME = 1
    _COL_ID = 2
    _COL_MODE = 3
    _COL_STATUS = 4
    _COL_LAST_OPENED = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("League Manager")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Active", "Display Name", "League ID", "Mode", "Status", "Last Opened"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            self._COL_ACTIVE, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            self._COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            self._COL_ID, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            self._COL_MODE, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            self._COL_STATUS, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            self._COL_LAST_OPENED, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.refresh_button = QPushButton("Refresh")
        self.set_active_button = QPushButton("Set Active")
        self.clone_button = QPushButton("Clone")
        self.archive_toggle_button = QPushButton("Archive / Restore")
        self.delete_button = QPushButton("Delete")
        self.close_button = QPushButton("Close")

        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.set_active_button)
        button_row.addWidget(self.clone_button)
        button_row.addWidget(self.archive_toggle_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch()
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.refresh_button.clicked.connect(self.refresh_table)
        self.set_active_button.clicked.connect(self.set_active_from_selection)
        self.clone_button.clicked.connect(self.clone_from_selection)
        self.archive_toggle_button.clicked.connect(self.toggle_archive_from_selection)
        self.delete_button.clicked.connect(self.delete_from_selection)
        self.close_button.clicked.connect(self.accept)

        self.refresh_table()

    def refresh_table(self) -> None:
        records = sorted(
            league_registry.list_leagues(),
            key=lambda rec: (rec.display_name.lower(), rec.id),
        )
        active_league_id = get_active_league_id()

        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            active_value = "Yes" if record.id == active_league_id else ""
            mode_label = "Owner League" if record.mode == "owner_league" else "Single Player"
            status_label = "Archived" if record.status == "archived" else "Active"
            last_opened = record.last_opened_at or "-"

            for col, value in (
                (self._COL_ACTIVE, active_value),
                (self._COL_NAME, record.display_name),
                (self._COL_ID, record.id),
                (self._COL_MODE, mode_label),
                (self._COL_STATUS, status_label),
                (self._COL_LAST_OPENED, last_opened),
            ):
                item = QTableWidgetItem(value)
                if col == self._COL_ACTIVE:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

        if records:
            self.table.selectRow(0)

    def _selected_league_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, self._COL_ID)
        if item is None:
            return None
        league_id = item.text().strip().lower()
        return league_id or None

    def set_active_from_selection(self) -> None:
        league_id = self._selected_league_id()
        if not league_id:
            QMessageBox.warning(self, "League Manager", "Select a league first.")
            return
        record = league_registry.get_league(league_id)
        if record is None:
            QMessageBox.warning(self, "League Manager", "Selected league no longer exists.")
            self.refresh_table()
            return
        if record.status == "archived":
            QMessageBox.warning(
                self,
                "League Manager",
                "Archived leagues cannot be selected as active. Restore it first.",
            )
            return
        try:
            league_lifecycle.switch_active_league(record.id)
        except Exception as exc:
            QMessageBox.warning(self, "League Manager", f"Unable to set active league: {exc}")
            return
        self.refresh_table()
        QMessageBox.information(
            self,
            "League Manager",
            (
                f'Active league is now "{record.display_name}".\n'
                "Restart the app if existing windows do not fully refresh."
            ),
        )

    def toggle_archive_from_selection(self) -> None:
        league_id = self._selected_league_id()
        if not league_id:
            QMessageBox.warning(self, "League Manager", "Select a league first.")
            return
        record = league_registry.get_league(league_id)
        if record is None:
            QMessageBox.warning(self, "League Manager", "Selected league no longer exists.")
            self.refresh_table()
            return

        target_status = "active" if record.status == "archived" else "archived"
        if target_status == "archived":
            confirm = QMessageBox.question(
                self,
                "Archive League",
                f'Archive "{record.display_name}"? This hides it from active use.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        try:
            if target_status == "archived":
                league_lifecycle.archive_league(record.id)
            else:
                league_lifecycle.unarchive_league(record.id)
        except Exception as exc:
            QMessageBox.warning(self, "League Manager", f"Unable to update league: {exc}")
            return

        self.refresh_table()

    def clone_from_selection(self) -> None:
        league_id = self._selected_league_id()
        if not league_id:
            QMessageBox.warning(self, "League Manager", "Select a league first.")
            return
        source = league_registry.get_league(league_id)
        if source is None:
            QMessageBox.warning(self, "League Manager", "Selected league no longer exists.")
            self.refresh_table()
            return
        clone_name, ok = QInputDialog.getText(
            self,
            "Clone League",
            "New league display name:",
            text=f"{source.display_name} (Copy)",
        )
        if not ok:
            return
        clone_name = clone_name.strip()
        if not clone_name:
            QMessageBox.warning(self, "League Manager", "League name is required.")
            return
        try:
            league_lifecycle.clone_league(
                source.id,
                display_name=clone_name,
                activate=False,
            )
        except Exception as exc:
            QMessageBox.warning(self, "League Manager", f"Unable to clone league: {exc}")
            return
        self.refresh_table()
        QMessageBox.information(
            self,
            "League Manager",
            f'Cloned "{source.display_name}" to "{clone_name}".',
        )

    def delete_from_selection(self) -> None:
        league_id = self._selected_league_id()
        if not league_id:
            QMessageBox.warning(self, "League Manager", "Select a league first.")
            return
        record = league_registry.get_league(league_id)
        if record is None:
            QMessageBox.warning(self, "League Manager", "Selected league no longer exists.")
            self.refresh_table()
            return

        confirm = QMessageBox.question(
            self,
            "Delete League",
            (
                f'Delete "{record.display_name}"?\n\n'
                "This removes the league entry and its on-disk data."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            active_id = get_active_league_id()
            league_lifecycle.delete_league(
                record.id,
                delete_data=True,
                force_if_active=(active_id == record.id),
            )
        except Exception as exc:
            QMessageBox.warning(self, "League Manager", f"Unable to delete league: {exc}")
            return
        self.refresh_table()


__all__ = ["LeagueManagerDialog"]
