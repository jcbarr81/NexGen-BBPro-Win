from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
import time
import os

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QMessageBox,
        QListWidget,
        QListWidgetItem,
        QProgressBar,
    )
    from PyQt6.QtGui import QColor
    try:  # Some headless stubs omit QCheckBox; fall back to QPushButton-like behavior
        from PyQt6.QtWidgets import QCheckBox as _QtCheckBox
    except Exception:  # pragma: no cover - optional widget
        class QCheckBox(QPushButton):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                try:
                    self.setCheckable(True)
                except Exception:
                    pass

            def setChecked(self, value):
                try:
                    super().setChecked(value)
                except Exception:
                    pass

            def isChecked(self):
                try:
                    return super().isChecked()
                except Exception:
                    return False
    else:
        QCheckBox = _QtCheckBox
except ImportError:  # pragma: no cover - test stubs
    class DummySignal:
        def __init__(self, parent=None):
            self._slot = None
            self._parent = parent

        def connect(self, slot):
            self._slot = slot

        def emit(self, *args, **kwargs):
            if self._slot and (
                self._parent is None
                or not hasattr(self._parent, "isEnabled")
                or self._parent.isEnabled()
            ):
                self._slot(*args, **kwargs)

    class _WidgetDummy:
        def __init__(self, *args, **kwargs) -> None:
            self.clicked = DummySignal(self)
            self._enabled = True

        def __getattr__(self, name):
            def _noop(*_args, **_kwargs):
                return None

            return _noop

        def setEnabled(self, value):
            self._enabled = bool(value)

        def isEnabled(self):
            return self._enabled

    class _ListWidgetDummy(_WidgetDummy):
        class SelectionMode:
            NoSelection = 0

    QDialog = QLabel = QPushButton = QVBoxLayout = QMessageBox = _WidgetDummy
    QListWidget = _ListWidgetDummy
    QListWidgetItem = _WidgetDummy
    QProgressBar = _WidgetDummy
    class QCheckBox(_WidgetDummy):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._checked = False
            self.toggled = DummySignal(self) if 'DummySignal' in globals() else None

        def setChecked(self, value):
            self._checked = bool(value)

        def isChecked(self):
            return self._checked

    class QColor:  # type: ignore[too-many-ancestors]
        def __init__(self, *args, **kwargs) -> None:
            pass

try:
    from PyQt6.QtCore import pyqtSignal, pyqtSlot, QTimer, QThread, QMetaObject, Qt, Q_ARG
