"""Lineup + pitching-staff editor endpoints.

Both are simple CSV files under ``data/lineups/`` and
``data/rosters/<team>_pitching.csv``. The simulator's
``simulate_game_scores`` needs them to be valid before the season day can
advance, so this router provides GET + PUT + an "autofill" hook that
reuses the existing :func:`utils.lineup_autofill.auto_fill_lineup_for_team`.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Body, HTTPException, status

from utils.lineup_autofill import auto_fill_lineup_for_team
from utils.lineup_loader import load_lineup
from utils.path_utils import get_data_dir, resolve_app_path

from ..security import CurrentIdentity

router = APIRouter(
    prefix="/teams/{team_id}",
    tags=["lineups"],
    dependencies=[CurrentIdentity],
)

Vs = Literal["lhp", "rhp"]


def _lineup_dir() -> Path:
    return resolve_app_path("data/lineups")


def _lineup_path(team_id: str, vs: Vs) -> Path:
    return _lineup_dir() / f"{team_id}_vs_{vs}.csv"


def _pitching_path(team_id: str) -> Path:
    return resolve_app_path("data/rosters") / f"{team_id}_pitching.csv"


# ---------------------------------------------------------------------------
# Lineup


@router.get("/lineup/{vs}")
def get_lineup(team_id: str, vs: Vs) -> Dict[str, Any]:
    try:
        rows = load_lineup(team_id, vs=vs)
    except FileNotFoundError:
        return {"team_id": team_id, "vs": vs, "exists": False, "lineup": []}
    return {
        "team_id": team_id,
        "vs": vs,
        "exists": True,
        "lineup": [
            {"order": idx + 1, "player_id": pid, "position": pos}
            for idx, (pid, pos) in enumerate(rows)
        ],
    }


@router.put("/lineup/{vs}")
def save_lineup(
    team_id: str,
    vs: Vs,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    rows_in = payload.get("lineup")
    if not isinstance(rows_in, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lineup must be a list.",
        )

    # Run the full shared validator before we touch disk. Warnings don't
    # block the save, but any error aborts with a 422 carrying the full
    # error + warning list so the UI can display them.
    from services.roster_validation import validate_lineup

    from .validation import load_players_map

    players = load_players_map()
    result = validate_lineup(lineup_rows=rows_in, players=players, vs=vs)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Lineup has validation errors.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    parsed: List[tuple[str, str]] = []
    for entry in rows_in:
        pid = str(entry.get("player_id", "")).strip()
        pos = str(entry.get("position", "")).strip().upper()
        parsed.append((pid, pos))

    path = _lineup_path(team_id, vs)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["order", "player_id", "position"])
        for i, (pid, pos) in enumerate(parsed, start=1):
            writer.writerow([i, pid, pos])

    return get_lineup(team_id, vs)


@router.post("/lineup/autofill")
def autofill_lineup(team_id: str) -> Dict[str, Any]:
    try:
        auto_fill_lineup_for_team(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Autofill failed: {exc}",
        ) from exc
    return {
        "team_id": team_id,
        "lhp": get_lineup(team_id, "lhp"),
        "rhp": get_lineup(team_id, "rhp"),
    }


# ---------------------------------------------------------------------------
# Pitching staff


@router.get("/pitching")
def get_pitching_staff(team_id: str) -> Dict[str, Any]:
    path = _pitching_path(team_id)
    entries: List[Dict[str, str]] = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if len(row) < 2:
                    continue
                entries.append(
                    {"player_id": row[0].strip(), "role": row[1].strip().upper()},
                )
    return {"team_id": team_id, "exists": path.exists(), "staff": entries}


@router.put("/pitching")
def save_pitching_staff(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    rows_in = payload.get("staff")
    if not isinstance(rows_in, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="staff must be a list.",
        )

    from services.roster_validation import validate_pitching_staff

    from .validation import load_players_map, load_team_levels

    players = load_players_map()
    active_ids = load_team_levels(team_id).get("act", [])
    result = validate_pitching_staff(
        staff=rows_in, players=players, active_ids=active_ids
    )
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Pitching staff has validation errors.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    parsed: List[tuple[str, str]] = []
    for entry in rows_in:
        pid = str(entry.get("player_id", "")).strip()
        role = str(entry.get("role", "")).strip().upper()
        parsed.append((pid, role))

    path = _pitching_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for pid, role in parsed:
            writer.writerow([pid, role])

    return get_pitching_staff(team_id)
