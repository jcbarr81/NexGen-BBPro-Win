from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

"""Playoffs viewer window.

Displays the current bracket (rounds, series, and game results). This window
provides refresh and simulation controls for stepping through the playoffs.
"""

from services.season_progress_flags import (
    ProgressUpdateError,
    mark_playoffs_completed,
)
from services.unified_data_service import get_unified_data_service

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QWidget,
        QFrame,
        QMessageBox,
    )
    from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
except Exception:  # pragma: no cover - headless stubs for tests
    class _Signal:
        def __init__(self):
            self._slot = None
        def connect(self, slot):
            self._slot = slot
        def emit(self, *a, **k):
            if self._slot:
                self._slot(*a, **k)
    class _SignalDescriptor:
        def __init__(self):
            self._signals = {}
        def __get__(self, obj, owner):
            if obj is None:
                return self
            key = id(obj)
            sig = self._signals.get(key)
            if sig is None:
                sig = _Signal()
                self._signals[key] = sig
            return sig
    class QDialog:
        def __init__(self, *a, **k):
            pass
        def show(self):
            pass
    class QWidget: pass
    class QFrame(QWidget):
        class Shape: StyledPanel = 0
        def setFrameShape(self, *a, **k): pass
    class QLabel:
        def __init__(self, text="", *a, **k): self._t=text
        def setText(self, t): self._t=t
    class QPushButton:
        def __init__(self, *a, **k): self.clicked=_Signal()
    class QMessageBox:
        @staticmethod
        def information(*a, **k): pass
        @staticmethod
        def warning(*a, **k): pass
    class QVBoxLayout:
        def __init__(self, *a, **k): pass
        def addWidget(self, *a, **k): pass
        def addLayout(self, *a, **k): pass
        def addStretch(self, *a, **k): pass
        def setContentsMargins(self, *a, **k): pass
        def setSpacing(self, *a, **k): pass
    class QHBoxLayout(QVBoxLayout): pass
    class QScrollArea:
        def __init__(self, *a, **k): pass
        def setWidget(self, *a, **k): pass
        def setWidgetResizable(self, *a, **k): pass
    class Qt:
        class AlignmentFlag: AlignLeft = 0; AlignTop = 0; AlignHCenter = 0
    class QObject:
        def __init__(self, *a, **k):
            pass
    class QTimer:
        @staticmethod
        def singleShot(ms, func):
            func()
    def pyqtSignal(*a, **k):
        return _SignalDescriptor()

from playbalance.playoffs import load_bracket

ROUND_STAGE_ALIASES = {
    "WC": "Play-In",
    "DS": "Round 1",
    # Note: "CS" label varies by context. For single-league brackets where CS is the last
    # displayed round, we relabel it as "League Championship" downstream.
    "CS": "Round 2",
    "WS": "Championship",
    "FINAL": "Championship",
    "FINALS": "Championship",
}


class _PlayoffNotifier(QObject):
    sim_finished = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()


def _friendly_round_title(raw_name: str, *, single_league: bool = False) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return "Round"
    parts = name.split()
    if len(parts) == 1:
        code = parts[0].upper()
        if single_league and code == "CS":
            return "League Championship"
        return ROUND_STAGE_ALIASES.get(code, name)
    stage_code = parts[-1].upper()
    if single_league and stage_code == "CS":
        label = "League Championship"
    else:
        label = ROUND_STAGE_ALIASES.get(stage_code)
    if not label:
        return name
    league = " ".join(parts[:-1]).strip()
    return f"{label} - {league}" if league else label


