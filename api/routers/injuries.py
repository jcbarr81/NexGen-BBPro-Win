"""Injury center endpoint.

Surfaces a team's DL + IR rosters with descriptions, list type, return
date and days remaining. Reuses the same helpers the PyQt
``ui/injury_center_window.py`` calls.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.injury_manager import (
    disabled_list_days_remaining,
    disabled_list_label,
    injury_list_for,
    is_player_dl_eligible,
    place_on_injury_list,
    recover_from_injury,
)
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster

from ..security import CurrentIdentity, require_bearer, require_team_owner

router = APIRouter(prefix="/teams/{team_id}", tags=["injuries"], dependencies=[CurrentIdentity])


def _sim_today() -> date:
    """The league's current date — the clock the injured list is measured in."""

    try:
        from utils.sim_date import get_current_sim_date

        sim_date = (get_current_sim_date() or "").strip()
        if sim_date:
            return date.fromisoformat(sim_date[:10])
    except Exception:  # pragma: no cover - defensive
        pass
    return date.today()


def _player_block(player: Any, level: str, dl_tier: str | None) -> Dict[str, Any]:
    today = _sim_today()
    days_remaining: int | None = None
    try:
        days_remaining = disabled_list_days_remaining(player, today)
    except Exception:
        days_remaining = None
    eligible = False
    try:
        eligible = bool(is_player_dl_eligible(player, today))
    except Exception:
        eligible = False
    return {
        "player_id": getattr(player, "player_id", ""),
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "primary_position": getattr(player, "primary_position", ""),
        "is_pitcher": bool(getattr(player, "is_pitcher", False)),
        "level": level,
        "dl_tier": dl_tier,
        "list_label": disabled_list_label(dl_tier or ""),
        "injury_description": getattr(player, "injury_description", "") or "",
        "return_date": getattr(player, "return_date", "") or "",
        "injury_eligible_date": getattr(player, "injury_eligible_date", "") or "",
        "injury_start_date": getattr(player, "injury_start_date", "") or "",
        "injury_minimum_days": getattr(player, "injury_minimum_days", "") or "",
        "days_remaining": days_remaining,
        "dl_eligible": eligible,
    }


@router.get("/injuries")
def team_injuries(team_id: str) -> Dict[str, Any]:
    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load roster for {team_id}: {exc}",
        ) from exc

    try:
        players_by_id = {
            getattr(p, "player_id", ""): p
            for p in load_players_from_csv("data/players.csv")
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load players.csv: {exc}",
        ) from exc

    dl: List[Dict[str, Any]] = []
    for pid in roster.dl:
        player = players_by_id.get(pid)
        if player is None:
            continue
        dl.append(_player_block(player, "DL", roster.dl_tiers.get(pid, "dl15")))

    ir: List[Dict[str, Any]] = []
    for pid in roster.ir:
        player = players_by_id.get(pid)
        if player is None:
            continue
        ir.append(_player_block(player, "IR", "ir"))

    # Also surface ACT players flagged as injured (day-to-day) so the
    # owner can see them in one place even when not on a list.
    day_to_day: List[Dict[str, Any]] = []
    for pid in roster.act:
        player = players_by_id.get(pid)
        if player is None:
            continue
        if bool(getattr(player, "injured", False)):
            day_to_day.append(_player_block(player, "ACT", None))

    eligible_to_activate = sum(1 for p in dl if p.get("dl_eligible"))
    return {
        "team_id": team_id,
        "counts": {
            "dl": len(dl),
            "ir": len(ir),
            "day_to_day": len(day_to_day),
            "eligible_to_activate": eligible_to_activate,
        },
        "dl": dl,
        "ir": ir,
        "day_to_day": day_to_day,
    }


# ---------------------------------------------------------------------------
# Owner controls
#
# Both sides of the injured list used to be entirely machine-driven: the sim
# placed players and the automation activated them, with no way for an owner to
# say "I'll put him on the list to free a spot" or "I want him back today". In
# MLB both are team decisions, so they are owner actions here — gated by
# ``require_team_owner`` (commissioners and super-admins pass, matching the
# finance actions).


