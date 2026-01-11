from __future__ import annotations

from typing import Dict

from PyQt6.QtWidgets import (
    QDialog,
    QTabWidget,
    QVBoxLayout,
)
from PyQt6.QtCore import Qt

from models.base_player import BasePlayer
from models.roster import Roster
from utils.pitcher_role import get_display_role, get_role
from utils.rating_display import overall_rating
from ui.player_profile_dialog import PlayerProfileDialog

# Reuse the existing retro roster tables for consistent look/feel
from .position_players_dialog import RosterTable as PosRosterTable
from .pitchers_dialog import RosterTable as PitRosterTable, PITCH_RATINGS


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

        # Pitchers tab ---------------------------------------------------
        pit_rows = self._build_pitcher_rows()
        self.pit_table = PitRosterTable(pit_rows)
        self.pit_table.itemDoubleClicked.connect(self._open_player_profile)

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
        seq = 1
        for slot, ids in (("ACT", self.roster.act), ("AAA", self.roster.aaa), ("LOW", self.roster.low)):
            for pid in ids:
                p = self.players.get(pid)
                if not p or get_role(p):
                    continue
                # Same columns as ui.position_players_dialog
                age = self._safe_age(getattr(p, "birthdate", ""))
                rows.append([
                    seq,
                    f"{p.last_name}, {p.first_name}",
                    overall_rating(p),
                    age,
                    slot,
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
        seq = 1
        for slot, ids in (("ACT", self.roster.act), ("AAA", self.roster.aaa), ("LOW", self.roster.low)):
            for pid in ids:
                p = self.players.get(pid)
                role = get_role(p) if p else ""
                if not p or not role:
                    continue
                display_role = get_display_role(p)
                pitch_vals = [getattr(p, code, "") if getattr(p, code, 0) else "" for code in PITCH_RATINGS]
                rows.append([
                    seq,
                    f"{p.last_name}, {p.first_name}",
                    overall_rating(p),
                    slot,
                    display_role,
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
