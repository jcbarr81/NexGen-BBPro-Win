"""Admin league-management actions (commissioner only).

Ports the destructive admin actions from
``ui/admin_dashboard/actions/league.py`` that weren't exposed anywhere
else — regenerate schedule, reset stats, clone league.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import date
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from utils.path_utils import get_data_dir, get_data_root

from ..security import require_bearer

router = APIRouter(prefix="/admin-league", tags=["admin-league"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("/schedule-templates")
def schedule_templates(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    """List available schedule templates for regenerate."""

    try:
        from services.league_presets import load_schedule_templates
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Template catalog unavailable: {exc}",
        ) from exc
    templates = load_schedule_templates()
    return {
        "templates": [
            {
                "id": getattr(t, "template_id", getattr(t, "id", "")),
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", ""),
                "games_per_team": getattr(t, "games_per_team", 0),
            }
            for t in templates
        ],
    }


@router.post("/regenerate-schedule")
async def regenerate_schedule(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    template_id = str(payload.get("template_id", "mlb_162")).strip() or "mlb_162"

    from utils.team_loader import load_teams
    from services.league_presets import generate_schedule_from_template
    from playbalance.schedule_generator import save_schedule

    data_root = get_data_dir()
    teams_path = data_root / "teams.csv"
    try:
        teams = [t.team_id for t in load_teams(teams_path)]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed reading teams: {exc}",
        ) from exc
    if not teams:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No teams found to schedule.",
        )

    # Use the current season's league_year when available.
    start_year: int | None = None
    try:
        from playbalance.season_context import SeasonContext

        ctx = SeasonContext.load()
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
        schedule = await asyncio.to_thread(
            generate_schedule_from_template, template_id, teams, year=start_year
        )
        if not schedule:
            raise RuntimeError("Schedule generation returned no games.")
        await asyncio.to_thread(save_schedule, schedule, schedule_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Schedule generation failed: {exc}",
        ) from exc

    return {
        "games": len(schedule),
        "template_id": template_id,
        "start_year": start_year,
        "schedule_path": str(schedule_path),
    }


@router.post("/reset-stats")
def reset_stats_action(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    """Wipe season_stats.json. Does not touch schedule or rosters."""

    try:
        from utils.stats_persistence import reset_stats
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stats module unavailable: {exc}",
        ) from exc
    stats_path = get_data_dir() / "season_stats.json"
    try:
        reset_stats(stats_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset stats: {exc}",
        ) from exc
    return {"reset": True, "path": str(stats_path)}


@router.post("/reset-results")
def reset_results(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    """Mark every scheduled game as unplayed (keeps the dates + matchups)."""

    import csv

    schedule_path = get_data_dir() / "schedule.csv"
    if not schedule_path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No schedule.csv to reset.",
        )
    rows: list[Dict[str, str]] = []
    with schedule_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or [
            "date",
            "home",
            "away",
            "result",
            "played",
            "boxscore",
        ]
        for row in reader:
            row["result"] = ""
            row["played"] = ""
            row["boxscore"] = ""
            rows.append(row)
    with schedule_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {"reset": True, "games": len(rows)}


@router.post("/repair-lineups")
def repair_lineups(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    """Port of ui/season_progress_window.py::_repair_lineups.

    Ensures every team has a valid 9-slot lineup for vs-LHP + vs-RHP.
    Runs the lineup autofill for any team that fails validation; returns
    the list of teams fixed vs still-broken.
    """

    from utils.lineup_autofill import auto_fill_lineup_for_team
    from utils.player_loader import load_players_from_csv
    from utils.roster_backfill import ensure_active_rosters
    from utils.team_loader import load_teams

    data_dir = get_data_dir()
    try:
        teams = load_teams(data_dir / "teams.csv")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load teams: {exc}",
        ) from exc

    try:
        players = {
            p.player_id: p
            for p in load_players_from_csv(data_dir / "players.csv")
        }
        ensure_active_rosters(players=players, roster_dir=data_dir / "rosters")
    except Exception as exc:
        # Roster backfill failure is a warning, not fatal — still try the
        # lineup autofill for each team.
        pass

    fixed: list[str] = []
    failed: list[str] = []
    for team in teams:
        try:
            auto_fill_lineup_for_team(team.team_id)
            fixed.append(team.team_id)
        except Exception:
            failed.append(team.team_id)
    return {"fixed": fixed, "failed": failed}


@router.post("/reset-to-opening-day")
def reset_to_opening_day(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Rewind the current league to Opening Day.

    Ports ``ui/admin_dashboard/actions/league.reset_season_to_opening_day``.
    Clears regular-season results, standings, stats, season history,
    draft + playoff artifacts for the current year, injuries, and
    pitcher recovery state; sets phase back to REGULAR_SEASON.

    Optional opt-in purges via payload flags:
      - ``purge_boxscores`` — also delete ``boxscores/season``.
      - ``clear_news`` — also delete ``news_feed.txt`` + ``news_feed.jsonl``.
      - ``clear_transactions`` — also clear ``transactions.csv``.
    """

    import csv

    purge_box = bool(payload.get("purge_boxscores", False))
    clear_news = bool(payload.get("clear_news", False))
    clear_transactions = bool(payload.get("clear_transactions", False))

    data_root = get_data_dir()
    sched = data_root / "schedule.csv"
    if not sched.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reset: schedule.csv not found. Generate a schedule first.",
        )

    notes: list[str] = []

    # 1. Clear schedule result/played/boxscore columns.
    try:
        rows: list[Dict[str, str]] = []
        with sched.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for record in reader:
                record = dict(record)
                record["result"] = ""
                record["played"] = ""
                record["boxscore"] = ""
                rows.append(record)
        fieldnames = ["date", "home", "away", "result", "played", "boxscore"]
        with sched.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for record in rows:
                writer.writerow({key: record.get(key, "") for key in fieldnames})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed rewriting schedule: {exc}",
        ) from exc

    # 2. Determine league's opening-day year from the schedule.
    first_year: int | None = None
    try:
        if rows and rows[0].get("date"):
            first_year = int(str(rows[0]["date"]).split("-")[0])
    except Exception:
        first_year = None

    # 3. Reset season_progress.json (keep other years' draft_completed).
    progress = data_root / "season_progress.json"
    try:
        data: Dict[str, Any] = {
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
                if first_year is not None:
                    completed.discard(first_year)
                if completed:
                    data["draft_completed_years"] = sorted(completed)
            except Exception:
                pass
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed resetting progress: {exc}",
        ) from exc

    # 4. Empty standings.
    try:
        from services.standings_repository import save_standings

        save_standings({})
    except Exception as exc:
        notes.append(f"Standings reset failed: {exc}")

    # 5. Reset season stats JSON.
    try:
        from utils.stats_persistence import reset_stats

        reset_stats(data_root / "season_stats.json")
    except Exception as exc:
        notes.append(f"Season stats reset failed: {exc}")

    # 6. Delete season_history/ directory.
    history_dir = data_root / "season_history"
    try:
        if history_dir.exists():
            shutil.rmtree(history_dir)
    except Exception as exc:
        notes.append(f"Failed clearing season history: {exc}")

    # 7. Delete draft artifacts for the current year.
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
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass

    # 8. Delete playoff bracket files.
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
        for candidate in data_root.glob("playoffs_summary_*.md"):
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception:
                pass
    except Exception as exc:
        notes.append(f"Playoff cleanup failed: {exc}")

    # 9. Clear player injury flags + reconcile rosters.
    try:
        from utils.player_loader import load_players_from_csv
        from services.players_repository import save_players
        from utils.roster_loader import load_roster, save_roster
        from services.injury_manager import recover_from_injury

        players_path = data_root / "players.csv"
        players = list(load_players_from_csv(players_path))
        players_by_id: Dict[str, Any] = {}
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
            players_by_id = {p.player_id: p for p in players}
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
                injured_ids = list(getattr(roster, "dl", []) or []) + list(
                    getattr(roster, "ir", []) or []
                )
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
                    try:
                        roster.promote_replacements()
                    except Exception:
                        pass
                    save_roster(team_id, roster)
    except Exception as exc:
        notes.append(f"Failed clearing injuries: {exc}")

    # 10. Set phase back to REGULAR_SEASON.
    try:
        from playbalance.season_manager import SeasonManager, SeasonPhase

        manager = SeasonManager()
        manager.phase = SeasonPhase.REGULAR_SEASON
        manager.save()
        try:
            manager.finalize_rosters()
        except Exception:
            pass
    except Exception as exc:
        notes.append(f"Failed setting phase: {exc}")

    # 11. Reset pitcher recovery tracker.
    try:
        from utils.pitcher_recovery import PitcherRecoveryTracker

        PitcherRecoveryTracker.instance().reset()
    except Exception as exc:
        notes.append(f"Pitcher recovery reset failed: {exc}")

    # 12. Log news event (only if not also purging news).
    if not clear_news:
        try:
            from utils.news_logger import log_news_event

            log_news_event("League reset to Opening Day")
        except Exception:
            pass

    # 13. Optional purges.
    boxscores_cleared = False
    if purge_box:
        try:
            box_dir = data_root / "boxscores" / "season"
            if box_dir.exists():
                shutil.rmtree(box_dir)
            boxscores_cleared = True
            try:
                from utils.news_logger import log_news_event

                log_news_event("Purged saved season boxscores")
            except Exception:
                pass
        except Exception as exc:
            notes.append(f"Boxscore purge failed: {exc}")

    news_cleared = False
    if clear_news:
        try:
            for name in ("news_feed.txt", "news_feed.jsonl"):
                target = data_root / name
                if target.exists():
                    target.unlink()
            news_cleared = True
        except Exception as exc:
            notes.append(f"News feed purge failed: {exc}")

    transactions_cleared = False
    if clear_transactions:
        try:
            from services.transaction_log import clear_transactions as clear_txn_log

            clear_txn_log(path=data_root / "transactions.csv")
            transactions_cleared = True
        except Exception as exc:
            notes.append(f"Transactions purge failed: {exc}")

    return {
        "reset": True,
        "opening_day_year": first_year,
        "boxscores_cleared": boxscores_cleared,
        "news_cleared": news_cleared,
        "transactions_cleared": transactions_cleared,
        "notes": notes,
    }


