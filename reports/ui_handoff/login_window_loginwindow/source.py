from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QInputDialog,
    QVBoxLayout,
    QMessageBox,
)
from PyQt6.QtCore import Qt
import logging
import sys
import importlib

import bcrypt

from services import league_registry
from utils.path_utils import get_data_dir
from utils.league_settings import is_owner_league, verify_commissioner_password
from ui.theme import DARK_QSS
from ui.window_utils import show_on_top, untrack_on_top
from ui.version_badge import install_version_badge

logger = logging.getLogger(__name__)
USER_FILE = None  # Backward-compatible test override.


class LoginWindow(QWidget):
    def __init__(self, splash=None):
        super().__init__()
        self.setWindowTitle("UBL Login")

        # Keep a reference to the splash screen so it can be closed after
        # successful authentication.
        self.splash = splash

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.username_input.setFocus()

        self.league_label = QLabel("League:")
        self.league_selector = QComboBox()
        self.league_selector.currentIndexChanged.connect(self._on_league_changed)

        self.login_button = QPushButton("Login")
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self.handle_login)

        self._build_layout()
        self._populate_league_selector()

        # Connect returnPressed signal to login
        self.username_input.returnPressed.connect(self.handle_login)
        self.password_input.returnPressed.connect(self.handle_login)

        self.dashboard = None

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_maximized()

    def handle_login(self):
        try:
            username = self.username_input.text()
            password = self.password_input.text()
            users_file = self._users_file_path()

            if not users_file.exists():
                QMessageBox.critical(
                    self,
                    "Error",
                    "User file not found for the selected league.",
                )
                return

            with users_file.open("r") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) != 4:
                        continue
                    file_user, file_pass, role, team_id = parts
                    if file_user != username:
                        continue
                    hashed_match = False
                    try:
                        hashed_match = bcrypt.checkpw(
                            password.encode("utf-8"), file_pass.encode("utf-8")
                        )
                    except ValueError:
                        hashed_match = False
                    if hashed_match or password == file_pass:
                        self.accept_login(role, team_id)
                        return

            QMessageBox.warning(self, "Login Failed", "Invalid username or password.")
        except Exception:
            logger.exception("Login handler failed")
            QMessageBox.critical(
                self,
                "Error",
                "Login failed due to an unexpected error. See startup.log for details.",
            )

    def _users_file_path(self):
        if USER_FILE:
            try:
                from pathlib import Path

                return Path(USER_FILE)
            except Exception:
                pass
        return get_data_dir() / "users.txt"

    def _populate_league_selector(self) -> None:
        records = [
            record
            for record in league_registry.list_leagues()
            if record.status != "archived"
        ]
        if not records:
            self.league_label.hide()
            self.league_selector.hide()
            return

        records.sort(key=lambda rec: rec.display_name.lower())
        current_active = league_registry.get_active_league()
        active_id = current_active.id if current_active is not None else ""

        self.league_selector.blockSignals(True)
        self.league_selector.clear()
        active_index = 0
        for idx, record in enumerate(records):
            self.league_selector.addItem(record.display_name, record.id)
            if record.id == active_id:
                active_index = idx
        self.league_selector.setCurrentIndex(active_index)
        self.league_selector.blockSignals(False)

        selected_id = self.league_selector.currentData()
        if isinstance(selected_id, str) and selected_id:
            self._set_active_league(selected_id)

    def _on_league_changed(self, _index: int) -> None:
        league_id = self.league_selector.currentData()
        if not isinstance(league_id, str) or not league_id:
            return
        self._set_active_league(league_id)

    def _set_active_league(self, league_id: str) -> None:
        try:
            league_registry.set_active_league(league_id, ensure_data_dir=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "League Selection",
                f"Unable to switch to selected league: {exc}",
            )
            return
        record = league_registry.get_league(league_id)
        if record is not None:
            self.setWindowTitle(f"UBL Login - {record.display_name}")

    def accept_login(self, role, team_id):
        if role == "admin":
            if is_owner_league():
                password, ok = QInputDialog.getText(
                    self,
                    "Commissioner Access",
                    "Enter commissioner password:",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return
                password = password.strip()
                if not verify_commissioner_password(password):
                    QMessageBox.warning(
                        self,
                        "Commissioner Access",
                        "Incorrect commissioner password.",
                    )
                    return
            mod = importlib.import_module("ui.admin_dashboard")
            dash_cls = getattr(mod, "AdminDashboard", None) or getattr(
                mod, "MainWindow", None
            )
            if dash_cls is None:
                QMessageBox.warning(self, "Error", "Admin dashboard not found.")
                return
            self.dashboard = dash_cls()
        elif role == "owner":
            mod = importlib.import_module("ui.owner_dashboard")
            dash_cls = getattr(mod, "OwnerDashboard", None) or getattr(
                mod, "MainWindow", None
            )
            if dash_cls is None:
                QMessageBox.warning(self, "Error", "Owner dashboard not found.")
                return
            self.dashboard = dash_cls(team_id)
        else:
            QMessageBox.warning(self, "Error", "Unrecognized role.")
            return

        # Preserve dashboard cleanup handlers, then restore splash state.
        original_close_event = getattr(self.dashboard, "closeEvent", None)

        def _wrapped_close_event(event, _original=original_close_event):
            try:
                if callable(_original):
                    _original(event)
            except Exception:
                pass
            self.dashboard_closed(event)

        self.dashboard.closeEvent = _wrapped_close_event

        app = QApplication.instance()
        if app:
            app.setStyleSheet(DARK_QSS)
            install_version_badge(app)

        show_on_top(self.dashboard)

        # Close the login window now that the dashboard is displayed.
        self.close()

    def dashboard_closed(self, event):
        """Handle a dashboard being closed by returning focus to the splash."""
        suppress_splash = False
        if self.dashboard is not None:
            try:
                untrack_on_top(self.dashboard)
            except Exception:
                pass
            suppress_splash = getattr(self.dashboard, "_suppress_splash_on_close", False)
        if self.splash:
            if not suppress_splash:
                # Restore the splash screen when the dashboard closes.
                self.splash.show()
                self.splash.raise_()
                self.splash.activateWindow()
            self.splash.login_button.setEnabled(True)
            if getattr(self.splash, "login_window", None) is self:
                self.splash.login_window = None
        self.dashboard = None
        event.accept()

    def closeEvent(self, event):
        """Ensure the splash button is re-enabled if login is cancelled."""
        try:
            untrack_on_top(self)
        except Exception:
            pass
        if self.dashboard is None and self.splash:
            self.splash.login_button.setEnabled(True)
            if getattr(self.splash, "login_window", None) is self:
                self.splash.login_window = None
        event.accept()

    def _ensure_maximized(self) -> None:
        """Ensure the login window is maximized."""
        state_enum = getattr(Qt, "WindowState", None)
        window_state = getattr(self, "windowState", None)
        set_state = getattr(self, "setWindowState", None)
        show_max = getattr(self, "showMaximized", None)

        if state_enum is not None and callable(window_state) and callable(set_state):
            try:
                current_state = window_state()
                desired = getattr(state_enum, "WindowMaximized", None)
                if desired is not None and current_state is not None:
                    set_state(current_state | desired)
                    activate = getattr(self, "activateWindow", None)
                    if callable(activate):
                        activate()
                    return
            except Exception:
                pass

        if callable(show_max):
            try:
                show_max()
            except Exception:
                pass

    def _build_layout(self) -> None:
        """Build a maximized layout with centered login controls."""
        root = QVBoxLayout()
        root.setContentsMargins(80, 80, 80, 80)
        root.setSpacing(24)

        form_panel = QWidget()
        form_panel.setObjectName("LoginPanel")
        form = QVBoxLayout(form_panel)
        form.setSpacing(12)
        form.setContentsMargins(32, 32, 32, 32)

        title_user = QLabel("Username:")
        title_pass = QLabel("Password:")
        form.addWidget(self.league_label, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addWidget(self.league_selector)
        form.addWidget(title_user, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addWidget(self.username_input)
        form.addWidget(title_pass, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addWidget(self.password_input)
        form.addWidget(self.login_button, alignment=Qt.AlignmentFlag.AlignRight)

        root.addStretch(3)
        root.addWidget(form_panel, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addStretch(4)

        self.setLayout(root)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    install_version_badge(app)
    window = LoginWindow()
    window.show()
    sys.exit(app.exec())
