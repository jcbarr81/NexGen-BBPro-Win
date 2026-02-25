from __future__ import annotations

"""Dialog for editing position depth charts for a team."""

from typing import Callable, Dict, List, Optional

try:  # pragma: no cover - PyQt stubs for tests
    from PyQt6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QGridLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    from PyQt6.QtCore import QTimer
except Exception:  # pragma: no cover
    class _Signal:
        def connect(self, *_args, **_kwargs):
            return None

    class QWidget:  # type: ignore[too-many-ancestors]
        def __init__(self, *args, **kwargs):
            pass

    class QDialog(QWidget):
        def reject(self):
            pass

    class QLabel(QWidget):
        def __init__(self, text="", *_, **__):
            self._text = text

        def setText(self, text):
            self._text = text

    class QPushButton(QWidget):
        def __init__(self, *_args, **_kwargs):
            self.clicked = _Signal()

    class QComboBox(QWidget):
        def __init__(self, *_, **__):
            self._items: list[tuple[str, str]] = []
            self._index = 0

        def addItem(self, label, data=""):
            self._items.append((label, data))

        def findData(self, value):
            for idx, (_, data) in enumerate(self._items):
                if data == value:
                    return idx
            return -1

        def setCurrentIndex(self, idx):
            if 0 <= idx < len(self._items):
                self._index = idx

        def currentData(self):
            if 0 <= self._index < len(self._items):
                return self._items[self._index][1]
            return ""

        def clear(self):
            self._items = []
            self._index = 0

        def blockSignals(self, *_):
            return None

    class QGridLayout:
        def __init__(self, *_, **__):
            pass

        def addWidget(self, *_, **__):
            pass

        def addLayout(self, *_, **__):
            pass

    class QVBoxLayout(QGridLayout):
        def __init__(self, *_args, **_kwargs):
            super().__init__()

    class QMessageBox:
        @staticmethod
        def information(*_, **__):
            pass

        @staticmethod
        def warning(*_, **__):
            pass

    class QDialogButtonBox(QWidget):
        class StandardButton:
            Save = 1
            Cancel = 2

        def __init__(self, *_a, **_k):
            self.accepted = _Signal()
            self.rejected = _Signal()
    class QTimer:
        @staticmethod
        def singleShot(_msec, callback):
            if callback is not None:
                callback()

from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.depth_chart import (
    DEPTH_CHART_POSITIONS,
    depth_order_for_position,
    load_depth_chart,
    save_depth_chart,
)
from services.unified_data_service import get_unified_data_service


