"""Notification preferences + history endpoints.

Backed by :mod:`services.notification_settings` and
:mod:`services.notification_engine`. Each owner picks which league
events should fire a notification (and optionally pause a multi-day
sim) on the Notifications page; the engine consumes those rules during
``/season/simulate/*``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.notification_engine import load_history
from services.notification_settings import (
    load_notification_settings,
    rules_index,
    save_notification_settings,
)

from ..security import require_bearer

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/schema")
def get_schema(
    _: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Return the rule catalog the UI uses to render checkboxes."""

    return {"categories": rules_index()}


@router.get("/settings/{team_id}")
def get_settings(
    team_id: str,
    _: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    settings = load_notification_settings(team_id)
    return settings.to_dict()


@router.put("/settings/{team_id}")
def put_settings(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    try:
        settings = save_notification_settings(team_id, payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return settings.to_dict()


@router.get("/history/{team_id}")
def history(
    team_id: str,
    limit: int = 100,
    _: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    capped = max(1, min(int(limit), 500))
    items = load_history(team_id, limit=capped)
    return {"team_id": team_id, "count": len(items), "events": items}
