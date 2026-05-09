"""All-Star Game endpoints — recap of past games + on-demand re-roll.

Games are normally produced automatically when the sim crosses the
All-Star break midpoint (see ``api/routers/season.py``); these endpoints
just expose the persisted history for the UI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from services.all_star_game import (
    load_all_star_history,
    load_all_star_year,
    play_all_star_game,
    select_all_star_rosters,
)
from utils.league_settings import can_run_season_progression

from ..security import CurrentIdentity, require_bearer

router = APIRouter(prefix="/all-star", tags=["all-star"], dependencies=[CurrentIdentity])


@router.get("")
def list_all_star_games() -> Dict[str, Any]:
    """Return every persisted All-Star Game, newest year first."""

    history = load_all_star_history()
    years = sorted(
        (int(y) for y in history.keys() if str(y).isdigit()),
        reverse=True,
    )
    games: List[Dict[str, Any]] = []
    for year in years:
        record = history.get(str(year))
        if isinstance(record, dict):
            games.append(record)
    return {"count": len(games), "games": games}


@router.get("/{year}")
def get_all_star_game(year: int) -> Dict[str, Any]:
    record = load_all_star_year(year)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No All-Star Game on file for {year}.",
        )
    return record


@router.get("/{year}/rosters")
def preview_rosters(year: int) -> Dict[str, Any]:
    """Preview what the rosters WOULD be if the game ran right now.

    Useful before the sim crosses the break to see the picks.
    """

    return select_all_star_rosters() | {"year": year}


@router.post("/{year}/play")
def trigger_all_star_game(
    year: int,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Manually run / re-roll the All-Star Game for a given year.

    Useful when an admin wants to regenerate (``force=true``) or when
    a league created mid-season needs to backfill. Auth follows the
    same rule as season progression: solo owner OR commish.
    """

    role = str(identity.get("r", "")).lower()
    if not can_run_season_progression(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the commissioner can trigger this in owner leagues.",
        )
    force = bool(payload.get("force", False))
    seed_raw = payload.get("seed")
    try:
        seed: Optional[int] = int(seed_raw) if seed_raw is not None else None
    except (TypeError, ValueError):
        seed = None
    return play_all_star_game(year=year, force=force, seed=seed)
