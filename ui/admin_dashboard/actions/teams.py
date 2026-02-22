"""Team management actions for the admin dashboard."""
from __future__ import annotations

import csv
import time
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from utils.lineup_autofill import auto_fill_lineup_for_team
from utils.path_utils import get_data_dir
from utils.pitcher_role import get_role
from utils.pitching_autofill import autofill_pitching_staff
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.team_loader import load_teams
from utils.roster_validation import missing_positions
from services.roster_auto_assign import auto_assign_all_teams

from ..context import DashboardContext


class _UiDispatcher(QObject):
    """Thread-safe bridge to queue callables on the GUI thread."""

    trigger = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.trigger.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, callback: object) -> None:
        try:
            if callable(callback):
                callback()
        except Exception:
            pass


_DISPATCHER = _UiDispatcher()


def _schedule(callback) -> None:
    app = QApplication.instance()
    if app is None:
        if callable(callback):
            callback()
        return
    _DISPATCHER.trigger.emit(callback)


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def set_all_lineups(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Auto-fill batting orders for every team in the current league."""

    data_dir = get_data_dir()
    teams = load_teams(data_dir / "teams.csv")
    errors: list[str] = []
    for team in teams:
        try:
            auto_fill_lineup_for_team(
                team.team_id,
                players_file=data_dir / "players.csv",
                roster_dir=data_dir / "rosters",
                lineup_dir=data_dir / "lineups",
            )
        except Exception as exc:
            errors.append(f"{team.team_id}: {exc}")

    if parent is None:
        return

    if errors:
        QMessageBox.warning(
            parent,
            "Lineups Set (with issues)",
            "Some lineups could not be auto-filled:\n" + "\n".join(errors),
        )
    else:
        QMessageBox.information(parent, "Lineups Set", "Lineups auto-filled for all teams.")


def set_all_pitching_roles(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Assign pitching roles for all clubs based on current rosters."""

    data_dir = get_data_dir()
    players_file = data_dir / "players.csv"
    if not players_file.exists():
        if parent is not None:
            QMessageBox.warning(parent, "Error", "Players file not found.")
        return

    players = {}
    with players_file.open("r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            player_id = row.get("player_id", "").strip()
            players[player_id] = {
                "primary_position": row.get("primary_position", "").strip(),
                "role": row.get("role", "").strip(),
                "endurance": row.get("endurance", ""),
                "preferred_pitching_role": (row.get("preferred_pitching_role") or "").strip(),
            }

    teams = load_teams(data_dir / "teams.csv")
    for team in teams:
        try:
            roster = load_roster(team.team_id)
        except FileNotFoundError:
            continue
        available = [
            (pid, players[pid])
            for pid in roster.act
            if pid in players and get_role(players[pid])
        ]
        assignments = autofill_pitching_staff(available)
        path = data_dir / "rosters" / f"{team.team_id}_pitching.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists():
                try:
                    path.chmod(0o644)
                except OSError:
                    pass
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                for role, player_id in assignments.items():
                    writer.writerow([player_id, role])
        except PermissionError as exc:
            if parent is not None:
                QMessageBox.warning(
                    parent,
                    "Permission Denied",
                    f"Cannot write pitching roles to {path}.\n{exc}",
                )
            return

    if parent is not None:
        QMessageBox.information(
            parent,
            "Pitching Staff Set",
            "Pitching roles auto-filled for all teams.",
        )


def auto_reassign_rosters(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Reassign players across roster levels for all teams."""

    progress_state: dict[str, object] = {
        "phase": "Loading",
        "done": 0,
        "total": 0,
        "started": time.perf_counter(),
    }

    def _set_phase(phase: str, done: int | None = None, total: int | None = None) -> None:
        progress_state["phase"] = str(phase or "Processing")
        if done is not None:
            progress_state["done"] = max(0, int(done))
        if total is not None:
            progress_state["total"] = max(0, int(total))

    def _update_progress_label() -> None:
        if progress_dialog is None:
            return
        phase = str(progress_state.get("phase") or "Processing")
        done = int(progress_state.get("done") or 0)
        total = int(progress_state.get("total") or 0)
        elapsed = _format_elapsed(time.perf_counter() - float(progress_state["started"]))
        if total > 0:
            clamped_done = max(0, min(done, total))
            if progress_dialog.minimum() != 0 or progress_dialog.maximum() != total:
                progress_dialog.setRange(0, total)
            progress_dialog.setValue(clamped_done)
            progress_dialog.setLabelText(
                f"{phase} ({clamped_done}/{total})...\nElapsed: {elapsed}"
            )
            return
        if progress_dialog.minimum() != 0 or progress_dialog.maximum() != 0:
            progress_dialog.setRange(0, 0)
        progress_dialog.setValue(0)
        progress_dialog.setLabelText(f"{phase}...\nElapsed: {elapsed}")

    progress_dialog = None
    progress_tick = None
    if parent is not None:
        try:
            from PyQt6.QtWidgets import QProgressDialog

            progress_dialog = QProgressDialog(
                "Auto reassigning rosters for all teams...",
                None,
                0,
                0,
                parent,
            )
            progress_dialog.setWindowTitle("Auto Reassign Rosters")
            progress_dialog.setCancelButton(None)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setAutoClose(False)
            progress_dialog.setAutoReset(False)
            progress_dialog.setValue(0)
            progress_dialog.show()
            _update_progress_label()
            progress_tick = QTimer()
            progress_tick.setInterval(200)
            progress_tick.timeout.connect(_update_progress_label)
            progress_tick.start()
        except Exception:
            progress_dialog = None
            progress_tick = None

    if context.show_toast:
        context.show_toast("info", "Auto-reassigning rosters in background...")

    def worker() -> dict[str, object]:
        try:
            _set_phase("Loading")
            auto_assign_all_teams(progress_callback=_set_phase)
            _set_phase(
                "Validating",
                done=int(progress_state.get("total") or 0),
                total=int(progress_state.get("total") or 0),
            )
            data_dir = get_data_dir()
            players = {
                p.player_id: p for p in load_players_from_csv(data_dir / "players.csv")
            }
            teams = load_teams(data_dir / "teams.csv")
            issues: list[str] = []
            for team in teams:
                try:
                    roster = load_roster(team.team_id)
                except FileNotFoundError:
                    continue
                missing = missing_positions(roster, players)
                if missing:
                    issues.append(f"{team.team_id}: {', '.join(missing)}")
            _set_phase(
                "Complete",
                done=int(progress_state.get("total") or 0),
                total=int(progress_state.get("total") or 0),
            )
            return {"status": "success", "issues": issues}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def finish(payload: dict[str, object]) -> None:
        if progress_tick is not None:
            try:
                progress_tick.stop()
            except Exception:
                pass
        if progress_dialog is not None:
            try:
                progress_dialog.close()
            except Exception:
                pass
        status = payload.get("status")
        if status != "success":
            message = str(payload.get("message") or "Auto reassign failed.")
            if parent is not None:
                QMessageBox.warning(parent, "Auto Reassign Failed", message)
            if context.show_toast:
                context.show_toast("error", message)
            return

        issues = payload.get("issues") or []
        if parent is not None:
            if issues:
                QMessageBox.warning(
                    parent,
                    "Coverage Warnings",
                    "Some teams lack defensive coverage on the Active roster:\n"
                    + "\n".join(str(item) for item in issues),
                )
            else:
                QMessageBox.information(
                    parent,
                    "Rosters Updated",
                    "Auto reassigned rosters for all teams.",
                )
        if context.show_toast:
            context.show_toast("success", "Auto reassign completed.")

    future = context.run_async(worker)

    def handle_result(result_future) -> None:
        try:
            payload = result_future.result()
        except Exception as exc:
            payload = {"status": "error", "message": str(exc)}
        _schedule(lambda: finish(payload))

    if hasattr(future, "add_done_callback"):
        future.add_done_callback(handle_result)
        if context.register_cleanup and hasattr(future, "cancel"):
            context.register_cleanup(lambda fut=future: fut.cancel())
    else:
        if hasattr(future, "result"):
            handle_result(future)
        else:
            class _Immediate:
                def __init__(self, value):
                    self._value = value

                def result(self):
                    return self._value

            handle_result(_Immediate(future))


__all__ = [
    "auto_reassign_rosters",
    "set_all_lineups",
    "set_all_pitching_roles",
]
