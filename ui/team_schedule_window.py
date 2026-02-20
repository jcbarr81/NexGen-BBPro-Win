import calendar
import csv
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
try:  # pragma: no cover - allow tests without full PyQt6
    from PyQt6.QtGui import QColor
except Exception:  # pragma: no cover
    QColor = None
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .boxscore_window import BoxScoreWindow
from utils.path_utils import ActivePath, get_data_dir

SCHEDULE_FILE = ActivePath(lambda: get_data_dir() / "schedule.csv")


class TeamScheduleWindow(QDialog):
    """Dialog displaying a team's schedule in a calendar style."""

    def __init__(self, team_id: str, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("Team Schedule")
            self.setGeometry(100, 100, 800, 600)
        except Exception:  # pragma: no cover
            pass

        layout = QVBoxLayout(self)

        nav = QHBoxLayout()
        self.prev_button = QPushButton("<")
        self.next_button = QPushButton(">")
        self.month_label = QLabel()
        nav.addWidget(self.prev_button)
        nav.addWidget(self.month_label)
        nav.addWidget(self.next_button)
        try:
            layout.addLayout(nav)
        except Exception:  # pragma: no cover - test stubs
            pass

        self.viewer = QTableWidget(6, 7)
        try:
            self.viewer.setHorizontalHeaderLabels(
                ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            )
            self.viewer.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.viewer.setMinimumHeight(560)
            self.viewer.cellDoubleClicked.connect(self._open_boxscore)
            # Enlarge cells for better readability
            self.viewer.horizontalHeader().setDefaultSectionSize(110)
            self.viewer.verticalHeader().setDefaultSectionSize(90)
        except Exception:  # pragma: no cover
            pass
        try:
            layout.addWidget(self.viewer)
        except Exception:  # pragma: no cover
            pass

        self.prev_button.clicked.connect(lambda: self._change_month(-1))
        self.next_button.clicked.connect(lambda: self._change_month(1))

        self._schedule: list[dict[str, str]] = []
        self._schedule_map: dict[str, dict[str, str]] = {}
        if SCHEDULE_FILE.exists():
            with SCHEDULE_FILE.open(newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if row.get("home") == team_id or row.get("away") == team_id:
                        opponent = (
                            row.get("away")
                            if row.get("home") == team_id
                            else row.get("home")
                        )
                        venue = "vs" if row.get("home") == team_id else "at"
                        entry = {
                            "date": row.get("date", ""),
                            "opponent": f"{venue} {opponent}",
                            "result": row.get("result", ""),
                            "boxscore": row.get("boxscore", ""),
                        }
                        self._schedule.append(entry)
                        self._schedule_map[entry["date"]] = entry

        if self._schedule:
            first = datetime.strptime(self._schedule[0]["date"], "%Y-%m-%d")
            self._month = first.replace(day=1)
            self._populate_month()
        else:
            if "_month" in self.__dict__:
                del self.__dict__["_month"]
            self.month_label.setText("")
            self.viewer.setRowCount(1)
            self.viewer.setColumnCount(1)
            item = QTableWidgetItem("No schedule available")
            try:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.viewer.horizontalHeader().hide()
                self.viewer.verticalHeader().hide()
                self.prev_button.setEnabled(False)
                self.next_button.setEnabled(False)
            except Exception:  # pragma: no cover
                pass
            self.viewer.setItem(0, 0, item)

    def _change_month(self, delta: int) -> None:
        month = self._month.month - 1 + delta
        year = self._month.year + month // 12
        month = month % 12 + 1
        self._month = self._month.replace(year=year, month=month, day=1)
        self._populate_month()

    def _populate_month(self) -> None:
        self.month_label.setText(self._month.strftime("%B %Y"))
        try:
            self.viewer.clearContents()
        except Exception:  # pragma: no cover
            pass
        days = calendar.monthrange(self._month.year, self._month.month)[1]
        first_weekday = (self._month.weekday() + 1) % 7
        row = 0
        col = first_weekday
        for day in range(1, days + 1):
            date_obj = self._month.replace(day=day)
            date_str = date_obj.strftime("%Y-%m-%d")
            game = self._schedule_map.get(date_str)
            text = str(day)
            if game:
                text += f"\n{game['opponent']}"
                if game.get("result"):
                    text += f"\n{game['result']}"
            item = QTableWidgetItem(text)
            if QColor is not None:
                # Ensure text remains legible against colored backgrounds
                item.setForeground(QColor("black"))
                if game:
                    color = (
                        QColor("#aaaaff")
                        if game["opponent"].startswith("vs")
                        else QColor("#dddddd")
                    )
                    item.setBackground(color)
            try:
                item.setData(Qt.ItemDataRole.UserRole, date_str)
            except Exception:  # pragma: no cover
                pass
            self.viewer.setItem(row, col, item)
            col += 1
            if col > 6:
                col = 0
                row += 1

    def _open_boxscore(self, row: int, column: int) -> None:
        item = self.viewer.item(row, column)
        if not item:
            return
        date_str = item.data(Qt.ItemDataRole.UserRole)
        game = self._schedule_map.get(date_str)
        if not game:
            return
        path = game.get("boxscore")
        if path:
            dlg = BoxScoreWindow(path, self)
            try:
                dlg.exec()
            except Exception:  # pragma: no cover
                pass
