"""Dialog for viewing pitchers grouped by roster level and role."""

from datetime import datetime
from typing import Dict, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from ui.player_profile_dialog import PlayerProfileDialog

from models.base_player import BasePlayer
from models.roster import Roster
from utils.pitcher_role import get_role
from utils.rating_display import rating_display_text


class PitchersWindow(QDialog):
    """Display all pitchers grouped by roster level with tabs for roles."""

    def __init__(self, players: Dict[str, BasePlayer], roster: Roster, parent=None):
        super().__init__(parent)
        self.players = players
        self.roster = roster

        self.setWindowTitle("Pitchers")

        layout = QVBoxLayout()
        layout.addWidget(self._build_level_section("Active (ACT)", roster.act))
        layout.addWidget(self._build_level_section("AAA", roster.aaa))
        layout.addWidget(self._build_level_section("LOW", roster.low))
        layout.addStretch()
        self.setLayout(layout)

        size = self.sizeHint()
        self.resize(size.width() * 2, size.height())

    # ------------------------------------------------------------------
    # Builders
    def _build_level_section(self, title: str, player_ids: Iterable[str]) -> QGroupBox:
        """Create a section showing pitchers for a single level using tabs."""

        group = QGroupBox(title)
        layout = QVBoxLayout()

        groups = {"SP": [], "RP": []}
        for pid in player_ids:
            p = self.players.get(pid)
            role = get_role(p) if p else ""
            if not role:
                continue
            groups[role].append(p)

        tab_widget = QTabWidget()
        for role, players in groups.items():
            if not players:
                continue
            lw = QListWidget()
            for player in players:
                lw.addItem(self._make_pitcher_item(player))
            lw.itemDoubleClicked.connect(self._open_player_profile)
            label = "Starting Pitchers (SP)" if role == "SP" else "Relief Pitchers (RP)"
            tab_widget.addTab(lw, label)

        layout.addWidget(tab_widget)
        group.setLayout(layout)
        return group

    # ------------------------------------------------------------------
    # Helpers
    def _make_pitcher_item(self, p: BasePlayer) -> QListWidgetItem:
        age = self._calculate_age(p.birthdate)
        arm_display = rating_display_text(
            getattr(p, "arm", 0), key="AS", is_pitcher=True
        )
        endurance_display = rating_display_text(
            getattr(p, "endurance", 0), key="EN", is_pitcher=True
        )
        control_display = rating_display_text(
            getattr(p, "control", 0), key="CO", is_pitcher=True
        )
        core = f"AS:{arm_display} EN:{endurance_display} CO:{control_display}"
        role = get_role(p)
        label = f"{p.first_name} {p.last_name} ({age}) - {role or p.primary_position} | {core}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, p.player_id)
        return item

    def _calculate_age(self, birthdate_str: str):
        try:
            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
            today = datetime.today().date()
            return today.year - birthdate.year - (
                (today.month, today.day) < (birthdate.month, birthdate.day)
            )
        except Exception:
            return "?"

    # ------------------------------------------------------------------
    # Player profile dialog
    def _open_player_profile(self, item: QListWidgetItem):
        """Open the player profile dialog for the selected pitcher."""
        pid = item.data(Qt.ItemDataRole.UserRole)
        player = self.players.get(pid)
        if not player:
            return
        PlayerProfileDialog(player, self).exec()

