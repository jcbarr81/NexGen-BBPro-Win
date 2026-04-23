"""League registry + active-league endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from services import league_lifecycle, league_registry
from utils import path_utils

from ..schemas import LeagueRecordOut
from ..security import CurrentIdentity, require_bearer

router = APIRouter(prefix="/leagues", tags=["leagues"], dependencies=[CurrentIdentity])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


@router.get("", response_model=List[LeagueRecordOut])
def list_leagues() -> List[LeagueRecordOut]:
    records = league_registry.list_leagues()
    return [LeagueRecordOut(**asdict(record)) for record in records]


@router.get("/active")
def get_active() -> dict:
    return {"league_id": path_utils.get_active_league_id()}


@router.post("/active/{league_id}")
def set_active(league_id: str) -> dict:
    record = league_registry.get_league(league_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown league")
    path_utils.set_active_league_id(league_id)
    return {"league_id": path_utils.get_active_league_id()}


@router.delete("/{league_id}")
def delete_league(
    league_id: str,
    _: Dict[str, Any] = Depends(_require_admin),
) -> dict:
    """Permanently delete a league and its on-disk data. Admin only."""

    record = league_registry.get_league(league_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown league"
        )
    try:
        removed = league_lifecycle.delete_league(
            league_id, delete_data=True, force_if_active=True
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown league"
        )
    return {
        "deleted": True,
        "league_id": league_id,
        "active_league": path_utils.get_active_league_id(),
    }
