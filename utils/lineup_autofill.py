from __future__ import annotations

import csv
from datetime import date
import random
from pathlib import Path
from typing import Dict

from services.team_strategy_profiles import resolve_team_strategy_profile
from utils.path_utils import resolve_app_path
from utils.roster_loader import load_roster
from utils.player_loader import load_players_from_csv
from utils.depth_chart import depth_order_for_position, load_depth_chart
from services.decision_explanations import (
    append_decision_log,
    explanation,
    reason,
    should_persist_decision_logs,
)


def auto_fill_lineup_for_team(
    team_id: str,
    *,
    players_file: str | Path = "data/players.csv",
    roster_dir: str | Path = "data/rosters",
    lineup_dir: str | Path = "data/lineups",
    strategy_profile: str | None = None,
    vs: str | None = None,
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
    data_dir_hint = players_path.parent if players_path.name.lower() == "players.csv" else None

    players: Dict[str, object] = {p.player_id: p for p in load_players_from_csv(str(players_path))}
    roster = load_roster(team_id, roster_root)
    act_ids = [pid for pid in roster.act if pid in players]
    profile = _resolve_strategy_profile_token(
        team_id,
        explicit=strategy_profile,
        data_dir_hint=data_dir_hint,
    )
    try:
        depth_chart = load_depth_chart(team_id)
    except Exception:
        depth_chart = {}

    # Collect non-pitchers first
    def is_pitcher(p: object) -> bool:
        return getattr(p, "is_pitcher", False) or str(getattr(p, "primary_position", "")).upper() == "P"

    lineup: list[tuple[str, str]] = []
    used: set[str] = set()
    depth_chart_assignments = 0
    fallback_assignments = 0
    emergency_fill_count = 0
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
        base_score = (0.6 * off) + (0.2 * sp) + (0.2 * defense)
        return base_score + _strategy_hitter_bonus(p, profile=profile)

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
            depth_chart_assignments += 1
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
        fallback_assignments += 1

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
            depth_chart_assignments += 1
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
                fallback_assignments += 1

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
            emergency_fill_count += 1

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
            emergency_fill_count += 1

    lineup_root.mkdir(parents=True, exist_ok=True)
    # Order batting by hitter_score (best bats earlier)
    result = sorted(lineup[:9], key=lambda pair: hitter_score(pair[0]), reverse=True)
    # ``vs`` filters which lineup file(s) to overwrite. ``None`` (default)
    # writes both vs_lhp and vs_rhp. Pass "lhp" or "rhp" to target one only.
    vs_token = (vs or "").strip().lower()
    if vs_token in {"lhp", "rhp"}:
        targets: tuple[str, ...] = (f"vs_{vs_token}",)
    else:
        targets = ("vs_lhp", "vs_rhp")
    for target in targets:
        path = lineup_root / f"{team_id}_{target}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order", "player_id", "position"])
            for i, (pid, pos) in enumerate(result, start=1):
                writer.writerow([i, pid, pos])

    decision = explanation(
        "lineup_autofill",
        "generated",
        actor="automation",
        team_id=team_id,
        context={
            "act_pool_size": len(act_ids),
            "lineup_size": len(result),
            "depth_chart_assignments": depth_chart_assignments,
            "fallback_assignments": fallback_assignments,
            "emergency_fill_count": emergency_fill_count,
            "strategy_profile": profile,
        },
        reasons=[
            reason(
                "coverage_first",
                "Filled scarce defensive positions before batting order sort.",
            ),
            reason(
                "depth_chart_preference",
                "Used depth chart priority where eligible players were available.",
                details={"count": depth_chart_assignments},
            ),
            reason(
                "best_remaining_bat",
                "Used hitter score to select fallback or DH slots.",
                details={"count": fallback_assignments},
            ),
            reason(
                "emergency_fill",
                "Used emergency DH fills when coverage candidates were short.",
                details={"count": emergency_fill_count},
            ),
            reason(
                "strategy_profile",
                "Applied strategy-profile hitter valuation during fallback and order scoring.",
                details={"profile": profile},
            ),
        ],
    )
    auto_fill_lineup_for_team.last_explanation = decision.to_dict()  # type: ignore[attr-defined]
    if should_persist_decision_logs():
        append_decision_log(decision)
    return result


def _resolve_strategy_profile_token(
    team_id: str,
    *,
    explicit: str | None,
    data_dir_hint: Path | None,
) -> str:
    token = str(explicit or "").strip().lower()
    if token:
        return token
    try:
        resolved = resolve_team_strategy_profile(team_id, data_dir=data_dir_hint)
        return str(resolved.profile or "balanced")
    except Exception:
        return "balanced"


def _player_age(player: object) -> int | None:
    token = str(getattr(player, "birthdate", "") or "").strip()
    if not token:
        return None
    try:
        born = date.fromisoformat(token[:10])
    except Exception:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _norm_rating(value: object) -> float:
    try:
        numeric = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(99.0, numeric)) / 99.0


def _strategy_hitter_bonus(player: object, *, profile: str) -> float:
    token = str(profile or "balanced").strip().lower()
    if token == "balanced":
        return 0.0
    ch = _norm_rating(getattr(player, "ch", 0))
    ph = _norm_rating(getattr(player, "ph", 0))
    sp = _norm_rating(getattr(player, "sp", 0))
    eye = _norm_rating(getattr(player, "eye", 0))
    fa = _norm_rating(getattr(player, "fa", 0))
    arm = _norm_rating(getattr(player, "arm", 0))
    gf = _norm_rating(getattr(player, "gf", 0))
    age = _player_age(player)

    if token == "win_now":
        bonus = (2.4 * ch) + (2.8 * ph) + (1.4 * eye) - (0.7 * fa)
        if isinstance(age, int) and age <= 23:
            bonus -= 0.4
        return bonus
    if token == "development_focus":
        bonus = (1.1 * sp) + (1.0 * fa) + (0.7 * ch)
        if isinstance(age, int) and age < 28:
            bonus += max(0, 28 - age) * 0.30
        return bonus
    if token == "defense_first":
        return (2.9 * fa) + (1.7 * arm) + (1.8 * gf) - (0.6 * ph)
    if token == "power_offense":
        return (3.3 * ph) + (1.2 * ch) + (0.8 * sp) - (0.7 * fa)
    return 0.0
