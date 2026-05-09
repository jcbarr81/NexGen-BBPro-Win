"""League stats endpoint.

Mirrors ``ui/league_stats_window.py``: returns every player's batting or
pitching line plus team totals, all hydrated from
``data/season_stats.json``.
"""

from __future__ import annotations

import csv
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from utils.path_utils import get_data_dir
from utils.stats_persistence import load_stats as _load_season_stats

from ..security import CurrentIdentity

router = APIRouter(prefix="/league", tags=["stats"], dependencies=[CurrentIdentity])
team_router = APIRouter(prefix="/teams", tags=["stats"], dependencies=[CurrentIdentity])

BATTING_COLUMNS: List[str] = [
    "g", "ab", "r", "h", "2b", "3b", "hr", "rbi", "bb", "so", "sb",
    "avg", "obp", "slg",
]
PITCHING_COLUMNS: List[str] = [
    "w", "l", "era", "g", "gs", "sv", "ip", "h", "er", "bb", "so", "whip",
]
TEAM_COLUMNS: List[str] = ["g", "w", "l", "r", "ra"]


def _normalize_player(stats: Dict[str, Any] | None) -> Dict[str, Any]:
    s = dict(stats or {})
    if "b2" in s and "2b" not in s:
        s["2b"] = s["b2"]
    if "b3" in s and "3b" not in s:
        s["3b"] = s["b3"]
    s.setdefault("w", s.get("wins", s.get("w", 0)))
    s.setdefault("l", s.get("losses", s.get("l", 0)))
    return s


def _row(stat_block: Dict[str, Any], cols: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for col in cols:
        v = stat_block.get(col)
        if v is None:
            out[col] = None
            continue
        # Try numeric coercion so React can sort/format consistently.
        try:
            f = float(v)
            out[col] = int(f) if f.is_integer() and col not in {"avg", "obp", "slg", "era", "whip", "ip"} else f
        except (TypeError, ValueError):
            out[col] = str(v)
    return out


@router.get("/stats")
def league_stats() -> Dict[str, Any]:
    try:
        season = _load_season_stats()
    except Exception:
        season = {"players": {}, "teams": {}}

    player_stats = season.get("players") or {}
    team_stats = season.get("teams") or {}

    # Player meta from CSV (avoids invoking the heavier player loader).
    meta: Dict[str, Dict[str, str]] = {}
    players_path = get_data_dir() / "players.csv"
    try:
        with players_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                meta[row["player_id"]] = row
    except OSError:
        meta = {}

    batters: List[Dict[str, Any]] = []
    pitchers: List[Dict[str, Any]] = []
    for pid, info in meta.items():
        is_pitcher = str(info.get("is_pitcher", "")).strip().lower() in {"1", "true", "yes"}
        block = _normalize_player(player_stats.get(pid))
        # Skip players with no stat sample at all to keep the table compact.
        if not block:
            continue
        entry = {
            "player_id": pid,
            "first_name": info.get("first_name", ""),
            "last_name": info.get("last_name", ""),
            "primary_position": info.get("primary_position", ""),
            "is_pitcher": is_pitcher,
            "stats": _row(block, PITCHING_COLUMNS if is_pitcher else BATTING_COLUMNS),
        }
        (pitchers if is_pitcher else batters).append(entry)

    teams: List[Dict[str, Any]] = []
    for tid, info in team_stats.items():
        teams.append(
            {
                "team_id": tid,
                "stats": _row(dict(info or {}), TEAM_COLUMNS),
            }
        )

    return {
        "columns": {
            "batters": BATTING_COLUMNS,
            "pitchers": PITCHING_COLUMNS,
            "teams": TEAM_COLUMNS,
        },
        "batters": batters,
        "pitchers": pitchers,
        "teams": teams,
    }


@team_router.get("/{team_id}/stats")
def team_stats(team_id: str) -> Dict[str, Any]:
    """Port of ui/team_stats_window.py — roster-filtered player lines + team totals."""

    try:
        season = _load_season_stats()
    except Exception:
        season = {"players": {}, "teams": {}}

    player_stats = season.get("players") or {}
    team_stats_map = season.get("teams") or {}

    players_path = get_data_dir() / "players.csv"
    try:
        with players_path.open("r", encoding="utf-8", newline="") as handle:
            all_meta = {row["player_id"]: row for row in csv.DictReader(handle)}
    except OSError:
        all_meta = {}

    # Restrict to players currently rostered by the target team. Roster
    # CSVs are written headerless by ``utils.roster_io.write_roster_csv``
    # as ``[player_id, level]`` rows — DictReader would treat the first
    # data row as the header and quietly return empty player_ids for
    # every subsequent row.
    roster_ids: set[str] = set()
    roster_path = get_data_dir() / "rosters" / f"{team_id}.csv"
    try:
        with roster_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if not row:
                    continue
                pid = (row[0] or "").strip()
                if pid:
                    roster_ids.add(pid)
    except OSError:
        pass

    if not roster_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No roster entries for team {team_id}.",
        )

    batters: List[Dict[str, Any]] = []
    pitchers: List[Dict[str, Any]] = []
    for pid in sorted(roster_ids):
        info = all_meta.get(pid)
        if not info:
            continue
        is_pitcher = str(info.get("is_pitcher", "")).strip().lower() in {"1", "true", "yes"}
        block = _normalize_player(player_stats.get(pid))
        if not block:
            continue
        entry = {
            "player_id": pid,
            "first_name": info.get("first_name", ""),
            "last_name": info.get("last_name", ""),
            "primary_position": info.get("primary_position", ""),
            "is_pitcher": is_pitcher,
            "stats": _row(block, PITCHING_COLUMNS if is_pitcher else BATTING_COLUMNS),
        }
        (pitchers if is_pitcher else batters).append(entry)

    team_block = team_stats_map.get(team_id) or {}
    team_totals = _row(dict(team_block), TEAM_COLUMNS)

    return {
        "team_id": team_id,
        "columns": {
            "batters": BATTING_COLUMNS,
            "pitchers": PITCHING_COLUMNS,
            "team": TEAM_COLUMNS,
        },
        "batters": batters,
        "pitchers": pitchers,
        "team_totals": team_totals,
    }
