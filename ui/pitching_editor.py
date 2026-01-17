from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout, QGridLayout, QComboBox, QPushButton, QMessageBox
from PyQt6.QtCore import QEvent
import csv

from utils.pitcher_role import get_display_role, get_role
from utils.pitching_autofill import autofill_pitching_staff
from utils.path_utils import get_base_dir

class PitchingEditor(QDialog):
    def __init__(self, team_id):
        super().__init__()
        self.team_id = team_id
        self.setWindowTitle("Pitching Staff Editor")
        self.setMinimumSize(500, 500)

        layout = QVBoxLayout(self)

        self.roles = ["SP1", "SP2", "SP3", "SP4", "SP5", "LR", "MR", "SU", "CL"]
        self.pitcher_dropdowns = {}

        self.players_dict = self.load_players_dict()
        self.act_ids = self.get_act_level_ids()

        grid = QGridLayout()
        for i, role in enumerate(self.roles):
            label = QLabel(role)
            dropdown = QComboBox()
            dropdown.installEventFilter(self)
            for pid, pdata in self.players_dict.items():
                if pid in self.act_ids and get_role(pdata):
                    dropdown.addItem(pdata["name"], userData=pid)
            self.pitcher_dropdowns[role] = dropdown
            grid.addWidget(label, i, 0)
            grid.addWidget(dropdown, i, 1)

        layout.addLayout(grid)

        save_btn = QPushButton("Save Pitching Staff")
        save_btn.clicked.connect(self.save_pitching_staff)
        layout.addWidget(save_btn)

        autofill_btn = QPushButton("Auto-Fill Staff")
        autofill_btn.clicked.connect(self.autofill_staff)
        layout.addWidget(autofill_btn)

        clear_btn = QPushButton("Clear Staff")
        clear_btn.clicked.connect(self.clear_staff)
        layout.addWidget(clear_btn)

        self._baseline = []
        self.load_pitching_staff()

    def _player_lookup(self):
        cache = getattr(self, "_player_lookup_cache", None)
        if cache is None:
            try:
                from utils.player_loader import load_players_from_csv
                cache = {
                    p.player_id: p for p in load_players_from_csv("data/players.csv")
                }
            except Exception:
                cache = {}
            self._player_lookup_cache = cache
        return cache

    def _open_player_profile(self, player_id):
        if not player_id:
            return
        player = self._player_lookup().get(player_id)
        if player is None:
            return
        try:
            from ui.player_profile_dialog import PlayerProfileDialog
            PlayerProfileDialog(player, self).exec()
        except Exception:
            pass

    def load_players_dict(self):
        path = get_base_dir() / "data" / "players.csv"
        players = {}
        if path.exists():
            with path.open(newline='', encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    pid = row["player_id"].strip()
                    # Show the same role label used in the roster views.
                    display_role = get_display_role(row)
                    display_pos = display_role or row["primary_position"]
                    name = f"{row['first_name']} {row['last_name']} ({display_pos})"
                    players[pid] = {
                        "name": name,
                        "primary_position": row["primary_position"],
                        "role": row.get("role", ""),
                        "endurance": row.get("endurance", ""),
                        "preferred_pitching_role": row.get("preferred_pitching_role") or "",
                    }
        return players

    def get_act_level_ids(self):
        act_ids = set()
        path = get_base_dir() / "data" / "rosters" / f"{self.team_id}.csv"
        if path.exists():
            with path.open(newline='', encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 2 and row[1].strip().upper() == "ACT":
                        act_ids.add(row[0].strip())
        return act_ids

    def save_pitching_staff(self):
        used_ids = set()
        for role, dropdown in self.pitcher_dropdowns.items():
            player_id = dropdown.currentData()
            if player_id in used_ids:
                QMessageBox.warning(self, "Validation Error", f"{self.players_dict[player_id]['name']} is assigned to multiple roles.")
                return False
            if player_id:
                used_ids.add(player_id)
        path = get_base_dir() / "data" / "rosters" / f"{self.team_id}_pitching.csv"
        try:
            if path.exists():
                try:
                    path.chmod(0o644)  # ensure writable if previously locked
                except OSError:
                    pass
            with path.open("w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                for role, dropdown in self.pitcher_dropdowns.items():
                    player_id = dropdown.currentData()
                    if player_id:
                        writer.writerow([player_id, role])
            self._refresh_baseline()
            QMessageBox.information(self, "Saved", "Pitching staff saved successfully.")
            return True
        except PermissionError as exc:
            QMessageBox.warning(self, "Permission Denied", f"Cannot save to {path}.\n{exc}")
            return False

    def load_pitching_staff(self):
        path = get_base_dir() / "data" / "rosters" / f"{self.team_id}_pitching.csv"
        if path.exists():
            with path.open(newline='', encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 2:
                        player_id, role = row[0], row[1]
                        if role in self.pitcher_dropdowns:
                            dropdown = self.pitcher_dropdowns[role]
                            for i in range(dropdown.count()):
                                if dropdown.itemData(i) == player_id:
                                    dropdown.setCurrentIndex(i)
                                    break
        self._refresh_baseline()

    def autofill_staff(self):
        available = [
            (pid, pdata)
            for pid, pdata in self.players_dict.items()
            if pid in self.act_ids and get_role(pdata)
        ]
        assignments = autofill_pitching_staff(available)
        for role, dropdown in self.pitcher_dropdowns.items():
            pid = assignments.get(role)
            if pid is None:
                dropdown.setCurrentIndex(-1)
                continue
            for i in range(dropdown.count()):
                if dropdown.itemData(i) == pid:
                    dropdown.setCurrentIndex(i)
                    break

    def clear_staff(self):
        for dropdown in self.pitcher_dropdowns.values():
            dropdown.setCurrentIndex(-1)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt signature
        if event.type() == QEvent.Type.MouseButtonDblClick:
            if isinstance(obj, QComboBox):
                self._open_player_profile(obj.currentData())
                return True
        return super().eventFilter(obj, event)

    def _snapshot_staff(self):
        snapshot = []
        for role in self.roles:
            dropdown = self.pitcher_dropdowns.get(role)
            snapshot.append((role, dropdown.currentData() if dropdown else None))
        return snapshot

    def _refresh_baseline(self):
        self._baseline = self._snapshot_staff()

    def _has_unsaved_changes(self) -> bool:
        return self._snapshot_staff() != getattr(self, "_baseline", [])

    def closeEvent(self, event):  # noqa: N802 - Qt signature
        if not self._has_unsaved_changes():
            super().closeEvent(event)
            return

        choice = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved pitching staff changes. Save before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Save:
            if self.save_pitching_staff():
                super().closeEvent(event)
            else:
                event.ignore()
        elif choice == QMessageBox.StandardButton.Discard:
            super().closeEvent(event)
        else:
            event.ignore()
