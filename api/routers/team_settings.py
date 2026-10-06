"""Team settings endpoint.

Reads and writes the per-team configuration the PyQt
``ui/team_settings_dialog.py`` exposes: colors, stadium, team-strategy
profile (or league default), and auto-reassign override.

Reuses the existing helpers under ``utils.team_loader``,
``services.team_strategy_profiles`` and
``services.team_auto_reassign_settings`` -- nothing here re-implements
business logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from models.team import Team
from services.team_auto_reassign_settings import (
    resolve_team_auto_reassign,
    set_team_auto_reassign,
)
from services.team_strategy_profiles import (
    DEFAULT_PROFILE,
    STRATEGY_PROFILES,
    resolve_team_strategy_profile,
    set_team_strategy_profile,
)
from utils.team_loader import load_teams, save_team_settings

try:  # ballpark catalog is best-effort -- absent in some test fixtures
    from utils.park_utils import list_ballpark_names

    def _ballpark_names() -> List[str]:
        try:
            return list(list_ballpark_names())
        except Exception:
            return []
except Exception:  # pragma: no cover

    def _ballpark_names() -> List[str]:
        return []

from utils.park_utils import park_info_for_exact_name, park_info_for_id

from ..security import CurrentIdentity, require_bearer, require_team_owner

router = APIRouter(
    prefix="/teams/{team_id}/settings",
    tags=["team-settings"],
    dependencies=[CurrentIdentity],
)


def _team(team_id: str) -> Team:
    for team in load_teams():
        if team.team_id == team_id:
            return team
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Team {team_id} not found.",
    )


def _park_summary(team: Team) -> Optional[Dict[str, Any]]:
    """The catalog park whose real dimensions this team plays in, if explicit."""
    if not team.park_id:
        return None
    try:
        info = park_info_for_id(team.park_id, prefer_name=team.stadium)
    except Exception:
        return None
    if info is None:
        return None
    return {"park_id": info.park_id, "name": info.name, "year": info.year}


def _resolve_park_id(
    team: Team, new_stadium: str, payload: Dict[str, Any]
) -> Optional[str]:
    """Return the team's park_id after this save (audit L13).

    Saving here is a deliberate choice, so it is what makes a park explicit:
    an explicit ``park_id`` (from the catalog browser) wins; otherwise a
    stadium the owner CHANGED to an exact catalog name picks that park, and
    any other new name is the generic park. An unchanged stadium keeps its
    current park_id, so a colors-only save never turns a generated name like
    "Royals Stadium" into Kauffman's geometry. Legacy leagues (park_id None)
    stay on the name lookup and are left alone.
    """
    if team.park_id is None:
        return None
    if "park_id" in payload:
        requested = str(payload.get("park_id") or "").strip()
        if not requested:
            return ""
        info = park_info_for_id(requested, prefer_name=new_stadium)
        if info is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown ballpark id: {requested}",
            )
        return info.park_id
    if new_stadium.strip() == (team.stadium or "").strip():
        return team.park_id
    info = park_info_for_exact_name(new_stadium)
    return info.park_id if info is not None and info.park_id else ""


def _serialize(team_id: str) -> Dict[str, Any]:
    team = _team(team_id)
    strategy = resolve_team_strategy_profile(team_id)
    auto_reassign = resolve_team_auto_reassign(team_id)
    profiles = [
        {
            "id": pid,
            "label": str(meta.get("label", pid.title())),
            "description": str(meta.get("description", "")),
        }
        for pid, meta in STRATEGY_PROFILES.items()
    ]
    return {
        "team_id": team.team_id,
        "name": team.name,
        "city": team.city,
        "abbreviation": team.abbreviation,
        "division": team.division,
        "stadium": team.stadium,
        # Audit L13: null = legacy league (park resolved by name, as before);
        # "" = generic park; otherwise the explicitly chosen catalog park.
        "park_id": team.park_id,
        "park": _park_summary(team),
        "primary_color": team.primary_color,
        "secondary_color": team.secondary_color,
        "strategy": {
            "profile": strategy.profile,
            "label": strategy.label,
            "description": strategy.description,
            "source": strategy.source,
        },
        "auto_reassign": {
            "enabled": auto_reassign.enabled,
            "source": auto_reassign.source,
        },
        "options": {
            "strategies": profiles,
            "default_strategy": DEFAULT_PROFILE,
            "ballparks": _ballpark_names(),
        },
    }


@router.get("")
def get_settings(team_id: str) -> Dict[str, Any]:
    return _serialize(team_id)


@router.put("")
def save_settings(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    # Team-scoped write: ownership is enforced server-side. This was gated
    # by authentication only, so any signed-in user could edit another
    # club's data. Admins short-circuit inside require_team_owner.
    require_team_owner(identity, team_id)

    team = _team(team_id)

    # Pluck only the editable fields. None means "leave unchanged".
    primary = payload.get("primary_color")
    secondary = payload.get("secondary_color")
    stadium = payload.get("stadium")
    strategy: Optional[str] = payload.get("strategy")
    auto_reassign = payload.get("auto_reassign", "__missing__")

    new_primary = str(primary) if primary is not None else team.primary_color
    new_secondary = (
        str(secondary) if secondary is not None else team.secondary_color
    )
    new_stadium = str(stadium) if stadium is not None else team.stadium
    new_park_id = _resolve_park_id(team, new_stadium, payload)

    try:
        save_team_settings(
            Team(
                team_id=team.team_id,
                name=team.name,
                city=team.city,
                abbreviation=team.abbreviation,
                division=team.division,
                stadium=new_stadium,
                primary_color=new_primary,
                secondary_color=new_secondary,
                owner_id=team.owner_id,
                park_id=new_park_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if strategy is not None:
        # "" / "default" / a valid profile id -- helper handles all cases.
        result = set_team_strategy_profile(team_id, strategy)
        if not result.get("saved", True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(result.get("message", "Invalid strategy.")),
            )

    if auto_reassign != "__missing__":
        result = set_team_auto_reassign(team_id, auto_reassign)
        if not result.get("saved", True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(result.get("message", "Invalid auto-reassign value.")),
            )

    return _serialize(team_id)
