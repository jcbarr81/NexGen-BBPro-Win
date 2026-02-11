from __future__ import annotations

from typing import Dict

from PyQt6.QtWidgets import (
    QDialog,
    QTabWidget,
    QVBoxLayout,
    QTableWidgetItem,
    QMenu,
)
from PyQt6.QtCore import Qt, QModelIndex

from models.base_player import BasePlayer
from models.roster import Roster
from services.training_settings import load_training_settings, set_player_training_weights
from utils.pitcher_role import get_display_role, get_role
from utils.rating_display import overall_rating
from ui.player_profile_dialog import PlayerProfileDialog
from ui.training_focus_dialog import TrainingFocusDialog

# Reuse the existing retro roster tables for consistent look/feel
from .position_players_dialog import (
    RosterTable as PosRosterTable,
    FOCUS_COLUMN as POS_FOCUS_COLUMN,
)
from .pitchers_dialog import (
    RosterTable as PitRosterTable,
    PITCH_RATINGS,
    FOCUS_COLUMN as PIT_FOCUS_COLUMN,
)


class PlayerBrowserDialog(QDialog):
    """Tabbed browser for Position Players and Pitchers.

    Uses the existing retro-styled tables from the dedicated dialogs to
    ensure visual and behavioural parity while consolidating entry points.
    """

    def __init__(
        self,
        players: Dict[str, BasePlayer],
        roster: Roster,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.players = players
        self.roster = roster

        self.setWindowTitle("Players")
        self.resize(1100, 680)

        tabs = QTabWidget(self)

        # Position players tab ------------------------------------------
        pos_rows = self._build_position_rows()
        self.pos_table = PosRosterTable(pos_rows, use_position_context=True)
        self.pos_table.itemDoubleClicked.connect(self._open_player_profile)
        self.pos_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pos_table.customContextMenuRequested.connect(
            lambda pos: self._show_training_menu(self.pos_table, pos)
        )

        # Pitchers tab ---------------------------------------------------
        pit_rows = self._build_pitcher_rows()
        self.pit_table = PitRosterTable(pit_rows)
        self.pit_table.itemDoubleClicked.connect(self._open_player_profile)
        self.pit_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pit_table.customContextMenuRequested.connect(
            lambda pos: self._show_training_menu(self.pit_table, pos)
        )

        tabs.addTab(self.pos_table, "Position Players")
        tabs.addTab(self.pit_table, "Pitchers")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(tabs)

    # ------------------------------------------------------------------
    # Row builders (mirroring existing dialogs)
    def _build_position_rows(self):
        rows = []
        settings = load_training_settings()
        seq = 1
        for slot, ids in (("ACT", self.roster.act), ("AAA", self.roster.aaa), ("LOW", self.roster.low)):
            for pid in ids:
                p = self.players.get(pid)
                if not p or get_role(p):
                    continue
                # Same columns as ui.position_players_dialog
                age = self._safe_age(getattr(p, "birthdate", ""))
                focus_label = self._focus_label(settings, pid)
                rows.append([
                    seq,
                    f"{p.last_name}, {p.first_name}",
                    overall_rating(p),
                    age,
                    slot,
                    focus_label,
                    p.primary_position,
                    getattr(p, "bats", ""),
                    getattr(p, "ch", 0),
                    getattr(p, "ph", 0),
                    getattr(p, "sp", 0),
                    getattr(p, "fa", 0),
                    getattr(p, "arm", 0),
                    pid,
                ])
                seq += 1
        return rows

    def _build_pitcher_rows(self):
        rows = []
        settings = load_training_settings()
        seq = 1
        for slot, ids in (("ACT", self.roster.act), ("AAA", self.roster.aaa), ("LOW", self.roster.low)):
            for pid in ids:
                p = self.players.get(pid)
                role = get_role(p) if p else ""
                if not p or not role:
                    continue
                display_role = get_display_role(p)
                pitch_vals = [getattr(p, code, "") if getattr(p, code, 0) else "" for code in PITCH_RATINGS]
                focus_label = self._focus_label(settings, pid)
                rows.append([
                    seq,
                    f"{p.last_name}, {p.first_name}",
                    overall_rating(p),
                    slot,
                    display_role,
                    focus_label,
                    getattr(p, "bats", ""),
                    getattr(p, "arm", 0),
                    getattr(p, "endurance", 0),
                    getattr(p, "control", 0),
                    *pitch_vals,
                    getattr(p, "movement", 0),
                    getattr(p, "fa", 0),
                    pid,
                ])
                seq += 1
        return rows

    # ------------------------------------------------------------------
    def _open_player_profile(self, item):
        row = item.row()
        table = item.tableWidget()
        if table is self.pos_table and item.column() == POS_FOCUS_COLUMN:
            pid = self._player_id_for_row(table, row)
            if pid:
                self._open_training_focus(pid)
            return
        if table is self.pit_table and item.column() == PIT_FOCUS_COLUMN:
            pid = self._player_id_for_row(table, row)
            if pid:
                self._open_training_focus(pid)
            return
        # Both tables set player id on first column's UserRole
        first = item.tableWidget().item(row, 0)
        if not first:
            return
        pid = first.data(Qt.ItemDataRole.UserRole)
        player = self.players.get(pid)
        if not player:
            return
        PlayerProfileDialog(player, self).exec()

    def _safe_age(self, birthdate: str):
        from datetime import datetime
        try:
            b = datetime.strptime(birthdate, "%Y-%m-%d").date()
            t = datetime.today().date()
            return t.year - b.year - ((t.month, t.day) < (b.month, b.day))
        except Exception:
            return "?"

    def _focus_label(self, settings, player_id: str) -> str:
        pid = str(player_id)
        if pid in settings.player_overrides:
            return "Player"
        team_id = getattr(self.roster, "team_id", None)
        if team_id and str(team_id) in settings.team_overrides:
            return "Team"
        return "League"

    def _show_training_menu(self, table, pos) -> None:
        row = table.rowAt(pos.y())
        if row >= 0:
            selection = table.selectionModel()
            if selection is None or not selection.isRowSelected(row, QModelIndex()):
                table.selectRow(row)
        player_ids = self._selected_player_ids(table)
        if not player_ids:
            return
        menu = QMenu(self)
        edit_action = menu.addAction("Training Focus...")
        bulk_action = menu.addAction("Apply Training Focus to Selected...")
        edit_action.setEnabled(len(player_ids) == 1)
        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == edit_action and len(player_ids) == 1:
            self._open_training_focus(player_ids[0])
        elif action == bulk_action:
            self._apply_bulk_training_focus(player_ids)

    def _selected_player_ids(self, table) -> list[str]:
        selection = table.selectionModel()
        if selection is None:
            return []
        rows = selection.selectedRows()
        player_ids: list[str] = []
        for index in rows:
            pid = self._player_id_for_row(table, index.row())
            if pid:
                player_ids.append(pid)
        return player_ids

    def _player_id_for_row(self, table, row: int) -> str:
        pid_item = table.item(row, 0)
        if not pid_item:
            return ""
        pid = pid_item.data(Qt.ItemDataRole.UserRole)
        return str(pid) if pid else ""

    def _open_training_focus(self, player_id: str) -> None:
        player = self.players.get(player_id)
        if not player:
            return
        player_name = f"{player.first_name} {player.last_name}".strip()
        dialog = TrainingFocusDialog(
            parent=self,
            mode="player",
            player_id=str(player_id),
            player_name=player_name,
            team_id=getattr(self.roster, "team_id", None),
        )
        if dialog.exec():
            self._refresh_focus_columns([player_id])

    def _apply_bulk_training_focus(self, player_ids: list[str]) -> None:
        if not player_ids:
            return
        label = f"Apply these allocations to {len(player_ids)} players."
        dialog = TrainingFocusDialog(
            parent=self,
            mode="bulk",
            team_id=getattr(self.roster, "team_id", None),
            bulk_label=label,
        )
        if not dialog.exec():
            return
        weights = dialog.result_weights
        if not weights:
            return
        hitters, pitchers = weights
        for pid in player_ids:
            set_player_training_weights(pid, hitters, pitchers)
        self._refresh_focus_columns(player_ids)

    def _refresh_focus_columns(self, player_ids: list[str] | None = None) -> None:
        settings = load_training_settings()
        target = {str(pid) for pid in player_ids} if player_ids else None
        for table, focus_col in (
            (self.pos_table, POS_FOCUS_COLUMN),
            (self.pit_table, PIT_FOCUS_COLUMN),
        ):
            for row in range(table.rowCount()):
                pid = self._player_id_for_row(table, row)
                if not pid:
                    continue
                if target is not None and pid not in target:
                    continue
                label = self._focus_label(settings, pid)
                item = table.item(row, focus_col)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                    table.setItem(row, focus_col, item)
                item.setData(Qt.ItemDataRole.DisplayRole, label)
