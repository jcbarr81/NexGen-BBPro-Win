from __future__ import annotations

"""Injury Center (read-only).

Displays a consolidated view of injured players across all teams with the
team assignment, injury list (DL/IR), description and expected return date.
This is a viewer-only tool; roster changes are handled elsewhere.
"""

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QGridLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QAbstractItemView,
        QLineEdit,
        QComboBox,
    )
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QGuiApplication
except Exception:  # pragma: no cover - headless stubs for tests
    class _Signal:
        def __init__(self): self._s=None
        def connect(self, s): self._s=s
        def emit(self,*a,**k):
            if self._s: self._s(*a,**k)
    class QDialog:
        def __init__(self,*a,**k): pass
        def show(self): pass
    class QLabel:
        def __init__(self, t="", *a, **k): self._t=t
        def setText(self, t): self._t=t
    class QPushButton:
        def __init__(self,*a,**k): self.clicked=_Signal()
    class QTableWidget:
        def __init__(self,*a,**k): pass
        def setHorizontalHeaderLabels(self,*a,**k): pass
        def setRowCount(self,*a,**k): pass
        def setItem(self,*a,**k): pass
        def setEditTriggers(self,*a,**k): pass
        def setSelectionBehavior(self,*a,**k): pass
        def setSelectionMode(self,*a,**k): pass
    class QTableWidgetItem:
        def __init__(self, t=""): self._t=str(t)
        def text(self): return self._t
    class QVBoxLayout:
        def __init__(self,*a,**k): pass
        def addWidget(self,*a,**k): pass
        def addLayout(self,*a,**k): pass
        def setContentsMargins(self,*a,**k): pass
        def setSpacing(self,*a,**k): pass
    class QHBoxLayout(QVBoxLayout): pass
    class QGridLayout(QVBoxLayout):
        def setHorizontalSpacing(self,*a,**k): pass
        def setVerticalSpacing(self,*a,**k): pass
        def setColumnStretch(self,*a,**k): pass
    class QAbstractItemView:
        class EditTrigger: NoEditTriggers=0
        class SelectionBehavior: SelectRows=0
        class SelectionMode: SingleSelection=0
    class Qt:
        class AlignmentFlag: AlignLeft=0; AlignHCenter=0; AlignRight=0
    class QLineEdit:
        def __init__(self,*a,**k): self._t=""
        def text(self): return self._t
        def setText(self, t): self._t=t
    class QComboBox:
        def __init__(self,*a,**k): self._items=[]; self._idx=0
        def addItems(self, items): self._items=list(items)
        def currentText(self):
            return self._items[self._idx] if self._items else ""
    class QTimer:
        @staticmethod
        def singleShot(_msec, callback):
            if callback is not None:
                callback()
    class QGuiApplication:
        @staticmethod
        def primaryScreen():
            return None

from typing import Callable, Dict, List, Optional, Tuple
from datetime import datetime

from utils.player_loader import load_players_from_csv
from utils.team_loader import load_teams
from utils.roster_loader import load_roster
from utils.roster_loader import save_roster
from utils.player_writer import save_players_to_csv
from services.unified_data_service import get_unified_data_service
from services.injury_manager import (
    DL_LABELS,
    disabled_list_days_remaining,
    disabled_list_label,
    place_on_injury_list,
    recover_from_injury,
)
from utils.news_logger import log_news_event
try:
    from services.roster_auto_assign import ACTIVE_MAX, AAA_MAX, LOW_MAX
except Exception:  # sensible defaults
    ACTIVE_MAX, AAA_MAX, LOW_MAX = 25, 15, 10


_DL_CHOICES = [("dl15", DL_LABELS.get("dl15", "15-Day DL"))]


