from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QVBoxLayout,
    QGridLayout,
    QComboBox,
    QPushButton,
    QMessageBox,
    QGroupBox,
    QHBoxLayout,
)
try:
    from PyQt6.QtCore import QEvent, QTimer
except ImportError:  # pragma: no cover - fallback for lightweight test stubs
    try:
        from PyQt6.QtCore import QTimer
    except ImportError:  # pragma: no cover - fallback when QTimer is not stubbed
        class _DummySignal:
            def connect(self, *_args, **_kwargs) -> None:
                return None

        class QTimer:  # type: ignore[too-many-ancestors]
            def __init__(self, *_args, **_kwargs) -> None:
                self.timeout = _DummySignal()

            def setSingleShot(self, *_args, **_kwargs) -> None:
                return None

            def setInterval(self, *_args, **_kwargs) -> None:
                return None

            def start(self, *_args, **_kwargs) -> None:
                return None

            def stop(self, *_args, **_kwargs) -> None:
                return None

    class QEvent:  # type: ignore[too-many-ancestors]
        class Type:
            MouseButtonDblClick = object()
import csv
from pathlib import Path

from utils.pitcher_role import get_display_role, get_role
from utils.pitching_autofill import autofill_pitching_staff
from utils.path_utils import get_data_dir
from utils.recovery_manager import (
    clear_recovery,
    needs_recovery,
    recovery_path_for_data_file,
    write_recovery_csv,
)
from .components import ActionButtonPanel

