"""Validation probe endpoints.

Thin wrappers around ``services.roster_validation`` so the Electron UI can
run the same checks the save endpoints enforce — useful for live feedback
while the user edits (e.g. disable Save while errors exist).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from fastapi import APIRouter, Body, HTTPException, status

from services.roster_validation import (
    DEFAULT_LEVEL_CAPS,
    PITCHING_ROLES,
    validate_depth_chart,
    validate_lineup,
    validate_pitching_staff,
    validate_roster_move,
    validate_trade,
)
from utils.path_utils import get_data_dir

from ..security import CurrentIdentity

router = APIRouter(tags=["validation"], dependencies=[CurrentIdentity])


def load_players_map() -> Dict[str, Dict[str, Any]]:
    """Return a dict keyed by player_id with the CSV columns needed for
    validation. Cheap to call because we only read players.csv."""

    path = get_data_dir() / "players.csv"
    out: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = (row.get("player_id") or "").strip()
            if not pid:
                continue
            out[pid] = {
                "player_id": pid,
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "primary_position": row.get("primary_position", ""),
                "other_positions": row.get("other_positions", ""),
                "is_pitcher": row.get("is_pitcher", ""),
                "age": row.get("age", "") or None,
                # Fields used by utils.pitching_autofill — without these the
                # pitching-staff auto-fill would silently filter every pitcher
                # because get_role() / get_display_role() see no signal.
                "role": row.get("role", ""),
                "preferred_pitching_role": row.get("preferred_pitching_role", ""),
                "endurance": row.get("endurance", ""),
                "ratings": {
                    k[len("rating_") :]: row[k]
                    for k in row
                    if k.startswith("rating_")
                },
            }
    return out


def load_team_levels(team_id: str) -> Dict[str, List[str]]:
    """Return a {level: [player_id...]} map loaded from rosters/{team}.csv.

    Roster files are written headerless by ``utils.roster_io.write_roster_csv``
    as ``[player_id, level]`` rows, with ``DL15``/``DL45``/``IR`` mapped onto
    the ``dl``/``ir`` buckets — match that exactly so depth-chart and
    pitching-staff validation see the same roster the rest of the app does.
    """

    path = get_data_dir() / "rosters" / f"{team_id}.csv"
    levels: Dict[str, List[str]] = {"act": [], "aaa": [], "low": [], "dl": [], "ir": []}
    if not path.exists():
        return levels
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if len(row) < 2:
                continue
            pid = (row[0] or "").strip()
            if not pid:
                continue
            tag = (row[1] or "").strip().upper()
            if tag == "ACT":
                levels["act"].append(pid)
            elif tag == "AAA":
                levels["aaa"].append(pid)
            elif tag == "LOW":
                levels["low"].append(pid)
            elif tag in {"DL", "DL15"}:
                levels["dl"].append(pid)
            elif tag in {"DL45", "IR"}:
                levels["ir"].append(pid)
    return levels


# ---------------------------------------------------------------------------
# Lineup


@router.post("/teams/{team_id}/lineup/{vs}/validate")
def validate_lineup_endpoint(
    team_id: str,
    vs: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    rows = payload.get("lineup")
    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="lineup must be a list."
        )
    players = load_players_map()
    result = validate_lineup(lineup_rows=rows, players=players, vs=vs)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Pitching staff


@router.post("/teams/{team_id}/pitching/validate")
def validate_pitching_endpoint(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    staff = payload.get("staff")
    if not isinstance(staff, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="staff must be a list."
        )
    players = load_players_map()
    active_ids = load_team_levels(team_id).get("act", [])
    result = validate_pitching_staff(
        staff=staff, players=players, active_ids=active_ids
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Depth chart


@router.post("/teams/{team_id}/depth-chart/validate")
def validate_depth_chart_endpoint(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chart must be an object.",
        )
    players = load_players_map()
    levels = load_team_levels(team_id)
    roster_ids: List[str] = []
    for v in levels.values():
        roster_ids.extend(v)
    result = validate_depth_chart(
        chart=chart, players=players, roster_ids=roster_ids
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Roster move


@router.post("/teams/{team_id}/roster/validate-move")
def validate_roster_move_endpoint(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    target_level = str(payload.get("target_level", "")).strip()
    if not player_id or not target_level:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id and target_level are required.",
        )
    players = load_players_map()
    levels = load_team_levels(team_id)
    result = validate_roster_move(
        current_levels=levels,
        player_id=player_id,
        target_level=target_level,
        players=players,
        level_caps=DEFAULT_LEVEL_CAPS,
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Trade


@router.post("/trades/validate")
def validate_trade_endpoint(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from_team = str(payload.get("from_team", "")).strip()
    to_team = str(payload.get("to_team", "")).strip()
    if not from_team or not to_team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_team and to_team are required.",
        )
    give_player_ids = _string_list(payload.get("give_player_ids"))
    receive_player_ids = _string_list(payload.get("receive_player_ids"))
    give_pick_ids = _string_list(payload.get("give_pick_ids"))
    receive_pick_ids = _string_list(payload.get("receive_pick_ids"))
    settings = payload.get("settings") or {}
    payroll_result = payload.get("payroll_result")
    tradable_from = payload.get("tradable_pick_ids_from")
    tradable_to = payload.get("tradable_pick_ids_to")

    players = load_players_map()
    from_levels = load_team_levels(from_team)
    to_levels = load_team_levels(to_team)
    result = validate_trade(
        give_player_ids=give_player_ids,
        receive_player_ids=receive_player_ids,
        give_pick_ids=give_pick_ids,
        receive_pick_ids=receive_pick_ids,
        from_team_levels=from_levels,
        to_team_levels=to_levels,
        players=players,
        settings=settings if isinstance(settings, dict) else {},
        payroll_result=payroll_result if isinstance(payroll_result, dict) else None,
        tradable_pick_ids_from=tradable_from if isinstance(tradable_from, list) else None,
        tradable_pick_ids_to=tradable_to if isinstance(tradable_to, list) else None,
    )
    return result.to_dict()


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if str(v)]


__all__ = ["router", "load_players_map", "load_team_levels"]