class InjuryCenterWindow(QDialog):
    def __init__(self, parent=None, *, team_filter: str | None = None):
        super().__init__(parent)
        self._team_filter = team_filter
        try:
            title = "Injury Center"
            if team_filter:
                title = f"{team_filter} Injuries"
            self.setWindowTitle(title)
            self._apply_default_size()
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("Injured Players")
        header.addWidget(self.title)
        header.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Player", "Team", "List", "Days Remaining", "Position", "Description", "Return Date"]
        )
        try:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        except Exception:
            pass
        root.addWidget(self.table)

        # Compact control panel keeps the dialog from stretching across the screen
        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        root.addLayout(controls)

        form = QGridLayout()
        try:
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(4)
        except Exception:
            pass
        controls.addLayout(form)

        form.addWidget(QLabel("Description"), 0, 0, 1, 2)
        self.desc_edit = QLineEdit()
        try:
            self.desc_edit.setPlaceholderText("e.g., Hamstring strain")
        except Exception:
            pass
        form.addWidget(self.desc_edit, 1, 0, 1, 2)

        form.addWidget(QLabel("Return (YYYY-MM-DD)"), 0, 2)
        self.ret_edit = QLineEdit()
        try:
            self.ret_edit.setPlaceholderText("YYYY-MM-DD (optional)")
            self.ret_edit.setToolTip("Enter return date in YYYY-MM-DD format. Leave blank if unknown.")
        except Exception:
            pass
        form.addWidget(self.ret_edit, 1, 2)

        form.addWidget(QLabel("List"), 0, 3)
        self.list_combo = QComboBox()
        self._dl_codes = [code for code, _label in _DL_CHOICES]
        try:
            for code, label in _DL_CHOICES:
                self.list_combo.addItem(label, code)
            self.list_combo.setToolTip("15-day disabled list")
        except Exception:
            try:
                self.list_combo.addItems([label for _, label in _DL_CHOICES])
            except Exception:
                pass
        form.addWidget(self.list_combo, 1, 3)

        form.addWidget(QLabel("Destination"), 0, 4)
        self.dest_combo = QComboBox()
        try:
            self.dest_combo.addItems(["Active (ACT)", "AAA", "Low"])
            self.dest_combo.setToolTip("Level to place player on recovery")
        except Exception:
            pass
        form.addWidget(self.dest_combo, 1, 4)

        try:
            form.setColumnStretch(0, 3)
            form.setColumnStretch(1, 0)
            form.setColumnStretch(2, 1)
            form.setColumnStretch(3, 1)
            form.setColumnStretch(4, 1)
        except Exception:
            pass

        self.btn_place_dl = QPushButton("Place on DL")
        self.btn_place_ir = QPushButton("Place on IR")
        self.btn_recover = QPushButton("Recover to Destination")
        self.btn_promote_best = QPushButton("Promote Best Replacement")
        self.role_hint_label = QLabel("Recommended: --")
        try:
            self.role_hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        except Exception:
            pass
        try:
            self.btn_place_dl.clicked.connect(lambda: self._place_on_list(self._chosen_dl_code()))
            self.btn_place_ir.clicked.connect(lambda: self._place_on_list("ir"))
            self.btn_recover.clicked.connect(self._recover)
            # Live date validation styling
            self.ret_edit.textChanged.connect(self._on_date_changed)
            self.btn_promote_best.clicked.connect(self._promote_best)
        except Exception:
            pass
        buttons_grid = QGridLayout()
        try:
            buttons_grid.setContentsMargins(0, 0, 0, 0)
            buttons_grid.setHorizontalSpacing(10)
            buttons_grid.setVerticalSpacing(6)
        except Exception:
            pass
        controls.addLayout(buttons_grid)
        for btn, row, col in (
            (self.btn_place_dl, 0, 0),
            (self.btn_place_ir, 0, 1),
            (self.btn_recover, 0, 2),
            (self.btn_promote_best, 1, 0),
        ):
            buttons_grid.addWidget(btn, row, col)
        try:
            buttons_grid.setColumnStretch(0, 1)
            buttons_grid.setColumnStretch(1, 1)
            buttons_grid.setColumnStretch(2, 1)
        except Exception:
            pass
        try:
            controls.addWidget(self.role_hint_label, alignment=Qt.AlignmentFlag.AlignRight)
        except Exception:
            controls.addWidget(self.role_hint_label)

        # Roster counts indicator
        counts_row = QHBoxLayout()
        counts_row.addWidget(QLabel("Roster Counts:"))
        self.counts_label = QLabel("ACT --/--  AAA --/--  LOW --/--")
        counts_row.addWidget(self.counts_label)
        counts_row.addStretch()
        root.addLayout(counts_row)

        # Tiny legend for limits and FULL marker
        try:
            self.counts_legend = QLabel(
                f"Legend: FULL denotes at/over capacity. Limits ACT {ACTIVE_MAX}, AAA {AAA_MAX}, LOW {LOW_MAX}."
            )
            try:
                self.counts_legend.setWordWrap(True)
                self.counts_legend.setStyleSheet("color: #888888; font-size: 11px;")
            except Exception:
                pass
            root.addWidget(self.counts_legend)
        except Exception:
            pass

        self.status = QLabel("Ready")
        root.addWidget(self.status)

        self._players_index: Dict[str, object] = {}
        self._rows: List[Dict[str, str]] = []
        self._service = get_unified_data_service()
        self._event_unsubscribes: List[Callable[[], None]] = []
        self._pending_refresh = False
        self._pending_toast_reason: Optional[str] = None
        self._selection_signal_hooked = False
        self._register_event_listeners()
        self.refresh()

    def _apply_default_size(self) -> None:
        """Scale the dialog to a comfortable fraction of the screen size."""
        min_w, min_h = 820, 520
        try:
            self.setMinimumSize(min_w, min_h)
        except Exception:
            pass
        screen = None
        try:
            screen = self.screen()
        except Exception:
            screen = None
        if not screen:
            try:
                screen = QGuiApplication.primaryScreen()
            except Exception:
                screen = None
        if screen:
            try:
                geom = screen.availableGeometry()
            except Exception:
                geom = None
            if geom:
                width = max(min_w, min(int(geom.width() * 0.6), 1300))
                height = max(min_h, min(int(geom.height() * 0.65), 900))
                self.resize(width, height)
                return
        self.resize(960, 600)

    def refresh(self) -> None:
        # Build player -> team/list lookup tables from current rosters
        team_lookup: Dict[str, str] = {}
        injury_list_lookup: Dict[str, str] = {}
        try:
            teams = load_teams()
        except Exception:
            teams = []
        for t in teams:
            team_id = str(getattr(t, "team_id", "")).strip()
            if not team_id:
                continue
            try:
                roster = load_roster(team_id)
            except Exception:
                continue
            for group in ("act", "aaa", "low", "dl", "ir"):
                for pid in getattr(roster, group, []) or []:
                    if pid:
                        team_lookup[pid] = team_id
            tier_map = getattr(roster, "dl_tiers", {}) or {}
            for pid in getattr(roster, "dl", []) or []:
                if pid:
                    injury_list_lookup[pid] = tier_map.get(pid, "dl15")
            for pid in getattr(roster, "ir", []) or []:
                if pid:
                    injury_list_lookup[pid] = "ir"

        # Load player details and build filtered list
        try:
            players = load_players_from_csv("data/players.csv")
        except Exception:
            players = []
        injured: List[object] = []
        self._players_index = {getattr(p, 'player_id', ''): p for p in players}
        for p in players:
            pid = getattr(p, 'player_id', '')
            if not pid:
                continue
            if getattr(p, 'injured', False) or pid in injury_list_lookup:
                injured.append(p)

        # Filter players for display
        display_rows: List[Tuple[object, str, str]] = []
        for p in injured:
            pid = getattr(p, 'player_id', '')
            if not pid:
                continue
            team_id = team_lookup.get(pid, "")
            if self._team_filter and team_id != self._team_filter:
                continue
            list_code = getattr(p, 'injury_list', None) or injury_list_lookup.get(pid, "") or ""
            display_rows.append((p, team_id, list_code))

        # Fill table with filtered rows
        self.table.setRowCount(len(display_rows))
        self._rows = []
        for row, (p, team_id, list_code) in enumerate(display_rows):
            pid = getattr(p, 'player_id', '')
            name = f"{getattr(p,'first_name','')} {getattr(p,'last_name','')}".strip()
            list_label = disabled_list_label(list_code)
            pos = getattr(p, 'primary_position', '')
            desc = getattr(p, 'injury_description', '') or ""
            ret = getattr(p, 'return_date', '') or ""
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(team_id))
            self.table.setItem(row, 2, QTableWidgetItem(list_label))
            days_remaining = disabled_list_days_remaining(p)
            days_text = str(days_remaining) if days_remaining is not None else ""
            self.table.setItem(row, 3, QTableWidgetItem(days_text))
            self.table.setItem(row, 4, QTableWidgetItem(str(pos)))
            self.table.setItem(row, 5, QTableWidgetItem(desc))
            self.table.setItem(row, 6, QTableWidgetItem(ret))
            self._rows.append({"player_id": pid, "team_id": team_id, "list": list_code})

        if self._team_filter:
            self.status.setText(f"Showing {len(display_rows)} injured players for {self._team_filter}")
        else:
            self.status.setText(f"Showing {len(display_rows)} injured players")
        if not self._selection_signal_hooked:
            try:
                self.table.itemSelectionChanged.connect(self._on_selection_changed)
                self._selection_signal_hooked = True
            except Exception:
                pass
        self._on_selection_changed()

    def _register_event_listeners(self) -> None:
        bus = getattr(self._service, "events", None)
        if bus is None:
            return

        def _on_roster(_payload: Optional[dict] = None) -> None:
            self._queue_refresh("Roster changes detected; injury data refreshed.")

        def _on_players(_payload: Optional[dict] = None) -> None:
            self._queue_refresh("Player information updated; injury data refreshed.")

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
                try:
                    self.status.setText("Changes detected; refresh will run when reopened.")
                except Exception:
                    pass
                return
            self._pending_refresh = False
            self._pending_toast_reason = None
            self.refresh()
            self._maybe_toast("info", reason)

        QTimer.singleShot(0, _execute)

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

    def showEvent(self, event):  # pragma: no cover - UI callback
        try:
            super().showEvent(event)
        except Exception:
            pass
        if self._pending_refresh:
            self._pending_refresh = False
            self.refresh()
            if self._pending_toast_reason:
                self._maybe_toast("info", self._pending_toast_reason)
                self._pending_toast_reason = None

    def closeEvent(self, event):  # pragma: no cover - UI callback
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

    # ------------------------------------------------------------------
    # Actions
    def _set_field_valid(self, widget, valid: bool) -> None:
        try:
            if valid:
                widget.setStyleSheet("")
            else:
                widget.setStyleSheet("border: 1px solid #cc4455;")
        except Exception:
            pass

    def _on_date_changed(self) -> None:
        try:
            txt = (self.ret_edit.text() or "").strip()
        except Exception:
            txt = ""
        ok = self._validate_iso_date(txt)
        self._set_field_valid(self.ret_edit, ok)
        if not ok:
            try:
                self.status.setText("Return date must be YYYY-MM-DD")
            except Exception:
                pass
    def _validate_iso_date(self, s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return True
        try:
            # Accept strict YYYY-MM-DD
            datetime.strptime(s, "%Y-%m-%d")
            return True
        except Exception:
            return False
    def _selected(self) -> Tuple[str | None, str | None]:
        row = getattr(self.table, 'currentRow', lambda: -1)()
        if row is None or row < 0 or row >= len(self._rows):
            return None, None
        return self._rows[row].get("player_id"), self._rows[row].get("team_id")

    def _update_counts(self, team_id: str | None) -> None:
        if not team_id:
            try:
                self.counts_label.setText(f"ACT --/{ACTIVE_MAX}  AAA --/{AAA_MAX}  LOW --/{LOW_MAX}")
                self.counts_label.setStyleSheet("")
            except Exception:
                pass
            return
        try:
            r = load_roster(team_id)
        except Exception:
            try:
                self.counts_label.setText(f"ACT ?/{ACTIVE_MAX}  AAA ?/{AAA_MAX}  LOW ?/{LOW_MAX}")
                self.counts_label.setStyleSheet("color: #cc8844;")
            except Exception:
                pass
            return
        act, aaa, low = len(getattr(r, 'act', []) or []), len(getattr(r, 'aaa', []) or []), len(getattr(r, 'low', []) or [])
        # Append FULL marker for any level at or above capacity
        act_mark = " (FULL)" if act >= ACTIVE_MAX else ""
        aaa_mark = " (FULL)" if aaa >= AAA_MAX else ""
        low_mark = " (FULL)" if low >= LOW_MAX else ""
        text = f"ACT {act}/{ACTIVE_MAX}{act_mark}  AAA {aaa}/{AAA_MAX}{aaa_mark}  LOW {low}/{LOW_MAX}{low_mark}"
        try:
            self.counts_label.setText(text)
            # Visual warning: orange when any level is at/over capacity; else default
            if act >= ACTIVE_MAX or aaa >= AAA_MAX or low >= LOW_MAX:
                self.counts_label.setStyleSheet("color: #cc8844; font-weight: 600;")
            else:
                self.counts_label.setStyleSheet("")
        except Exception:
            pass

    def _on_selection_changed(self) -> None:
        pid, team_id = self._selected()
        self._update_counts(team_id)
        # Update role hint
        try:
            p = self._players_index.get(pid or "")
            if p is not None:
                is_pitcher = bool(getattr(p, 'is_pitcher', False) or str(getattr(p, 'primary_position', '')).upper() == 'P')
                hint = "Pitcher" if is_pitcher else "Hitter"
                self.role_hint_label.setText(f"Recommended: {hint}")
            else:
                self.role_hint_label.setText("Recommended: --")
        except Exception:
            pass

    def _find_team_and_roster(self, pid: str) -> Tuple[str | None, object | None]:
        try:
            teams = load_teams()
        except Exception:
            teams = []
        for t in teams:
            try:
                r = load_roster(t.team_id)
            except Exception:
                continue
            for level in ("act", "aaa", "low", "dl", "ir"):
                if pid in getattr(r, level):
                    return t.team_id, r
        return None, None

    def _persist_player(self, player) -> None:
        try:
            plist = list(load_players_from_csv("data/players.csv"))
        except Exception:
            return
        replaced = False
        for idx, existing in enumerate(plist):
            if getattr(existing, "player_id", "") == getattr(player, "player_id", ""):
                plist[idx] = player
                replaced = True
                break
        if not replaced:
            plist.append(player)
        try:
            from utils.path_utils import get_data_dir

            save_players_to_csv(plist, str(get_data_dir() / 'players.csv'))
        except Exception:
            pass
        try:
            load_players_from_csv.cache_clear()
        except Exception:
            pass

    def _chosen_dl_code(self) -> str:
        codes = getattr(self, "_dl_codes", ["dl15"])
        try:
            idx = self.list_combo.currentIndex()
        except Exception:
            idx = 0
        if 0 <= idx < len(codes):
            return codes[idx]
        return codes[0] if codes else "dl15"

    def _place_on_list(self, list_name: str) -> None:
        pid, team_hint = self._selected()
        if not pid:
            self.status.setText("Select a player first.")
            return
        player = self._players_index.get(pid)
        if player is None:
            self.status.setText("Player not found in database.")
            return
        team_id, roster = (team_hint, None)
        if not team_id:
            team_id, roster = self._find_team_and_roster(pid)
        if not team_id:
            self.status.setText("Could not determine player's team.")
            return
        if self._team_filter and team_id != self._team_filter:
            self.status.setText("Cannot modify injuries for other teams.")
            return
        if roster is None:
            try:
                roster = load_roster(team_id)
            except Exception as exc:
                self.status.setText(f"Failed to load roster: {exc}")
                return
        # Update player injury fields
        try:
            place_on_injury_list(player, roster, list_name)
            desc = self.desc_edit.text().strip()
            ret = self.ret_edit.text().strip()
            if not self._validate_iso_date(ret):
                self.status.setText("Return date must be YYYY-MM-DD")
                return
            try:
                player.injured = True
                player.injury_description = desc or player.injury_description
                eligible = getattr(player, "injury_eligible_date", None)
                adjusted_ret = ret
                if ret and eligible:
                    try:
                        ret_dt = datetime.strptime(ret, "%Y-%m-%d").date()
                        elig_dt = datetime.strptime(eligible, "%Y-%m-%d").date()
                    except Exception:
                        pass
                    else:
                        if ret_dt < elig_dt:
                            adjusted_ret = eligible
                    if adjusted_ret != ret:
                        try:
                            self.status.setText("Return date adjusted to earliest eligible day.")
                        except Exception:
                            pass
                player.return_date = adjusted_ret or player.return_date
            except Exception:
                pass
            save_roster(team_id, roster)
            self._persist_player(player)
            # Clear caches
            try:
                load_roster.cache_clear()
            except Exception:
                pass
            readable_list = disabled_list_label(list_name) or list_name.upper()
            log_news_event(
                f"Placed {getattr(player,'first_name','')} {getattr(player,'last_name','')} on {readable_list} ({team_id})"
            )
            self.refresh()
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")

    def _recover(self) -> None:
        pid, team_hint = self._selected()
        if not pid:
            self.status.setText("Select a player first.")
            return
        player = self._players_index.get(pid)
        if player is None:
            self.status.setText("Player not found in database.")
            return
        team_id, roster = (team_hint, None)
        if not team_id:
            team_id, roster = self._find_team_and_roster(pid)
        if not team_id:
            self.status.setText("Could not determine player's team.")
            return
        if roster is None:
            try:
                roster = load_roster(team_id)
            except Exception as exc:
                self.status.setText(f"Failed to load roster: {exc}")
                return
        try:
            # Destination mapping
            dest_label = ""
            try:
                dest_label = (self.dest_combo.currentText() or "").lower()
            except Exception:
                dest_label = "active (act)"
            dest = "act"
            if "aaa" in dest_label:
                dest = "aaa"
            elif "low" in dest_label:
                dest = "low"
            list_label = disabled_list_label(getattr(player, "injury_list", None)) or "injury list"
            try:
                recover_from_injury(player, roster, destination=dest)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            try:
                player.injured = False
                player.injury_description = None
                player.return_date = None
            except Exception:
                pass
            save_roster(team_id, roster)
            self._persist_player(player)
            try:
                load_roster.cache_clear()
            except Exception:
                pass
            log_news_event(
                f"Activated {getattr(player,'first_name','')} {getattr(player,'last_name','')} from {list_label} ({team_id})"
            )
            self.refresh()
        except Exception as exc:
            self.status.setText(f"Failed: {exc}")

    def _promote_best(self) -> None:
        # Promote best replacement from AAA/Low to ACT for the selected team
        _pid, team_id = self._selected()
        if not team_id:
            self.status.setText("Select a team row first.")
            return
        try:
            roster = load_roster(team_id)
        except Exception as exc:
            self.status.setText(f"Failed to load roster: {exc}")
            return
        if len(getattr(roster, 'act', []) or []) >= ACTIVE_MAX:
            self.status.setText(f"Active roster already at limit ({ACTIVE_MAX}).")
            return
        # Load players to score candidates
        try:
            players = load_players_from_csv("data/players.csv")
        except Exception:
            players = []
        pmap = {getattr(p, 'player_id', ''): p for p in players}
        # Decide candidate pool from AAA then Low
        pool_ids = (getattr(roster, 'aaa', []) or []) + (getattr(roster, 'low', []) or [])
        if not pool_ids:
            self.status.setText("No candidates in AAA/Low.")
            return
        # If a player is selected, prefer role-aware promotion using that player's type
        sel_pid, _ = self._selected()
        sel_obj = pmap.get(sel_pid or "")
        sel_is_pitcher = bool(getattr(sel_obj, 'is_pitcher', False) or str(getattr(sel_obj, 'primary_position', '')).upper() == 'P') if sel_obj else False

        def pitcher_score(p):
            return (float(getattr(p, 'endurance', 0)) * 0.5 + float(getattr(p, 'control', 0)) * 0.3 + float(getattr(p, 'movement', 0)) * 0.2)

        def hitter_score(p):
            keys = ['ch','ph','sp','pl','vl','sc','fa','arm']
            vals = []
            for k in keys:
                try:
                    vals.append(float(getattr(p, k, 0)))
                except Exception:
                    vals.append(0.0)
            return sum(vals)/len(vals) if vals else 0.0

        best_id = None
        best_val = -1.0
        for pid in pool_ids:
            p = pmap.get(pid)
            if not p:
                continue
            is_pitcher = bool(getattr(p, 'is_pitcher', False) or str(getattr(p, 'primary_position', '')).upper() == 'P')
            if sel_obj:
                # Role-aware: match type of injured/selected player
                if sel_is_pitcher and not is_pitcher:
                    continue
                if not sel_is_pitcher and is_pitcher:
                    continue
            score = pitcher_score(p) if is_pitcher else hitter_score(p)
            if score > best_val:
                best_val = score
                best_id = pid
        if not best_id:
            self.status.setText("No suitable candidate found.")
            return
        # Promote: remove from AAA/Low and append to ACT
        try:
            if best_id in roster.aaa:
                roster.aaa.remove(best_id)
            elif best_id in roster.low:
                roster.low.remove(best_id)
            roster.act.append(best_id)
            save_roster(team_id, roster)
            try:
                load_roster.cache_clear()
            except Exception:
                pass
            log_news_event(f"Promoted {best_id} to ACT for {team_id}")
            self.refresh()
        except Exception as exc:
            self.status.setText(f"Failed to promote: {exc}")


__all__ = ["InjuryCenterWindow"]
