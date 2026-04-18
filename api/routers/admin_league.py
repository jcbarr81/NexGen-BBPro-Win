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
        from services.league_presets import list_schedule_templates
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Template catalog unavailable: {exc}",
        ) from exc
    templates = list_schedule_templates()
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
    from utils.schedule_generator import (
        generate_schedule_from_template,
        save_schedule,
    )

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
