from __future__ import annotations

"""Minimal Draft Console (phase 2 scaffold).

Pauses on Draft Day; can generate a pool, compute a draft order, and auto-draft
multiple rounds while persisting state/results. UI will be expanded in later
phases.
"""

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QLabel,
        QPushButton,
        QMessageBox,
        QTableWidget,
        QTableWidgetItem,
        QHBoxLayout,
        QLineEdit,
        QFrame,
        QGridLayout,
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap
except Exception:  # pragma: no cover - lightweight stubs for headless tests
    class _Signal:
        def __init__(self):
            self._slot = None

        def connect(self, slot):
            self._slot = slot

        def emit(self, *a, **k):
            if self._slot:
                self._slot(*a, **k)

    class QDialog:
        def __init__(self, *a, **k):
            pass

        def accept(self):
            pass

        def exec(self):
            return 0

    class QLabel:
        def __init__(self, text: str = "", *a, **k):
            self._text = text

        def setText(self, text: str):
            self._text = text

        def text(self) -> str:
            return self._text

        def setPixmap(self, *a, **k):
            pass

        class _Font:
            def setPointSize(self, *a, **k):
                pass

            def setBold(self, *a, **k):
                pass

        def font(self):
            return QLabel._Font()

        def setFont(self, *a, **k):
            pass

    class QPushButton:
        def __init__(self, *a, **k):
            self.clicked = _Signal()

        def setObjectName(self, *a, **k):
            pass

    class QMessageBox:
        class StandardButton:
            Yes = 1
            No = 2

        @staticmethod
        def warning(*a, **k):
            return None

        @staticmethod
        def information(*a, **k):
            return None

        @staticmethod
        def question(*a, **k):
            return QMessageBox.StandardButton.Yes

    class QTableWidgetItem:
        def __init__(self, text=""):
            self._text = str(text)

        def text(self):
            return self._text

        def setText(self, text: str) -> None:
            self._text = str(text)

        def setData(self, *_args, **_kwargs) -> None:
            return None

    class QTableWidget:
        def __init__(self, *a, **k):
            pass

        def setHorizontalHeaderLabels(self, *a, **k):
            pass

        class _VH:
            def setVisible(self, *a, **k):
                pass

        def verticalHeader(self):
            return QTableWidget._VH()

        class EditTrigger:
            NoEditTriggers = 0

        def setEditTriggers(self, *a, **k):
            pass

        def setRowCount(self, *a, **k):
            pass

        def setItem(self, *a, **k):
            pass

        def setCellWidget(self, *a, **k):
            pass

        def resizeColumnsToContents(self, *a, **k):
            pass

        def item(self, *a, **k):
            return None

        def rowCount(self):
            return 0

        def columnCount(self):
            return 0

        def setRowHidden(self, *a, **k):
            pass

    class QHBoxLayout:
        def __init__(self, *a, **k):
            pass

        def addWidget(self, *a, **k):
            pass

        def addLayout(self, *a, **k):
            pass

        def addStretch(self, *a, **k):
            pass

    class QVBoxLayout(QHBoxLayout):
        def setContentsMargins(self, *a, **k):
            pass

        def setSpacing(self, *a, **k):
            pass

    class QLineEdit:
        def __init__(self, *a, **k):
            self.textChanged = _Signal()

        def text(self):
            return ""

    class QGridLayout:
        def __init__(self, *a, **k):
            pass

        def setContentsMargins(self, *a, **k):
            pass

        def setHorizontalSpacing(self, *a, **k):
            pass

        def setVerticalSpacing(self, *a, **k):
            pass

        def addWidget(self, *a, **k):
            pass

    class QFrame:
        class Shape:
            StyledPanel = 0

        def setFrameShape(self, *a, **k):
            pass

    class Qt:
        class AlignmentFlag:
            AlignHCenter = 0
        class ItemDataRole:
            DisplayRole = 0
            EditRole = 2

    class QPixmap:
        def __init__(self, *a, **k):
            pass

        def isNull(self):
            return False

