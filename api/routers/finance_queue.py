"""GM finance queue endpoints (commissioner review).

Wraps :mod:`services.gm_finance_queue`:

- List pending owner decisions (arbitration + free-agency).
- Approve / reject individual rows.
- Apply approved decisions as a batch (writes contracts, rosters, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.gm_finance_queue import (
    apply_approved_queue_decisions,
    list_pending_queue_decisions,
    set_queue_review_status,
)

from ..security import require_bearer

router = APIRouter(prefix="/finance-queue", tags=["finance-queue"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("")
def list_queue(
    queue_type: Optional[str] = None,
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    rows = list_pending_queue_decisions(queue_type=queue_type)
    return {"count": len(rows), "rows": rows}


@router.post("/review")
def review(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    team_id = str(payload.get("team_id", "")).strip()
    queue_type = str(payload.get("queue_type", "")).strip()
    item_id = str(payload.get("item_id", "")).strip()
    review_status = str(payload.get("review_status", "")).strip()
    notes = payload.get("notes")
    if not (team_id and queue_type and item_id and review_status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team_id, queue_type, item_id, review_status are required.",
        )
    try:
        row = set_queue_review_status(
            team_id,
            queue_type=queue_type,
            item_id=item_id,
            review_status=review_status,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision {item_id} not found for {team_id}.",
        )
    return {"row": row}


@router.post("/apply-approved")
def apply_approved(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        result = apply_approved_queue_decisions()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    if not isinstance(result, dict):
        result = {"result": str(result)}
    return result
