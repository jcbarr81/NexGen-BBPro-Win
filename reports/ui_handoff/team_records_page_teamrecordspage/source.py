from __future__ import annotations

from typing import Iterable, List, Tuple
from types import SimpleNamespace

try:
    from PyQt6.QtCore import Qt
except ImportError:  # pragma: no cover - test stubs
    Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(
            AlignLeft=None,
            AlignRight=None,
            AlignVCenter=None,
        ),
        ItemDataRole=SimpleNamespace(UserRole=None),
    )

try:
    from PyQt6.QtWidgets import (
        QWidget,
        QVBoxLayout,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QTabWidget,
        QLabel,
    )
except ImportError:  # pragma: no cover - test stubs
    class _QtDummy:
        EditTrigger = SimpleNamespace(NoEditTriggers=None)
        SelectionBehavior = SimpleNamespace(SelectRows=None)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):
            def _dummy(*_args, **_kwargs):
                return self

            return _dummy

    QWidget = QVBoxLayout = QScrollArea = QTableWidget = QTableWidgetItem = QTabWidget = QLabel = _QtDummy

    class QHeaderView:  # type: ignore[too-many-ancestors]
        class ResizeMode:
            Stretch = None
            ResizeToContents = None

from .components import Card, section_title
from .stat_helpers import format_number
from services.record_book import team_record_book

_BATTING_LEADERS: List[Tuple[str, str, bool, int]] = [
    ("AVG", "avg", True, 3),
    ("HR", "hr", True, 0),
    ("RBI", "rbi", True, 0),
    ("SB", "sb", True, 0),
    ("OPS", "ops", True, 3),
]

_PITCHING_LEADERS: List[Tuple[str, str, bool, int]] = [
    ("ERA", "era", False, 2),
    ("WHIP", "whip", False, 2),
    ("Wins", "w", True, 0),
    ("Strikeouts", "so", True, 0),
    ("Saves", "sv", True, 0),
]


class TeamRecordsPage(QWidget):
    """Owner dashboard page for team records and leaders."""

    def __init__(self, dashboard) -> None:
        super().__init__()
        self._dashboard = dashboard

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        self.records_card = Card()
        self.records_card.layout().addWidget(section_title("Team Records"))
        self.records_table = QTableWidget(0, 3)
        self._configure_table(self.records_table, ["Record", "Value", "Season"])
        self.records_card.layout().addWidget(self.records_table)
        layout.addWidget(self.records_card)

        self.leaders_card = Card()
        self.leaders_card.layout().addWidget(section_title("Team Leaders"))
        self.leaders_tabs = QTabWidget()
        self.batting_table = QTableWidget(0, 3)
        self.pitching_table = QTableWidget(0, 3)
        self._configure_table(self.batting_table, ["Category", "Leader", "Value"])
        self._configure_table(self.pitching_table, ["Category", "Leader", "Value"])
        self.leaders_tabs.addTab(self.batting_table, "Batting")
        self.leaders_tabs.addTab(self.pitching_table, "Pitching")
        self.leaders_card.layout().addWidget(self.leaders_tabs)
        layout.addWidget(self.leaders_card)
        layout.addStretch()

        try:
            self.batting_table.itemDoubleClicked.connect(
                lambda item, table=self.batting_table: self._open_player_from_table(table, item)
            )
            self.pitching_table.itemDoubleClicked.connect(
                lambda item, table=self.pitching_table: self._open_player_from_table(table, item)
            )
        except Exception:
            pass

    def refresh(self) -> None:
        self._refresh_records()
        self._refresh_leaders()

    def _refresh_records(self) -> None:
        team_id = getattr(self._dashboard, "team_id", None)
        records = team_record_book(str(team_id)) if team_id else []
        try:
            self.records_table.setRowCount(len(records))
        except Exception:
            return
        for row_idx, entry in enumerate(records):
            label = str(entry.get("label") or "--")
            value = str(entry.get("value_text") or entry.get("value") or "--")
            season = str(entry.get("season_label") or entry.get("season_id") or "-")
            self.records_table.setItem(row_idx, 0, QTableWidgetItem(label))
            self.records_table.setItem(row_idx, 1, QTableWidgetItem(value))
            self.records_table.setItem(row_idx, 2, QTableWidgetItem(season))

    def _refresh_leaders(self) -> None:
        hitters, pitchers = self._team_player_groups()
        self._populate_leader_table(self.batting_table, hitters, _BATTING_LEADERS)
        self._populate_leader_table(self.pitching_table, pitchers, _PITCHING_LEADERS)

    def _team_player_groups(self) -> tuple[List[object], List[object]]:
        roster = getattr(self._dashboard, "roster", None)
        players = getattr(self._dashboard, "players", {}) or {}
        ids: List[str] = []
        if roster is not None:
            ids = list(getattr(roster, "act", []) or [])
        if not ids:
            ids = list(players.keys())
        pool = [players[pid] for pid in ids if pid in players]
        hitters = [p for p in pool if not getattr(p, "is_pitcher", False)]
        pitchers = [p for p in pool if getattr(p, "is_pitcher", False)]
        return hitters, pitchers

    def _populate_leader_table(
        self,
        table: QTableWidget,
        players: Iterable[object],
        categories: List[Tuple[str, str, bool, int]],
    ) -> None:
        rows = list(categories)
        try:
            table.setRowCount(len(rows))
        except Exception:
            return
        for row_idx, (label, key, descending, decimals) in enumerate(rows):
            leader, value = self._leader_for_category(players, key, descending=descending)
            value_text = self._format_value(value, decimals)
            leader_name = "--"
            leader_id = ""
            if leader is not None:
                leader_name = f"{getattr(leader, 'first_name', '')} {getattr(leader, 'last_name', '')}".strip()
                leader_id = getattr(leader, "player_id", "") or ""
            cat_item = QTableWidgetItem(label)
            name_item = QTableWidgetItem(leader_name or "--")
            value_item = QTableWidgetItem(value_text)
            try:
                name_item.setData(Qt.ItemDataRole.UserRole, leader_id)
            except Exception:
                pass
            table.setItem(row_idx, 0, cat_item)
            table.setItem(row_idx, 1, name_item)
            table.setItem(row_idx, 2, value_item)

    def _leader_for_category(
        self,
        players: Iterable[object],
        key: str,
        *,
        descending: bool,
    ) -> tuple[object | None, float | None]:
        best_player = None
        best_value = None
        for player in players:
            stats = getattr(player, "season_stats", {}) or {}
            raw = stats.get(key)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if best_value is None:
                best_value = value
                best_player = player
                continue
            if descending and value > best_value:
                best_value = value
                best_player = player
            if not descending and value < best_value:
                best_value = value
                best_player = player
        return best_player, best_value

    def _format_value(self, value: float | None, decimals: int) -> str:
        if value is None:
            return "--"
        try:
            return format_number(value, decimals=decimals)
        except Exception:
            return str(value)

    def _open_player_from_table(self, table: QTableWidget, item: QTableWidgetItem) -> None:
        try:
            row = item.row()
            name_cell = table.item(row, 1)
            player_id = name_cell.data(Qt.ItemDataRole.UserRole) if name_cell else None
        except Exception:
            player_id = None
        if not player_id:
            return
        opener = getattr(self._dashboard, "open_player_profile", None)
        if callable(opener):
            try:
                opener(str(player_id))
            except Exception:
                pass

    def _configure_table(self, table: QTableWidget, headers: List[str]) -> None:
        try:
            table.setHorizontalHeaderLabels(headers)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        except Exception:
            pass
