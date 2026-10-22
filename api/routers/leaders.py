"""League leaders endpoint.

Mirrors the categories + qualifier logic from
``ui/league_leaders_window.py`` and surfaces the top N for each one in a
single response. Uses the same helpers (``top_players``, season stats
loader) so numbers match the PyQt build exactly.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, status

from utils.stat_helpers import top_players
from utils.player_loader import load_players_from_csv
# Cached read-only variant (S1-05) — this router never mutates the payload.
from utils.stats_persistence import load_stats_cached as _load_season_stats

from ..security import CurrentIdentity

router = APIRouter(prefix="/league", tags=["leaders"], dependencies=[CurrentIdentity])


# (label, stat key, descending, pitcher_only, decimals)
_BATTING: List[Tuple[str, str, bool, bool, int]] = [
    ("Average", "avg", True, False, 3),
    ("Home Runs", "hr", True, False, 0),
    ("RBI", "rbi", True, False, 0),
    ("Stolen Bases", "sb", True, False, 0),
    ("On-Base %", "obp", True, False, 3),
]
_PITCHING: List[Tuple[str, str, bool, bool, int]] = [
    ("ERA", "era", False, True, 2),
    ("WHIP", "whip", False, True, 2),
    ("Wins", "w", True, True, 0),
    ("Strikeouts", "so", True, True, 0),
    ("Saves", "sv", True, True, 0),
]


def _batter_pa(stats: Dict[str, Any]) -> int:
    try:
        ab = int(stats.get("ab", 0) or 0)
        bb = int(stats.get("bb", 0) or 0)
        hbp = int(stats.get("hbp", 0) or 0)
        sf = int(stats.get("sf", 0) or 0)
        sh = int(stats.get("sh", 0) or 0)
        return ab + bb + hbp + sf + sh
    except Exception:
        return 0


def _pitcher_ip(stats: Dict[str, Any]) -> float:
    try:
        ip = stats.get("ip")
        if ip is None:
            outs = stats.get("outs") or 0
            ip = float(outs) / 3.0
        return float(ip or 0)
    except Exception:
        return 0.0


def _qualified(
    stats: Dict[str, Any],
    *,
    pitcher_only: bool,
    apply_qualifier: bool,
    min_pa: int,
    min_ip: int,
) -> bool:
    if pitcher_only and apply_qualifier and min_ip:
        if _pitcher_ip(stats) < min_ip:
            return False
    if not pitcher_only and apply_qualifier and min_pa:
        if _batter_pa(stats) < min_pa:
            return False
    return True


def _has_sample(stats: Dict[str, Any], key: str) -> bool:
    try:
        if key in {"era", "whip"}:
            return _pitcher_ip(stats) > 0
        if key == "avg":
            return int(stats.get("ab", 0) or 0) > 0
        if key == "obp":
            return (
                float(stats.get("ab", 0) or 0)
                + float(stats.get("bb", 0) or 0)
                + float(stats.get("hbp", 0) or 0)
                + float(stats.get("sf", 0) or 0)
            ) > 0
    except Exception:
        return False
    return True


def _player_label(
    player: Any, team_index: Dict[str, str] | None = None
) -> Dict[str, Any]:
    """Label a leaderboard row.

    ``team_id`` has to come from the roster files: players.csv carries no such
    column, so ``player.team_id`` is always empty and the client — which
    renders the team chip only when one is present — showed none at all.
    """

    player_id = getattr(player, "player_id", "")
    team_id = str(getattr(player, "team_id", "") or "")
    if not team_id and team_index is not None:
        team_id = team_index.get(str(player_id), "")
    return {
        "player_id": player_id,
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "team_id": team_id,
    }


@router.get("/leaders/postseasons")
def postseason_years() -> Dict[str, Any]:
    """The postseasons there are leaders for, newest first (8.4.0)."""

    from services.postseason_stats import list_postseasons

    try:
        postseasons = list_postseasons()
    except Exception:
        postseasons = []
    return {
        "postseasons": postseasons,
        "latest": postseasons[0]["year"] if postseasons else None,
    }


def _postseason_leaders(limit: int, season: Optional[str]) -> Dict[str, Any]:
    """One postseason's leaders. Each player qualifies on the games HIS club
    played in it (services.postseason_stats: 3.1 PA / 1.0 IP per game)."""

    from services.postseason_stats import (
        IP_PER_TEAM_GAME,
        PA_PER_TEAM_GAME,
        leader_inputs,
        minimums_for_games,
    )

    data = leader_inputs(season)
    if data is None:
        if season not in (None, ""):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No postseason stats for {season}.",
            )
        data = {"players": [], "team_index": {}, "minimums": {}, "max_team_games": 0,
                "year": None, "season_id": "", "current": False}
    minimums = data["minimums"]
    max_g = int(data["max_team_games"] or 0)
    top_pa, top_ip = minimums_for_games(max_g) if max_g else (0, 0)
    players = data["players"]
    hitters = [p for p in players if not getattr(p, "is_pitcher", False)]
    pitchers = [p for p in players if getattr(p, "is_pitcher", False)]
    team_index = data["team_index"]

    def min_pa(player: Any) -> int:
        return minimums.get(player.player_id, (top_pa, top_ip))[0]

    def min_ip(player: Any) -> int:
        return minimums.get(player.player_id, (top_pa, top_ip))[1]

    return {
        "postseason": True,
        "season": data["year"],
        "season_id": data["season_id"],
        "current": data["current"],
        "qualifiers": {
            # The champion's (most games) figures; each player's own club's
            # games set his.
            "min_pa": top_pa,
            "min_ip": top_ip,
            "max_team_games": max_g,
            "pa_per_team_game": PA_PER_TEAM_GAME,
            "ip_per_team_game": IP_PER_TEAM_GAME,
            "per_club": True,
        },
        "batting": _boards(hitters, _BATTING, limit, team_index, min_pa, min_ip),
        "pitching": _boards(pitchers, _PITCHING, limit, team_index, min_pa, min_ip),
    }


def _boards(
    pool: List[Any],
    categories: List[Tuple[str, str, bool, bool, int]],
    limit: int,
    team_index: Dict[str, str],
    min_pa_for: Callable[[Any], int],
    min_ip_for: Callable[[Any], int],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for label, key, descending, pitcher_only, decimals in categories:
        apply_qualifier = key != "sv"

        def collect(p_list: List[Any]) -> List[Tuple[Any, Any]]:
            if not p_list:
                return []
            ranked = top_players(
                p_list,
                key,
                pitcher_only=pitcher_only,
                descending=descending,
                limit=len(p_list),
            )
            return [
                (player, value)
                for player, value in ranked
                if _qualified(
                    getattr(player, "season_stats", {}) or {},
                    pitcher_only=pitcher_only,
                    apply_qualifier=apply_qualifier,
                    min_pa=min_pa_for(player),
                    min_ip=min_ip_for(player),
                )
                and _has_sample(getattr(player, "season_stats", {}) or {}, key)
            ]

        picks = collect(pool)
        picks.sort(
            key=lambda item: (
                float(item[1])
                if isinstance(item[1], (int, float))
                else 0.0
            ),
            reverse=descending,
        )
        out.append(
            {
                "label": label,
                "key": key,
                "decimals": decimals,
                "descending": descending,
                "leaders": [
                    {
                        "rank": i + 1,
                        "player": _player_label(player, team_index),
                        "value": float(value)
                        if isinstance(value, (int, float))
                        else value,
                    }
                    for i, (player, value) in enumerate(picks[:limit])
                ],
            }
        )
    return out


@router.get("/leaders")
def league_leaders(
    limit: int = Query(default=5, ge=1, le=25),
    postseason: bool = Query(default=False),
    season: Optional[str] = Query(
        default=None,
        description="Postseason year (or season id); defaults to the latest.",
    ),
) -> Dict[str, Any]:
    if postseason:
        return _postseason_leaders(limit, season)
    try:
        season = _load_season_stats()
    except Exception:
        season = {"players": {}, "teams": {}}

    # Roster membership is the only source of a player's team — players.csv has
    # no team_id column. Built once per request, not per leaderboard row.
    from services.team_lookup import player_team_index

    try:
        team_index = player_team_index()
    except Exception:
        team_index = {}

    # Hydrate players + season stats.
    players_by_id = {
        p.player_id: p for p in load_players_from_csv("data/players.csv")
    }
    for pid, stats in (season.get("players") or {}).items():
        if pid in players_by_id:
            players_by_id[pid].season_stats = stats

    everyone = list(players_by_id.values())
    hitters = [p for p in everyone if not getattr(p, "is_pitcher", False)]
    pitchers = [p for p in everyone if getattr(p, "is_pitcher", False)]

    team_games = [int(v.get("g", 0) or 0) for v in (season.get("teams") or {}).values()]
    max_g = max(team_games) if team_games else 0
    min_pa = max(1, int(round(max_g * 3.1))) if max_g else 0
    min_ip = max(1, int(round(max_g * 1.0))) if max_g else 0

    return {
        "qualifiers": {"min_pa": min_pa, "min_ip": min_ip, "max_team_games": max_g},
        "batting": _boards(
            hitters, _BATTING, limit, team_index, lambda _p: min_pa, lambda _p: min_ip
        ),
        "pitching": _boards(
            pitchers, _PITCHING, limit, team_index, lambda _p: min_pa, lambda _p: min_ip
        ),
    }
