"""User management actions for the admin dashboard."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.window_utils import show_on_top
from utils.path_utils import get_data_dir
from utils.team_loader import load_teams
from utils.user_manager import add_user, load_users, update_user

from ..context import DashboardContext

RefreshCallback = Optional[Callable[[], None]]


def add_user_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
    refresh_callback: RefreshCallback = None,
) -> None:
    """Display the add-user dialog and persist the new account."""

    if parent is None:
        return

    dialog = QDialog(parent)
    dialog.setWindowTitle("Add User")

    layout = QVBoxLayout()

    username_input = QLineEdit()
    password_input = QLineEdit()
    password_input.setEchoMode(QLineEdit.EchoMode.Password)
    role_combo = QComboBox()
    role_combo.addItem("Admin", userData="admin")
    role_combo.addItem("Owner", userData="owner")
    team_combo = QComboBox()

    layout.addWidget(QLabel("Username:"))
    layout.addWidget(username_input)
    layout.addWidget(QLabel("Password:"))
    layout.addWidget(password_input)
    layout.addWidget(QLabel("Role:"))
    layout.addWidget(role_combo)
    layout.addWidget(QLabel("Team:"))
    layout.addWidget(team_combo)

    data_dir = get_data_dir()
    teams = load_teams(data_dir / "teams.csv")
    team_combo.addItem("None", "")
    for team in teams:
        team_combo.addItem(f"{team.name} ({team.team_id})", userData=team.team_id)

    btn_layout = QHBoxLayout()
    add_btn = QPushButton("Add")
    cancel_btn = QPushButton("Cancel")
    btn_layout.addWidget(add_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    def sync_team_enabled() -> None:
        team_combo.setEnabled(role_combo.currentData() == "owner")

    role_combo.currentIndexChanged.connect(lambda *_: sync_team_enabled())
    sync_team_enabled()

    def handle_add() -> None:
        username = username_input.text().strip()
        password = password_input.text().strip()
        team_id = team_combo.currentData()
        role = role_combo.currentData()
        if not username or not password:
            QMessageBox.warning(dialog, "Error", "Username and password required")
            return
        if role == "owner" and not team_id:
            QMessageBox.warning(dialog, "Error", "Select a team for the owner role")
            return
        try:
            add_user(username, password, role, team_id, data_dir / "users.txt")
        except ValueError as exc:
            QMessageBox.warning(dialog, "Error", str(exc))
            return
        QMessageBox.information(dialog, "Success", f"User {username} added.")
        dialog.accept()
        if refresh_callback is not None:
            try:
                refresh_callback()
            except Exception:
                pass

    add_btn.clicked.connect(handle_add)
    cancel_btn.clicked.connect(dialog.reject)

    dialog.setLayout(layout)
    show_on_top(dialog)


def edit_user_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
    selected_username: Optional[str] = None,
    refresh_callback: RefreshCallback = None,
) -> None:
    """Display the edit-user dialog and persist updates."""

    if parent is None:
        return

    dialog = QDialog(parent)
    dialog.setWindowTitle("Edit User")

    data_dir = get_data_dir()
    users = load_users(data_dir / "users.txt")
    if not users:
        QMessageBox.information(parent, "No Users", "No users available.")
        return

    layout = QVBoxLayout()

    user_combo = QComboBox()
    for user in users:
        user_combo.addItem(user["username"], userData=user)

    password_input = QLineEdit()
    password_input.setEchoMode(QLineEdit.EchoMode.Password)

    role_combo = QComboBox()
    role_combo.addItem("Admin", userData="admin")
    role_combo.addItem("Owner", userData="owner")

    team_combo = QComboBox()
    teams = load_teams(data_dir / "teams.csv")
    team_combo.addItem("None", "")
    for team in teams:
        team_combo.addItem(f"{team.name} ({team.team_id})", userData=team.team_id)

    layout.addWidget(QLabel("User:"))
    layout.addWidget(user_combo)
    layout.addWidget(QLabel("New Password:"))
    layout.addWidget(password_input)
    layout.addWidget(QLabel("Role:"))
    layout.addWidget(role_combo)
    layout.addWidget(QLabel("Team:"))
    layout.addWidget(team_combo)

    btn_layout = QHBoxLayout()
    save_btn = QPushButton("Update")
    cancel_btn = QPushButton("Cancel")
    btn_layout.addWidget(save_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    def sync_fields() -> None:
        user = user_combo.currentData()
        if not user:
            return
        team_index = team_combo.findData(user.get("team_id"))
        if team_index >= 0:
            team_combo.setCurrentIndex(team_index)
        role_index = role_combo.findData(user.get("role", "admin"))
        if role_index >= 0:
            role_combo.setCurrentIndex(role_index)
        password_input.clear()

    def sync_team_enabled() -> None:
        team_combo.setEnabled(role_combo.currentData() == "owner")

    user_combo.currentIndexChanged.connect(lambda _: sync_fields())
    role_combo.currentIndexChanged.connect(lambda *_: sync_team_enabled())

    if selected_username:
        index = user_combo.findText(selected_username)
        if index >= 0:
            user_combo.setCurrentIndex(index)

    sync_fields()
    sync_team_enabled()

    def handle_update() -> None:
        user = user_combo.currentData()
        new_password = password_input.text().strip() or None
        new_team = team_combo.currentData()
        new_role = role_combo.currentData()
        if new_role == "owner" and not new_team:
            QMessageBox.warning(dialog, "Error", "Select a team for the owner role")
            return
        try:
            update_user(
                user["username"],
                new_password,
                new_team,
                data_dir / "users.txt",
                new_role=new_role,
            )
        except ValueError as exc:
            QMessageBox.warning(dialog, "Error", str(exc))
            return
        QMessageBox.information(dialog, "Success", f"User {user['username']} updated.")
        dialog.accept()
        if refresh_callback is not None:
            try:
                refresh_callback()
            except Exception:
                pass

    save_btn.clicked.connect(handle_update)
    cancel_btn.clicked.connect(dialog.reject)

    dialog.setLayout(layout)
    show_on_top(dialog)


__all__ = ["add_user_action", "edit_user_action"]
