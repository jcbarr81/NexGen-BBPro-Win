"""Physics tuning editor endpoints.

Mirrors the slider surface exposed by ``ui/playbalance_editor.py`` by
reusing the same spec list and the existing load/save helpers. Admin-only.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.physics_tuning_settings import (
    load_physics_tuning_overrides,
    load_physics_tuning_values,
    reset_physics_tuning_overrides,
    save_physics_tuning_overrides,
)
from services.physics_tuning_spec import _TUNING_SECTIONS

from ..security import require_bearer

router = APIRouter(prefix="/tuning", tags=["tuning"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


def _serialize_spec() -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for label, specs in _TUNING_SECTIONS:
        sections.append(
            {
                "label": label,
                "sliders": [asdict(s) for s in specs],
            }
        )
    return sections


@router.get("")
def get_tuning(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    return {
        "sections": _serialize_spec(),
        "defaults": load_physics_tuning_values(),
        "overrides": load_physics_tuning_overrides(),
    }


@router.put("")
def save_tuning(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    overrides = payload.get("overrides")
    if not isinstance(overrides, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="overrides must be an object mapping knob → number.",
        )
    try:
        save_physics_tuning_overrides(overrides)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {
        "sections": _serialize_spec(),
        "defaults": load_physics_tuning_values(),
        "overrides": load_physics_tuning_overrides(),
    }


@router.post("/reset")
def reset_tuning(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    reset_physics_tuning_overrides()
    return {
        "sections": _serialize_spec(),
        "defaults": load_physics_tuning_values(),
        "overrides": load_physics_tuning_overrides(),
    }
