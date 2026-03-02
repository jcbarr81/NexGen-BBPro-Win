from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QComboBox,
    QPushButton,
    QWidget,
    QMessageBox,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
)
from PyQt6.QtGui import QPixmap
try:
    from PyQt6.QtCore import Qt, QPropertyAnimation, QEvent, QTimer
except ImportError:  # pragma: no cover - fallback for lightweight test stubs
    from PyQt6.QtCore import Qt, QPropertyAnimation

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

from utils.lineup_autofill import auto_fill_lineup_for_team
from utils.path_utils import get_base_dir, get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.recovery_manager import (
    clear_recovery,
    needs_recovery,
    recovery_path_for_data_file,
    write_recovery_csv,
)
from services.decision_explanations import summarize_decision_explanation

class LineupEditor(QDialog):
    _AUTOFILL_REASON_PLACEHOLDER = (
        "Run Auto-Fill Lineup to view the latest lineup decision reasons."
    )

    def __init__(self, team_id):
        self.team_id = team_id
        super().__init__()
        self._base_title = "Lineup Editor"
        self.setWindowTitle(self._base_title)
        self.setMinimumSize(980, 640)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1500)
        self._autosave_timer.timeout.connect(self._write_recovery)
        self._recovery_checked_views = set()

        layout = QHBoxLayout()
        self.setLayout(layout)

        # Left: Field diagram
        field_container = QWidget()
        field_layout = QVBoxLayout(field_container)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(0)

        self.field_label = QLabel()
        field_path = get_base_dir() / "assets" / "field_diagram.png"
        if field_path.exists():
            pixmap = QPixmap(str(field_path)).scaledToWidth(
                400, Qt.TransformationMode.SmoothTransformation
            )
            self.field_label.setPixmap(pixmap)
            overlay_w, overlay_h = pixmap.width(), pixmap.height()
        else:
            self.field_label.setText("Field Image Placeholder")
            self.field_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            overlay_w, overlay_h = 400, 500
        self.field_label.setFixedSize(overlay_w, overlay_h)
        field_layout.addWidget(self.field_label)

        self.field_overlay = QWidget(self.field_label)
        self.field_overlay.setGeometry(0, 0, overlay_w, overlay_h)
        self.field_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.field_overlay.setStyleSheet("background: transparent;")

        self.position_labels = {}
        y_offset = 0
        position_coords = {
            "C": (160, 303),
            "1B": (225, 163),
            "2B": (220, 111),
            "SS": (98, 111),
            "3B": (62, 162),
            "LF": (55, 57),
            "CF": (158, 22),
            "RF": (230, 57),
            "DH": (275, 237),
        }
        for pos, (x, y) in position_coords.items():
            label = QLabel("", self.field_overlay)
            label.move(x, y + y_offset)
            label.setStyleSheet(
                "color: blue; font-size: 9px; font-weight: bold; background-color: rgba(255, 255, 255, 0.6); border-radius: 4px;"
            )
            label.setFixedWidth(100)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            self.position_labels[pos] = label

        layout.addWidget(field_container)

        # Right: Batting order and bench
        right_container = QWidget()
        right_panel = QVBoxLayout(right_container)
        right_panel.setContentsMargins(10, 10, 10, 10)
        right_panel.setSpacing(12)

        # View selector for vs LHP / vs RHP
        view_selector_group = QGroupBox("Lineup View Mode")
        view_selector_layout = QHBoxLayout()
        self.view_selector = QComboBox()
        self.view_selector.addItems(["vs LHP", "vs RHP"])
        view_selector_layout.addWidget(QLabel("View Lineup For:"))
        view_selector_layout.addWidget(self.view_selector)
        view_selector_group.setLayout(view_selector_layout)
        right_panel.addWidget(view_selector_group)

        status_group = QGroupBox("Lineup Status")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(4)
        self.dirty_label = QLabel("All changes saved.")
        self.dirty_label.setStyleSheet("color: #888888;")
        status_layout.addWidget(self.dirty_label)
        self.lineup_health_label = QLabel("Filled: 0/9 | Duplicates: 0")
        self.lineup_health_label.setStyleSheet("color: #666666;")
        status_layout.addWidget(self.lineup_health_label)
        status_hint = QLabel("Tip: Double-click a player in lineup/bench to open their profile.")
        status_hint.setWordWrap(True)
        status_hint.setStyleSheet("color: #777777; font-size: 11px;")
        status_layout.addWidget(status_hint)
        status_group.setLayout(status_layout)
        right_panel.addWidget(status_group)

        order_group = QGroupBox("Batting Order")
        order_group_layout = QVBoxLayout()
        order_group_layout.setContentsMargins(10, 8, 10, 8)
        order_group_layout.setSpacing(6)

        self.order_grid = QGridLayout()
        self.order_grid.setHorizontalSpacing(8)
        self.order_grid.setVerticalSpacing(6)
        self.player_dropdowns = []
        self.position_dropdowns = []

        self.players_dict = self.load_players_dict()
        self.act_level_ids = self.get_act_level_ids()
        self.act_players = [
            (pid, pdata["name"]) for pid, pdata in self.players_dict.items()
            if not pdata.get("is_pitcher") and pid in self.act_level_ids
        ]

        for i in range(9):
            spot = QLabel(str(i + 1))
            player_dropdown = QComboBox()
            player_dropdown.installEventFilter(self)
            pos_dropdown = QComboBox()
            pos_dropdown.addItems(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"])
            pos_dropdown.currentIndexChanged.connect(
                lambda _=None, i=i: self._on_position_changed(i)
            )

            self.order_grid.addWidget(spot, i, 0)
            self.order_grid.addWidget(player_dropdown, i, 1)
            self.order_grid.addWidget(pos_dropdown, i, 2)

            player_dropdown.currentIndexChanged.connect(
                lambda _=None, i=i: self._on_player_changed(i)
            )

            self.player_dropdowns.append(player_dropdown)
            self.position_dropdowns.append(pos_dropdown)

        order_group_layout.addLayout(self.order_grid)
        order_group.setLayout(order_group_layout)
        right_panel.addWidget(order_group)

        bench_group = QGroupBox("Substitute / Bench")
        bench_layout = QVBoxLayout()
        bench_layout.setContentsMargins(10, 8, 10, 8)
        bench_layout.setSpacing(6)

        self.bench_display = QListWidget()
        self.bench_display.setMinimumHeight(100)
        self.bench_display.setMaximumHeight(150)
        self.bench_display.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.bench_display.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        bench_layout.addWidget(self.bench_display)
        bench_group.setLayout(bench_layout)
        right_panel.addWidget(bench_group)
        self.bench_display.itemDoubleClicked.connect(self._open_bench_player_profile)

        action_group = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(8)
        self.save_button = QPushButton("Save Lineup")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.save_lineup)
        action_layout.addWidget(self.save_button)

        self.autofill_button = QPushButton("Auto-Fill Lineup")
        self.autofill_button.clicked.connect(self.autofill_lineup)
        action_layout.addWidget(self.autofill_button)

        self.clear_button = QPushButton("Clear Lineup")
        self.clear_button.clicked.connect(self.clear_lineup)
        action_layout.addWidget(self.clear_button)
        action_group.setLayout(action_layout)
        right_panel.addWidget(action_group)

        autofill_reason_group = QGroupBox("Auto-Fill Decision Reasons")
        autofill_reason_layout = QVBoxLayout()
        autofill_reason_layout.setContentsMargins(10, 8, 10, 8)
        autofill_reason_layout.setSpacing(4)
        self.autofill_reason_label = QLabel(self._AUTOFILL_REASON_PLACEHOLDER)
        self.autofill_reason_label.setWordWrap(True)
        autofill_reason_layout.addWidget(self.autofill_reason_label)
        autofill_reason_group.setLayout(autofill_reason_layout)
        right_panel.addWidget(autofill_reason_group)
        right_panel.addStretch(1)

        layout.addWidget(right_container)

        self.view_selector.currentIndexChanged.connect(self.switch_view)
        self.current_view = "vs LHP"
        self._baseline = []
        self._load_lineup_with_recovery()
        self.update_bench_display()
        self._update_lineup_health()
        self._update_autofill_reason_label()

    def autofill_lineup(self):
        try:
            auto_fill_lineup_for_team(self.team_id)
        except Exception as exc:
            QMessageBox.warning(self, "Auto-Fill Failed", str(exc))
            return

        payload = getattr(auto_fill_lineup_for_team, "last_explanation", None)
        self._update_autofill_reason_label(payload)
        self.load_lineup()
        clear_recovery(self.get_lineup_filename())
        self.update_bench_display()
        QMessageBox.information(
            self,
            "Lineup Auto-Filled",
            "Lineups updated using the league auto-fill logic.",
        )

    def save_lineup(self):
        # Validate that each player is eligible for their selected position
        for i in range(9):
            player_id = self.player_dropdowns[i].currentData()
            position = self.position_dropdowns[i].currentText()

            if not player_id:
                QMessageBox.warning(self, "Validation Error", f"Lineup slot {i + 1} is empty.")
                return False

            pdata = self.players_dict.get(player_id)
            if not pdata:
                QMessageBox.warning(self, "Validation Error", f"Player ID {player_id} not found.")
                return False

            if position == "DH":
                if pdata.get("is_pitcher"):
                    QMessageBox.warning(self, "Validation Error", f"{pdata['name']} cannot be the DH.")
                    return False
            else:
                primary = pdata.get("primary_position")
                others = pdata.get("other_positions", [])
                if position != primary and position not in others:
                    QMessageBox.warning(self, "Validation Error", f"{pdata['name']} is not eligible to play {position}.")
                    return False

        filename = Path(self.get_lineup_filename())
        filename.parent.mkdir(parents=True, exist_ok=True)
        for lbl in self.position_labels.values():
            lbl.setText("")
        with filename.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order", "player_id", "position"])
            for i in range(9):
                player_id = self.player_dropdowns[i].currentData()
                position = self.position_dropdowns[i].currentText()
                writer.writerow([i + 1, player_id, position])
                if position in self.position_labels:
                    self.position_labels[position].setText(self.players_dict.get(player_id, {}).get("name", ""))

        self._refresh_baseline()
        clear_recovery(self.get_lineup_filename())
        self._update_lineup_health()
        QMessageBox.information(self, "Lineup Saved", "Lineup saved successfully.")
        return True

    def load_players_dict(self):
        players = {}
        try:
            loaded = load_players_from_csv(get_data_dir() / "players.csv")
        except Exception:
            loaded = []
        for player in loaded:
            player_id = str(getattr(player, "player_id", "") or "").strip()
            if not player_id:
                continue
            first = str(getattr(player, "first_name", "") or "").strip()
            last = str(getattr(player, "last_name", "") or "").strip()
            primary = str(getattr(player, "primary_position", "") or "").strip()
            raw_others = getattr(player, "other_positions", [])
            if isinstance(raw_others, str):
                others = [item for item in raw_others.split("|") if item]
            else:
                others = list(raw_others or [])
            players[player_id] = {
                "name": f"{first} {last}".strip() + (f" ({primary})" if primary else ""),
                "primary_position": primary,
                "other_positions": others,
                "is_pitcher": bool(getattr(player, "is_pitcher", False)),
                "ratings": {
                    "CH": getattr(player, "ch", ""),
                    "PH": getattr(player, "ph", ""),
                    "SP": getattr(player, "sp", ""),
                },
            }
        return players

    def get_act_level_ids(self):
        try:
            roster = load_roster(self.team_id)
        except Exception:
            return set()
        return {str(pid).strip() for pid in roster.act if str(pid).strip()}

    def switch_view(self):
        self.current_view = self.view_selector.currentText()
        self._autosave_timer.stop()
        self._load_lineup_with_recovery()
        self.update_bench_display()
        self._update_lineup_health()

    def get_lineup_filename(self):
        """Return path to the lineup CSV for the current view.

        Lineup files live in ``data/lineups`` with names like
        ``TEAM_vs_lhp.csv`` or ``TEAM_vs_rhp.csv`` and use the columns
        ``order,player_id,position``.
        """
        suffix = "vs_lhp" if self.current_view == "vs LHP" else "vs_rhp"
        return get_data_dir() / "lineups" / f"{self.team_id}_{suffix}.csv"

    def load_lineup(self, source_path: Path | None = None, *, set_baseline: bool = True):
        for lbl in self.position_labels.values():
            lbl.setText("")
        filename = Path(source_path) if source_path is not None else Path(self.get_lineup_filename())
        if filename.exists():
            with filename.open("r", newline='', encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        i = int(row.get("order", 0)) - 1
                    except (TypeError, ValueError):
                        continue
                    if not 0 <= i < 9:
                        continue
                    player_id = row.get("player_id", "").strip()
                    position = row.get("position", "").strip()
                    self.position_dropdowns[i].setCurrentText(position)
                    self.update_player_dropdown(i)
                    for index in range(self.player_dropdowns[i].count()):
                        if self.player_dropdowns[i].itemData(index) == player_id:
                            self.player_dropdowns[i].setCurrentIndex(index)
                            if position in self.position_labels:
                                self.position_labels[position].setText(self.players_dict.get(player_id, {}).get("name", ""))
                            break
        if set_baseline:
            self._refresh_baseline()

    def update_bench_display(self):
        used_ids = {self.player_dropdowns[i].currentData() for i in range(9)}
        # Show only position players on the ACT roster who are not in the
        # current batting order. Rely on the explicit is_pitcher flag rather
        # than derived role to avoid misclassifying pitchers with missing
        # endurance/role fields.
        bench_players = sorted(
            [
                (pdata["name"], pid)
                for pid, pdata in self.players_dict.items()
                if pid in self.act_level_ids
                and pid not in used_ids
                and not pdata.get("is_pitcher", False)
            ],
            key=lambda item: item[0],
        )

        self.bench_display.clear()
        if bench_players:
            for name, pid in bench_players:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, pid)
                self.bench_display.addItem(item)
        else:
            self.bench_display.addItem("(none)")
        self._update_lineup_health()

    def update_overlay_label(self, index):
        position = self.position_dropdowns[index].currentText()
        player_id = self.player_dropdowns[index].currentData()
        if position in self.position_labels:
            label = self.position_labels[position]
            new_name = self.players_dict.get(player_id, {}).get("name", "")

            animation = QPropertyAnimation(label, b"windowOpacity")
            animation.setDuration(200)
            animation.setStartValue(1.0)
            animation.setEndValue(0.0)

            def set_text_and_fade_in():
                label.setText(new_name)
                fade_in = QPropertyAnimation(label, b"windowOpacity")
                fade_in.setDuration(200)
                fade_in.setStartValue(0.0)
                fade_in.setEndValue(1.0)
                fade_in.start()
                label.fade_in_anim = fade_in  # prevent garbage collection

            animation.finished.connect(set_text_and_fade_in)
            animation.start()
            label.fade_out_anim = animation  # prevent garbage collection

    def clear_lineup(self):
        for i in range(9):
            self.player_dropdowns[i].setCurrentIndex(-1)
            self.position_dropdowns[i].setCurrentIndex(0)
        for lbl in self.position_labels.values():
            lbl.setText("")
        self.update_bench_display()
        self._schedule_autosave()
        self._update_lineup_health()

    def update_player_dropdown(self, index):
        selected_pos = self.position_dropdowns[index].currentText()
        dropdown = self.player_dropdowns[index]
        dropdown.clear()
        for pid, pdata in self.players_dict.items():
            if pid not in self.act_level_ids:
                continue
            primary = pdata.get("primary_position")
            others = pdata.get("other_positions", [])
            if selected_pos == "DH":
                if not pdata.get("is_pitcher"):
                    dropdown.addItem(pdata["name"], userData=pid)
            elif selected_pos == primary or selected_pos in others:
                dropdown.addItem(pdata["name"], userData=pid)

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

    def _open_bench_player_profile(self, item):
        player_id = item.data(Qt.ItemDataRole.UserRole)
        self._open_player_profile(player_id)

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

    def _load_lineup_with_recovery(self) -> None:
        view_key = self.current_view
        if view_key in self._recovery_checked_views:
            self.load_lineup()
            self._set_dirty_state(self._has_unsaved_changes())
            return
        self._recovery_checked_views.add(view_key)
        data_path = self.get_lineup_filename()
        if not needs_recovery(data_path):
            self.load_lineup()
            self._set_dirty_state(False)
            return
        recovery_path = recovery_path_for_data_file(data_path)
        choice = self._prompt_recovery_choice(
            "Recover Lineup",
            "Autosaved lineup changes were found from a previous session. Restore them?",
        )
        if choice == "restore":
            self.load_lineup(source_path=recovery_path, set_baseline=False)
            self._set_dirty_state(True)
            return
        clear_recovery(data_path)
        self.load_lineup()
        self._set_dirty_state(False)

    def _schedule_autosave(self) -> None:
        dirty = self._has_unsaved_changes()
        self._set_dirty_state(dirty)
        if not dirty:
            clear_recovery(self.get_lineup_filename())
            return
        self._autosave_timer.start()

    def _write_recovery(self) -> None:
        if not self._has_unsaved_changes():
            clear_recovery(self.get_lineup_filename())
            return
        rows = []
        for i in range(9):
            player_id = self.player_dropdowns[i].currentData() or ""
            position = self.position_dropdowns[i].currentText()
            rows.append((str(i + 1), str(player_id), position))
        write_recovery_csv(
            self.get_lineup_filename(),
            rows,
            header=("order", "player_id", "position"),
        )

    def eventFilter(self, obj, event):  # noqa: N802 - Qt signature
        if event.type() == QEvent.Type.MouseButtonDblClick:
            if isinstance(obj, QComboBox):
                self._open_player_profile(obj.currentData())
                return True
        return super().eventFilter(obj, event)

    def _snapshot_lineup(self):
        snapshot = []
        for i in range(9):
            player_id = self.player_dropdowns[i].currentData()
            position = self.position_dropdowns[i].currentText()
            snapshot.append((player_id, position))
        return snapshot

    def _refresh_baseline(self):
        self._baseline = self._snapshot_lineup()
        self._set_dirty_state(False)
        self._update_lineup_health()

    def _has_unsaved_changes(self) -> bool:
        return self._snapshot_lineup() != getattr(self, "_baseline", [])

    def _set_dirty_state(self, dirty: bool) -> None:
        if dirty:
            self.dirty_label.setText("Unsaved changes.")
            self.dirty_label.setStyleSheet("color: #e67700; font-weight: 600;")
            self.setWindowTitle(f"{self._base_title} *")
        else:
            self.dirty_label.setText("All changes saved.")
            self.dirty_label.setStyleSheet("color: #888888;")
            self.setWindowTitle(self._base_title)

    def _on_position_changed(self, index: int) -> None:
        self.update_player_dropdown(index)
        self.update_overlay_label(index)
        self.update_bench_display()
        self._schedule_autosave()

    def _on_player_changed(self, index: int) -> None:
        self.update_overlay_label(index)
        self.update_bench_display()
        self._schedule_autosave()

    def _update_lineup_health(self) -> None:
        selected_ids = [self.player_dropdowns[i].currentData() for i in range(9)]
        filled_ids = [pid for pid in selected_ids if pid]
        filled = len(filled_ids)
        duplicate_count = max(0, filled - len(set(filled_ids)))
        self.lineup_health_label.setText(
            f"Filled: {filled}/9 | Duplicates: {duplicate_count}"
        )
        if duplicate_count > 0:
            self.lineup_health_label.setStyleSheet("color: #b54708; font-weight: 600;")
        elif filled < 9:
            self.lineup_health_label.setStyleSheet("color: #666666;")
        else:
            self.lineup_health_label.setStyleSheet("color: #12703d; font-weight: 600;")

    def closeEvent(self, event):  # noqa: N802 - Qt signature
        if not self._has_unsaved_changes():
            super().closeEvent(event)
            return

        choice = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved lineup changes. Save before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Save:
            if self.save_lineup():
                super().closeEvent(event)
            else:
                event.ignore()
        elif choice == QMessageBox.StandardButton.Discard:
            clear_recovery(self.get_lineup_filename())
            super().closeEvent(event)
        else:
            event.ignore()

    def _update_autofill_reason_label(self, payload=None) -> None:
        summary = self._AUTOFILL_REASON_PLACEHOLDER
        current_payload = payload
        if current_payload is None:
            current_payload = getattr(auto_fill_lineup_for_team, "last_explanation", None)
        if isinstance(current_payload, dict):
            decision_type = str(current_payload.get("decision_type") or "").strip()
            payload_team_id = str(current_payload.get("team_id") or "").strip()
            if decision_type == "lineup_autofill" and (
                not payload_team_id or payload_team_id == self.team_id
            ):
                summary = summarize_decision_explanation(
                    current_payload,
                    fallback="Lineup auto-fill completed. Detailed reasons were unavailable.",
                    max_reasons=4,
                )
        self.autofill_reason_label.setText(summary)
