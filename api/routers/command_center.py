"""League command center snapshot."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from services.league_command_center import build_league_command_center_snapshot

from ..security import CurrentIdentity

router = APIRouter(prefix="/league", tags=["command-center"], dependencies=[CurrentIdentity])


@router.get("/command-center")
def get_command_center() -> Dict[str, Any]:
    try:
        return build_league_command_center_snapshot()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build command center: {exc}",
        ) from exc