@router.post("/clone")
def clone_league(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Copy the active league into a new league directory.

    The destination id + display name are required. We copy under
    ``<data_root>/leagues/<id>`` and register it in ``league_registry.json``.
    """

    new_id = str(payload.get("league_id", "")).strip()
    new_name = str(payload.get("display_name", "")).strip()
    if not new_id or not new_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="league_id and display_name are required.",
        )
    if not new_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="league_id must be alphanumeric (dashes/underscores allowed).",
        )

    data_root = get_data_root()
    leagues_dir = data_root / "leagues"
    src_dir = get_data_dir()
    dst_dir = leagues_dir / new_id
    if dst_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"League '{new_id}' already exists.",
        )

    try:
        shutil.copytree(src_dir, dst_dir)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Copy failed: {exc}",
        ) from exc

    # Register in league_registry.json.
    registry_path = data_root / "league_registry.json"
    registry: Dict[str, Any] = {"leagues": []}
    if registry_path.exists():
        try:
            with registry_path.open("r", encoding="utf-8") as fh:
                registry = json.load(fh)
        except Exception:
            registry = {"leagues": []}
    leagues = registry.get("leagues", [])
    if any(entry.get("id") == new_id for entry in leagues):
        # Already registered but dst existed? Shouldn't happen; just no-op.
        pass
    else:
        leagues.append(
            {
                "id": new_id,
                "display_name": new_name,
                "mode": "clone",
                "status": "active",
            }
        )
        registry["leagues"] = leagues
        try:
            with registry_path.open("w", encoding="utf-8") as fh:
                json.dump(registry, fh, indent=2)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Copied but registry write failed: {exc}",
            ) from exc

    return {
        "league_id": new_id,
        "display_name": new_name,
        "path": str(dst_dir),
    }
