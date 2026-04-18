"""Hall of Fame endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services import hall_of_fame as hof

from ..security import CurrentIdentity, require_bearer

router = APIRouter(prefix="/hall-of-fame", tags=["hof"], dependencies=[CurrentIdentity])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("")
def get_hall_of_fame() -> Dict[str, Any]:
    inductees = hof.list_inductees()
    candidates = [asdict(c) for c in hof.list_candidates()]
    return {
        "inductees": inductees,
        "candidates": candidates,
    }


@router.post("/induct")
def induct(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="player_id is required."
        )
    try:
        result = hof.add_manual_inductee(player_id, note=payload.get("note"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"result": result}


@router.post("/remove")
def remove(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="player_id is required."
        )
    try:
        result = hof.remove_inductee(player_id, reason=payload.get("reason"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"result": result}


@router.post("/refresh")
def refresh(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        result = hof.update_hall_of_fame()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return {"result": result}
