"""Physics tuning editor endpoints.

Mirrors the slider surface exposed by ``ui/playbalance_editor.py`` by
reusing the same spec list and the existing load/save helpers. Admin-only.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from physics_sim.engine_generation import (
    CURRENT_ENGINE_GENERATION,
    LEGACY_ENGINE_GENERATION,
)
from services.league_rating_centers import get_league_engine_generation
from services.physics_tuning_settings import (
    load_physics_tuning_defaults,
    load_physics_tuning_overrides,
    reset_physics_tuning_overrides,
    save_physics_tuning_overrides,
)
from services.physics_tuning_spec import tuning_sections_for_generation

from ..security import require_bearer

router = APIRouter(prefix="/tuning", tags=["tuning"])

# The one line the Physics Tuning page shows about the league's engine.
ENGINE_MESSAGE_LEGACY = (
    "This league moves to the new game engine at the start of next season."
)
ENGINE_MESSAGE_CURRENT = "This league uses the new game engine."


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


def _serialize_spec(generation: int | None = None) -> List[Dict[str, Any]]:
    # Release 5: the slider set is the one of the league season's engine
    # generation (the rebased sliders from generation 5); a league on the
    # legacy engine gets the catalog it always had.
    if generation is None:
        generation = get_league_engine_generation(store=False)
    sections: List[Dict[str, Any]] = []
    for label, specs in tuning_sections_for_generation(generation):
        sections.append(
            {
                "label": label,
                "sliders": [asdict(s) for s in specs],
            }
        )
    return sections


def _engine_block(generation: int) -> Dict[str, Any]:
    current = generation > LEGACY_ENGINE_GENERATION
    return {
        "generation": generation,
        "latest_generation": CURRENT_ENGINE_GENERATION,
        "message": ENGINE_MESSAGE_CURRENT if current else ENGINE_MESSAGE_LEGACY,
    }


def _view() -> Dict[str, Any]:
    # A page load reads the season's generation and never fixes it. One
    # lookup, so the sliders, the defaults and the overrides agree.
    generation = get_league_engine_generation(store=False)
    return {
        "sections": _serialize_spec(generation),
        # ``defaults`` are the engine's defaults under the league's
        # generation, not the effective values: the editor saves every knob
        # that differs from them, so a stored override the commissioner did
        # not touch this session is sent back and kept.
        "defaults": load_physics_tuning_defaults(generation),
        "overrides": load_physics_tuning_overrides(generation),
        "engine": _engine_block(generation),
    }


@router.get("")
def get_tuning(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    return _view()


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
    return _view()


@router.post("/reset")
def reset_tuning(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    reset_physics_tuning_overrides()
    return _view()
