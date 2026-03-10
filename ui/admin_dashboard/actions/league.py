"""League lifecycle actions for the admin dashboard."""
from __future__ import annotations

import csv
import json
import shutil
import time
from threading import Lock
from datetime import date
from typing import Callable, Iterable, Optional, Tuple

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QWidget,
    QProgressDialog,
)

try:  # PyQt6.sip is optional depending on packaging
    from PyQt6 import sip
except Exception:  # pragma: no cover - defensive import
    sip = None  # type: ignore

from playbalance.league_creator import create_league, MAX_LEAGUE_TEAMS
from playbalance.season_context import slugify_league_id
from playbalance.schedule_generator import save_schedule
from playbalance.season_manager import SeasonManager, SeasonPhase

from services import league_registry
from ui.team_entry_dialog import TeamEntryDialog
from ui.league_preset_dialogs import (
    LeagueSetupChoiceDialog,
    select_quickstart_preset,
    select_rule_preset,
    select_schedule_template,
)
from ui.window_utils import ensure_on_top
from utils.news_logger import log_news_event
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from services.players_repository import save_players
from utils.roster_loader import load_roster, save_roster
from services.injury_manager import recover_from_injury
from utils.pitcher_recovery import PitcherRecoveryTracker
from utils.stats_persistence import reset_stats
from utils.team_loader import load_teams
from services.standings_repository import save_standings
from services.transaction_log import clear_transactions as clear_transaction_log
from services.league_presets import (
    apply_rule_preset,
    build_quickstart_structure,
    generate_schedule_from_template,
    get_quickstart_preset,
    get_rule_preset,
    get_schedule_template,
    record_league_metadata,
)
from services.trade_settings import (
    CPU_PROPOSAL_CADENCE_VALUES,
    MAX_ALLOWED_PICK_TRADE_YEARS,
    MIN_ALLOWED_PICK_TRADE_YEARS,
    update_trade_settings,
)
from services.league_creation_finance import (
    apply_initial_finance_settings,
    finance_summary_lines,
)
from utils.league_settings import configure_league_settings
from ui.league_creation_finance_dialog import LeagueCreationFinanceDialog

from ..context import DashboardContext

AfterCallback = Optional[Callable[[], None]]


def _schedule(callback: Callable[[], None]) -> None:
    QTimer.singleShot(0, callback)


def _alive_widget(widget: Optional[QWidget]) -> Optional[QWidget]:
    """Return *widget* when still valid, otherwise ``None``."""

    if widget is None:
        return None
    if sip is not None:
        try:
            if sip.isdeleted(widget):  # type: ignore[attr-defined]
                return None
        except Exception:
            pass
    return widget


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


class _ProgressPhaseTracker:
    """Thread-safe phase holder used by long-running worker actions."""

    def __init__(self, initial_phase: str = "Loading") -> None:
        self._phase = str(initial_phase or "Loading")
        self._lock = Lock()

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = str(phase or "Processing")

    def get_phase(self) -> str:
        with self._lock:
            return self._phase


def _run_with_progress_dialog(
    context: DashboardContext,
    parent: Optional[QWidget],
    *,
    title: str,
    label: str,
    worker: Callable[[], object],
    phase_getter: Callable[[], str] | None = None,
) -> object:
    """Run *worker* and keep the UI responsive while showing progress."""

    progress_dialog: Optional[QProgressDialog] = None
    started = time.perf_counter()

    def _refresh_label() -> None:
        if progress_dialog is None:
            return
        phase_text = ""
        if phase_getter is not None:
            try:
                phase_text = str(phase_getter() or "").strip()
            except Exception:
                phase_text = ""
        elapsed_text = _format_elapsed(time.perf_counter() - started)
        if phase_text:
            progress_dialog.setLabelText(f"{phase_text}...\nElapsed: {elapsed_text}")
            return
        progress_dialog.setLabelText(f"{label}\nElapsed: {elapsed_text}")

    if parent is not None:
        try:
            progress_dialog = QProgressDialog(label, None, 0, 0, parent)
            progress_dialog.setWindowTitle(title)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setAutoClose(False)
            progress_dialog.setAutoReset(False)
            progress_dialog.setCancelButton(None)
            progress_dialog.show()
            _refresh_label()
        except Exception:
            progress_dialog = None

    try:
        future = context.run_async(worker)
        if hasattr(future, "done") and hasattr(future, "result"):
            app = QApplication.instance()
            while True:
                try:
                    if future.done():
                        break
                except Exception:
                    break
                if app is not None:
                    try:
                        _refresh_label()
                        app.processEvents()
                    except Exception:
                        pass
                time.sleep(0.02)
            return future.result()
        if hasattr(future, "result"):
            return future.result()
        return future
    finally:
        if progress_dialog is not None:
            try:
                progress_dialog.close()
            except Exception:
                pass


