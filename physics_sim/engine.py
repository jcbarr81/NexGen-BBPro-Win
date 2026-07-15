from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Any, List
import random
import re

from .config import load_tuning, TuningConfig
from .data_loader import load_players_by_id
from .models import BatterRatings, PitcherRatings
from .fielding import (
    adjusted_arm_rating,
    adjusted_fielding_rating,
    build_default_defense,
    build_defense_from_lineup,
    DefenseRatings,
    compute_defense_ratings,
    out_probability,
    double_play_probability,
    select_out_type,
    error_probability,
    select_error_type,
)
from .park import load_park, Park
from .physics import (
    simulate_pitch,
    resolve_batted_ball,
    PitchResult,
    strike_zone_bounds,
    miss_distance,
)
from .usage import UsageState, reliever_rest_days
from .team_data import (
    build_staff,
    build_bench,
    load_lineup,
    load_pitching_staff,
    load_roster_status,
    active_roster_ids,
    resolve_lineup,
    _normalize_team_id,
)
from utils.path_utils import get_data_dir
from utils.lineup_autofill import auto_fill_lineup_for_team
from services.injury_simulator import InjurySimulator

# Pitch-outcome classification sets (S1-09: module constants — these were
# rebuilt as set literals on every pitch).
_STRIKE_OUTCOMES = frozenset(
    {"strike", "swinging_strike", "foul", "in_play", "interference"}
)
_BALL_OUTCOMES = frozenset({"ball", "hbp"})


@dataclass
class GameResult:
    totals: Dict[str, int]
    pitch_log: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BaseState:
    first: BatterRatings | None = None
    second: BatterRatings | None = None
    third: BatterRatings | None = None


@dataclass
class LineupState:
    lineup: List[BatterRatings]
    positions: Dict[str, str]
    bench: List[BatterRatings] = field(default_factory=list)
    bench_used: set[str] = field(default_factory=set)
    substitutions: List[Dict[str, Any]] = field(default_factory=list)
    batting_lines: Dict[str, "BatterLine"] = field(default_factory=dict)
    fielding_lines: Dict[str, "FieldingLine"] = field(default_factory=dict)


@dataclass
class PitcherState:
    pitcher: PitcherRatings
    pitches: int = 0
    fatigue_start: float = 0.0
    fatigue_limit: float = 0.0
    last_penalty: float = 0.0
    pregame_penalty: float = 0.0
    usage_multiplier: float = 1.0
    debt: float = 0.0
    used: bool = False
    available: bool = True
    staff_role: str = ""
    rest_role: str = ""
    in_save_situation: bool = False
    entered_save_opp: bool = False


@dataclass
class PitcherLine:
    pitcher_id: str
    g: int = 0
    gs: int = 0
    w: int = 0
    l: int = 0
    gf: int = 0
    sv: int = 0
    svo: int = 0
    hld: int = 0
    bs: int = 0
    ir: int = 0
    irs: int = 0
    pitches: int = 0
    batters_faced: int = 0
    outs: int = 0
    hits: int = 0
    runs: int = 0
    earned_runs: int = 0
    walks: int = 0
    ibb: int = 0
    strikeouts: int = 0
    so_looking: int = 0
    so_swinging: int = 0
    home_runs: int = 0
    b1: int = 0
    b2: int = 0
    b3: int = 0
    hbp: int = 0
    wp: int = 0
    bk: int = 0
    pk: int = 0
    pocs: int = 0
    balls: int = 0
    strikes: int = 0
    first_pitch_strikes: int = 0
    zone_pitches: int = 0
    o_zone_pitches: int = 0
    zone_swings: int = 0
    o_zone_swings: int = 0
    zone_contacts: int = 0
    o_zone_contacts: int = 0
    gb: int = 0
    ld: int = 0
    fb: int = 0
    consecutive_hits: int = 0
    inning_runs: int = 0
    inning_hits: int = 0
    inning_walks: int = 0
    inning_baserunners: int = 0
    current_inning: int = 1


@dataclass
class BatterLine:
    player_id: str
    g: int = 0
    gs: int = 0
    pa: int = 0
    ab: int = 0
    r: int = 0
    h: int = 0
    b1: int = 0
    b2: int = 0
    b3: int = 0
    hr: int = 0
    rbi: int = 0
    bb: int = 0
    ibb: int = 0
    hbp: int = 0
    so: int = 0
    so_looking: int = 0
    so_swinging: int = 0
    sh: int = 0
    sf: int = 0
    roe: int = 0
    fc: int = 0
    gidp: int = 0
    sb: int = 0
    cs: int = 0
    po: int = 0
    pocs: int = 0
    pitches: int = 0
    lob: int = 0
    lead: int = 0
    gb: int = 0
    ld: int = 0
    fb: int = 0
    ci: int = 0


# S2-01: per-PA outcome tagging on the pitch log (the log otherwise carries no PA
# result). A snapshot-diff of these BatterLine counters over a PA yields the
# outcome; these keys are only mutated during the batter's own PA.
_PA_RESULT_KEYS = (
    "ab", "h", "b2", "b3", "hr", "bb", "ibb", "hbp",
    "so", "sf", "sh", "roe", "fc", "gidp",
)


def _pa_result_token(delta: Dict[str, int]) -> str | None:
    # Priority matters: IBB also increments bb; hits increment h and ab.
    if delta.get("hr"):
        return "hr"
    if delta.get("b3"):
        return "3b"
    if delta.get("b2"):
        return "2b"
    if delta.get("h"):
        return "1b"
    if delta.get("ibb"):
        return "ibb"
    if delta.get("bb"):
        return "bb"
    if delta.get("hbp"):
        return "hbp"
    if delta.get("so"):
        return "so"
    if delta.get("sf"):
        return "sf"
    if delta.get("sh"):
        return "sh"
    if delta.get("roe"):
        return "roe"
    if delta.get("ab") or delta.get("fc") or delta.get("gidp"):
        return "out"
    return None


@dataclass
class FieldingLine:
    player_id: str
    g: int = 0
    gs: int = 0
    po: int = 0
    a: int = 0
    e: int = 0
    dp: int = 0
    tp: int = 0
    pk: int = 0
    pb: int = 0
    ci: int = 0
    cs: int = 0
    sba: int = 0


@dataclass
class TeamPitchingState:
    starter: PitcherState
    bullpen: List[PitcherState]
    current: PitcherState
    lines: Dict[str, PitcherLine] = field(default_factory=dict)

    def all_pitchers(self) -> List[PitcherState]:
        return [self.starter] + list(self.bullpen)


def _pitcher_usage_limits(
    pitcher: PitcherRatings,
    tuning: TuningConfig,
    *,
    role: str = "",
) -> tuple[float, float]:
    endurance = pitcher.endurance if pitcher.endurance > 0 else 50.0
    start_base = tuning.get("fatigue_start_base", 50.0)
    start_scale = tuning.get("fatigue_start_endurance_scale", 0.5)
    limit_base = tuning.get("fatigue_limit_base", 15.0)
    limit_scale = tuning.get("fatigue_limit_endurance_scale", 0.0)
    fatigue_start = start_base + (endurance * start_scale)
    fatigue_limit = fatigue_start + limit_base + (endurance * limit_scale)
    role = (role or "").upper()
    if role in {"CL", "SU", "MR"}:
        start_scale = tuning.get("reliever_fatigue_start_scale", 0.5)
        limit_scale = tuning.get("reliever_fatigue_limit_scale", 0.5)
        fatigue_start *= start_scale
        span = max(5.0, fatigue_limit - fatigue_start)
        fatigue_limit = fatigue_start + span * limit_scale
    elif role == "LR":
        start_scale = tuning.get("long_reliever_fatigue_start_scale", 0.75)
        limit_scale = tuning.get("long_reliever_fatigue_limit_scale", 0.75)
        fatigue_start *= start_scale
        span = max(5.0, fatigue_limit - fatigue_start)
        fatigue_limit = fatigue_start + span * limit_scale
    fatigue_limit = max(fatigue_start + 5.0, fatigue_limit)
    return fatigue_start, fatigue_limit


def _sp_sort_key(role: str) -> tuple[int, str]:
    match = re.match(r"SP(\d+)", role or "")
    if match:
        return int(match.group(1)), role
    return 99, role


def _rest_days_for_role(role: str, tuning: TuningConfig) -> int:
    role = (role or "").upper()
    if role.startswith("SP"):
        return int(tuning.get("starter_rest_days", 4.0))
    return 0  # relievers use the pitch-count table (S2-03)


def _pitcher_days_since_use(
    pitcher_id: str,
    *,
    usage_state: UsageState | None,
    game_day: int | None,
) -> int | None:
    if usage_state is None or game_day is None:
        return None
    workload = usage_state.workload_for(pitcher_id)
    if workload.last_used_day is None:
        return None
    return game_day - workload.last_used_day


def _pitcher_is_rested(
    *,
    pitcher_id: str,
    role: str,
    usage_state: UsageState | None,
    game_day: int | None,
    tuning: TuningConfig,
) -> bool:
    days_since = _pitcher_days_since_use(
        pitcher_id, usage_state=usage_state, game_day=game_day
    )
    if days_since is None:
        return True
    role_u = (role or "").upper()
    if role_u.startswith("SP"):
        return days_since >= _rest_days_for_role(role_u, tuning)
    workload = usage_state.workload_for(pitcher_id)
    required = reliever_rest_days(workload.last_pitches, tuning) + 1
    return days_since >= required


def _order_pitchers_for_game(
    pitchers: List[PitcherRatings],
    *,
    roles_by_id: Dict[str, str] | None,
    usage_state: UsageState | None,
    game_day: int | None,
    tuning: TuningConfig,
) -> List[PitcherRatings]:
    if not pitchers:
        return []
    roles_by_id = roles_by_id or {}
    starters: list[tuple[str, PitcherRatings]] = []
    bullpen: list[PitcherRatings] = []
    long_relief: list[PitcherRatings] = []
    sp_slots = {"SP1", "SP2", "SP3", "SP4", "SP5"}
    for pitcher in pitchers:
        role = roles_by_id.get(pitcher.player_id, "")
        if not role:
            role = pitcher.preferred_role or pitcher.role or ""
        role = role.upper()
        if role in sp_slots:
            starters.append((role, pitcher))
        elif role == "LR":
            long_relief.append(pitcher)
        else:
            bullpen.append(pitcher)
    if not starters:
        if long_relief:
            starter = long_relief[0]
            rest = [p for p in bullpen + long_relief if p is not starter]
            return [starter] + rest
        return list(pitchers)

    starters_sorted = sorted(starters, key=lambda item: _sp_sort_key(item[0]))
    rotation = [pitcher for _, pitcher in starters_sorted]
    start_index = 0
    if game_day is not None:
        start_index = game_day % len(rotation)
    chosen_index = start_index

    def _has_available_pitches(pitcher: PitcherRatings, role: str) -> bool:
        if usage_state is None or game_day is None:
            return True
        _, fatigue_limit = _pitcher_usage_limits(pitcher, tuning, role=role)
        if fatigue_limit <= 0:
            return False
        debt = usage_state.workload_for(pitcher.player_id).fatigue_debt
        ratio = max(0.0, debt / max(1.0, fatigue_limit))
        availability_ratio = 1.0
        if role == "CL":
            availability_ratio = tuning.get("closer_availability_ratio", 1.3)
        return ratio <= availability_ratio

    def _starter_available(pitcher: PitcherRatings, role: str) -> bool:
        return _pitcher_is_rested(
            pitcher_id=pitcher.player_id,
            role=role,
            usage_state=usage_state,
            game_day=game_day,
            tuning=tuning,
        ) and _has_available_pitches(pitcher, role)

    def _rest_score(pitcher: PitcherRatings) -> int:
        days_since = _pitcher_days_since_use(
            pitcher.player_id,
            usage_state=usage_state,
            game_day=game_day,
        )
        return days_since if days_since is not None else -1

    if usage_state is not None and game_day is not None:
        available_indices = [
            idx
            for idx, (role, pitcher) in enumerate(starters_sorted)
            if _starter_available(pitcher, role)
        ]
        if available_indices:
            for offset in range(len(rotation)):
                idx = (start_index + offset) % len(rotation)
                if idx in available_indices:
                    chosen_index = idx
                    break
        else:
            lr_candidates = [
                pitcher
                for pitcher in long_relief
                if _starter_available(pitcher, "LR")
            ]
            if lr_candidates:
                starter = max(lr_candidates, key=_rest_score)
                rest = [p for p in bullpen + long_relief if p is not starter]
                rotation_rest = list(rotation)
                return [starter] + rest + rotation_rest
            chosen_index = max(range(len(rotation)), key=lambda idx: _rest_score(rotation[idx]))

    rotation = rotation[chosen_index:] + rotation[:chosen_index]
    starter = rotation[0]
    rotation_rest = rotation[1:]
    ordered = [starter] + bullpen + long_relief + rotation_rest
    return ordered


def _fatigue_penalty(state: PitcherState, tuning: TuningConfig) -> float:
    if state.pitches <= state.fatigue_start:
        return 0.0
    span = max(1.0, state.fatigue_limit - state.fatigue_start)
    raw = (state.pitches - state.fatigue_start) / span
    raw *= tuning.get("fatigue_decay_scale", 1.0)
    durability = state.pitcher.durability if state.pitcher.durability > 0 else 50.0
    raw *= 1.0 + (50.0 - durability) / 200.0
    return min(1.5, max(0.0, raw))


def _fatigue_factors(penalty: float) -> tuple[float, float, float]:
    velocity_factor = max(0.85, 1.0 - (0.15 * penalty))
    command_factor = max(0.60, 1.0 - (0.30 * penalty))
    movement_factor = max(0.65, 1.0 - (0.25 * penalty))
    return velocity_factor, command_factor, movement_factor


def _pitcher_usage_summary(state: PitcherState) -> Dict[str, float | str]:
    return {
        "player_id": state.pitcher.player_id,
        "staff_role": state.staff_role,
        "pitches": state.pitches,
        "fatigue_start": round(state.fatigue_start, 1),
        "fatigue_limit": round(state.fatigue_limit, 1),
        "fatigue_penalty": round(state.last_penalty, 3),
        "pregame_penalty": round(state.pregame_penalty, 3),
        "usage_multiplier": round(state.usage_multiplier, 3),
        "fatigue_debt": round(state.debt, 1),
        "available": bool(state.available),
    }


def _apply_usage_state(
    state: PitcherState,
    usage_state: UsageState | None,
    game_day: int | None,
    tuning: TuningConfig,
) -> None:
    if usage_state is None or game_day is None:
        return
    workload = usage_state.workload_for(state.pitcher.player_id)
    state.debt = workload.fatigue_debt
    if state.fatigue_limit <= 0:
        return
    ratio = max(0.0, state.debt / max(1.0, state.fatigue_limit))
    penalty_scale = tuning.get("fatigue_debt_penalty_scale", 0.6)
    state.pregame_penalty = min(0.9, ratio * penalty_scale)
    start_reduction = tuning.get("fatigue_debt_start_reduction", 0.4)
    limit_reduction = tuning.get("fatigue_debt_limit_reduction", 0.5)
    state.fatigue_start = max(5.0, state.fatigue_start * (1.0 - ratio * start_reduction))
    state.fatigue_limit = max(
        state.fatigue_start + 5.0, state.fatigue_limit * (1.0 - ratio * limit_reduction)
    )
    rest_role = state.rest_role or state.staff_role
    availability_ratio = 1.0
    if rest_role == "CL":
        availability_ratio = tuning.get("closer_availability_ratio", 1.3)
    state.available = ratio <= availability_ratio
    is_starter = rest_role.upper().startswith("SP")
    if is_starter:
        required_days = _rest_days_for_role(rest_role, tuning)
    else:
        # S2-03: relievers (CL included) use the pitch-count table.
        required_days = reliever_rest_days(workload.last_pitches, tuning) + 1
    if required_days > 0 and workload.last_used_day is not None:
        days_since = game_day - workload.last_used_day
        if days_since < required_days:
            state.available = False
            rest_penalty = tuning.get("short_rest_penalty", 0.35)
            rest_deficit = required_days - days_since
            scaled = rest_penalty * (rest_deficit / max(1.0, float(required_days)))
            state.pregame_penalty = max(state.pregame_penalty, scaled)
    if not is_starter:
        # S2-03: block the 3rd consecutive day for ALL relievers.
        max_consecutive = int(tuning.get("reliever_max_consecutive_days", 2.0))
        if max_consecutive > 0 and workload.last_used_day is not None:
            if game_day - workload.last_used_day == 1:
                if workload.consecutive_days_used >= max_consecutive:
                    state.available = False
    if rest_role == "CL":
        max_ratio = float(tuning.get("closer_max_appearances_ratio", 0.0))
        if max_ratio > 0.0:
            max_apps = max(1, int((game_day + 1) * max_ratio))
            if workload.appearances >= max_apps:
                state.available = False


def _line_for_pitcher(
    team_state: TeamPitchingState, pitcher_state: PitcherState, inning: int
) -> PitcherLine:
    pid = pitcher_state.pitcher.player_id
    line = team_state.lines.get(pid)
    if line is None:
        line = PitcherLine(pitcher_id=pid, current_inning=inning)
        team_state.lines[pid] = line
    if line.g == 0:
        line.g = 1
    if pitcher_state is team_state.starter and line.gs == 0:
        line.gs = 1
    if line.current_inning != inning:
        line.current_inning = inning
        line.inning_runs = 0
        line.inning_hits = 0
        line.inning_walks = 0
        line.inning_baserunners = 0
    return line


