"""Change-request queue endpoints (commissioner tools)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services import change_requests as cr

from ..security import require_bearer

router = APIRouter(prefix="/change-requests", tags=["change-requests"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("")
def list_requests(
    status_filter: Optional[str] = None,
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    rows = cr.list_requests(status=status_filter)
    return {"count": len(rows), "requests": rows}


@router.post("/status")
def update_status(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    request_id = str(payload.get("request_id", "")).strip()
    new_status = str(payload.get("status", "")).strip()
    if not (request_id and new_status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="request_id and status are required.",
        )
    row = cr.update_request_status(
        request_id,
        status=new_status,
        note=payload.get("note"),
    )
    if not row or row.get("status") == "missing":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found.",
        )
    return {"request": row}