class DepthChartDialog(QDialog):
    def __init__(self, dashboard):
        super().__init__(dashboard)
        self._dashboard = dashboard
        self.team_id = getattr(dashboard, "team_id", "")
        self.setWindowTitle(f"Depth Chart — {self.team_id}")
        self.resize(600, 420)
        self.players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        self.roster = load_roster(self.team_id)
        try:
            self.chart = load_depth_chart(self.team_id)
        except Exception:
            self.chart = {}
        self._level_map = self._build_level_index()
        self._combo_map: Dict[tuple[str, int], QComboBox] = {}
        self._service = get_unified_data_service()
        self._event_unsubscribes: List[Callable[[], None]] = []
        self._pending_refresh = False
        self._pending_toast_reason: Optional[str] = None
        self._build_ui()
        self._apply_existing_values()
        self._register_event_listeners()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("Position"), 0, 0)
        for idx, label in enumerate(["Starter", "1st Backup", "2nd Backup"], start=1):
            grid.addWidget(QLabel(label), 0, idx)
        for row, pos in enumerate(DEPTH_CHART_POSITIONS, start=1):
            grid.addWidget(QLabel(pos), row, 0)
            for slot in range(3):
                combo = QComboBox()
                self._populate_combo(combo, pos)
                grid.addWidget(combo, row, slot + 1)
                self._combo_map[(pos, slot)] = combo
        root.addLayout(grid)
        try:
            auto_btn = QPushButton("Auto Populate")
            auto_btn.clicked.connect(self._auto_populate)
        except Exception:
            auto_btn = QPushButton()
        self._auto_button = auto_btn
        root.addWidget(auto_btn)
        self.status_label = QLabel()
        root.addWidget(self.status_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        try:
            buttons.accepted.connect(self._save)
            buttons.rejected.connect(self.reject)
        except Exception:
            pass
        root.addWidget(buttons)

    def _build_level_index(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for level, group in (
            ("ACT", self.roster.act),
            ("AAA", self.roster.aaa),
            ("LOW", self.roster.low),
            ("DL", self.roster.dl),
            ("IR", self.roster.ir),
        ):
            for pid in group:
                mapping[pid] = level
        return mapping

    def _player_label(self, pid: str) -> str:
        player = self.players.get(pid)
        if player is None:
            return pid
        name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
        pos = getattr(player, "primary_position", "")
        level = self._level_map.get(pid, "")
        suffix = f" ({level})" if level else ""
        return f"{name} - {pos}{suffix}"

    def _eligible_players(self, position: str) -> List[str]:
        pos = position.upper()
        ids = (
            list(self.roster.act)
            + list(self.roster.aaa)
            + list(self.roster.low)
            + list(self.roster.dl)
            + list(self.roster.ir)
        )
        def can_play(pid: str) -> bool:
            player = self.players.get(pid)
            if player is None:
                return False
            if getattr(player, "is_pitcher", False):
                return False
            primary = str(getattr(player, "primary_position", "")).upper()
            if pos == "DH":
                return True
            if primary == pos:
                return True
            for other in getattr(player, "other_positions", []) or []:
                if str(other).upper() == pos:
                    return True
            return False

        return [pid for pid in ids if can_play(pid)]

    def _populate_combo(self, combo: QComboBox, position: str) -> None:
        combo.addItem("— None —", "")
        for pid in self._eligible_players(position):
            combo.addItem(self._player_label(pid), pid)

    def _set_combo_selection(self, combo: QComboBox, player_id: str) -> None:
        target = str(player_id or "").strip()
        if not target:
            try:
                combo.setCurrentIndex(0)
            except Exception:
                pass
            return
        idx = combo.findData(target)
        if idx == -1:
            try:
                combo.addItem(self._player_label(target), target)
            except Exception:
                pass
            idx = combo.findData(target)
        if idx >= 0:
            try:
                combo.setCurrentIndex(idx)
            except Exception:
                pass

    def _auto_populate(self) -> None:
        self._refresh_data()
        assigned: set[str] = set()
        level_order = {"ACT": 0, "AAA": 1, "LOW": 2, "DL": 3, "IR": 4}

        def _sort_candidates(position: str) -> List[str]:
            pos = position.upper()
            primaries: List[str] = []
            secondaries: List[str] = []
            seen: set[str] = set()
            for pid in self._eligible_players(position):
                if pid in seen:
                    continue
                seen.add(pid)
                player = self.players.get(pid)
                primary = str(getattr(player, "primary_position", "")).upper()
                if primary == pos:
                    primaries.append(pid)
                else:
                    secondaries.append(pid)

            def _sorted(pool: List[str]) -> List[str]:
                return sorted(
                    pool,
                    key=lambda pid: (
                        level_order.get(self._level_map.get(pid, ""), 5),
                    ),
                )

            ordered = _sorted(primaries) + _sorted(secondaries)
            unique: List[str] = []
            for pid in ordered:
                if pid not in unique:
                    unique.append(pid)
            return unique

        for position in DEPTH_CHART_POSITIONS:
            candidates = _sort_candidates(position)
            choices: List[str] = []
            for pid in candidates:
                if pid not in assigned:
                    choices.append(pid)
                if len(choices) >= 3:
                    break
            if len(choices) < 3:
                for pid in candidates:
                    if pid not in choices:
                        choices.append(pid)
                    if len(choices) >= 3:
                        break
            for slot in range(3):
                combo = self._combo_map.get((position, slot))
                if combo is None:
                    continue
                pid = choices[slot] if slot < len(choices) else ""
                self._set_combo_selection(combo, pid)
            assigned.update(choices)

        self.status_label.setText("Auto-populated from current roster.")
        self._maybe_toast("info", "Depth chart auto-populated.")

    def _apply_existing_values(self) -> None:
        for pos in DEPTH_CHART_POSITIONS:
            entries = depth_order_for_position(self.chart, pos)
            for slot in range(3):
                combo = self._combo_map.get((pos, slot))
                if combo is None:
                    continue
                pid = entries[slot] if slot < len(entries) else ""
                if not pid:
                    combo.setCurrentIndex(0)
                    continue
                idx = combo.findData(pid)
                if idx == -1:
                    combo.addItem(self._player_label(pid), pid)
                    idx = combo.findData(pid)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

    def _register_event_listeners(self) -> None:
        bus = getattr(self._service, "events", None)
        if bus is None:
            return

        def _on_roster(payload: Optional[dict] = None) -> None:
            team_id = str((payload or {}).get("team_id", ""))
            if team_id and team_id != str(self.team_id):
                return
            self._queue_refresh("Roster changes detected; depth chart refreshed.")

        def _on_players(_payload: Optional[dict] = None) -> None:
            self._queue_refresh("Player data updated; depth chart refreshed.")

        for topic, handler in (
            ("rosters.updated", _on_roster),
            ("rosters.invalidated", _on_roster),
            ("players.updated", _on_players),
            ("players.invalidated", _on_players),
        ):
            try:
                self._event_unsubscribes.append(bus.subscribe(topic, handler))
            except Exception:
                pass

    def _queue_refresh(self, reason: str) -> None:
        def _execute() -> None:
            if not self._is_visible():
                self._pending_refresh = True
                self._pending_toast_reason = reason
                return
            self._pending_refresh = False
            self._pending_toast_reason = None
            self._refresh_data()
            self.status_label.setText("Auto-refreshed from latest roster data.")
            self._maybe_toast("info", reason)

        QTimer.singleShot(0, _execute)

    def _refresh_data(self) -> None:
        self.players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        self.roster = load_roster(self.team_id)
        self._level_map = self._build_level_index()
        current_choices: Dict[tuple[str, int], str] = {}
        for key, combo in self._combo_map.items():
            try:
                current = combo.currentData()
            except Exception:
                current = ""
            current_choices[key] = str(current or "")
        for (position, slot), combo in self._combo_map.items():
            try:
                combo.blockSignals(True)
            except Exception:
                pass
            try:
                combo.clear()
            except Exception:
                continue
            self._populate_combo(combo, position)
            selected = current_choices.get((position, slot), "")
            if selected:
                idx = combo.findData(selected)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)
            try:
                combo.blockSignals(False)
            except Exception:
                pass

    def _maybe_toast(self, kind: str, message: str) -> None:
        callback = self._toast_callback()
        if callable(callback):
            try:
                callback(kind, message)
            except Exception:
                pass

    def _toast_callback(self) -> Optional[Callable[[str, str], None]]:
        parent = self.parent()
        if parent is None:
            return None
        for attr in ("_show_toast", "show_toast"):
            candidate = getattr(parent, attr, None)
            if callable(candidate):
                return candidate
        return None

    def _is_visible(self) -> bool:
        try:
            return bool(self.isVisible())
        except Exception:
            return True

    def showEvent(self, event):  # pragma: no cover - GUI callback
        try:
            super().showEvent(event)
        except Exception:
            pass
        if self._pending_refresh:
            self._pending_refresh = False
            self._refresh_data()
            if self._pending_toast_reason:
                self._maybe_toast("info", self._pending_toast_reason)
                self._pending_toast_reason = None

    def closeEvent(self, event):  # pragma: no cover - GUI callback
        for unsubscribe in self._event_unsubscribes:
            try:
                unsubscribe()
            except Exception:
                pass
        self._event_unsubscribes.clear()
        try:
            super().closeEvent(event)
        except Exception:
            pass

    def _save(self) -> None:
        result: Dict[str, List[str]] = {pos: [] for pos in DEPTH_CHART_POSITIONS}
        for pos in DEPTH_CHART_POSITIONS:
            seen: set[str] = set()
            for slot in range(3):
                combo = self._combo_map.get((pos, slot))
                if combo is None:
                    continue
                pid = combo.currentData() or ""
                pid = str(pid).strip()
                if pid and pid not in seen:
                    seen.add(pid)
                    result[pos].append(pid)
        try:
            save_depth_chart(self.team_id, result)
        except Exception as exc:
            QMessageBox.warning(self, "Depth Chart", f"Failed to save depth chart: {exc}")
            return
        self.status_label.setText("Saved.")
        QMessageBox.information(self, "Depth Chart", "Depth chart saved.")


__all__ = ["DepthChartDialog"]
