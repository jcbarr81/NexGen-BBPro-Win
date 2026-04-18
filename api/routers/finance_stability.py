"""Finance stability scenario-tester endpoints (admin-only)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.finance_stability import (
    evaluate_finance_stability_guardrails,
    run_finance_stability_preset_comparison,
    run_finance_stability_simulation,
)

from ..security import require_bearer

router = APIRouter(prefix="/finance-stability", tags=["finance-stability"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.post("/run")
async def run_simulation(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    seasons = int(payload.get("seasons", 3) or 3)
    seed: Optional[int] = payload.get("seed") if isinstance(payload.get("seed"), int) else None
    preset = str(payload.get("preset", "standard")).strip() or "standard"
    try:
        return await asyncio.to_thread(
            run_finance_stability_simulation,
            seasons=seasons,
            preset=preset,
            seed=seed,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/compare")
async def run_comparison(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    seasons = int(payload.get("seasons", 3) or 3)
    seed: Optional[int] = payload.get("seed") if isinstance(payload.get("seed"), int) else None
    presets = payload.get("presets") or None
    try:
        return await asyncio.to_thread(
            run_finance_stability_preset_comparison,
            seasons=seasons,
            presets=presets,
            seed=seed,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/evaluate")
def evaluate(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    seasons = payload.get("season_metrics")
    if not isinstance(seasons, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="season_metrics must be a list.",
        )
    try:
        return evaluate_finance_stability_guardrails(seasons)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
