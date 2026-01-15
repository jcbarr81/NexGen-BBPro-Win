"""League lifecycle actions for the admin dashboard."""
from __future__ import annotations

import csv
import json
import shutil
from datetime import date
from typing import Callable, Iterable, Optional, Tuple

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QInputDialog,
    QMessageBox,
    QWidget,
)

try:  # PyQt6.sip is optional depending on packaging
    from PyQt6 import sip
except Exception:  # pragma: no cover - defensive import
    sip = None  # type: ignore

from playbalance.league_creator import create_league
from playbalance.schedule_generator import generate_mlb_schedule, save_schedule
from playbalance.season_manager import SeasonManager, SeasonPhase

from ui.team_entry_dialog import TeamEntryDialog
from ui.window_utils import ensure_on_top
from utils.news_logger import log_news_event
from utils.path_utils import get_base_dir
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.roster_loader import load_roster, save_roster
from services.injury_manager import recover_from_injury
from utils.pitcher_recovery import PitcherRecoveryTracker
from utils.stats_persistence import reset_stats
from utils.team_loader import load_teams
from services.standings_repository import save_standings

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


def create_league_action(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
    refresh_callbacks: Iterable[Callable[[], None]] | None = None,
) -> None:
    """Launch the guided dialog flow for creating a new league."""

    if parent is None:
        return

    confirm = QMessageBox.question(
        parent,
        "Overwrite Existing League?",
        (
            "Creating a new league will overwrite the current league and "
            "teams. Continue?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return

    league_name, ok = QInputDialog.getText(parent, "League Name", "Enter league name:")
    if not ok or not league_name:
        return
    league_name = league_name.strip()

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

    dialog = TeamEntryDialog(divisions, teams_per_div, parent)
    ensure_on_top(dialog)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    structure = dialog.get_structure()
    data_dir = get_base_dir() / "data"
    try:
        create_league(str(data_dir), structure, league_name)
    except OSError as exc:
        QMessageBox.critical(parent, "Error", f"Failed to purge existing league: {exc}")
        return

    QMessageBox.information(parent, "League Created", "New league generated.")
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

    data_root = get_base_dir() / "data"
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
                save_players_to_csv(players, str(players_path))
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
            try:
                load_players_from_csv.cache_clear()  # type: ignore[attr-defined]
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
                transactions = data_root / "transactions.csv"
                if transactions.exists():
                    transactions.unlink()
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

    data_root = get_base_dir() / "data"
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

    start = date(date.today().year, 4, 1)
    schedule_path = data_root / "schedule.csv"

    try:
        schedule = generate_mlb_schedule(teams, start)
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