def _load_team(team_id: str):
    from utils.roster_loader import load_roster, save_roster

    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No roster for team {team_id}: {exc}",
        ) from exc
    return roster, save_roster


def _find_player(player_id: str):
    for player in load_players_from_csv("data/players.csv"):
        if getattr(player, "player_id", "") == player_id:
            return player
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Player {player_id} not found."
    )


def _persist(team_id: str, roster, save_roster, player) -> None:
    from services.players_repository import save_players

    save_roster(team_id, roster)
    try:
        save_players([player])
    except Exception:  # pragma: no cover - defensive
        pass


@router.post("/injuries/{player_id}/place")
def place_on_list(
    team_id: str,
    player_id: str,
    payload: Dict[str, Any] = Body(default=None),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Put an injured player on an injured list.

    MLB requires a medical reason, so a healthy player cannot be stashed here to
    free a roster spot. The list is chosen by role (10-day for position players,
    15-day for pitchers) unless the caller explicitly asks for the 60-day.
    """

    require_team_owner(identity, team_id)
    roster, save_roster = _load_team(team_id)
    player = _find_player(player_id)

    if player_id not in list(getattr(roster, "act", []) or []):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an active-roster player can be placed on an injured list.",
        )
    if not bool(getattr(player, "injured", False)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{getattr(player, 'first_name', '')} "
                f"{getattr(player, 'last_name', '')}".strip()
                + " isn't injured. Only an injured player can go on the list."
            ),
        )

    requested = str((payload or {}).get("list_name") or "").strip().lower()
    try:
        tier = injury_list_for(player, requested or "dl15")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown injured list {requested!r}.",
        )

    try:
        # No explicit date: place_on_injury_list defaults to the SIM date.
        place_on_injury_list(player, roster, list_name=tier)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    _persist(team_id, roster, save_roster, player)
    return {
        "team_id": team_id,
        "player_id": player_id,
        "injury_list": getattr(player, "injury_list", ""),
        "list_label": disabled_list_label(getattr(player, "injury_list", "")),
        "injury_eligible_date": getattr(player, "injury_eligible_date", "") or "",
        "days_remaining": disabled_list_days_remaining(player, _sim_today()),
    }


@router.post("/injuries/{player_id}/activate")
def activate_from_list(
    team_id: str,
    player_id: str,
    payload: Dict[str, Any] = Body(default=None),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Activate a player whose minimum stint has elapsed.

    The owner picks the destination rather than being silently optioned: the
    automation falls back to AAA when the active roster is full, which is not a
    choice anyone asked for.
    """

    require_team_owner(identity, team_id)
    roster, save_roster = _load_team(team_id)
    player = _find_player(player_id)

    on_a_list = player_id in list(getattr(roster, "dl", []) or []) or player_id in list(
        getattr(roster, "ir", []) or []
    )
    if not on_a_list:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That player isn't on an injured list.",
        )

    destination = str((payload or {}).get("destination") or "act").strip().lower()
    if destination not in {"act", "aaa", "low"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="destination must be one of act, aaa or low.",
        )

    if destination == "act":
        from utils.roster_loader import active_roster_cap

        if len(list(getattr(roster, "act", []) or [])) >= active_roster_cap():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "act_full",
                    "message": (
                        "The active roster is full. Option a player down first "
                        "(Roster page), or activate him to AAA."
                    ),
                },
            )

    try:
        recover_from_injury(player, roster, destination=destination, today=_sim_today())
    except ValueError as exc:
        # Still serving the minimum — the message carries the days remaining.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_yet_eligible", "message": str(exc)},
        ) from exc

    restored: Dict[str, str] = {}
    if destination == "act":
        try:
            from services.lineup_restore import restore_depth_chart_starter
            from utils.path_utils import get_data_dir

            restored = restore_depth_chart_starter(
                team_id,
                player_id,
                lineup_dir=get_data_dir() / "lineups",
                active_ids=list(getattr(roster, "act", []) or []),
            )
        except Exception:  # pragma: no cover - defensive
            restored = {}

    _persist(team_id, roster, save_roster, player)
    return {
        "team_id": team_id,
        "player_id": player_id,
        "destination": destination,
        "lineup_restored": restored,
    }