def _times_through_order(batters_faced: int, lineup_size: int) -> int:
    if lineup_size <= 0:
        return 1
    return ((batters_faced - 1) // lineup_size) + 1


def _is_perfect(line: PitcherLine) -> bool:
    return line.hits == 0 and line.walks == 0 and line.hbp == 0


def _is_no_hit(line: PitcherLine) -> bool:
    return line.hits == 0


def _is_one_hit(line: PitcherLine) -> bool:
    return line.hits <= 1


def _hook_aggression(score_diff: int, postseason: bool, tuning: TuningConfig) -> float:
    aggression = tuning.get("hook_aggression_scale", 1.0)
    close_diff = tuning.get("close_game_run_diff", 2.0)
    if abs(score_diff) <= close_diff:
        aggression *= tuning.get("close_game_hook_scale", 1.1)
    if postseason:
        aggression *= tuning.get("postseason_hook_scale", 1.2)
    return aggression


def _should_hook_pitcher(
    *,
    pitcher_state: PitcherState,
    line: PitcherLine,
    lineup_size: int,
    score_diff: int,
    postseason: bool,
    tuning: TuningConfig,
) -> bool:
    innings_pitched = line.outs / 3.0
    achievement_inning = tuning.get("achievement_inning_threshold", 7.0)
    perfect = _is_perfect(line)
    no_hit = _is_no_hit(line)

    if innings_pitched >= achievement_inning:
        if perfect and pitcher_state.pitches <= tuning.get("perfect_pitch_limit", 170.0):
            return False
        if no_hit and pitcher_state.pitches <= tuning.get("nohit_pitch_limit", 160.0):
            return False

    role = (pitcher_state.staff_role or "").upper()
    if role in {"CL", "SU", "MR", "LR"}:
        if role == "CL":
            max_outs = int(tuning.get("closer_max_outs", 3.0))
        elif role == "SU":
            max_outs = int(tuning.get("setup_max_outs", 3.0))
        elif role == "MR":
            max_outs = int(tuning.get("middle_reliever_max_outs", 6.0))
        else:
            max_outs = int(tuning.get("long_reliever_max_outs", 9.0))
        if max_outs > 0 and line.outs >= max_outs:
            return True

    pitch_cap = pitcher_state.fatigue_limit
    if innings_pitched >= achievement_inning:
        if line.runs == 0:
            pitch_cap += tuning.get("shutout_pitch_bonus", 10.0)
        if _is_one_hit(line):
            pitch_cap += tuning.get("one_hit_pitch_bonus", 8.0)
    if pitcher_state.pitches >= pitch_cap:
        return True

    hook_score = 0.0
    if line.runs >= tuning.get("hook_runs_allowed", 5.5):
        hook_score += 1.0 + 0.2 * (line.runs - tuning.get("hook_runs_allowed", 5.5))
    if line.hits >= tuning.get("hook_hits_allowed", 8.0):
        hook_score += 0.8 + 0.15 * (line.hits - tuning.get("hook_hits_allowed", 8.0))
    if line.walks >= tuning.get("hook_walks_allowed", 4.0):
        hook_score += 0.8 + 0.2 * (line.walks - tuning.get("hook_walks_allowed", 4.0))
    if line.consecutive_hits >= tuning.get("hook_consecutive_hits", 3.0):
        hook_score += 0.3 * (
            line.consecutive_hits - tuning.get("hook_consecutive_hits", 3.0) + 1
        )
    if line.inning_runs >= tuning.get("hook_runs_in_inning", 3.0):
        hook_score += 0.6 * (
            line.inning_runs - tuning.get("hook_runs_in_inning", 3.0) + 1
        )
    if line.inning_walks >= tuning.get("hook_walks_in_inning", 2.0):
        hook_score += 0.4 * (
            line.inning_walks - tuning.get("hook_walks_in_inning", 2.0) + 1
        )
    if line.inning_baserunners >= tuning.get("hook_baserunners_in_inning", 4.0):
        hook_score += 0.4 * (
            line.inning_baserunners - tuning.get("hook_baserunners_in_inning", 4.0) + 1
        )

    fatigue_trigger = tuning.get("hook_fatigue_penalty", 0.6)
    if pitcher_state.last_penalty >= fatigue_trigger:
        hook_score += 0.8

    tto = _times_through_order(line.batters_faced, lineup_size)
    soft_trigger = tuning.get("hook_fatigue_soft_penalty", 0.3)
    if tto >= 3 and pitcher_state.last_penalty >= soft_trigger:
        hook_score += tuning.get("hook_tto_penalty", 0.4)

    hook_score *= _hook_aggression(score_diff, postseason, tuning)

    leash_bonus = 0.0
    if innings_pitched >= achievement_inning:
        if line.runs == 0:
            leash_bonus += tuning.get("leash_shutout_bonus", 0.4)
        if _is_one_hit(line):
            leash_bonus += tuning.get("leash_one_hit_bonus", 0.3)
        if no_hit:
            leash_bonus += tuning.get("leash_nohit_bonus", 0.6)
        if perfect:
            leash_bonus += tuning.get("leash_perfect_bonus", 0.8)

    return hook_score - leash_bonus >= tuning.get("hook_threshold", 1.6)


def _reliever_score(
    pitcher_state: PitcherState,
    leverage: str,
    *,
    score_diff: int,
) -> float:
    pitcher = pitcher_state.pitcher
    stuff = (pitcher.control + pitcher.movement + pitcher.arm) / 3.0
    endurance = pitcher.endurance
    freshness = 1.0 - min(0.7, pitcher_state.pregame_penalty)
    role = (pitcher_state.staff_role or "").upper()
    if leverage == "high":
        score = stuff * 1.1 + endurance * 0.1
        if score_diff > 0:
            if role in {"CL", "SU"}:
                score += 8.0
            elif role == "MR":
                score += 3.0
            elif role in {"LR"} or role.startswith("SP"):
                score -= 4.0
        elif score_diff == 0:
            # S2-04: tied high leverage — SU is the default tied-game arm; CL is
            # not penalized (eligibility is gated in _select_reliever).
            if role == "SU":
                score += 4.0
            elif role == "MR":
                score += 1.0
        else:
            if role == "CL":
                score -= 6.0  # never burn the closer down a run
            elif role == "SU":
                score -= 2.0
    elif leverage == "long":
        score = endurance * 0.7 + stuff * 0.3
        if role == "LR" or role.startswith("SP"):
            score += 6.0
        elif role in {"CL", "SU"}:
            score -= 6.0
    else:
        score = stuff * 0.6 + endurance * 0.4
        if role in {"MR", "SU"}:
            score += 2.0
        elif role == "CL":
            score -= 4.0
    return score * freshness


def _matchup_score(
    pitcher_state: PitcherState,
    upcoming_batters: List[BatterRatings] | None,
    tuning: TuningConfig,
) -> float:
    if not upcoming_batters:
        return 0.0
    pitcher_hand = (pitcher_state.pitcher.throws or "R").upper()
    score = 0.0
    for batter in upcoming_batters:
        batter_hand = (batter.bats or "R").upper()
        if batter_hand == "S":
            score -= 0.5
            effective_side = "L" if pitcher_hand == "R" else "R"
        else:
            effective_side = batter_hand
            score += 1.0 if batter_hand == pitcher_hand else -1.0
        if effective_side == "L":
            score += (pitcher_state.pitcher.vs_left - 50.0) / 25.0
    return score


def _select_reliever(
    team_state: TeamPitchingState,
    leverage: str,
    *,
    inning: int,
    score_diff: int,
    is_home_defense: bool = False,
    upcoming_batters: List[BatterRatings] | None = None,
    tuning: TuningConfig | None = None,
) -> PitcherState:
    candidates = [
        pitcher
        for pitcher in team_state.bullpen
        if pitcher.available and not pitcher.used
    ]
    if not candidates:
        return team_state.current
    closer_inning = int((tuning.get("closer_inning_min", 9.0) if tuning else 9.0))
    tied_road_inning = int(
        (tuning.get("closer_tied_road_inning_min", 10.0) if tuning else 10.0)
    )
    save_chance = leverage == "high" and score_diff > 0
    # S2-04: allow the CL in a tied game — always at home from the 9th (no save
    # can materialize), for both sides once extras start (hold on the road in a
    # tied 9th so a later lead still hands the CL a save).
    tied_closer_ok = (
        score_diff == 0
        and inning >= closer_inning
        and (is_home_defense or inning >= tied_road_inning)
    )
    if not (save_chance or tied_closer_ok):
        non_cl = [
            pitcher
            for pitcher in candidates
            if (pitcher.staff_role or "").upper() != "CL"
        ]
        if non_cl:
            candidates = non_cl
    if save_chance or tied_closer_ok:
        closers: list[PitcherState] = []
        if inning >= closer_inning:
            closers = [
                pitcher
                for pitcher in candidates
                if (pitcher.staff_role or "").upper() == "CL"
            ]
            if closers:
                candidates = closers
        if not closers and save_chance:
            setup = [
                pitcher
                for pitcher in candidates
                if (pitcher.staff_role or "").upper() == "SU"
            ]
            if setup:
                candidates = setup
    def score(candidate: PitcherState) -> float:
        base = _reliever_score(candidate, leverage, score_diff=score_diff)
        if tuning is None or not upcoming_batters:
            return base
        matchup = _matchup_score(candidate, upcoming_batters, tuning)
        return base + matchup * tuning.get("bullpen_platoon_weight", 2.0)

    return max(candidates, key=score)


def _leverage_type(inning: int, score_diff: int, tuning: TuningConfig) -> str:
    save_diff = int(tuning.get("save_opportunity_run_diff", 3.0))
    if inning >= 8 and score_diff > 0 and score_diff <= save_diff:
        return "high"
    close_diff = tuning.get("close_game_run_diff", 2.0)
    close_game = abs(score_diff) <= close_diff
    if close_game and inning >= 8:
        return "high"
    if inning <= 5:
        return "long"
    return "mid"


def _usage_multiplier(
    *, inning: int, score_diff: int, postseason: bool, tuning: TuningConfig
) -> float:
    mult = 1.0
    close_diff = tuning.get("close_game_run_diff", 2.0)
    if abs(score_diff) <= close_diff and inning >= 7:
        mult += 0.15
    if postseason:
        mult += 0.1
    return mult


def _enter_pitcher(
    team_state: TeamPitchingState,
    pitcher_state: PitcherState,
    *,
    inning: int,
    score_diff: int,
    postseason: bool,
    tuning: TuningConfig,
) -> None:
    pitcher_state.used = True
    pitcher_state.usage_multiplier = _usage_multiplier(
        inning=inning, score_diff=score_diff, postseason=postseason, tuning=tuning
    )
    team_state.current = pitcher_state


def _save_opportunity(
    *,
    lead: int,
    inning: int,
    bases: BaseState,
    tuning: TuningConfig,
) -> bool:
    save_diff = int(tuning.get("save_opportunity_run_diff", 3.0))
    min_inning = int(tuning.get("save_opportunity_inning", 1.0))
    if lead <= 0 or inning < min_inning:
        return False
    if lead <= save_diff:
        return True
    runners_on = sum(
        1 for runner in (bases.first, bases.second, bases.third) if runner is not None
    )
    if lead == save_diff + 1 and runners_on >= 2:
        return True
    if lead == save_diff + 2 and runners_on >= 3:
        return True
    return False


def _pitcher_exit_stats(
    *,
    pitcher_state: PitcherState,
    line: PitcherLine,
    defense_score: int,
    offense_score: int,
    game_finished: bool,
) -> None:
    lead = defense_score - offense_score
    if pitcher_state.entered_save_opp and pitcher_state.in_save_situation:
        if lead > 0:
            if not game_finished and line.outs > 0:
                line.hld += 1
        else:
            line.bs += 1
    pitcher_state.in_save_situation = False


def _pitcher_enter_stats(
    *,
    pitching_state: TeamPitchingState,
    pitcher_state: PitcherState,
    lineup_state: LineupState,
    inning: int,
    score_diff: int,
    defense_score: int,
    offense_score: int,
    bases: BaseState,
    postseason: bool,
    tuning: TuningConfig,
) -> PitcherLine:
    _enter_pitcher(
        pitching_state,
        pitcher_state,
        inning=inning,
        score_diff=score_diff,
        postseason=postseason,
        tuning=tuning,
    )
    line = _line_for_pitcher(pitching_state, pitcher_state, inning)
    _fielding_line(lineup_state, pitcher_state.pitcher.player_id)
    inherited = sum(
        1 for runner in (bases.first, bases.second, bases.third) if runner is not None
    )
    if inherited:
        line.ir += inherited
        line.inning_baserunners += inherited
    lead = defense_score - offense_score
    save_opp = _save_opportunity(lead=lead, inning=inning, bases=bases, tuning=tuning)
    pitcher_state.entered_save_opp = save_opp
    pitcher_state.in_save_situation = save_opp
    if save_opp:
        line.svo += 1
    return line


def _build_team_pitching_state(
    pitchers: List[PitcherRatings],
    *,
    tuning: TuningConfig,
    usage_state: UsageState | None,
    game_day: int | None,
    postseason: bool,
    roles_by_id: Dict[str, str] | None = None,
) -> TeamPitchingState:
    if not pitchers:
        raise ValueError("At least one pitcher is required to simulate a game.")
    starter_role = ""
    if roles_by_id is not None:
        starter_role = roles_by_id.get(pitchers[0].player_id, "")
    if not starter_role:
        starter_role = pitchers[0].preferred_role or pitchers[0].role
    starter_limits = _pitcher_usage_limits(
        pitchers[0],
        tuning,
        role=starter_role,
    )
    starter_state = PitcherState(
        pitcher=pitchers[0],
        fatigue_start=starter_limits[0],
        fatigue_limit=starter_limits[1],
        staff_role=starter_role,
        rest_role=starter_role,
    )
    _apply_usage_state(starter_state, usage_state, game_day, tuning)
    bullpen: list[PitcherState] = []
    for pitcher in pitchers[1:]:
        staff_role = ""
        if roles_by_id is not None:
            staff_role = roles_by_id.get(pitcher.player_id, "")
        if not staff_role:
            staff_role = pitcher.preferred_role or pitcher.role
        if staff_role.upper().startswith("SP"):
            continue
        bullpen_role = staff_role
        fatigue_start, fatigue_limit = _pitcher_usage_limits(
            pitcher,
            tuning,
            role=bullpen_role,
        )
        reliever_state = PitcherState(
            pitcher=pitcher,
            fatigue_start=fatigue_start,
            fatigue_limit=fatigue_limit,
            staff_role=bullpen_role,
            rest_role=staff_role,
        )
        _apply_usage_state(reliever_state, usage_state, game_day, tuning)
        bullpen.append(reliever_state)
    if not bullpen:
        for pitcher in pitchers[1:]:
            staff_role = ""
            if roles_by_id is not None:
                staff_role = roles_by_id.get(pitcher.player_id, "")
            if not staff_role:
                staff_role = pitcher.preferred_role or pitcher.role
            fatigue_start, fatigue_limit = _pitcher_usage_limits(
                pitcher,
                tuning,
                role="LR",
            )
            reliever_state = PitcherState(
                pitcher=pitcher,
                fatigue_start=fatigue_start,
                fatigue_limit=fatigue_limit,
                staff_role="LR",
                rest_role=staff_role,
            )
            _apply_usage_state(reliever_state, usage_state, game_day, tuning)
            bullpen.append(reliever_state)
    team_state = TeamPitchingState(
        starter=starter_state,
        bullpen=bullpen,
        current=starter_state,
    )
    starter_state.used = True
    starter_state.usage_multiplier = _usage_multiplier(
        inning=1, score_diff=0, postseason=postseason, tuning=tuning
    )
    return team_state


def _pitcher_line_summary(line: PitcherLine) -> Dict[str, float | str]:
    return {
        "player_id": line.pitcher_id,
        "g": line.g,
        "gs": line.gs,
        "w": line.w,
        "l": line.l,
        "gf": line.gf,
        "sv": line.sv,
        "svo": line.svo,
        "hld": line.hld,
        "bs": line.bs,
        "ir": line.ir,
        "irs": line.irs,
        "bf": line.batters_faced,
        "batters_faced": line.batters_faced,
        "outs": line.outs,
        "innings_pitched": round(line.outs / 3.0, 1),
        "hits": line.hits,
        "h": line.hits,
        "runs": line.runs,
        "r": line.runs,
        "earned_runs": line.earned_runs,
        "er": line.earned_runs,
        "home_runs": line.home_runs,
        "hr": line.home_runs,
        "1b": line.b1,
        "2b": line.b2,
        "3b": line.b3,
        "walks": line.walks,
        "bb": line.walks,
        "ibb": line.ibb,
        "strikeouts": line.strikeouts,
        "so": line.strikeouts,
        "so_looking": line.so_looking,
        "so_swinging": line.so_swinging,
        "hbp": line.hbp,
        "wp": line.wp,
        "bk": line.bk,
        "pk": line.pk,
        "pocs": line.pocs,
        "pitches": line.pitches,
        "balls": line.balls,
        "strikes": line.strikes,
        "first_pitch_strikes": line.first_pitch_strikes,
        "zone_pitches": line.zone_pitches,
        "o_zone_pitches": line.o_zone_pitches,
        "zone_swings": line.zone_swings,
        "o_zone_swings": line.o_zone_swings,
        "zone_contacts": line.zone_contacts,
        "o_zone_contacts": line.o_zone_contacts,
        "gb": line.gb,
        "ld": line.ld,
        "fb": line.fb,
    }


def _team_line_summaries(team_state: TeamPitchingState) -> List[Dict[str, float | str]]:
    return [_pitcher_line_summary(line) for line in team_state.lines.values()]


def _batter_line(lineup_state: LineupState, batter: BatterRatings) -> BatterLine:
    line = lineup_state.batting_lines.get(batter.player_id)
    if line is None:
        line = BatterLine(player_id=batter.player_id)
        lineup_state.batting_lines[batter.player_id] = line
    return line


def _batter_line_summary(line: BatterLine) -> Dict[str, int]:
    return {
        "player_id": line.player_id,
        "g": line.g,
        "gs": line.gs,
        "pa": line.pa,
        "ab": line.ab,
        "r": line.r,
        "h": line.h,
        "b1": line.b1,
        "b2": line.b2,
        "b3": line.b3,
        "hr": line.hr,
        "rbi": line.rbi,
        "bb": line.bb,
        "ibb": line.ibb,
        "hbp": line.hbp,
        "so": line.so,
        "so_looking": line.so_looking,
        "so_swinging": line.so_swinging,
        "sh": line.sh,
        "sf": line.sf,
        "roe": line.roe,
        "fc": line.fc,
        "gidp": line.gidp,
        "sb": line.sb,
        "cs": line.cs,
        "po": line.po,
        "pocs": line.pocs,
        "pitches": line.pitches,
        "lob": line.lob,
        "lead": line.lead,
        "gb": line.gb,
        "ld": line.ld,
        "fb": line.fb,
        "ci": line.ci,
    }


def _team_batting_summaries(lineup_state: LineupState) -> List[Dict[str, int]]:
    order = [b.player_id for b in lineup_state.lineup]
    seen = set(order)
    ordered_lines = [
        lineup_state.batting_lines[player_id]
        for player_id in order
        if player_id in lineup_state.batting_lines
    ]
    for player_id, line in lineup_state.batting_lines.items():
        if player_id in seen:
            continue
        ordered_lines.append(line)
    return [_batter_line_summary(line) for line in ordered_lines]


def _fielding_line(
    lineup_state: LineupState, player_id: str, *, starting: bool = False
) -> FieldingLine:
    line = lineup_state.fielding_lines.get(player_id)
    if line is None:
        line = FieldingLine(player_id=player_id)
        lineup_state.fielding_lines[player_id] = line
    line.g = max(1, line.g)
    if starting:
        line.gs = max(1, line.gs)
    return line


def _fielding_line_summary(line: FieldingLine) -> Dict[str, int]:
    return {
        "player_id": line.player_id,
        "g": line.g,
        "gs": line.gs,
        "po": line.po,
        "a": line.a,
        "e": line.e,
        "dp": line.dp,
        "tp": line.tp,
        "pk": line.pk,
        "pb": line.pb,
        "ci": line.ci,
        "cs": line.cs,
        "sba": line.sba,
    }


def _team_fielding_summaries(lineup_state: LineupState) -> List[Dict[str, int]]:
    order = [b.player_id for b in lineup_state.lineup]
    seen = set(order)
    ordered_lines = [
        lineup_state.fielding_lines[player_id]
        for player_id in order
        if player_id in lineup_state.fielding_lines
    ]
    for player_id, line in lineup_state.fielding_lines.items():
        if player_id in seen:
            continue
        ordered_lines.append(line)
    return [_fielding_line_summary(line) for line in ordered_lines]


def _base_runner_ids(bases: BaseState) -> set[str]:
    return {
        runner.player_id
        for runner in (bases.first, bases.second, bases.third)
        if runner is not None
    }


def _reconcile_runner_pitchers(
    runner_pitchers: dict[str, PitcherLine],
    *,
    before_ids: set[str],
    bases: BaseState,
    scored: list[BatterRatings],
) -> None:
    after_ids = _base_runner_ids(bases)
    scored_ids = {runner.player_id for runner in scored}
    removed = before_ids - after_ids - scored_ids
    for runner_id in removed:
        runner_pitchers.pop(runner_id, None)


def _lead_level(
    *,
    speed: float,
    pitcher_hold: float,
    balls: int,
    strikes: int,
    outs: int,
    tuning: TuningConfig,
) -> int:
    lead = 0.0
    speed_threshold = tuning.get("lead_speed_threshold", 70.0)
    aggressive_threshold = tuning.get("lead_speed_aggressive", 85.0)
    if speed >= speed_threshold:
        lead = 1.0
    if speed >= aggressive_threshold:
        lead = 2.0
    if balls - strikes >= 2:
        lead += tuning.get("lead_ball_bonus", 1.0)
    elif strikes - balls >= 2:
        lead -= tuning.get("lead_two_strike_penalty", 1.0)
    if outs >= 2:
        lead -= tuning.get("lead_two_out_penalty", 1.0)
    hold_threshold = tuning.get("lead_hold_threshold", 70.0)
    if pitcher_hold >= hold_threshold:
        lead -= 1.0
    lead = max(0.0, min(2.0, lead))
    return int(round(lead))


def _update_runner_leads(
    *,
    bases: BaseState,
    lineup_state: LineupState,
    pitcher_hold: float,
    balls: int,
    strikes: int,
    outs: int,
    tuning: TuningConfig,
) -> None:
    for runner in (bases.first, bases.second):
        if runner is None:
            continue
        lead = _lead_level(
            speed=runner.speed,
            pitcher_hold=pitcher_hold,
            balls=balls,
            strikes=strikes,
            outs=outs,
            tuning=tuning,
        )
        _batter_line(lineup_state, runner).lead += lead

def _advance_on_walk(
    bases: BaseState, batter: BatterRatings
) -> tuple[int, list[BatterRatings]]:
    runs = 0
    scored: list[BatterRatings] = []
    if bases.first and bases.second and bases.third:
        runs += 1
        scored.append(bases.third)
        bases.third = bases.second
        bases.second = bases.first
        bases.first = batter
        return runs, scored
    if bases.second and bases.first and not bases.third:
        bases.third = bases.second
        bases.second = bases.first
        bases.first = batter
        return runs, scored
    if bases.first and not bases.second:
        bases.second = bases.first
        bases.first = batter
        return runs, scored
    bases.first = batter
    return runs, scored


def _advance_prob(speed: float, arm: float, tuning: TuningConfig, extra: float = 0.0) -> float:
    base = 0.45 + (speed - 50.0) / 200.0 - (arm - 50.0) / 250.0 + extra
    base *= tuning.get("advancement_aggression_scale", 1.0)
    return max(0.05, min(0.95, base))


def _out_on_base_prob(
    speed: float, arm: float, tuning: TuningConfig, extra: float = 0.0
) -> float:
    base = tuning.get("extra_base_out_base", 0.08) + extra
    base += (arm - 50.0) / 200.0
    base -= (speed - 50.0) / 240.0
    base *= tuning.get("extra_base_out_scale", 1.0)
    return max(0.01, min(0.55, base))


def _throw_error_probability(defense_arm: float, tuning: TuningConfig) -> float:
    base = tuning.get("throw_error_base", 0.015)
    arm_adj = (50.0 - defense_arm) / 300.0
    arm_adj *= tuning.get("throw_error_arm_scale", 1.0)
    prob = (base + arm_adj) * tuning.get("throw_error_scale", 1.0)
    return max(0.001, min(0.08, prob))


def _attempt_extra_base(
    *,
    runner: BatterRatings,
    defense_arm: float,
    tuning: TuningConfig,
    attempt_extra: float = 0.0,
    out_extra: float = 0.0,
    force: bool = False,
) -> str:
    attempt_prob = _advance_prob(
        runner.speed, defense_arm, tuning, extra=attempt_extra
    )
    if not force and random.random() >= attempt_prob:
        return "hold"
    out_prob = _out_on_base_prob(
        runner.speed, defense_arm, tuning, extra=out_extra
    )
    if random.random() < out_prob:
        if random.random() < _throw_error_probability(defense_arm, tuning):
            return "error"
        return "out"
    return "advance"


def _advance_on_hit(
    *,
    bases: BaseState,
    batter: BatterRatings,
    hit_type: str,
    defense_arm: float,
    tuning: TuningConfig,
) -> tuple[int, int, list[str], list[BatterRatings], list[BatterRatings]]:
    runs = 0
    outs = 0
    events: list[str] = []
    scored: list[BatterRatings] = []
    error_advances: list[BatterRatings] = []
    if hit_type == "hr":
        scored.extend(
            runner for runner in (bases.first, bases.second, bases.third) if runner
        )
        scored.append(batter)
        runs = len(scored)
        bases.first = bases.second = bases.third = None
        return runs, outs, events, scored, error_advances

    if hit_type == "triple":
        scored.extend(
            runner for runner in (bases.first, bases.second, bases.third) if runner
        )
        runs = len(scored)
        bases.first = bases.second = None
        bases.third = batter
        return runs, outs, events, scored, error_advances

    if hit_type == "double":
        runner_first = bases.first
        runner_second = bases.second
        runner_third = bases.third
        bases.first = None
        bases.second = batter
        bases.third = None

        if runner_third:
            result = _attempt_extra_base(
                runner=runner_third,
                defense_arm=defense_arm,
                tuning=tuning,
                attempt_extra=0.25,
                out_extra=-0.02,
                force=True,
            )
            if result == "out":
                outs += 1
                events.append("oobH")
            elif result == "error":
                runs += 1
                scored.append(runner_third)
                error_advances.append(runner_third)
                events.append("e_th")
            else:
                runs += 1
                scored.append(runner_third)

        if runner_second:
            result = _attempt_extra_base(
                runner=runner_second,
                defense_arm=defense_arm,
                tuning=tuning,
                attempt_extra=0.15,
                out_extra=0.02,
                force=True,
            )
            if result == "out":
                outs += 1
                events.append("oobH")
            elif result == "error":
                runs += 1
                scored.append(runner_second)
                error_advances.append(runner_second)
                events.append("e_th")
            else:
                runs += 1
                scored.append(runner_second)

        if runner_first:
            result = _attempt_extra_base(
                runner=runner_first,
                defense_arm=defense_arm,
                tuning=tuning,
                attempt_extra=-0.05,
                out_extra=0.12,
                force=False,
            )
            if result == "advance":
                runs += 1
                scored.append(runner_first)
            elif result == "error":
                runs += 1
                scored.append(runner_first)
                error_advances.append(runner_first)
                events.append("e_th")
            elif result == "out":
                outs += 1
                events.append("oobH")
            else:
                bases.third = runner_first
        return runs, outs, events, scored, error_advances

    # Single
    runner_first = bases.first
    runner_second = bases.second
    runner_third = bases.third
    bases.first = batter
    bases.second = None
    bases.third = None

    if runner_third:
        result = _attempt_extra_base(
            runner=runner_third,
            defense_arm=defense_arm,
            tuning=tuning,
            attempt_extra=0.25,
            out_extra=-0.02,
            force=True,
        )
        if result == "out":
            outs += 1
            events.append("oobH")
        elif result == "error":
            runs += 1
            scored.append(runner_third)
            error_advances.append(runner_third)
            events.append("e_th")
        else:
            runs += 1
            scored.append(runner_third)

    if runner_second:
        result = _attempt_extra_base(
            runner=runner_second,
            defense_arm=defense_arm,
            tuning=tuning,
            attempt_extra=0.15,
            out_extra=0.05,
            force=False,
        )
        if result == "advance":
            runs += 1
            scored.append(runner_second)
        elif result == "error":
            runs += 1
            scored.append(runner_second)
            error_advances.append(runner_second)
            events.append("e_th")
        elif result == "out":
            outs += 1
            events.append("oobH")
        else:
            bases.third = runner_second

    if runner_first:
        if bases.third is None:
            result = _attempt_extra_base(
                runner=runner_first,
                defense_arm=defense_arm,
                tuning=tuning,
                attempt_extra=0.05,
                out_extra=0.08,
                force=False,
            )
            if result == "advance":
                bases.third = runner_first
            elif result == "error":
                error_advances.append(runner_first)
                events.append("e_th")
                if random.random() < tuning.get("throw_error_extra_base_chance", 0.35):
                    runs += 1
                    scored.append(runner_first)
                else:
                    bases.third = runner_first
            elif result == "out":
                outs += 1
                events.append("oob3")
            else:
                bases.second = runner_first
        else:
            bases.second = runner_first
    return runs, outs, events, scored, error_advances


def _maybe_upgrade_hit(
    *,
    hit_type: str,
    batter: BatterRatings,
    ball_type: str | None,
    defense_arm: float,
    tuning: TuningConfig,
) -> str:
    if hit_type not in {"single", "double"}:
        return hit_type
    if ball_type not in {"ld", "fb"}:
        return hit_type
    speed_norm = max(0.0, (batter.speed - 50.0) / 50.0)
    if hit_type == "single":
        base = tuning.get("stretch_double_base", 0.0)
        speed_scale = tuning.get("stretch_double_speed_scale", 0.0)
        arm_scale = tuning.get("stretch_double_arm_scale", 0.0)
        upgrade_to = "double"
    else:
        base = tuning.get("stretch_triple_base", 0.0)
        speed_scale = tuning.get("stretch_triple_speed_scale", 0.0)
        arm_scale = tuning.get("stretch_triple_arm_scale", 0.0)
        upgrade_to = "triple"
    chance = base + speed_norm * speed_scale
    arm_penalty = 1.0 - (defense_arm / 100.0) * arm_scale
    chance *= max(0.1, arm_penalty)
    if random.random() < chance:
        return upgrade_to
    return hit_type


def _credit_outs_on_base(
    *,
    defense_state: LineupState,
    defense_map: Dict[str, BatterRatings],
    events: list[str],
    ball_type: str | None,
    spray_angle: float | None,
    batter_side: str,
    tuning: TuningConfig,
) -> None:
    if not events:
        return
    out_events = [event for event in events if event in {"oobH", "oob3"}]
    if not out_events:
        return
    infield_play = ball_type == "gb"
    fallback = ["SS", "2B", "3B", "1B"] if infield_play else ["CF", "LF", "RF"]
    fielder_pos = _fielder_position_for_ball(
        ball_type=ball_type or "fb",
        spray_angle=spray_angle,
        batter_side=batter_side,
        tuning=tuning,
        infield_play=infield_play,
    )
    _, assist_fielder = _find_fielder(
        defense_map, fielder_pos, fallback_positions=fallback
    )
    for event in out_events:
        putout_pos = "C" if event == "oobH" else "3B"
        if assist_fielder is not None:
            _fielding_line(defense_state, assist_fielder.player_id).a += 1
        putout_fielder = defense_map.get(putout_pos)
        if putout_fielder is not None:
            _fielding_line(defense_state, putout_fielder.player_id).po += 1


def _append_entry_value(entry: dict[str, Any], key: str, value: str) -> None:
    existing = entry.get(key)
    if existing is None:
        entry[key] = value
        return
    if isinstance(existing, list):
        if value not in existing:
            existing.append(value)
        return
    if existing != value:
        entry[key] = [existing, value]


def _credit_throw_error(
    *,
    defense_state: LineupState,
    defense_map: Dict[str, BatterRatings],
    ball_type: str | None,
    spray_angle: float | None,
    batter_side: str,
    infield_play: bool,
    tuning: TuningConfig,
) -> None:
    fallback = ["SS", "2B", "3B", "1B"] if infield_play else ["CF", "LF", "RF"]
    fielder_pos = _fielder_position_for_ball(
        ball_type=ball_type or "fb",
        spray_angle=spray_angle,
        batter_side=batter_side,
        tuning=tuning,
        infield_play=infield_play,
    )
    _, fielder = _find_fielder(
        defense_map, fielder_pos, fallback_positions=fallback
    )
    if fielder is not None:
        _fielding_line(defense_state, fielder.player_id).e += 1


def _advance_on_error(
    *,
    bases: BaseState,
    batter: BatterRatings,
    defense_arm: float,
    tuning: TuningConfig,
) -> tuple[int, int, list[str], list[BatterRatings], list[BatterRatings]]:
    return _advance_on_hit(
        bases=bases,
        batter=batter,
        hit_type="single",
        defense_arm=defense_arm,
        tuning=tuning,
    )


def _advance_on_air_out(
    *,
    bases: BaseState,
    outs: int,
    thrower_arm: float,
    tuning: TuningConfig,
) -> tuple[int, int, bool, list[BatterRatings], BatterRatings | None]:
    runs = 0
    extra_outs = 0
    sac_fly = False
    scored: list[BatterRatings] = []
    tag_out_runner: BatterRatings | None = None
    if bases.third and outs < 2:
        prob = _advance_prob(
            bases.third.speed,
            thrower_arm,
            tuning,
            extra=tuning.get("tag_up_third_extra", 0.15),
        )
        if random.random() < prob:
            runs += 1
            scored.append(bases.third)
            sac_fly = True
            bases.third = None
        else:
            extra_outs += 1
            tag_out_runner = bases.third
            bases.third = None
    if bases.second and outs < 2 and bases.third is None:
        prob = _advance_prob(
            bases.second.speed,
            thrower_arm,
            tuning,
            extra=tuning.get("tag_up_second_extra", 0.05),
        )
        if random.random() < prob:
            bases.third = bases.second
            bases.second = None
    return runs, extra_outs, sac_fly, scored, tag_out_runner


def _fielder_ratings(
    *,
    fielder: BatterRatings | None,
    position: str | None,
    fallback_fielding: float,
    fallback_arm: float,
    tuning: TuningConfig,
) -> tuple[float, float]:
    if fielder is None or position is None:
        return fallback_fielding, fallback_arm
    fielding = adjusted_fielding_rating(fielder, position, tuning)
    fielding *= tuning.get("range_scale", 1.0)
    arm = adjusted_arm_rating(fielder, tuning)
    return fielding, arm


def _catcher_context(
    defense: Dict[str, BatterRatings],
    defense_ratings: DefenseRatings,
    tuning: TuningConfig,
) -> tuple[float, float]:
    catcher = defense.get("C")
    if catcher is None:
        return 50.0, defense_ratings.arm
    fielding = adjusted_fielding_rating(catcher, "C", tuning)
    fielding *= tuning.get("range_scale", 1.0)
    arm = adjusted_arm_rating(catcher, tuning)
    return fielding, arm


def _effective_batter_side(batter_hand: str | None, pitcher_hand: str | None) -> str:
    hand = (batter_hand or "R").upper()
    pitcher = (pitcher_hand or "R").upper()
    if hand == "S":
        return "L" if pitcher == "R" else "R"
    if hand in {"L", "R"}:
        return hand
    return "R"


def _spray_dir(angle: float, batter_side: str) -> float:
    spray = float(angle)
    if batter_side == "R":
        spray = -spray
    return spray


def _infield_pos_for_spray(spray_dir: float) -> str:
    if spray_dir >= 25:
        return "3B"
    if spray_dir <= -25:
        return "1B"
    if spray_dir >= 6:
        return "SS"
    if spray_dir <= -6:
        return "2B"
    return "SS" if spray_dir >= 0 else "2B"


def _outfield_pos_for_spray(spray_dir: float, tuning: TuningConfig) -> str:
    center_band = tuning.get("spray_center_band_deg", 8.0)
    if abs(spray_dir) <= center_band:
        return "CF"
    return "LF" if spray_dir > 0 else "RF"


def _fielder_position_for_ball(
    *,
    ball_type: str,
    spray_angle: float | None,
    batter_side: str,
    tuning: TuningConfig,
    infield_play: bool,
) -> str:
    angle = spray_angle or 0.0
    spray_dir = _spray_dir(angle, batter_side)
    if ball_type == "gb":
        return _infield_pos_for_spray(spray_dir)
    if infield_play:
        return _infield_pos_for_spray(spray_dir)
    return _outfield_pos_for_spray(spray_dir, tuning)


def _find_fielder(
    defense_map: Dict[str, BatterRatings],
    primary_pos: str,
    fallback_positions: list[str] | None = None,
) -> tuple[str, BatterRatings] | tuple[None, None]:
    positions = [primary_pos] + (fallback_positions or [])
    for pos in positions:
        player = defense_map.get(pos)
        if player is not None:
            return pos, player
    return None, None


def _pickoff_attempt_rate(
    *,
    speed: float,
    base_rate: float,
    pitcher_hold: float,
    tuning: TuningConfig,
) -> float:
    rate = base_rate * tuning.get("pickoff_freq_scale", 1.0)
    rate *= 0.7 + (speed - 50.0) / 120.0
    rate *= 0.8 + (pitcher_hold - 50.0) / 140.0
    return max(0.0002, min(0.05, rate))


def _pickoff_success_prob(
    *,
    speed: float,
    pitcher_hold: float,
    pitcher_arm: float,
    defense_arm: float,
    tuning: TuningConfig,
) -> float:
    base = tuning.get("pickoff_success_base", 0.06)
    base += (pitcher_hold - 50.0) / 240.0
    base += (pitcher_arm - 50.0) / 320.0
    base *= tuning.get("pickoff_arm_scale", 1.0)
    base += (defense_arm - 50.0) / 260.0
    base -= (speed - 50.0) / 200.0
    base *= tuning.get("pickoff_success_scale", 1.0)
    return max(0.01, min(0.5, base))


def _attempt_pickoff(
    *,
    bases: BaseState,
    pitcher_hold: float,
    pitcher_arm: float,
    defense_arm: float,
    tuning: TuningConfig,
) -> tuple[str | None, int, bool]:
    if bases.first:
        runner = bases.first
        rate = _pickoff_attempt_rate(
            speed=runner.speed,
            base_rate=tuning.get("pickoff_attempt_rate_first", 0.004),
            pitcher_hold=pitcher_hold,
            tuning=tuning,
        )
        if random.random() < rate:
            success = _pickoff_success_prob(
                speed=runner.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                defense_arm=defense_arm,
                tuning=tuning,
            )
            if random.random() < success:
                bases.first = None
                return "po1", 1, True
            return "poa1", 0, True
    if bases.second:
        runner = bases.second
        rate = _pickoff_attempt_rate(
            speed=runner.speed,
            base_rate=tuning.get("pickoff_attempt_rate_second", 0.0015),
            pitcher_hold=pitcher_hold,
            tuning=tuning,
        )
        if random.random() < rate:
            success = _pickoff_success_prob(
                speed=runner.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                defense_arm=defense_arm,
                tuning=tuning,
            )
            if random.random() < success:
                bases.second = None
                return "po2", 1, True
            return "poa2", 0, True
    if bases.third:
        runner = bases.third
        rate = _pickoff_attempt_rate(
            speed=runner.speed,
            base_rate=tuning.get("pickoff_attempt_rate_third", 0.0003),
            pitcher_hold=pitcher_hold,
            tuning=tuning,
        )
        if random.random() < rate:
            success = _pickoff_success_prob(
                speed=runner.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                defense_arm=defense_arm,
                tuning=tuning,
            )
            if random.random() < success:
                bases.third = None
                return "po3", 1, True
            return "poa3", 0, True
    return None, 0, False


def _pickoff_caught_stealing(
    *,
    runner: BatterRatings,
    base: str,
    pitcher_hold: float,
    pitcher_arm: float,
    catcher_arm: float,
    catcher_fielding: float,
    balls: int,
    strikes: int,
    outs: int,
    inning: int,
    score_diff: int,
    tuning: TuningConfig,
) -> bool:
    base_rates = {
        "first": tuning.get("steal_attempt_rate_first", 0.012),
        "second": tuning.get("steal_attempt_rate_second", 0.006),
        "third": tuning.get("steal_attempt_rate_home", 0.001),
    }
    base_rate = base_rates.get(base)
    if base_rate is None:
        return False
    rate = _steal_attempt_rate(
        speed=runner.speed,
        base_rate=base_rate,
        pitcher_hold=pitcher_hold,
        pitcher_arm=pitcher_arm,
        catcher_arm=catcher_arm,
        catcher_fielding=catcher_fielding,
        tuning=tuning,
    )
    rate *= _steal_context_multiplier(
        balls=balls,
        strikes=strikes,
        outs=outs,
        inning=inning,
        score_diff=score_diff,
        tuning=tuning,
    )
    return random.random() < rate


def _steal_attempt_rate(
    *,
    speed: float,
    base_rate: float,
    pitcher_hold: float,
    pitcher_arm: float,
    catcher_arm: float,
    catcher_fielding: float,
    tuning: TuningConfig,
) -> float:
    attempt = base_rate * tuning.get("steal_freq_scale", 1.0)
    attempt *= 0.5 + (speed - 50.0) / 60.0
    attempt *= 1.0 - (pitcher_hold - 50.0) / 180.0
    pitcher_adj = (pitcher_arm - 50.0) / 260.0
    pitcher_adj *= tuning.get("steal_pitcher_arm_deterrent", 1.0)
    attempt *= 1.0 - pitcher_adj
    attempt *= 1.0 - (catcher_arm - 50.0) / 220.0
    fielding_adj = (catcher_fielding - 50.0) / 260.0
    fielding_adj *= tuning.get("steal_catcher_fielding_deterrent", 1.0)
    attempt *= 1.0 - fielding_adj
    return max(0.001, min(0.25, attempt))


def _steal_context_multiplier(
    *,
    balls: int,
    strikes: int,
    outs: int,
    inning: int,
    score_diff: int,
    tuning: TuningConfig,
) -> float:
    mult = 1.0
    if balls - strikes >= 2:
        mult *= tuning.get("steal_count_favorable", 1.25)
    elif strikes - balls >= 2:
        mult *= tuning.get("steal_count_unfavorable", 0.75)
    if strikes >= 2:
        mult *= tuning.get("steal_two_strike_scale", 0.85)
    if balls >= 3:
        mult *= tuning.get("steal_three_ball_scale", 1.1)
    if outs >= 2:
        mult *= tuning.get("steal_two_out_scale", 1.05)
    if inning <= 2:
        mult *= tuning.get("steal_early_inning_scale", 0.9)
    if inning >= 7 and abs(score_diff) <= 2:
        mult *= tuning.get("steal_close_late_scale", 1.2)
    if score_diff >= 3:
        mult *= tuning.get("steal_ahead_big_scale", 0.7)
    if score_diff <= -3:
        mult *= tuning.get("steal_behind_big_scale", 0.85)
    return max(0.1, min(3.0, mult))


def _steal_success_prob(
    *,
    speed: float,
    pitcher_hold: float,
    pitcher_arm: float,
    catcher_arm: float,
    catcher_fielding: float,
    tuning: TuningConfig,
) -> float:
    base = tuning.get("steal_success_base", 0.72)
    base += (speed - 50.0) / 150.0
    base -= (pitcher_hold - 50.0) / 250.0
    pitcher_adj = (pitcher_arm - 50.0) / 300.0
    pitcher_adj *= tuning.get("steal_pitcher_arm_success", 1.0)
    base -= pitcher_adj
    base -= (catcher_arm - 50.0) / 220.0
    fielding_adj = (catcher_fielding - 50.0) / 280.0
    fielding_adj *= tuning.get("steal_catcher_fielding_success", 1.0)
    base -= fielding_adj
    return max(0.1, min(0.95, base))


def _attempt_steal(
    *,
    bases: BaseState,
    pitcher_hold: float,
    pitcher_arm: float,
    catcher_arm: float,
    catcher_fielding: float,
    balls: int,
    strikes: int,
    outs: int,
    inning: int,
    score_diff: int,
    tuning: TuningConfig,
) -> tuple[list[tuple[BatterRatings, str]], int, int, list[BatterRatings]]:
    events: list[tuple[BatterRatings, str]] = []
    outs_added = 0
    runs_scored = 0
    scored: list[BatterRatings] = []

    context_mult = _steal_context_multiplier(
        balls=balls,
        strikes=strikes,
        outs=outs,
        inning=inning,
        score_diff=score_diff,
        tuning=tuning,
    )

    if bases.third:
        runner = bases.third
        rate = _steal_attempt_rate(
            speed=runner.speed,
            base_rate=tuning.get("steal_attempt_rate_home", 0.001),
            pitcher_hold=pitcher_hold,
            pitcher_arm=pitcher_arm,
            catcher_arm=catcher_arm,
            catcher_fielding=catcher_fielding,
            tuning=tuning,
        )
        rate *= context_mult
        if random.random() < rate:
            success = _steal_success_prob(
                speed=runner.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                catcher_arm=catcher_arm,
                catcher_fielding=catcher_fielding,
                tuning=tuning,
            )
            success *= tuning.get("steal_home_success_scale", 0.6)
            if random.random() < success:
                bases.third = None
                runs_scored += 1
                scored.append(runner)
                events.append((runner, "sbh"))
            else:
                bases.third = None
                outs_added += 1
                events.append((runner, "csh"))
            return events, outs_added, runs_scored, scored

    if bases.first and bases.second and not bases.third:
        double_rate = tuning.get("double_steal_rate", 0.003)
        double_rate *= tuning.get("steal_freq_scale", 1.0)
        double_rate *= context_mult
        if random.random() < double_rate:
            runner_second = bases.second
            success = _steal_success_prob(
                speed=runner_second.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                catcher_arm=catcher_arm,
                catcher_fielding=catcher_fielding,
                tuning=tuning,
            )
            if random.random() < success:
                bases.third = runner_second
                bases.second = None
                events.append((runner_second, "sb3"))
            else:
                bases.second = None
                outs_added += 1
                events.append((runner_second, "cs3"))
            runner_first = bases.first
            success = _steal_success_prob(
                speed=runner_first.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                catcher_arm=catcher_arm,
                catcher_fielding=catcher_fielding,
                tuning=tuning,
            )
            if random.random() < success:
                bases.second = runner_first
                bases.first = None
                events.append((runner_first, "sb2"))
            else:
                bases.first = None
                outs_added += 1
                events.append((runner_first, "cs2"))
            return events, outs_added, runs_scored, scored

    if bases.second and not bases.third:
        runner = bases.second
        rate = _steal_attempt_rate(
            speed=runner.speed,
            base_rate=tuning.get("steal_attempt_rate_second", 0.006),
            pitcher_hold=pitcher_hold,
            pitcher_arm=pitcher_arm,
            catcher_arm=catcher_arm,
            catcher_fielding=catcher_fielding,
            tuning=tuning,
        )
        rate *= context_mult
        if random.random() < rate:
            success = _steal_success_prob(
                speed=runner.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                catcher_arm=catcher_arm,
                catcher_fielding=catcher_fielding,
                tuning=tuning,
            )
            if random.random() < success:
                bases.third = runner
                bases.second = None
                events.append((runner, "sb3"))
                return events, outs_added, runs_scored, scored
            bases.second = None
            outs_added += 1
            events.append((runner, "cs3"))
            return events, outs_added, runs_scored, scored

    if bases.first and not bases.second:
        runner = bases.first
        rate = _steal_attempt_rate(
            speed=runner.speed,
            base_rate=tuning.get("steal_attempt_rate_first", 0.012),
            pitcher_hold=pitcher_hold,
            pitcher_arm=pitcher_arm,
            catcher_arm=catcher_arm,
            catcher_fielding=catcher_fielding,
            tuning=tuning,
        )
        rate *= context_mult
        if random.random() < rate:
            success = _steal_success_prob(
                speed=runner.speed,
                pitcher_hold=pitcher_hold,
                pitcher_arm=pitcher_arm,
                catcher_arm=catcher_arm,
                catcher_fielding=catcher_fielding,
                tuning=tuning,
            )
            if random.random() < success:
                bases.second = runner
                bases.first = None
                events.append((runner, "sb2"))
                return events, outs_added, runs_scored, scored
            bases.first = None
            outs_added += 1
            events.append((runner, "cs2"))
            return events, outs_added, runs_scored, scored
    return events, outs_added, runs_scored, scored


def _advance_on_missed_pitch(
    *,
    bases: BaseState,
    catcher_arm: float,
    tuning: TuningConfig,
) -> tuple[int, list[BatterRatings]]:
    runs = 0
    scored: list[BatterRatings] = []
    if bases.third:
        prob = _advance_prob(
            bases.third.speed, catcher_arm, tuning, extra=0.20
        )
        if random.random() < prob:
            runs += 1
            scored.append(bases.third)
            bases.third = None
    if bases.second and bases.third is None:
        prob = _advance_prob(
            bases.second.speed, catcher_arm, tuning, extra=0.10
        )
        if random.random() < prob:
            bases.third = bases.second
            bases.second = None
    if bases.first and bases.second is None:
        prob = _advance_prob(
            bases.first.speed, catcher_arm, tuning, extra=0.05
        )
        if random.random() < prob:
            bases.second = bases.first
            bases.first = None
    return runs, scored


def _missed_pitch_type(
    *,
    location: tuple[float, float],
    pitcher_control: float,
    catcher_fielding: float,
    zone_bottom: float,
    zone_top: float,
    tuning: TuningConfig,
    force: bool = False,
) -> str | None:
    miss_scale = tuning.get("missed_pitch_loc_scale", 0.6)
    miss = miss_distance(
        location=location, zone_bottom=zone_bottom, zone_top=zone_top, tuning=tuning
    )
    miss *= miss_scale
    wp_rate = tuning.get("wild_pitch_rate", 0.0035)
    wp_rate *= 1.0 + (50.0 - pitcher_control) / 120.0
    wp_rate *= 1.0 + miss
    pb_rate = tuning.get("passed_ball_rate", 0.0025)
    pb_rate *= 1.0 + (50.0 - catcher_fielding) / 100.0
    pb_rate *= 1.0 + miss
    total = wp_rate + pb_rate
    if total <= 0:
        return "wp" if force else None
    if force:
        roll = random.random() * total
        return "wp" if roll < wp_rate else "pb"
    roll = random.random()
    if roll < wp_rate:
        return "wp"
    if roll < wp_rate + pb_rate:
        return "pb"
    return None


def _resolve_dropped_third_strike(
    *,
    bases: BaseState,
    outs: int,
    batter: BatterRatings,
    pitcher_control: float,
    catcher_fielding: float,
    catcher_arm: float,
    tuning: TuningConfig,
    location: tuple[float, float],
    zone_bottom: float,
    zone_top: float,
) -> tuple[bool, int, int, str | None, list[BatterRatings]]:
    k_rate = tuning.get("k_in_dirt_rate", 0.02)
    miss = miss_distance(
        location=location, zone_bottom=zone_bottom, zone_top=zone_top, tuning=tuning
    )
    miss *= tuning.get("missed_pitch_loc_scale", 0.6)
    k_rate *= 1.0 + miss
    k_rate *= 1.0 + (50.0 - pitcher_control) / 150.0
    k_rate *= 1.0 + (50.0 - catcher_fielding) / 140.0
    if random.random() >= k_rate:
        return False, 1, 0, None, []

    miss_event = _missed_pitch_type(
        location=location,
        pitcher_control=pitcher_control,
        catcher_fielding=catcher_fielding,
        zone_bottom=zone_bottom,
        zone_top=zone_top,
        tuning=tuning,
        force=True,
    )
    runs_scored, scored = _advance_on_missed_pitch(
        bases=bases, catcher_arm=catcher_arm, tuning=tuning
    )
    eligible = bases.first is None or outs >= 2
    outs_added = 1
    reached = False
    if eligible:
        walk_runs, walk_scored = _advance_on_walk(bases, batter)
        runs_scored += walk_runs
        scored.extend(walk_scored)
        outs_added = 0
        reached = True
    return reached, outs_added, runs_scored, miss_event, scored


def _resolve_ground_out(
    *,
    bases: BaseState,
    outs: int,
    batter: BatterRatings,
    defense_map: Dict[str, BatterRatings],
    defense_ratings: DefenseRatings,
    spray_angle: float | None,
    batter_side: str,
    tuning: TuningConfig,
) -> tuple[int, int, list[str], list[BatterRatings]]:
    runs = 0
    outs_added = 1
    events: list[str] = []
    scored: list[BatterRatings] = []
    infield_range = defense_ratings.infield
    turn_arm = defense_ratings.arm

    primary_pos = _fielder_position_for_ball(
        ball_type="gb",
        spray_angle=spray_angle,
        batter_side=batter_side,
        tuning=tuning,
        infield_play=True,
    )
    primary_pos, primary_fielder = _find_fielder(
        defense_map,
        primary_pos,
        fallback_positions=["SS", "2B", "3B", "1B"],
    )
    pivot_pos = "2B" if primary_pos in {"SS", "3B"} else "SS"
    _, pivot_fielder = _find_fielder(
        defense_map, pivot_pos, fallback_positions=["2B", "SS"]
    )
    _, oneb_fielder = _find_fielder(defense_map, "1B", fallback_positions=["P"])
    range_scale = tuning.get("range_scale", 1.0)

    range_values = []
    if primary_fielder is not None and primary_pos is not None:
        range_values.append(
            adjusted_fielding_rating(primary_fielder, primary_pos, tuning)
            * range_scale
        )
    if pivot_fielder is not None:
        range_values.append(
            adjusted_fielding_rating(pivot_fielder, pivot_pos, tuning) * range_scale
        )
    if range_values:
        infield_range = sum(range_values) / len(range_values)

    arm_values = []
    if primary_fielder is not None:
        arm_values.append(adjusted_arm_rating(primary_fielder, tuning))
    if pivot_fielder is not None:
        arm_values.append(adjusted_arm_rating(pivot_fielder, tuning))
    if oneb_fielder is not None:
        arm_values.append(adjusted_arm_rating(oneb_fielder, tuning))
    if arm_values:
        turn_arm = sum(arm_values) / len(arm_values)
    if bases.first and bases.second and outs < 2:
        tp_prob = tuning.get("triple_play_base", 0.0008)
        tp_prob += (infield_range - 50.0) / 900.0
        tp_prob -= (bases.first.speed - 50.0) / 800.0
        tp_prob -= (bases.second.speed - 50.0) / 800.0
        tp_prob = max(0.0, min(0.02, tp_prob))
        if random.random() < tp_prob:
            outs_added = 3
            bases.first = None
            bases.second = None
            events.append("tp")
            return runs, outs_added, events, scored
    if bases.third and outs < 2:
        prob = tuning.get("ground_rbi_prob", 0.12)
        prob += (bases.third.speed - 50.0) / 400.0
        if random.random() < prob:
            runs += 1
            scored.append(bases.third)
            bases.third = None
    if bases.first and outs < 2:
        dp_prob = double_play_probability(
            runner_speed=bases.first.speed,
            infield_range=infield_range,
            turn_arm=turn_arm,
            tuning=tuning,
        )
        if random.random() < dp_prob:
            outs_added = 2
            bases.first = None
            events.append("dp")
            return runs, outs_added, events, scored
        force_prob = tuning.get("fielder_choice_force_prob", 0.55)
        force_prob += (infield_range - 50.0) / 200.0
        force_prob += (turn_arm - 50.0) / 320.0
        force_prob -= (bases.first.speed - 50.0) / 220.0
        if random.random() < force_prob:
            bases.first = batter
            events.append("fc")
        else:
            prob = _advance_prob(
                bases.first.speed, turn_arm, tuning, extra=0.05
            )
            if random.random() < prob:
                bases.second = bases.first
                bases.first = None
    return runs, outs_added, events, scored


def _lineup_index(lineup: List[BatterRatings], player_id: str) -> int | None:
    for idx, player in enumerate(lineup):
        if player.player_id == player_id:
            return idx
    return None


# Share of league PA that come against LHP is ~26%; the vs-RHP counter-shift is
# scaled by 0.26/0.74 ≈ 0.35 so a batter's season-weighted platoon effect from
# vs_left is ~neutral: 0.74*(-0.35*d) + 0.26*(d) ≈ 0.
PLATOON_RHP_COUNTER_SCALE = 0.35


def _platoon_vl_delta(batter: BatterRatings, pitcher_hand: str) -> float:
    """Signed vs-hand rating delta derived from the single vs_left rating."""
    d = batter.vs_left - 50.0
    if (pitcher_hand or "R").upper() == "L":
        return d
    return -PLATOON_RHP_COUNTER_SCALE * d


def _platoon_bonus(batter: BatterRatings, pitcher: PitcherRatings) -> float:
    hand = (pitcher.throws or "R").upper()
    bats = (batter.bats or "R").upper()
    if bats == "S":
        h = 0.5  # mirrors handedness_switch_bonus default
    elif bats == hand:
        h = -1.0
    else:
        h = 1.0
    return 2.0 * h + 0.2275 * _platoon_vl_delta(batter, hand)


def _batter_offense_score(batter: BatterRatings, pitcher: PitcherRatings) -> float:
    return batter.contact * 0.55 + batter.power * 0.45 + _platoon_bonus(batter, pitcher)


def _available_bench(lineup_state: LineupState) -> List[BatterRatings]:
    return [b for b in lineup_state.bench if b.player_id not in lineup_state.bench_used]


def _upcoming_batters(
    lineup_state: LineupState, batter_index: int, count: int = 3
) -> List[BatterRatings]:
    lineup = lineup_state.lineup
    if not lineup:
        return []
    return [lineup[(batter_index + i) % len(lineup)] for i in range(count)]


def _defense_rating_for_pos(
    player: BatterRatings, position: str, tuning: TuningConfig
) -> float:
    rating = player.fielding
    if position == player.primary_position:
        rating *= tuning.get("defense_primary_pos_scale", 1.0)
    elif position in player.other_positions:
        rating *= tuning.get("defense_secondary_pos_scale", 0.9)
    else:
        rating *= tuning.get("defense_out_of_pos_scale", 0.75)
    return rating


def _select_defensive_replacement(
    *,
    lineup_state: LineupState,
    tuning: TuningConfig,
) -> tuple[str, BatterRatings, BatterRatings] | None:
    if not lineup_state.positions:
        return None
    current_by_id = {b.player_id: b for b in lineup_state.lineup}
    positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    min_diff = tuning.get("defensive_sub_fielding_diff", 8.0)
    best: tuple[str, BatterRatings, BatterRatings] | None = None
    best_gain = min_diff
    candidates = _available_bench(lineup_state)
    if not candidates:
        return None
    for pos in positions:
        current_id = None
        for pid, player_pos in lineup_state.positions.items():
            if player_pos == pos:
                current_id = pid
                break
        if current_id is None:
            continue
        current_player = current_by_id.get(current_id)
        if current_player is None:
            continue
        current_rating = _defense_rating_for_pos(current_player, pos, tuning)
        for candidate in candidates:
            if pos != candidate.primary_position and pos not in candidate.other_positions:
                continue
            cand_rating = _defense_rating_for_pos(candidate, pos, tuning)
            gain = cand_rating - current_rating
            if gain >= best_gain:
                best_gain = gain
                best = (pos, current_player, candidate)
    return best


def _maybe_defensive_sub(
    *,
    lineup_state: LineupState,
    inning: int,
    score_diff: int,
    defense_team: str,
    pitcher_id: str,
    tuning: TuningConfig,
) -> None:
    if inning < int(tuning.get("defensive_sub_inning", 7.0)):
        return
    close_diff = tuning.get("defensive_sub_close_run_diff", 2.0)
    if abs(score_diff) > close_diff:
        return
    if score_diff < 0:
        return
    choice = _select_defensive_replacement(
        lineup_state=lineup_state,
        tuning=tuning,
    )
    if choice is None:
        return
    _position, old_player, new_player = choice
    _apply_substitution(
        lineup_state=lineup_state,
        old_player=old_player,
        new_player=new_player,
        role="DEF",
        inning=inning,
        batting_team=defense_team,
        pitcher_id=pitcher_id,
    )


def _apply_substitution(
    *,
    lineup_state: LineupState,
    old_player: BatterRatings,
    new_player: BatterRatings,
    role: str,
    inning: int,
    batting_team: str,
    pitcher_id: str,
) -> bool:
    slot = _lineup_index(lineup_state.lineup, old_player.player_id)
    if slot is None:
        return False
    lineup_state.lineup[slot] = new_player
    pos = lineup_state.positions.pop(old_player.player_id, None)
    if pos:
        lineup_state.positions[new_player.player_id] = pos
        if pos.upper() != "DH":
            _fielding_line(lineup_state, new_player.player_id)
    new_line = _batter_line(lineup_state, new_player)
    new_line.g = max(1, new_line.g)
    lineup_state.bench_used.add(new_player.player_id)
    lineup_state.bench = [
        b for b in lineup_state.bench if b.player_id != new_player.player_id
    ]
    lineup_state.substitutions.append(
        {
            "team": batting_team,
            "inning": inning,
            "role": role,
            "out": old_player.player_id,
            "in": new_player.player_id,
            "position": pos or "",
            "pitcher_id": pitcher_id,
        }
    )
    return True


def _select_pinch_hitter(
    *,
    lineup_state: LineupState,
    batter: BatterRatings,
    pitcher: PitcherRatings,
    inning: int,
    outs: int,
    score_diff: int,
    bases: BaseState,
    tuning: TuningConfig,
) -> BatterRatings | None:
    if inning < int(tuning.get("pinch_hit_inning", 7.0)):
        return None
    close_diff = tuning.get("pinch_hit_close_run_diff", 2.0)
    if score_diff > close_diff:
        return None
    if outs >= 2 and bases.first is None and bases.second is None and bases.third is None:
        return None
    candidates = _available_bench(lineup_state)
    if not candidates:
        return None
    current_score = _batter_offense_score(batter, pitcher)
    best = max(candidates, key=lambda b: _batter_offense_score(b, pitcher))
    best_score = _batter_offense_score(best, pitcher)
    if best_score - current_score < tuning.get("pinch_hit_advantage_min", 6.0):
        return None
    return best


def _select_pinch_runner(
    *,
    lineup_state: LineupState,
    runner: BatterRatings,
    inning: int,
    score_diff: int,
    tuning: TuningConfig,
) -> BatterRatings | None:
    if inning < int(tuning.get("pinch_run_inning", 7.0)):
        return None
    close_diff = tuning.get("pinch_run_close_run_diff", 2.0)
    if score_diff > close_diff:
        return None
    if runner.speed >= tuning.get("pinch_run_speed_min", 55.0):
        return None
    candidates = _available_bench(lineup_state)
    if not candidates:
        return None
    min_diff = tuning.get("pinch_run_speed_diff", 8.0)
    faster = [b for b in candidates if b.speed >= runner.speed + min_diff]
    if not faster:
        return None
    return max(faster, key=lambda b: b.speed)


def _maybe_pinch_run(
    *,
    lineup_state: LineupState,
    bases: BaseState,
    unearned_runners: set[str] | None,
    runner_pitchers: dict[str, PitcherLine] | None,
    inning: int,
    score_diff: int,
    batting_team: str,
    pitcher_id: str,
    tuning: TuningConfig,
) -> str | None:
    base_codes = {"third": "pr3", "second": "pr2", "first": "pr1"}
    for base_attr in ("third", "second", "first"):
        runner = getattr(bases, base_attr)
        if runner is None:
            continue
        replacement = _select_pinch_runner(
            lineup_state=lineup_state,
            runner=runner,
            inning=inning,
            score_diff=score_diff,
            tuning=tuning,
        )
        if replacement is None:
            continue
        if _apply_substitution(
            lineup_state=lineup_state,
            old_player=runner,
            new_player=replacement,
            role="PR",
            inning=inning,
            batting_team=batting_team,
            pitcher_id=pitcher_id,
        ):
            setattr(bases, base_attr, replacement)
            if unearned_runners is not None and runner.player_id in unearned_runners:
                unearned_runners.discard(runner.player_id)
                unearned_runners.add(replacement.player_id)
            if runner_pitchers is not None:
                pitcher_line = runner_pitchers.pop(runner.player_id, None)
                if pitcher_line is not None:
                    runner_pitchers[replacement.player_id] = pitcher_line
            return base_codes[base_attr]
    return None


def _advance_on_balk(bases: BaseState) -> tuple[int, list[BatterRatings]]:
    runs = 0
    scored: list[BatterRatings] = []
    if bases.third:
        runs += 1
        scored.append(bases.third)
        bases.third = None
    if bases.second:
        bases.third = bases.second
        bases.second = None
    if bases.first:
        bases.second = bases.first
        bases.first = None
    return runs, scored


def _should_intentional_walk(
    *,
    bases: BaseState,
    batter: BatterRatings,
    pitcher: PitcherRatings,
    inning: int,
    outs: int,
    score_diff: int,
    tuning: TuningConfig,
) -> bool:
    if bases.first is not None:
        return False
    if bases.second is None and bases.third is None:
        return False
    if outs >= 2 and bases.third is None:
        return False
    if inning < int(tuning.get("ibb_inning", 7.0)):
        return False
    close_diff = tuning.get("ibb_close_run_diff", 2.0)
    if abs(score_diff) > close_diff:
        return False
    threat = _batter_offense_score(batter, pitcher)
    if threat < tuning.get("ibb_batter_threshold", 65.0):
        return False
    return random.random() < tuning.get("ibb_chance", 0.35)


def _should_bunt(
    *,
    bases: BaseState,
    batter: BatterRatings,
    inning: int,
    outs: int,
    score_diff: int,
    tuning: TuningConfig,
) -> bool:
    if outs >= 2:
        return False
    if bases.first is None and bases.second is None and bases.third is None:
        return False
    if inning > int(tuning.get("bunt_inning_max", 8.0)):
        return False
    close_diff = tuning.get("bunt_close_run_diff", 2.0)
    if abs(score_diff) > close_diff:
        return False
    rate = tuning.get("bunt_attempt_rate", 0.03)
    if bases.first and bases.second:
        rate *= 0.7
    if bases.third:
        rate *= 1.2
    if batter.power >= 60.0:
        rate *= 0.6
    if batter.speed >= 60.0:
        rate *= 1.2
    return random.random() < max(0.0, min(0.5, rate))


def _resolve_bunt(
    *,
    bases: BaseState,
    batter: BatterRatings,
    outs: int,
    defense: DefenseRatings,
    tuning: TuningConfig,
) -> tuple[int, int, bool, bool, list[str], list[BatterRatings], list[BatterRatings]]:
    runs = 0
    outs_added = 0
    events: list[str] = []
    scored: list[BatterRatings] = []
    error_advances: list[BatterRatings] = []

    hit_prob = tuning.get("bunt_hit_base", 0.03)
    hit_prob += (batter.speed - 50.0) / 250.0
    hit_prob += (batter.contact - 50.0) / 300.0
    hit_prob -= (defense.infield - 50.0) / 400.0
    hit_prob = max(0.0, min(0.2, hit_prob))
    if random.random() < hit_prob:
        events.append("bunt_hit")
        (
            runs_scored,
            outs_added_hit,
            extra_events,
            scored,
            error_advances,
        ) = _advance_on_hit(
            bases=bases,
            batter=batter,
            hit_type="single",
            defense_arm=defense.arm,
            tuning=tuning,
        )
        runs += runs_scored
        outs_added += outs_added_hit
        events.extend(extra_events)
        return runs, outs_added, True, False, events, scored, error_advances

    success_prob = tuning.get("bunt_success_base", 0.68)
    success_prob += (batter.contact - 50.0) / 200.0
    success_prob -= (defense.infield - 50.0) / 260.0
    success_prob = max(0.25, min(0.95, success_prob))
    if outs < 2 and random.random() < success_prob:
        outs_added = 1
        events.append("sac")
        if bases.third:
            squeeze_rate = tuning.get("bunt_squeeze_rate", 0.15)
            if random.random() < squeeze_rate:
                runs += 1
                scored.append(bases.third)
                bases.third = None
        if bases.second and bases.third is None:
            bases.third = bases.second
            bases.second = None
        if bases.first and bases.second is None:
            bases.second = bases.first
            bases.first = None
        return runs, outs_added, False, True, events, scored, error_advances

    outs_added = 1
    events.append("bunt_out")
    if bases.first and outs < 2:
        dp_prob = tuning.get("bunt_double_play_base", 0.08)
        dp_prob += (defense.infield - 50.0) / 300.0
        dp_prob -= (bases.first.speed - 50.0) / 350.0
        dp_prob = max(0.01, min(0.35, dp_prob))
        if random.random() < dp_prob:
            outs_added = 2
            bases.first = None
            events.append("dp")
    return runs, outs_added, False, False, events, scored, error_advances


def _select_injury_replacement(
    *,
    lineup_state: LineupState,
    injured_player: BatterRatings,
    tuning: TuningConfig,
) -> BatterRatings | None:
    candidates = _available_bench(lineup_state)
    if not candidates:
        return None
    pos = lineup_state.positions.get(injured_player.player_id)
    if pos:
        eligible = [
            b
            for b in candidates
            if b.primary_position == pos or pos in b.other_positions
        ]
        if eligible:
            return max(
                eligible,
                key=lambda b: _defense_rating_for_pos(b, pos, tuning),
            )
    return max(candidates, key=lambda b: b.fielding)


def _maybe_injure_player(
    *,
    injury_sim: InjurySimulator | None,
    injured_players: set[str],
    injury_events: list[dict[str, Any]],
    player: BatterRatings,
    trigger: str,
    context: dict[str, float] | None,
    inning: int,
    outs: int,
    team: str,
    pitcher_id: str,
    tuning: TuningConfig,
    lineup_state: LineupState | None = None,
    bases: BaseState | None = None,
    base_attr: str | None = None,
    unearned_runners: set[str] | None = None,
    runner_pitchers: dict[str, PitcherLine] | None = None,
) -> dict[str, Any] | None:
    if injury_sim is None:
        return None
    if player.player_id in injured_players:
        return None
    rate_scale = tuning.get("injury_rate_scale", 0.1)
    if rate_scale <= 0.0 or random.random() >= rate_scale:
        return None
    outcome = injury_sim.maybe_create_injury(trigger, player, context=context)
    if outcome is None:
        return None
    injured_players.add(player.player_id)
    event = {
        "team": team,
        "player_id": player.player_id,
        "trigger": trigger,
        "inning": inning,
        "outs": outs,
        "severity": outcome.severity,
        "days": outcome.days,
        "dl_tier": outcome.dl_tier,
        "description": outcome.description,
        "pitcher_id": pitcher_id,
    }
    if lineup_state is not None:
        replacement = _select_injury_replacement(
            lineup_state=lineup_state,
            injured_player=player,
            tuning=tuning,
        )
        if replacement is not None and _apply_substitution(
            lineup_state=lineup_state,
            old_player=player,
            new_player=replacement,
            role="INJ",
            inning=inning,
            batting_team=team,
            pitcher_id=pitcher_id,
        ):
            event["replacement_id"] = replacement.player_id
            if bases is not None and base_attr:
                current = getattr(bases, base_attr)
                if current is not None and current.player_id == player.player_id:
                    setattr(bases, base_attr, replacement)
                    if (
                        unearned_runners is not None
                        and player.player_id in unearned_runners
                    ):
                        unearned_runners.discard(player.player_id)
                        unearned_runners.add(replacement.player_id)
                    if runner_pitchers is not None:
                        pitcher_line = runner_pitchers.pop(player.player_id, None)
                        if pitcher_line is not None:
                            runner_pitchers[replacement.player_id] = pitcher_line
    injury_events.append(event)
    return event


def _batter_fatigue_penalty(
    batter: BatterRatings,
    *,
    usage_state: UsageState | None,
    game_day: int | None,
    tuning: TuningConfig,
) -> float:
    if usage_state is None or game_day is None:
        return 0.0
    workload = usage_state.batter_workload_for(batter.player_id)
    threshold = tuning.get("batter_fatigue_threshold_base", 35.0)
    threshold += batter.durability * tuning.get("batter_fatigue_threshold_scale", 0.45)
    if threshold <= 0.0:
        return 0.0
    over = max(0.0, workload.fatigue_debt - threshold)
    ratio = over / threshold
    penalty = ratio * tuning.get("batter_fatigue_penalty_scale", 0.5)
    cap = tuning.get("batter_fatigue_penalty_cap", 0.35)
    return max(0.0, min(cap, penalty))


def _apply_batter_fatigue(
    batters: List[BatterRatings],
    *,
    usage_state: UsageState | None,
    game_day: int | None,
    tuning: TuningConfig,
) -> List[BatterRatings]:
    if usage_state is None or game_day is None:
        return list(batters)

    adjusted: List[BatterRatings] = []
    for batter in batters:
        penalty = _batter_fatigue_penalty(
            batter, usage_state=usage_state, game_day=game_day, tuning=tuning
        )
        if penalty <= 0.0:
            adjusted.append(batter)
            continue
        offense_scale = 1.0 - penalty * tuning.get("batter_fatigue_offense_scale", 0.8)
        eye_scale = 1.0 - penalty * tuning.get("batter_fatigue_eye_scale", 0.7)
        speed_scale = 1.0 - penalty * tuning.get("batter_fatigue_speed_scale", 0.5)
        defense_scale = 1.0 - penalty * tuning.get("batter_fatigue_defense_scale", 0.4)

        def clamp(value: float) -> float:
            return max(1.0, min(100.0, value))

        updated = replace(
            batter,
            contact=clamp(batter.contact * offense_scale),
            power=clamp(batter.power * offense_scale),
            eye=clamp(batter.eye * eye_scale),
            speed=clamp(batter.speed * speed_scale),
            fielding=clamp(batter.fielding * defense_scale),
            arm=clamp(batter.arm * defense_scale),
        )
        setattr(updated, "fatigue_penalty", penalty)
        adjusted.append(updated)
    return adjusted


def _maybe_pitcher_overuse_injury(
    *,
    injury_sim: InjurySimulator | None,
    injured_players: set[str],
    injury_events: list[dict[str, Any]],
    pitching_state: TeamPitchingState,
    lineup_state: LineupState,
    bases: BaseState,
    inning: int,
    outs: int,
    score_diff: int,
    defense_score: int,
    offense_score: int,
    upcoming_batters: List[BatterRatings],
    team: str,
    tuning: TuningConfig,
    postseason: bool,
) -> bool:
    if injury_sim is None:
        return False
    pitcher_state = pitching_state.current
    pitcher = pitcher_state.pitcher
    if pitcher.player_id in injured_players:
        return False
    min_pitches = tuning.get("injury_overuse_pitch_min", 80.0)
    if pitcher_state.pitches < min_pitches:
        return False
    threshold = tuning.get("injury_overuse_penalty_threshold", 0.6)
    if pitcher_state.last_penalty < threshold:
        return False
    rate_scale = tuning.get("injury_rate_scale", 0.1)
    if rate_scale <= 0.0 or random.random() >= rate_scale:
        return False
    outcome = injury_sim.maybe_create_injury(
        "pitcher_overuse",
        pitcher,
        context={"fatigue": min(1.5, pitcher_state.last_penalty)},
    )
    if outcome is None:
        return False
    injured_players.add(pitcher.player_id)
    event = {
        "team": team,
        "player_id": pitcher.player_id,
        "trigger": "pitcher_overuse",
        "inning": inning,
        "outs": outs,
        "severity": outcome.severity,
        "days": outcome.days,
        "dl_tier": outcome.dl_tier,
        "description": outcome.description,
        "pitcher_id": pitcher.player_id,
        "pitch_count": pitcher_state.pitches,
    }
    pitcher_state.available = False
    leverage = _leverage_type(inning, score_diff, tuning)
    next_pitcher = _select_reliever(
        pitching_state,
        leverage,
        inning=inning,
        score_diff=score_diff,
        is_home_defense=(team == "home"),
        upcoming_batters=upcoming_batters,
        tuning=tuning,
    )
    if next_pitcher is not pitcher_state:
        line = _line_for_pitcher(pitching_state, pitcher_state, inning)
        _pitcher_exit_stats(
            pitcher_state=pitcher_state,
            line=line,
            defense_score=defense_score,
            offense_score=offense_score,
            game_finished=False,
        )
        _pitcher_enter_stats(
            pitching_state=pitching_state,
            pitcher_state=next_pitcher,
            lineup_state=lineup_state,
            inning=inning,
            score_diff=score_diff,
            defense_score=defense_score,
            offense_score=offense_score,
            bases=bases,
            postseason=postseason,
            tuning=tuning,
        )
        event["replacement_id"] = next_pitcher.pitcher.player_id
    injury_events.append(event)
    return True


def _handedness_advantage(batter_hand: str, pitcher_hand: str, tuning: TuningConfig) -> float:
    if batter_hand == "S":
        return tuning.get("handedness_switch_bonus", 0.5)
    if batter_hand == pitcher_hand:
        return -1.0
    return 1.0


def _batter_context(
    batter: BatterRatings, pitcher: PitcherRatings, tuning: TuningConfig
) -> Dict[str, Any]:
    pitcher_hand = (pitcher.throws or "R").upper()
    batter_hand = (batter.bats or "R").upper()
    eye = batter.eye * 0.8 + (100.0 - pitcher.control) * 0.2
    contact = batter.contact
    power = batter.power
    handedness = _handedness_advantage(batter_hand, pitcher_hand, tuning)
    contact += handedness * tuning.get("handedness_contact_bonus", 2.0)
    power += handedness * tuning.get("handedness_power_bonus", 2.0)
    eye += handedness * tuning.get("handedness_eye_bonus", 2.0)
    platoon_chase = 0.0
    vs_left_diff = _platoon_vl_delta(batter, pitcher_hand)
    contact += vs_left_diff * tuning.get("platoon_contact_scale", 0.25)
    power += vs_left_diff * tuning.get("platoon_power_scale", 0.2)
    eye += vs_left_diff * tuning.get("platoon_eye_scale", 0.3)
    platoon_chase -= vs_left_diff * tuning.get("platoon_chase_scale", 0.0015)
    contact = max(1.0, min(100.0, contact))
    power = max(1.0, min(100.0, power))
    eye = max(1.0, min(100.0, eye))
    batter_side = _effective_batter_side(batter_hand, pitcher_hand)
    return {
        "contact": contact,
        "power": power,
        "gb_tendency": batter.gb_tendency,
        "pull_tendency": batter.pull_tendency,
        "eye": eye,
        "bats": batter_hand,
        "batter_side": batter_side,
        "platoon_chase": platoon_chase,
        "height": batter.height,
        "zone_bottom": batter.zone_bottom,
        "zone_top": batter.zone_top,
    }


def _lineup_hand_from_starter(starter: PitcherRatings | None) -> str:
    if starter is None:
        return "R"
    hand = (starter.throws or "R").upper()
    return "L" if hand == "L" else "R"


def _resolve_data_root(base_dir: Path | None) -> Path:
    if base_dir is None:
        return get_data_dir()
    base = Path(base_dir)
    if (base / "rosters").exists() and not (base / "data").exists():
        return base
    return base / "data"


def simulate_matchup_from_files(
    *,
    away_team: str,
    home_team: str,
    players_path: Path | None = None,
    base_dir: Path | None = None,
    away_lineup_hand: str | None = None,
    home_lineup_hand: str | None = None,
    park_name: str | None = None,
    seed: int | None = None,
    tuning_overrides: Dict[str, Any] | None = None,
    usage_state: UsageState | None = None,
    game_day: int | None = None,
    postseason: bool = False,
) -> GameResult:
    """Load lineups/pitching staffs from CSVs and simulate a matchup."""

    data_root = _resolve_data_root(base_dir)
    players_csv = Path(players_path) if players_path is not None else data_root / "players.csv"
    batters_by_id, pitchers_by_id = load_players_by_id(players_csv)

    away_statuses = load_roster_status(away_team, base_dir=data_root)
    home_statuses = load_roster_status(home_team, base_dir=data_root)
    away_active = active_roster_ids(away_statuses) if away_statuses else None
    home_active = active_roster_ids(home_statuses) if home_statuses else None

    away_assignments = load_pitching_staff(away_team, base_dir=data_root)
    home_assignments = load_pitching_staff(home_team, base_dir=data_root)
    away_pitchers, away_roles, missing_away_pitchers = build_staff(
        away_assignments,
        pitchers_by_id,
        active_ids=away_active,
        game_day=game_day,
    )
    home_pitchers, home_roles, missing_home_pitchers = build_staff(
        home_assignments,
        pitchers_by_id,
        active_ids=home_active,
        game_day=game_day,
    )
    if not away_pitchers:
        fallback = sorted(
            pitchers_by_id.values(),
            key=lambda p: getattr(p, "endurance", 0),
            reverse=True,
        )
        away_pitchers = fallback[:10]
    if not home_pitchers:
        fallback = sorted(
            pitchers_by_id.values(),
            key=lambda p: getattr(p, "endurance", 0),
            reverse=True,
        )
        home_pitchers = fallback[:10]
    away_starter = away_pitchers[0] if away_pitchers else None
    home_starter = home_pitchers[0] if home_pitchers else None

    if away_lineup_hand is None:
        away_lineup_hand = _lineup_hand_from_starter(home_starter)
    if home_lineup_hand is None:
        home_lineup_hand = _lineup_hand_from_starter(away_starter)

    away_lineup_slots = load_lineup(away_team, away_lineup_hand, base_dir=data_root)
    home_lineup_slots = load_lineup(home_team, home_lineup_hand, base_dir=data_root)
    away_lineup, away_positions, missing_away_batters = resolve_lineup(
        away_lineup_slots, batters_by_id
    )
    home_lineup, home_positions, missing_home_batters = resolve_lineup(
        home_lineup_slots, batters_by_id
    )
    if missing_away_batters or len(away_lineup) < 9:
        auto_fill_lineup_for_team(
            _normalize_team_id(away_team),
            players_file=str(players_csv),
            roster_dir=str(data_root / "rosters"),
            lineup_dir=str(data_root / "lineups"),
        )
        away_lineup_slots = load_lineup(away_team, away_lineup_hand, base_dir=data_root)
        away_lineup, away_positions, missing_away_batters = resolve_lineup(
            away_lineup_slots, batters_by_id
        )
    if missing_home_batters or len(home_lineup) < 9:
        auto_fill_lineup_for_team(
            _normalize_team_id(home_team),
            players_file=str(players_csv),
            roster_dir=str(data_root / "rosters"),
            lineup_dir=str(data_root / "lineups"),
        )
        home_lineup_slots = load_lineup(home_team, home_lineup_hand, base_dir=data_root)
        home_lineup, home_positions, missing_home_batters = resolve_lineup(
            home_lineup_slots, batters_by_id
        )
    away_bench = build_bench(
        team_id=away_team,
        batters_by_id=batters_by_id,
        lineup_ids=[b.player_id for b in away_lineup],
        base_dir=data_root,
    )
    home_bench = build_bench(
        team_id=home_team,
        batters_by_id=batters_by_id,
        lineup_ids=[b.player_id for b in home_lineup],
        base_dir=data_root,
    )

    result = simulate_game(
        away_lineup=away_lineup,
        home_lineup=home_lineup,
        away_lineup_positions=away_positions,
        home_lineup_positions=home_positions,
        away_bench=away_bench,
        home_bench=home_bench,
        away_pitchers=away_pitchers,
        home_pitchers=home_pitchers,
        away_pitcher_roles=away_roles,
        home_pitcher_roles=home_roles,
        park_name=park_name,
        seed=seed,
        tuning_overrides=tuning_overrides,
        usage_state=usage_state,
        game_day=game_day,
        postseason=postseason,
    )
    result.metadata["lineup_hand"] = {
        "away": away_lineup_hand,
        "home": home_lineup_hand,
    }
    result.metadata["missing_players"] = {
        "away_batters": missing_away_batters,
        "home_batters": missing_home_batters,
        "away_pitchers": missing_away_pitchers,
        "home_pitchers": missing_home_pitchers,
    }
    result.metadata["teams"] = {"away": away_team, "home": home_team}
    return result


def simulate_game(
    *,
    batters: List[BatterRatings] | None = None,
    pitchers: List[PitcherRatings] | None = None,
    away_lineup: List[BatterRatings] | None = None,
    home_lineup: List[BatterRatings] | None = None,
    away_lineup_positions: Dict[str, str] | None = None,
    home_lineup_positions: Dict[str, str] | None = None,
    away_bench: List[BatterRatings] | None = None,
    home_bench: List[BatterRatings] | None = None,
    away_pitchers: List[PitcherRatings] | None = None,
    home_pitchers: List[PitcherRatings] | None = None,
    away_pitcher_roles: Dict[str, str] | None = None,
    home_pitcher_roles: Dict[str, str] | None = None,
    park_name: str | None = None,
    seed: int | None = None,
    tuning_overrides: Dict[str, Any] | None = None,
    usage_state: UsageState | None = None,
    game_day: int | None = None,
    postseason: bool = False,
) -> GameResult:
    """Very early stub of the physics-based game simulation.

    This will be expanded to handle full rosters, substitutions, defense, and
    realistic fatigue/usage. It currently supports a starter + bullpen and
    optional multi-game usage tracking.
    """

    rng = random.Random(seed)
    random.seed(seed)
    tuning: TuningConfig = load_tuning(overrides=tuning_overrides)
    park: Park = load_park(park_name)
    injury_sim: InjurySimulator | None = None
    if tuning.get("injuries_enabled", 1.0) > 0.5:
        injury_sim = InjurySimulator(rng=rng)
    injury_events: list[dict[str, Any]] = []
    injured_players: set[str] = set()

    totals = {
        "pa": 0,
        "ab": 0,
        "h": 0,
        "b1": 0,
        "b2": 0,
        "b3": 0,
        "bb": 0,
        "k": 0,
        "so_looking": 0,
        "so_swinging": 0,
        "hbp": 0,
        "roe": 0,
        "e": 0,
        "e_field": 0,
        "e_throw": 0,
        "fc": 0,
        "gidp": 0,
        "tp": 0,
        "sf": 0,
        "sh": 0,
        "sb": 0,
        "cs": 0,
        "po": 0,
        "oob": 0,
        "ibb": 0,
        "balk": 0,
        "ci": 0,
        "wp": 0,
        "pb": 0,
        "hr": 0,
        "called_strikes": 0,
        "swinging_strikes": 0,
        "called_third_strikes": 0,
        "swinging_third_strikes": 0,
        "r": 0,
        "r_away": 0,
        "r_home": 0,
        "lob": 0,
        "lob_away": 0,
        "lob_home": 0,
        "pitches": 0,
    }
    pitch_log: List[Dict[str, Any]] = []
    score_away = 0
    score_home = 0
    inning_runs_away: List[int] = []
    inning_runs_home: List[int] = []

    # Basic lineup/defense selection for a two-team matchup.
    if away_lineup is None or home_lineup is None:
        if not batters:
            raise ValueError("Batters are required when explicit lineups are not set.")
        if len(batters) >= 18:
            away_lineup = batters[:9]
            home_lineup = batters[9:18]
        else:
            away_lineup = batters[:9] if len(batters) >= 9 else batters
            home_lineup = list(away_lineup)
    away_positions = away_lineup_positions or {}
    home_positions = home_lineup_positions or {}
    if not away_lineup or not home_lineup:
        raise ValueError("Both teams must have at least one batter in the lineup.")
    away_bench = away_bench or []
    home_bench = home_bench or []
    away_lineup_ids = {b.player_id for b in away_lineup}
    home_lineup_ids = {b.player_id for b in home_lineup}
    away_bench = [b for b in away_bench if b.player_id not in away_lineup_ids]
    home_bench = [b for b in home_bench if b.player_id not in home_lineup_ids]

    if away_pitchers is None or home_pitchers is None:
        if not pitchers:
            raise ValueError("Pitchers are required when explicit staffs are not set.")
        if len(pitchers) >= 4:
            midpoint = len(pitchers) // 2
            away_pitchers = pitchers[:midpoint]
            home_pitchers = pitchers[midpoint:]
        elif len(pitchers) >= 2:
            away_pitchers = [pitchers[0]]
            home_pitchers = [pitchers[1]]
        else:
            away_pitchers = pitchers[:1]
            home_pitchers = pitchers[:1]
    if not away_pitchers or not home_pitchers:
        raise ValueError("Both teams must have at least one pitcher.")

    if usage_state is not None and game_day is not None:
        usage_pitchers = list(away_pitchers) + list(home_pitchers)
        usage_batters = (
            list(away_lineup)
            + list(home_lineup)
            + list(away_bench)
            + list(home_bench)
        )
        usage_state.advance_day(
            day=game_day,
            pitchers=usage_pitchers,
            batters=usage_batters,
            tuning=tuning,
        )

        away_lineup = _apply_batter_fatigue(
            list(away_lineup),
            usage_state=usage_state,
            game_day=game_day,
            tuning=tuning,
        )
        home_lineup = _apply_batter_fatigue(
            list(home_lineup),
            usage_state=usage_state,
            game_day=game_day,
            tuning=tuning,
        )
        away_bench = _apply_batter_fatigue(
            list(away_bench),
            usage_state=usage_state,
            game_day=game_day,
            tuning=tuning,
        )
        home_bench = _apply_batter_fatigue(
            list(home_bench),
            usage_state=usage_state,
            game_day=game_day,
            tuning=tuning,
        )

    away_pitchers = _order_pitchers_for_game(
        list(away_pitchers),
        roles_by_id=away_pitcher_roles,
        usage_state=usage_state,
        game_day=game_day,
        tuning=tuning,
    )
    home_pitchers = _order_pitchers_for_game(
        list(home_pitchers),
        roles_by_id=home_pitcher_roles,
        usage_state=usage_state,
        game_day=game_day,
        tuning=tuning,
    )

    away_state = LineupState(
        lineup=list(away_lineup),
        positions=dict(away_positions),
        bench=list(away_bench),
    )
    home_state = LineupState(
        lineup=list(home_lineup),
        positions=dict(home_positions),
        bench=list(home_bench),
    )
    for state in (away_state, home_state):
        for batter in state.lineup:
            line = _batter_line(state, batter)
            line.g = max(1, line.g)
            line.gs = max(1, line.gs)
        for player_id, pos in state.positions.items():
            if pos and pos.upper() != "DH":
                _fielding_line(state, player_id, starting=True)

    away_staff = _build_team_pitching_state(
        away_pitchers,
        tuning=tuning,
        usage_state=usage_state,
        game_day=game_day,
        postseason=postseason,
        roles_by_id=away_pitcher_roles,
    )
    home_staff = _build_team_pitching_state(
        home_pitchers,
        tuning=tuning,
        usage_state=usage_state,
        game_day=game_day,
        postseason=postseason,
        roles_by_id=home_pitcher_roles,
    )
    _fielding_line(away_state, away_staff.starter.pitcher.player_id, starting=True)
    _fielding_line(home_state, home_staff.starter.pitcher.player_id, starting=True)
    pitcher_of_record = {
        "away": away_staff.current.pitcher.player_id,
        "home": home_staff.current.pitcher.player_id,
    }
    losing_pitcher: str | None = None
    away_index = 0
    home_index = 0
    batter_tracking: dict[str, dict[str, int]] = {}

    def play_half_inning(
        offense_state: LineupState,
        defense_state: LineupState,
        pitching_state: TeamPitchingState,
        batter_index: int,
        inning: int,
        batting_team: str,
        walkoff_allowed: bool,
    ) -> tuple[int, int]:
        outs = 0
        bases = BaseState()
        lineup = offense_state.lineup
        lineup_size = len(lineup) if lineup else 1
        half_inning_runs = 0
        runner_pitchers: dict[str, PitcherLine] = {}
        unearned_runners: set[str] = set()
        unearned_outs = 0
        if batting_team == "away":
            offense_score = score_away
            defense_score = score_home
            defense_team = "home"
        else:
            offense_score = score_home
            defense_score = score_away
            defense_team = "away"
        _maybe_defensive_sub(
            lineup_state=defense_state,
            inning=inning,
            score_diff=defense_score - offense_score,
            defense_team=defense_team,
            pitcher_id=pitching_state.current.pitcher.player_id,
            tuning=tuning,
        )
        defense_map = (
            build_defense_from_lineup(defense_state.lineup, defense_state.positions)
            if defense_state.positions
            else build_default_defense(defense_state.lineup)
        )
        defense_ratings = compute_defense_ratings(defense_map, tuning)
        catcher_fielding, catcher_arm = _catcher_context(
            defense_map, defense_ratings, tuning
        )
        walkoff = False

        if (
            tuning.get("extra_innings_runner", 0.0) > 0.5
            and inning >= int(tuning.get("extra_innings_runner_start", 10.0))
            and lineup
        ):
            ghost = lineup[(batter_index - 1) % len(lineup)]
            bases.second = ghost
            unearned_runners.add(ghost.player_id)

        if inning >= 9:
            lead = defense_score - offense_score
            save_opp = False
            if lead > 0:
                save_opp = _save_opportunity(
                    lead=lead,
                    inning=inning,
                    bases=bases,
                    tuning=tuning,
                )
            closer_inning = int(tuning.get("closer_inning_min", 9.0))
            tied_road_inning = int(tuning.get("closer_tied_road_inning_min", 10.0))
            # S2-04: bring the CL into a tied half-inning the defense may use him
            # in (home from the 9th; both sides once extras start).
            tied_entry = (
                lead == 0
                and inning >= closer_inning
                and (defense_team == "home" or inning >= tied_road_inning)
            )
            current_role = (pitching_state.current.staff_role or "").upper()
            if (save_opp or tied_entry) and current_role != "CL":
                    upcoming = [
                        lineup[(batter_index + offset) % len(lineup)]
                        for offset in range(min(3, len(lineup)))
                    ]
                    leverage = _leverage_type(inning, lead, tuning)
                    closer_candidates = [
                        pitcher
                        for pitcher in pitching_state.bullpen
                        if (pitcher.staff_role or "").upper() == "CL"
                        and not pitcher.used
                    ]
                    available_closers = [
                        pitcher for pitcher in closer_candidates if pitcher.available
                    ]
                    if available_closers:
                        next_pitcher = max(
                            available_closers,
                            key=lambda candidate: _reliever_score(
                                candidate, leverage, score_diff=lead
                            ),
                        )
                    elif closer_candidates:
                        next_pitcher = max(
                            closer_candidates,
                            key=lambda candidate: _reliever_score(
                                candidate, leverage, score_diff=lead
                            ),
                        )
                    else:
                        next_pitcher = _select_reliever(
                            pitching_state,
                            leverage,
                            inning=inning,
                            score_diff=lead,
                            is_home_defense=(defense_team == "home"),
                            upcoming_batters=upcoming,
                            tuning=tuning,
                        )
                    if next_pitcher is not pitching_state.current:
                        line = _line_for_pitcher(
                            pitching_state, pitching_state.current, inning
                        )
                        _pitcher_exit_stats(
                            pitcher_state=pitching_state.current,
                            line=line,
                            defense_score=defense_score,
                            offense_score=offense_score,
                            game_finished=False,
                        )
                        _pitcher_enter_stats(
                            pitching_state=pitching_state,
                            pitcher_state=next_pitcher,
                            lineup_state=defense_state,
                            inning=inning,
                            score_diff=lead,
                            defense_score=defense_score,
                            offense_score=offense_score,
                            bases=bases,
                            postseason=postseason,
                            tuning=tuning,
                        )

        def record_runs(
            runs_scored: int,
            line: PitcherLine,
            scored_runners: list[BatterRatings] | None = None,
            pitcher_state: PitcherState | None = None,
        ) -> None:
            nonlocal score_away, score_home, walkoff, half_inning_runs, unearned_outs
            nonlocal losing_pitcher
            if runs_scored <= 0:
                return
            prev_offense_score = (
                score_away if batting_team == "away" else score_home
            )
            prev_defense_score = (
                score_home if batting_team == "away" else score_away
            )
            totals["r"] += runs_scored
            line.inning_runs += runs_scored
            half_inning_runs += runs_scored
            if scored_runners:
                for runner in scored_runners:
                    _batter_line(offense_state, runner).r += 1
                    responsible_line = runner_pitchers.pop(
                        runner.player_id, line
                    )
                    responsible_line.runs += 1
                    unearned = (
                        runner.player_id in unearned_runners
                        or outs + unearned_outs >= 3
                    )
                    if not unearned:
                        responsible_line.earned_runs += 1
                    unearned_runners.discard(runner.player_id)
                    if responsible_line is not line:
                        line.irs += 1
            else:
                line.runs += runs_scored
                line.earned_runs += runs_scored
            if batting_team == "away":
                totals["r_away"] += runs_scored
                score_away += runs_scored
            else:
                totals["r_home"] += runs_scored
                score_home += runs_scored
            if prev_offense_score <= prev_defense_score:
                offense_score = (
                    score_away if batting_team == "away" else score_home
                )
                defense_score = (
                    score_home if batting_team == "away" else score_away
                )
                if offense_score > defense_score:
                    offense_pitching = (
                        away_staff if batting_team == "away" else home_staff
                    )
                    pitcher_of_record[batting_team] = (
                        offense_pitching.current.pitcher.player_id
                    )
                    losing_pitcher = line.pitcher_id
            pitcher_state = pitcher_state or pitching_state.current
            if pitcher_state is not None and pitcher_state.in_save_situation:
                defense_score = (
                    score_home if batting_team == "away" else score_away
                )
                offense_score = (
                    score_away if batting_team == "away" else score_home
                )
                if defense_score - offense_score <= 0:
                    line.bs += 1
                    pitcher_state.in_save_situation = False
            if walkoff_allowed and batting_team == "home" and score_home > score_away:
                walkoff = True

        def rbi_credit(
            scored_runners: list[BatterRatings],
            error_runners: list[BatterRatings],
        ) -> int:
            if not scored_runners:
                return 0
            if not error_runners:
                return len(scored_runners)
            error_ids = {runner.player_id for runner in error_runners}
            return sum(
                1 for runner in scored_runners if runner.player_id not in error_ids
            )

        def apply_advance_errors(
            *,
            error_runners: list[BatterRatings],
            ball_type: str | None,
            spray_angle: float | None,
            batter_side: str,
            infield_play: bool,
            error_on: str,
            log_entry: dict[str, Any] | None = None,
        ) -> None:
            nonlocal unearned_outs
            if not error_runners:
                return
            runner_ids: list[str] = []
            for runner in error_runners:
                totals["e"] += 1
                totals["e_throw"] += 1
                unearned_outs += 1
                unearned_runners.add(runner.player_id)
                runner_ids.append(runner.player_id)
                _credit_throw_error(
                    defense_state=defense_state,
                    defense_map=defense_map,
                    ball_type=ball_type,
                    spray_angle=spray_angle,
                    batter_side=batter_side,
                    infield_play=infield_play,
                    tuning=tuning,
                )
            entry = log_entry
            if entry is None and pitch_log:
                entry = pitch_log[-1]
            if entry is not None:
                _append_entry_value(entry, "error_type", "throwing")
                _append_entry_value(entry, "error_on", error_on)
                existing = entry.get("error_runners")
                if isinstance(existing, list):
                    for runner_id in runner_ids:
                        if runner_id not in existing:
                            existing.append(runner_id)
                else:
                    entry["error_runners"] = runner_ids

        def sync_unearned_runners() -> None:
            base_ids = {
                runner.player_id
                for runner in (bases.first, bases.second, bases.third)
                if runner is not None
            }
            unearned_runners.intersection_update(base_ids)

        open_pa: list[tuple[BatterLine, dict[str, int]]] = []

        def _close_open_pa() -> None:
            if not open_pa:
                return
            bline, snap = open_pa.pop()
            delta = {k: getattr(bline, k) - snap[k] for k in _PA_RESULT_KEYS}
            token = _pa_result_token(delta)
            if token and pitch_log:
                pitch_log[-1]["pa_result"] = token

        def finalize_half_inning() -> None:
            _close_open_pa()
            lob = 0
            for runner in (bases.first, bases.second, bases.third):
                if runner is None:
                    continue
                _batter_line(offense_state, runner).lob += 1
                lob += 1
            totals["lob"] += lob
            if batting_team == "away":
                totals["lob_away"] += lob
                inning_runs_away.append(half_inning_runs)
            else:
                totals["lob_home"] += lob
                inning_runs_home.append(half_inning_runs)

        def post_at_bat(pitcher_state: PitcherState) -> None:
            if walkoff or outs >= 3 or not pitch_log:
                return
            if batting_team == "away":
                offense_score = score_away
                defense_score = score_home
            else:
                offense_score = score_home
                defense_score = score_away
            score_diff = offense_score - defense_score
            pinch_event = _maybe_pinch_run(
                lineup_state=offense_state,
                bases=bases,
                unearned_runners=unearned_runners,
                runner_pitchers=runner_pitchers,
                inning=inning,
                score_diff=score_diff,
                batting_team=batting_team,
                pitcher_id=pitcher_state.pitcher.player_id,
                tuning=tuning,
            )
            if pinch_event:
                existing_event = pitch_log[-1].get("runner_event")
                if existing_event:
                    pitch_log[-1]["runner_event"] = f"{existing_event}+{pinch_event}"
                else:
                    pitch_log[-1]["runner_event"] = pinch_event
        while outs < 3:
            pitcher_state = pitching_state.current
            line = _line_for_pitcher(pitching_state, pitcher_state, inning)
            for runner in (bases.first, bases.second, bases.third):
                if runner is None:
                    continue
                runner_pitchers.setdefault(runner.player_id, line)
            balls = strikes = 0
            batter = offense_state.lineup[batter_index % len(offense_state.lineup)]
            last_pitch_type: str | None = None
            last_pitch_repeat = 0
            if batting_team == "away":
                offense_score = score_away
                defense_score = score_home
            else:
                offense_score = score_home
                defense_score = score_away
            score_diff = offense_score - defense_score
            pinch_hitter = _select_pinch_hitter(
                lineup_state=offense_state,
                batter=batter,
                pitcher=pitcher_state.pitcher,
                inning=inning,
                outs=outs,
                score_diff=score_diff,
                bases=bases,
                tuning=tuning,
            )
            if pinch_hitter is not None and _apply_substitution(
                lineup_state=offense_state,
                old_player=batter,
                new_player=pinch_hitter,
                role="PH",
                inning=inning,
                batting_team=batting_team,
                pitcher_id=pitcher_state.pitcher.player_id,
            ):
                batter = pinch_hitter
            tracker = batter_tracking.setdefault(
                batter.player_id,
                {"pitches": 0, "swings": 0, "o_zone_pitches": 0, "o_zone_swings": 0},
            )
            batter_line = _batter_line(offense_state, batter)
            zone_bottom, zone_top = strike_zone_bounds(
                height_in=batter.height,
                zone_bottom=batter.zone_bottom,
                zone_top=batter.zone_top,
                tuning=tuning,
            )
            batter_index += 1
            totals["pa"] += 1
            batter_line.pa += 1
            _close_open_pa()
            open_pa.append(
                (batter_line, {k: getattr(batter_line, k) for k in _PA_RESULT_KEYS})
            )
            if batter_line.g == 0:
                batter_line.g = 1
            line.batters_faced += 1
            at_bat_over = False
            if _should_intentional_walk(
                bases=bases,
                batter=batter,
                pitcher=pitcher_state.pitcher,
                inning=inning,
                outs=outs,
                score_diff=score_diff,
                tuning=tuning,
            ):
                totals["bb"] += 1
                totals["ibb"] += 1
                line.walks += 1
                line.ibb += 1
                line.inning_walks += 1
                line.inning_baserunners += 1
                line.consecutive_hits = 0
                batter_line.bb += 1
                batter_line.ibb += 1
                before_ids = _base_runner_ids(bases)
                runs_scored, scored = _advance_on_walk(bases, batter)
                _reconcile_runner_pitchers(
                    runner_pitchers,
                    before_ids=before_ids,
                    bases=bases,
                    scored=scored,
                )
                runner_pitchers[batter.player_id] = line
                record_runs(runs_scored, line, scored)
                if scored:
                    batter_line.rbi += len(scored)
                pitch_log.append(
                    {
                        "outcome": "ibb",
                        "pitcher_id": pitcher_state.pitcher.player_id,
                        "batter_id": batter.player_id,
                    }
                )
                post_at_bat(pitcher_state)
                continue
            if _should_bunt(
                bases=bases,
                batter=batter,
                inning=inning,
                outs=outs,
                score_diff=score_diff,
                tuning=tuning,
            ):
                before_ids = _base_runner_ids(bases)
                (
                    runs_scored,
                    outs_added,
                    is_hit,
                    sac_hit,
                    events,
                    scored,
                    error_advances,
                ) = _resolve_bunt(
                    bases=bases,
                    batter=batter,
                    outs=outs,
                    defense=defense_ratings,
                    tuning=tuning,
                )
                entry = {
                    "outcome": "bunt",
                    "pitcher_id": pitcher_state.pitcher.player_id,
                    "batter_id": batter.player_id,
                }
                _reconcile_runner_pitchers(
                    runner_pitchers,
                    before_ids=before_ids,
                    bases=bases,
                    scored=scored,
                )
                if is_hit:
                    totals["h"] += 1
                    totals["b1"] += 1
                    totals["ab"] += 1
                    line.hits += 1
                    line.b1 += 1
                    line.inning_hits += 1
                    line.inning_baserunners += 1
                    line.consecutive_hits += 1
                    batter_line.ab += 1
                    batter_line.h += 1
                    batter_line.b1 += 1
                    runner_pitchers[batter.player_id] = line
                    batter_side = _effective_batter_side(
                        batter.bats, pitcher_state.pitcher.throws
                    )
                    _credit_outs_on_base(
                        defense_state=defense_state,
                        defense_map=defense_map,
                        events=events,
                        ball_type="gb",
                        spray_angle=0.0,
                        batter_side=batter_side,
                        tuning=tuning,
                    )
                    apply_advance_errors(
                        error_runners=error_advances,
                        ball_type="gb",
                        spray_angle=0.0,
                        batter_side=batter_side,
                        infield_play=True,
                        error_on="advance",
                        log_entry=entry,
                    )
                    if outs_added:
                        totals["oob"] += outs_added
                else:
                    line.consecutive_hits = 0
                    if outs_added:
                        batter_side = _effective_batter_side(
                            batter.bats, pitcher_state.pitcher.throws
                        )
                        primary_guess = _fielder_position_for_ball(
                            ball_type="gb",
                            spray_angle=None,
                            batter_side=batter_side,
                            tuning=tuning,
                            infield_play=True,
                        )
                        primary_pos, primary_fielder = _find_fielder(
                            defense_map,
                            primary_guess,
                            fallback_positions=["P", "1B", "3B", "SS", "2B"],
                        )
                        oneb_pos, oneb_fielder = _find_fielder(
                            defense_map, "1B", fallback_positions=["P"]
                        )
                        if "dp" in events:
                            if primary_fielder is not None:
                                _fielding_line(
                                    defense_state, primary_fielder.player_id
                                ).a += 1
                                _fielding_line(
                                    defense_state, primary_fielder.player_id
                                ).dp += 1
                            pivot_pos = (
                                "2B" if primary_pos in {"SS", "3B"} else "SS"
                            )
                            _, pivot_fielder = _find_fielder(
                                defense_map, pivot_pos, fallback_positions=["2B", "SS"]
                            )
                            if pivot_fielder is not None:
                                _fielding_line(
                                    defense_state, pivot_fielder.player_id
                                ).po += 1
                                _fielding_line(
                                    defense_state, pivot_fielder.player_id
                                ).dp += 1
                            if oneb_fielder is not None:
                                _fielding_line(
                                    defense_state, oneb_fielder.player_id
                                ).po += 1
                                _fielding_line(
                                    defense_state, oneb_fielder.player_id
                                ).dp += 1
                        else:
                            if primary_fielder is not None:
                                if primary_pos == "1B":
                                    _fielding_line(
                                        defense_state, primary_fielder.player_id
                                    ).po += 1
                                else:
                                    _fielding_line(
                                        defense_state, primary_fielder.player_id
                                    ).a += 1
                                    if oneb_fielder is not None:
                                        _fielding_line(
                                            defense_state, oneb_fielder.player_id
                                        ).po += 1
                                    else:
                                        _fielding_line(
                                            defense_state, primary_fielder.player_id
                                        ).po += 1
                    if sac_hit:
                        totals["sh"] += 1
                        batter_line.sh += 1
                    else:
                        totals["ab"] += 1
                        batter_line.ab += 1
                if outs_added:
                    outs += outs_added
                    line.outs += outs_added
                record_runs(runs_scored, line, scored)
                if events and "dp" in events:
                    totals["gidp"] += 1
                    batter_line.gidp += 1
                if runs_scored and "dp" not in events:
                    rbi_runs = rbi_credit(scored, error_advances)
                    if rbi_runs:
                        batter_line.rbi += rbi_runs
                if events:
                    entry["runner_event"] = "+".join(events)
                pitch_log.append(entry)
                post_at_bat(pitcher_state)
                continue
            # Constant for the whole plate appearance — hoisted out of the
            # per-pitch loop (S1-09): batter context depends only on the
            # batter/pitcher pairing, and most of the pitcher dict is static
            # (the three fatigue-scaled entries update per pitch below).
            _pa_batter_ctx = _batter_context(batter, pitcher_state.pitcher, tuning)
            _pa_pitcher_ctx = {
                "repertoire": pitcher_state.pitcher.repertoire or {"fb": 50},
                # Fastball velocity; per-type offsets are subtracted in
                # simulate_pitch. +3 vs the old flat 80 recenters the
                # usage-weighted league average now that offspeed pitches
                # are slower (QW-13).
                "velocity": 83.0 + (pitcher_state.pitcher.arm * 0.2),
                "control": pitcher_state.pitcher.control,
                "movement": pitcher_state.pitcher.movement,
                "fatigue_factor": 1.0,
                "hand": pitcher_state.pitcher.throws,
                "vs_left": pitcher_state.pitcher.vs_left,
            }
            while True:
                pitcher_state.pitches += 1
                penalty = _fatigue_penalty(pitcher_state, tuning) + pitcher_state.pregame_penalty
                penalty = min(1.5, penalty)
                pitcher_state.last_penalty = penalty
                velocity_factor, command_factor, movement_factor = _fatigue_factors(
                    penalty
                )
                pitcher = pitcher_state.pitcher
                _update_runner_leads(
                    bases=bases,
                    lineup_state=offense_state,
                    pitcher_hold=pitcher.hold_runner,
                    balls=balls,
                    strikes=strikes,
                    outs=outs,
                    tuning=tuning,
                )
                pitches_seen = tracker.get("pitches", 0)
                swing_rate = None
                chase_rate = None
                if pitches_seen:
                    swing_rate = tracker.get("swings", 0) / pitches_seen
                o_zone_seen = tracker.get("o_zone_pitches", 0)
                if o_zone_seen:
                    chase_rate = tracker.get("o_zone_swings", 0) / o_zone_seen
                pitch_context = {
                    "inning": inning,
                    "outs": outs,
                    "score_diff": defense_score - offense_score,
                    "bases": {
                        "first": bases.first is not None,
                        "second": bases.second is not None,
                        "third": bases.third is not None,
                    },
                    "catcher_fielding": catcher_fielding,
                    "batter_pitches_seen": pitches_seen,
                    "batter_swing_rate": swing_rate,
                    "batter_chase_rate": chase_rate,
                    "last_pitch_type": last_pitch_type,
                    "last_pitch_repeat": last_pitch_repeat,
                    "foul_territory_scale": park.foul_territory_scale,
                }
                _pa_pitcher_ctx["control"] = pitcher.control * command_factor
                _pa_pitcher_ctx["movement"] = pitcher.movement * movement_factor
                _pa_pitcher_ctx["fatigue_factor"] = velocity_factor
                res: PitchResult = simulate_pitch(
                    batter=_pa_batter_ctx,
                    pitcher=_pa_pitcher_ctx,
                    tuning=tuning,
                    count=(balls, strikes),
                    context=pitch_context,
                )
                totals["pitches"] += 1
                line.pitches = pitcher_state.pitches
                entry = res.__dict__.copy()
                entry["count"] = f"{balls}-{strikes}"
                entry["pitch_count"] = pitcher_state.pitches
                entry["fatigue_penalty"] = penalty
                entry["pitcher_id"] = pitcher.player_id
                entry["batter_id"] = batter.player_id
                pitch_log.append(entry)
                batter_line.pitches += 1
                is_strike = res.outcome in _STRIKE_OUTCOMES
                is_ball = res.outcome in _BALL_OUTCOMES
                if is_strike:
                    line.strikes += 1
                elif is_ball:
                    line.balls += 1
                if balls == 0 and strikes == 0 and is_strike:
                    line.first_pitch_strikes += 1
                if res.in_zone is not None:
                    if res.in_zone:
                        line.zone_pitches += 1
                    else:
                        line.o_zone_pitches += 1
                    if res.swing:
                        if res.in_zone:
                            line.zone_swings += 1
                        else:
                            line.o_zone_swings += 1
                        if res.contact:
                            if res.in_zone:
                                line.zone_contacts += 1
                            else:
                                line.o_zone_contacts += 1
                tracker["pitches"] = tracker.get("pitches", 0) + 1
                if not res.in_zone:
                    tracker["o_zone_pitches"] = tracker.get("o_zone_pitches", 0) + 1
                if res.swing:
                    tracker["swings"] = tracker.get("swings", 0) + 1
                    if not res.in_zone:
                        tracker["o_zone_swings"] = tracker.get("o_zone_swings", 0) + 1
                if res.pitch_type == last_pitch_type:
                    last_pitch_repeat += 1
                else:
                    last_pitch_type = res.pitch_type
                    last_pitch_repeat = 1

                if res.outcome == "ball":
                    balls += 1
                    if balls >= 4:
                        totals["bb"] += 1
                        line.walks += 1
                        line.inning_walks += 1
                        line.inning_baserunners += 1
                        line.consecutive_hits = 0
                        batter_line.bb += 1
                        before_ids = _base_runner_ids(bases)
                        runs_scored, scored = _advance_on_walk(bases, batter)
                        _reconcile_runner_pitchers(
                            runner_pitchers,
                            before_ids=before_ids,
                            bases=bases,
                            scored=scored,
                        )
                        runner_pitchers[batter.player_id] = line
                        record_runs(runs_scored, line, scored)
                        if scored:
                            batter_line.rbi += len(scored)
                        at_bat_over = True
                elif res.outcome == "hbp":
                    totals["hbp"] += 1
                    line.hbp += 1
                    line.inning_baserunners += 1
                    line.consecutive_hits = 0
                    batter_line.hbp += 1
                    before_ids = _base_runner_ids(bases)
                    runs_scored, scored = _advance_on_walk(bases, batter)
                    _reconcile_runner_pitchers(
                        runner_pitchers,
                        before_ids=before_ids,
                        bases=bases,
                        scored=scored,
                    )
                    runner_pitchers[batter.player_id] = line
                    record_runs(runs_scored, line, scored)
                    if scored:
                        batter_line.rbi += len(scored)
                    injury_event = _maybe_injure_player(
                        injury_sim=injury_sim,
                        injured_players=injured_players,
                        injury_events=injury_events,
                        player=batter,
                        trigger="hit_by_pitch",
                        context={"pitch_velocity": (res.velocity or 90.0) / 90.0},
                        inning=inning,
                        outs=outs,
                        team=batting_team,
                        pitcher_id=pitcher_state.pitcher.player_id,
                        tuning=tuning,
                        lineup_state=offense_state,
                        bases=bases,
                        base_attr="first",
                        unearned_runners=unearned_runners,
                        runner_pitchers=runner_pitchers,
                    )
                    if injury_event:
                        pitch_log[-1]["injury"] = injury_event
                    at_bat_over = True
                elif res.outcome == "interference":
                    totals["ci"] += 1
                    line.inning_baserunners += 1
                    line.consecutive_hits = 0
                    batter_line.ci += 1
                    catcher = defense_map.get("C")
                    if catcher is not None:
                        _fielding_line(defense_state, catcher.player_id).ci += 1
                    before_ids = _base_runner_ids(bases)
                    runs_scored, scored = _advance_on_walk(bases, batter)
                    _reconcile_runner_pitchers(
                        runner_pitchers,
                        before_ids=before_ids,
                        bases=bases,
                        scored=scored,
                    )
                    runner_pitchers[batter.player_id] = line
                    record_runs(runs_scored, line, scored)
                    if scored:
                        batter_line.rbi += len(scored)
                    at_bat_over = True
                elif res.outcome == "strike":
                    totals["called_strikes"] += 1
                    pitch_log[-1]["called_strike"] = True
                    pitch_log[-1]["called_strike_zone"] = (
                        "in_zone" if res.in_zone else "out_of_zone"
                    )
                    strikes += 1
                    if strikes >= 3:
                        totals["ab"] += 1
                        totals["k"] += 1
                        totals["so_looking"] += 1
                        totals["called_third_strikes"] += 1
                        line.strikeouts += 1
                        line.so_looking += 1
                        line.consecutive_hits = 0
                        batter_line.ab += 1
                        batter_line.so += 1
                        batter_line.so_looking += 1
                        pitch_log[-1]["strikeout"] = True
                        pitch_log[-1]["strikeout_type"] = "called"
                        before_ids = _base_runner_ids(bases)
                        reached, outs_added, runs_scored, miss_event, scored = (
                            _resolve_dropped_third_strike(
                                bases=bases,
                                outs=outs,
                                batter=batter,
                                pitcher_control=pitcher.control,
                                catcher_fielding=catcher_fielding,
                                catcher_arm=catcher_arm,
                                tuning=tuning,
                                location=res.location,
                                zone_bottom=zone_bottom,
                                zone_top=zone_top,
                            )
                        )
                        _reconcile_runner_pitchers(
                            runner_pitchers,
                            before_ids=before_ids,
                            bases=bases,
                            scored=scored,
                        )
                        if reached:
                            runner_pitchers[batter.player_id] = line
                        if miss_event == "wp":
                            totals["wp"] += 1
                            line.wp += 1
                            pitch_log[-1]["runner_event"] = "k_wp"
                        elif miss_event == "pb":
                            totals["pb"] += 1
                            catcher = defense_map.get("C")
                            if catcher is not None:
                                _fielding_line(defense_state, catcher.player_id).pb += 1
                            pitch_log[-1]["runner_event"] = "k_pb"
                        if reached:
                            line.inning_baserunners += 1
                        record_runs(runs_scored, line, scored)
                        outs += outs_added
                        line.outs += outs_added
                        if outs_added:
                            catcher = defense_map.get("C")
                            if catcher is not None:
                                _fielding_line(
                                    defense_state, catcher.player_id
                                ).po += outs_added
                            _fielding_line(
                                defense_state, pitcher_state.pitcher.player_id
                            ).a += outs_added
                        at_bat_over = True
                elif res.outcome == "swinging_strike":
                    totals["swinging_strikes"] += 1
                    pitch_log[-1]["swinging_strike"] = True
                    strikes += 1
                    if strikes >= 3:
                        totals["ab"] += 1
                        totals["k"] += 1
                        totals["so_swinging"] += 1
                        totals["swinging_third_strikes"] += 1
                        line.strikeouts += 1
                        line.so_swinging += 1
                        line.consecutive_hits = 0
                        batter_line.ab += 1
                        batter_line.so += 1
                        batter_line.so_swinging += 1
                        pitch_log[-1]["strikeout"] = True
                        pitch_log[-1]["strikeout_type"] = "swinging"
                        reached, outs_added, runs_scored, miss_event, scored = (
                            _resolve_dropped_third_strike(
                                bases=bases,
                                outs=outs,
                                batter=batter,
                                pitcher_control=pitcher.control,
                                catcher_fielding=catcher_fielding,
                                catcher_arm=catcher_arm,
                                tuning=tuning,
                                location=res.location,
                                zone_bottom=zone_bottom,
                                zone_top=zone_top,
                            )
                        )
                        if miss_event == "wp":
                            totals["wp"] += 1
                            line.wp += 1
                            pitch_log[-1]["runner_event"] = "k_wp"
                        elif miss_event == "pb":
                            totals["pb"] += 1
                            catcher = defense_map.get("C")
                            if catcher is not None:
                                _fielding_line(defense_state, catcher.player_id).pb += 1
                            pitch_log[-1]["runner_event"] = "k_pb"
                        if reached:
                            line.inning_baserunners += 1
                        record_runs(runs_scored, line, scored)
                        outs += outs_added
                        line.outs += outs_added
                        if outs_added:
                            catcher = defense_map.get("C")
                            if catcher is not None:
                                _fielding_line(
                                    defense_state, catcher.player_id
                                ).po += outs_added
                            _fielding_line(
                                defense_state, pitcher_state.pitcher.player_id
                            ).a += outs_added
                        at_bat_over = True
                elif res.outcome == "foul":
                    strikes = min(2, strikes + 1)
                elif res.outcome == "in_play":
                    totals["ab"] += 1
                    batter_line.ab += 1
                    dist, is_hr, ball_type, hit_type = resolve_batted_ball(
                        exit_velo=res.exit_velo or 90.0,
                        launch_angle=res.launch_angle or 12.0,
                        spray_angle=res.spray_angle or 0.0,
                        park=park,
                        tuning=tuning,
                        batter_speed=batter.speed,
                        batter_contact=batter.contact,
                        batter_power=batter.power,
                    )
                    res.distance = dist
                    res.ball_type = ball_type
                    res.hit_type = hit_type
                    pitch_log[-1].update(res.__dict__)
                    if ball_type == "gb":
                        batter_line.gb += 1
                        line.gb += 1
                    elif ball_type == "ld":
                        batter_line.ld += 1
                        line.ld += 1
                    elif ball_type == "fb":
                        batter_line.fb += 1
                        line.fb += 1
                    if is_hr:
                        totals["h"] += 1
                        totals["hr"] += 1
                        line.hits += 1
                        line.home_runs += 1
                        line.inning_hits += 1
                        line.inning_baserunners += 1
                        line.consecutive_hits += 1
                        batter_line.h += 1
                        batter_line.hr += 1
                        (
                            runs_scored,
                            outs_added,
                            events,
                            scored,
                            error_advances,
                        ) = _advance_on_hit(
                            bases=bases,
                            batter=batter,
                            hit_type="hr",
                            defense_arm=defense_ratings.arm,
                            tuning=tuning,
                        )
                        record_runs(runs_scored, line, scored)
                        if scored:
                            rbi_runs = rbi_credit(scored, error_advances)
                            if rbi_runs:
                                batter_line.rbi += rbi_runs
                        if outs_added:
                            totals["oob"] += outs_added
                            outs += outs_added
                            line.outs += outs_added
                        if events:
                            pitch_log[-1]["runner_event"] = "+".join(events)
                        at_bat_over = True
                    else:
                        batter_hand = (batter.bats or "R").upper()
                        pitcher_hand = (pitcher.throws or "R").upper()
                        if batter_hand == "S":
                            batter_hand = "L" if pitcher_hand == "R" else "R"
                        out_prob = out_probability(
                            ball_type=ball_type,
                            exit_velo=res.exit_velo or 90.0,
                            launch_angle=res.launch_angle or 12.0,
                            spray_angle=res.spray_angle,
                            batter_side=batter_hand,
                            pull_tendency=batter.pull_tendency,
                            defense=defense_ratings,
                            tuning=tuning,
                        )
                        hit_prob = (1.0 - out_prob) * tuning.get("babip_scale", 1.0)
                        hit_prob = max(0.02, min(0.95, hit_prob))
                        if rng.random() < hit_prob:
                            totals["h"] += 1
                            line.hits += 1
                            line.inning_hits += 1
                            line.inning_baserunners += 1
                            line.consecutive_hits += 1
                            batter_line.h += 1
                            advance_infield = ball_type == "gb"
                            advance_pos = _fielder_position_for_ball(
                                ball_type=ball_type,
                                spray_angle=res.spray_angle,
                                batter_side=batter_hand,
                                tuning=tuning,
                                infield_play=advance_infield,
                            )
                            advance_fallback = (
                                ["SS", "2B", "3B", "1B"]
                                if advance_infield
                                else ["CF", "LF", "RF"]
                            )
                            advance_pos, advance_fielder = _find_fielder(
                                defense_map,
                                advance_pos,
                                fallback_positions=advance_fallback,
                            )
                            advance_fielding = (
                                defense_ratings.infield
                                if advance_infield
                                else defense_ratings.outfield
                            )
                            _, advance_arm = _fielder_ratings(
                                fielder=advance_fielder,
                                position=advance_pos,
                                fallback_fielding=advance_fielding,
                                fallback_arm=defense_ratings.arm,
                                tuning=tuning,
                            )
                            resolved_hit = _maybe_upgrade_hit(
                                hit_type=hit_type or "single",
                                batter=batter,
                                ball_type=ball_type,
                                defense_arm=advance_arm,
                                tuning=tuning,
                            )
                            if resolved_hit == "double":
                                batter_line.b2 += 1
                                line.b2 += 1
                                totals["b2"] += 1
                            elif resolved_hit == "triple":
                                batter_line.b3 += 1
                                line.b3 += 1
                                totals["b3"] += 1
                            else:
                                batter_line.b1 += 1
                                line.b1 += 1
                                totals["b1"] += 1
                            before_ids = _base_runner_ids(bases)
                            (
                                runs_scored,
                                outs_added,
                                events,
                                scored,
                                error_advances,
                            ) = _advance_on_hit(
                                bases=bases,
                                batter=batter,
                                hit_type=resolved_hit,
                                defense_arm=advance_arm,
                                tuning=tuning,
                            )
                            _reconcile_runner_pitchers(
                                runner_pitchers,
                                before_ids=before_ids,
                                bases=bases,
                                scored=scored,
                            )
                            if batter in (bases.first, bases.second, bases.third):
                                runner_pitchers[batter.player_id] = line
                            _credit_outs_on_base(
                                defense_state=defense_state,
                                defense_map=defense_map,
                                events=events,
                                ball_type=ball_type,
                                spray_angle=res.spray_angle,
                                batter_side=batter_hand,
                                tuning=tuning,
                            )
                            apply_advance_errors(
                                error_runners=error_advances,
                                ball_type=ball_type,
                                spray_angle=res.spray_angle,
                                batter_side=batter_hand,
                                infield_play=ball_type == "gb",
                                error_on="advance",
                            )
                            record_runs(runs_scored, line, scored)
                            if scored:
                                rbi_runs = rbi_credit(scored, error_advances)
                                if rbi_runs:
                                    batter_line.rbi += rbi_runs
                            if outs_added:
                                totals["oob"] += outs_added
                                outs += outs_added
                                line.outs += outs_added
                            if events:
                                pitch_log[-1]["runner_event"] = "+".join(events)
                        else:
                            out_type, infield_play = select_out_type(
                                ball_type, res.launch_angle or 12.0
                            )
                            res.out_type = out_type
                            error_pos = _fielder_position_for_ball(
                                ball_type=ball_type,
                                spray_angle=res.spray_angle,
                                batter_side=batter_hand,
                                tuning=tuning,
                                infield_play=infield_play,
                            )
                            error_fallback = (
                                ["SS", "2B", "3B", "1B"]
                                if infield_play
                                else ["CF", "LF", "RF"]
                            )
                            error_pos, error_fielder = _find_fielder(
                                defense_map,
                                error_pos,
                                fallback_positions=error_fallback,
                            )
                            fallback_fielding = (
                                defense_ratings.infield
                                if infield_play or out_type == "groundout"
                                else defense_ratings.outfield
                            )
                            error_fielding, error_arm = _fielder_ratings(
                                fielder=error_fielder,
                                position=error_pos,
                                fallback_fielding=fallback_fielding,
                                fallback_arm=defense_ratings.arm,
                                tuning=tuning,
                            )
                            error_prob = error_probability(
                                out_type=out_type,
                                infield_play=infield_play,
                                fielding=error_fielding,
                                arm=error_arm,
                                tuning=tuning,
                            )
                            if rng.random() < error_prob:
                                totals["roe"] += 1
                                totals["e"] += 1
                                error_type = select_error_type(
                                    out_type=out_type,
                                    infield_play=infield_play,
                                    fielding=error_fielding,
                                    arm=error_arm,
                                    tuning=tuning,
                                )
                                if error_type == "throwing":
                                    totals["e_throw"] += 1
                                else:
                                    totals["e_field"] += 1
                                if error_fielder is not None:
                                    _fielding_line(
                                        defense_state, error_fielder.player_id
                                    ).e += 1
                                line.inning_baserunners += 1
                                line.consecutive_hits = 0
                                batter_line.roe += 1
                                unearned_outs += 1
                                unearned_runners.add(batter.player_id)
                                res.reached_on_error = True
                                pitch_log[-1]["error_type"] = error_type
                                pitch_log[-1]["error_on"] = out_type
                                pitch_log[-1].update(res.__dict__)
                                before_ids = _base_runner_ids(bases)
                                (
                                    runs_scored,
                                    outs_added,
                                    events,
                                    scored,
                                    error_advances,
                                ) = _advance_on_error(
                                    bases=bases,
                                    batter=batter,
                                    defense_arm=error_arm,
                                    tuning=tuning,
                                )
                                _reconcile_runner_pitchers(
                                    runner_pitchers,
                                    before_ids=before_ids,
                                    bases=bases,
                                    scored=scored,
                                )
                                runner_pitchers[batter.player_id] = line
                                batter_side = _effective_batter_side(
                                    batter.bats, pitcher.throws
                                )
                                _credit_outs_on_base(
                                    defense_state=defense_state,
                                    defense_map=defense_map,
                                    events=events,
                                    ball_type=ball_type,
                                    spray_angle=res.spray_angle,
                                    batter_side=batter_side,
                                    tuning=tuning,
                                )
                                apply_advance_errors(
                                    error_runners=error_advances,
                                    ball_type=ball_type,
                                    spray_angle=res.spray_angle,
                                    batter_side=batter_side,
                                    infield_play=infield_play,
                                    error_on="advance",
                                )
                                record_runs(runs_scored, line, scored)
                                if outs_added:
                                    totals["oob"] += outs_added
                                    outs += outs_added
                                    line.outs += outs_added
                                if events:
                                    pitch_log[-1]["runner_event"] = "+".join(events)
                            else:
                                res.reached_on_error = False
                                pitch_log[-1].update(res.__dict__)
                                batter_side = _effective_batter_side(
                                    batter.bats, pitcher.throws
                                )
                                if out_type == "groundout":
                                    before_ids = _base_runner_ids(bases)
                                    runs_scored, outs_added, events, scored = _resolve_ground_out(
                                        bases=bases,
                                        outs=outs,
                                        batter=batter,
                                        defense_map=defense_map,
                                        defense_ratings=defense_ratings,
                                        spray_angle=res.spray_angle,
                                        batter_side=batter_side,
                                        tuning=tuning,
                                    )
                                    _reconcile_runner_pitchers(
                                        runner_pitchers,
                                        before_ids=before_ids,
                                        bases=bases,
                                        scored=scored,
                                    )
                                    if batter in (bases.first, bases.second, bases.third):
                                        runner_pitchers[batter.player_id] = line
                                    primary_guess = _fielder_position_for_ball(
                                        ball_type="gb",
                                        spray_angle=res.spray_angle,
                                        batter_side=batter_side,
                                        tuning=tuning,
                                        infield_play=True,
                                    )
                                    primary_pos, primary_fielder = _find_fielder(
                                        defense_map,
                                        primary_guess,
                                        fallback_positions=["SS", "2B", "3B", "1B"],
                                    )
                                    oneb_pos, oneb_fielder = _find_fielder(
                                        defense_map, "1B", fallback_positions=["P"]
                                    )
                                    if "tp" in events:
                                        primary_id = (
                                            primary_fielder.player_id
                                            if primary_fielder is not None
                                            else None
                                        )
                                        oneb_id = (
                                            oneb_fielder.player_id
                                            if oneb_fielder is not None
                                            else None
                                        )
                                        pivot_pos = (
                                            "2B" if primary_pos in {"SS", "3B"} else "SS"
                                        )
                                        _, pivot_fielder = _find_fielder(
                                            defense_map,
                                            pivot_pos,
                                            fallback_positions=["2B", "SS"],
                                        )
                                        pivot_id = (
                                            pivot_fielder.player_id
                                            if pivot_fielder is not None
                                            else None
                                        )
                                        used_po: set[str] = set()
                                        used_a: set[str] = set()
                                        used_tp: set[str] = set()
                                        if primary_fielder is not None:
                                            primary_line = _fielding_line(
                                                defense_state, primary_fielder.player_id
                                            )
                                            if primary_pos != "1B":
                                                if primary_id not in used_po:
                                                    primary_line.po += 1
                                                    used_po.add(primary_id)
                                            if primary_id not in used_a:
                                                primary_line.a += 1
                                                used_a.add(primary_id)
                                            if primary_id not in used_tp:
                                                primary_line.tp += 1
                                                used_tp.add(primary_id)
                                        if pivot_fielder is not None:
                                            pivot_line = _fielding_line(
                                                defense_state, pivot_fielder.player_id
                                            )
                                            if pivot_id not in used_po:
                                                pivot_line.po += 1
                                                used_po.add(pivot_id)
                                            if pivot_id not in used_a:
                                                pivot_line.a += 1
                                                used_a.add(pivot_id)
                                            if pivot_id not in used_tp:
                                                pivot_line.tp += 1
                                                used_tp.add(pivot_id)
                                        if (
                                            oneb_fielder is not None
                                            and oneb_id not in used_po
                                        ):
                                            oneb_line = _fielding_line(
                                                defense_state, oneb_fielder.player_id
                                            )
                                            oneb_line.po += 1
                                            used_po.add(oneb_id)
                                            if oneb_id not in used_tp:
                                                oneb_line.tp += 1
                                                used_tp.add(oneb_id)
                                    elif "dp" in events:
                                        if primary_fielder is not None:
                                            if primary_pos == "1B":
                                                _fielding_line(
                                                    defense_state, primary_fielder.player_id
                                                ).po += 1
                                            else:
                                                _fielding_line(
                                                    defense_state, primary_fielder.player_id
                                                ).a += 1
                                            _fielding_line(
                                                defense_state, primary_fielder.player_id
                                            ).dp += 1
                                        pivot_pos = (
                                            "2B" if primary_pos in {"SS", "3B"} else "SS"
                                        )
                                        _, pivot_fielder = _find_fielder(
                                            defense_map, pivot_pos, fallback_positions=["2B", "SS"]
                                        )
                                        if pivot_fielder is not None:
                                            _fielding_line(
                                                defense_state, pivot_fielder.player_id
                                            ).po += 1
                                            _fielding_line(
                                                defense_state, pivot_fielder.player_id
                                            ).dp += 1
                                        if oneb_fielder is not None:
                                            _fielding_line(
                                                defense_state, oneb_fielder.player_id
                                            ).po += 1
                                            _fielding_line(
                                                defense_state, oneb_fielder.player_id
                                            ).dp += 1
                                    elif "fc" in events:
                                        if primary_fielder is not None:
                                            _fielding_line(
                                                defense_state, primary_fielder.player_id
                                            ).a += 1
                                        pivot_pos = (
                                            "2B" if primary_pos in {"SS", "3B"} else "SS"
                                        )
                                        _, pivot_fielder = _find_fielder(
                                            defense_map, pivot_pos, fallback_positions=["2B", "SS"]
                                        )
                                        if pivot_fielder is not None:
                                            _fielding_line(
                                                defense_state, pivot_fielder.player_id
                                            ).po += 1
                                    else:
                                        if primary_fielder is not None:
                                            if primary_pos == "1B":
                                                _fielding_line(
                                                    defense_state, primary_fielder.player_id
                                                ).po += 1
                                            else:
                                                _fielding_line(
                                                    defense_state, primary_fielder.player_id
                                                ).a += 1
                                                if oneb_fielder is not None:
                                                    _fielding_line(
                                                        defense_state,
                                                        oneb_fielder.player_id,
                                                    ).po += 1
                                                else:
                                                    _fielding_line(
                                                        defense_state,
                                                        primary_fielder.player_id,
                                                    ).po += 1
                                    if "dp" in events or "tp" in events:
                                        totals["gidp"] += 1
                                        batter_line.gidp += 1
                                    if "tp" in events:
                                        totals["tp"] += 1
                                    if "fc" in events:
                                        totals["fc"] += 1
                                        batter_line.fc += 1
                                        line.inning_baserunners += 1
                                    if events:
                                        pitch_log[-1]["runner_event"] = "+".join(events)
                                    if runs_scored and "dp" not in events:
                                        batter_line.rbi += len(scored)
                                else:
                                    before_ids = _base_runner_ids(bases)
                                    fielder_pos = _fielder_position_for_ball(
                                        ball_type=ball_type,
                                        spray_angle=res.spray_angle,
                                        batter_side=batter_side,
                                        tuning=tuning,
                                        infield_play=infield_play,
                                    )
                                    fallback = (
                                        ["SS", "2B", "3B", "1B"]
                                        if infield_play
                                        else ["CF", "LF", "RF"]
                                    )
                                    pos, fielder = _find_fielder(
                                        defense_map, fielder_pos, fallback_positions=fallback
                                    )
                                    fallback_fielding = (
                                        defense_ratings.infield
                                        if infield_play
                                        else defense_ratings.outfield
                                    )
                                    _, thrower_arm = _fielder_ratings(
                                        fielder=fielder,
                                        position=pos,
                                        fallback_fielding=fallback_fielding,
                                        fallback_arm=defense_ratings.arm,
                                        tuning=tuning,
                                    )
                                    (
                                        runs_scored,
                                        extra_outs,
                                        sac_fly,
                                        scored,
                                        tag_out_runner,
                                    ) = _advance_on_air_out(
                                        bases=bases,
                                        outs=outs,
                                        thrower_arm=thrower_arm,
                                        tuning=tuning,
                                    )
                                    air_events: list[str] = []
                                    if (
                                        tag_out_runner is not None
                                        and random.random()
                                        < _throw_error_probability(
                                            thrower_arm, tuning
                                        )
                                    ):
                                        extra_outs = 0
                                        runs_scored += 1
                                        scored.append(tag_out_runner)
                                        sac_fly = False
                                        air_events.append("e_th")
                                        apply_advance_errors(
                                            error_runners=[tag_out_runner],
                                            ball_type=ball_type,
                                            spray_angle=res.spray_angle,
                                            batter_side=batter_side,
                                            infield_play=infield_play,
                                            error_on="tag_up",
                                        )
                                    _reconcile_runner_pitchers(
                                        runner_pitchers,
                                        before_ids=before_ids,
                                        bases=bases,
                                        scored=scored,
                                    )
                                    if fielder is not None:
                                        _fielding_line(
                                            defense_state, fielder.player_id
                                        ).po += 1
                                    if extra_outs:
                                        totals["oob"] += extra_outs
                                        if fielder is not None:
                                            _fielding_line(
                                                defense_state, fielder.player_id
                                            ).a += extra_outs
                                        catcher = defense_map.get("C")
                                        if catcher is not None:
                                            _fielding_line(
                                                defense_state, catcher.player_id
                                            ).po += extra_outs
                                    outs_added = 1 + extra_outs
                                    if sac_fly:
                                        totals["sf"] += 1
                                        batter_line.sf += 1
                                        if totals["ab"] > 0:
                                            totals["ab"] -= 1
                                        if batter_line.ab > 0:
                                            batter_line.ab -= 1
                                        if scored:
                                            batter_line.rbi += len(scored)
                                    if air_events:
                                        pitch_log[-1]["runner_event"] = "+".join(air_events)
                                outs += outs_added
                                line.outs += outs_added
                                line.consecutive_hits = 0
                                record_runs(runs_scored, line, scored)
                    at_bat_over = True

                if at_bat_over:
                    sync_unearned_runners()
                    post_at_bat(pitcher_state)
                    break

                runner_event = None
                if res.outcome in {"ball", "strike", "swinging_strike", "foul"}:
                    if batting_team == "away":
                        offense_score = score_away
                        defense_score = score_home
                    else:
                        offense_score = score_home
                        defense_score = score_away
                    score_diff = offense_score - defense_score
                    pickoff_refs = {
                        "po1": bases.first,
                        "poa1": bases.first,
                        "po2": bases.second,
                        "poa2": bases.second,
                        "po3": bases.third,
                        "poa3": bases.third,
                    }
                    if bases.first or bases.second or bases.third:
                        balk_rate = tuning.get("balk_rate", 0.0004)
                        balk_rate *= 1.0 + (50.0 - pitcher.control) / 200.0
                        if random.random() < balk_rate:
                            totals["balk"] += 1
                            line.bk += 1
                            runs_scored, scored = _advance_on_balk(bases)
                            record_runs(runs_scored, line, scored)
                            runner_event = "balk"
                    if runner_event is None:
                        miss_event = _missed_pitch_type(
                            location=res.location,
                            pitcher_control=pitcher.control,
                            catcher_fielding=catcher_fielding,
                            zone_bottom=zone_bottom,
                            zone_top=zone_top,
                            tuning=tuning,
                        )
                        if miss_event:
                            runner_event = miss_event
                            if miss_event == "wp":
                                totals["wp"] += 1
                                line.wp += 1
                            else:
                                totals["pb"] += 1
                                catcher = defense_map.get("C")
                                if catcher is not None:
                                    _fielding_line(defense_state, catcher.player_id).pb += 1
                            runs_scored, scored = _advance_on_missed_pitch(
                                bases=bases, catcher_arm=catcher_arm, tuning=tuning
                            )
                            record_runs(runs_scored, line, scored)
                        else:
                            (
                                pickoff_event,
                                pickoff_outs,
                                pickoff_attempted,
                            ) = _attempt_pickoff(
                                bases=bases,
                                pitcher_hold=pitcher.hold_runner,
                                pitcher_arm=pitcher.arm,
                                defense_arm=defense_ratings.arm,
                                tuning=tuning,
                            )
                            if pickoff_attempted:
                                if pickoff_outs:
                                    totals["po"] += pickoff_outs
                                    outs += pickoff_outs
                                    line.outs += pickoff_outs
                                runner_event = pickoff_event
                                runner = pickoff_refs.get(pickoff_event)
                                if pickoff_event in {"po1", "po2", "po3"} and runner:
                                    base_map = {
                                        "po1": "first",
                                        "po2": "second",
                                        "po3": "third",
                                    }
                                    base_key = base_map.get(pickoff_event, "")
                                    is_pocs = _pickoff_caught_stealing(
                                        runner=runner,
                                        base=base_key,
                                        pitcher_hold=pitcher.hold_runner,
                                        pitcher_arm=pitcher.arm,
                                        catcher_arm=catcher_arm,
                                        catcher_fielding=catcher_fielding,
                                        balls=balls,
                                        strikes=strikes,
                                        outs=outs,
                                        inning=inning,
                                        score_diff=score_diff,
                                        tuning=tuning,
                                    )
                                    if is_pocs:
                                        _batter_line(offense_state, runner).pocs += 1
                                        line.pocs += 1
                                    else:
                                        _batter_line(offense_state, runner).po += 1
                                        line.pk += 1
                                        _fielding_line(
                                            defense_state,
                                            pitcher_state.pitcher.player_id,
                                        ).pk += 1
                                    pos_map = {"po1": "1B", "po2": "2B", "po3": "3B"}
                                    pos = pos_map.get(pickoff_event)
                                    if pos:
                                        fielder = defense_map.get(pos)
                                        if fielder is not None:
                                            _fielding_line(
                                                defense_state, fielder.player_id
                                            ).po += 1
                                    runner_pitchers.pop(runner.player_id, None)
                                    injury_event = _maybe_injure_player(
                                        injury_sim=injury_sim,
                                        injured_players=injured_players,
                                        injury_events=injury_events,
                                        player=runner,
                                        trigger="collision",
                                        context={"speed": runner.speed / 100.0},
                                        inning=inning,
                                        outs=outs,
                                        team=batting_team,
                                        pitcher_id=pitcher.player_id,
                                        tuning=tuning,
                                        lineup_state=offense_state,
                                        runner_pitchers=runner_pitchers,
                                    )
                                    if injury_event:
                                        pitch_log[-1]["injury"] = injury_event
                            else:
                                events, outs_added, runs_scored, scored = _attempt_steal(
                                    bases=bases,
                                    pitcher_hold=pitcher.hold_runner,
                                    pitcher_arm=pitcher.arm,
                                    catcher_arm=catcher_arm,
                                    catcher_fielding=catcher_fielding,
                                    balls=balls,
                                    strikes=strikes,
                                    outs=outs,
                                    inning=inning,
                                    score_diff=score_diff,
                                    tuning=tuning,
                                )
                                if events:
                                    catcher = defense_map.get("C")
                                    catcher_line = (
                                        _fielding_line(defense_state, catcher.player_id)
                                        if catcher is not None
                                        else None
                                    )
                                    for runner, event_code in events:
                                        if event_code.startswith("sb"):
                                            totals["sb"] += 1
                                            _batter_line(offense_state, runner).sb += 1
                                            if catcher_line is not None:
                                                catcher_line.sba += 1
                                        elif event_code.startswith("cs"):
                                            totals["cs"] += 1
                                            _batter_line(offense_state, runner).cs += 1
                                            if catcher_line is not None:
                                                catcher_line.sba += 1
                                                catcher_line.cs += 1
                                                catcher_line.a += 1
                                            tagger = None
                                            if event_code == "cs2":
                                                tagger = defense_map.get("2B") or defense_map.get(
                                                    "SS"
                                                )
                                            elif event_code == "cs3":
                                                tagger = defense_map.get("3B")
                                            elif event_code == "csh":
                                                tagger = defense_map.get("C")
                                            if tagger is not None:
                                                _fielding_line(
                                                    defense_state, tagger.player_id
                                                ).po += 1
                                            runner_pitchers.pop(runner.player_id, None)
                                    if outs_added:
                                        outs += outs_added
                                        line.outs += outs_added
                                    record_runs(runs_scored, line, scored)
                                    runner_event = "+".join(event_code for _, event_code in events)
                                    for runner, event_code in events:
                                        if event_code.startswith("cs") or event_code == "csh":
                                            injury_event = _maybe_injure_player(
                                                injury_sim=injury_sim,
                                                injured_players=injured_players,
                                                injury_events=injury_events,
                                                player=runner,
                                                trigger="collision",
                                                context={"speed": runner.speed / 100.0},
                                                inning=inning,
                                                outs=outs,
                                                team=batting_team,
                                                pitcher_id=pitcher.player_id,
                                                tuning=tuning,
                                                lineup_state=offense_state,
                                                runner_pitchers=runner_pitchers,
                                            )
                                            if injury_event:
                                                pitch_log[-1]["injury"] = injury_event

                if runner_event:
                    pitch_log[-1]["runner_event"] = runner_event
                    sync_unearned_runners()
                    if outs >= 3:
                        break
            if walkoff:
                finalize_half_inning()
                return outs, batter_index
            if outs >= 3:
                continue
            if batting_team == "away":
                pitching_score = score_home
                batting_score = score_away
            else:
                pitching_score = score_away
                batting_score = score_home
            score_diff = pitching_score - batting_score
            line = _line_for_pitcher(pitching_state, pitching_state.current, inning)
            upcoming = _upcoming_batters(offense_state, batter_index, count=3)
            if _maybe_pitcher_overuse_injury(
                injury_sim=injury_sim,
                injured_players=injured_players,
                injury_events=injury_events,
                pitching_state=pitching_state,
                lineup_state=defense_state,
                bases=bases,
                inning=inning,
                outs=outs,
                score_diff=score_diff,
                defense_score=pitching_score,
                offense_score=batting_score,
                upcoming_batters=upcoming,
                team=defense_team,
                tuning=tuning,
                postseason=postseason,
            ):
                continue
            if _should_hook_pitcher(
                pitcher_state=pitching_state.current,
                line=line,
                lineup_size=lineup_size,
                score_diff=score_diff,
                postseason=postseason,
                tuning=tuning,
            ):
                leverage = _leverage_type(inning, score_diff, tuning)
                next_pitcher = _select_reliever(
                    pitching_state,
                    leverage,
                    inning=inning,
                    score_diff=score_diff,
                    is_home_defense=(defense_team == "home"),
                    upcoming_batters=upcoming,
                    tuning=tuning,
                )
                if next_pitcher is not pitching_state.current:
                    _pitcher_exit_stats(
                        pitcher_state=pitching_state.current,
                        line=line,
                        defense_score=pitching_score,
                        offense_score=batting_score,
                        game_finished=False,
                    )
                    _pitcher_enter_stats(
                        pitching_state=pitching_state,
                        pitcher_state=next_pitcher,
                        lineup_state=defense_state,
                        inning=inning,
                        score_diff=score_diff,
                        defense_score=pitching_score,
                        offense_score=batting_score,
                        bases=bases,
                        postseason=postseason,
                        tuning=tuning,
                    )
        finalize_half_inning()
        return outs, batter_index

    max_innings = int(tuning.get("max_innings", 18.0))
    inning = 1
    ended_in_tie = False
    while True:
        _, away_index = play_half_inning(
            away_state,
            home_state,
            home_staff,
            away_index,
            inning,
            "away",
            False,
        )
        if inning >= 9 and score_home > score_away:
            break
        _, home_index = play_half_inning(
            home_state,
            away_state,
            away_staff,
            home_index,
            inning,
            "home",
            inning >= 9,
        )
        if inning >= 9 and score_home != score_away:
            break
        inning += 1
        if inning > max_innings:
            ended_in_tie = True
            break

    final_home = home_staff.current
    final_away = away_staff.current
    home_line = _line_for_pitcher(home_staff, final_home, inning)
    away_line = _line_for_pitcher(away_staff, final_away, inning)
    home_line.gf += 1
    away_line.gf += 1

    if score_home != score_away:
        winner_key = "home" if score_home > score_away else "away"
        loser_key = "away" if winner_key == "home" else "home"
        winning_pid = pitcher_of_record.get(winner_key)
        losing_pid = losing_pitcher
        if losing_pid is None:
            losing_pid = (
                home_staff.current.pitcher.player_id
                if loser_key == "home"
                else away_staff.current.pitcher.player_id
            )
        if winning_pid:
            winning_state = home_staff if winner_key == "home" else away_staff
            win_line = winning_state.lines.get(winning_pid)
            if win_line is None:
                win_line = PitcherLine(pitcher_id=winning_pid, current_inning=inning)
                winning_state.lines[winning_pid] = win_line
            win_line.w += 1
        if losing_pid:
            losing_state = home_staff if loser_key == "home" else away_staff
            loss_line = losing_state.lines.get(losing_pid)
            if loss_line is None:
                loss_line = PitcherLine(pitcher_id=losing_pid, current_inning=inning)
                losing_state.lines[losing_pid] = loss_line
            loss_line.l += 1

        def award_save(
            *,
            final_pitcher: PitcherState,
            line: PitcherLine,
            winning_pitcher_id: str | None,
            lead: int,
        ) -> bool:
            if final_pitcher.pitcher.player_id == winning_pitcher_id:
                return False
            if final_pitcher.entered_save_opp:
                return True
            long_innings = int(tuning.get("save_long_innings", 3.0))
            if long_innings > 0 and lead > 0 and line.outs >= long_innings * 3:
                return True
            return False

        if winner_key == "home":
            if award_save(
                final_pitcher=final_home,
                line=home_line,
                winning_pitcher_id=winning_pid,
                lead=score_home - score_away,
            ):
                home_line.sv += 1
        else:
            if award_save(
                final_pitcher=final_away,
                line=away_line,
                winning_pitcher_id=winning_pid,
                lead=score_away - score_home,
            ):
                away_line.sv += 1

    if usage_state is not None and game_day is not None:
        for state in away_staff.all_pitchers() + home_staff.all_pitchers():
            if state.pitches > 0:
                usage_state.record_outing(
                    pitcher_id=state.pitcher.player_id,
                    pitches=state.pitches,
                    day=game_day,
                    multiplier=state.usage_multiplier,
                    tuning=tuning,
                )
        batter_lookup: dict[str, BatterRatings] = {
            batter.player_id: batter
            for batter in (
                list(away_state.lineup)
                + list(away_state.bench)
                + list(home_state.lineup)
                + list(home_state.bench)
            )
        }
        batter_ids = set(away_state.batting_lines.keys())
        batter_ids.update(home_state.batting_lines.keys())
        batter_ids.update(away_state.fielding_lines.keys())
        batter_ids.update(home_state.fielding_lines.keys())
        for event in away_state.substitutions + home_state.substitutions:
            if isinstance(event, dict):
                player_id = event.get("new_player_id")
                if player_id:
                    batter_ids.add(str(player_id))
        for player_id in batter_ids:
            batter = batter_lookup.get(player_id)
            if batter is None:
                continue
            usage_state.record_batter_game(
                player_id=player_id,
                day=game_day,
                durability=batter.durability,
                tuning=tuning,
            )

    return GameResult(
        totals=totals,
        pitch_log=pitch_log,
        metadata={
            "park": park.name,
            "seed": seed,
            "pitcher_usage": {
                "away": [
                    _pitcher_usage_summary(state)
                    for state in away_staff.all_pitchers()
                ],
                "home": [
                    _pitcher_usage_summary(state)
                    for state in home_staff.all_pitchers()
                ],
            },
            "pitcher_lines": {
                "away": _team_line_summaries(away_staff),
                "home": _team_line_summaries(home_staff),
            },
            "batting_lines": {
                "away": _team_batting_summaries(away_state),
                "home": _team_batting_summaries(home_state),
            },
            "fielding_lines": {
                "away": _team_fielding_summaries(away_state),
                "home": _team_fielding_summaries(home_state),
            },
            "score": {"away": score_away, "home": score_home},
            "inning_runs": {
                "away": inning_runs_away,
                "home": inning_runs_home,
            },
            "ended_in_tie": ended_in_tie,
            "innings": inning,
            "substitutions": {
                "away": away_state.substitutions,
                "home": home_state.substitutions,
            },
            "bench_remaining": {
                "away": len(away_state.bench),
                "home": len(home_state.bench),
            },
            "injury_events": injury_events,
        },
    )