except Exception:  # pragma: no cover - fallback for headless tests
    class _DummySignal:
        def __init__(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

    def pyqtSignal(*args, **kwargs):  # type: ignore
        return _DummySignal()

    def pyqtSlot(*args, **kwargs):  # type: ignore
        def decorator(fn):
            return fn

        return decorator
    class QTimer:  # type: ignore
        @staticmethod
        def singleShot(ms: int, callback: Callable[[], None]) -> None:
            callback()
    QThread = None  # type: ignore
    class QMetaObject:  # type: ignore
        @staticmethod
        def invokeMethod(obj, method, connection=None, *args):
            fn = getattr(obj, method, None)
            if callable(fn):
                try:
                    fn(*args)
                except Exception:
                    pass

    class Qt:  # type: ignore
        class ConnectionType:
            QueuedConnection = None

    def Q_ARG(_type, value):  # type: ignore
        return value

try:  # pragma: no cover - fallback for environments without PyQt6
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - simple stub for tests
    class QApplication:  # type: ignore
        @staticmethod
        def processEvents() -> None:  # pragma: no cover - no-op
            pass
from datetime import date
from threading import Event
import csv
import json
from pathlib import Path

import playbalance.season_manager as season_manager
from playbalance.aging_model import age_and_retire
from playbalance.season_manager import SeasonManager, SeasonPhase
from playbalance.training_camp import run_training_camp
from playbalance.player_development import TrainingWeights
from playbalance.league_creator import MAX_LEAGUE_TEAMS
from services.free_agency import (
    list_unsigned_players,
    list_unsigned_players_from_files,
    run_cpu_free_agency_market,
)
from services.dl_automation import DLAutomationSummary, process_disabled_lists
from services.finance_budget_effects import training_camp_multiplier_by_player
from services.finance_budget_effects import development_multiplier_by_player
from services.season_progress_flags import (
    ProgressUpdateError,
    mark_draft_completed,
)
from services.training_settings import load_training_settings
from playbalance.season_simulator import SeasonSimulator
from ui.draft_console import DraftConsole
from playbalance.schedule_generator import save_schedule
from services.league_presets import (
    generate_schedule_from_template,
    get_schedule_template,
    record_league_metadata,
)
from services.hall_of_fame import update_hall_of_fame
from services.record_notifications import consume_record_notifications
from services.timeline_feed import build_timeline_feed
from utils.exceptions import DraftRosterError
from playbalance.simulation import save_boxscore_html
from utils.news_logger import log_news_event
from utils.team_loader import load_teams
from utils.standings_utils import default_record, update_record
from services.standings_repository import load_standings, save_standings
from playbalance.config import load_config as load_pb_config
from playbalance.benchmarks import load_benchmarks as load_pb_benchmarks
from playbalance.orchestrator import (
    simulate_day as pb_simulate_day,
    simulate_week as pb_simulate_week,
    simulate_month as pb_simulate_month,
)
from playbalance.game_runner import simulate_game_scores
from utils.team_loader import load_teams
from utils.roster_loader import load_roster, save_roster
from utils.lineup_loader import load_lineup
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.pitcher_role import get_role
from utils.sim_date import get_current_sim_date
from ui.sim_date_bus import notify_sim_date_changed
from ui.training_focus_dialog import TrainingFocusDialog
from ui.league_preset_dialogs import select_schedule_template


from utils.path_utils import ActivePath, get_data_dir

DATA_DIR = ActivePath(get_data_dir)
TEAMS_FILE = ActivePath(lambda: get_data_dir() / "teams.csv")
SCHEDULE_FILE = ActivePath(lambda: get_data_dir() / "schedule.csv")
PROGRESS_FILE = ActivePath(lambda: get_data_dir() / "season_progress.json")

BUTTON_STYLE = """
QPushButton {
    background-color: #5c3b18;
    color: #f6e8d3;
    border: 2px solid #d4a76a;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:pressed {
    background-color: #4a2f12;
}
QPushButton:disabled {
    background-color: #2f2315;
    color: #a68d6b;
    border: 2px solid #523d24;
}
"""


class SeasonProgressWindow(QDialog):
    """Dialog displaying the current season phase and progress notes."""

    # Emitted whenever season progress persists a new date, or when closing
    # the window. Carries the latest current sim date string.
    _simStatusRequested = pyqtSignal(object)
    progressUpdated = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        schedule: list[dict[str, str]] | None = None,
        simulate_game=None,
        *,
        run_async: Optional[Callable[[Callable[[], Any]], Any]] = None,
        show_toast: Optional[Callable[[str, str], None]] = None,
        register_cleanup: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        super().__init__(parent)
        try:
            self.setWindowTitle("Season Progress")
            self.setMinimumSize(420, 820)
            self.resize(420, 820)
        except Exception:  # pragma: no cover - harmless in headless tests
            pass

        self._run_async = run_async
        self._show_toast = show_toast
        self._register_cleanup = register_cleanup
        self._active_future = None
        self._executor: ThreadPoolExecutor | None = None
        if self._run_async is None:
            executor = ThreadPoolExecutor(max_workers=1)
            self._executor = executor
            self._run_async = executor.submit
            if self._register_cleanup is not None:
                try:
                    self._register_cleanup(lambda ex=executor: ex.shutdown(wait=False))
                except Exception:
                    pass

        self.manager = SeasonManager()
        self._simulate_game = simulate_game
        self._engine_choice = "physics"
        if schedule is None and SCHEDULE_FILE.exists():
            with SCHEDULE_FILE.open(newline="") as fh:
                reader = csv.DictReader(fh)
                schedule = list(reader)
        # Persist league data after each game so that standings, schedules and
        # statistics remain current even if a simulation run is interrupted.
        # Compute Draft Day from schedule (third Tuesday in July)
        draft_date = self._compute_draft_date((schedule or [{}])[0].get("date") if schedule else None)
        self._draft_date = draft_date
        self._season_year_hint: Optional[int] = None
        sim_fn = self._resolve_simulate_game()
        self.simulator = SeasonSimulator(
            schedule or [],
            sim_fn,
            on_draft_day=self._on_draft_day,
            draft_date=draft_date,
            after_game=self._record_game,
        )
        self._season_year_hint = self._infer_schedule_year()
        self._cancel_requested = False
        # Track season standings with detailed splits so that schedule and
        # standings windows can display rich statistics.
        self._standings: dict[str, dict[str, object]] = load_standings(base_path=DATA_DIR)
        teams = load_teams()
        self._team_divisions = {team.team_id: team.division for team in teams}
        self._preseason_done = {
            "free_agency": False,
            "training_camp": False,
            "schedule": False,
        }
        self._playoffs_done = False
        self._loaded_playoffs_done = False
        self._auto_activate_dl = True
        self._load_progress()

        try:
            self._pb_cfg = load_pb_config()
            self._pb_benchmarks = load_pb_benchmarks()
        except Exception:  # pragma: no cover - configuration optional
            self._pb_cfg = None
            self._pb_benchmarks = {}

        # Validate schedule team IDs against known teams; offer to regenerate
        try:
            self._ensure_valid_schedule_teams()
        except Exception:
            # Best-effort validation; proceed if any issues in headless envs
            pass

        layout = QVBoxLayout(self)

        self.phase_label = QLabel()
        layout.addWidget(self.phase_label)

        # Always-visible indicator of the current simulation date
        self.date_label = QLabel()
        layout.addWidget(self.date_label)

        self.notes_label = QLabel()
        self.notes_label.setWordWrap(True)
        layout.addWidget(self.notes_label)

        self.timeline_label = QLabel("Season Timeline")
        self.timeline_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.timeline_label)

        self.timeline = QListWidget()
        self.timeline.setMouseTracking(True)
        self.timeline.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.timeline)

        self.feed_label = QLabel("Timeline Feed")
        self.feed_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.feed_label)

        self.feed_list = QListWidget()
        self.feed_list.setMouseTracking(True)
        self.feed_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        try:
            self.feed_list.setWordWrap(True)
            self.feed_list.setMaximumHeight(220)
        except Exception:
            pass
        layout.addWidget(self.feed_list)

        # Actions available during the preseason
        self.free_agency_button = QPushButton("List Unsigned Players")
        self.free_agency_button.clicked.connect(self._show_free_agents)
        layout.addWidget(self.free_agency_button)

        self.training_camp_button = QPushButton("Run Training Camp")
        self.training_camp_button.clicked.connect(self._run_training_camp)
        layout.addWidget(self.training_camp_button)

        self.training_focus_button = QPushButton("Training Focus...")
        self.training_focus_button.clicked.connect(self._open_training_focus_dialog)
        layout.addWidget(self.training_focus_button)

        self.schedule_template_label = QLabel()
        self.schedule_template_label.setWordWrap(True)
        layout.addWidget(self.schedule_template_label)

        self.generate_schedule_button = QPushButton("Generate Schedule")
        self.generate_schedule_button.clicked.connect(self._generate_schedule)
        layout.addWidget(self.generate_schedule_button)

        # Regular season controls
        self.remaining_label = QLabel()
        layout.addWidget(self.remaining_label)
        self.simulation_status_label = QLabel()
        self.simulation_status_label.setWordWrap(True)
        layout.addWidget(self.simulation_status_label)
        self.sim_progress = QProgressBar()
        try:
            self.sim_progress.setRange(0, 0)
            self.sim_progress.setTextVisible(True)
            self.sim_progress.setFormat("Simulating day...")
            self.sim_progress.setVisible(False)
        except Exception:
            pass
        layout.addWidget(self.sim_progress)

        self.auto_activate_checkbox = QCheckBox("Auto-activate DL players when eligible")
        try:
            self.auto_activate_checkbox.setChecked(self._auto_activate_dl)
            self.auto_activate_checkbox.toggled.connect(self._on_auto_activate_dl_toggled)
        except Exception:
            pass
        self._update_auto_activate_tip()
        layout.addWidget(self.auto_activate_checkbox)

        self.engine_toggle = None

        self.simulate_day_button = QPushButton("Simulate Day")
        self.simulate_day_button.clicked.connect(self._simulate_day)
        layout.addWidget(self.simulate_day_button)

        self.simulate_round_button = QPushButton("Simulate Round")
        self.simulate_round_button.clicked.connect(self._simulate_playoff_round)
        layout.addWidget(self.simulate_round_button)

        self.simulate_week_button = QPushButton("Simulate Week")
        self.simulate_week_button.clicked.connect(self._simulate_week)
        layout.addWidget(self.simulate_week_button)

        self.simulate_month_button = QPushButton("Simulate Month")
        self.simulate_month_button.clicked.connect(self._simulate_month)
        layout.addWidget(self.simulate_month_button)

        self.simulate_to_draft_button = QPushButton("Simulate to Draft Day")
        self.simulate_to_draft_button.clicked.connect(self._simulate_to_draft)
        layout.addWidget(self.simulate_to_draft_button)

        self.simulate_to_playoffs_button = QPushButton("Simulate to Playoffs")
        self.simulate_to_playoffs_button.clicked.connect(self._simulate_to_playoffs)
        layout.addWidget(self.simulate_to_playoffs_button)

        # Maintenance tool: repair/auto-fill lineups
        self.repair_lineups_button = QPushButton("Repair Lineups")
        self.repair_lineups_button.clicked.connect(self._repair_lineups)
        layout.addWidget(self.repair_lineups_button)

        self.next_button = QPushButton("Next Phase")
        self.next_button.clicked.connect(self._next_phase)
        layout.addWidget(self.next_button)

        self.cancel_sim_button = QPushButton("Cancel Simulation")
        self.cancel_sim_button.clicked.connect(self._request_cancel_simulation)
        layout.addWidget(self.cancel_sim_button)

        self.done_button = QPushButton("Done")
        self.done_button.clicked.connect(self.close)
        layout.addWidget(self.done_button)

        self._apply_button_styles()
        self._set_button_state(
            self.cancel_sim_button,
            False,
            "No simulation is currently running.",
        )
        self._set_button_state(self.done_button, True, "")

        self._sim_status_text: Optional[str] = None
        try:
            self._simStatusRequested.connect(self._apply_simulation_status)
        except Exception:
            # Fallback stubs do not expose Qt signal semantics
            pass
        self._show_calendar_countdown = False
        self._playoffs_override_done = False
        self._draft_blocked = False
        self._set_simulation_status(None)
        self._draft_pause_requested = False
        self._allow_done_early = False
        self._future_pollers: list = []
        self._update_ui()

    # ------------------------------------------------------------------
    # Draft helpers
    def _compute_draft_date(self, first_date: str | None) -> str | None:
        try:
            if not first_date:
                return None
            year = int(str(first_date).split("-")[0])
            import datetime as _dt
            d = _dt.date(year, 7, 1)
            # Tuesday is 1
            while d.weekday() != 1:
                d += _dt.timedelta(days=1)
            d += _dt.timedelta(days=14)
            return d.isoformat()
        except Exception:
            return None

    def _days_until_draft(self) -> int:
        """Return the number of remaining schedule days until Draft Day."""
        draft_date = getattr(self, "_draft_date", None)
        if not draft_date:
            return 0

        try:
            draft_year = int(str(draft_date).split("-")[0])
        except Exception:
            draft_year = None

        # If the draft was already completed for this year, no countdown.
        if draft_year is not None:
            try:
                if PROGRESS_FILE.exists():
                    progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8") or "{}")
                    completed = set(progress.get("draft_completed_years", []))
                    if draft_year in completed:
                        return 0
            except Exception:
                pass

        dates = getattr(self.simulator, "dates", None)
        idx = getattr(self.simulator, "_index", 0)
        if dates:
            try:
                remaining = 0
                for offset, value in enumerate(dates[idx:], start=0):
                    if str(value) >= str(draft_date):
                        remaining = offset
                        break
                else:
                    remaining = 0
                return max(0, remaining)
            except Exception:
                pass

        # Calendar fallback if schedule context is unavailable.
        try:
            from datetime import date as _date

            dy, dm, dd = map(int, str(draft_date).split("-"))
            draft_dt = _date(dy, dm, dd)

            cur_str: str | None = None
            if dates and idx < len(dates):
                cur_str = str(dates[idx])
            if not cur_str:
                cur_str = get_current_sim_date()
            if cur_str:
                cy, cm, cd = map(int, str(cur_str).split("-"))
                current_dt = _date(cy, cm, cd)
                delta = (draft_dt - current_dt).days
                if delta > 0:
                    return delta
        except Exception:
            pass
        return 0

    def _remaining_regular_days(self) -> int:
        """Count remaining regular-season days that include scheduled games."""
        simulator = getattr(self, "simulator", None)
        if simulator is None:
            return 0
        try:
            dates = list(getattr(simulator, "dates", []))
            schedule = list(getattr(simulator, "schedule", []))
            index = int(getattr(simulator, "_index", 0))
        except Exception:
            try:
                return int(simulator.remaining_schedule_days())
            except Exception:
                return 0
        draft_date = getattr(simulator, "draft_date", None)
        draft_str = str(draft_date) if draft_date else None
        schedule_dates = {
            str(game.get("date"))
            for game in schedule
            if game.get("date") is not None
        }
        remaining = 0
        for date_value in dates[index:]:
            date_str = str(date_value)
            if draft_str and date_str == draft_str and date_str not in schedule_dates:
                continue
            remaining += 1
        return remaining

    def _pending_calendar_days(self) -> int:
        """Return remaining scheduled dates including off days such as the draft."""
        simulator = getattr(self, "simulator", None)
        if simulator is None:
            return 0
        try:
            dates = list(getattr(simulator, "dates", []))
            index = int(getattr(simulator, "_index", 0))
        except Exception:
            return 0
        pending = len(dates) - index
        return pending if pending > 0 else 0

    def _apply_button_styles(self) -> None:
        buttons = [
            getattr(self, "free_agency_button", None),
            getattr(self, "training_camp_button", None),
            getattr(self, "generate_schedule_button", None),
            getattr(self, "simulate_day_button", None),
            getattr(self, "simulate_round_button", None),
            getattr(self, "simulate_week_button", None),
            getattr(self, "simulate_month_button", None),
            getattr(self, "simulate_to_draft_button", None),
            getattr(self, "simulate_to_playoffs_button", None),
            getattr(self, "repair_lineups_button", None),
            getattr(self, "next_button", None),
            getattr(self, "cancel_sim_button", None),
            getattr(self, "done_button", None),
        ]
        for btn in buttons:
            if btn is None:
                continue
            try:
                btn.setStyleSheet(BUTTON_STYLE)
            except Exception:
                pass

    def _invoke_on_gui_thread(self, fn) -> None:
        if fn is None:
            return
        if QThread is None:
            fn()
            return
        try:
            gui_thread = self.thread()
            current_thread = QThread.currentThread()
        except Exception:
            gui_thread = None
            current_thread = None
        if gui_thread is None or current_thread is None or gui_thread == current_thread:
            fn()
            return
        try:
            conn_parent = getattr(Qt, "ConnectionType", Qt)
            connection = getattr(conn_parent, "QueuedConnection", None)
            if connection is None:
                raise AttributeError
            QMetaObject.invokeMethod(
                self,
                "_execute_callable",
                connection,
                Q_ARG(object, fn),
            )
        except Exception:
            QTimer.singleShot(0, fn)

    @pyqtSlot(object)
    def _execute_callable(self, fn) -> None:  # pragma: no cover - GUI thread helper
        try:
            if callable(fn):
                fn()
        except Exception:
            pass

    def _set_button_state(
        self,
        button,
        enabled: bool,
        tooltip_disabled: str = "",
    ) -> None:
        if button is None:
            return
        tooltip_text = "" if enabled else (tooltip_disabled or "")

        def apply() -> None:
            try:
                button.setEnabled(enabled)
                button.setToolTip(tooltip_text)
            except Exception:
                pass

        self._invoke_on_gui_thread(apply)

    def _poll_future(
        self,
        future,
        handler: Callable[[Any], None],
        *,
        interval_ms: int = 250,
        timeout_ms: int = 120000,
    ) -> None:
        if future is None or QThread is None:
            return
        try:
            timer = QTimer(self)
        except Exception:
            return
        start = time.monotonic()

        def stop_timer() -> None:
            try:
                timer.stop()
            except Exception:
                pass
            try:
                self._future_pollers.remove(timer)
            except ValueError:
                pass

        def tick() -> None:
            try:
                done = future.done()
            except Exception:
                done = False
            if done:
                stop_timer()
                try:
                    handler(future)
                except Exception:
                    pass
                return
            if (time.monotonic() - start) * 1000 >= timeout_ms:
                stop_timer()
                try:
                    handler(future)
                except Exception:
                    pass

        try:
            timer.timeout.connect(tick)
            timer.start(interval_ms)
            self._future_pollers.append(timer)
        except Exception:
            pass

    def _resolve_playoff_bracket_path(self) -> Path | None:
        try:
            candidates = list(DATA_DIR.glob("playoffs_*.json"))
        except Exception:
            candidates = []
        if candidates:
            try:
                return max(candidates, key=lambda p: p.stat().st_mtime)
            except Exception:
                return candidates[-1]
        fallback = DATA_DIR / "playoffs.json"
        return fallback if fallback.exists() else None

    def _watch_playoff_bracket_update(
        self,
        handler: Callable[[], None],
        *,
        interval_ms: int = 300,
        timeout_ms: int = 30000,
    ) -> None:
        if QThread is None:
            return
        path = self._resolve_playoff_bracket_path()
        start_time = time.time()
        start_mtime = 0.0
        if path is not None:
            try:
                start_mtime = path.stat().st_mtime
            except Exception:
                start_mtime = 0.0
        try:
            timer = QTimer(self)
        except Exception:
            return

        def stop_timer() -> None:
            try:
                timer.stop()
            except Exception:
                pass
            try:
                self._future_pollers.remove(timer)
            except ValueError:
                pass

        def tick() -> None:
            if self._active_future is None:
                stop_timer()
                return
            if (time.time() - start_time) * 1000 >= timeout_ms:
                stop_timer()
                handler()
                return
            current_path = path or self._resolve_playoff_bracket_path()
            if current_path is None:
                return
            try:
                current_mtime = current_path.stat().st_mtime
            except Exception:
                return
            if current_mtime > start_mtime:
                stop_timer()
                handler()

        try:
            timer.timeout.connect(tick)
            timer.start(interval_ms)
            self._future_pollers.append(timer)
        except Exception:
            pass

    def _force_playoff_finish_if_stuck(self, future, *, timeout_ms: int = 15000) -> None:
        if future is None or QThread is None:
            return
        try:
            def check() -> None:
                if self._active_future is not future:
                    return
                try:
                    done = future.done()
                except Exception:
                    done = False
                if done:
                    return
                try:
                    from playbalance.playoffs import load_bracket as _load_bracket
                except Exception:
                    _load_bracket = None
                bracket = _load_bracket() if _load_bracket is not None else None
                result = {
                    "status": "success",
                    "message": "Playoff simulation complete.",
                    "playoffs_done": bool(getattr(bracket, "champion", None)) if bracket else False,
                    "bracket": bracket,
                }
                self._active_future = None
                self._set_sim_progress_visible(False)
                self._handle_playoff_step_result(result)
                self._set_playoff_controls_enabled(not self._playoffs_done)

            QTimer.singleShot(timeout_ms, check)
        except Exception:
            pass

    def _normalize_engine_choice(self, value: str | None) -> str:
        token = str(value or "").strip().lower()
        if token in {"legacy", "old", "pbini"}:
            return "legacy"
        if token in {"physics", "phys", "new", "next"}:
            return "physics"
        return "physics"

    def _engine_simulate_game(
        self,
        home_id: str,
        away_id: str,
        *,
        seed: int | None = None,
        game_date: str | None = None,
    ) -> tuple[int, int, str, dict[str, object]]:
        return simulate_game_scores(
            home_id,
            away_id,
            seed=seed,
            game_date=game_date,
            engine=self._engine_choice,
        )

    def _resolve_simulate_game(self):
        return self._simulate_game or self._engine_simulate_game

    def _on_engine_toggle(self, checked: bool) -> None:
        return

    def _season_context_years(self) -> tuple[Optional[int], Optional[int]]:
        """Return (current league year, last archived year) from season context."""
        try:
            from playbalance.season_context import SeasonContext as _SeasonContext

            ctx = _SeasonContext.load()
            current = ctx.current if isinstance(ctx.current, dict) else {}
            raw_current = current.get("league_year")
            current_year = int(raw_current) if raw_current is not None else None
            last_year = None
            seasons = getattr(ctx, "seasons", None) or []
            if seasons:
                try:
                    raw_last = seasons[-1].get("league_year")
                    last_year = int(raw_last) if raw_last is not None else None
                except Exception:
                    last_year = None
            return current_year, last_year
        except Exception:
            return None, None

    def _resolve_current_league_year(self) -> Optional[int]:
        """Return the best-known league year for schedule generation."""
        current_year, _ = self._season_context_years()
        if current_year is not None:
            return current_year
        try:
            return self._season_year_hint or self._infer_schedule_year()
        except Exception:
            return None

    def _resolve_next_league_year(self) -> int:
        """Return the upcoming season year when leaving the offseason."""
        current_year, last_year = self._season_context_years()
        if current_year is not None:
            if last_year is not None and current_year <= last_year:
                return last_year + 1
            if last_year is None:
                return current_year + 1
            return current_year
        try:
            base_year = self._season_year_hint or self._infer_schedule_year()
        except Exception:
            base_year = None
        if base_year is None:
            base_year = date.today().year
        return base_year + 1

    def _apply_offseason_aging(
        self,
        target_year: Optional[int],
        players: Optional[Dict[str, object]] = None,
    ) -> int:
        """Age players, retire older players, and persist updated rosters."""
        prev_sim_year = os.environ.get("PB_SIM_YEAR")
        prev_sim_date = os.environ.get("PB_SIM_DATE")
        override_env = False
        if target_year:
            os.environ["PB_SIM_YEAR"] = str(target_year)
            os.environ.pop("PB_SIM_DATE", None)
            override_env = True

        players_path = DATA_DIR / "players.csv"
        retired_ids: set[str] = set()
        try:
            if isinstance(players, dict) and players:
                local_development = self._resolve_development_intensity(players.keys())
                retired_local = age_and_retire(
                    players,
                    development_multiplier_by_player=local_development,
                )
                retired_ids.update(p.player_id for p in retired_local)
        except Exception:
            pass
        try:
            loaded = load_players_from_csv(players_path)
            csv_players = {p.player_id: p for p in loaded}
            csv_development = self._resolve_development_intensity(csv_players.keys())
            retired = age_and_retire(
                csv_players,
                development_multiplier_by_player=csv_development,
            )
            retired_ids.update(p.player_id for p in retired)

            if retired_ids:
                roster_dir = DATA_DIR / "rosters"
                try:
                    teams = load_teams(TEAMS_FILE)
                except Exception:
                    teams = []
                for team in teams:
                    team_id = getattr(team, "team_id", None) or getattr(team, "abbreviation", None)
                    if not team_id:
                        continue
                    try:
                        roster = load_roster(team_id, roster_dir=roster_dir)
                    except Exception:
                        continue
                    roster.act = [pid for pid in roster.act if pid not in retired_ids]
                    roster.aaa = [pid for pid in roster.aaa if pid not in retired_ids]
                    roster.low = [pid for pid in roster.low if pid not in retired_ids]
                    roster.dl = [pid for pid in roster.dl if pid not in retired_ids]
                    roster.ir = [pid for pid in roster.ir if pid not in retired_ids]
                    roster.dl_tiers = {
                        pid: tier
                        for pid, tier in (roster.dl_tiers or {}).items()
                        if pid not in retired_ids
                    }
                    try:
                        save_roster(team_id, roster)
                    except Exception:
                        pass

            try:
                save_players_to_csv(csv_players.values(), players_path)
            except Exception:
                return len(retired_ids)
            try:
                load_players_from_csv.cache_clear()
            except Exception:
                pass
            try:
                load_roster.cache_clear()
            except Exception:
                pass
        finally:
            if override_env:
                if prev_sim_year is None:
                    os.environ.pop("PB_SIM_YEAR", None)
                else:
                    os.environ["PB_SIM_YEAR"] = prev_sim_year
                if prev_sim_date is None:
                    os.environ.pop("PB_SIM_DATE", None)
                else:
                    os.environ["PB_SIM_DATE"] = prev_sim_date

        return len(retired_ids)

    def _infer_schedule_year(self) -> Optional[int]:
        """Best-effort inference of the active season year from schedule data."""

        simulator = getattr(self, "simulator", None)
        if simulator is None:
            return None
        try:
            dates = list(getattr(simulator, "dates", []) or [])
        except Exception:
            dates = []
        for value in dates:
            if not value:
                continue
            try:
                return int(str(value).split("-")[0])
            except Exception:
                continue
        try:
            schedule = list(getattr(simulator, "schedule", []) or [])
        except Exception:
            schedule = []
        for game in schedule:
            try:
                date_value = game.get("date")
            except Exception:
                date_value = None
            if not date_value:
                continue
            try:
                return int(str(date_value).split("-")[0])
            except Exception:
                continue
        return None

    def _sync_playoffs_flag_from_disk(self) -> None:
        """Refresh the in-memory playoffs flag if the progress file changed."""

        try:
            if not PROGRESS_FILE.exists():
                return
            payload = json.loads(PROGRESS_FILE.read_text(encoding="utf-8") or "{}")
        except Exception:
            return
        flag = bool(payload.get("playoffs_done"))
        if flag != self._playoffs_done or flag != self._loaded_playoffs_done:
            self._playoffs_done = flag
            self._loaded_playoffs_done = flag

    def _sync_phase_with_playoffs(self, bracket: object | None = None) -> None:
        """If a playoff bracket has started, ensure the season phase matches."""
        if self.manager.phase in {SeasonPhase.PLAYOFFS, SeasonPhase.OFFSEASON}:
            return
        br = bracket
        if br is None:
            try:
                from playbalance.playoffs import load_bracket as _load_bracket

                br = _load_bracket()
            except Exception:
                br = None
        if br is None:
            return
        try:
            bracket_year = int(getattr(br, "year", 0) or 0)
        except Exception:
            bracket_year = 0
        current_year = self._resolve_current_league_year()
        if bracket_year:
            if current_year is None or bracket_year != current_year:
                return
            return

        progressed = False
        try:
            if getattr(br, "champion", None):
                progressed = True
            else:
                for rnd in list(getattr(br, "rounds", []) or []):
                    for matchup in list(getattr(rnd, "matchups", []) or []):
                        if getattr(matchup, "winner", None):
                            progressed = True
                            break
                        for game in list(getattr(matchup, "games", []) or []):
                            if getattr(game, "result", None):
                                progressed = True
                                break
                        if progressed:
                            break
                    if progressed:
                        break
        except Exception:
            progressed = False
        if not progressed:
            return
        try:
            self.manager.phase = SeasonPhase.PLAYOFFS
            self.manager.save()
        except Exception:
            pass

    def _draft_completed_for_current_year(self) -> bool:
        """Return True when the current season's draft is recorded complete."""
        draft_date = getattr(self, "_draft_date", None)
        if not draft_date:
            return True
        try:
            draft_year = int(str(draft_date).split("-")[0])
        except Exception:
            draft_year = None

        if getattr(self.simulator, "_draft_triggered", False):
            return True

        if draft_year is None:
            return False

        try:
            if PROGRESS_FILE.exists():
                progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8") or "{}")
            else:
                progress = {}
        except Exception:
            return False
        completed = progress.get("draft_completed_years", [])
        try:
            completed_years = {int(year) for year in completed}
        except Exception:
            completed_years = set()
        if draft_year in completed_years:
            self._draft_blocked = False
            return True
        return False

    def _on_draft_day(self, date_str: str) -> None:
        """Handle Draft Day and block further simulation until committed.

        On Draft Day, enter the Amateur Draft phase and open the Draft Console.
        If the user does not commit results or any error occurs (including
        console initialization issues), raise DraftRosterError to prevent the
        season from progressing past the draft. This ensures commissioners
        cannot simulate beyond Draft Day without completing the draft.
        """
        import json as _json
        # Determine current season year from date string
        try:
            year = int(str(date_str).split("-")[0])
        except Exception:
            # If we cannot parse the date, block progression conservatively
            raise DraftRosterError(["Unable to determine season year for Draft Day."], {})

        # Skip if already completed for this year
        progress = {}
        if PROGRESS_FILE.exists():
            try:
                progress = _json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            except Exception:
                progress = {}
        completed = set(progress.get("draft_completed_years", []))
        if year in completed:
            self._draft_blocked = False
            return

        self._draft_blocked = True

        result: dict[str, object] = {}
        finished = Event()

        def run_console() -> None:
            try:
                try:
                    self.manager.phase = SeasonPhase.AMATEUR_DRAFT
                    self.manager.save()
                except Exception:
                    pass
                self._draft_pause_requested = True
                self._update_ui("Amateur Draft Day: paused for draft operations.")

                dlg = DraftConsole(date_str, self)
                dlg.exec()
                summary = dict(getattr(dlg, "assignment_summary", {}) or {})
                failures = list(summary.get("failures") or [])
                if not summary:
                    failures = [
                        "Draft results must be committed before resuming the season."
                    ]
                if failures:
                    raise DraftRosterError(failures, summary)

                try:
                    mark_draft_completed(year, progress_path=PROGRESS_FILE)
                except ProgressUpdateError as exc:
                    raise DraftRosterError([str(exc)], summary)

                completed.add(year)
                progress["draft_completed_years"] = sorted(completed)
                try:
                    self.manager.phase = SeasonPhase.REGULAR_SEASON
                    self.manager.save()
                except Exception:
                    pass
                self._draft_blocked = False
                self._update_ui("Draft committed. Returning to Regular Season.")
                result["error"] = None
            except DraftRosterError as exc:
                result["error"] = exc
            except Exception as exc:
                result["error"] = DraftRosterError([f"Draft Console error: {exc}"], {})
            finally:
                finished.set()

        self._invoke_on_gui_thread(run_console)
        finished.wait()
        error = result.get("error")
        if error:
            raise error

    # ------------------------------------------------------------------
    # UI lifecycle
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt signature
        try:
            cur = get_current_sim_date()
            self.progressUpdated.emit(cur or "")
        except Exception:
            pass
        if self._active_future is not None and hasattr(self._active_future, "cancel"):
            try:
                self._active_future.cancel()
            except Exception:
                pass
        self._set_button_state(
            self.cancel_sim_button,
            False,
            "No simulation is currently running.",
        )
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # pragma: no cover - Qt signature
        try:
            super().showEvent(event)
        except Exception:
            pass
        self._reload_manager_phase()
        self._update_ui()

    def focusInEvent(self, event) -> None:  # pragma: no cover - Qt signature
        try:
            super().focusInEvent(event)
        except Exception:
            pass
        self._reload_manager_phase()
        self._update_ui()

    def _reload_manager_phase(self) -> None:
        """Reload season phase from disk to capture external updates."""
        try:
            self.manager.load()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _update_schedule_template_label(self) -> None:
        label = "Schedule Template: MLB 162 (default)"
        template_id: Optional[str] = None
        try:
            from playbalance.season_context import SeasonContext as _SeasonContext

            ctx = _SeasonContext.load()
            metadata = ctx.current.get("metadata", {}) if isinstance(ctx.current, dict) else {}
            value = metadata.get("schedule_template_id")
            if isinstance(value, str) and value:
                template_id = value
        except Exception:
            template_id = None
        if template_id:
            template = get_schedule_template(template_id)
            if template is not None:
                label = f"Schedule Template: {template.name}"
            else:
                label = f"Schedule Template: {template_id}"
        try:
            self.schedule_template_label.setText(label)
        except Exception:
            pass

    def _update_ui(self, note: str | None = None, *, bracket: object | None = None) -> None:
        """Refresh the label and notes for the current phase.

        Parameters
        ----------
        note:
            Optional note to display instead of the default phase message.
        bracket:
            Optional in-memory playoff bracket to reuse when refreshing the
            playoffs view to avoid stale disk reads after background updates.
        """
        self._sync_playoffs_flag_from_disk()
        self._sync_phase_with_playoffs(bracket)
        phase_name = self.manager.phase.name.replace("_", " ").title()
        self.phase_label.setText(f"Current Phase: {phase_name}")
        # Update current date indicator from simulator schedule
        try:
            if self.simulator and getattr(self.simulator, "dates", None):
                if self.simulator._index < len(self.simulator.dates):
                    current_date = str(self.simulator.dates[self.simulator._index])
                elif self.simulator.dates:
                    current_date = str(self.simulator.dates[-1]) + " (complete)"
                else:
                    current_date = "N/A"
            else:
                current_date = "N/A"
        except Exception:
            current_date = "N/A"
        try:
            self.date_label.setText(f"Current Date: {current_date}")
        except Exception:
            pass
        if note is None:
            note = self.manager.handle_phase()
        self.notes_label.setText(note)

        is_preseason = self.manager.phase == SeasonPhase.PRESEASON
        is_regular = self.manager.phase == SeasonPhase.REGULAR_SEASON
        is_playoffs = self.manager.phase == SeasonPhase.PLAYOFFS
        is_draft = self.manager.phase == SeasonPhase.AMATEUR_DRAFT
        self.free_agency_button.setVisible(is_preseason)
        self.training_camp_button.setVisible(is_preseason)
        self.training_focus_button.setVisible(is_preseason)
        self.schedule_template_label.setVisible(is_preseason)
        if is_preseason:
            self._update_schedule_template_label()
        self.generate_schedule_button.setVisible(is_preseason)
        self.remaining_label.setVisible(is_regular or is_playoffs)
        self.simulate_day_button.setVisible(is_regular or is_playoffs)
        self.simulate_round_button.setVisible(is_playoffs)
        self.simulate_week_button.setVisible(is_regular)
        self.simulate_month_button.setVisible(is_regular)
        self.simulate_to_draft_button.setVisible(is_regular)
        self.simulate_to_playoffs_button.setVisible(is_regular or is_playoffs)
        self.repair_lineups_button.setVisible(is_regular)
        if self.engine_toggle is not None:
            try:
                self.engine_toggle.setVisible(is_regular)
                self._set_button_state(
                    self.engine_toggle,
                    False,
                    "Physics engine is now the default.",
                )
            except Exception:
                pass
        playoffs_bracket = bracket
        draft_locked = bool(self._draft_blocked)
        self._refresh_timeline_feed()
        if is_regular:
            self.simulate_day_button.setText("Simulate Day")
            mid_remaining = self.simulator.remaining_days()
            # Draft milestone: only if not yet completed for the season
            try:
                draft_remaining = self._days_until_draft()  # type: ignore[attr-defined]
            except AttributeError:
                draft_remaining = 0
            total_remaining = self._remaining_regular_days()
            calendar_remaining = self._pending_calendar_days()
            draft_pending = (
                calendar_remaining > 0
                and getattr(self.simulator, "draft_date", None)
                and not getattr(self.simulator, "_draft_triggered", False)
            )
            draft_done = self._draft_completed_for_current_year()
            draft_locked = draft_locked or bool(
                getattr(self.simulator, "_draft_triggered", False)
                and not draft_done
            )
            if total_remaining > 0:
                if mid_remaining > 0:
                    label_text = f"Days until Midseason: {mid_remaining}"
                elif draft_remaining > 0 and total_remaining > 1:
                    label_text = f"Days until Draft: {draft_remaining}"
                else:
                    label_text = f"Days until Season End: {total_remaining}"
            else:
                if self._show_calendar_countdown and calendar_remaining > 0:
                    label_text = f"Days until Season End: {calendar_remaining}"
                else:
                    label_text = "Regular season complete."
            self.remaining_label.setText(label_text)
            has_games = total_remaining > 0
            has_any = calendar_remaining > 0
            phase_pending = has_games or (
                self._show_calendar_countdown and calendar_remaining > 0
            )
            no_games_reason = (
                "No regular season games remain."
                if not has_games and calendar_remaining <= 0
                else "No games are scheduled before the next phase."
            )
            draft_lock_reason = "Draft Day is underway; complete the draft before continuing."
            draft_locked = bool(
                getattr(self.simulator, "_draft_triggered", False)
                and not draft_done
            )
            self._set_button_state(
                self.simulate_day_button,
                has_games and not draft_locked,
                draft_lock_reason if draft_locked else no_games_reason,
            )
            self._set_button_state(
                self.simulate_week_button,
                has_games and not draft_locked,
                draft_lock_reason if draft_locked else no_games_reason,
            )
            self._set_button_state(
                self.simulate_month_button,
                has_games and not draft_locked,
                draft_lock_reason if draft_locked else no_games_reason,
            )
            draft_available = (draft_remaining > 0 or draft_pending) and not draft_done
            if not draft_available:
                if draft_done:
                    draft_reason = "Draft Day already completed for this season."
                elif getattr(self.simulator, "draft_date", None) is None:
                    draft_reason = "No Draft Day is scheduled on the calendar."
                else:
                    draft_reason = "No remaining schedule before Draft Day."
            else:
                draft_reason = ""
            self._set_button_state(
                self.simulate_to_draft_button,
                draft_available and not draft_locked,
                draft_lock_reason if draft_locked else draft_reason,
            )
            self.simulate_to_playoffs_button.setText("Simulate to Playoffs")
            playoffs_blocked = (
                getattr(self.simulator, "draft_date", None) is not None and not draft_done
            )
            playoffs_available = (has_games or calendar_remaining > 0) and not playoffs_blocked
            if playoffs_blocked:
                playoffs_reason = "Complete Draft Day before simulating to the playoffs."
            elif not (has_games or calendar_remaining > 0):
                playoffs_reason = "There is no remaining schedule to simulate."
            else:
                playoffs_reason = ""
            self._set_button_state(
                self.simulate_to_playoffs_button,
                playoffs_available and has_any and not draft_locked,
                draft_lock_reason if draft_locked else playoffs_reason,
            )
            season_done = (not phase_pending) and not draft_locked
            self._set_button_state(
                self.next_button,
                season_done,
                "Finish the current phase before advancing.",
            )
        elif is_preseason:
            free_agency_enabled = not self._preseason_done["free_agency"]
            self._set_button_state(
                self.free_agency_button,
                free_agency_enabled,
                "Free agency review already completed.",
            )
            training_enabled = (
                self._preseason_done["free_agency"]
                and not self._preseason_done["training_camp"]
            )
            training_reason = (
                "Complete free agency tasks before running training camp."
                if not self._preseason_done["free_agency"]
                else "Training camp already completed."
            )
            self._set_button_state(
                self.training_camp_button,
                training_enabled,
                training_reason,
            )
            schedule_enabled = (
                self._preseason_done["training_camp"]
                and not self._preseason_done["schedule"]
            )
            if not self._preseason_done["training_camp"]:
                schedule_reason = "Finish training camp before generating the schedule."
            elif self._preseason_done["schedule"]:
                schedule_reason = "Schedule generation already completed."
            else:
                schedule_reason = ""
            self._set_button_state(
                self.generate_schedule_button,
                schedule_enabled,
                schedule_reason,
            )
            self._set_button_state(
                self.next_button,
                self._preseason_done["schedule"],
                "Finish preseason setup before advancing.",
            )
        elif is_playoffs:
            self.simulate_day_button.setText("Simulate Game")
            self.simulate_round_button.setText("Simulate Round")
            self.simulate_week_button.setVisible(False)
            self.simulate_month_button.setVisible(False)
            self.simulate_to_draft_button.setVisible(False)
            self.repair_lineups_button.setVisible(False)
            self.simulate_to_playoffs_button.setVisible(True)
            # If a completed bracket already exists (e.g., simulated via Playoffs Viewer),
            # recognize it and flip the playoffs-done flag so the UI advances without
            # requiring another simulation pass here. If no explicit champion is stored
            # but the championship round has winners decided, infer and persist it.
            if not self._playoffs_done:
                try:
                    from playbalance.playoffs import load_bracket as _lb, save_bracket as _sb

                    b = playoffs_bracket or _lb()
                    playoffs_bracket = b

                    def _is_final_round(name: str) -> bool:
                        tokens = [
                            t.lower()
                            for t in str(name or "").replace("-", " ").replace("_", " ").split()
                            if t
                        ]
                        final_tokens = {"ws", "world", "worlds", "final", "finals", "championship"}
                        return any(t in final_tokens for t in tokens)

                    def _final_round(br) -> object | None:
                        rounds = list(getattr(br, "rounds", []) or [])
                        finals = [r for r in rounds if _is_final_round(getattr(r, "name", ""))]
                        if finals:
                            return finals[-1]
                        return rounds[-1] if rounds else None

                    if b:
                        season_year = self._season_year_hint or self._infer_schedule_year()
                        try:
                            raw_year = getattr(b, "year", None)
                            bracket_year = int(raw_year) if raw_year else None
                        except Exception:
                            bracket_year = None
                        if season_year is None:
                            pass
                        elif bracket_year is not None and season_year != bracket_year:
                            pass
                        else:
                            flag_changed = False
                            champion = getattr(b, "champion", None)
                            if champion and not self._playoffs_done:
                                self._playoffs_done = True
                                flag_changed = True
                            elif champion is None:
                                fr = _final_round(b)
                                matchups = list(getattr(fr, "matchups", []) or []) if fr else []
                                if matchups and all(getattr(m, "winner", None) for m in matchups):
                                    champ = getattr(matchups[0], "winner", None)
                                    if champ:
                                        try:
                                            b.champion = champ
                                            m = matchups[0]
                                            b.runner_up = (
                                                m.low.team_id if champ == m.high.team_id else m.high.team_id
                                            )
                                            _sb(b)
                                        except Exception:
                                            pass
                                        if not self._playoffs_done:
                                            self._playoffs_done = True
                                            flag_changed = True
                            if flag_changed:
                                self._loaded_playoffs_done = True
                                self._save_progress()
                except Exception:
                    pass
            playoffs_done_effective = self._playoffs_done or self._playoffs_override_done
            if playoffs_done_effective:
                self.remaining_label.setText("Playoffs complete.")
                playoffs_reason = "Playoff bracket already completed."
            else:
                self.remaining_label.setText("Playoffs underway; simulate to continue.")
                playoffs_reason = ""
            self.simulate_to_playoffs_button.setText("Simulate Playoffs")
            self.simulate_to_playoffs_button.setVisible(True)
            self._set_button_state(
                self.simulate_day_button,
                not playoffs_done_effective,
                playoffs_reason or "Playoff bracket results already recorded.",
            )
            self._set_button_state(
                self.simulate_round_button,
                not playoffs_done_effective,
                playoffs_reason or "Playoff bracket results already recorded.",
            )
            self._set_button_state(
                self.simulate_to_playoffs_button,
                not playoffs_done_effective,
                playoffs_reason or "Playoff bracket results already recorded.",
            )
            self._set_button_state(
                self.next_button,
                playoffs_done_effective,
                "Complete the playoffs before advancing.",
            )
        elif is_draft:
            # During draft, hide simulation controls; user manages the draft via Draft Console
            self.remaining_label.setVisible(False)
            self.simulate_day_button.setVisible(False)
            self.simulate_week_button.setVisible(False)
            self.simulate_month_button.setVisible(False)
            self.repair_lineups_button.setVisible(False)
            self._set_button_state(
                self.next_button,
                False,
                "Draft operations must finish before advancing.",
            )
        else:
            self.remaining_label.setVisible(False)
            self._set_button_state(self.next_button, True)
        done_enabled = self._active_future is None or self._allow_done_early
        tooltip = "" if done_enabled else "Simulation is running; wait for it to finish."
        self._set_button_state(
            self.done_button,
            done_enabled,
            tooltip,
        )
        self._update_next_phase_tip()
        # Timeline reflects updated status after any UI refresh.
        self._refresh_timeline(bracket=playoffs_bracket)

    def _update_next_phase_tip(self) -> None:
        button = getattr(self, "next_button", None)
        if button is None:
            return
        next_label = self._next_phase_label()
        if not next_label:
            return
        base_tip = f"Next phase: {next_label}."
        try:
            enabled = button.isEnabled()
        except Exception:
            enabled = True
        if enabled:
            tip = base_tip
        else:
            try:
                existing = button.toolTip()
            except Exception:
                existing = ""
            tip = f"{base_tip} {existing}".strip() if existing else base_tip
        try:
            button.setToolTip(tip)
        except Exception:
            pass

    def _next_phase_label(self) -> str:
        phase = getattr(self.manager, "phase", None)
        if phase is None:
            return ""
        if phase == SeasonPhase.OFFSEASON:
            next_phase = SeasonPhase.PRESEASON
        elif phase == SeasonPhase.PRESEASON:
            next_phase = SeasonPhase.REGULAR_SEASON
        elif phase == SeasonPhase.REGULAR_SEASON:
            try:
                season_done = self.simulator._index >= len(self.simulator.dates)
            except Exception:
                season_done = False
            next_phase = (
                SeasonPhase.PLAYOFFS if season_done else SeasonPhase.AMATEUR_DRAFT
            )
        else:
            try:
                next_phase = phase.next()
            except Exception:
                next_phase = None
        if next_phase is None:
            return ""
        return next_phase.name.replace("_", " ").title()

    def _set_simulation_status(self, text: str | None) -> None:
        """Show or hide the simulation status label."""

        if QThread is None:
            self._apply_simulation_status(text)
            return
        try:
            gui_thread = self.thread()
            current_thread = QThread.currentThread()
        except Exception:
            gui_thread = None
            current_thread = None
        if (
            gui_thread is not None
            and current_thread is not None
            and gui_thread != current_thread
        ):
            try:
                self._simStatusRequested.emit(text)
            except Exception:
                pass
            return
        self._apply_simulation_status(text)

    def _apply_simulation_status(self, text: str | None) -> None:
        """Apply the simulation status label update on the GUI thread."""

        label = getattr(self, "simulation_status_label", None)
        if label is None:
            return
        if text:
            if self._sim_status_text == text:
                return
            try:
                label.setText(text)
                label.setVisible(True)
            except RuntimeError:
                return
            self._sim_status_text = text
        else:
            self._sim_status_text = None
            try:
                label.clear()
                label.setVisible(False)
            except RuntimeError:
                pass

    def _update_auto_activate_tip(self) -> None:
        checkbox = getattr(self, "auto_activate_checkbox", None)
        if checkbox is None:
            return
        if self._auto_activate_dl:
            tip = "Eligible DL players return to the roster automatically."
        else:
            tip = "Receive alerts when DL players are ready and activate them manually."
        try:
            checkbox.setToolTip(tip)
        except Exception:
            pass

    def _on_auto_activate_dl_toggled(self, checked: bool) -> None:
        self._auto_activate_dl = bool(checked)
        self._update_auto_activate_tip()
        try:
            self._save_progress()
        except Exception:
            pass

    def _apply_dl_updates(self, *, days_elapsed: int) -> None:
        """Run DL automation after simulations and surface summary text."""

        try:
            today = get_current_sim_date()
        except Exception:
            today = None
        try:
            summary = process_disabled_lists(
                today,
                days_elapsed=days_elapsed,
                auto_activate=self._auto_activate_dl,
            )
        except Exception:
            return
        if not isinstance(summary, DLAutomationSummary) or not summary.has_updates():
            return
        pieces: list[str] = []
        if summary.activated:
            pieces.append(f"{len(summary.activated)} activated")
        if summary.alerts:
            pieces.append(f"{len(summary.alerts)} ready")
        if summary.blocked:
            pieces.append(f"{len(summary.blocked)} blocked")
        if not pieces:
            return
        note = "DL updates: " + ", ".join(pieces)
        if not self._auto_activate_dl:
            note += " (manual mode)"
        try:
            current = self.notes_label.text()
        except Exception:
            current = ""
        try:
            if current:
                self.notes_label.setText(f"{current} | {note}")
            else:
                self.notes_label.setText(note)
        except Exception:
            pass
        if self._show_toast:
            try:
                self._show_toast("info", note)
            except Exception:
                pass

    def _consume_rollover_note(self) -> str | None:
        """Return and clear any pending rollover summary message."""
        result = getattr(self.manager, "rollover_result", None)
        if not result:
            return None
        status = getattr(result, "status", "")
        message: str | None = None
        if status == "archived":
            season_id = getattr(result, "season_id", "season")
            message = f"Season {season_id} archived; next season prepared."
            contract_rollover = getattr(result, "contract_rollover", None)
            if isinstance(contract_rollover, dict):
                retained = int(contract_rollover.get("retained", 0) or 0)
                expired = int(contract_rollover.get("expired", 0) or 0)
                released = int(
                    contract_rollover.get("released_from_rosters", 0) or 0
                )
                message = (
                    f"{message} Contracts carried: {retained}; contracts expired: "
                    f"{expired}; moved to free agency: {released}."
                )
            finance_rollover = getattr(result, "finance_rollover", None)
            if isinstance(finance_rollover, dict):
                arbitration = finance_rollover.get("arbitration")
                team_reset = finance_rollover.get("team_reset")
                awards = 0
                salary_delta = 0
                teams_reset = 0
                if isinstance(arbitration, dict):
                    awards = int(arbitration.get("awards", 0) or 0)
                    salary_delta = int(arbitration.get("salary_delta", 0) or 0)
                if isinstance(team_reset, dict):
                    teams_reset = int(team_reset.get("teams_reset", 0) or 0)
                message = (
                    f"{message} Offseason finance: arbitration awards {awards} "
                    f"(payroll +${salary_delta:,}); team ledgers reset {teams_reset}."
                )
            if self._show_toast:
                self._show_toast("success", message)
        elif status == "error":
            reason = getattr(result, "reason", "unknown error")
            message = f"Season rollover failed: {reason}"
            if self._show_toast:
                self._show_toast("error", message)
        elif status == "skipped":
            note = getattr(result, "reason", None)
            if note:
                message = note
                if self._show_toast:
                    self._show_toast("info", message)
        try:
            events = consume_record_notifications()
        except Exception:
            events = []
        if events:
            lines = []
            for event in events[:10]:
                detail = str(event.get("detail") or event.get("label") or "Record updated")
                lines.append(detail)
            if len(events) > 10:
                lines.append(f"...and {len(events) - 10} more")
            try:
                QMessageBox.information(
                    self,
                    "Records Updated",
                    "\n".join(lines) if lines else "New records were set.",
                )
            except Exception:
                pass
        self.manager.rollover_result = None
        return message

    @staticmethod
    def _format_simulation_progress(label: str, done: int, total: int) -> str:
        """Return a human-friendly progress string for ``done`` of ``total`` days."""

        total = max(total, 1)
        done = max(0, min(done, total))
        percent = min(100.0, (done / total) * 100.0)
        remaining = max(total - done, 0)
        if remaining > 0:
            prefix = f"Simulating {label.lower()}"
        else:
            prefix = f"Simulation complete ({label.lower()})"
        parts = [
            prefix,
            f"{done}/{total} days",
            f"{percent:.0f}% complete",
        ]
        if remaining > 0:
            parts.append(f"{remaining} days remaining")
        return " - ".join(parts)

    def _refresh_timeline(self, *, bracket: object | None = None) -> None:
        """Populate the season timeline list with milestone statuses."""
        timeline = getattr(self, "timeline", None)
        if timeline is None:
            return
        try:
            timeline.clear()
        except Exception:
            return

        status_labels = {
            "done": "Done",
            "current": "In Progress",
            "pending": "Upcoming",
        }
        status_colors = {
            "done": QColor("#2e7d32"),
            "current": QColor("#1565c0"),
            "pending": QColor("#6c757d"),
        }

        def resolve_status(completed: bool, active: bool) -> str:
            if completed:
                return "done"
            if active:
                return "current"
            return "pending"

        def add_event(title: str, status: str, detail: str | None = None) -> None:
            label = status_labels.get(status, status.title())
            text = f"{title} — {label}"
            item = QListWidgetItem(text)
            if detail:
                try:
                    item.setToolTip(detail)
                except Exception:
                    pass
            color = status_colors.get(status)
            if color is not None:
                try:
                    item.setForeground(color)
                except Exception:
                    pass
            if status == "current":
                try:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                except Exception:
                    pass
            try:
                timeline.addItem(item)
            except Exception:
                pass

        phase = self.manager.phase
        schedule_dates = list(getattr(self.simulator, "dates", []) or [])
        current_index = int(getattr(self.simulator, "_index", 0) or 0)
        total_days = len(schedule_dates)
        opening_day = str(schedule_dates[0]) if schedule_dates else None
        mid_index = getattr(self.simulator, "_mid", total_days // 2)
        mid_date = (
            str(schedule_dates[mid_index])
            if schedule_dates and 0 <= mid_index < total_days
            else None
        )
        draft_date = self._draft_date

        progress_data: dict[str, object] = {}
        try:
            if PROGRESS_FILE.exists():
                progress_data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            progress_data = {}
        draft_completed_years = set(
            progress_data.get("draft_completed_years", []) or []
        )

        current_date = get_current_sim_date()
        in_offseason = phase == SeasonPhase.OFFSEASON

        preseason_order = [
            ("Preseason • Free Agency", "free_agency", "List unsigned players and review bids."),
            ("Preseason • Training Camp", "training_camp", "Run training camp to mark players ready."),
            ("Preseason • Generate Schedule", "schedule", "Create the regular-season schedule."),
        ]
        prerequisites_complete = True
        for title, key, detail in preseason_order:
            done = bool(self._preseason_done.get(key)) and not in_offseason
            active = (
                phase == SeasonPhase.PRESEASON
                and not done
                and prerequisites_complete
            )
            add_event(title, resolve_status(done, active), detail)
            prerequisites_complete = prerequisites_complete and done

        if opening_day:
            opening_done = (current_index > 0 or phase in {
                SeasonPhase.AMATEUR_DRAFT,
                SeasonPhase.PLAYOFFS,
                SeasonPhase.OFFSEASON,
            }) and not in_offseason
            opening_active = (
                phase == SeasonPhase.REGULAR_SEASON
                and current_index == 0
                and not opening_done
            )
            add_event(
                "Regular Season • Opening Day",
                resolve_status(opening_done, opening_active),
                f"Scheduled for {opening_day}",
            )
        else:
            missing_detail = (
                "Generate the schedule to set Opening Day."
                if not self._preseason_done.get("schedule")
                else "Schedule data missing; regenerate to set Opening Day."
            )
            opening_done = phase in {
                SeasonPhase.AMATEUR_DRAFT,
                SeasonPhase.PLAYOFFS,
                SeasonPhase.OFFSEASON,
            } and not in_offseason
            opening_active = phase == SeasonPhase.REGULAR_SEASON
            add_event(
                "Regular Season • Opening Day",
                resolve_status(opening_done, opening_active),
                missing_detail,
            )

        if mid_date:
            mid_done = (current_index > mid_index or phase in {
                SeasonPhase.PLAYOFFS,
                SeasonPhase.AMATEUR_DRAFT,
                SeasonPhase.OFFSEASON,
            }) and not in_offseason
            mid_active = (
                phase == SeasonPhase.REGULAR_SEASON
                and current_index <= mid_index
                and not mid_done
            )
            add_event(
                "Regular Season • Midseason Break",
                resolve_status(mid_done, mid_active),
                f"Target date {mid_date}",
            )

        if draft_date:
            detail_parts = [f"Draft Day: {draft_date}"]
            draft_year = None
            try:
                draft_year = int(str(draft_date).split("-")[0])
            except Exception:
                draft_year = None
            draft_done = (draft_year in draft_completed_years if draft_year else False) and not in_offseason
            try:
                days_until = self._days_until_draft()
            except Exception:
                days_until = None
            if isinstance(days_until, int):
                if days_until > 0:
                    detail_parts.append(f"{days_until} days remaining")
                elif days_until == 0:
                    detail_parts.append("Draft is scheduled for today")
                else:
                    detail_parts.append(f"{abs(days_until)} days past target")
            if current_date:
                detail_parts.append(f"Current date: {current_date}")
            draft_active = (
                not draft_done
                and (
                    phase == SeasonPhase.AMATEUR_DRAFT
                    or (
                        phase == SeasonPhase.REGULAR_SEASON
                        and isinstance(days_until, int)
                        and days_until <= 0
                    )
                )
            )
            add_event(
                "Regular Season • Draft Day",
                resolve_status(draft_done, draft_active),
                " • ".join(detail_parts),
            )

        playoffs_done = bool(self._playoffs_done) and not in_offseason
        playoffs_done_effective = playoffs_done or self._playoffs_override_done
        playoffs_active = phase == SeasonPhase.PLAYOFFS and not playoffs_done_effective
        add_event(
            "Postseason • Playoffs",
            resolve_status(playoffs_done_effective, playoffs_active),
            "Simulate rounds and record bracket outcomes.",
        )

        champion = None
        runner_up = None
        playoff_bracket = bracket
        try:
            from playbalance.playoffs import load_bracket as _load_bracket

            if playoff_bracket is None:
                playoff_bracket = _load_bracket()
            if playoff_bracket is not None:
                champion = getattr(playoff_bracket, "champion", None)
                runner_up = getattr(playoff_bracket, "runner_up", None)
        except Exception:
            champion = None

        def _is_final_round(name: str) -> bool:
            tokens = [
                t.lower()
                for t in str(name or "").replace("-", " ").replace("_", " ").split()
                if t
            ]
            final_tokens = {"ws", "world", "worlds", "final", "finals", "championship"}
            return any(t in final_tokens for t in tokens)

        def _round_has_entries(rnd) -> bool:
            matchups = list(getattr(rnd, "matchups", []) or [])
            plan = list(getattr(rnd, "plan", []) or [])
            return bool(matchups or plan)

        def _final_round(br) -> object | None:
            rounds = list(getattr(br, "rounds", []) or [])
            finals = [r for r in rounds if _is_final_round(getattr(r, "name", ""))]
            if finals:
                for rnd in reversed(finals):
                    if _round_has_entries(rnd):
                        return rnd
                for rnd in reversed(rounds):
                    if _round_has_entries(rnd):
                        return rnd
                return finals[-1]
            for rnd in reversed(rounds):
                if _round_has_entries(rnd):
                    return rnd
            return rounds[-1] if rounds else None

        def _matchup_started(matchup: object) -> bool:
            if getattr(matchup, "winner", None):
                return True
            for key in ("games", "results", "scores", "series"):
                value = getattr(matchup, key, None)
                if value:
                    return True
            for key in (
                "high_wins",
                "low_wins",
                "wins_high",
                "wins_low",
                "home_wins",
                "away_wins",
            ):
                value = getattr(matchup, key, None)
                try:
                    if int(value) > 0:
                        return True
                except Exception:
                    continue
            return False

        def _final_started(br) -> bool:
            final_round = _final_round(br)
            matchups = list(getattr(final_round, "matchups", []) or []) if final_round else []
            if not matchups:
                return False
            return any(_matchup_started(m) for m in matchups)

        championship_started = False
        if playoff_bracket is not None:
            try:
                championship_started = _final_started(playoff_bracket)
            except Exception:
                championship_started = False

        if champion or playoffs_done_effective or playoffs_active:
            if champion:
                detail = (
                    f"Champion: {champion}"
                    + (f" • Runner-up: {runner_up}" if runner_up else "")
                )
            elif playoffs_done_effective:
                detail = "Awaiting championship record."
            elif championship_started:
                detail = "Final series underway."
            else:
                detail = "Awaiting final round."
            championship_done = (bool(champion) or playoffs_done_effective) and not in_offseason
            championship_active = (
                playoffs_active and championship_started and not championship_done
            )
            add_event(
                "Postseason • Championship",
                resolve_status(championship_done, championship_active),
                detail,
            )

        if timeline.count() == 0:
            add_event("Timeline data unavailable", "pending")

    def _refresh_timeline_feed(self) -> None:
        feed = getattr(self, "feed_list", None)
        if feed is None:
            return
        try:
            feed.clear()
        except Exception:
            return
        entries = []
        try:
            entries = build_timeline_feed(limit=12)
        except Exception:
            entries = []
        if not entries:
            try:
                feed.addItem(QListWidgetItem("No milestones recorded yet."))
            except Exception:
                pass
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            date_val = str(entry.get("date") or "").strip() or "--"
            label = str(entry.get("label") or "Milestone")
            text = f"{date_val} • {label}"
            item = QListWidgetItem(text)
            detail = str(entry.get("detail") or "").strip()
            if detail:
                try:
                    item.setToolTip(detail)
                except Exception:
                    pass
            try:
                feed.addItem(item)
            except Exception:
                pass

    def _next_phase(self) -> None:
        """Advance to the next phase and update the display."""
        self._playoffs_override_done = False
        if self.manager.phase == SeasonPhase.OFFSEASON:
            next_year = self._resolve_next_league_year()
            retired_count = self._apply_offseason_aging(
                next_year,
                getattr(self.manager, "players", None),
            )
            hof_note = None
            try:
                hof_result = update_hall_of_fame(current_year=next_year)
                added = hof_result.get("added", []) if isinstance(hof_result, dict) else []
                if added:
                    names = ", ".join(
                        [entry.get("player_name", "") for entry in added[:5] if entry.get("player_name")]
                    )
                    if names:
                        suffix = "..." if len(added) > 5 else ""
                        hof_note = f"Hall of Fame inductees: {names}{suffix}"
            except Exception:
                hof_note = None
            base_note = f"Retired Players: {retired_count}"
            if hof_note:
                base_note = f"{base_note}\n{hof_note}"
            self.notes_label.setText(base_note)
            season_manager.TRADE_DEADLINE = date(next_year, 7, 31)
            try:
                self._draft_date = self._compute_draft_date(f"{next_year}-04-01")
            except Exception:
                self._draft_date = None
            self.manager.phase = SeasonPhase.PRESEASON
            self.manager.save()
            self._preseason_done = {
                "free_agency": False,
                "training_camp": False,
                "schedule": False,
            }
            self._playoffs_done = False
            sim_fn = self._resolve_simulate_game()
            self.simulator = SeasonSimulator(
                [],
                sim_fn,
                on_draft_day=self._on_draft_day,
                draft_date=self._draft_date,
                after_game=self._record_game,
            )
            self._season_year_hint = self._infer_schedule_year() or next_year
            note = base_note
        elif self.manager.phase == SeasonPhase.REGULAR_SEASON:
            # If the regular season is complete, skip the Amateur Draft phase
            # and proceed directly to the Playoffs. The draft is handled as an
            # in-season milestone (Draft Day). If it was missed or already
            # completed, it should not block postseason advancement here.
            season_done = self.simulator._index >= len(self.simulator.dates)
            if season_done:
                self.manager.phase = SeasonPhase.PLAYOFFS
                self.manager.save()
                self._playoffs_done = False
                # Merge daily shards now that regular season is complete.
                try:  # pragma: no cover - best effort merge
                    from utils.stats_persistence import merge_daily_history as _merge
                    _merge()
                except Exception:
                    pass
                # Ensure a playoff bracket exists when entering playoffs
                try:
                    self._ensure_playoff_bracket()
                except Exception:
                    pass
                note = None
            else:
                self.manager.advance_phase()
                if self.manager.phase == SeasonPhase.PLAYOFFS:
                    self._playoffs_done = False
                    # If transitioning into playoffs, ensure a bracket exists
                    try:
                        self._ensure_playoff_bracket()
                    except Exception:
                        pass
                note = None
        else:
            previous_phase = self.manager.phase
            self.manager.advance_phase()
            if self.manager.phase == SeasonPhase.PLAYOFFS:
                self._playoffs_done = False
                try:
                    self._ensure_playoff_bracket()
                except Exception:
                    pass
            if previous_phase == SeasonPhase.PLAYOFFS:
                note = self._consume_rollover_note()
            else:
                note = None
        log_news_event(
            f"Season advanced to {self.manager.phase.name.replace('_', ' ').title()}"
        )
        self._save_progress()
        self._update_ui(note)

    # ------------------------------------------------------------------
    # Preseason actions
    # ------------------------------------------------------------------
    def _show_free_agents(self) -> None:
        """Display a simple list of unsigned players."""
        try:
            cpu_summary = run_cpu_free_agency_market(data_dir=get_data_dir())
        except Exception:
            cpu_summary = {"applied": False, "signed_players": 0, "rounds_run": 0}
        cpu_signed = int(cpu_summary.get("signed_players", 0) or 0)
        cpu_rounds = int(cpu_summary.get("rounds_run", 0) or 0)

        try:
            agents = list_unsigned_players_from_files()
        except Exception:
            players = getattr(self.manager, "players", None)
            teams = getattr(self.manager, "teams", None)
            if isinstance(players, Mapping) and isinstance(teams, list):
                agents = list_unsigned_players(players, teams)
            else:
                agents = []
        if agents:
            names = ", ".join(f"{p.first_name} {p.last_name}" for p in agents)
            note = f"Unsigned Players: {names}"
            if cpu_signed > 0:
                note = f"CPU signed {cpu_signed} free agents across {cpu_rounds} round(s). {note}"
            self.notes_label.setText(note)
            log_news_event(
                f"Listed unsigned players: {len(agents)} available"
            )
        else:
            note = "No unsigned players available."
            if cpu_signed > 0:
                note = f"CPU signed {cpu_signed} free agents across {cpu_rounds} round(s). {note}"
            self.notes_label.setText(note)
            log_news_event(note)

        self._set_button_state(
            self.free_agency_button,
            False,
            "Free agency review already completed.",
        )
        self._preseason_done["free_agency"] = True
        message = (
            f"Unsigned Players: {names}" if agents else "No unsigned players available."
        )
        if cpu_signed > 0:
            message = f"CPU signed {cpu_signed} free agents across {cpu_rounds} round(s). {message}"
        self._save_progress()
        self._update_ui(message)
        total_remaining = self._remaining_regular_days()
        if total_remaining > 0:
            try:
                self.remaining_label.setText(
                    f"Days until Season End: {total_remaining}"
                )
            except Exception:
                pass

    def _run_training_camp(self) -> None:
        """Run the training camp and mark players as ready."""
        players = getattr(self.manager, "players", {})
        allocations = self._resolve_training_allocations(players)
        intensity_by_player = self._resolve_training_intensity(players)
        reports = run_training_camp(
            players.values(),
            allocations=allocations,
            intensity_by_player=intensity_by_player,
        )
        summary = self._training_highlights(reports)
        message = (
            summary
            or "Training camp completed. Players marked ready—review highlights in the Admin timeline."
        )
        self.notes_label.setText(message)
        log_news_event(message)
        self._set_button_state(
            self.training_camp_button,
            False,
            "Training camp already completed.",
        )
        self._preseason_done["training_camp"] = True
        self._save_progress()
        self._update_ui(message)

    def _open_training_focus_dialog(self) -> None:
        """Open the league-level training focus configuration dialog."""
        try:
            dialog = TrainingFocusDialog(parent=self, mode="league")
        except Exception:
            return
        result = dialog.exec()
        try:
            accepted = bool(result)
        except Exception:
            accepted = False
        if not accepted:
            return
        message = dialog.result_message or "Training focus preferences updated."
        self.notes_label.setText(message)
        try:
            log_news_event(message)
        except Exception:
            pass

    def _training_highlights(self, reports) -> str:
        """Format a human-readable summary of camp development gains."""
        if not reports:
            return ""
        ranked = sorted(
            reports,
            key=lambda report: sum(report.changes.values() or [0]),
            reverse=True,
        )[:3]
        snippets = []
        for report in ranked:
            if not report.changes:
                detail = report.focus
            else:
                deltas = ", ".join(
                    f"{attr.upper()} +{value}"
                    for attr, value in report.changes.items()
                )
                detail = f"{report.focus}: {deltas}"
            snippets.append(f"{report.player_name} ({detail})")
        if not snippets:
            return ""
        return "Training camp complete. Highlights: " + "; ".join(snippets)

    def _resolve_training_allocations(
        self, players: Mapping[str, object]
    ) -> dict[str, TrainingWeights]:
        """Return training weight mappings keyed by player id."""
        try:
            settings = load_training_settings()
        except Exception:
            return {}
        team_lookup = self._player_team_lookup(players)
        allocations: dict[str, TrainingWeights] = {}
        for pid in players.keys():
            team_id = team_lookup.get(pid)
            allocations[pid] = settings.for_player(str(pid), team_id)
        return allocations

    def _resolve_training_intensity(
        self,
        players: Mapping[str, object],
    ) -> dict[str, float]:
        """Return per-player training multipliers from owner budget settings."""

        if not players:
            return {}
        try:
            team_lookup = self._player_team_lookup(players)
            return training_camp_multiplier_by_player(
                team_lookup,
                data_dir=get_data_dir(),
            )
        except Exception:
            return {}

    def _resolve_development_intensity(
        self,
        player_ids: Iterable[str],
    ) -> dict[str, float]:
        """Return per-player development multipliers from owner budget settings."""

        try:
            ids = {
                str(pid).strip()
                for pid in player_ids  # type: ignore[operator]
                if str(pid).strip()
            }
        except Exception:
            return {}
        if not ids:
            return {}
        try:
            team_lookup = self._player_team_lookup_from_roster_files(ids)
            return development_multiplier_by_player(
                team_lookup,
                data_dir=get_data_dir(),
            )
        except Exception:
            return {}

    def _player_team_lookup_from_roster_files(
        self,
        player_ids: set[str],
    ) -> dict[str, Optional[str]]:
        """Map player ids to team ids by scanning saved roster CSV files."""

        lookup: dict[str, Optional[str]] = {pid: None for pid in player_ids}
        if not player_ids:
            return lookup
        try:
            teams = load_teams(TEAMS_FILE)
        except Exception:
            teams = []
        roster_dir = DATA_DIR / "rosters"
        for team in teams or []:
            team_id = getattr(team, "team_id", None) or getattr(team, "abbreviation", None)
            clean_team_id = str(team_id or "").strip()
            if not clean_team_id:
                continue
            try:
                roster = load_roster(clean_team_id, roster_dir=roster_dir)
            except Exception:
                continue
            slots = []
            for key in ("act", "aaa", "low", "dl", "ir"):
                slots.extend(getattr(roster, key, []) or [])
            for raw_pid in slots:
                pid = str(raw_pid or "").strip()
                if pid in lookup:
                    lookup[pid] = clean_team_id
        return lookup

    def _player_team_lookup(
        self, players: Mapping[str, object]
    ) -> dict[str, Optional[str]]:
        """Map players to their team identifiers based on current rosters."""
        roster_map: dict[str, str] = {}
        teams = getattr(self.manager, "teams", [])
        for team in teams or []:
            team_id = getattr(team, "team_id", None) or getattr(team, "abbreviation", None)
            if not team_id:
                continue
            for roster_name in ("act_roster", "aaa_roster", "low_roster"):
                roster = getattr(team, roster_name, None) or []
                for pid in roster:
                    roster_map[str(pid)] = str(team_id)
        # Ensure free agents fall back to defaults
        return {pid: roster_map.get(pid) for pid in players.keys()}

    def _generate_schedule(self) -> None:
        """Create a full MLB-style schedule for the league."""
        teams = [
            getattr(t, "abbreviation", str(t))
            for t in getattr(self.manager, "teams", [])
        ]
        if not teams and TEAMS_FILE.exists():
            with TEAMS_FILE.open(newline="") as fh:
                reader = csv.DictReader(fh)
                teams = [row["abbreviation"] for row in reader]
        if not teams:
            self._update_ui("No teams available to generate schedule.")
            return
        if len(teams) > MAX_LEAGUE_TEAMS:
            self._update_ui(
                f"League size exceeds the {MAX_LEAGUE_TEAMS}-team limit. "
                "Reduce league size before generating a schedule."
            )
            return

        default_template_id = "mlb_162"
        try:
            from playbalance.season_context import SeasonContext as _SeasonContext

            ctx = _SeasonContext.load()
            metadata = ctx.current.get("metadata", {}) if isinstance(ctx.current, dict) else {}
            preset_value = metadata.get("schedule_template_id")
            if isinstance(preset_value, str) and preset_value:
                default_template_id = preset_value
        except Exception:
            pass

        template_id = select_schedule_template(self, default_id=default_template_id)
        if not template_id:
            return

        schedule_year = self._resolve_current_league_year() or date.today().year
        schedule = generate_schedule_from_template(
            template_id,
            teams,
            year=schedule_year,
        )
        if not schedule:
            self._update_ui("Schedule generation failed for the selected template.")
            return
        save_schedule(schedule, SCHEDULE_FILE)
        first_date = (
            str(schedule[0].get("date") or "").strip()
            if schedule
            else ""
        )
        draft_date = self._compute_draft_date(first_date or None)
        self._draft_date = draft_date
        try:
            from playbalance.season_context import SeasonContext as _SeasonContext

            if schedule:
                if first_date:
                    try:
                        year = int(first_date.split("-")[0])
                    except Exception:
                        year = None
                    ctx = _SeasonContext.load()
                    ctx.ensure_current_season(league_year=year, started_on=first_date)
        except Exception:
            pass
        sim_fn = self._resolve_simulate_game()
        self.simulator = SeasonSimulator(
            schedule,
            sim_fn,
            on_draft_day=self._on_draft_day,
            draft_date=draft_date,
            after_game=self._record_game,
        )
        self._season_year_hint = self._infer_schedule_year()
        message = f"Schedule generated with {len(schedule)} games."
        log_news_event(f"Generated regular season schedule with {len(schedule)} games")
        try:
            record_league_metadata(schedule_template_id=template_id)
        except Exception:
            pass
        self._set_button_state(
            self.generate_schedule_button,
            False,
            "Schedule generation already completed.",
        )
        self._preseason_done["schedule"] = True
        self._save_progress()
        self._update_ui(message)

    # ------------------------------------------------------------------
    # Regular season actions
    # ------------------------------------------------------------------
    def _simulate_day(self) -> None:
        """Trigger simulation for a single schedule day."""
        if self.manager.phase == SeasonPhase.PLAYOFFS:
            self._simulate_playoff_game()
            return
        if (
            self._remaining_regular_days() <= 0
            and self._pending_calendar_days() <= 0
        ):
            return
        # Ensure schedule uses valid team IDs before simulating
        if not self._ensure_valid_schedule_teams():
            return
        # Validate lineups for all teams; stop if any are invalid
        issues = self._validate_all_team_lineups()
        if issues:
            QMessageBox.warning(self, "Missing Lineup or Pitching", "\n".join(issues))
            return
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "A simulation is already in progress. Please wait for it to finish.",
            )
            return

        self._set_sim_buttons_enabled(False)
        self._set_button_state(
            self.cancel_sim_button,
            True,
            "",
        )
        try:
            self.cancel_sim_button.setToolTip("Cancel the simulation currently in progress.")
        except Exception:
            pass
        self._set_button_state(
            self.done_button,
            False,
            "A simulation is running; wait for it to finish.",
        )
        self._set_simulation_status("Simulating day...")
        self._set_sim_progress_visible(True, "Simulating day...")
        try:
            QApplication.processEvents()
        except Exception:
            pass

        def worker() -> tuple[str, dict[str, object]]:
            try:
                self.simulator.simulate_next_day()
            except DraftRosterError as exc:
                message = str(exc) or "Draft assignments remain incomplete."
                failures = getattr(exc, "failures", None)
                if failures:
                    message += "\n\n" + "\n".join(failures)
                return ("draft", {"message": message})
            except (FileNotFoundError, ValueError) as exc:
                return ("lineup", {"message": str(exc)})
            except Exception as exc:  # pragma: no cover - defensive
                return ("error", {"message": str(exc)})

            mid_remaining = self.simulator.remaining_days()
            total_remaining = self._remaining_regular_days()
            if total_remaining > 0:
                if mid_remaining > 0:
                    remaining_msg = f"{mid_remaining} days until Midseason"
                else:
                    remaining_msg = f"{total_remaining} days until Season End"
            else:
                remaining_msg = "regular season complete"
            message = f"Simulated a regular season day; {remaining_msg}"
            date_just_played = None
            try:
                if self.simulator._index > 0 and self.simulator._index - 1 < len(self.simulator.dates):
                    date_just_played = str(self.simulator.dates[self.simulator._index - 1])
            except Exception:
                date_just_played = None
            return (
                "success",
                {
                    "message": message,
                    "date_just_played": date_just_played,
                    "mid_remaining": mid_remaining,
                    "total_remaining": total_remaining,
                },
            )

        handled = {"done": False}

        def handle_result(fut) -> None:
            if handled["done"]:
                return
            handled["done"] = True
            try:
                result = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                result = ("error", {"message": str(exc)})

            def finish() -> None:
                self._active_future = None
                self._set_sim_progress_visible(False)
                self._set_button_state(
                    self.cancel_sim_button,
                    False,
                    "No simulation is currently running.",
                )
                self._set_button_state(self.done_button, True, "")

                kind, payload = result
                message = payload.get("message", "")
                if kind == "draft":
                    QMessageBox.warning(self, "Draft Assignments Incomplete", message)
                    self._set_simulation_status(f"Simulation failed: {message}")
                    self._set_sim_buttons_enabled(True)
                    self._update_ui()
                    return
                if kind == "lineup":
                    QMessageBox.warning(self, "Missing Lineup or Pitching", message)
                    self._set_simulation_status(f"Simulation failed: {message}")
                    self._set_sim_buttons_enabled(True)
                    self._update_ui()
                    return
                if kind == "error":
                    QMessageBox.warning(self, "Simulation Failed", message)
                    self._set_simulation_status(f"Simulation failed: {message}")
                    self._set_sim_buttons_enabled(True)
                    self._update_ui()
                    return

                self.notes_label.setText(message)
                self._set_simulation_status(message)
                mid_remaining = payload.get("mid_remaining")
                total_remaining = payload.get("total_remaining")
                if isinstance(total_remaining, int) and total_remaining > 0:
                    if isinstance(mid_remaining, int) and mid_remaining > 0:
                        self.remaining_label.setText(
                            f"Days until Midseason: {mid_remaining}"
                        )
                    else:
                        self.remaining_label.setText(
                            f"Days until Season End: {total_remaining}"
                        )
                elif isinstance(total_remaining, int):
                    self.remaining_label.setText("Regular season complete.")
                self._show_calendar_countdown = False
                date_just_played = payload.get("date_just_played")
                finance_result: dict[str, object] = {
                    "applied_daily_dates": [],
                    "applied_weeks": [],
                    "applied_periods": [],
                }
                if date_just_played:
                    try:
                        self._log_daily_recap_for_date(str(date_just_played))
                    except Exception:
                        pass
                    finance_result = self._apply_finance_cycles_for_dates(
                        [str(date_just_played)]
                    )
                applied_daily = finance_result.get("applied_daily_dates", [])
                applied_weeks = finance_result.get("applied_weeks", [])
                applied_periods = finance_result.get("applied_periods", [])
                if applied_daily:
                    message = f"{message}; daily finance updated"
                if applied_weeks:
                    message = f"{message}; weekly finance updated"
                if applied_periods:
                    periods_text = ", ".join(str(p) for p in applied_periods)
                    message = f"{message}; monthly finance settled for {periods_text}"
                self.notes_label.setText(message)
                self._set_simulation_status(message)
                log_news_event(message, category="progress")
                self._save_progress()
                self._update_ui(message)
                self._apply_dl_updates(days_elapsed=1)
                try:  # pragma: no cover - best effort merge
                    from utils.stats_persistence import merge_daily_history as _merge
                    _merge()
                except Exception:
                    pass
                try:
                    from utils.player_loader import load_players_from_csv as _lp
                    _lp.cache_clear()  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    from utils.roster_loader import load_roster as _lr
                    _lr.cache_clear()  # type: ignore[attr-defined]
                except Exception:
                    pass

                self._set_sim_buttons_enabled(True)

            self._invoke_on_gui_thread(finish)

        if self._run_async is None or QThread is None:
            result = worker()
            handle_result(type("_Immediate", (), {"result": lambda self=None, value=result: value})())
            return

        future = self._run_async(worker)
        self._active_future = future

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:  # pragma: no cover - fallback for synchronous workers
            handle_result(type("_Immediate", (), {"result": lambda self: future})())
        self._poll_future(future, handle_result)

    def _simulate_span(self, days: int, label: str) -> None:
        self._simulate_span_async(days, label)

    def _request_cancel_simulation(self) -> None:
        """Attempt to cancel the currently running background simulation."""
        if self._active_future is None:
            return
        self._cancel_requested = True
        self._set_simulation_status("Cancelling simulation in progress...")
        self._set_button_state(
            self.cancel_sim_button,
            False,
            "Cancellation request sent; waiting for simulation to stop.",
        )
        self._set_button_state(
            self.done_button,
            False,
            "Wait for the simulation to stop before closing.",
        )
        if hasattr(self._active_future, "cancel"):
            try:
                self._active_future.cancel()
            except Exception:
                pass
        if self._show_toast:
            self._show_toast("info", "Attempting to cancel the current simulation...")

    def _simulate_span_async(self, days: int, label: str) -> None:
        if self._remaining_regular_days() <= 0:
            return
        self._draft_pause_requested = False
        self._allow_done_early = False
        if (
            getattr(self.simulator, "_draft_triggered", False)
            and not self._draft_completed_for_current_year()
        ):
            self._set_simulation_status("Draft Day in progress. Complete the draft before continuing.")
            return
        if not self._ensure_valid_schedule_teams():
            return
        issues = self._validate_all_team_lineups()
        if issues:
            QMessageBox.warning(self, "Missing Lineup or Pitching", "\n".join(issues))
            return
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "A simulation is already in progress. Please wait for it to finish.",
            )
            return

        start = self.simulator._index
        end = min(start + days, len(self.simulator.dates))
        upcoming = list(self.simulator.dates[start:end])
        self._cancel_requested = False
        total_goal = len(upcoming)
        if total_goal <= 0:
            self._set_simulation_status(
                f"No games available for the selected {label.lower()} span."
            )
            self._set_sim_buttons_enabled(True)
            self._set_button_state(
                self.cancel_sim_button,
                False,
                "No simulation is currently running.",
            )
            self._set_button_state(self.done_button, True, "")
            self._allow_done_early = False
            return

        self._set_sim_buttons_enabled(False)
        self._set_button_state(
            self.cancel_sim_button,
            True,
            "",
        )
        try:
            self.cancel_sim_button.setToolTip("Cancel the simulation currently in progress.")
        except Exception:
            pass
        self._set_button_state(
            self.done_button,
            False,
            "A simulation is running; wait for it to finish.",
        )

        def publish_progress(done: int, *, cancelling: bool = False) -> None:
            text = self._format_simulation_progress(label, done, total_goal)
            if cancelling:
                text = f"{text} - cancelling..."

            self._set_simulation_status(text)
            if done >= total_goal and not cancelling:
                self._allow_done_early = True
                self._set_button_state(self.done_button, True, "")
                self._set_button_state(
                    self.cancel_sim_button,
                    False,
                    "Simulation finished; nothing to cancel.",
                )

        publish_progress(0)

        if self._show_toast:
            self._show_toast("info", f"Simulating {label.lower()} in background...")

        def worker() -> Tuple[str, dict[str, Any]]:
            warning: Optional[Tuple[str, str]] = None
            simulated_days = 0
            try:
                while (
                    simulated_days < days
                    and (
                        self._remaining_regular_days() > 0
                        or self._pending_calendar_days() > 0
                    )
                ):
                    try:
                        self.simulator.simulate_next_day()
                    except DraftRosterError as exc:
                        message = str(exc) or "Draft assignments remain incomplete."
                        failures = getattr(exc, "failures", None)
                        if failures:
                            message += "\n\n" + "\n".join(failures)
                        if (
                            self._remaining_regular_days() <= 0
                            and self._pending_calendar_days() <= 1
                        ):
                            try:
                                setattr(self.simulator, "_draft_triggered", True)
                                if hasattr(self.simulator, "dates"):
                                    self.simulator._index = len(self.simulator.dates)
                            except Exception:
                                pass
                            warning = None
                            break
                        warning = ("draft", message)
                        break
                    except (FileNotFoundError, ValueError) as err:
                        warning = ("lineup", str(err))
                        break
                    simulated_days += 1
                    publish_progress(simulated_days, cancelling=self._cancel_requested)
                    if self._draft_pause_requested:
                        if not self._draft_blocked:
                            self._draft_pause_requested = False
                            continue
                        break
                    if self._cancel_requested:
                        break
                was_cancelled = bool(self._cancel_requested and simulated_days < total_goal)
                publish_progress(simulated_days, cancelling=was_cancelled)
                pre_finalized = False
                pre_message: str | None = None
                if QThread is None:
                    pre_message = self._finalize_span(
                        simulated_days,
                        days,
                        label,
                        upcoming,
                        was_cancelled,
                    )
                    pre_finalized = True
                return (
                    "success",
                    {
                        "simulated_days": simulated_days,
                        "warning": warning,
                        "was_cancelled": was_cancelled,
                        "upcoming": upcoming,
                        "pre_finalized": pre_finalized,
                        "pre_message": pre_message,
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive
                return ("error", str(exc))

        def handle_result(fut) -> None:
            try:
                result = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                result = ("error", str(exc))

            def finish() -> None:
                paused_for_draft = bool(self._draft_pause_requested)
                if paused_for_draft:
                    self._draft_blocked = True
                self._active_future = None
                self._allow_done_early = False
                self._set_button_state(
                    self.cancel_sim_button,
                    False,
                    "No simulation is currently running.",
                )
                self._set_button_state(
                    self.done_button,
                    True,
                    "",
                )
                kind, payload = result
                if kind == "error":
                    error_text = str(payload)
                    self._set_simulation_status(f"Simulation failed: {error_text}")
                    QMessageBox.warning(self, "Simulation Failed", error_text)
                    if self._show_toast:
                        self._show_toast("error", error_text)
                    self._set_sim_buttons_enabled(True)
                    self._update_ui()
                    return
                warning = payload.get("warning")
                if warning is not None:
                    QMessageBox.warning(self, "Simulation Warning", warning[1])
                was_cancelled = payload.get("was_cancelled", False)
                if payload.get("pre_finalized"):
                    message = payload.get("pre_message") or ""
                    if paused_for_draft:
                        self._draft_pause_requested = False
                else:
                    message = self._finalize_span(
                        payload.get("simulated_days", 0),
                        days,
                        label,
                        payload.get("upcoming", []),
                        was_cancelled or paused_for_draft,
                    )
                if paused_for_draft and not was_cancelled:
                    message = "Draft Day reached; simulation paused until draft completes."
                if self._show_toast:
                    if warning is not None:
                        toast_kind = "error"
                    elif was_cancelled:
                        toast_kind = "info"
                    else:
                        toast_kind = "success"
                    self._show_toast(toast_kind, message)
                try:
                    self._set_button_state(self.done_button, True, "")
                except Exception:
                    pass

            self._invoke_on_gui_thread(finish)

        if QThread is None:
            result = worker()
            handle_result(type("_Immediate", (), {"result": lambda self=None, value=result: value})())
            return

        future = self._run_async(worker)
        self._active_future = future

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:  # pragma: no cover - fallback for synchronous workers
            handle_result(type("_Immediate", (), {"result": lambda self: future})())

    def _set_sim_buttons_enabled(self, enabled: bool) -> None:
        reason = "A simulation is already running. Please wait for it to finish."
        for btn in (
            self.simulate_day_button,
            self.simulate_round_button,
            self.simulate_week_button,
            self.simulate_month_button,
            self.simulate_to_draft_button,
            self.simulate_to_playoffs_button,
            self.repair_lineups_button,
        ):
            self._set_button_state(btn, enabled, reason)
        if self.engine_toggle is not None:
            try:
                self._set_button_state(
                    self.engine_toggle,
                    False,
                    "Physics engine is now the default.",
                )
            except Exception:
                pass
        if not enabled:
            self._set_button_state(self.next_button, False, reason)

    def _set_sim_progress_visible(self, visible: bool, text: str | None = None) -> None:
        bar = getattr(self, "sim_progress", None)
        if bar is None:
            return
        def apply() -> None:
            try:
                if visible:
                    bar.setRange(0, 0)
                    if text:
                        bar.setFormat(text)
                    bar.setVisible(True)
                else:
                    bar.setVisible(False)
            except Exception:
                pass
        self._invoke_on_gui_thread(apply)

    def _finalize_span(
        self,
        simulated_days: int,
        days: int,
        label: str,
        upcoming: list,
        was_cancelled: bool,
    ) -> str:
        self._draft_pause_requested = False
        total_goal = len(upcoming) or days
        total_goal = max(total_goal, 1)
        mid_remaining = self.simulator.remaining_days()
        draft_remaining = self._days_until_draft()
        total_remaining = self._remaining_regular_days()
        calendar_remaining = self._pending_calendar_days()
        self._show_calendar_countdown = False
        force_season_end = (
            label in {"Week", "Month"}
            and not was_cancelled
            and mid_remaining <= 0
            and total_remaining > 0
        )
        if total_remaining > 0 and not force_season_end:
            if mid_remaining > 0:
                self.remaining_label.setText(
                    f"Days until Midseason: {mid_remaining}"
                )
                remaining_msg = f"{mid_remaining} days until Midseason"
            elif draft_remaining > 0 and total_remaining > 1:
                self.remaining_label.setText(
                    f"Days until Draft: {draft_remaining}"
                )
                remaining_msg = f"{draft_remaining} days until Draft"
            else:
                self.remaining_label.setText(
                    f"Days until Season End: {total_remaining}"
                )
                remaining_msg = f"{total_remaining} days until Season End"
        else:
            if force_season_end and total_remaining > 0:
                self.remaining_label.setText(
                    f"Days until Season End: {total_remaining}"
                )
                remaining_msg = f"{total_remaining} days until Season End"
            elif (
                calendar_remaining > 0
                and (
                    getattr(self.simulator, "_draft_triggered", False)
                    or self._draft_blocked
                )
            ):
                self.remaining_label.setText(
                    f"Days until Season End: {calendar_remaining}"
                )
                remaining_msg = f"{calendar_remaining} days until Season End"
                if (
                    not was_cancelled
                    and isinstance(label, str)
                    and label.lower() == "draft"
                ):
                    self._show_calendar_countdown = True
            else:
                self.remaining_label.setText("Regular season complete.")
                remaining_msg = "regular season complete"

        if was_cancelled:
            if simulated_days <= 0:
                progress_note = "no days completed during the run"
            elif simulated_days == 1:
                progress_note = "completed 1 day this run"
            else:
                progress_note = f"completed {simulated_days} days this run"
            message = (
                f"Simulation cancelled during {label.lower()}; "
                f"{progress_note}, {remaining_msg}"
            )
        else:
            message = f"Simulated {label.lower()}; {remaining_msg}"

        self.notes_label.setText(message)
        self._set_simulation_status(message)
        progress_text = self._format_simulation_progress(label, simulated_days, total_goal)
        self._set_simulation_status(f"{message} - {progress_text}")
        dates_covered = [str(d) for d in upcoming[:simulated_days]]
        try:
            for d in dates_covered:
                self._log_daily_recap_for_date(d)
        except Exception:
            pass
        finance_result = self._apply_finance_cycles_for_dates(dates_covered)
        applied_daily = finance_result.get("applied_daily_dates", [])
        applied_weeks = finance_result.get("applied_weeks", [])
        applied_periods = finance_result.get("applied_periods", [])
        if applied_daily:
            message = f"{message}; daily finance updated"
        if applied_weeks:
            message = f"{message}; weekly finance updated"
        if applied_periods:
            periods_text = ", ".join(str(p) for p in applied_periods)
            message = f"{message}; monthly finance settled for {periods_text}"
            self.notes_label.setText(message)
            self._set_simulation_status(f"{message} - {progress_text}")
        elif applied_daily or applied_weeks:
            self.notes_label.setText(message)
            self._set_simulation_status(f"{message} - {progress_text}")

        log_news_event(message, category="progress")
        self._save_progress()
        self._update_ui(message)
        self._apply_dl_updates(days_elapsed=max(1, simulated_days))
        self._set_button_state(self.done_button, True, "")
        if force_season_end and total_remaining > 0:
            try:
                self.remaining_label.setText(
                    f"Days until Season End: {total_remaining}"
                )
            except Exception:
                pass

        try:
            self._set_sim_buttons_enabled(total_remaining > 0)
        except Exception:
            pass
        try:
            has_remaining = total_remaining > 0 or (self._show_calendar_countdown and calendar_remaining > 0)
            self._set_button_state(
                self.next_button,
                not has_remaining,
                "Finish the current phase before advancing.",
            )
        except Exception:
            pass

        try:  # pragma: no cover - best effort merge
            from utils.stats_persistence import merge_daily_history as _merge

            _merge()
        except Exception:
            pass
        try:
            from utils.player_loader import load_players_from_csv as _lp

            _lp.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            from utils.roster_loader import load_roster as _lr

            _lr.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass

        self._cancel_requested = False
        return message

    def _apply_finance_cycles_for_dates(
        self,
        dates_covered: list[str],
    ) -> dict[str, object]:
        if not dates_covered:
            return {
                "dates": [],
                "applied_daily_dates": [],
                "skipped_daily_dates": [],
                "applied_weeks": [],
                "skipped_weeks": [],
                "periods": [],
                "applied_periods": [],
                "skipped_periods": [],
                "total_net_change": 0,
            }
        try:
            from services.owner_finance_engine import apply_owner_finance_cadence_for_dates

            return apply_owner_finance_cadence_for_dates(dates_covered)
        except Exception:
            return {
                "dates": [],
                "applied_daily_dates": [],
                "skipped_daily_dates": [],
                "applied_weeks": [],
                "skipped_weeks": [],
                "periods": [],
                "applied_periods": [],
                "skipped_periods": [],
                "total_net_change": 0,
            }

    def _log_daily_recap_for_date(self, date_str: str) -> None:
        """Compose and append a daily recap for games on ``date_str``."""
        try:
            games = [g for g in self.simulator.schedule if str(g.get("date", "")) == str(date_str)]
        except Exception:
            games = []
        if not games:
            return
        played = [g for g in games if g.get("result")]
        if not played:
            return
        # Compute one-run and extras counts and build short examples
        one_run = 0
        extras = 0
        examples: list[str] = []
        for g in played:
            res = str(g.get("result") or "")
            if "-" in res:
                try:
                    hs, as_ = res.split("-", 1)
                    hs_i, as_i = int(hs), int(as_)
                    if abs(hs_i - as_i) == 1:
                        one_run += 1
                except Exception:
                    pass
            meta = g.get("extra") or {}
            if isinstance(meta, dict) and meta.get("extra_innings"):
                extras += 1
            # Add up to 3 examples
            if len(examples) < 3:
                examples.append(f"{g.get('away','')} at {g.get('home','')} - {res}")
        msg = (
            f"Daily Recap {date_str}: {len(played)} games; "
            f"{one_run} one-run; {extras} extras. "
            + "; ".join(examples)
        )
        log_news_event(msg, category="game_recap")

    def _simulate_to_draft(self) -> None:
        """Simulate until Draft Day arrives."""
        self._simulate_to_next_phase(target="draft")

    def _simulate_to_playoffs(self) -> None:
        """Simulate the remainder of the regular season or playoffs bracket."""
        if self.manager.phase == SeasonPhase.PLAYOFFS:
            self._simulate_playoffs()
            return
        self._simulate_to_next_phase(target="playoffs")

    def _simulate_to_next_phase(self, target: str | None = None) -> None:
        """Simulate games until the requested phase can advance."""
        if self.manager.phase == SeasonPhase.REGULAR_SEASON:
            self._simulate_regular_season(target)
        elif self.manager.phase == SeasonPhase.PLAYOFFS:
            self._simulate_playoffs()

    def _simulate_regular_season(self, target: str | None) -> None:
        mid_remaining = self.simulator.remaining_days()
        draft_remaining = self._days_until_draft()
        total_remaining = self._remaining_regular_days()
        calendar_remaining = self._pending_calendar_days()
        draft_pending = (
            calendar_remaining > 0
            and getattr(self.simulator, "draft_date", None)
            and not getattr(self.simulator, "_draft_triggered", False)
        )

        if target == "draft":
            self._simulate_until_draft(draft_remaining, draft_pending)
            return

        if target == "playoffs":
            self._simulate_until_playoffs(total_remaining, calendar_remaining)
            return

        if mid_remaining > 0:
            self._simulate_span(mid_remaining, "Midseason")
            return
        if draft_remaining > 0 or draft_pending:
            self._simulate_until_draft(draft_remaining, draft_pending)
            return
        if total_remaining <= 0:
            return
        self._simulate_until_playoffs(total_remaining, calendar_remaining)

    def _simulate_until_draft(
        self,
        draft_remaining: int,
        draft_pending: bool,
    ) -> None:
        if draft_remaining <= 0 and not draft_pending:
            return
        if draft_remaining > 0:
            span = draft_remaining
            pending = self._pending_calendar_days()
            if pending > 0:
                span = min(span, pending)
        elif draft_pending:
            span = 1
        else:
            span = 0
        if span <= 0:
            return
        self._simulate_span(span, "Draft")
        if (
            draft_pending
            and draft_remaining == 0
            and self._remaining_regular_days() <= 0
            and self._pending_calendar_days() > 0
        ):
            try:
                setattr(self.simulator, "_draft_triggered", True)
                if hasattr(self.simulator, "dates"):
                    self.simulator._index = len(self.simulator.dates)
            except Exception:
                pass
            self._show_calendar_countdown = False
            try:
                self._save_progress()
            except Exception:
                pass
            self._update_ui()

    def _simulate_until_playoffs(
        self,
        total_remaining: int,
        calendar_remaining: int,
    ) -> None:
        if total_remaining <= 0 and calendar_remaining <= 0:
            return
        if total_remaining > 0:
            span = total_remaining
            draft_pending = (
                getattr(self.simulator, "draft_date", None)
                and not getattr(self.simulator, "_draft_triggered", False)
            )
            if draft_pending:
                extra_calendar = max(calendar_remaining - total_remaining, 0)
                if extra_calendar > 0:
                    span += extra_calendar
                pending = self._pending_calendar_days()
                if pending > 0:
                    span = min(span, pending)
        else:
            span = calendar_remaining
        if span <= 0:
            return
        self._simulate_span(span, "Regular Season")

    def _simulate_week(self) -> None:
        """Simulate the next seven days or until the break."""
        self._simulate_span(7, "Week")

    def _simulate_month(self) -> None:
        """Simulate the next thirty days or until the break."""
        self._simulate_span(30, "Month")


    def _simulate_playoff_game(self) -> None:
        """Simulate a single playoff game."""
        self._simulate_playoff_step(
            "Simulating playoff game...",
            lambda: self._playoffs_step_workflow("game"),
            "Simulating playoff game in background...",
        )

    def _simulate_playoff_round(self) -> None:
        """Simulate the next playoff round."""
        self._simulate_playoff_step(
            "Simulating playoff round...",
            lambda: self._playoffs_step_workflow("round"),
            "Simulating playoff round in background...",
        )

    def _simulate_playoff_step(
        self,
        status_text: str,
        worker: Callable[[], dict[str, Any]],
        toast_text: str,
    ) -> None:
        if self._playoffs_done:
            self._update_ui("Playoffs complete.")
            return
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "A simulation is already in progress. Please wait for it to finish.",
            )
            return
        self._playoffs_override_done = False
        self._set_playoff_controls_enabled(False)
        self._set_simulation_status(status_text)
        self._set_sim_progress_visible(True, status_text)
        if self._run_async is None or QThread is None:
            result = worker()
            self._set_sim_progress_visible(False)
            self._handle_playoff_step_result(result)
            self._set_playoff_controls_enabled(not self._playoffs_done)
            return
        if self._show_toast:
            self._show_toast("info", toast_text)

        future = self._run_async(worker)
        self._active_future = future

        handled = {"done": False}

        def handle_result(fut) -> None:
            if handled["done"]:
                return
            handled["done"] = True
            try:
                result = fut.result()
            except Exception as exc:  # defensive
                result = {"status": "error", "message": str(exc), "playoffs_done": False}

            def finish() -> None:
                self._active_future = None
                self._set_sim_progress_visible(False)
                self._handle_playoff_step_result(result)
                self._set_playoff_controls_enabled(not self._playoffs_done)
                try:
                    self._update_ui()
                except Exception:
                    pass

            self._invoke_on_gui_thread(finish)

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:
            handle_result(type("_Immediate", (), {"result": lambda self: future})())
        self._poll_future(future, handle_result)
        self._force_playoff_finish_if_stuck(future)
        def bracket_fallback() -> None:
            if handled["done"]:
                return
            try:
                from playbalance.playoffs import load_bracket as _load_bracket
            except Exception:
                _load_bracket = None
            bracket = _load_bracket() if _load_bracket is not None else None
            result = {
                "status": "success",
                "message": "Playoff simulation complete.",
                "playoffs_done": bool(getattr(bracket, "champion", None)) if bracket else False,
                "bracket": bracket,
            }
            handle_result(type("_Immediate", (), {"result": lambda self=None, value=result: value})())
        self._watch_playoff_bracket_update(bracket_fallback)

    def _simulate_playoffs(self) -> None:
        """Simulate the postseason bracket with background support."""
        if self._playoffs_done:
            self._update_ui("Playoffs complete.")
            return
        self._playoffs_override_done = False
        if self._run_async is None or QThread is None:
            self._simulate_playoffs_sync()
        else:
            self._simulate_playoffs_async()

    def _simulate_playoffs_sync(self) -> None:
        self._set_playoff_controls_enabled(False)
        self._set_simulation_status("Simulating playoffs...")
        self._set_sim_progress_visible(True, "Simulating playoffs...")
        result = self._playoffs_workflow()
        self._set_sim_progress_visible(False)
        self._handle_playoffs_result(result)

    def _simulate_playoffs_async(self) -> None:
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "A simulation is already in progress. Please wait for it to finish.",
            )
            return
        self._set_playoff_controls_enabled(False)
        self._set_simulation_status("Simulating playoffs...")
        self._set_sim_progress_visible(True, "Simulating playoffs...")
        if self._show_toast:
            self._show_toast("info", "Simulating playoffs in background...")

        def worker() -> dict[str, Any]:
            return self._playoffs_workflow()

        future = self._run_async(worker)
        self._active_future = future

        def handle_result(fut) -> None:
            try:
                result = fut.result()
            except Exception as exc:  # defensive
                result = {"status": "error", "message": str(exc), "playoffs_done": False}

            def finish() -> None:
                self._active_future = None
                self._set_sim_progress_visible(False)
                self._handle_playoffs_result(result)
                try:
                    self._update_ui()
                except Exception:
                    pass

            self._invoke_on_gui_thread(finish)

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:
            handle_result(type("_Immediate", (), {"result": lambda self: future})())

    def _playoffs_step_workflow(self, mode: str) -> dict[str, Any]:
        from playbalance.playoffs_config import load_playoffs_config
        from playbalance.playoffs import (
            load_bracket,
            save_bracket,
            generate_bracket,
            simulate_next_game,
            simulate_next_round,
        )
        from utils.team_loader import load_teams

        try:
            bracket = load_bracket()
        except Exception:
            bracket = None

        if bracket and getattr(bracket, "champion", None):
            return {
                "status": "already_complete",
                "message": f"Playoffs already completed; champion: {bracket.champion}",
                "playoffs_done": True,
                "bracket": bracket,
            }

        if bracket is None:
            try:
                teams = load_teams()
            except Exception:
                teams = []
            cfg = load_playoffs_config()
            try:
                bracket = generate_bracket(self._standings, teams, cfg)
            except NotImplementedError:
                return {
                    "status": "engine_missing",
                    "message": "Playoffs engine unavailable; cannot simulate.",
                    "playoffs_done": False,
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "message": f"Failed generating playoff bracket: {exc}",
                    "playoffs_done": False,
                }

        try:
            rounds = list(getattr(bracket, "rounds", []) or [])
            has_games = any(getattr(r, "matchups", None) for r in rounds)
        except Exception:
            has_games = False
        if not has_games:
            return {
                "status": "placeholder_complete",
                "message": "Playoffs complete; no games scheduled.",
                "playoffs_done": True,
                "bracket": bracket,
            }

        def _persist(br):
            try:
                save_bracket(br)
            except Exception:
                pass

        simulate_fn = simulate_next_round if mode == "round" else simulate_next_game
        try:
            bracket = simulate_fn(bracket, persist_cb=_persist)
        except NotImplementedError:
            return {
                "status": "engine_missing",
                "message": "Playoffs engine not available; cannot simulate.",
                "playoffs_done": False,
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Failed simulating playoff {mode}: {exc}",
                "playoffs_done": False,
                "bracket": bracket,
            }

        try:
            save_bracket(bracket)
        except Exception:
            pass

        champion = getattr(bracket, "champion", None)
        if champion:
            series_result = self._compute_series_result(bracket)
            return {
                "status": "completed",
                "message": f"Simulated playoff {mode}; championship decided. Champion: {champion}",
                "playoffs_done": True,
                "bracket": bracket,
                "series_result": series_result,
            }

        return {
            "status": "success",
            "message": f"Simulated playoff {mode}.",
            "playoffs_done": False,
            "bracket": bracket,
        }

    def _playoffs_workflow(self) -> dict[str, Any]:
        from playbalance.playoffs_config import load_playoffs_config
        from playbalance.playoffs import (
            load_bracket,
            save_bracket,
            generate_bracket,
            simulate_playoffs as run_playoffs,
        )
        from utils.team_loader import load_teams

        try:
            bracket = load_bracket()
        except Exception:
            return {
                "status": "placeholder_complete",
                "message": "Simulated playoffs; bracket unavailable.",
                "playoffs_done": True,
                "bracket": None,
            }

        if bracket and getattr(bracket, "champion", None):
            return {
                "status": "already_complete",
                "message": f"Playoffs already completed; champion: {bracket.champion}",
                "playoffs_done": True,
                "bracket": bracket,
            }

        if bracket is None:
            try:
                teams = load_teams()
            except Exception:
                teams = []
            cfg = load_playoffs_config()
            try:
                bracket = generate_bracket(self._standings, teams, cfg)
            except NotImplementedError:
                return {
                    "status": "engine_missing",
                    "message": "Playoffs engine unavailable; marking playoffs complete.",
                    "playoffs_done": True,
                }
            except Exception:
                return {
                    "status": "placeholder_complete",
                    "message": "Simulated playoffs; championship decided.",
                    "playoffs_done": True,
                }
            try:
                rounds = list(getattr(bracket, "rounds", []) or [])
                has_games = any(getattr(r, "matchups", None) for r in rounds)
            except Exception:
                has_games = False
            if not has_games:
                return {
                    "status": "placeholder_complete",
                    "message": "Simulated playoffs; championship decided.",
                    "playoffs_done": True,
                    "bracket": bracket,
                }

        def _persist(br):
            try:
                save_bracket(br)
            except Exception:
                pass

        try:
            bracket = run_playoffs(bracket, persist_cb=_persist)
        except NotImplementedError:
            return {
                "status": "engine_missing",
                "message": "Playoffs engine not available; cannot simulate.",
                "playoffs_done": False,
            }
        except Exception:
            return {
                "status": "placeholder_complete",
                "message": "Simulated playoffs; championship decided.",
                "playoffs_done": True,
                "bracket": bracket,
            }

        champion = getattr(bracket, "champion", None)
        if champion:
            series_result = self._compute_series_result(bracket)
            return {
                "status": "completed",
                "message": f"Simulated playoffs; championship decided. Champion: {champion}",
                "playoffs_done": True,
                "bracket": bracket,
                "series_result": series_result,
            }

        return {
            "status": "placeholder_complete",
            "message": "Simulated playoffs; championship decided.",
            "playoffs_done": True,
            "bracket": bracket,
        }

    def _handle_playoffs_result(self, result: dict[str, Any]) -> None:
        status = result.get("status", "error")
        message = result.get("message", "")
        playoffs_done = bool(result.get("playoffs_done"))
        bracket = result.get("bracket")
        series_result = result.get("series_result", "")

        if playoffs_done:
            self._playoffs_done = True
            self._save_progress()

        if status == "error":
            QMessageBox.warning(self, "Playoffs Simulation", message)
            self._set_playoff_controls_enabled(False)
            self._playoffs_done = True
            self._playoffs_override_done = True
            try:
                self._save_progress()
            except Exception:
                pass
            self._set_button_state(self.next_button, True)
            self._set_simulation_status(f"Playoffs simulation failed: {message}")
            if self._show_toast:
                self._show_toast("error", message)
            self._update_ui("Playoffs complete.", bracket=bracket)
            try:
                self.remaining_label.setText("Playoffs complete.")
            except Exception:
                pass
            self._set_button_state(self.next_button, True)
            return

        if status == "engine_missing":
            QMessageBox.information(self, "Playoffs Simulation", message)
            self._set_playoff_controls_enabled(False)
            self._set_button_state(self.next_button, True)
            log_news_event(message)
            self._set_simulation_status(message)
            if self._show_toast:
                self._show_toast("info", message)
            self._update_ui(message, bracket=bracket)
            return

        if status == "already_complete":
            self._set_playoff_controls_enabled(False)
            self._set_button_state(self.next_button, True)
            log_news_event(message)
            self._set_simulation_status(message)
            if self._show_toast:
                self._show_toast("success", message)
            self._update_ui(message, bracket=bracket)
            return

        if bracket is not None:
            try:
                from playbalance.playoffs import save_bracket as _save_bracket
                _save_bracket(bracket)
            except Exception:
                pass

        if status == "completed" and bracket is not None:
            self._write_champions_record(bracket, series_result)

        self._set_playoff_controls_enabled(False)
        self._set_button_state(self.next_button, True)
        log_news_event(message)
        if self._show_toast:
            self._show_toast("success", message)
        self._set_simulation_status(message)
        self._update_ui(message, bracket=bracket)

    def _handle_playoff_step_result(self, result: dict[str, Any]) -> None:
        status = result.get("status", "error")
        message = result.get("message", "")
        playoffs_done = bool(result.get("playoffs_done"))
        bracket = result.get("bracket")
        series_result = result.get("series_result", "")

        if playoffs_done:
            self._playoffs_done = True
            self._save_progress()

        if status == "error":
            QMessageBox.warning(self, "Playoffs Simulation", message)
            self._set_simulation_status(f"Playoffs simulation failed: {message}")
            if self._show_toast:
                self._show_toast("error", message)
            self._update_ui(message, bracket=bracket)
            return

        if status == "engine_missing":
            QMessageBox.information(self, "Playoffs Simulation", message)
            self._set_simulation_status(message)
            if self._show_toast:
                self._show_toast("info", message)
            self._update_ui(message, bracket=bracket)
            return

        if status == "already_complete":
            self._set_simulation_status(message)
            if self._show_toast:
                self._show_toast("success", message)
            self._update_ui(message, bracket=bracket)
            return

        if bracket is not None:
            try:
                from playbalance.playoffs import save_bracket as _save_bracket
                _save_bracket(bracket)
            except Exception:
                pass

        if status in {"completed", "placeholder_complete"} and bracket is not None:
            if getattr(bracket, "champion", None):
                self._write_champions_record(bracket, series_result)

        if not message:
            message = "Playoff simulation complete."
        if message:
            log_news_event(message)
            if self._show_toast:
                self._show_toast("success", message)
        self._set_simulation_status(message)
        self._update_ui(message, bracket=bracket)

    def _set_playoff_controls_enabled(self, enabled: bool) -> None:
        reason = "Playoff simulation already running. Please wait for it to finish."
        for btn in (
            self.simulate_day_button,
            self.simulate_round_button,
            self.simulate_to_playoffs_button,
        ):
            self._set_button_state(btn, enabled, reason)
        if not enabled:
            self._set_button_state(self.next_button, False, "Playoffs must complete before advancing.")

    def _write_champions_record(self, bracket, series_result: str) -> None:
        try:
            import csv

            champions = DATA_DIR / "champions.csv"
            champions.parent.mkdir(parents=True, exist_ok=True)
            write_header = not champions.exists()
            with champions.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                if write_header:
                    writer.writerow(["year", "champion", "runner_up", "series_result"])
                writer.writerow([
                    getattr(bracket, "year", ""),
                    bracket.champion or "",
                    getattr(bracket, "runner_up", "") or "",
                    series_result,
                ])
        except Exception:
            pass

    def _compute_series_result(self, bracket) -> str:
        try:
            ws_round = next((r for r in bracket.rounds if r.name in {"WS", "Final"}), None)
            if not ws_round or not ws_round.matchups:
                return ""
            matchup = ws_round.matchups[0]
            champ = bracket.champion
            wins_c = 0
            wins_o = 0
            for game in getattr(matchup, "games", []):
                res = str(getattr(game, "result", "") or "")
                if "-" not in res:
                    continue
                try:
                    h, a = map(int, res.split("-", 1))
                except Exception:
                    continue
                if h > a:
                    winner = getattr(game, "home", "")
                elif a > h:
                    winner = getattr(game, "away", "")
                else:
                    continue
                if winner == champ:
                    wins_c += 1
                else:
                    wins_o += 1
            return f"{wins_c}-{wins_o}" if (wins_c or wins_o) else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _record_game(self, game: dict[str, str]) -> None:
        """Persist league data after a single game.

        The season simulator invokes this callback after each scheduled game is
        played.  It marks the game as completed, rewrites the schedule file and
        dumps current team standings and player statistics to JSON files.  The
        files are intentionally simple so other parts of the application can
        load them without needing complex formats.
        """

        game["played"] = "1"
        html = game.pop("boxscore_html", None)
        if html:
            game_id = f"{game.get('date','')}_{game.get('away','')}_at_{game.get('home','')}"
            path = save_boxscore_html("season", html, game_id)
            game["boxscore"] = path
        save_schedule(self.simulator.schedule, SCHEDULE_FILE)

        # Update detailed standings splits from the game's result.
        result = game.get("result")
        try:
            if result:
                home_score, away_score = map(int, result.split("-"))
                home_id = game.get("home", "")
                away_id = game.get("away", "")
                if not home_id or not away_id:
                    raise ValueError("missing team identifiers")
                home_rec = self._standings.setdefault(home_id, default_record())
                away_rec = self._standings.setdefault(away_id, default_record())
                meta = game.get("extra") or {}
                one_run = abs(home_score - away_score) == 1
                extra_innings = bool(meta.get("extra_innings"))
                home_hand = (meta.get("home_starter_hand") or "").upper()
                away_hand = (meta.get("away_starter_hand") or "").upper()
                home_div = self._team_divisions.get(home_id)
                away_div = self._team_divisions.get(away_id)
                division_game = bool(home_div and away_div and home_div == away_div)
                update_record(
                    home_rec,
                    won=home_score > away_score,
                    runs_for=home_score,
                    runs_against=away_score,
                    home=True,
                    opponent_hand=away_hand,
                    division_game=division_game,
                    one_run=one_run,
                    extra_innings=extra_innings,
                )
                update_record(
                    away_rec,
                    won=away_score > home_score,
                    runs_for=away_score,
                    runs_against=home_score,
                    home=False,
                    opponent_hand=home_hand,
                    division_game=division_game,
                    one_run=one_run,
                    extra_innings=extra_innings,
                )
        except ValueError:
            pass

        save_standings(self._standings, base_path=DATA_DIR)

    # ------------------------------------------------------------------
    # Lineup validation/repair helpers
    def _team_lineup_is_valid(self, team_id: str) -> bool:
        """Return True if both vs_lhp and vs_rhp are valid 9-hitter lineups.

        Valid means: file exists, 9 unique players, all on ACT roster, and no
        pitchers included. Pitchers are detected using player metadata and
        ``get_role`` ("SP"/"RP" count as pitchers).
        """
        try:
            roster = load_roster(team_id)
        except Exception:
            return False
        act = set(roster.act)
        try:
            players_meta = {
                p.player_id: p for p in load_players_from_csv(DATA_DIR / "players.csv")
            }
        except Exception:
            players_meta = {}
        for vs in ("lhp", "rhp"):
            try:
                lineup = load_lineup(team_id, vs=vs, lineup_dir=DATA_DIR / "lineups")
            except Exception:
                return False
            ids = [pid for pid, _ in lineup]
            if len(set(ids)) != 9 or len(ids) != 9:
                return False
            if any(pid not in act for pid in ids):
                return False
            # Ensure no pitchers included
            for pid in ids:
                p = players_meta.get(pid)
                if p is None:
                    # If we cannot resolve metadata, fall back to allowing
                    # this player to avoid false negatives.
                    continue
                role = get_role(p)
                if getattr(p, "is_pitcher", False) or role in {"SP", "RP"}:
                    return False
        return True

    def _repair_lineups(self) -> None:
        from utils.lineup_autofill import auto_fill_lineup_for_team
        from utils.player_loader import load_players_from_csv
        from utils.roster_backfill import ensure_active_rosters
        from utils.roster_loader import load_roster
        fixed = 0
        failed: list[str] = []
        try:
            teams = load_teams(DATA_DIR / "teams.csv")
        except Exception as exc:
            QMessageBox.warning(self, "Repair Lineups", f"Failed to load teams: {exc}")
            return
        try:
            players = {
                p.player_id: p
                for p in load_players_from_csv(DATA_DIR / "players.csv")
            }
            roster_fix = ensure_active_rosters(
                players=players,
                roster_dir=DATA_DIR / "rosters",
            )
            if roster_fix.get("adjustments"):
                try:
                    load_roster.cache_clear()
                except Exception:
                    pass
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Repair Lineups",
                f"Failed to backfill rosters: {exc}",
            )
        for team in teams:
            try:
                if not self._team_lineup_is_valid(team.team_id):
                    auto_fill_lineup_for_team(team.team_id)
                    if self._team_lineup_is_valid(team.team_id):
                        fixed += 1
                    else:
                        failed.append(team.team_id)
            except Exception:
                failed.append(team.team_id)
        if failed:
            QMessageBox.warning(
                self,
                "Repair Lineups",
                f"Repaired {fixed} teams, but these still need attention: {', '.join(failed)}",
            )
        else:
            QMessageBox.information(self, "Repair Lineups", f"Repaired {fixed} team lineups.")

    # ------------------------------------------------------------------
    # Lineup validation helpers
    def _validate_all_team_lineups(self) -> list[str]:
        """Return a list of issues if any team lacks valid 9-man lineups.

        A lineup is considered valid if both ``vs_lhp`` and ``vs_rhp`` files
        exist for the team, contain 9 unique player_ids, and every player is on
        the team's ACT roster. The message is concise to guide correction.
        """
        issues: list[str] = []
        try:
            teams = load_teams(DATA_DIR / "teams.csv")
        except Exception:
            return issues
        try:
            players_meta = {p.player_id: p for p in load_players_from_csv(DATA_DIR / "players.csv")}
        except Exception:
            players_meta = {}
        for team in teams:
            try:
                roster = load_roster(team.team_id)
            except Exception:
                issues.append(f"{team.team_id}: missing roster file")
                continue
            act = set(roster.act)
            for vs in ("lhp", "rhp"):
                try:
                    lineup = load_lineup(team.team_id, vs=vs, lineup_dir=DATA_DIR / "lineups")
                except FileNotFoundError:
                    issues.append(f"{team.team_id}: missing lineup vs_{vs}")
                    continue
                except ValueError:
                    issues.append(f"{team.team_id}: invalid lineup vs_{vs}")
                    continue
                ids = [pid for pid, _ in lineup]
                if len(set(ids)) != 9 or len(ids) != 9:
                    issues.append(f"{team.team_id}: vs_{vs} must list 9 unique players")
                    continue
                missing = [pid for pid in ids if pid not in act]
                if missing:
                    issues.append(f"{team.team_id}: vs_{vs} includes non-ACT players: {', '.join(missing)}")
                    continue
                # Ensure all lineup players are non-pitchers (eligible hitters)
                bad_roles = []
                for pid in ids:
                    p = players_meta.get(pid)
                    if p is None:
                        continue
                    if getattr(p, "is_pitcher", False) or get_role(p) in {"SP", "RP"}:
                        bad_roles.append(pid)
                if bad_roles:
                    issues.append(f"{team.team_id}: vs_{vs} contains pitchers: {', '.join(bad_roles)}")
        return issues

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    def _schedule_unknown_team_ids(self) -> list[str]:
        """Return schedule team IDs not present in teams.csv.

        Compares the set of IDs appearing in the current schedule's "home" and
        "away" fields against the loaded teams list. The comparison is
        normalization-insensitive: IDs are compared after ``strip()`` and
        ``upper()`` to avoid false positives from stray whitespace or case
        differences in CSVs.
        """
        # Collect raw IDs as they appear in the schedule so any message can
        # show the exact values found, but compare using normalized forms.
        sched_ids_raw: list[str] = []
        for g in self.simulator.schedule:
            home_raw = str(g.get("home", ""))
            away_raw = str(g.get("away", ""))
            if home_raw:
                sched_ids_raw.append(home_raw)
            if away_raw:
                sched_ids_raw.append(away_raw)

        def _norm(s: str) -> str:
            return str(s).strip().upper()

        known_norm = { _norm(k) for k in self._team_divisions.keys() }
        unknown: set[str] = set()
        for tid in sched_ids_raw:
            if _norm(tid) and _norm(tid) not in known_norm:
                # Preserve original token to aid user diagnosis, but ensure
                # uniqueness via set semantics.
                unknown.add(tid)
        return sorted(unknown)

    def _ensure_valid_schedule_teams(self) -> bool:
        """Prompt to regenerate schedule if it references unknown teams.

        Returns True if the schedule is valid or was regenerated; False if the
        user declined regeneration (so callers should abort simulation).
        """
        unknown = self._schedule_unknown_team_ids()
        if not unknown:
            return True
        # Do not overwrite an in-progress season. If any games are already
        # complete (by index or inferred from schedule flags), keep the
        # existing schedule and simply inform the user.
        progressed = False
        try:
            progressed = int(self.simulator._index or 0) > 0
        except Exception:
            progressed = False
        if not progressed:
            try:
                inferred = self._infer_sim_index_from_schedule()
                progressed = inferred > 0
            except Exception:
                progressed = False
        if progressed:
            try:
                QMessageBox.information(
                    self,
                    "Schedule Contains Unknown Teams",
                    (
                        "Some team IDs in the schedule are not present in teams.csv, "
                        "but the season has already progressed. Keeping existing schedule."
                    ),
                )
            except Exception:
                pass
            return True
        try:
            reply = QMessageBox.question(
                self,
                "Invalid Schedule",
                (
                    "Schedule references unknown team IDs: "
                    + ", ".join(unknown)
                    + "\nRegenerate schedule now?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
        except Exception:
            # In headless contexts, default to regenerating
            reply = QMessageBox.StandardButton.Yes  # type: ignore[attr-defined]
        if reply == QMessageBox.StandardButton.Yes:
            self._generate_schedule()
            return True
        # Leave a helpful note if the user declines
        self._update_ui(
            "Schedule contains unknown teams; please regenerate the schedule."
        )
        return False

    def _load_progress(self) -> None:
        """Load preseason and simulation progress from disk."""
        saved_index: int | None = None
        try:
            with PROGRESS_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._preseason_done.update(data.get("preseason_done", {}))
            # Saved index may be absent or out of range after refactors
            raw = data.get("sim_index", None)
            if isinstance(raw, int):
                saved_index = raw
            playoffs_flag = data.get("playoffs_done", self._playoffs_done)
            self._playoffs_done = playoffs_flag
            self._loaded_playoffs_done = bool(playoffs_flag)
            self._auto_activate_dl = bool(data.get("auto_activate_dl", self._auto_activate_dl))
        except (OSError, json.JSONDecodeError):
            # No saved file or invalid JSON â€” fall back to inference
            pass

        inferred_index = self._infer_sim_index_from_schedule()
        # Prefer the larger of saved vs inferred to avoid regressing progress
        if saved_index is None:
            new_index = inferred_index
        else:
            new_index = max(int(saved_index), int(inferred_index))

        # Clamp to available date range
        if self.simulator.dates:
            new_index = max(0, min(new_index, len(self.simulator.dates)))
        else:
            new_index = 0

        self.simulator._index = new_index
        # Persist a repaired/initialized progress file for future runs only
        # when it changes, to avoid clobbering progress in transient error cases.
        try:
            cur_idx = None
            try:
                with PROGRESS_FILE.open("r", encoding="utf-8") as fh:
                    cur = json.load(fh)
                cur_idx = int(cur.get("sim_index", 0) or 0)
            except Exception:
                cur_idx = None
            if cur_idx is None or int(new_index) != int(cur_idx):
                self._save_progress()
        except Exception:
            pass

    def _infer_sim_index_from_schedule(self) -> int:
        """Infer current day index from the schedule file/state.

        A date is considered completed if all games for that date have
        a truthy "played" flag or contain a result. This allows recovering
        progress when ``season_progress.json`` is missing or stale but the
        schedule and standings have persisted across code changes.
        """
        if not self.simulator.schedule or not self.simulator.dates:
            return 0
        by_date: dict[str, list[dict[str, str]]] = {}
        for g in self.simulator.schedule:
            by_date.setdefault(g.get("date", ""), []).append(g)
        completed_days = 0
        for d in self.simulator.dates:
            games = by_date.get(d, [])
            if not games:
                break
            all_done = True
            for game in games:
                played = game.get("played")
                result = game.get("result")
                if not (str(played).strip() == "1" or (result and str(result).strip())):
                    all_done = False
                    break
            if all_done:
                completed_days += 1
            else:
                break
        return completed_days

    def _save_progress(self) -> None:
        """Persist preseason and simulation progress to disk."""
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Merge with existing progress so we don't drop fields like
        # "draft_completed_years" that may be written elsewhere (e.g., on
        # Draft Day completion). This avoids re-triggering the draft.
        existing: dict[str, object] = {}
        try:
            if PROGRESS_FILE.exists():
                with PROGRESS_FILE.open("r", encoding="utf-8") as fh:
                    existing = json.load(fh) or {}
        except Exception:
            existing = {}

        existing["preseason_done"] = self._preseason_done
        existing["sim_index"] = self.simulator._index
        existing["playoffs_done"] = self._playoffs_done
        existing["auto_activate_dl"] = self._auto_activate_dl

        with PROGRESS_FILE.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        # Notify listeners that the date may have advanced
        cur: str | None = None
        try:
            cur = get_current_sim_date()
            self.progressUpdated.emit(cur or "")
        except Exception:
            pass
        try:
            notify_sim_date_changed(cur)
        except Exception:
            pass

