"""League leaders endpoint.

Mirrors the categories + qualifier logic from
``ui/league_leaders_window.py`` and surfaces the top N for each one in a
single response. Uses the same helpers (``top_players``, season stats
loader) so numbers match the PyQt build exactly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Query

from utils.stat_helpers import top_players
from utils.player_loader import load_players_from_csv
from utils.stats_persistence import load_stats as _load_season_stats

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


def _player_label(player: Any) -> Dict[str, Any]:
    return {
        "player_id": getattr(player, "player_id", ""),
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "team_id": str(getattr(player, "team_id", "") or ""),
    }


@router.get("/leaders")
def league_leaders(
    limit: int = Query(default=5, ge=1, le=25),
) -> Dict[str, Any]:
    try:
        season = _load_season_stats()
    except Exception:
        season = {"players": {}, "teams": {}}

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

    def board(
        pool: List[Any],
        fallback: List[Any],
        categories: List[Tuple[str, str, bool, bool, int]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for label, key, descending, pitcher_only, decimals in categories:
            apply_qualifier = key != "sv"
            primary_pool = (
                fallback if (key == "sv" and pitcher_only) else pool
            )

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
                        min_pa=min_pa,
                        min_ip=min_ip,
                    )
                    and _has_sample(getattr(player, "season_stats", {}) or {}, key)
                ]

            picks = collect(primary_pool)
            if len(picks) < limit:
                seen = {
                    getattr(p, "player_id", id(p)) for p, _ in picks
                }
                for player, value in collect(fallback):
                    pid = getattr(player, "player_id", id(player))
                    if pid in seen:
                        continue
                    picks.append((player, value))
                    seen.add(pid)
                    if len(picks) >= limit:
                        break

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
                            "player": _player_label(player),
                            "value": float(value)
                            if isinstance(value, (int, float))
                            else value,
                        }
                        for i, (player, value) in enumerate(picks[:limit])
                    ],
                }
            )
        return out

    return {
        "qualifiers": {"min_pa": min_pa, "min_ip": min_ip, "max_team_games": max_g},
        "batting": board(hitters, hitters, _BATTING),
        "pitching": board(pitchers, pitchers, _PITCHING),
    }
