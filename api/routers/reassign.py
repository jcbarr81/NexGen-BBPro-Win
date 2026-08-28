"""Roster auto-assign endpoints (admin/owner).

`POST /teams/{team_id}/auto-assign` — reassign one team.
`POST /reassign/all`             — admin: reassign every team in the league.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from services.roster_auto_assign import auto_assign_all_teams, auto_assign_team

from ..security import CurrentIdentity, require_bearer

team_router = APIRouter(
    prefix="/teams/{team_id}",
    tags=["reassign"],
    dependencies=[CurrentIdentity],
)
all_router = APIRouter(prefix="/reassign", tags=["reassign"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


@team_router.post("/auto-assign")
async def auto_assign_one(team_id: str) -> Dict[str, Any]:
    try:
        result = await asyncio.to_thread(auto_assign_team, team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auto-assign failed: {exc}",
        ) from exc
    released = list((result or {}).get("released") or [])
    overflow = list((result or {}).get("overflow") or [])
    moved = list((result or {}).get("moved") or [])
    return {
        "team_id": team_id,
        "status": "ok",
        "released": released,
        "released_count": len(released),
        # Players kept over the AAA soft-cap (org under the total limit) instead
        # of being cut — the UI should ask the owner to trim these manually.
        "overflow": overflow,
        "overflow_count": len(overflow),
        # Every player whose level changed, so the UI can show what moved
        # instead of only the resulting counts.
        "moved": moved,
        "moved_count": len(moved),
    }


@all_router.post("/all")
async def auto_assign_all(_: Dict[str, Any] = Depends(_require_admin)) -> Dict[str, Any]:
    try:
        await asyncio.to_thread(auto_assign_all_teams)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"League-wide auto-assign failed: {exc}",
        ) from exc
    return {"status": "ok"}
