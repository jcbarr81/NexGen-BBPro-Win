"""Roster endpoint for a single team.

Ports the data side of ``ui/roster_page.py``: returns the team's roster
split by level (ACT / AAA / LOW / DL / IR) with each player hydrated to a
lightweight summary so the React table can render without a second trip.

Read-only in Phase 4 iteration 1. Editing moves (promote, demote, DL) ride
on top in a follow-up and will use the existing ``services.roster_moves``
module.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, status

from services.roster_moves import cut_player
from services.transaction_log import record_transaction
from utils.pitcher_role import get_display_role, get_role
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster

from ..security import CurrentIdentity
from ._rating_presentation import compute_overall, rating_context, scale_rating

router = APIRouter(prefix="/teams/{team_id}", tags=["roster"], dependencies=[CurrentIdentity])

_RATING_FIELDS = (
    "ch",
    "ph",
    "sp",
    "eye",
    "gf",
    "pl",
    "vl",
    "sc",
    "fa",
    "arm",
)
_PITCHER_RATING_FIELDS = (
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "fb",
    "cu",
    "cb",
    "sl",
    "si",
    "scb",
    "kn",
)


def _player_summary(player: Any, level: str, dl_tier: str | None = None) -> Dict[str, Any]:
    is_pitcher = bool(getattr(player, "is_pitcher", False))
    position = getattr(player, "primary_position", None)

    ratings: Dict[str, Any] = {}
    ratings_context: Dict[str, Dict[str, Any]] = {}
    for key in _RATING_FIELDS:
        raw = getattr(player, key, None)
        if raw is None:
            continue
        ratings[key] = scale_rating(
            raw, key=key, position=position, is_pitcher=is_pitcher
        )
        ctx = rating_context(
            raw, key=key, position=position, is_pitcher=is_pitcher
        )
        if ctx is not None:
            ratings_context[key] = ctx
    if is_pitcher:
        for key in _PITCHER_RATING_FIELDS:
            raw = getattr(player, key, None)
            if raw is None:
                continue
            ratings[key] = scale_rating(
                raw, key=key, position=position, is_pitcher=is_pitcher
            )

    overall = compute_overall(
        lambda k: getattr(player, k, None),
        is_pitcher=is_pitcher,
        position=position,
    )

    birthdate = getattr(player, "birthdate", "") or ""
    age: Optional[int] = None
    if birthdate:
        try:
            birth = datetime.strptime(str(birthdate), "%Y-%m-%d").date()
            today = date.today()
            age = today.year - birth.year - (
                (today.month, today.day) < (birth.month, birth.day)
            )
        except ValueError:
            age = None

    # For pitchers, prefer ``preferred_pitching_role`` (the granular
    # SP/RP/CL/LR/MR/SU value the user actually maintains) over the raw
    # ``role`` CSV column, which is stale on every row in the seed data
    # (all 272 pitchers ship with role="RP" even when they're starters).
    # Bucket the granular value to SP/RP for the high-level role tab; the
    # raw granular value is exposed below as ``preferred_pitching_role``.
    raw_role = str(getattr(player, "role", "") or "").strip()
    if is_pitcher:
        display = get_display_role(player)
        resolved_role = "SP" if str(display).upper() == "SP" else (
            "RP" if display else (get_role(player) or raw_role)
        )
    else:
        resolved_role = raw_role

    return {
        "player_id": getattr(player, "player_id", ""),
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "primary_position": getattr(player, "primary_position", ""),
        "other_positions": getattr(player, "other_positions", "") or "",
        "bats": getattr(player, "bats", "") or "",
        "throws": getattr(player, "throws", "") or "",
        "role": resolved_role,
        "preferred_pitching_role": (
            getattr(player, "preferred_pitching_role", "") or ""
        ),
        "birthdate": str(birthdate) if birthdate else "",
        "age": age,
        "is_pitcher": is_pitcher,
        "injured": bool(getattr(player, "injured", False)),
        "injury_description": getattr(player, "injury_description", "") or "",
        "ratings_context": ratings_context,
        "overall_raw": overall["overall_raw"],
        "overall_display": overall["overall_display"],
        "overall_stars_text": overall["overall_stars_text"],
        "level": level,
        "dl_tier": dl_tier,
        "ratings": ratings,
    }


@router.get("/roster")
def team_roster(team_id: str) -> Dict[str, Any]:
    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load roster for {team_id}: {exc}",
        ) from exc

    try:
        players_list = load_players_from_csv("data/players.csv")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load players.csv: {exc}",
        ) from exc
    players_by_id = {getattr(p, "player_id", ""): p for p in players_list}

    def _hydrate(ids: List[str], level: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for pid in ids:
            player = players_by_id.get(pid)
            if player is None:
                # Unknown id -- surface as a stub so the UI still shows
                # something recognizable.
                out.append(
                    {
                        "player_id": pid,
                        "first_name": "",
                        "last_name": pid,
                        "primary_position": "",
                        "other_positions": "",
                        "bats": "",
                        "throws": "",
                        "role": "",
                        "preferred_pitching_role": "",
                        "birthdate": "",
                        "age": None,
                        "is_pitcher": False,
                        "injured": False,
                        "injury_description": "",
                        "level": level,
                        "dl_tier": None,
                        "ratings": {},
                    }
                )
                continue
            dl_tier = roster.dl_tiers.get(pid) if level == "DL" else None
            out.append(_player_summary(player, level, dl_tier))
        return out

    return {
        "team_id": team_id,
        "active_size": len(roster.act),
        "levels": {
            "ACT": _hydrate(roster.act, "ACT"),
            "AAA": _hydrate(roster.aaa, "AAA"),
            "LOW": _hydrate(roster.low, "LOW"),
            "DL": _hydrate(roster.dl, "DL"),
            "IR": _hydrate(roster.ir, "IR"),
        },
    }


# ---------------------------------------------------------------------------
# Write actions (promote / demote / DL / IR / cut)

_LEVEL_ATTR = {"ACT": "act", "AAA": "aaa", "LOW": "low", "DL": "dl", "IR": "ir"}
Level = Literal["ACT", "AAA", "LOW", "DL", "IR"]


def _find_level(roster, player_id: str) -> Optional[str]:
    for label, attr in _LEVEL_ATTR.items():
        if player_id in getattr(roster, attr, []):
            return label
    return None


@router.post("/roster/move")
def move_roster(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    to_level = str(payload.get("to", "")).strip().upper()
    dl_tier = str(payload.get("dl_tier", "")).strip().lower() or None

    if not player_id or to_level not in _LEVEL_ATTR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id and a valid 'to' level are required.",
        )

    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load roster: {exc}",
        ) from exc

    from_level = _find_level(roster, player_id)
    if from_level is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{player_id} is not on {team_id}'s roster.",
        )
    if from_level == to_level:
        return team_roster(team_id)

    # Run the shared roster-move validator before mutating state.
    from services.roster_validation import DEFAULT_LEVEL_CAPS, validate_roster_move

    from .validation import load_players_map, load_team_levels

    players_map = load_players_map()
    current_levels = load_team_levels(team_id)
    result = validate_roster_move(
        current_levels=current_levels,
        player_id=player_id,
        target_level=to_level.lower(),
        players=players_map,
        level_caps=DEFAULT_LEVEL_CAPS,
    )
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Roster move would violate league rules.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    try:
        roster.move_player(player_id, _LEVEL_ATTR[from_level], _LEVEL_ATTR[to_level])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if to_level == "DL" and dl_tier in {"dl15", "dl45"}:
        roster.dl_tiers[player_id] = dl_tier

    try:
        save_roster(team_id, roster)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save roster: {exc}",
        ) from exc

    try:
        record_transaction(
            action="assign",
            team_id=team_id,
            player_id=player_id,
            from_level=from_level,
            to_level=to_level,
            details=(
                f"Moved from {from_level} to {to_level}"
                + (f" ({dl_tier})" if dl_tier else "")
            ),
        )
    except Exception:
        pass

    return team_roster(team_id)


@router.post("/roster/cut")
def cut_roster(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )
    try:
        cut_player(team_id, player_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cut: {exc}",
        ) from exc
    return team_roster(team_id)
