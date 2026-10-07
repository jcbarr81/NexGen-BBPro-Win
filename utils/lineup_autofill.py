from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping

from services.team_strategy_profiles import resolve_team_strategy_profile
from utils.path_utils import resolve_app_path
from utils.roster_loader import load_roster
from utils.player_loader import load_players_from_csv
from utils.depth_chart import depth_order_for_position, load_depth_chart
from utils.position_fit import (
    DIFFICULTY_ORDER,
    FILL_FAMILY,
    FILL_ORDER,
    fielding_fit,
    in_fill_family,
    player_positions,
)
from utils.roster_rules import counts_as_pitcher, is_catcher
from services.decision_explanations import (
    append_decision_log,
    explanation,
    reason,
    should_persist_decision_logs,
)


def lineup_depth_chart(team_id: str) -> dict:
    """The depth chart that may pin lineup starters, or ``{}``.

    A chart the sim generated (every chartless club gets one for injury
    coverage) is advisory: letting it pin starters would erase the
    handedness-aware vs-LHP / vs-RHP passes (S2-01) and pick by overall rating
    instead of matchup. Only a chart a person saved decides who starts.
    """

    try:
        from utils.depth_chart import is_depth_chart_auto

        if is_depth_chart_auto(team_id):
            return {}
        return load_depth_chart(team_id)
    except Exception:
        return {}


