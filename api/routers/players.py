"""Player list + detail endpoints sourced from ``players.csv``.

The list/detail endpoints surface a trimmed summary so the React table can
render fast. The ``/profile`` endpoint reuses the existing PyQt view-model
(``ui/player_profile_v2_viewmodel.py``) -- one source of truth for the
ratings/stats/contract/injury composition -- and serializes it for the
React profile page.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv

from ..schemas import PlayerSummary
from ..security import CurrentIdentity

router = APIRouter(prefix="/players", tags=["players"], dependencies=[CurrentIdentity])

_HEADLINE_RATINGS = ("ch", "ph", "sp", "eye", "arm", "fa", "control", "movement", "endurance")


def _row_to_summary(row: dict) -> PlayerSummary:
    ratings = {key: row.get(key) for key in _HEADLINE_RATINGS if row.get(key)}
    is_pitcher = str(row.get("is_pitcher", "")).strip().lower() in {"1", "true", "yes"}
    return PlayerSummary(
        player_id=row.get("player_id", ""),
        first_name=row.get("first_name", ""),
        last_name=row.get("last_name", ""),
        primary_position=row.get("primary_position", ""),
        is_pitcher=is_pitcher,
        bats=row.get("bats", "") or "",
        role=row.get("role", "") or "",
        ratings=ratings,
    )


def _iter_players():
    path = get_data_dir() / "players.csv"
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


@router.get("", response_model=List[PlayerSummary])
def list_players(
    position: Optional[str] = Query(default=None, description="Filter by primary_position"),
    pitchers_only: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=5000),
) -> List[PlayerSummary]:
    out: List[PlayerSummary] = []
    for row in _iter_players():
        summary = _row_to_summary(row)
        if pitchers_only and not summary.is_pitcher:
            continue
        if position and summary.primary_position.lower() != position.lower():
            continue
        out.append(summary)
        if len(out) >= limit:
            break
    return out


@router.get("/browse")
def browse_players(
    q: Optional[str] = Query(default=None, description="Substring match on name or id"),
    team_id: Optional[str] = Query(default=None),
    position: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None, description="Hitters/Pitchers/All"),
    free_agents_only: bool = Query(default=False),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> Dict[str, Any]:
    """League-wide player browser with team affiliation joined.

    Walks every team roster once to figure out who plays where (and which
    minors level they're on). Free agents are rows where no team claimed
    them. Filters apply server-side so the React table can stay light.
    """

    from utils.roster_loader import load_roster
    from utils.team_loader import load_teams

    # Build (team_id, level) lookup by walking each team's roster.
    affiliation: Dict[str, Dict[str, str]] = {}
    try:
        for team in load_teams():
            try:
                roster = load_roster(team.team_id)
            except Exception:
                continue
            for level, ids in (
                ("ACT", roster.act),
                ("AAA", roster.aaa),
                ("LOW", roster.low),
                ("DL", roster.dl),
                ("IR", roster.ir),
            ):
                for pid in ids:
                    affiliation.setdefault(
                        pid, {"team_id": team.team_id, "level": level}
                    )
    except Exception:
        affiliation = {}

    needle = q.strip().lower() if q else ""
    role_norm = role.strip().lower() if role else ""

    rows: List[Dict[str, Any]] = []
    for row in _iter_players():
        summary = _row_to_summary(row)
        if position and summary.primary_position.lower() != position.lower():
            continue
        if role_norm == "hitters" and summary.is_pitcher:
            continue
        if role_norm == "pitchers" and not summary.is_pitcher:
            continue

        affil = affiliation.get(summary.player_id)
        team = affil["team_id"] if affil else ""
        level = affil["level"] if affil else "FA"

        if free_agents_only and team:
            continue
        if team_id and team != team_id:
            continue
        if needle:
            haystack = (
                f"{summary.first_name} {summary.last_name} {summary.player_id}".lower()
            )
            if needle not in haystack:
                continue

        rows.append(
            {
                **summary.model_dump(),
                "team_id": team,
                "level": level,
            }
        )
        if len(rows) >= limit:
            break
    rows.sort(key=lambda r: (r["last_name"], r["first_name"]))
    return {"count": len(rows), "players": rows}


@router.get("/{player_id}", response_model=PlayerSummary)
def get_player(player_id: str) -> PlayerSummary:
    for row in _iter_players():
        if row.get("player_id") == player_id:
            return _row_to_summary(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")


def _coerce(value: Any) -> Any:
    """Recursively turn dataclasses / tuples / sets into JSON-friendly forms."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return _coerce(asdict(value))
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    return str(value)


@router.get("/{player_id}/profile")
def get_player_profile(player_id: str) -> Dict[str, Any]:
    """Hydrate a player and run the existing v2 view-model builder."""

    try:
        from ui.player_profile_v2_viewmodel import build_player_profile_view_model
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile view-model unavailable: {exc}",
        ) from exc

    try:
        players = load_players_from_csv("data/players.csv")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load players.csv: {exc}",
        ) from exc

    player = next((p for p in players if getattr(p, "player_id", "") == player_id), None)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found.",
        )

    try:
        view_model = build_player_profile_view_model(player)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build profile: {exc}",
        ) from exc

    return _coerce(view_model)
