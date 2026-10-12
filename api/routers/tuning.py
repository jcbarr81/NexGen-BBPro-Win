"""Physics tuning editor endpoints.

Mirrors the slider surface exposed by ``ui/playbalance_editor.py`` by
reusing the same spec list and the existing load/save helpers. Admin-only.
"""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from physics_sim.engine_generation import (
    CURRENT_ENGINE_GENERATION,
    LEGACY_ENGINE_GENERATION,
)
from services.league_rating_centers import (
    get_league_engine_generation,
    new_seasons_held_on_legacy,
)
from services.physics_tuning_settings import (
    load_physics_tuning_defaults,
    load_physics_tuning_overrides,
    reset_physics_tuning_overrides,
    save_physics_tuning_overrides,
)
from services.physics_tuning_spec import tuning_sections_for_generation

from ..security import require_bearer

router = APIRouter(prefix="/tuning", tags=["tuning"])
_LOGGER = logging.getLogger(__name__)

# The one line the Physics Tuning page shows about the league's engine.
ENGINE_MESSAGE_LEGACY = (
    "This league moves to the new game engine at the start of next season."
)
# While the operations switch holds new seasons on the legacy engine
# (NEXGEN_NEW_SEASON_ENGINE), the line above would promise a move that the
# next rollover is not going to make.
ENGINE_MESSAGE_LEGACY_HELD = (
    "This league uses the current game engine. The new game engine is not "
    "being switched on for new seasons yet."
)
ENGINE_MESSAGE_CURRENT = "This league uses the new game engine."
ENGINE_LOOKUP_FAILED = (
    "Could not work out which game engine this league's season is on, so "
    "the tuning settings were not loaded and nothing was changed. Try again; "
    "if it keeps happening, the league's season files need attention."
)


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
        generation = _league_generation()
    sections: List[Dict[str, Any]] = []
    for label, specs in tuning_sections_for_generation(generation):
        sections.append(
            {
                "label": label,
                "sliders": [asdict(s) for s in specs],
            }
        )
    return sections


def _league_generation() -> int:
    """The season's generation for the page: read, never fixed.

    The lookup raises on a real fault instead of answering "legacy"
    (services.league_rating_centers). The page then gets an error to show,
    not the wrong engine's sliders -- which a save would write to the file.
    """
    try:
        return get_league_engine_generation(store=False)
    except Exception as exc:
        _LOGGER.exception("tuning page: engine generation lookup failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ENGINE_LOOKUP_FAILED,
        ) from exc


def _engine_block(generation: int) -> Dict[str, Any]:
    if generation > LEGACY_ENGINE_GENERATION:
        message = ENGINE_MESSAGE_CURRENT
    elif new_seasons_held_on_legacy():
        message = ENGINE_MESSAGE_LEGACY_HELD
    else:
        message = ENGINE_MESSAGE_LEGACY
    return {
        "generation": generation,
        "latest_generation": CURRENT_ENGINE_GENERATION,
        "message": message,
    }


def _view() -> Dict[str, Any]:
    # A page load reads the season's generation and never fixes it. One
    # lookup, so the sliders, the defaults and the overrides agree. The
    # overrides come back on the generation's scales, converted in memory:
    # a page load never converts the file (services.physics_tuning_settings).
    generation = _league_generation()
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
    # Before anything is written: a save that cannot tell which engine the
    # season is on must not store sliders on a guessed scale.
    _league_generation()
    try:
        save_physics_tuning_overrides(overrides)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _view()


@router.post("/reset")
def reset_tuning(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    _league_generation()  # as in save_tuning: fail before anything is removed
    reset_physics_tuning_overrides()
    return _view()
