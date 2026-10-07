from __future__ import annotations

import random
from pathlib import Path
from typing import Dict

from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    counts_as_pitcher,
)
from utils.team_loader import load_teams


def ensure_active_rosters(
    *,
    players: Dict[str, object] | None = None,
    players_file: str | Path = "data/players.csv",
    roster_dir: str | Path = "data/rosters",
    min_hitters: int = 9,
    min_pitchers: int = 1,
    active_max: int = ACTIVE_ROSTER_SIZE,
    data_dir: str | Path | None = None,
) -> dict[str, int]:
    """Ensure each CPU team has valid active players, filling from free agents if needed.

    Targets 13 position players and 13 pitchers (never more pitchers than
    the 13-pitcher limit). Owner teams are never touched -- this signs free
    agents -- and when ownership can't be read nothing is. Players trimmed
    from an oversized active roster go to AAA, never off the roster.
    """

    try:
        from services.team_ownership import human_owned_team_ids_strict

        if data_dir is None:
            root = Path(roster_dir)
            if root.is_absolute():
                data_dir = root.parent
        human_ids = human_owned_team_ids_strict(data_dir)
    except Exception:  # pragma: no cover - defensive
        human_ids = None
    if human_ids is None:
        return {"adjustments": 0, "free_agents_left": 0, "skipped": "ownership_unknown"}

    if players is None:
        players = {
            p.player_id: p for p in load_players_from_csv(str(players_file))
        }

    valid_ids = set(players.keys())
    rostered: set[str] = set()
    adjustments = 0

    rosters = {}
    for team in load_teams():
        roster = load_roster(team.team_id, roster_dir=roster_dir)
        rostered.update(roster.act + roster.aaa + roster.low + roster.dl + roster.ir)
        if str(team.team_id).upper() in human_ids:
            continue
        removed = 0

        def _filter_ids(ids: list[str]) -> list[str]:
            nonlocal removed
            filtered = [pid for pid in ids if pid in valid_ids]
            removed += len(ids) - len(filtered)
            return filtered

        roster.act = _filter_ids(roster.act)
        roster.aaa = _filter_ids(roster.aaa)
        roster.low = _filter_ids(roster.low)
        roster.dl = _filter_ids(roster.dl)
        roster.ir = _filter_ids(roster.ir)
        if roster.dl_tiers:
            roster.dl_tiers = {
                pid: tier for pid, tier in roster.dl_tiers.items() if pid in valid_ids
            }
        if removed:
            adjustments += removed
        rosters[team.team_id] = roster

    def is_pitcher(pid: str) -> bool:
        return counts_as_pitcher(players.get(pid))

    free_agents = [
        pid
        for pid in players.keys()
        if pid not in rostered and not str(pid).startswith("D")
    ]
    random.shuffle(free_agents)
    free_hitters = [pid for pid in free_agents if not is_pitcher(pid)]
    free_pitchers = [pid for pid in free_agents if is_pitcher(pid)]

    for team_id, roster in rosters.items():
        act_ids = list(dict.fromkeys(roster.act))
        act_hitters = [pid for pid in act_ids if not is_pitcher(pid)]
        act_pitchers = [pid for pid in act_ids if is_pitcher(pid)]

        org_hitters = [
            pid
            for pid in (roster.aaa + roster.low)
            if not is_pitcher(pid) and pid not in act_ids
        ]
        org_pitchers = [
            pid
            for pid in (roster.aaa + roster.low)
            if is_pitcher(pid) and pid not in act_ids
        ]

        need_hitters = max(0, min_hitters - len(act_hitters))
        while need_hitters > 0:
            if org_hitters:
                pid = org_hitters.pop(0)
                if pid in roster.aaa:
                    roster.aaa.remove(pid)
                if pid in roster.low:
                    roster.low.remove(pid)
            elif free_hitters:
                pid = free_hitters.pop(0)
            else:
                break
            act_ids.append(pid)
            act_hitters.append(pid)
            need_hitters -= 1
            adjustments += 1

        while len(act_pitchers) < min_pitchers:
            if org_pitchers:
                pid = org_pitchers.pop(0)
                if pid in roster.aaa:
                    roster.aaa.remove(pid)
                if pid in roster.low:
                    roster.low.remove(pid)
                act_ids.append(pid)
                act_pitchers.append(pid)
                adjustments += 1
            elif free_pitchers:
                pid = free_pitchers.pop(0)
                act_ids.append(pid)
                act_pitchers.append(pid)
                adjustments += 1
            else:
                break

        def add_hitter() -> bool:
            if org_hitters:
                pid = org_hitters.pop()
                if pid in roster.aaa:
                    roster.aaa.remove(pid)
                if pid in roster.low:
                    roster.low.remove(pid)
            elif free_hitters:
                pid = free_hitters.pop()
            else:
                return False
            act_ids.append(pid)
            act_hitters.append(pid)
            return True

        def add_pitcher() -> bool:
            if len(act_pitchers) >= MAX_ACTIVE_PITCHERS:
                return False
            if org_pitchers:
                pid = org_pitchers.pop()
                if pid in roster.aaa:
                    roster.aaa.remove(pid)
                if pid in roster.low:
                    roster.low.remove(pid)
            elif free_pitchers:
                pid = free_pitchers.pop()
            else:
                return False
            act_ids.append(pid)
            act_pitchers.append(pid)
            return True

        def option(pid: str) -> None:
            nonlocal adjustments
            if pid in act_ids:
                act_ids.remove(pid)
            if pid not in roster.aaa:
                roster.aaa.append(pid)
            adjustments += 1

        target_hitters = max(min_hitters, ACT_HITTER_TARGET)
        target_pitchers = max(min_pitchers, MAX_ACTIVE_PITCHERS)
        while len(act_ids) < active_max:
            if len(act_hitters) < target_hitters and add_hitter():
                adjustments += 1
                continue
            if len(act_pitchers) < target_pitchers and add_pitcher():
                adjustments += 1
                continue
            if add_hitter():
                adjustments += 1
                continue
            break

        while len(act_pitchers) > max(min_pitchers, MAX_ACTIVE_PITCHERS):
            option(act_pitchers.pop())

        while len(act_ids) > active_max and act_pitchers and len(act_pitchers) > min_pitchers:
            option(act_pitchers.pop())

        while len(act_ids) > active_max and len(act_hitters) > min_hitters:
            option(act_hitters.pop())

        roster.act = act_ids
        save_roster(team_id, roster)

    return {
        "adjustments": adjustments,
        "free_agents_left": len(free_hitters) + len(free_pitchers),
    }