class PitchingEditor(QDialog):
    def __init__(self, team_id):
        super().__init__()
        self.team_id = team_id
        self._base_title = "Pitching Staff Editor"
        self.setWindowTitle(self._base_title)
        self.setMinimumSize(760, 560)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1500)
        self._autosave_timer.timeout.connect(self._write_recovery)
        self._recovery_checked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        status_group = QGroupBox("Staff Status")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(4)
        self.dirty_label = QLabel("All changes saved.")
        self.dirty_label.setStyleSheet("color: #888888;")
        status_layout.addWidget(self.dirty_label)
        self.staff_health_label = QLabel("Filled: 0/9 | Duplicates: 0")
        self.staff_health_label.setStyleSheet("color: #666666;")
        status_layout.addWidget(self.staff_health_label)
        status_hint = QLabel(
            "Tip: Double-click a pitcher name to open the player profile."
        )
        status_hint.setWordWrap(True)
        status_hint.setStyleSheet("color: #777777; font-size: 11px;")
        status_layout.addWidget(status_hint)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        self.roles = ["SP1", "SP2", "SP3", "SP4", "SP5", "LR", "MR", "SU", "CL"]
        self.pitcher_dropdowns = {}

        self.players_dict = self.load_players_dict()
        self.act_ids = self.get_act_level_ids()

        assignments_group = QGroupBox("Role Assignments")
        assignments_layout = QVBoxLayout()
        assignments_layout.setContentsMargins(10, 8, 10, 8)
        assignments_layout.setSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        for i, role in enumerate(self.roles):
            label = QLabel(role)
            dropdown = QComboBox()
            dropdown.installEventFilter(self)
            for pid, pdata in self.players_dict.items():
                if pid in self.act_ids and get_role(pdata):
                    dropdown.addItem(pdata["name"], userData=pid)
            dropdown.currentIndexChanged.connect(self._on_assignment_changed)
            self.pitcher_dropdowns[role] = dropdown
            grid.addWidget(label, i, 0)
            grid.addWidget(dropdown, i, 1)

        assignments_layout.addLayout(grid)
        assignments_group.setLayout(assignments_layout)
        layout.addWidget(assignments_group)

        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(8)
        action_panel = ActionButtonPanel(
            min_columns=1,
            max_columns=3,
            target_button_width=190,
            min_button_width=150,
            max_button_width=220,
        )
        self.save_button = QPushButton("Save Pitching Staff")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.save_pitching_staff)
        action_panel.add_button(self.save_button)

        self.autofill_button = QPushButton("Auto-Fill Staff")
        self.autofill_button.clicked.connect(self.autofill_staff)
        action_panel.add_button(self.autofill_button)

        self.clear_button = QPushButton("Clear Staff")
        self.clear_button.clicked.connect(self.clear_staff)
        action_panel.add_button(self.clear_button)
        action_layout.addWidget(action_panel)
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)

        self._baseline = []
        self._load_staff_with_recovery()
        self._update_staff_health()

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
        path = get_data_dir() / "players.csv"
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
        path = get_data_dir() / "rosters" / f"{self.team_id}.csv"
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
        path = get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv"
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
            clear_recovery(path)
            QMessageBox.information(self, "Saved", "Pitching staff saved successfully.")
            return True
        except PermissionError as exc:
            QMessageBox.warning(self, "Permission Denied", f"Cannot save to {path}.\n{exc}")
            return False

    def load_pitching_staff(self, source_path: Path | None = None, *, set_baseline: bool = True):
        path = Path(source_path) if source_path is not None else get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv"
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
        if set_baseline:
            self._refresh_baseline()
        self._update_staff_health()

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
        self._schedule_autosave()
        self._update_staff_health()

    def clear_staff(self):
        for dropdown in self.pitcher_dropdowns.values():
            dropdown.setCurrentIndex(-1)
        self._schedule_autosave()
        self._update_staff_health()

    def _prompt_recovery_choice(self, title: str, message: str) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        restore_btn = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(restore_btn)
        box.exec()
        if box.clickedButton() == restore_btn:
            return "restore"
        if box.clickedButton() == discard_btn:
            return "discard"
        return "discard"

    def _load_staff_with_recovery(self) -> None:
        if self._recovery_checked:
            self.load_pitching_staff()
            self._set_dirty_state(self._has_unsaved_changes())
            return
        self._recovery_checked = True
        data_path = get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv"
        if not needs_recovery(data_path):
            self.load_pitching_staff()
            self._set_dirty_state(False)
            return
        recovery_path = recovery_path_for_data_file(data_path)
        choice = self._prompt_recovery_choice(
            "Recover Pitching Staff",
            "Autosaved pitching staff changes were found from a previous session. Restore them?",
        )
        if choice == "restore":
            self.load_pitching_staff(source_path=recovery_path, set_baseline=False)
            self._set_dirty_state(True)
            return
        clear_recovery(data_path)
        self.load_pitching_staff()
        self._set_dirty_state(False)

    def _schedule_autosave(self) -> None:
        dirty = self._has_unsaved_changes()
        self._set_dirty_state(dirty)
        if not dirty:
            clear_recovery(get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv")
            return
        self._autosave_timer.start()
        self._update_staff_health()

    def _write_recovery(self) -> None:
        if not self._has_unsaved_changes():
            clear_recovery(get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv")
            return
        rows = []
        for role, dropdown in self.pitcher_dropdowns.items():
            player_id = dropdown.currentData() or ""
            if player_id:
                rows.append((str(player_id), str(role)))
        data_path = get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv"
        write_recovery_csv(data_path, rows)

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
        self._set_dirty_state(False)
        self._update_staff_health()

    def _has_unsaved_changes(self) -> bool:
        return self._snapshot_staff() != getattr(self, "_baseline", [])

    def _set_dirty_state(self, dirty: bool) -> None:
        if dirty:
            self.dirty_label.setText("Unsaved changes.")
            self.dirty_label.setStyleSheet("color: #e67700; font-weight: 600;")
            self.setWindowTitle(f"{self._base_title} *")
        else:
            self.dirty_label.setText("All changes saved.")
            self.dirty_label.setStyleSheet("color: #888888;")
            self.setWindowTitle(self._base_title)

    def _on_assignment_changed(self) -> None:
        self._schedule_autosave()
        self._update_staff_health()

    def _update_staff_health(self) -> None:
        selected_ids = [dropdown.currentData() for dropdown in self.pitcher_dropdowns.values()]
        filled_ids = [pid for pid in selected_ids if pid]
        filled = len(filled_ids)
        duplicate_count = max(0, filled - len(set(filled_ids)))
        self.staff_health_label.setText(
            f"Filled: {filled}/9 | Duplicates: {duplicate_count}"
        )
        if duplicate_count > 0:
            self.staff_health_label.setStyleSheet("color: #b54708; font-weight: 600;")
        elif filled < len(self.roles):
            self.staff_health_label.setStyleSheet("color: #666666;")
        else:
            self.staff_health_label.setStyleSheet("color: #12703d; font-weight: 600;")

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
            clear_recovery(get_data_dir() / "rosters" / f"{self.team_id}_pitching.csv")
            super().closeEvent(event)
        else:
            event.ignore()
