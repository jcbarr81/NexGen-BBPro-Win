"""Auto-generate a team's depth chart from its current roster.

Mirrors the PyQt depth-chart dialog's "Auto Populate" button: for each
position (C/SS/CF/3B/2B/1B/LF/RF/DH) pick the top-three best-fit
non-pitchers, preferring players whose primary position matches and who
are on the active roster, sorted by overall rating.

Players are not artificially restricted to a single position — the
PyQt dialog let a strong utility player appear in multiple depth charts
when there weren't enough natural fits, and we keep that behavior here
by falling back to already-assigned candidates only when fewer than
``MAX_DEPTH`` unique fits exist.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping

from utils.depth_chart import DEPTH_CHART_POSITIONS, MAX_DEPTH, save_depth_chart
from utils.player_loader import load_players_from_csv
from utils.rating_display import overall_rating
from utils.roster_loader import load_roster

__all__ = ["auto_generate_depth_chart"]


_LEVEL_PRIORITY = {"act": 0, "aaa": 1, "low": 2, "dl": 3, "ir": 4}


def _level_for(pid: str, levels: Mapping[str, Iterable[str]]) -> str:
    for level, ids in levels.items():
        if pid in ids:
            return level
    return ""


def _is_pitcher(player: object) -> bool:
    if getattr(player, "is_pitcher", False):
        return True
    return str(getattr(player, "primary_position", "")).strip().upper() == "P"


def _can_play(player: object, position: str) -> bool:
    if _is_pitcher(player):
        return False
    if position == "DH":
        return True
    primary = str(getattr(player, "primary_position", "")).strip().upper()
    if primary == position:
        return True
    others = getattr(player, "other_positions", None) or []
    if isinstance(others, str):
        others = [others]
    for other in others:
        if str(other).strip().upper() == position:
            return True
    return False


def auto_generate_depth_chart(
    team_id: str,
    *,
    persist: bool = True,
) -> Dict[str, List[str]]:
    """Return (and optionally save) an auto-populated depth chart.

    For each position the helper splits the eligible roster into
    ``primary`` fits (the position is the player's primary) and
    ``secondary`` fits (the player can play it via ``other_positions``).
    Each group is sorted by level (ACT first) then overall rating
    (descending). The merged list seeds each position with up to
    ``MAX_DEPTH`` players, preferring unassigned candidates first and
    falling back to already-assigned ones only when no other unique
    eligible player exists.
    """

    roster = load_roster(team_id)
    levels: Dict[str, List[str]] = {
        "act": list(roster.act),
        "aaa": list(roster.aaa),
        "low": list(roster.low),
        "dl": list(roster.dl),
        "ir": list(roster.ir),
    }

    players_list = load_players_from_csv("data/players.csv")
    players_by_id = {getattr(p, "player_id", ""): p for p in players_list}

    # Roster-wide ID list, used for level resolution. Exclude pitchers
    # up front so depth-chart scoring never has to consider them.
    roster_ids: List[str] = []
    for ids in levels.values():
        for pid in ids:
            player = players_by_id.get(pid)
            if player and not _is_pitcher(player):
                roster_ids.append(pid)

    def _candidates(position: str) -> List[str]:
        primaries: List[str] = []
        secondaries: List[str] = []
        for pid in roster_ids:
            player = players_by_id.get(pid)
            if player is None or not _can_play(player, position):
                continue
            primary = str(getattr(player, "primary_position", "")).strip().upper()
            if primary == position:
                primaries.append(pid)
            else:
                secondaries.append(pid)

        def _sort(pool: List[str]) -> List[str]:
            return sorted(
                pool,
                key=lambda pid: (
                    _LEVEL_PRIORITY.get(_level_for(pid, levels), 5),
                    -int(overall_rating(players_by_id.get(pid)) or 0),
                ),
            )

        return _sort(primaries) + _sort(secondaries)

    chart: Dict[str, List[str]] = {pos: [] for pos in DEPTH_CHART_POSITIONS}
    assigned: set[str] = set()

    for position in DEPTH_CHART_POSITIONS:
        ranked = _candidates(position)
        chosen: List[str] = []
        # First pass: prefer players not yet placed at another position.
        for pid in ranked:
            if pid in chosen:
                continue
            if pid in assigned:
                continue
            chosen.append(pid)
            if len(chosen) >= MAX_DEPTH:
                break
        # Fallback pass: backfill with already-placed players if the
        # roster doesn't cover this position three players deep.
        if len(chosen) < MAX_DEPTH:
            for pid in ranked:
                if pid in chosen:
                    continue
                chosen.append(pid)
                if len(chosen) >= MAX_DEPTH:
                    break
        chart[position] = chosen
        assigned.update(chosen)

    if persist:
        save_depth_chart(team_id, chart)
    return chart