def _build_bracket_markdown(bracket) -> list[str]:
    lines: list[str] = []
    title = f"# Playoffs {getattr(bracket, 'year', '')}"
    champ = getattr(bracket, "champion", None)
    if champ:
        title += f" - Champion: {champ}"
    lines.append(title)
    lines.append("")
    try:
        try:
            _lg_keys = list((getattr(bracket, "seeds_by_league", {}) or {}).keys())
        except Exception:
            _lg_keys = []
        _all_rounds = list(getattr(bracket, "rounds", []) or [])
        if len(_lg_keys) <= 1:
            _rounds_iter = [
                r
                for r in _all_rounds
                if str(getattr(r, "name", "")).strip().lower() not in {"final", "finals"}
            ]
        else:
            _rounds_iter = _all_rounds

        for rnd in _rounds_iter:
            lines.append(
                f"## {_friendly_round_title(rnd.name, single_league=(len(_lg_keys) <= 1))}"
            )
            for m in rnd.matchups or []:
                wins_high = 0
                wins_low = 0
                for g in (m.games or []):
                    res = str(getattr(g, "result", "") or "")
                    home = getattr(g, "home", "")
                    away = getattr(g, "away", "")
                    if "-" in res:
                        try:
                            hs, as_ = res.split("-", 1)
                            hs, as_ = int(hs), int(as_)
                            if hs > as_:
                                winner = home
                            elif as_ > hs:
                                winner = away
                            else:
                                continue
                            if winner == m.high.team_id:
                                wins_high += 1
                            elif winner == m.low.team_id:
                                wins_low += 1
                        except Exception:
                            pass
                series = f" ({wins_high}-{wins_low})" if (wins_high or wins_low) else ""
                lines.append(
                    f"- ({m.high.seed}) {m.high.team_id} vs ({m.low.seed}) {m.low.team_id}{series} - Winner: {m.winner or 'TBD'}"
                )
                for gi, g in enumerate(m.games or []):
                    res = str(getattr(g, "result", "") or "?")
                    path = getattr(g, "boxscore", "") or ""
                    lines.append(
                        f"  - G{gi+1}: {g.away} at {g.home} - {res}  {path}"
                    )
            lines.append("")
    except Exception:
        pass
    return lines


