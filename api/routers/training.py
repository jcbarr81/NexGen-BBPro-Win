"""Training-focus endpoints.

Wraps :mod:`services.training_settings` so the Electron page can read the
effective hitter + pitcher weights for a team, save a team-level override,
or clear the override and fall back to the league defaults.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, status

from services.training_settings import (
    HITTER_TRACKS,
    PITCHER_TRACKS,
    clear_team_training_weights,
    load_training_settings,
    set_team_training_weights,
)

from ..security import CurrentIdentity

router = APIRouter(
    prefix="/teams/{team_id}/training",
    tags=["training"],
    dependencies=[CurrentIdentity],
)


def _serialize(team_id: str) -> Dict[str, Any]:
    settings = load_training_settings()
    weights = settings.for_team(team_id)
    source = "team" if team_id in settings.team_overrides else "defaults"
    return {
        "team_id": team_id,
        "source": source,
        "league_id": settings.league_id,
        "tracks": {
            "hitters": list(HITTER_TRACKS),
            "pitchers": list(PITCHER_TRACKS),
        },
        "hitters": {k: float(weights.hitters.get(k, 0.0)) for k in HITTER_TRACKS},
        "pitchers": {k: float(weights.pitchers.get(k, 0.0)) for k in PITCHER_TRACKS},
        "defaults": {
            "hitters": {
                k: float(settings.defaults.hitters.get(k, 0.0)) for k in HITTER_TRACKS
            },
            "pitchers": {
                k: float(settings.defaults.pitchers.get(k, 0.0)) for k in PITCHER_TRACKS
            },
        },
    }


@router.get("")
def get_training(team_id: str) -> Dict[str, Any]:
    return _serialize(team_id)


@router.put("")
def save_training(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    hitters = payload.get("hitters")
    pitchers = payload.get("pitchers")
    if not isinstance(hitters, dict) or not isinstance(pitchers, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hitters and pitchers must be objects mapping track -> percent.",
        )
    try:
        set_team_training_weights(team_id, hitters, pitchers)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize(team_id)


@router.delete("")
def reset_training(team_id: str) -> Dict[str, Any]:
    clear_team_training_weights(team_id)
    return _serialize(team_id)
