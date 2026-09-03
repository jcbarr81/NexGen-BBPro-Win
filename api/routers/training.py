"""Training-focus endpoints.

Wraps :mod:`services.training_settings` so the Electron page can read the
effective hitter + pitcher weights for a team, save a team-level override,
or clear the override and fall back to the league defaults.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.training_settings import (
    HITTER_TRACKS,
    PITCHER_TRACKS,
    clear_player_training_weights,
    clear_team_training_weights,
    load_training_settings,
    set_player_training_weights,
    set_team_training_weights,
    update_league_training_defaults,
)

from ..security import CurrentIdentity, require_bearer, require_team_owner

router = APIRouter(
    prefix="/teams/{team_id}/training",
    tags=["training"],
    dependencies=[CurrentIdentity],
)

# Sibling router for per-player overrides — ported from
# ``ui/training_focus_dialog.py`` (mode="player"). Player overrides shadow
# the team default which shadows the league default.
player_router = APIRouter(
    prefix="/players/{player_id}/training",
    tags=["training"],
    dependencies=[CurrentIdentity],
)

# Sibling router for league-level defaults — ported from
# ``ui/training_focus_dialog.py`` (mode="league"). Commissioner-only edits.
league_router = APIRouter(
    prefix="/training/league",
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
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    # Team-scoped write: ownership is enforced server-side. This was gated
    # by authentication only, so any signed-in user could edit another
    # club's data. Admins short-circuit inside require_team_owner.
    require_team_owner(identity, team_id)

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
def reset_training(
    team_id: str,
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    # Team-scoped write: ownership is enforced server-side. This was gated
    # by authentication only, so any signed-in user could edit another
    # club's data. Admins short-circuit inside require_team_owner.
    require_team_owner(identity, team_id)

    clear_team_training_weights(team_id)
    return _serialize(team_id)


def _serialize_player(player_id: str, team_id: str | None) -> Dict[str, Any]:
    settings = load_training_settings()
    weights = settings.for_player(player_id, team_id)
    pid = str(player_id)
    if pid in settings.player_overrides:
        source = "player"
    elif team_id and team_id in settings.team_overrides:
        source = "team"
    else:
        source = "defaults"
    return {
        "player_id": pid,
        "team_id": team_id,
        "source": source,
        "league_id": settings.league_id,
        "tracks": {
            "hitters": list(HITTER_TRACKS),
            "pitchers": list(PITCHER_TRACKS),
        },
        "hitters": {k: float(weights.hitters.get(k, 0.0)) for k in HITTER_TRACKS},
        "pitchers": {
            k: float(weights.pitchers.get(k, 0.0)) for k in PITCHER_TRACKS
        },
        "defaults": {
            "hitters": {
                k: float(settings.defaults.hitters.get(k, 0.0))
                for k in HITTER_TRACKS
            },
            "pitchers": {
                k: float(settings.defaults.pitchers.get(k, 0.0))
                for k in PITCHER_TRACKS
            },
        },
    }


@player_router.get("")
def get_player_training(
    player_id: str,
    team_id: str | None = None,
) -> Dict[str, Any]:
    return _serialize_player(player_id, team_id)


@player_router.put("")
def save_player_training(
    player_id: str,
    payload: Dict[str, Any] = Body(...),
    team_id: str | None = None,
) -> Dict[str, Any]:
    hitters = payload.get("hitters")
    pitchers = payload.get("pitchers")
    if not isinstance(hitters, dict) or not isinstance(pitchers, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hitters and pitchers must be objects mapping track -> percent.",
        )
    try:
        set_player_training_weights(player_id, hitters, pitchers)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize_player(player_id, team_id)


@player_router.delete("")
def reset_player_training(
    player_id: str,
    team_id: str | None = None,
) -> Dict[str, Any]:
    clear_player_training_weights(player_id)
    return _serialize_player(player_id, team_id)


def _serialize_league() -> Dict[str, Any]:
    settings = load_training_settings()
    return {
        "league_id": settings.league_id,
        "tracks": {
            "hitters": list(HITTER_TRACKS),
            "pitchers": list(PITCHER_TRACKS),
        },
        "hitters": {
            k: float(settings.defaults.hitters.get(k, 0.0)) for k in HITTER_TRACKS
        },
        "pitchers": {
            k: float(settings.defaults.pitchers.get(k, 0.0)) for k in PITCHER_TRACKS
        },
    }


@league_router.get("")
def get_league_training() -> Dict[str, Any]:
    return _serialize_league()


@league_router.put("")
def save_league_training(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    hitters = payload.get("hitters")
    pitchers = payload.get("pitchers")
    if not isinstance(hitters, dict) or not isinstance(pitchers, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hitters and pitchers must be objects mapping track -> percent.",
        )
    try:
        update_league_training_defaults(hitters, pitchers)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize_league()
