from PyQt6.QtCore import Qt
try:  # pragma: no cover - test stub fallback
    from PyQt6.QtCore import pyqtSignal
except Exception:  # pragma: no cover
    class _DummySignal:
        def connect(self, *_args, **_kwargs):
            return None

        def emit(self, *_args, **_kwargs):
            return None

    def pyqtSignal(*_args, **_kwargs):  # type: ignore[misc]
        return _DummySignal()
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QGridLayout,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QScrollArea,
)

from .components import Card, section_title
from .design_tokens import apply_status
from .player_profile_dialog import PlayerProfileDialog
from utils.depth_chart import (
    DEPTH_CHART_POSITIONS,
    default_depth_chart,
    load_depth_chart,
    save_depth_chart,
)
from utils.roster_validation import missing_positions


class DepthChartListWidget(QListWidget):
    """List widget that supports drag-and-drop reordering."""

    reordered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSpacing(2)
        self.setAlternatingRowColors(False)
        self.setMinimumHeight(96)
        self.setObjectName("DepthChartList")

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class RosterPage(QWidget):
    """Page with shortcuts for roster-related tasks."""

    def __init__(self, dashboard):
        super().__init__()
        self._dashboard = dashboard
        self._depth_lists: dict[str, DepthChartListWidget] = {}
        self._depth_dirty = False
        self._depth_title = None

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

        layout.addWidget(self._build_roster_actions_card())
        layout.addWidget(self._build_depth_chart_card())
        layout.addStretch()

    def _build_roster_actions_card(self) -> Card:
        card = Card()
        card.layout().addWidget(section_title("Roster Management"))

        self.coverage_label = QLabel("")
        self.coverage_label.setObjectName("StatusLabel")
        card.layout().addWidget(self.coverage_label)

        btn_players = QPushButton("Players", objectName="Primary")
        btn_players.setToolTip("Browse all position players and pitchers")
        btn_players.clicked.connect(self._dashboard.open_player_browser_dialog)
        card.layout().addWidget(btn_players)

        btn_pitch = QPushButton("Pitching Staff", objectName="Primary")
        btn_pitch.clicked.connect(self._dashboard.open_pitching_editor)
        card.layout().addWidget(btn_pitch)

        btn_lineups = QPushButton("Lineups", objectName="Primary")
        btn_lineups.clicked.connect(self._dashboard.open_lineup_editor)
        card.layout().addWidget(btn_lineups)

        btn_move = QPushButton("Reassign Players", objectName="Primary")
        btn_move.clicked.connect(self._dashboard.open_reassign_players_dialog)
        card.layout().addWidget(btn_move)

        btn_injuries = QPushButton("Injury Center", objectName="Primary")
        btn_injuries.clicked.connect(self._dashboard.open_team_injury_center)
        card.layout().addWidget(btn_injuries)

        btn_training = QPushButton("Training Focus", objectName="Primary")
        btn_training.setToolTip("Adjust hitter/pitcher development budgets for this team")
        btn_training.clicked.connect(self._dashboard.open_training_focus_dialog)
        card.layout().addWidget(btn_training)

        btn_change_request = QPushButton("Submit Change Request", objectName="Primary")
        btn_change_request.setToolTip("Export roster/lineup changes for commissioner approval")
        btn_change_request.clicked.connect(self._dashboard.open_change_request_export_dialog)
        card.layout().addWidget(btn_change_request)

        card.layout().addStretch()
        return card

    def _build_depth_chart_card(self) -> Card:
        card = Card()
        self._depth_title = section_title("Depth Chart Priorities")
        card.layout().addWidget(self._depth_title)
        hint = QLabel("Drag players to change their priority. Use the full Depth Chart dialog to add or remove players.")
        hint.setWordWrap(True)
        card.layout().addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        columns = 3
        for idx, pos in enumerate(DEPTH_CHART_POSITIONS):
            row = idx // columns
            col = idx % columns
            grid.addWidget(self._build_depth_cell(pos), row, col)
        card.layout().addLayout(grid)

        controls = QHBoxLayout()
        self.save_depth_btn = QPushButton("Save Depth Chart", objectName="Primary")
        self.save_depth_btn.clicked.connect(self._save_depth_chart)
        controls.addWidget(self.save_depth_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.depth_status = QLabel("All changes saved.")
        self.depth_status.setObjectName("StatusLabel")
        apply_status(self.depth_status, "muted")
        controls.addWidget(self.depth_status, 1)
        controls.addStretch()
        card.layout().addLayout(controls)
        return card

    def _build_depth_cell(self, position: str) -> QWidget:
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        title = QLabel(position)
        title.setStyleSheet("font-weight: 600;")
        v.addWidget(title)
        lst = DepthChartListWidget()
        lst.reordered.connect(self._on_depth_chart_changed)
        lst.itemDoubleClicked.connect(self._open_player_profile)
        v.addWidget(lst)
        self._depth_lists[position] = lst
        return holder

    def refresh(self) -> None:
        """Update defensive coverage notice and surface depth chart order."""
        try:
            roster = getattr(self._dashboard, "roster", None)
            players = getattr(self._dashboard, "players", {})
            missing = missing_positions(roster, players) if roster else []
        except Exception:
            missing = []
        if missing:
            text = "Missing coverage: " + ", ".join(missing)
            apply_status(self.coverage_label, "warning")
        else:
            text = "Defensive coverage looks good."
            apply_status(self.coverage_label, "success")
        self.coverage_label.setText(text)
        self._refresh_depth_chart()
        try:
            self._dashboard.maybe_show_depth_chart_tutorial()
        except Exception:
            pass

    # Depth chart helpers -------------------------------------------------
    def _refresh_depth_chart(self) -> None:
        if self._depth_dirty:
            return
        chart = self._load_chart()
        roster = getattr(self._dashboard, "roster", None)
        level_map = self._build_level_index(roster)
        players = getattr(self._dashboard, "players", {})
        for pos, widget in self._depth_lists.items():
            widget.blockSignals(True)
            widget.clear()
            entries = self._entries_with_fallback(pos, chart.get(pos, []), roster, players)
            for pid in entries:
                widget.addItem(self._make_player_item(pid, players, level_map))
            widget.blockSignals(False)
        self._set_depth_dirty(False)

    def _load_chart(self) -> dict[str, list[str]]:
        try:
            return load_depth_chart(self._dashboard.team_id)
        except Exception:
            return default_depth_chart()

    def _build_level_index(self, roster) -> dict[str, str]:
        mapping: dict[str, str] = {}
        if roster is None:
            return mapping
        for level_name, group in (
            ("ACT", getattr(roster, "act", [])),
            ("AAA", getattr(roster, "aaa", [])),
            ("LOW", getattr(roster, "low", [])),
        ):
            for pid in group or []:
                mapping[pid] = level_name
        for pid in getattr(roster, "dl", []) or []:
            mapping[pid] = "DL"
        for pid in getattr(roster, "ir", []) or []:
            mapping[pid] = "IR"
        return mapping

    def _make_player_item(self, pid: str, players: dict, level_map: dict[str, str]) -> QListWidgetItem:
        player = players.get(pid)
        if player is None:
            label = pid
        else:
            name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
            pos = getattr(player, "primary_position", "")
            label = f"{name} - {pos}".strip(" -")
        level = level_map.get(pid)
        if level:
            label = f"{label} ({level})"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, pid)
        return item

    def _on_depth_chart_changed(self) -> None:
        self._set_depth_dirty(True)

    def _set_depth_dirty(self, dirty: bool) -> None:
        self._depth_dirty = dirty
        if dirty:
            self.depth_status.setText("Unsaved changes.")
            apply_status(self.depth_status, "warning")
            if self._depth_title is not None:
                self._depth_title.setText("Depth Chart Priorities *")
        else:
            self.depth_status.setText("All changes saved.")
            apply_status(self.depth_status, "muted")
            if self._depth_title is not None:
                self._depth_title.setText("Depth Chart Priorities")

    def _entries_with_fallback(
        self,
        position: str,
        stored: list[str],
        roster,
        players: dict[str, object],
    ) -> list[str]:
        entries: list[str] = []
        seen: set[str] = set()
        for pid in stored:
            if pid and pid not in seen:
                entries.append(pid)
                seen.add(pid)
        if roster is None or len(entries) >= 3:
            return entries[:3]
        for pid in self._eligible_players(position, roster, players):
            if pid not in seen:
                entries.append(pid)
                seen.add(pid)
            if len(entries) >= 3:
                break
        return entries[:3]

    def _eligible_players(self, position: str, roster, players: dict[str, object]) -> list[str]:
        target = position.upper()
        ids = (
            list(getattr(roster, "act", []) or [])
            + list(getattr(roster, "aaa", []) or [])
            + list(getattr(roster, "low", []) or [])
        )
        def can_play(pid: str) -> bool:
            player = players.get(pid)
            if player is None:
                return False
            if getattr(player, "is_pitcher", False):
                return target == "DH"
            primary = str(getattr(player, "primary_position", "")).upper()
            if target == "DH":
                return True
            if primary == target:
                return True
            for other in getattr(player, "other_positions", []) or []:
                if str(other).upper() == target:
                    return True
            return False

        return [pid for pid in ids if can_play(pid)]

    def _open_player_profile(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        if not pid:
            return
        player = getattr(self._dashboard, "players", {}).get(pid)
        if player is None:
            return
        try:
            dlg = PlayerProfileDialog(player, self)
            dlg.exec()
        except Exception:
            pass

    def _collect_depth_chart(self) -> dict[str, list[str]]:
        data: dict[str, list[str]] = {}
        for pos, widget in self._depth_lists.items():
            entries: list[str] = []
            for row in range(widget.count()):
                pid = widget.item(row).data(Qt.ItemDataRole.UserRole) or ""
                if pid:
                    entries.append(str(pid))
            data[pos] = entries[:3]
        return data

    def _save_depth_chart(self) -> None:
        data = self._collect_depth_chart()
        try:
            save_depth_chart(self._dashboard.team_id, data)
        except Exception as exc:
            self.depth_status.setText(f"Failed to save: {exc}")
            apply_status(self.depth_status, "danger")
            return
        self._set_depth_dirty(False)