def _build_creation_confirmation_message(
    *,
    league_name: str,
    league_mode: str,
    team_count: int,
    setup_lines: list[str],
    trade_lines: list[str],
    finance_lines: list[str],
) -> str:
    lines = [
        "Review League Setup",
        "",
        f"League name: {league_name}",
        f"League mode: {league_mode}",
        f"Teams: {team_count}",
    ]
    if setup_lines:
        lines.extend([""] + setup_lines)
    if trade_lines:
        lines.extend(["", "Trade Policy:"] + [f"- {line}" for line in trade_lines])
    if finance_lines:
        lines.extend(["", "Finance Setup:"] + [f"- {line}" for line in finance_lines])
    lines.extend(["", "Create league now?"])
    return "\n".join(lines)


def create_league_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
    refresh_callbacks: Iterable[Callable[[], None]] | None = None,
    show_draft_settings_reminder: bool = True,
) -> None:
    """Launch the guided dialog flow for creating a new league."""

    if parent is None:
        return

    setup_dialog = LeagueSetupChoiceDialog(parent)
    if setup_dialog.exec() != QDialog.DialogCode.Accepted:
        return
    setup_choice = setup_dialog.choice or "custom"

    league_name, ok = QInputDialog.getText(parent, "League Name", "Enter league name:")
    if not ok or not league_name:
        return
    league_name = league_name.strip()
    league_id = slugify_league_id(league_name)
    existing_league = league_registry.get_league(league_id)

    if existing_league is not None:
        overwrite = QMessageBox.question(
            parent,
            "Overwrite Existing League?",
            (
                f'League "{existing_league.display_name}" already exists '
                f'(ID: {league_id}).\n\n'
                "Creating this league will overwrite that league's data. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if overwrite != QMessageBox.StandardButton.Yes:
            return

    owner_league = False
    commissioner_password: str | None = None
    owner_choice = QMessageBox.question(
        parent,
        "Owner League?",
        "Is this a multi-owner league? (Requires commissioner password for admin actions)",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if owner_choice == QMessageBox.StandardButton.Yes:
        owner_league = True
        password, ok = QInputDialog.getText(
            parent,
            "Commissioner Password",
            "Set commissioner password:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        password = password.strip()
        if not password:
            QMessageBox.warning(
                parent,
                "Commissioner Password",
                "Commissioner password is required for owner leagues.",
            )
            return
        confirm, ok = QInputDialog.getText(
            parent,
            "Confirm Password",
            "Confirm commissioner password:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        if password != confirm.strip():
            QMessageBox.warning(
                parent,
                "Commissioner Password",
                "Passwords do not match.",
            )
            return
        commissioner_password = password

    # Trade configuration defaults for the new league.
    trades_enabled = True
    draft_pick_trading_enabled = False
    require_commissioner_approval = False
    cpu_initiated_trades_enabled = True
    cpu_proposal_cadence = "normal"
    max_pick_trade_years = 3

    trades_choice = QMessageBox.question(
        parent,
        "Enable Trading?",
        "Enable team-to-team trading for this league?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if trades_choice != QMessageBox.StandardButton.Yes:
        trades_enabled = False

    if trades_enabled:
        pick_choice = QMessageBox.question(
            parent,
            "Draft Pick Trading?",
            "Allow teams to include draft picks in trades?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        draft_pick_trading_enabled = pick_choice == QMessageBox.StandardButton.Yes
        if draft_pick_trading_enabled:
            max_years, ok = QInputDialog.getInt(
                parent,
                "Draft Pick Trade Window",
                "Maximum years out for tradable draft picks:",
                max_pick_trade_years,
                MIN_ALLOWED_PICK_TRADE_YEARS,
                MAX_ALLOWED_PICK_TRADE_YEARS,
            )
            if not ok:
                return
            max_pick_trade_years = int(max_years)

        approval_default = (
            QMessageBox.StandardButton.Yes
            if owner_league
            else QMessageBox.StandardButton.No
        )
        approval_choice = QMessageBox.question(
            parent,
            "Commissioner Trade Approval?",
            "Require commissioner approval before accepted trades execute?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            approval_default,
        )
        require_commissioner_approval = (
            approval_choice == QMessageBox.StandardButton.Yes
        )

        cpu_trades_choice = QMessageBox.question(
            parent,
            "CPU-Initiated Trades?",
            (
                "Allow CPU teams to send counter-offers and initiate trade "
                "proposals to owners?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        cpu_initiated_trades_enabled = (
            cpu_trades_choice == QMessageBox.StandardButton.Yes
        )
        if cpu_initiated_trades_enabled:
            cadence_items = ["Off", "Low", "Normal", "High"]
            cadence_choice, ok = QInputDialog.getItem(
                parent,
                "CPU Trade Proposal Cadence",
                "CPU proactive trade proposal cadence:",
                cadence_items,
                cadence_items.index("Normal"),
                False,
            )
            if not ok:
                return
            cadence_token = str(cadence_choice or "Normal").strip().lower()
            if cadence_token not in CPU_PROPOSAL_CADENCE_VALUES:
                cadence_token = "normal"
            cpu_proposal_cadence = cadence_token

    setup_summary_lines: list[str] = []
    if setup_choice == "quickstart":
        quickstart_id = select_quickstart_preset(parent)
        if not quickstart_id:
            return
        preset = get_quickstart_preset(quickstart_id)
        if preset is None:
            QMessageBox.warning(parent, "Preset Error", "Unable to load quick-start preset.")
            return
        default_schedule_id = preset.schedule_template_id or "mlb_162"
        chosen_schedule_id = select_schedule_template(
            parent,
            default_id=default_schedule_id,
        )
        if not chosen_schedule_id:
            return
        total_teams = len(preset.divisions) * preset.teams_per_division
        rule_preset = get_rule_preset(preset.rule_preset_id)
        schedule_template = get_schedule_template(chosen_schedule_id)
        rule_label = (
            rule_preset.name
            if rule_preset is not None
            else preset.rule_preset_id or "None"
        )
        schedule_label = (
            schedule_template.name
            if schedule_template is not None
            else chosen_schedule_id or "None"
        )
        setup_summary_lines = [
            f"Setup mode: Quick-Start ({preset.name})",
            f"Divisions: {', '.join(preset.divisions)}",
            f"Rule preset: {rule_label}",
            f"Schedule template: {schedule_label}",
        ]
        summary_lines = [
            f"League name: {league_name}",
            f"Quick-Start preset: {preset.name}",
            f"Teams: {total_teams} ({preset.teams_per_division} per division)",
            "Divisions: " + ", ".join(preset.divisions),
            f"Rule preset: {rule_label}",
            f"Schedule template: {schedule_label}",
            "",
            "Continue?",
        ]
        confirm = QMessageBox.question(
            parent,
            "Confirm Quick-Start Setup",
            "\n".join(summary_lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            structure = build_quickstart_structure(preset)
        except ValueError as exc:
            QMessageBox.warning(parent, "Preset Error", str(exc))
            return
    else:
        div_text, ok = QInputDialog.getText(
            parent,
            "Divisions",
            "Enter division names separated by commas:",
        )
        if not ok or not div_text:
            return

        divisions = [d.strip() for d in div_text.split(",") if d.strip()]
        if not divisions:
            return

        teams_per_div, ok = QInputDialog.getInt(
            parent,
            "Teams",
            "Teams per division:",
            2,
            1,
            20,
        )
        if not ok:
            return
        total_teams = len(divisions) * teams_per_div
        if total_teams > MAX_LEAGUE_TEAMS:
            QMessageBox.warning(
                parent,
                "Too Many Teams",
                (
                    f"This setup would create {total_teams} teams, but the current limit "
                    f"is {MAX_LEAGUE_TEAMS}. Reduce divisions or teams per division."
                ),
            )
            return

        dialog = TeamEntryDialog(divisions, teams_per_div, parent)
        ensure_on_top(dialog)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        structure = dialog.get_structure()
        setup_summary_lines = [
            "Setup mode: Custom",
            "Divisions: " + ", ".join(divisions),
            f"Teams per division: {teams_per_div}",
        ]

    finance_dialog = LeagueCreationFinanceDialog(parent)
    ensure_on_top(finance_dialog)
    if finance_dialog.exec() != QDialog.DialogCode.Accepted:
        return
    finance_config = finance_dialog.get_selection()

    trade_summary_lines = [
        f"Trading enabled: {'Yes' if trades_enabled else 'No'}",
        (
            f"Draft-pick trading: {'Yes' if draft_pick_trading_enabled else 'No'}"
            if trades_enabled
            else "Draft-pick trading: No"
        ),
        (
            f"Commissioner trade approval: {'Yes' if require_commissioner_approval else 'No'}"
            if trades_enabled
            else "Commissioner trade approval: No"
        ),
        (
            f"CPU-initiated trade offers: {'Yes' if cpu_initiated_trades_enabled else 'No'}"
            if trades_enabled
            else "CPU-initiated trade offers: No"
        ),
        (
            f"CPU proactive proposal cadence: {cpu_proposal_cadence.title()}"
            if trades_enabled and cpu_initiated_trades_enabled
            else "CPU proactive proposal cadence: Off"
        ),
    ]
    if trades_enabled and draft_pick_trading_enabled:
        trade_summary_lines.append(
            f"Max draft-pick trade years: {max_pick_trade_years}"
        )

    mode_label = "Multi-owner" if owner_league else "Single-player"
    confirmation = _build_creation_confirmation_message(
        league_name=league_name,
        league_mode=mode_label,
        team_count=total_teams,
        setup_lines=setup_summary_lines,
        trade_lines=trade_summary_lines,
        finance_lines=finance_summary_lines(finance_config),
    )
    final_confirm = QMessageBox.question(
        parent,
        "Confirm League Creation",
        confirmation,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if final_confirm != QMessageBox.StandardButton.Yes:
        return

    target_data_dir = league_registry.get_league_data_dir(league_id, create=True)
    phase_tracker = _ProgressPhaseTracker("Loading")

    def _create_worker() -> None:
        create_league(
            str(target_data_dir),
            structure,
            league_name,
            progress_callback=phase_tracker.set_phase,
        )

    try:
        _run_with_progress_dialog(
            context,
            parent,
            title="Creating League",
            label=f'Creating league "{league_name}"...',
            worker=_create_worker,
            phase_getter=phase_tracker.get_phase,
        )
    except ValueError as exc:
        QMessageBox.warning(parent, "League Size Error", str(exc))
        return
    except OSError as exc:
        QMessageBox.critical(parent, "Error", f"Failed to create league data: {exc}")
        return
    except Exception as exc:
        QMessageBox.critical(parent, "Error", f"Failed to create league: {exc}")
        return

    league_mode = "owner_league" if owner_league else "single_player"
    try:
        if existing_league is None:
            league_registry.register_league(
                league_id,
                display_name=league_name,
                mode=league_mode,
                status="active",
            )
        else:
            league_registry.update_league(
                league_id,
                display_name=league_name,
                mode=league_mode,
                status="active",
            )
        league_registry.set_active_league(league_id, ensure_data_dir=True)
    except Exception as exc:
        QMessageBox.warning(
            parent,
            "League Registry",
            f"League data was created, but registry update failed: {exc}",
        )
        return

    rule_preset_id: Optional[str] = None
    schedule_template_id: Optional[str] = None
    quickstart_id: Optional[str] = None

    if setup_choice == "quickstart":
        quickstart_id = preset.preset_id if preset is not None else None
        rule_preset_id = preset.rule_preset_id if preset is not None else None
        schedule_template_id = chosen_schedule_id if preset is not None else None
        if rule_preset_id:
            apply_rule_preset(rule_preset_id)
    else:
        chosen_rule = select_rule_preset(parent, include_none=True)
        if chosen_rule and chosen_rule != "__none__":
            rule_preset_id = chosen_rule
            apply_rule_preset(chosen_rule)

        chosen_schedule = select_schedule_template(parent, default_id="mlb_162")
        if chosen_schedule:
            schedule_template_id = chosen_schedule

    try:
        record_league_metadata(
            quickstart_preset_id=quickstart_id,
            rule_preset_id=rule_preset_id,
            schedule_template_id=schedule_template_id,
        )
    except Exception:
        pass

    try:
        configure_league_settings(
            mode=league_mode,
            commissioner_password=commissioner_password,
            path=target_data_dir / "league_settings.json",
        )
    except Exception as exc:
        QMessageBox.warning(
            parent,
            "League Settings",
            f"Unable to save league settings: {exc}",
        )

    try:
        update_trade_settings(
            trades_enabled=trades_enabled,
            draft_pick_trading_enabled=draft_pick_trading_enabled,
            require_commissioner_approval=require_commissioner_approval,
            cpu_initiated_trades_enabled=cpu_initiated_trades_enabled,
            cpu_proposal_cadence=cpu_proposal_cadence,
            max_pick_trade_years=max_pick_trade_years,
            path=target_data_dir / "trade_settings.json",
            league_id=league_id,
        )
    except Exception as exc:
        QMessageBox.warning(
            parent,
            "Trade Settings",
            f"Unable to save trade settings: {exc}",
        )

    try:
        apply_initial_finance_settings(
            finance_config,
            data_dir=target_data_dir,
            league_id=league_id,
        )
    except Exception as exc:
        QMessageBox.warning(
            parent,
            "Financial Settings",
            f"Unable to save initial finance settings: {exc}",
        )

    QMessageBox.information(
        parent,
        "League Created",
        (
            f'League "{league_name}" was created and set as active.\n'
            "Restart the app if open windows still show data from the previous league."
        ),
    )
    if show_draft_settings_reminder:
        try:
            reminder = QMessageBox(parent)
            reminder.setWindowTitle("Draft Settings Reminder")
            reminder.setIcon(QMessageBox.Icon.Information)
            reminder.setText(
                "Before the season starts, review Draft Settings (rounds, pool size, seed)."
            )
            open_btn = reminder.addButton(
                "Open Draft Settings", QMessageBox.ButtonRole.ActionRole
            )
            reminder.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
            reminder.exec()
            if reminder.clickedButton() == open_btn:
                open_settings = getattr(parent, "open_draft_settings", None)
                if callable(open_settings):
                    open_settings()
        except Exception:
            pass
    for callback in refresh_callbacks or ():
        try:
            callback()
        except Exception:
            pass



def reset_season_to_opening_day(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
    after_reset: AfterCallback = None,
) -> None:
    """Reset season progress, standings, and supporting data asynchronously."""

    if parent is None:
        return

    confirm = QMessageBox.question(
        parent,
        "Reset to Opening Day",
        (
            "This will clear all regular-season results and standings, "
            "and rewind the season to Opening Day. Continue?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return

    data_root = get_data_dir()
    sched = data_root / "schedule.csv"
    purge_box = (
        QMessageBox.question(
            parent,
            "Purge Boxscores?",
            "Also delete saved season boxscores (data/boxscores/season)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )
    clear_news = (
        QMessageBox.question(
            parent,
            "Clear News Feed?",
            "Also purge league news history (data/news_feed.txt and data/news_feed.jsonl)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )
    clear_transactions = (
        QMessageBox.question(
            parent,
            "Clear Transactions Log?",
            "Also delete recorded transactions (data/transactions.csv)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )

    if not sched.exists():
        QMessageBox.warning(
            parent,
            "No Schedule",
            "Cannot reset: schedule.csv not found. Generate a schedule first.",
        )
        return

    progress_dialog: Optional[QProgressDialog] = None
    try:
        progress_dialog = QProgressDialog("Resetting league...", None, 0, 0, parent)
        progress_dialog.setWindowTitle("Resetting League")
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setCancelButton(None)
        try:
            from PyQt6.QtCore import Qt as _Qt

            if hasattr(_Qt, "WindowModality"):
                progress_dialog.setWindowModality(_Qt.WindowModality.NonModal)
        except Exception:
            pass
        progress_dialog.show()
    except Exception:
        progress_dialog = None

    if context.show_toast:
        context.show_toast("info", "Resetting league in background...")

    def worker() -> Tuple[str, str]:
        progress = data_root / "season_progress.json"
        stats_file = data_root / "season_stats.json"
        history_dir = data_root / "season_history"
        notes: list[str] = []

        try:
            rows: list[dict[str, str]] = []
            with sched.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for record in reader:
                    record = dict(record)
                    record["result"] = ""
                    record["played"] = ""
                    record["boxscore"] = ""
                    rows.append(record)
        except Exception as exc:
            raise RuntimeError(f"Failed reading schedule: {exc}") from exc

        try:
            fieldnames = ["date", "home", "away", "result", "played", "boxscore"]
            with sched.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for record in rows:
                    writer.writerow({
                        "date": record.get("date", ""),
                        "home": record.get("home", ""),
                        "away": record.get("away", ""),
                        "result": record.get("result", ""),
                        "played": record.get("played", ""),
                        "boxscore": record.get("boxscore", ""),
                    })
        except Exception as exc:
            raise RuntimeError(f"Failed rewriting schedule: {exc}") from exc

        first_year: Optional[int] = None
        try:
            if rows:
                first = rows[0]
                if first.get("date"):
                    first_year = int(str(first["date"]).split("-")[0])
        except Exception:
            first_year = None

        try:
            data = {
                "preseason_done": {
                    "free_agency": True,
                    "training_camp": True,
                    "schedule": True,
                },
                "sim_index": 0,
                "playoffs_done": False,
            }
            if progress.exists():
                try:
                    current = json.loads(progress.read_text(encoding="utf-8"))
                    completed = set(current.get("draft_completed_years", []))
                    if first_year is not None and first_year in completed:
                        completed.discard(first_year)
                    if completed:
                        data["draft_completed_years"] = sorted(completed)
                except Exception:
                    pass
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(f"Failed resetting progress: {exc}") from exc

        try:
            save_standings({})
        except Exception:
            pass

        try:
            reset_stats(stats_file)
        except Exception as exc:
            notes.append(f"Failed resetting season stats: {exc}")
        try:
            if history_dir.exists():
                shutil.rmtree(history_dir)
        except Exception as exc:
            notes.append(f"Failed clearing season history: {exc}")

        try:
            if first_year is not None:
                draft_files = [
                    f"draft_pool_{first_year}.json",
                    f"draft_pool_{first_year}.csv",
                    f"draft_state_{first_year}.json",
                    f"draft_results_{first_year}.csv",
                ]
                for name in draft_files:
                    target = data_root / name
                    try:
                        lock = target.with_suffix(target.suffix + ".lock")
                        if lock.exists():
                            lock.unlink()
                    except Exception:
                        pass
                    if target.exists():
                        try:
                            target.unlink()
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            playoff_candidates = [data_root / "playoffs.json"]
            if first_year is not None:
                playoff_candidates.append(data_root / f"playoffs_{first_year}.json")
            try:
                playoff_candidates.extend(data_root.glob("playoffs_*.json"))
            except Exception:
                pass
            for candidate in playoff_candidates:
                try:
                    if candidate.exists():
                        bak = candidate.with_suffix(candidate.suffix + ".bak")
                        lock = candidate.with_suffix(candidate.suffix + ".lock")
                        if lock.exists():
                            lock.unlink()
                        if bak.exists():
                            bak.unlink()
                        candidate.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            for candidate in data_root.glob("playoffs_summary_*.md"):
                try:
                    if candidate.exists():
                        candidate.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            players_path = data_root / "players.csv"
            players = list(load_players_from_csv(players_path))
            players_by_id = {}
            if players:
                for player in players:
                    player.injured = False
                    player.injury_description = None
                    player.return_date = None
                    player.injury_list = None
                    player.injury_start_date = None
                    player.injury_minimum_days = None
                    player.injury_eligible_date = None
                    player.injury_rehab_assignment = None
                    player.injury_rehab_days = 0
                    if hasattr(player, "ready"):
                        player.ready = True
                players_by_id = {player.player_id: player for player in players}
                save_players(players, players_path)
            roster_dir = data_root / "rosters"
            if roster_dir.exists():
                for roster_file in roster_dir.glob("*.csv"):
                    team_id = roster_file.stem
                    try:
                        roster = load_roster(team_id, roster_dir)
                    except Exception:
                        continue
                    changed = False
                    injured_ids = list(getattr(roster, "dl", []) or []) + list(getattr(roster, "ir", []) or [])
                    for pid in injured_ids:
                        player = players_by_id.get(pid)
                        if player is None:
                            if pid in roster.dl:
                                roster.dl.remove(pid)
                                changed = True
                            if pid in roster.ir:
                                roster.ir.remove(pid)
                                changed = True
                            roster.dl_tiers.pop(pid, None)
                            continue
                        try:
                            recover_from_injury(player, roster, destination="act", force=True)
                            changed = True
                        except Exception:
                            if pid in roster.dl:
                                roster.dl.remove(pid)
                                changed = True
                            if pid in roster.ir:
                                roster.ir.remove(pid)
                                changed = True
                            roster.dl_tiers.pop(pid, None)
                    if changed:
                        roster.promote_replacements()
                        save_roster(team_id, roster)
                        try:
                            load_roster.cache_clear(team_id, roster_dir)  # type: ignore[attr-defined]
                        except Exception:
                            pass
        except Exception as exc:
            notes.append(f"Failed clearing injuries: {exc}")

        try:
            manager = SeasonManager()
            manager.phase = SeasonPhase.REGULAR_SEASON
            manager.save()
            try:
                manager.finalize_rosters()
            except Exception:
                pass
        except Exception as exc:
            notes.append(f"State updated, but failed setting phase: {exc}")

        try:
            tracker = PitcherRecoveryTracker.instance()
            tracker.reset()
        except Exception as exc:
            notes.append(f"Failed resetting pitcher recovery data: {exc}")

        logged_reset_event = not clear_news
        if logged_reset_event:
            try:
                log_news_event("League reset to Opening Day")
            except Exception:
                pass

        if purge_box:
            try:
                box_dir = data_root / "boxscores" / "season"
                if box_dir.exists():
                    shutil.rmtree(box_dir)
                log_news_event("Purged saved season boxscores")
            except Exception as exc:
                notes.append(f"Boxscore purge failed: {exc}")

        news_cleared = False
        if clear_news:
            try:
                news_txt = data_root / "news_feed.txt"
                news_json = data_root / "news_feed.jsonl"
                for path in (news_txt, news_json):
                    if path.exists():
                        path.unlink()
                news_cleared = True
            except Exception as exc:
                notes.append(f"News feed purge failed: {exc}")

        transactions_cleared = False
        if clear_transactions:
            try:
                clear_transaction_log(path=data_root / "transactions.csv")
                transactions_cleared = True
            except Exception as exc:
                notes.append(f"Transactions purge failed: {exc}")

        message = "League reset to Opening Day."
        if purge_box:
            message += " Season boxscores purged."
        if news_cleared:
            message += " News feed cleared."
        if transactions_cleared:
            message += " Transactions log cleared."
        if notes:
            message += " " + " ".join(notes)
        return "success", message

    def handle_result(result_future) -> None:
        try:
            kind, message = result_future.result()
        except Exception as exc:
            kind, message = "error", str(exc)

        def finish() -> None:
            if progress_dialog is not None:
                try:
                    progress_dialog.close()
                except Exception:
                    pass
            dialog_parent = _alive_widget(parent)
            if dialog_parent is not None:
                if kind == "success":
                    QMessageBox.information(dialog_parent, "Reset Complete", message)
                else:
                    QMessageBox.warning(dialog_parent, "Reset Failed", message)
            if context.show_toast:
                toast_kind = "success" if kind == "success" else "error"
                context.show_toast(toast_kind, message)
            if kind == "success" and after_reset is not None:
                try:
                    after_reset()
                except Exception:
                    pass

        _schedule(finish)

    future = context.run_async(worker)
    if hasattr(future, "add_done_callback"):
        future.add_done_callback(handle_result)
        if context.register_cleanup and hasattr(future, "cancel"):
            context.register_cleanup(lambda fut=future: fut.cancel())
    else:
        try:
            result = worker()
        except Exception as exc:
            result = ("error", str(exc))
        class _Immediate:
            def __init__(self, value):
                self._value = value
            def result(self):
                return self._value
        handle_result(_Immediate(result))


def regenerate_schedule_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Generate a fresh regular-season schedule and overwrite schedule.csv."""

    if parent is None:
        return

    confirm = QMessageBox.question(
        parent,
        "Regenerate Regular Season Schedule",
        (
            "This will overwrite the existing regular-season schedule and clear "
            "any recorded results. Continue?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return

    data_root = get_data_dir()
    teams_path = data_root / "teams.csv"
    try:
        teams = [team.team_id for team in load_teams(teams_path)]
    except Exception as exc:
        QMessageBox.critical(
            parent,
            "Unable to Load Teams",
            f"Failed reading teams from {teams_path}:\n{exc}",
        )
        return

    if not teams:
        QMessageBox.warning(parent, "No Teams", "No teams found to schedule.")
        return
    if len(teams) > MAX_LEAGUE_TEAMS:
        QMessageBox.warning(
            parent,
            "Too Many Teams",
            (
                f"This league has {len(teams)} teams, but schedule generation is limited "
                f"to {MAX_LEAGUE_TEAMS}. Reduce the league size before regenerating."
            ),
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
    template_id = select_schedule_template(parent, default_id=default_template_id)
    if not template_id:
        return

    start_year: Optional[int] = None
    try:
        from playbalance.season_context import SeasonContext as _SeasonContext

        ctx = _SeasonContext.load()
        current = ctx.current if isinstance(ctx.current, dict) else {}
        raw_year = current.get("league_year")
        if raw_year is not None:
            start_year = int(raw_year)
    except Exception:
        start_year = None
    if start_year is None:
        start_year = date.today().year
    schedule_path = data_root / "schedule.csv"

    try:
        schedule = generate_schedule_from_template(
            template_id,
            teams,
            year=start_year,
        )
        if not schedule:
            raise RuntimeError("Schedule generation failed for the selected template.")
        save_schedule(schedule, schedule_path)
    except Exception as exc:
        QMessageBox.critical(parent, "Schedule Generation Failed", str(exc))
        return

    try:
        from playbalance.season_context import SeasonContext as _SeasonContext

        if schedule:
            first_date = str(schedule[0].get("date", "")).strip()
            if first_date:
                try:
                    year = int(first_date.split("-")[0])
                except Exception:
                    year = None
                ctx = _SeasonContext.load()
                ctx.ensure_current_season(league_year=year, started_on=first_date)
    except Exception:
        pass

    try:
        log_news_event(
            f"Admin regenerated regular season schedule ({len(schedule)} games)"
        )
    except Exception:
        pass

    try:
        record_league_metadata(schedule_template_id=template_id)
    except Exception:
        pass

    message = (
        f"Schedule regenerated with {len(schedule)} games.\n"
        "All previous results have been cleared."
    )
    QMessageBox.information(parent, "Schedule Regenerated", message)
    if context.show_toast:
        try:
            context.show_toast("success", message)
        except Exception:
            pass


__all__ = [
    "create_league_action",
    "regenerate_schedule_action",
    "reset_season_to_opening_day",
]

