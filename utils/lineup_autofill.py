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
    - Build ``vs_lhp`` and ``vs_rhp`` from two INDEPENDENT passes: ``hitter_score``
      is handedness-aware (S2-01), so a lefty-masher can win a slot vs LHP and
      lose it vs RHP — the two files can differ in personnel and/or order.
      Depth-chart-preferred slots still pin personnel (only order differs there).
    - Return the vs_rhp lineup (majority matchup; used as the salvage lineup).
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

    # Scarcity-aware order: C/SS/CF first
    positions = ["C", "SS", "CF", "3B", "2B", "1B", "LF", "RF"]

    def eligible_for(pid: str, pos: str, used: set[str]) -> bool:
        p = players.get(pid)
        if not p or is_pitcher(p):
            return False
        primary = str(getattr(p, "primary_position", "")).upper()
        others = [str(x).upper() for x in (getattr(p, "other_positions", []) or [])]
        return pos == primary or pos in others

    def hitter_score(pid: str, *, vs_hand: str) -> float:
        p = players.get(pid)
        if not p:
            return -1.0
        ch = float(getattr(p, "ch", 0)); ph = float(getattr(p, "ph", 0))
        sp = float(getattr(p, "sp", 0))
        fa = float(getattr(p, "fa", 0)); arm = float(getattr(p, "arm", 0))
        off = 0.5 * ch + 0.5 * ph
        defense = 0.5 * fa + 0.5 * arm
        base_score = (0.6 * off) + (0.2 * sp) + (0.2 * defense)
        return (
            base_score
            + _platoon_adjustment(p, vs_hand=vs_hand)
            + _strategy_hitter_bonus(p, profile=profile)
        )

    def depth_preferred(pos: str, used: set[str]) -> list[str]:
        preferred = depth_order_for_position(depth_chart, pos)
        return [
            pid
            for pid in preferred
            if pid in act_ids and pid not in used and eligible_for(pid, pos, used)
        ]

    def _build_lineup(hand: str) -> tuple[list[tuple[str, str]], dict[str, int]]:
        """One independent, handedness-aware coverage-first pass."""
        lineup: list[tuple[str, str]] = []
        used: set[str] = set()
        counters = {"depth_chart": 0, "fallback": 0, "emergency": 0}
        score = lambda pid: hitter_score(pid, vs_hand=hand)

        for pos in positions:
            # Choose best eligible by score, preferring explicit depth chart order
            preferred = depth_preferred(pos, used)
            if preferred:
                best = preferred[0]
                lineup.append((best, pos))
                used.add(best)
                counters["depth_chart"] += 1
                continue
            candidates = [pid for pid in act_ids if pid not in used and eligible_for(pid, pos, used)]
            if not candidates:
                candidates = [
                    pid
                    for pid in act_ids
                    if pid not in used and (players.get(pid) and not is_pitcher(players[pid]))
                ]
            if not candidates:
                continue
            best = max(candidates, key=score)
            lineup.append((best, pos))
            used.add(best)
            counters["fallback"] += 1

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
                counters["depth_chart"] += 1
            else:
                remaining = [
                    pid
                    for pid in act_ids
                    if pid not in used and (players.get(pid) and not is_pitcher(players[pid]))
                ]
                if remaining:
                    best = max(remaining, key=score)
                    lineup.append((best, "DH"))
                    used.add(best)
                    counters["fallback"] += 1

        # If still short, fill with any remaining ACT players (defensive pos unknown)
        for pid in act_ids:
            if len(lineup) >= 9:
                break
            if pid in used:
                continue
            p = players.get(pid)
            if p and not is_pitcher(p):
                lineup.append((pid, "DH"))
                used.add(pid)
                counters["emergency"] += 1

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
                counters["emergency"] += 1

        # Slot-weighted batting order (S2-02): leadoff OBP/speed, 2 best overall,
        # 3-4 power, 9 second-leadoff speed tilt. Consumes the platoon-adjusted
        # overall score so vs-LHP / vs-RHP orders each reflect their matchup.
        ordered = _assign_batting_order(
            lineup[:9], players, vs_hand=hand, overall_score=score
        )
        return ordered, counters

    lineup_root.mkdir(parents=True, exist_ok=True)
    # ``vs`` filters which lineup file(s) to overwrite. ``None`` (default) writes
    # both vs_lhp and vs_rhp from independent passes. Pass "lhp"/"rhp" for one.
    # A platoon bat left out of one file is automatically on that game's bench
    # (build_bench = ACT minus lineup) and available to the pinch-hit logic.
    vs_token = (vs or "").strip().lower()
    if vs_token in {"lhp", "rhp"}:
        targets: tuple[str, ...] = (f"vs_{vs_token}",)
    else:
        targets = ("vs_lhp", "vs_rhp")
    built: dict[str, list[tuple[str, str]]] = {}
    counters_by_target: dict[str, dict[str, int]] = {}
    for target in targets:
        hand = "L" if target == "vs_lhp" else "R"
        built[target], counters_by_target[target] = _build_lineup(hand)
        path = lineup_root / f"{team_id}_{target}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order", "player_id", "position"])
            for i, (pid, pos) in enumerate(built[target], start=1):
                writer.writerow([i, pid, pos])
    # Return vs_rhp when both are written (majority matchup / salvage lineup);
    # the single requested variant otherwise.
    result = built[targets[-1]]
    _tot = lambda key: sum(c.get(key, 0) for c in counters_by_target.values())

    decision = explanation(
        "lineup_autofill",
        "generated",
        actor="automation",
        team_id=team_id,
        context={
            "act_pool_size": len(act_ids),
            "lineup_size": len(result),
            "targets": list(targets),
            "assignments_by_target": counters_by_target,
            "depth_chart_assignments": _tot("depth_chart"),
            "fallback_assignments": _tot("fallback"),
            "emergency_fill_count": _tot("emergency"),
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
                details={"count": _tot("depth_chart")},
            ),
            reason(
                "best_remaining_bat",
                "Used hitter score to select fallback or DH slots.",
                details={"count": _tot("fallback")},
            ),
            reason(
                "emergency_fill",
                "Used emergency DH fills when coverage candidates were short.",
                details={"count": _tot("emergency")},
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


def _platoon_adjustment(player: object, *, vs_hand: str) -> float:
    """Mirror the physics engine's platoon scale (engine._batter_context /
    _platoon_vl_delta) projected onto hitter_score's 0.6*(0.5*ch+0.5*ph) offense
    weight: 0.6*(0.5*(2h+0.25d) + 0.5*(2h+0.20d)) = 1.2*h + 0.135*d. Keeping the
    same constants makes lineup choices agree with in-game outcomes (S2-01/S2-06).
    """
    hand = "L" if str(vs_hand or "R").upper().startswith("L") else "R"
    bats = str(getattr(player, "bats", "") or "R").upper()
    if bats == "S":
        h = 0.5
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    d = float(getattr(player, "vl", 50) or 50) - 50.0
    if hand != "L":
        d = -0.35 * d  # PLATOON_RHP_COUNTER_SCALE, see S2-06
    return 1.2 * h + 0.135 * d


def _slot_components(player: object, *, vs_hand: str) -> dict[str, float]:
    """Rating-space proxies for batting-slot fit. The platoon shifts reuse the
    engine's _batter_context scales (contact 0.25, power 0.20, eye 0.30 per point
    of vs-hand delta, plus the flat ±2.0 handedness shift) so slotting agrees
    with simulated outcomes (S2-02)."""
    hand = "L" if str(vs_hand or "R").upper().startswith("L") else "R"
    bats = str(getattr(player, "bats", "") or "R").upper()
    if bats == "S":
        h = 0.5
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    d = float(getattr(player, "vl", 50) or 50) - 50.0
    if hand != "L":
        d = -0.35 * d  # PLATOON_RHP_COUNTER_SCALE (S2-06)
    ch = float(getattr(player, "ch", 0)) + 2.0 * h + 0.25 * d
    ph = float(getattr(player, "ph", 0)) + 2.0 * h + 0.20 * d
    eye = float(getattr(player, "eye", 0)) + 2.0 * h + 0.30 * d
    sp = float(getattr(player, "sp", 0))
    return {
        "obp": 0.6 * eye + 0.4 * ch,
        "power": ph,
        "contact": ch,
        "speed": sp,
    }


# Slot weight table (each row sums to 1.00). See S2-02 spec for the rationale.
_SLOT_WEIGHTS: dict[int, dict[str, float]] = {
    #        overall  obp   power  speed  contact
    1: {"overall": 0.20, "obp": 0.45, "power": 0.05, "speed": 0.25, "contact": 0.05},
    2: {"overall": 0.50, "obp": 0.25, "power": 0.10, "speed": 0.05, "contact": 0.10},
    3: {"overall": 0.35, "obp": 0.15, "power": 0.35, "speed": 0.05, "contact": 0.10},
    4: {"overall": 0.25, "obp": 0.10, "power": 0.55, "speed": 0.00, "contact": 0.10},
    5: {"overall": 0.30, "obp": 0.10, "power": 0.40, "speed": 0.05, "contact": 0.15},
    6: {"overall": 0.60, "obp": 0.10, "power": 0.15, "speed": 0.10, "contact": 0.05},
    7: {"overall": 0.70, "obp": 0.10, "power": 0.10, "speed": 0.05, "contact": 0.05},
    8: {"overall": 0.80, "obp": 0.05, "power": 0.05, "speed": 0.05, "contact": 0.05},
    9: {"overall": 0.55, "obp": 0.05, "power": 0.05, "speed": 0.30, "contact": 0.05},
}
# Anchor the highest-leverage identities first (best overall at 2, top power at
# 4) so leadoff's heavy OBP/speed weights can't steal the best all-around bat.
_SLOT_FILL_ORDER = (2, 4, 1, 3, 5, 6, 7, 8, 9)


def _assign_batting_order(
    selected: list[tuple[str, str]],
    players: dict,
    *,
    vs_hand: str,
    overall_score,  # callable: (pid) -> float
) -> list[tuple[str, str]]:
    """Assign the 9 selected (pid, pos) pairs to batting slots by slot-specific
    weighting of overall / obp / power / speed / contact proxies. Pure permutation
    of the input; deterministic (pid-ascending tie-break, no RNG)."""
    pool = list(selected[:9])
    comps = {
        pid: _slot_components(players.get(pid), vs_hand=vs_hand)
        for pid, _pos in pool
        if players.get(pid) is not None
    }
    overall = {pid: float(overall_score(pid)) for pid, _pos in pool}
    zero = {"obp": 0.0, "power": 0.0, "contact": 0.0, "speed": 0.0}
    slots: dict[int, tuple[str, str]] = {}
    # Pre-sort so max() keeps the lowest pid on full ties (determinism).
    remaining = sorted(pool, key=lambda pr: pr[0])
    for slot in _SLOT_FILL_ORDER:
        if not remaining:
            break
        weights = _SLOT_WEIGHTS[slot]

        def slot_score(pair: tuple[str, str]) -> tuple[float, float]:
            pid = pair[0]
            c = comps.get(pid, zero)
            score = (
                weights["overall"] * overall.get(pid, 0.0)
                + weights["obp"] * c["obp"]
                + weights["power"] * c["power"]
                + weights["speed"] * c["speed"]
                + weights["contact"] * c["contact"]
            )
            return (score, overall.get(pid, 0.0))

        best = max(remaining, key=slot_score)
        slots[slot] = best
        remaining.remove(best)
    return [slots[i] for i in sorted(slots)]


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
