"""Offseason finance flow endpoints (admin-only).

Exposes the checklist + pipeline runner + stage-mark helpers from
``services.offseason_finance_flow`` so the Electron UI can walk an admin
through the end-of-season finance rollover.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.offseason_finance_flow import (
    collect_offseason_finance_overview,
    get_offseason_checklist,
    get_offseason_stage_details,
    mark_offseason_stage,
    run_offseason_financial_rollover,
)

from ..security import require_bearer

router = APIRouter(prefix="/offseason", tags=["offseason"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("/checklist")
def checklist(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        return get_offseason_checklist()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.get("/overview")
def overview(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        return collect_offseason_finance_overview()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.get("/details")
def details(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    """Return full review payload (contract expirations, arbitration,
    budget deltas, GM finance queue) the PyQt offseason dialog rendered
    in tabs.
    """

    try:
        return get_offseason_stage_details()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.get("/stage/{stage_id}")
def stage_details(stage_id: str, _: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    """Per-stage details (kept for compatibility; returns the same payload
    as /details since the underlying service builds all rows in one pass).
    """

    try:
        payload = get_offseason_stage_details()
        payload["stage_id"] = stage_id
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/run-pipeline")
def run_pipeline(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        overview = collect_offseason_finance_overview()
        ended = payload.get("ended_season_year") or overview.get("ended_season_year")
        nxt = payload.get("next_season_year") or overview.get("next_season_year")
        return run_offseason_financial_rollover(
            ended_season_year=int(ended) if ended is not None else None,
            next_season_year=int(nxt) if nxt is not None else None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/stage/mark")
def mark_stage(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    stage_id = str(payload.get("stage_id", "")).strip()
    if not stage_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="stage_id is required."
        )
    return mark_offseason_stage(stage_id)