class PlayoffsWindow(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        run_async: Optional[Callable[[Callable[[], Any]], Any]] = None,
        show_toast: Optional[Callable[[str, str], None]] = None,
        register_cleanup: Optional[Callable[[Callable[[], None]], None]] = None,
    ):
        super().__init__(parent)
        try:
            self.setWindowTitle("Playoffs")
            self.resize(900, 600)
        except Exception:
            pass

        self._executor: ThreadPoolExecutor | None = None
        if run_async is None:
            executor = ThreadPoolExecutor(max_workers=2)
            self._executor = executor
            self._run_async = executor.submit
            if register_cleanup is not None:
                register_cleanup(lambda ex=executor: ex.shutdown(wait=False))
        else:
            self._run_async = run_async
        self._show_toast = show_toast
        self._register_cleanup = register_cleanup
        self._notifier = _PlayoffNotifier()
        try:
            self._notifier.sim_finished.connect(self._handle_sim_result)
        except Exception:
            pass
        self._active_future: Any | None = None
        self._export_future: Any | None = None
        self._open_future: Any | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("Current Bracket")
        header.addWidget(self.title)
        header.addStretch()
        self.sim_game_btn = QPushButton("Simulate Day")
        self.sim_game_btn.clicked.connect(self._simulate_game)
        header.addWidget(self.sim_game_btn)
        self.sim_round_btn = QPushButton("Simulate Round")
        self.sim_round_btn.clicked.connect(self._simulate_round)
        header.addWidget(self.sim_round_btn)
        self.sim_all_btn = QPushButton("Simulate Remaining")
        self.sim_all_btn.clicked.connect(self._simulate_all)
        header.addWidget(self.sim_all_btn)
        self.export_btn = QPushButton("Export Summary")
        self.export_btn.clicked.connect(self._export_summary)
        header.addWidget(self.export_btn)
        self.open_btn = QPushButton("Open Summary")
        self.open_btn.clicked.connect(self._open_summary)
        header.addWidget(self.open_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        root.addWidget(self.scroll)

        self.container = QWidget()
        self.cv = QVBoxLayout(self.container)
        self.cv.setContentsMargins(8, 8, 8, 8)
        self.cv.setSpacing(10)
        self.scroll.setWidget(self.container)

        self._bracket = None
        self._last_summary_path = None
        self._data_service = get_unified_data_service()
        self._event_unsubscribes: list[Callable[[], None]] = []
        self._pending_refresh = False
        self._pending_toast_reason: Optional[str] = None
        self._register_data_subscriptions()
        self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt signature
        for fut in (self._active_future, self._export_future, self._open_future):
            try:
                if fut is not None and hasattr(fut, "cancel"):
                    fut.cancel()
            except Exception:
                pass
        self._active_future = None
        self._export_future = None
        self._open_future = None
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None
        for unsubscribe in getattr(self, "_event_unsubscribes", []):
            try:
                unsubscribe()
            except Exception:
                pass
        self._event_unsubscribes = []
        super().closeEvent(event)

    def _register_data_subscriptions(self) -> None:
        bus = getattr(self._data_service, "events", None)
        if bus is None:
            return

        def _enqueue_refresh(_payload=None) -> None:
            QTimer.singleShot(0, self._handle_external_update)

        for topic in ("standings.updated", "standings.invalidated"):
            try:
                self._event_unsubscribes.append(bus.subscribe(topic, _enqueue_refresh))
            except Exception:  # pragma: no cover - defensive
                pass

    def _handle_external_update(self) -> None:
        try:
            visible = self.isVisible()
        except Exception:
            visible = True
        message = "Standings updated; playoff bracket refreshed."
        if not visible:
            self._pending_refresh = True
            self._pending_toast_reason = message
            self._bracket = None
            return
        self.refresh()
        if callable(self._show_toast):
            try:
                self._show_toast("info", message)
            except Exception:
                pass

    def showEvent(self, event):  # pragma: no cover - UI callback
        try:
            super().showEvent(event)
        except Exception:
            pass
        if self._pending_refresh:
            self._pending_refresh = False
            self.refresh()
            if self._pending_toast_reason and callable(self._show_toast):
                try:
                    self._show_toast("info", self._pending_toast_reason)
                except Exception:
                    pass
            self._pending_toast_reason = None

    def refresh(self, *, bracket: object | None = None) -> None:
        if bracket is not None:
            self._bracket = bracket
        else:
            self._bracket = load_bracket()
        # Clear existing
        while getattr(self.cv, 'count', lambda: 0)():
            item = self.cv.takeAt(0)
            w = item.widget()
            if w is not None:
                try:
                    w.setParent(None)
                except Exception:
                    pass
        if not self._bracket:
            # Lazy-generate a bracket if we're in playoffs and none exists yet.
            try:
                from utils.path_utils import get_base_dir
                from playbalance.playoffs import generate_bracket, save_bracket
                from playbalance.playoffs_config import load_playoffs_config
                from utils.team_loader import load_teams
                from services.standings_repository import load_standings
                standings = load_standings()
                teams = []
                try:
                    teams = load_teams()
                except Exception:
                    pass
                cfg = load_playoffs_config()
                if standings and teams:
                    b = generate_bracket(standings, teams, cfg)
                    try:
                        save_bracket(b)
                        self._bracket = b
                    except Exception:
                        pass
            except Exception:
                pass
        if not self._bracket:
            self.cv.addWidget(QLabel("No playoffs bracket found."))
            try:
                self.sim_game_btn.setEnabled(False)
                self.sim_round_btn.setEnabled(False)
                self.sim_all_btn.setEnabled(False)
            except Exception:
                pass
            return
        # Header details
        year = getattr(self._bracket, 'year', '')
        champ = getattr(self._bracket, 'champion', None) or "(TBD)"
        self.title.setText(f"Playoffs {year} - Champion: {champ}")

        # Determine which rounds to show. In single-league formats the bracket
        # may include a duplicated "Final" entry (same as the league CS) purely
        # for metadata. Hide it from the viewer to avoid a phantom third round.
        try:
            _lg_keys = list((getattr(self._bracket, 'seeds_by_league', {}) or {}).keys())
        except Exception:
            _lg_keys = []
        _all_rounds = list(getattr(self._bracket, 'rounds', []) or [])
        if len(_lg_keys) <= 1:
            _rounds_iter = [
                r for r in _all_rounds
                if str(getattr(r, 'name', '')).strip().lower() not in {"final", "finals"}
            ]
        else:
            _rounds_iter = _all_rounds

        for rnd in _rounds_iter:
            box = QFrame()
            try:
                box.setFrameShape(QFrame.Shape.StyledPanel)
            except Exception:
                pass
            bv = QVBoxLayout(box)
            bv.setContentsMargins(8, 8, 8, 8)
            bv.setSpacing(6)
            raw_name = str(rnd.name)
            title = _friendly_round_title(raw_name, single_league=(len(_lg_keys) <= 1))
            lbl = QLabel(title)
            if title != raw_name and hasattr(lbl, "setToolTip"):
                try:
                    lbl.setToolTip(raw_name)
                except Exception:
                    pass
            bv.addWidget(lbl)
            if not rnd.matchups:
                bv.addWidget(QLabel("(awaiting participants)"))
            for i, m in enumerate(rnd.matchups):
                # Compute series record for tooltip
                wins_high = 0
                wins_low = 0
                game_lines = []
                try:
                    for gi, g in enumerate(m.games):
                        res = str(getattr(g, 'result', '') or '')
                        home = getattr(g, 'home', '')
                        away = getattr(g, 'away', '')
                        if '-' in res:
                            try:
                                hs, as_ = res.split('-', 1)
                                hs, as_ = int(hs), int(as_)
                                if hs > as_:
                                    if home == m.high.team_id:
                                        wins_high += 1
                                    elif home == m.low.team_id:
                                        wins_low += 1
                                elif as_ > hs:
                                    if away == m.high.team_id:
                                        wins_high += 1
                                    elif away == m.low.team_id:
                                        wins_low += 1
                            except Exception:
                                pass
                        game_lines.append(f"G{gi+1}: {away} at {home} - {res}")
                except Exception:
                    pass
                series_note = f" (Series {wins_high}-{wins_low})" if (wins_high or wins_low) else ""
                line = QLabel(f"({m.high.seed}) {m.high.team_id} vs ({m.low.seed}) {m.low.team_id}{series_note} - Winner: {m.winner or 'TBD'}")
                try:
                    line.setToolTip("\n".join(game_lines) if game_lines else "No games played yet.")
                except Exception:
                    pass
                bv.addWidget(line)
                # List game results succinctly
                for gi, g in enumerate(m.games):
                    res = g.result or "?"
                    gl = QLabel(f"  G{gi+1}: {g.away} at {g.home} - {res}")
                    bv.addWidget(gl)
            self.cv.addWidget(box)
        self.cv.addStretch(1)

        # Enable/disable simulate buttons if champion decided
        try:
            done = bool(getattr(self._bracket, 'champion', None))
            self.sim_game_btn.setEnabled(not done)
            self.sim_round_btn.setEnabled(not done)
            self.sim_all_btn.setEnabled(not done)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Simulation helpers
    def _simulate_game(self) -> None:
        self._simulate_game_async()

    def _simulate_round(self) -> None:
        self._simulate_round_async()

    def _simulate_all(self) -> None:
        self._simulate_all_async()

    def _simulate_game_async(self) -> None:
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "Playoff simulation already in progress. Please wait for it to finish.",
            )
            return
        payload = {
            "title": "Simulating next playoff game...",
            "worker": self._simulate_game_work,
        }
        self._run_playoff_worker(payload)

    def _simulate_round_async(self) -> None:
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "Playoff simulation already in progress. Please wait for it to finish.",
            )
            return
        payload = {
            "title": "Simulating next round...",
            "worker": self._simulate_round_work,
        }
        self._run_playoff_worker(payload)

    def _simulate_all_async(self) -> None:
        if self._active_future is not None:
            QMessageBox.information(
                self,
                "Simulation Running",
                "Playoff simulation already in progress. Please wait for it to finish.",
            )
            return
        payload = {
            "title": "Simulating remaining playoffs...",
            "worker": self._simulate_all_work,
        }
        self._run_playoff_worker(payload)

    def _run_playoff_worker(self, payload: dict[str, Any]) -> None:
        worker = payload["worker"]
        self._set_sim_buttons_enabled(False)
        if self._show_toast:
            self._show_toast("info", payload["title"])
        future = self._run_async(worker)
        self._active_future = future

        def handle_result(fut) -> None:
            try:
                result = fut.result()
            except Exception as exc:
                result = {"status": "error", "message": str(exc)}
            self._active_future = None
            try:
                self._notifier.sim_finished.emit(result)
            except Exception:
                self._handle_sim_result(result)

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:
            handle_result(type("_Immediate", (), {"result": lambda self: future})())

    def _simulate_round_work(self) -> dict[str, Any]:
        from playbalance.playoffs import simulate_next_round, save_bracket

        bracket = self._load_bracket_for_sim()
        if not bracket:
            return {"status": "error", "message": "No playoff bracket available."}
        try:
            bracket = simulate_next_round(bracket)
        except Exception as exc:
            return {"status": "error", "message": f"Failed simulating round: {exc}"}
        try:
            save_bracket(bracket)
        except Exception:
            pass
        self._bracket = bracket
        return {
            "status": "success",
            "message": "Simulated playoff round.",
            "bracket": bracket,
        }

    def _simulate_game_work(self) -> dict[str, Any]:
        from playbalance.playoffs import simulate_next_game, save_bracket

        bracket = self._load_bracket_for_sim()
        if not bracket:
            return {"status": "error", "message": "No playoff bracket available."}
        try:
            bracket = simulate_next_game(bracket)
        except Exception as exc:
            return {"status": "error", "message": f"Failed simulating game: {exc}"}
        try:
            save_bracket(bracket)
        except Exception:
            pass
        self._bracket = bracket
        return {
            "status": "success",
            "message": "Simulated next playoff game.",
            "bracket": bracket,
        }

    def _simulate_all_work(self) -> dict[str, Any]:
        from playbalance.playoffs import simulate_playoffs, save_bracket

        bracket = self._load_bracket_for_sim()
        if not bracket:
            return {"status": "error", "message": "No playoff bracket available."}
        try:
            bracket = simulate_playoffs(bracket)
        except Exception as exc:
            return {"status": "error", "message": f"Failed simulating playoffs: {exc}"}
        try:
            save_bracket(bracket)
        except Exception:
            pass
        self._bracket = bracket
        return {
            "status": "success",
            "message": "Simulated remaining playoffs.",
            "bracket": bracket,
        }

    def _load_bracket_for_sim(self):
        from playbalance.playoffs import load_bracket

        year = getattr(self._bracket, "year", None)
        bracket = self._bracket
        if bracket is None and year is not None:
            bracket = load_bracket(year=year)
        if bracket is None:
            bracket = load_bracket()
        return bracket

    def _handle_sim_result(self, result: dict[str, Any]) -> None:
        self._set_sim_buttons_enabled(True)
        status = result.get("status", "error")
        message = result.get("message", "")
        if status != "success":
            if message:
                QMessageBox.warning(self, "Playoffs Simulation", message)
            if self._show_toast:
                self._show_toast("error", message or "Playoff simulation failed.")
            return
        if message:
            if self._show_toast:
                self._show_toast("success", message)
        bracket = result.get("bracket")
        if bracket is not None:
            self._bracket = bracket
            champion = getattr(bracket, "champion", None)
            if champion:
                try:
                    mark_playoffs_completed()
                except ProgressUpdateError as exc:
                    if self._show_toast:
                        self._show_toast(
                            "warning",
                            f"Playoffs completed but progress file could not be updated: {exc}",
                        )
        self.refresh(bracket=bracket)

    def _set_sim_buttons_enabled(self, enabled: bool) -> None:
        for btn in (self.sim_game_btn, self.sim_round_btn, self.sim_all_btn):
            try:
                btn.setEnabled(enabled)
            except Exception:
                pass

    def _export_summary(self) -> None:
        if self._export_future is not None:
            QMessageBox.information(
                self,
                "Export Running",
                "A summary export is already running. Please wait for it to finish.",
            )
            return
        if self._show_toast:
            self._show_toast("info", "Exporting playoff summary in background...")

        def worker() -> dict[str, Any]:
            return self._export_summary_work()

        future = self._run_async(worker)
        self._export_future = future

        def handle_result(fut) -> None:
            try:
                result = fut.result()
            except Exception as exc:
                result = {"status": "error", "message": str(exc)}

            def finish() -> None:
                self._export_future = None
                self._handle_export_result(result)

            QTimer.singleShot(0, finish)

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:
            handle_result(type("_Immediate", (), {"result": lambda self: future})())

    def _export_summary_work(self) -> dict[str, Any]:
        from playbalance.playoffs import load_bracket
        from utils.path_utils import get_base_dir
        from pathlib import Path

        bracket = load_bracket()
        if not bracket:
            return {"status": "error", "message": "No playoff bracket available to export."}
        lines = _build_bracket_markdown(bracket)
        try:
            out = Path(get_base_dir()) / "data" / f"playoffs_summary_{getattr(bracket, 'year', '')}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(lines), encoding="utf-8")
            return {"status": "success", "path": str(out)}
        except Exception as exc:
            return {"status": "error", "message": f"Failed exporting summary: {exc}"}

    def _handle_export_result(self, result: dict[str, Any]) -> None:
        status = result.get("status", "error")
        path = result.get("path")
        message = result.get("message", "")
        if status != "success":
            retry = False
            try:
                btn = QMessageBox.question(
                    self,
                    "Export Summary",
                    message or "Export failed. Retry?",
                    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Close,
                    QMessageBox.StandardButton.Retry,
                )
                retry = btn == QMessageBox.StandardButton.Retry
            except Exception:
                if message:
                    QMessageBox.warning(self, "Export Summary", message)
            if self._show_toast:
                self._show_toast("error", message or "Export failed.")
            if retry:
                self._export_summary()
            return
        self._last_summary_path = path
        if self._show_toast:
            self._show_toast("success", f"Summary exported to {path}")
        QMessageBox.information(self, "Export Summary", f"Summary exported to:\n{path}")

    def _open_summary(self) -> None:
        if self._open_future is not None:
            QMessageBox.information(
                self,
                "Open Summary",
                "Summary is already being opened. Please wait.",
            )
            return
        if self._show_toast:
            self._show_toast("info", "Opening playoff summary...")

        def worker() -> dict[str, Any]:
            return self._open_summary_work()

        future = self._run_async(worker)
        self._open_future = future

        def handle_result(fut) -> None:
            try:
                result = fut.result()
            except Exception as exc:
                result = {"status": "error", "message": str(exc)}

            def finish() -> None:
                self._open_future = None
                self._handle_open_result(result)

            QTimer.singleShot(0, finish)

        if hasattr(future, "add_done_callback"):
            future.add_done_callback(handle_result)
            if self._register_cleanup and hasattr(future, "cancel"):
                self._register_cleanup(lambda fut=future: fut.cancel())
        else:
            handle_result(type("_Immediate", (), {"result": lambda self: future})())

    def _open_summary_work(self) -> dict[str, Any]:
        from playbalance.playoffs import load_bracket
        from utils.path_utils import get_base_dir
        from pathlib import Path
        import os
        import sys
        import subprocess

        path = self._last_summary_path
        if not path:
            bracket = load_bracket()
            if not bracket:
                return {"status": "error", "message": "No playoff bracket available."}
            out = Path(get_base_dir()) / "data" / f"playoffs_summary_{getattr(bracket, 'year', '')}.md"
            if not out.exists():
                export_result = self._export_summary_work()
                if export_result.get("status") != "success":
                    return export_result
                path = export_result.get("path")
            else:
                path = str(out)
        target = Path(path)
        if not target.exists():
            return {"status": "error", "message": "Summary file does not exist."}
        try:
            if os.name == "nt":
                try:
                    os.startfile(str(target))  # type: ignore[attr-defined]
                except Exception:
                    subprocess.Popen(["cmd", "/c", "start", "", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            return {"status": "error", "message": f"Unable to open summary: {exc}"}
        return {"status": "success", "message": f"Opened summary at {target}", "path": str(target)}

    def _handle_open_result(self, result: dict[str, Any]) -> None:
        status = result.get("status", "error")
        message = result.get("message", "")
        path = result.get("path")
        if status != "success":
            retry = False
            try:
                btn = QMessageBox.question(
                    self,
                    "Open Summary",
                    message or "Failed to open summary. Retry?",
                    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Close,
                    QMessageBox.StandardButton.Retry,
                )
                retry = btn == QMessageBox.StandardButton.Retry
            except Exception:
                if message:
                    QMessageBox.warning(self, "Open Summary", message)
            if self._show_toast:
                self._show_toast("error", message or "Failed to open summary.")
            if retry:
                self._open_summary()
            return
        if path:
            self._last_summary_path = path
        if self._show_toast:
            self._show_toast("success", message or "Opened summary.")


__all__ = ["PlayoffsWindow"]


