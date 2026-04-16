"""Free-agency endpoints.

GET /free-agents lists every player not on any team's roster, courtesy of
:func:`services.free_agency.list_unsigned_players_from_files`.

POST /teams/{team_id}/sign assigns a free agent to the team at the given
roster level using :func:`utils.roster_loader.save_roster` so the move
persists alongside everything else the sim consumes.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException, status

from services.free_agency import list_unsigned_players_from_files
from services.transaction_log import record_transaction
from utils.roster_loader import load_roster, save_roster

from ..security import CurrentIdentity

router = APIRouter(tags=["free-agency"], dependencies=[CurrentIdentity])

_LEVEL_ATTR = {"ACT": "act", "AAA": "aaa", "LOW": "low"}

_SUMMARY_RATING_KEYS = (
    "ch", "ph", "sp", "eye", "fa", "arm",
    "fb", "control", "movement", "endurance",
)


def _summarize(player: Any) -> Dict[str, Any]:
    is_pitcher = bool(getattr(player, "is_pitcher", False))
    ratings = {
        k: getattr(player, k, None)
        for k in _SUMMARY_RATING_KEYS
    }
    ratings = {k: v for k, v in ratings.items() if v is not None}
    return {
        "player_id": getattr(player, "player_id", ""),
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "primary_position": getattr(player, "primary_position", ""),
        "other_positions": getattr(player, "other_positions", "") or "",
        "bats": getattr(player, "bats", "") or "",
        "is_pitcher": is_pitcher,
        "role": getattr(player, "role", "") or "",
        "ratings": ratings,
    }


@router.get("/free-agents")
def list_free_agents(limit: int = 1000) -> Dict[str, Any]:
    try:
        players = list_unsigned_players_from_files()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load free agents: {exc}",
        ) from exc
    rows = [_summarize(p) for p in players]
    rows.sort(key=lambda r: (r["last_name"], r["first_name"]))
    return {"count": len(rows), "limit": limit, "free_agents": rows[:limit]}


@router.post("/teams/{team_id}/sign")
def sign_free_agent(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    level_raw = str(payload.get("level", "ACT")).strip().upper()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )
    if level_raw not in _LEVEL_ATTR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="level must be one of ACT / AAA / LOW.",
        )

    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load roster: {exc}",
        ) from exc

    # Make sure the player isn't already on this team somewhere.
    for attr in ("act", "aaa", "low", "dl", "ir"):
        if player_id in getattr(roster, attr, []):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{player_id} is already on {team_id}'s {attr.upper()} roster.",
            )

    # We don't re-validate "free agent" here because the roster_loader's
    # placeholder pool re-assigns IDs at signing time; trust the caller and
    # let save_roster + the placeholder reconciler resolve conflicts the
    # same way trades do.
    target_attr = _LEVEL_ATTR[level_raw]
    getattr(roster, target_attr).append(player_id)

    try:
        save_roster(team_id, roster)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save roster: {exc}",
        ) from exc

    try:
        record_transaction(
            action="sign",
            team_id=team_id,
            player_id=player_id,
            from_level="FA",
            to_level=level_raw,
            details=f"Signed as free agent to {level_raw}",
        )
    except Exception:
        pass

    return {
        "team_id": team_id,
        "player_id": player_id,
        "level": level_raw,
        "signed": True,
    }
