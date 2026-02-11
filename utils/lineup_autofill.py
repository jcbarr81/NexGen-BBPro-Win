from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Dict

from utils.path_utils import resolve_app_path
from utils.roster_loader import load_roster
from utils.player_loader import load_players_from_csv
from utils.depth_chart import depth_order_for_position, load_depth_chart


def auto_fill_lineup_for_team(
    team_id: str,
    *,
    players_file: str | Path = "data/players.csv",
    roster_dir: str | Path = "data/rosters",
    lineup_dir: str | Path = "data/lineups",
) -> list[tuple[str, str]]:
    """Create sound, coverage-first lineups for ``team_id`` from ACT.

    Strategy:
    - Score hitters using contact/power/speed + defensive skills to favor
      stronger bats who can field their positions.
    - Fill positions in a scarcity-aware order to ensure coverage:
      C, SS, CF, 3B, 2B, 1B, LF, RF, then DH as the best remaining bat.
    - Enforce 9 unique players, never selecting pitchers for the lineup.
    - Batting order is sorted by an overall hitter score (contact/power/speed/defense proxy).
    - Write both ``vs_lhp`` and ``vs_rhp`` using the same order for now.
    - Return the 9-player lineup used.
    """

    players_path = resolve_app_path(players_file)
    roster_root = resolve_app_path(roster_dir)
    lineup_root = resolve_app_path(lineup_dir)

    players: Dict[str, object] = {p.player_id: p for p in load_players_from_csv(str(players_path))}
    roster = load_roster(team_id, roster_root)
    act_ids = [pid for pid in roster.act if pid in players]
    try:
        depth_chart = load_depth_chart(team_id)
    except Exception:
        depth_chart = {}

    # Collect non-pitchers first
    def is_pitcher(p: object) -> bool:
        return getattr(p, "is_pitcher", False) or str(getattr(p, "primary_position", "")).upper() == "P"

    lineup: list[tuple[str, str]] = []
    used: set[str] = set()
    # Scarcity-aware order: C/SS/CF first
    positions = ["C", "SS", "CF", "3B", "2B", "1B", "LF", "RF"]

    def eligible_for(pid: str, pos: str) -> bool:
        p = players.get(pid)
        if not p or is_pitcher(p):
            return False
        primary = str(getattr(p, "primary_position", "")).upper()
        others = [str(x).upper() for x in (getattr(p, "other_positions", []) or [])]
        return pos == primary or pos in others

    def hitter_score(pid: str) -> float:
        p = players.get(pid)
        if not p:
            return -1.0
        ch = float(getattr(p, "ch", 0)); ph = float(getattr(p, "ph", 0))
        sp = float(getattr(p, "sp", 0))
        fa = float(getattr(p, "fa", 0)); arm = float(getattr(p, "arm", 0))
        off = 0.5 * ch + 0.5 * ph
        defense = 0.5 * fa + 0.5 * arm
        return 0.6 * off + 0.2 * sp + 0.2 * defense

    def depth_preferred(pos: str) -> list[str]:
        preferred = depth_order_for_position(depth_chart, pos)
        return [
            pid
            for pid in preferred
            if pid in act_ids and pid not in used and eligible_for(pid, pos)
        ]

    for pos in positions:
        # Choose best eligible by score, preferring explicit depth chart order
        preferred = depth_preferred(pos)
        if preferred:
            best = preferred[0]
            lineup.append((best, pos))
            used.add(best)
            continue
        candidates = [pid for pid in act_ids if pid not in used and eligible_for(pid, pos)]
        if not candidates:
            candidates = [
                pid
                for pid in act_ids
                if pid not in used and (players.get(pid) and not is_pitcher(players[pid]))
            ]
        if not candidates:
            continue
        best = max(candidates, key=hitter_score)
        lineup.append((best, pos))
        used.add(best)

    # DH is any remaining non-pitcher
    if len(lineup) < 9:
        dh_pref = [
            pid
            for pid in depth_order_for_position(depth_chart, "DH")
            if pid in act_ids
            and pid not in used
            and (players.get(pid) and not is_pitcher(players[pid]))
        ]
        if dh_pref:
            best = dh_pref[0]
            lineup.append((best, "DH"))
            used.add(best)
        else:
            remaining = [
                pid
                for pid in act_ids
                if pid not in used and (players.get(pid) and not is_pitcher(players[pid]))
            ]
            if remaining:
                best = max(remaining, key=hitter_score)
                lineup.append((best, "DH"))
                used.add(best)

    # If still short, just fill with any remaining ACT players (defensive pos unknown)
    for pid in act_ids:
        if len(lineup) >= 9:
            break
        if pid in used:
            continue
        p = players.get(pid)
        if p and not is_pitcher(p):
            lineup.append((pid, "DH"))
            used.add(pid)

    if len(lineup) < 9:
        fallback_ids = [
            pid
            for pid, player in players.items()
            if pid not in used and player and not is_pitcher(player)
        ]
        rng = random.Random(f"{team_id}-lineup-fallback")
        rng.shuffle(fallback_ids)
        for pid in fallback_ids:
            if len(lineup) >= 9:
                break
            lineup.append((pid, "DH"))
            used.add(pid)

    lineup_root.mkdir(parents=True, exist_ok=True)
    # Order batting by hitter_score (best bats earlier)
    result = sorted(lineup[:9], key=lambda pair: hitter_score(pair[0]), reverse=True)
    for vs in ("vs_lhp", "vs_rhp"):
        path = lineup_root / f"{team_id}_{vs}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order", "player_id", "position"])
            for i, (pid, pos) in enumerate(result, start=1):
                writer.writerow([i, pid, pos])
    return result
