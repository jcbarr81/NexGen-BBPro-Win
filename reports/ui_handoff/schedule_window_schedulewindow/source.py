from PyQt6.QtWidgets import (
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
import csv
from pathlib import Path

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
    """Dialog displaying the full league schedule as HTML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Schedule")
            self.setGeometry(100, 100, 800, 600)
        except Exception:  # pragma: no cover - stubs without this method
            pass

        layout = QVBoxLayout(self)

        self.viewer = QTableWidget(0, 4)
        try:
            self.viewer.setHorizontalHeaderLabels(["Date", "Away", "Home", "Result"])
            self.viewer.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.viewer.setMinimumHeight(560)
            self.viewer.cellDoubleClicked.connect(self._open_boxscore)
        except Exception:  # pragma: no cover
            pass
        layout.addWidget(self.viewer)

        self._schedule_data: list[dict[str, str]] = []
        if SCHEDULE_FILE.exists():
            with SCHEDULE_FILE.open(newline="") as fh:
                reader = csv.DictReader(fh)
                self._schedule_data = list(reader)

        try:
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
        except Exception:  # pragma: no cover
            pass

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

