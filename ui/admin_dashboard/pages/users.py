"""User management page migrated from the legacy admin dashboard."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...components import Card, section_title
from .base import DashboardPage

from utils.path_utils import get_data_dir
from utils.user_manager import load_users


class UsersPage(DashboardPage):
    """User account management with search and list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        card = Card()
        card.layout().addWidget(section_title("User Management"))

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by username or team id.")
        card.layout().addWidget(self.search)

        self.user_table = QTableWidget(0, 3)
        self.user_table.setHorizontalHeaderLabels(["Username", "Role", "Team"])
        self.user_table.setSortingEnabled(True)
        card.layout().addWidget(self.user_table)

        row = QHBoxLayout()
        self.add_user_button = QPushButton("Add User")
        self.edit_user_button = QPushButton("Edit User")
        row.addWidget(self.add_user_button)
        row.addWidget(self.edit_user_button)
        card.layout().addLayout(row)

        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()

        self.selected_username: str | None = None
        self.search.textChanged.connect(self._populate)
        self.user_table.itemSelectionChanged.connect(self._capture_selection)
        self._populate()

    def refresh(self) -> None:
        """Public hook to repopulate the users table."""
        self._populate()

    def _capture_selection(self) -> None:
        items = self.user_table.selectedItems()
        self.selected_username = items[0].text() if items else None

    def _populate(self) -> None:
        needle = self.search.text().strip().lower()
        try:
            users = load_users(get_data_dir() / "users.txt")
        except Exception:
            users = []
        rows = []
        for user in users:
            username = user.get("username", "")
            role = user.get("role", "")
            team = user.get("team_id", "")
            if not needle or needle in username.lower() or needle in team.lower():
                rows.append((username, role, team))
        self.user_table.setRowCount(len(rows))
        for row_index, (username, role, team) in enumerate(rows):
            self.user_table.setItem(row_index, 0, QTableWidgetItem(username))
            self.user_table.setItem(row_index, 1, QTableWidgetItem(role))
            self.user_table.setItem(row_index, 2, QTableWidgetItem(team))


__all__ = ["UsersPage"]