def auto_fill_lineup_for_team(
    team_id: str,
    *,
    players_file: str | Path = "data/players.csv",
    roster_dir: str | Path = "data/rosters",
    lineup_dir: str | Path = "data/lineups",
    strategy_profile: str | None = None,
    vs: str | None = None,
    persist: bool = True,
) -> list[tuple[str, str]]:
    """Create sound, coverage-first lineups for ``team_id`` from ACT.

    Strategy (the selection is :func:`build_lineup`):
    - Score hitters using contact/power/speed + defensive skills to favor
      stronger bats who can field their positions.
    - Fill the catcher first, then the scarcest position (fewest eligible
      players left) first, each with its best eligible player. A position
      nobody lists goes to the best FIT -- a player sliding over from a
      position he can leave, then the position's family (2B/3B at SS, a
      corner outfielder in CF), then the best fielder -- never simply the
      best bat, and never a non-catcher at C while a catcher is active.
      DH is the best remaining bat.
    - Enforce 9 unique players, never selecting pitchers for the lineup.
    - Batting order is sorted by an overall hitter score (contact/power/speed/defense proxy).
    - Build ``vs_lhp`` and ``vs_rhp`` from two INDEPENDENT passes: ``hitter_score``
      is handedness-aware (S2-01), so a lefty-masher can win a slot vs LHP and
      lose it vs RHP — the two files can differ in personnel and/or order.
      Depth-chart-preferred slots still pin personnel (only order differs there).
    - Return the vs_rhp lineup (majority matchup; used as the salvage lineup).
    - ``persist=False`` builds the lineup(s) without writing any file.
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
    depth_chart = lineup_depth_chart(team_id)

    def hitter_score(pid: str, *, vs_hand: str) -> float:
        p = players.get(pid)
        if not p:
            return -1.0
        return lineup_hitter_score(p, vs_hand=vs_hand, profile=profile)

    def _build_lineup(hand: str) -> tuple[list[tuple[str, str]], dict[str, int]]:
        """One independent, handedness-aware coverage-first pass."""
        score = lambda pid: hitter_score(pid, vs_hand=hand)
        lineup, counters = build_lineup(
            act_ids, players, score=score, depth_chart=depth_chart
        )

        if len(lineup) < 9:
            # This used to fill the gap from EVERY player in players.csv --
            # other clubs' minor leaguers, shuffled with a fixed seed -- which
            # the game then rejected, aborting the sim day on every retry
            # (audit H9). Emergency call-ups from the club's own minors happen
            # before each sim day (api.routers.season._prepare_rosters_for_date);
            # a lineup action never makes roster moves.
            raise ValueError(
                f"{team_id} cannot field nine position players: "
                f"{len(lineup)} healthy across the active roster and minors"
            )

        # Slot-weighted batting order (S2-02): leadoff OBP/speed, 2 best overall,
        # 3-4 power, 9 second-leadoff speed tilt. Consumes the platoon-adjusted
        # overall score so vs-LHP / vs-RHP orders each reflect their matchup.
        ordered = _assign_batting_order(
            lineup[:9], players, vs_hand=hand, overall_score=score
        )
        return ordered, counters

    if persist:
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
        if not persist:
            continue
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
                "best_fit_fallback",
                "Filled positions nobody lists with the best fit (a slide, the "
                "position's family, then fielding); the DH is the best remaining bat.",
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


def lineup_hitter_score(player: object, *, vs_hand: str, profile: str = "balanced") -> float:
    """The auto-fill's hitter value: bat, speed and defence, the platoon
    shift for ``vs_hand`` and the strategy-profile bonus."""

    ch = float(getattr(player, "ch", 0) or 0)
    ph = float(getattr(player, "ph", 0) or 0)
    sp = float(getattr(player, "sp", 0) or 0)
    fa = float(getattr(player, "fa", 0) or 0)
    arm = float(getattr(player, "arm", 0) or 0)
    off = 0.5 * ch + 0.5 * ph
    defense = 0.5 * fa + 0.5 * arm
    base_score = (0.6 * off) + (0.2 * sp) + (0.2 * defense)
    return (
        base_score
        + _platoon_adjustment(player, vs_hand=vs_hand)
        + _strategy_hitter_bonus(player, profile=profile)
    )


def build_lineup(
    pool_ids: Iterable[str],
    players: Mapping[str, object],
    *,
    score: Callable[[str], float],
    depth_chart: Mapping[str, object] | None = None,
) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Choose nine ``(player_id, position)`` pairs from ``pool_ids``. Pure.

    Release 3 (audit M12): the old pass filled C, SS, CF, ... in a fixed
    order and, for a position nobody listed, took the best remaining bat --
    which could be the next position's only option, cascading two or three
    players out of position (a missing shortstop replaced by a first
    baseman, then the second baseman's spot by an outfielder).

    1. Depth-chart picks a person saved pin their positions (eligible only).
    2. The catcher, then repeatedly the open position with the fewest
       eligible players left, takes its best eligible player by ``score``.
       Catchers (``is_catcher``) play elsewhere only when no one else can.
    3. Each position still open, hardest first (``DIFFICULTY_ORDER``):
       a. a player listed there slides over from an easier spot whose
          replacement is listed for it (nobody out of position);
       b. an unused player from the position's family (``FILL_FAMILY``);
       c. a starter from the family slides over, his spot going to an
          unused player listed for it (one player out of position, a
          similar one);
       d. the best unused non-catcher, then a catcher -- by fielding fit
          (``fielding_fit``), the bat only breaking ties.
       C is never handed to a non-catcher while a catcher is in the pool
       (one playing elsewhere slides back).
    4. DH: the best remaining bat.

    Pitchers are never picked. Returns fewer than nine pairs when the pool
    holds fewer than nine position players; the caller decides what that
    means. ``counters`` counts ``depth_chart`` / ``eligible`` / ``fallback``
    / ``emergency`` assignments.
    """

    hitters: list[str] = []
    seen: set[str] = set()
    for pid in pool_ids:
        p = players.get(pid)
        if pid in seen or p is None or counts_as_pitcher(p):
            continue
        seen.add(pid)
        hitters.append(pid)
    positions = {pid: player_positions(players[pid]) for pid in hitters}
    catchers = {pid for pid in hitters if is_catcher(players[pid])}
    counters = {"depth_chart": 0, "eligible": 0, "fallback": 0, "emergency": 0}
    at: dict[str, str] = {}  # position -> player id
    used: set[str] = set()

    def place(pid: str, pos: str, kind: str) -> None:
        at[pos] = pid
        used.add(pid)
        counters[kind] += 1

    def unused() -> list[str]:
        return [pid for pid in hitters if pid not in used]

    def best(cands: list[str], pos: str | None = None) -> str:
        # Sorted first so ties break on the player id, not the pool order.
        ordered = sorted(cands)
        if pos is None:
            return max(ordered, key=lambda pid: score(pid))
        return max(ordered, key=lambda pid: (fielding_fit(players[pid], pos), score(pid)))

    # 1. depth-chart pins
    chart = depth_chart or {}
    for pos in FILL_ORDER:
        if not chart:
            break
        for pid in depth_order_for_position(chart, pos):
            if pid in positions and pid not in used and pos in positions[pid]:
                place(pid, pos, "depth_chart")
                break

    # 2. eligible players, catcher first, then the scarcest position
    while True:
        options: dict[str, list[str]] = {}
        for pos in FILL_ORDER:
            if pos in at:
                continue
            cands = [pid for pid in unused() if pos in positions[pid]]
            if pos != "C":
                non_c = [pid for pid in cands if pid not in catchers]
                cands = non_c or cands
            if cands:
                options[pos] = cands
        if not options:
            break
        if "C" in options:
            pos = "C"
        else:
            pos = min(options, key=lambda q: (len(options[q]), FILL_ORDER.index(q)))
        place(best(options[pos]), pos, "eligible")

    # 3. best fit for positions nobody lists
    rank = {pos: idx for idx, pos in enumerate(DIFFICULTY_ORDER)}
    for _guard in range(len(FILL_ORDER) * 2):
        open_pos = [pos for pos in DIFFICULTY_ORDER if pos not in at]
        spare = unused()
        if not open_pos or not (spare or "C" in open_pos):
            break
        pos = open_pos[0]
        if pos == "C":
            # A catcher playing elsewhere goes back behind the plate.
            moved = sorted(
                (q for q, pid in at.items() if pid in catchers),
                key=lambda q: rank.get(q, 99),
            )
            if moved:
                q = moved[-1]
                at["C"] = at.pop(q)
                continue
            if not spare:
                break
            place(best(spare, "C"), "C", "fallback")
            continue
        if not spare:
            break
        # a. an eligible slide: nobody ends up out of position
        slid = False
        for q, pid in sorted(at.items(), key=lambda item: -rank.get(item[0], 99)):
            if q == "C" or rank.get(q, 99) <= rank[pos] or pos not in positions[pid]:
                continue
            fillers = [u for u in spare if q in positions[u]]
            if fillers:
                at[pos] = at.pop(q)
                place(best(fillers), q, "eligible")
                slid = True
                break
        if slid:
            continue
        spare_field = [u for u in spare if u not in catchers]
        # b. an unused family member
        family = [u for u in spare_field if in_fill_family(players[u], pos)]
        if family:
            place(best(family, pos), pos, "fallback")
            continue
        # c. a family starter slides over; his own spot stays covered
        for q, pid in sorted(at.items(), key=lambda item: -rank.get(item[0], 99)):
            if q == "C" or q not in FILL_FAMILY.get(pos, ()):
                continue
            fillers = [u for u in spare if q in positions[u] and u not in catchers]
            if fillers:
                at[pos] = at.pop(q)
                counters["fallback"] += 1
                place(best(fillers), q, "eligible")
                slid = True
                break
        if slid:
            continue
        # d. the best fielder left
        place(best(spare_field or spare, pos), pos, "fallback")

    lineup = [(at[pos], pos) for pos in FILL_ORDER if pos in at]

    # 4. DH: the best remaining bat
    spare = unused()
    if spare and len(lineup) < 9:
        dh_pref = [
            pid for pid in depth_order_for_position(chart, "DH") if pid in spare
        ] if chart else []
        if dh_pref:
            pick, kind = dh_pref[0], "depth_chart"
        else:
            pick, kind = best(spare), "eligible"
        lineup.append((pick, "DH"))
        used.add(pick)
        counters[kind] += 1
    # Short of a full defence: remaining hitters bat as DH.
    for pid in unused():
        if len(lineup) >= 9:
            break
        lineup.append((pid, "DH"))
        used.add(pid)
        counters["emergency"] += 1
    return lineup[:9], counters


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
