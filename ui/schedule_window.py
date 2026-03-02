from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
import csv
from datetime import datetime

try:
    from PyQt6.QtCore import Qt
except Exception:  # pragma: no cover - tests provide stub
    class Qt:
        class ItemDataRole:
            UserRole = 0

from .boxscore_window import BoxScoreWindow
from utils.path_utils import ActivePath, get_data_dir

SCHEDULE_FILE = ActivePath(lambda: get_data_dir() / "schedule.csv")


class ScheduleWindow(QDialog):
    """Dialog displaying the full league schedule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Schedule")
            self.setMinimumSize(980, 700)
            self.setGeometry(100, 100, 1080, 780)
        except Exception:  # pragma: no cover - stubs without this method
            pass

        layout = QVBoxLayout(self)
        self._safe_ui_call(layout, "setContentsMargins", 12, 12, 12, 12)
        self._safe_ui_call(layout, "setSpacing", 10)

        status_group = QGroupBox("Schedule Snapshot")
        status_layout = QVBoxLayout()
        self.status_label = QLabel("Loading schedule...")
        self._safe_ui_call(self.status_label, "setObjectName", "StatusLabel")
        self._safe_ui_call(self.status_label, "setWordWrap", True)
        status_layout.addWidget(self.status_label)
        status_hint = QLabel(
            "Double-click a result cell to open the linked box score."
        )
        self._safe_ui_call(status_hint, "setWordWrap", True)
        status_layout.addWidget(status_hint)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        action_group = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        self._safe_ui_call(action_layout, "setSpacing", 8)
        self.refresh_button = QPushButton("Refresh Schedule")
        self._safe_ui_call(self.refresh_button, "setObjectName", "Primary")
        self.refresh_button.clicked.connect(self._refresh_schedule)
        action_layout.addWidget(self.refresh_button)
        self.last_updated_label = QLabel("Last updated: --")
        self._safe_ui_call(self.last_updated_label, "setWordWrap", True)
        action_layout.addWidget(self.last_updated_label)
        action_layout.addStretch(1)
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)

        self.viewer = QTableWidget(0, 4)
        try:
            self.viewer.setHorizontalHeaderLabels(["Date", "Away", "Home", "Result"])
            self.viewer.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.viewer.setSelectionBehavior(
                QTableWidget.SelectionBehavior.SelectRows
            )
            self.viewer.setAlternatingRowColors(True)
            self.viewer.setMinimumHeight(580)
            self.viewer.cellDoubleClicked.connect(self._open_boxscore)
        except Exception:  # pragma: no cover
            pass
        layout.addWidget(self.viewer)

        self._schedule_data: list[dict[str, str]] = []
        self._refresh_schedule()

    def _refresh_schedule(self) -> None:
        self._schedule_data = self._load_schedule_data()
        self._populate_schedule_table()
        self._update_schedule_status()

    def _load_schedule_data(self) -> list[dict[str, str]]:
        if not SCHEDULE_FILE.exists():
            return []
        try:
            with SCHEDULE_FILE.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                return list(reader)
        except Exception:
            return []

    def _populate_schedule_table(self) -> None:
        if not hasattr(self, "viewer"):
            return

        try:
            if not self._schedule_data:
                self.viewer.setRowCount(1)
                self.viewer.setItem(0, 0, QTableWidgetItem("No schedule available"))
                self.viewer.setItem(0, 1, QTableWidgetItem(""))
                self.viewer.setItem(0, 2, QTableWidgetItem(""))
                self.viewer.setItem(0, 3, QTableWidgetItem(""))
                return
            self.viewer.setRowCount(len(self._schedule_data))
            for row, game in enumerate(self._schedule_data):
                for col, key in enumerate(["date", "away", "home", "result"]):
                    item = QTableWidgetItem(game.get(key, ""))
                    if key == "result":
                        try:
                            item.setData(Qt.ItemDataRole.UserRole, game.get("boxscore", ""))
                        except Exception:  # pragma: no cover - stub fallback
                            pass
                    self.viewer.setItem(row, col, item)
            self.viewer.resizeColumnsToContents()
        except Exception:  # pragma: no cover
            pass

    def _update_schedule_status(self) -> None:
        if hasattr(self, "status_label"):
            if not self._schedule_data:
                self.status_label.setText("No schedule entries found.")
            else:
                first_date = self._schedule_data[0].get("date", "")
                last_date = self._schedule_data[-1].get("date", "")
                self.status_label.setText(
                    f"{len(self._schedule_data)} game(s) loaded. "
                    f"Range: {first_date or '--'} to {last_date or '--'}."
                )
        if hasattr(self, "last_updated_label"):
            stamp = datetime.now().strftime("%H:%M:%S")
            self.last_updated_label.setText(f"Last updated: {stamp}")

    def _open_boxscore(self, row: int, column: int) -> None:
        """Open box score for the selected game if available."""
        if column != 3:
            return
        item = None
        try:
            item = self.viewer.item(row, column)
        except Exception:  # pragma: no cover - stub fallback
            item = None
        path = None
        if item is not None:
            try:
                path = item.data(Qt.ItemDataRole.UserRole)
            except Exception:  # pragma: no cover
                path = None
        if not path and 0 <= row < len(self._schedule_data):
            game = self._schedule_data[row]
            path = game.get("boxscore")
        if path:
            dlg = BoxScoreWindow(path, self)
            try:
                dlg.exec()
            except Exception:  # pragma: no cover
                pass

    @staticmethod
    def _safe_ui_call(target, method: str, *args) -> None:
        fn = getattr(target, method, None)
        if callable(fn):
            try:
                fn(*args)
            except Exception:
                return

