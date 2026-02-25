from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.transaction_log import load_transactions
from services.unified_data_service import get_unified_data_service


class TransactionsWindow(QDialog):
    """Dialog displaying recent roster transactions with simple filters."""

    COLUMNS = [
        "Timestamp",
        "Season Date",
        "Team",
        "Player",
        "Action",
        "Movement",
        "Counterparty",
        "Details",
    ]

    ACTION_FILTERS = [
        ("All", None),
        ("Draft", {"draft"}),
        ("Cut", {"cut"}),
        ("Trade In", {"trade_in"}),
        ("Trade Out", {"trade_out"}),
    ]

    def __init__(self, team_id: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._initial_team = team_id
        self._initial_team_used = False
        self.setWindowTitle("Transactions")
        self.resize(900, 420)

        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Team:"))
        self.team_box = QComboBox()
        filters.addWidget(self.team_box)
        filters.addWidget(QLabel("Action:"))
        self.action_box = QComboBox()
        for label, _ in self.ACTION_FILTERS:
            self.action_box.addItem(label)
        filters.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        filters.addWidget(refresh_btn)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        refresh_btn.clicked.connect(self._reload)
        self.team_box.currentIndexChanged.connect(self._reload)
        self.action_box.currentIndexChanged.connect(self._reload)

        self._service = get_unified_data_service()
        self._event_unsubscribes: list[callable] = []
        self._register_event_listeners()

        self._populate_team_filter()
        self._reload()

    def _populate_team_filter(self, preserve_selection: bool = False) -> None:
        rows = load_transactions()
        team_ids = sorted({row.get("team_id", "") for row in rows if row.get("team_id")})
        self.team_box.blockSignals(True)
        previous_team = self.team_box.currentData() if preserve_selection else None
        self.team_box.clear()
        self.team_box.addItem("All Teams", None)
        for tid in team_ids:
            self.team_box.addItem(tid, tid)
        target_team = None
        if preserve_selection and previous_team in team_ids:
            target_team = previous_team
        elif not self._initial_team_used and self._initial_team and self._initial_team in team_ids:
            target_team = self._initial_team
            self._initial_team_used = True
        if target_team is not None:
            index = self.team_box.findData(target_team)
            if index >= 0:
                self.team_box.setCurrentIndex(index)
        else:
            self.team_box.setCurrentIndex(0)
        self.team_box.blockSignals(False)

    def _register_event_listeners(self) -> None:
        """Watch for transaction updates and refresh the grid automatically."""

        bus = self._service.events

        def _schedule_refresh(_payload=None) -> None:
            QTimer.singleShot(0, self._handle_external_update)

        for topic in ("transactions.updated", "transactions.invalidated"):
            try:
                self._event_unsubscribes.append(bus.subscribe(topic, _schedule_refresh))
            except Exception:  # pragma: no cover - defensive
                pass

    def _handle_external_update(self) -> None:
        if not self.isVisible():
            return
        self._populate_team_filter(preserve_selection=True)
        self._reload()

    def _reload(self) -> None:
        team_value = self.team_box.currentData()
        action_idx = max(self.action_box.currentIndex(), 0)
        _, action_filter = self.ACTION_FILTERS[action_idx]

        rows = load_transactions(
            team_id=team_value,
            actions=action_filter,
        )
        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            movement = ""
            if row.get("from_level") or row.get("to_level"):
                movement = f"{row.get('from_level', '')} -> {row.get('to_level', '')}"
            values = [
                row.get("timestamp", ""),
                row.get("season_date", ""),
                row.get("team_id", ""),
                row.get("player_name", row.get("player_id", "")),
                row.get("action", "").replace("_", " ").title(),
                movement,
                row.get("counterparty", ""),
                row.get("details", ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col in (0, 1):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_idx, col, item)
        self.table.resizeColumnsToContents()

    def closeEvent(self, event):  # pragma: no cover - GUI wiring
        for unsubscribe in getattr(self, "_event_unsubscribes", []):
            try:
                unsubscribe()
            except Exception:
                pass
        self._event_unsubscribes = []
        super().closeEvent(event)


__all__ = ["TransactionsWindow"]