from datetime import datetime
from types import SimpleNamespace

from playbalance.draft_config import load_draft_config
from playbalance.draft_pool import generate_draft_pool, load_draft_pool, save_draft_pool
from services.draft_state import (
    append_result,
    compute_order_from_season_stats,
    initialize_state,
    load_state,
    save_state,
)
from services.season_progress_flags import ProgressUpdateError, mark_draft_completed
from ui.star_rating import star_label, star_pixmap
from utils.exceptions import DraftRosterError
from utils.news_logger import log_news_event
from utils.rating_display import overall_rating, rating_display_text, rating_display_value
from utils.team_loader import load_teams


class DraftConsole(QDialog):
    def __init__(self, draft_date: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Amateur Draft — Commissioner's Console")
        self.resize(1000, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        cfg = load_draft_config()
        self._cfg = cfg
        self._seed_value = None
        self.DRAFT_ROUNDS = int(cfg.get("rounds", 10))

        year = int(draft_date.split("-")[0]) if draft_date else 0
        self.year = year
        self.draft_date = draft_date
        self.assignment_failures: list[str] = []
        self.assignment_summary: dict[str, object] = {}
        self.last_assignment_error: DraftRosterError | None = None
        self.banner = QLabel(f"Draft Day: {draft_date}")
        bfont = self.banner.font()
        bfont.setPointSize(max(bfont.pointSize() + 2, 12))
        bfont.setBold(True)
        self.banner.setFont(bfont)
        layout.addWidget(self.banner)
        self.status = QLabel("Draft pool not generated yet.")
        layout.addWidget(self.status)

        btn_gen = QPushButton("Generate Draft Pool")
        btn_order = QPushButton("Compute Draft Order")
        btn_start = QPushButton("Auto Draft All")
        btn_make = QPushButton("Make Pick")
        btn_auto_this = QPushButton("Auto Pick (This Team)")
        btn_commit = QPushButton("Commit Draftees to Rosters")
        btn_close = QPushButton("Close")
        btn_gen.setObjectName("Primary")
        btn_order.setObjectName("Primary")
        btn_start.setObjectName("Primary")
        row_btns = QHBoxLayout()
        row_btns.addWidget(btn_gen)
        row_btns.addWidget(btn_order)
        row_btns.addWidget(btn_start)
        layout.addLayout(row_btns)

        # Main area: left (pool) | right (on-clock + preview + board)
        main = QHBoxLayout()
        layout.addLayout(main, 1)

        # Left: pool table + search
        left = QVBoxLayout()
        # Columns: [hidden ID], Name, Age, Pos, OVR, B/T, CH/PH/SP, ARM/FA, EN/CO/MV
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "Name",
            "Age",
            "Pos",
            "OVR",
            "B/T",
            "CH/PH/SP",
            "ARM/FA",
            "EN/CO/MV",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Hide the ID column from view
        try:
            self.table.setColumnHidden(0, True)
        except Exception:
            pass
        try:
            self.table.itemDoubleClicked.connect(self._open_profile_from_selection)
        except Exception:
            pass
        left.addWidget(self.table, 1)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        sr.addWidget(self.search, 1)
        left.addLayout(sr)
        main.addLayout(left, 2)

        # Right: on-the-clock, preview, and recent picks board
        right = QVBoxLayout()
        right.setSpacing(8)
        self.onclock = QLabel("On the clock: —")
        of = self.onclock.font()
        of.setBold(True)
        self.onclock.setFont(of)
        right.addWidget(self.onclock)

        # Preview panel
        self.preview = QFrame()
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(self.preview)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self._pv_labels = {
            "id": QLabel("ID:"),
            "name": QLabel("Name:"),
            "age": QLabel("Age:"),
            "pos": QLabel("Pos:"),
            "ovr": QLabel("OVR:"),
            "bt": QLabel("B/T:"),
            "hit": QLabel("CH/PH/SP:"),
            "def": QLabel("ARM/FA:"),
            "pit": QLabel("EN/CO/MV:"),
        }
        self._pv_values = {k: QLabel("") for k in self._pv_labels}
        for row, key in enumerate(["id", "name", "age", "pos", "ovr", "bt", "hit", "def", "pit"]):
            grid.addWidget(self._pv_labels[key], row, 0)
            grid.addWidget(self._pv_values[key], row, 1)
        right.addWidget(self.preview)

        # Recent picks board (top 10)
        # Columns: Pick, Team, Player (POS + Name), Age, OVR
        self.board = QTableWidget(0, 5)
        self.board.setHorizontalHeaderLabels(["Pick", "Team", "Player", "Age", "OVR"])
        self.board.verticalHeader().setVisible(False)
        self.board.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right.addWidget(QLabel("Recent Picks:"))
        right.addWidget(self.board, 1)
        main.addLayout(right, 1)

        action_row = QHBoxLayout()
        action_row.addWidget(btn_make)
        action_row.addWidget(btn_auto_this)
        action_row.addWidget(btn_commit)
        action_row.addStretch(1)
        action_row.addWidget(btn_close)
        layout.addLayout(action_row)

        btn_gen.clicked.connect(self._generate_pool)
        btn_order.clicked.connect(self._compute_order)
        btn_start.clicked.connect(self._auto_complete)
        btn_make.clicked.connect(self._make_pick)
        btn_auto_this.clicked.connect(self._auto_pick_current)
        btn_commit.clicked.connect(self._commit_to_rosters)
        btn_close.clicked.connect(self._close_if_complete)
        self.search.textChanged.connect(self._apply_filter)
        self.table.itemSelectionChanged.connect(self._update_preview_from_selection)

        # Show existing pool/state
        self.pool = load_draft_pool(self.year)
        if self.pool:
            self.status.setText(f"Draft pool loaded ({len(self.pool)} players).")
            # Build an index for lookup by ID
            self._pool_index = {str(p.get("player_id", "")): p for p in self.pool}
            self._populate_table(self.pool)
        self.state = load_state(self.year) or {}
        self._order_names = {t.team_id: f"{t.city} {t.name}" for t in load_teams()}
        # Establish seed: prefer existing state, else config, else default to year
        try:
            self._seed_value = self.state.get("seed") if self.state else None
        except Exception:
            self._seed_value = None
        if self._seed_value is None:
            self._seed_value = cfg.get("seed")
        if self._seed_value is None:
            self._seed_value = self.year
        # Ensure saved state aligns with current config (round count, team count)
        self._repair_state_to_config()
        self._remove_already_selected()
        self._update_status_round()
        self._rebuild_board()

    def _generate_pool(self) -> None:
        size = int(self._cfg.get("pool_size", 200))
        seed = None if self._seed_value is None else int(self._seed_value)
        pool = generate_draft_pool(self.year, size=size, seed=seed)
        save_draft_pool(self.year, pool)
        self.pool = [p.__dict__ for p in pool]
        self._pool_index = {str(p.get("player_id", "")): p for p in self.pool}
        self.status.setText(f"Draft pool generated ({len(pool)} players).")
        self._populate_table(self.pool)

    def _compute_order(self) -> None:
        seed = None if self._seed_value is None else int(self._seed_value)
        order = compute_order_from_season_stats(seed=seed)
        if not order:
            QMessageBox.warning(self, "Draft Order", "Unable to compute order from season stats.")
            return
        self.state = initialize_state(self.year, order=order, seed=seed)
        self.status.setText(f"Draft order computed for {len(order)} teams. Ready to draft.")
        self._update_status_round()
        self._rebuild_board()

    def _auto_complete(self) -> None:
        if not self.pool:
            QMessageBox.warning(self, "Draft", "Generate the draft pool first.")
            return
        if not self.state.get("order"):
            self._compute_order()
            if not self.state.get("order"):
                return
        while not self._is_complete():
            self._auto_pick_current()
        QMessageBox.information(self, "Draft Complete", "Auto-draft of all rounds complete.")
        # Keep the console open so the commissioner can review and commit
        # results; do not close the dialog automatically here.

    # UI helpers
    def _age_from_birthdate(self, birthdate: str | None) -> str:
        if not birthdate or not self.draft_date:
            return ""
        try:
            b = datetime.strptime(str(birthdate), "%Y-%m-%d").date()
            d = datetime.strptime(str(self.draft_date), "%Y-%m-%d").date()
            years = d.year - b.year - ((d.month, d.day) < (b.month, b.day))
            return str(max(0, years))
        except Exception:
            return ""

    def _overall_rating(self, p: dict) -> int:
        try:
            is_pitcher = bool(p.get("is_pitcher")) or str(
                p.get("primary_position", "")
            ).upper() == "P"
            payload = dict(p)
            payload["is_pitcher"] = is_pitcher
            if not payload.get("primary_position"):
                hint = "P" if is_pitcher else ""
                payload["primary_position"] = hint
            player = SimpleNamespace(**payload)
            return overall_rating(player)
        except Exception:
            return 0

    def _overall_display_value(self, p: dict) -> float | None:
        if not p:
            return None
        is_pitcher = bool(p.get("is_pitcher")) or str(
            p.get("primary_position", "")
        ).upper() == "P"
        raw = self._overall_rating(p)
        display = rating_display_value(
            raw,
            key="OVR",
            position=p.get("primary_position"),
            is_pitcher=is_pitcher,
            mode="scale_99",
        )
        try:
            return float(display)
        except (TypeError, ValueError):
            return None

    def _set_ovr_cell(
        self,
        table: QTableWidget,
        row: int,
        col: int,
        display_value: float | None,
        *,
        size: int = 9,
    ) -> None:
        item = QTableWidgetItem("")
        if display_value is not None:
            item.setData(Qt.ItemDataRole.EditRole, float(display_value))
        table.setItem(row, col, item)
        if display_value is None:
            return
        star = star_label(
            display_value,
            min_rating=35.0,
            max_rating=99.0,
            size=size,
            fixed_size=False,
        )
        table.setCellWidget(row, col, star)

    def _set_preview_ovr(self, display_value: float | None) -> None:
        label = self._pv_values.get("ovr")
        if label is None:
            return
        if display_value is None:
            label.setPixmap(QPixmap())
            label.setText("")
            return
        pix = star_pixmap(
            display_value,
            min_rating=35.0,
            max_rating=99.0,
            size=14,
        )
        if pix is None:
            label.setPixmap(QPixmap())
            label.setText("")
            return
        label.setPixmap(pix)
        label.setText("")

    def _populate_table(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            name = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
            bt = f"{p.get('bats','?')}/{p.get('throws','?')}"
            pos = p.get("primary_position", "?")
            is_pitcher = bool(p.get("is_pitcher")) or str(p.get("primary_position", "")).upper() == "P"
            chphsp = (
                f"{rating_display_text(p.get('ch', 0), key='CH', position=pos, is_pitcher=is_pitcher)}"
                f"/{rating_display_text(p.get('ph', 0), key='PH', position=pos, is_pitcher=is_pitcher)}"
                f"/{rating_display_text(p.get('sp', 0), key='SP', position=pos, is_pitcher=is_pitcher)}"
            )
            armfa = (
                f"{rating_display_text(p.get('arm', 0), key='AS', position=pos, is_pitcher=is_pitcher)}"
                f"/{rating_display_text(p.get('fa', 0), key='FA', position=pos, is_pitcher=is_pitcher)}"
            )
            age = self._age_from_birthdate(str(p.get("birthdate", "")))
            self.table.setItem(r, 0, QTableWidgetItem(p.get("player_id", "")))
            self.table.setItem(r, 1, QTableWidgetItem(name))
            self.table.setItem(r, 2, QTableWidgetItem(age))
            self.table.setItem(r, 3, QTableWidgetItem(pos))
            display_ovr = self._overall_display_value(p)
            self._set_ovr_cell(self.table, r, 4, display_ovr)
            self.table.setItem(r, 5, QTableWidgetItem(bt))
            self.table.setItem(r, 6, QTableWidgetItem(chphsp))
            self.table.setItem(r, 7, QTableWidgetItem(armfa))
            encomo = (
                f"{rating_display_text(p.get('endurance', 0), key='EN', position=pos, is_pitcher=True)}"
                f"/{rating_display_text(p.get('control', 0), key='CO', position=pos, is_pitcher=True)}"
                f"/{rating_display_text(p.get('movement', 0), key='MO', position=pos, is_pitcher=True)}"
                if is_pitcher
                else ""
            )
            self.table.setItem(r, 8, QTableWidgetItem(encomo))
        self.table.resizeColumnsToContents()
        # Maintain preview after refresh
        self._update_preview_from_selection()

    def _apply_filter(self) -> None:
        term = (self.search.text() or "").strip().lower()
        for r in range(self.table.rowCount()):
            match = not term
            if not match:
                for c in range(self.table.columnCount()):
                    item = self.table.item(r, c)
                    if item and term in item.text().lower():
                        match = True
                        break
            self.table.setRowHidden(r, not match)

    # Draft mechanics
    def _remove_already_selected(self) -> None:
        picks = self.state.get("selected", [])
        if not picks:
            return
        selected_ids = {p.get("player_id") for p in picks}
        self.pool = [p for p in self.pool if p.get("player_id") not in selected_ids]
        self._populate_table(self.pool)
        self._rebuild_board()

    def _update_status_round(self) -> None:
        if not self.state.get("order"):
            return
        if self._is_complete():
            # Draft is complete; show a clear message instead of an overflow round
            self.status.setText(f"Draft complete — {self.DRAFT_ROUNDS} rounds finished.")
            self.onclock.setText("Draft complete")
            return
        overall = int(self.state.get("overall_pick", 1))
        teams_count = len(self.state["order"])
        rnd = (overall - 1) // teams_count + 1
        idx = (overall - 1) % teams_count
        team_id = self.state["order"][idx]
        team_name = self._order_names.get(team_id, team_id)
        # Clamp round for display in case a stale state overshoots config
        self.state["round"] = rnd
        disp_round = min(max(int(rnd), 1), int(self.DRAFT_ROUNDS or 1))
        banner = (
            f"Round {disp_round}/{self.DRAFT_ROUNDS} — Pick {idx+1} of {teams_count} — "
            f"On the clock: {team_name}"
        )
        self.status.setText(banner)
        self.onclock.setText(f"On the clock: {team_name}")

    def _current_team(self) -> str | None:
        if not self.state.get("order"):
            return None
        overall = int(self.state.get("overall_pick", 1))
        idx = (overall - 1) % len(self.state["order"])
        return self.state["order"][idx]

    def _score(self, p: dict) -> int:
        """Fallback score (should not be used)."""
        if p.get("is_pitcher"):
            return int(p.get("endurance", 0)) + int(p.get("control", 0)) + int(p.get("movement", 0))
        return int(p.get("ch", 0)) + int(p.get("ph", 0)) + int(p.get("sp", 0))

    def _score_needaware(self, p: dict, team_id: str) -> int:
        try:
            from services.draft_ai import compute_team_needs, score_prospect
            cache = getattr(self, "_needs_cache", {})
            needs = cache.get(team_id)
            if needs is None:
                needs = compute_team_needs(team_id)
                if not hasattr(self, "_needs_cache"):
                    self._needs_cache = {}
                self._needs_cache[team_id] = needs
            return score_prospect(p, needs)
        except Exception:
            return self._score(p)

    def _make_pick(self) -> None:
        team_id = self._current_team()
        if team_id is None:
            return
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Draft", "Select a prospect to make a pick.")
            return
        pid = self.table.item(row, 0).text()
        self._commit_pick(team_id, pid)

    def _auto_pick_current(self) -> None:
        team_id = self._current_team()
        if team_id is None:
            return
        if not self.pool:
            return
        # choose best by score
        best = max(self.pool, key=lambda pr: self._score_needaware(pr, team_id))
        self._commit_pick(team_id, best.get("player_id", ""))

    def _commit_pick(self, team_id: str, pid: str) -> None:
        if not pid:
            return
        overall = int(self.state.get("overall_pick", 1))
        rnd = int(self.state.get("round", 1))
        self.state.setdefault("selected", []).append(
            {
                "round": rnd,
                "overall_pick": overall,
                "team_id": team_id,
                "player_id": pid,
            }
        )
        append_result(self.year, team_id=team_id, player_id=pid, rnd=rnd, overall=overall)
        # Remove from pool and advance
        self.pool = [p for p in self.pool if p.get("player_id") != pid]
        self._populate_table(self.pool)
        self.state["overall_pick"] = overall + 1
        save_state(self.year, self.state)
        if not self._is_complete():
            self._update_status_round()
            self._rebuild_board()
        else:
            # Reflect completion immediately in the UI
            self._update_status_round()

    def _is_complete(self) -> bool:
        if not self.state.get("order"):
            return False
        total_picks = self.DRAFT_ROUNDS * len(self.state["order"])
        return int(self.state.get("overall_pick", 1)) > total_picks

    def _repair_state_to_config(self) -> None:
        """Ensure loaded state is consistent with current config.

        Handles cases where a saved draft_state has an ``overall_pick`` or
        selection list that extends beyond the configured number of rounds, or
        where the team count has changed since the state was created. The goal
        is to avoid showing nonsensical banners like "Round 4/3" by clamping
        to the configured bounds and treating overflow as draft complete.
        """
        order = list(self.state.get("order", []))
        if not order:
            return
        teams_count = len(order)
        max_overall = max(int(self.DRAFT_ROUNDS or 0), 0) * teams_count
        overall = int(self.state.get("overall_pick", 1))
        if overall < 1:
            overall = 1
        # Clamp overall to "complete" if it exceeds configured rounds
        if overall > max_overall + 1:
            overall = max_overall + 1
        # Optionally trim saved selections beyond configured limit (non-destructive to CSV)
        sel = list(self.state.get("selected", []))
        if sel and len(sel) > max_overall:
            sel = sel[:max_overall]
            self.state["selected"] = sel
        self.state["overall_pick"] = overall
        # Persist the repaired state so subsequent opens are sane
        try:
            save_state(self.year, self.state)
        except Exception:
            pass

    def _close_if_complete(self) -> None:
        if not self._is_complete():
            if (
                QMessageBox.question(
                    self,
                    "Close Draft",
                    "Draft not complete. Close anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        self.accept()

    def _commit_to_rosters(self) -> None:
        try:
            from services.draft_assignment import commit_draft_results
        except Exception as exc:
            QMessageBox.warning(self, "Commit Failed", str(exc))
            return

        summary: dict[str, object] = {}
        failures: list[str] = []
        compliance: list[str] = []
        try:
            summary = commit_draft_results(self.year, season_date=getattr(self, "draft_date", None))
            failures = list(summary.get("failures") or [])
            compliance = list(summary.get("compliance_issues") or [])
            self.last_assignment_error = None
        except DraftRosterError as exc:
            summary = dict(exc.summary or {})
            summary.setdefault("players_added", 0)
            summary.setdefault("roster_assigned", 0)
            failures = list(summary.get("failures") or [])
            compliance = list(summary.get("compliance_issues") or [])
            if not compliance and not failures and exc.failures:
                # Older payloads may only populate ``exc.failures`` for compliance details.
                compliance = list(exc.failures)
            summary["failures"] = failures
            summary["compliance_issues"] = compliance
            self.last_assignment_error = exc
        except Exception as exc:
            QMessageBox.warning(self, "Commit Failed", str(exc))
            return

        progress_error: str | None = None
        if not failures:
            try:
                mark_draft_completed(int(self.year))
            except ProgressUpdateError as exc:
                progress_error = str(exc)
                failures.append(progress_error)
                summary["failures"] = failures

            if not progress_error:
                try:
                    from playbalance.season_manager import SeasonManager, SeasonPhase

                    mgr = SeasonManager()
                    mgr.phase = SeasonPhase.REGULAR_SEASON
                    mgr.save()
                except Exception:
                    pass

        all_issues = [*failures, *[msg for msg in compliance if msg not in failures]]
        if progress_error and progress_error not in all_issues:
            all_issues.append(progress_error)

        self.assignment_summary = summary
        self.assignment_failures = all_issues

        try:
            log_news_event(
                f"Amateur Draft {self.year} committed: "
                f"{int(summary.get('players_added', 0))} players added; "
                f"{int(summary.get('roster_assigned', 0))} roster assignments",
            )
        except Exception:
            pass
        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "notes_label"):
                parent.notes_label.setText(
                    f"Draft {self.year} committed - players added: "
                    f"{int(summary.get('players_added', 0))}, roster assignments: "
                    f"{int(summary.get('roster_assigned', 0))}",
                )
        except Exception:
            pass

        base_msg = (
            f"Players added: {int(summary.get('players_added', 0))}\n"
            f"Roster assignments: {int(summary.get('roster_assigned', 0))}"
        )
        if all_issues:
            detail_lines = "\n".join(all_issues)
            try:
                msg = QMessageBox(self)
                icon = None
                icon_enum = getattr(QMessageBox, "Icon", None)
                if icon_enum is not None:
                    icon = getattr(icon_enum, "Warning", None)
                else:
                    icon = getattr(QMessageBox, "Warning", None)
                if icon:
                    try:
                        msg.setIcon(icon)
                    except Exception:
                        pass
                msg.setWindowTitle("Draft Assignments")
                msg.setText(base_msg)
                msg.setInformativeText(
                    "Resolve roster compliance before resuming the season."
                )
                msg.setDetailedText(detail_lines)
                try:
                    interaction = getattr(Qt, "TextInteractionFlag", None)
                    if interaction and hasattr(interaction, "TextSelectableByMouse"):
                        msg.setTextInteractionFlags(interaction.TextSelectableByMouse)
                except Exception:
                    pass
                msg.exec()
            except Exception:
                QMessageBox.warning(
                    self,
                    "Draft Assignments",
                    base_msg
                    + "\n\n"
                    + detail_lines
                    + "\nResolve roster compliance before resuming the season.",
                )
        else:
            QMessageBox.information(
                self,
                "Draft Assignments",
                base_msg,
            )

    # Board and preview helpers
    def _rebuild_board(self) -> None:
        # Show last 10 picks
        picks = list(self.state.get("selected", []))
        tail = picks[-10:]
        self.board.setRowCount(len(tail))
        for i, sel in enumerate(tail):
            pick_no = sel.get("overall_pick", 0)
            team = self._order_names.get(sel.get("team_id", ""), sel.get("team_id", ""))
            # Replace player ID with POS and Name where possible
            pid = str(sel.get("player_id", ""))
            pr = None
            try:
                pr = getattr(self, "_pool_index", {}).get(pid)
            except Exception:
                pr = None
            if pr:
                pos = str(pr.get("primary_position", "")) or "?"
                pname = f"{pr.get('first_name','')} {pr.get('last_name','')}".strip()
                player = f"{pos} {pname}".strip()
                age = self._age_from_birthdate(str(pr.get("birthdate", "")))
                display_ovr = self._overall_display_value(pr)
            else:
                player = pid
                age = ""
                display_ovr = None
            self.board.setItem(i, 0, QTableWidgetItem(str(pick_no)))
            self.board.setItem(i, 1, QTableWidgetItem(team))
            self.board.setItem(i, 2, QTableWidgetItem(player))
            self.board.setItem(i, 3, QTableWidgetItem(age))
            self._set_ovr_cell(self.board, i, 4, display_ovr)
        self.board.resizeColumnsToContents()

    def _update_preview_from_selection(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            for key, v in self._pv_values.items():
                if key == "ovr":
                    v.setPixmap(QPixmap())
                    v.setText("")
                else:
                    v.setText("")
            return
        pid = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
        name = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        age = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
        pos = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
        bt = self.table.item(row, 5).text() if self.table.item(row, 5) else ""
        hit = self.table.item(row, 6).text() if self.table.item(row, 6) else ""
        df = self.table.item(row, 7).text() if self.table.item(row, 7) else ""
        pit = self.table.item(row, 8).text() if self.table.item(row, 8) else ""
        pr = None
        if pid:
            try:
                pr = getattr(self, "_pool_index", {}).get(pid)
            except Exception:
                pr = None
        self._pv_values["id"].setText(pid)
        self._pv_values["name"].setText(name)
        self._pv_values["age"].setText(age)
        self._pv_values["pos"].setText(pos)
        self._set_preview_ovr(self._overall_display_value(pr) if pr else None)
        self._pv_values["bt"].setText(bt)
        self._pv_values["hit"].setText(hit)
        self._pv_values["def"].setText(df)
        self._pv_values["pit"].setText(pit)

    def _open_profile_from_selection(self, *_args) -> None:
        try:
            from ui.player_profile_dialog import PlayerProfileDialog
            from models.player import Player as _Player
            from models.pitcher import Pitcher as _Pitcher
        except Exception:
            return
        row = self.table.currentRow()
        if row < 0:
            return
        pid = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
        if not pid:
            return
        # Find prospect dict by id
        pmap = {p.get("player_id"): p for p in self.pool}
        pr = pmap.get(pid)
        if not pr:
            return
        is_pitcher = bool(pr.get("is_pitcher")) or str(pr.get("primary_position","")) == "P"
        base_kwargs = dict(
            player_id=pr.get("player_id",""),
            first_name=pr.get("first_name","Prospect"),
            last_name=pr.get("last_name",""),
            birthdate=pr.get("birthdate","2006-01-01"),
            height=72,
            weight=195,
            bats=pr.get("bats","R"),
            primary_position=pr.get("primary_position","P" if is_pitcher else "SS"),
            other_positions=pr.get("other_positions",[]) or [],
            gf=50,
        )
        if is_pitcher:
            player = _Pitcher(
                **base_kwargs,
                endurance=int(pr.get("endurance",0) or 0),
                control=int(pr.get("control",0) or 0),
                movement=int(pr.get("movement",0) or 0),
                hold_runner=int(pr.get("hold_runner",0) or 0),
                arm=int(pr.get("arm",0) or 0),
                fa=int(pr.get("fa",0) or 0),
            )
        else:
            player = _Player(
                **base_kwargs,
                ch=int(pr.get("ch",0) or 0),
                ph=int(pr.get("ph",0) or 0),
                sp=int(pr.get("sp",0) or 0),
                pl=50,
                vl=50,
                sc=50,
                fa=int(pr.get("fa",0) or 0),
                arm=int(pr.get("arm",0) or 0),
            )
        try:
            PlayerProfileDialog(player, self).exec()
        except Exception:
            pass


__all__ = ["DraftConsole"]
