from __future__ import annotations

import random
from pathlib import Path
from typing import Dict

from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster
from utils.roster_rules import (
    AAA_CAP,
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    LOW_CAP,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    counts_as_pitcher,
)
from utils.team_loader import load_teams


def _low_eligible(player: object) -> bool:
    """True unless ``player`` is known to be too old for Low-A."""

    bd = getattr(player, "birthdate", None) if player is not None else None
    if not bd:
        return True
    try:
        from playbalance.aging import calculate_age
        from services.roster_validation import LOW_LEVEL_MAX_AGE

        return calculate_age(str(bd)) < LOW_LEVEL_MAX_AGE
    except Exception:
        return True


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
    agents -- and when ownership can't be read nothing is. Per club:

    1. surplus pitchers go down first -- to AAA while it is under its cap,
       else Low-A for a player young enough while it has room; when neither
       has room an own-org position player comes up to make it (a swap),
       else the pitcher stays active;
    2. the active roster fills to ``active_max``, own AAA/Low-A first, free
       agents only while the organisation is under ``ORG_LIMIT``;
    3. an active roster still over ``active_max`` options players the same
       way -- never the last healthy catcher.

    Players are only ever optioned, never released.
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

    def is_healthy_catcher(pid: str) -> bool:
        player = players.get(pid)
        return (
            player is not None
            and not is_pitcher(pid)
            and str(getattr(player, "primary_position", "") or "").strip().upper() == "C"
            and not getattr(player, "injured", False)
        )

    free_agents = [
        pid
        for pid in players.keys()
        if pid not in rostered and not str(pid).startswith("D")
    ]
    random.shuffle(free_agents)
    free_hitters = [pid for pid in free_agents if not is_pitcher(pid)]
    free_pitchers = [pid for pid in free_agents if is_pitcher(pid)]

    pitcher_limit = max(min_pitchers, MAX_ACTIVE_PITCHERS)
    target_hitters = max(min_hitters, ACT_HITTER_TARGET)

    for team_id, roster in rosters.items():
        act_ids = list(dict.fromkeys(roster.act))
        act_hitters = [pid for pid in act_ids if not is_pitcher(pid)]
        act_pitchers = [pid for pid in act_ids if is_pitcher(pid)]

        def org_size() -> int:
            return len(act_ids) + len(roster.aaa) + len(roster.low)

        def call_up(want_pitcher: bool) -> bool:
            # Own organisation, AAA before Low-A.
            for level in ("aaa", "low"):
                ids = getattr(roster, level)
                for pid in ids:
                    if pid in act_ids or is_pitcher(pid) != want_pitcher:
                        continue
                    ids.remove(pid)
                    act_ids.append(pid)
                    (act_pitchers if want_pitcher else act_hitters).append(pid)
                    return True
            return False

        def sign(want_pitcher: bool) -> bool:
            if org_size() >= ORG_LIMIT:
                return False
            pool = free_pitchers if want_pitcher else free_hitters
            if not pool:
                return False
            pid = pool.pop()
            act_ids.append(pid)
            (act_pitchers if want_pitcher else act_hitters).append(pid)
            return True

        def add_hitter() -> bool:
            return call_up(False) or sign(False)

        def add_pitcher() -> bool:
            if len(act_pitchers) >= pitcher_limit:
                return False
            return call_up(True) or sign(True)

        def destination(pid: str) -> str | None:
            if len(roster.aaa) < AAA_CAP:
                return "aaa"
            if len(roster.low) < LOW_CAP and _low_eligible(players.get(pid)):
                return "low"
            return None

        def option(pid: str, level: str) -> None:
            nonlocal adjustments
            act_ids.remove(pid)
            (act_pitchers if is_pitcher(pid) else act_hitters).remove(pid)
            getattr(roster, level).append(pid)
            adjustments += 1

        # 1. surplus pitchers down first, so the fill can use their spots.
        while len(act_pitchers) > pitcher_limit:
            pid = act_pitchers[-1]
            level = destination(pid)
            if level is None and len(act_hitters) < target_hitters and call_up(False):
                adjustments += 1        # a position player up makes the room
                level = destination(pid)
            if level is None:
                break                   # nowhere legal: he stays active
            option(pid, level)

        # 2. fill: position players to the target, then arms to the limit.
        while len(act_ids) < active_max:
            if len(act_hitters) < target_hitters and add_hitter():
                adjustments += 1
                continue
            if len(act_pitchers) < pitcher_limit and add_pitcher():
                adjustments += 1
                continue
            if add_hitter():
                adjustments += 1
                continue
            break

        # 3. still over the size cap: option by composition.
        while len(act_ids) > active_max:
            catchers = [p for p in act_hitters if is_healthy_catcher(p)]
            hitters = (
                [p for p in act_hitters if not (p in catchers and len(catchers) <= 1)]
                if len(act_hitters) > min_hitters
                else []
            )
            arms = act_pitchers if len(act_pitchers) > min_pitchers else []
            pools = (hitters, arms) if len(act_hitters) > target_hitters else (arms, hitters)
            victim = next((pool[-1] for pool in pools if pool), None)
            level = destination(victim) if victim is not None else None
            if level is None:
                break
            option(victim, level)

        roster.act = act_ids
        save_roster(team_id, roster)

    return {
        "adjustments": adjustments,
        "free_agents_left": len(free_hitters) + len(free_pitchers),
    }
