"""Strategy-aware CPU finance helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import random
from typing import Dict, Mapping

from services.contracts_service import (
    DEFAULT_MIN_SALARY,
    contract_payroll_value,
    estimate_salary_for_player,
    load_contracts_payload,
)
from services.finance_settings import DEFAULT_FINANCE_AI_TUNING, load_financial_settings
from services.owner_finance_engine import project_monthly_owner_finance
from services.payroll_engine import calculate_annual_payroll_totals
from services.team_strategy_profiles import (
    load_team_strategy_settings,
    resolve_team_strategy_profile,
    to_finance_strategy_profile,
)
from services.standings_repository import invalidate_standings, load_standings
from utils.path_utils import get_data_dir

__all__ = [
    "TeamFinanceStrategy",
    "ArbitrationDecision",
    "load_team_finance_strategies",
    "recommend_cpu_arbitration_decision",
    "estimate_free_agent_salary_band",
    "build_cpu_free_agent_bid_book",
]

PROFILE_CONTEND = "contend"
PROFILE_BALANCED = "balanced"
PROFILE_REBUILD = "rebuild"

AI_LEVEL_OFF = "off"
AI_LEVEL_BASIC = "basic"
AI_LEVEL_ADVANCED = "advanced"

_BUDGET_AGGRESSIVE = "aggressive"
_BUDGET_NEUTRAL = "neutral"
_BUDGET_CAUTIOUS = "cautious"


@dataclass(frozen=True)
class TeamFinanceStrategy:
    team_id: str
    profile: str
    budget_tone: str
    win_pct: float
    cash_on_hand: int
    debt: int
    projected_net: int
    annual_payroll: int
    next_year_commitment: int = 0
    two_year_commitment: int = 0
    raw_strategy_profile: str = "balanced"


@dataclass(frozen=True)
class ArbitrationDecision:
    applied_bump: float
    decision_code: str
    non_tender: bool


def load_team_finance_strategies(
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, TeamFinanceStrategy]:
    """Return per-team strategy profiles for CPU finance decisions."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    standings = _load_standings(resolved_data_dir)
    payroll_totals = calculate_annual_payroll_totals(data_dir=resolved_data_dir)
    commitments = _load_multi_year_commitments(resolved_data_dir)
    team_financials = _load_team_financials(resolved_data_dir)
    projections = project_monthly_owner_finance(data_dir=resolved_data_dir)
    try:
        strategy_settings = load_team_strategy_settings(data_dir=resolved_data_dir)
    except Exception:
        strategy_settings = {"default_profile": "balanced", "team_overrides": {}}
    strategy_default = str(strategy_settings.get("default_profile") or "balanced").strip().lower()
    raw_overrides = strategy_settings.get("team_overrides", {})
    strategy_overrides = raw_overrides if isinstance(raw_overrides, Mapping) else {}
    override_team_ids = {
        str(key or "").strip().upper() for key in strategy_overrides.keys()
    }

    team_ids = set(standings.keys())
    team_ids.update(payroll_totals.keys())
    team_ids.update(commitments.keys())
    teams_payload = team_financials.get("teams")
    if isinstance(teams_payload, Mapping):
        team_ids.update(str(team_id).strip() for team_id in teams_payload.keys())
    team_ids.discard("")

    strategies: Dict[str, TeamFinanceStrategy] = {}
    for team_id in sorted(team_ids):
        raw_financial = {}
        if isinstance(teams_payload, Mapping):
            raw_financial = teams_payload.get(team_id)
        financial = raw_financial if isinstance(raw_financial, Mapping) else {}
        cash_on_hand = _safe_int(financial.get("cash_on_hand"), fallback=0)
        debt = _safe_int(financial.get("debt"), fallback=0)
        annual_payroll = max(0, _safe_int(payroll_totals.get(team_id), fallback=0))
        commitment = commitments.get(team_id, {})
        next_year_commitment = max(
            0,
            _safe_int(commitment.get("next_year", 0), fallback=0),
        )
        two_year_commitment = max(
            0,
            _safe_int(commitment.get("two_year", 0), fallback=0),
        )
        projected_net = 0
        projection = projections.get(team_id)
        if projection is not None:
            projected_net = _safe_int(getattr(projection, "projected_net", 0), fallback=0)
        win_pct = _win_pct(standings.get(team_id))
        profile = _resolve_profile(win_pct, cash_on_hand=cash_on_hand, debt=debt, projected_net=projected_net)
        raw_strategy_profile = "balanced"
        has_team_override = str(team_id or "").strip().upper() in override_team_ids
        if has_team_override or strategy_default != "balanced":
            try:
                resolved_profile = resolve_team_strategy_profile(
                    team_id,
                    data_dir=resolved_data_dir,
                )
                raw_strategy_profile = str(getattr(resolved_profile, "profile", "balanced") or "balanced")
                profile = to_finance_strategy_profile(raw_strategy_profile)
            except Exception:
                pass
        budget_tone = _resolve_budget_tone(
            cash_on_hand=cash_on_hand,
            debt=debt,
            projected_net=projected_net,
        )
        strategies[team_id] = TeamFinanceStrategy(
            team_id=team_id,
            profile=profile,
            raw_strategy_profile=raw_strategy_profile,
            budget_tone=budget_tone,
            win_pct=win_pct,
            cash_on_hand=cash_on_hand,
            debt=debt,
            projected_net=projected_net,
            annual_payroll=annual_payroll,
            next_year_commitment=next_year_commitment,
            two_year_commitment=two_year_commitment,
        )
    return strategies


def recommend_cpu_arbitration_decision(
    *,
    ai_level: str,
    team_strategy: TeamFinanceStrategy | None,
    base_bump: float,
    current_salary: int,
    salary_share: float,
    talent_score: int,
    performance_score: int,
    tuning: Mapping[str, object] | None = None,
) -> ArbitrationDecision:
    """Return CPU arbitration action for one player."""

    level = str(ai_level or "").strip().lower()
    if level not in {AI_LEVEL_BASIC, AI_LEVEL_ADVANCED}:
        return ArbitrationDecision(
            applied_bump=max(0.0, float(base_bump)),
            decision_code="cpu_standard",
            non_tender=False,
        )

    profile = PROFILE_BALANCED
    budget_tone = _BUDGET_NEUTRAL
    if team_strategy is not None:
        profile = str(team_strategy.profile or PROFILE_BALANCED).strip().lower()
        budget_tone = str(team_strategy.budget_tone or _BUDGET_NEUTRAL).strip().lower()

    current_salary = max(0, int(current_salary))
    salary_share = max(0.0, float(salary_share))
    talent_score = max(0, min(99, int(talent_score)))
    performance_score = max(0, min(99, int(performance_score)))
    bump = max(0.0, float(base_bump))

    tuning_map = _merge_tuning(tuning)
    star_talent_threshold = _tuning_int(tuning_map, "star_talent_threshold")
    star_performance_threshold = _tuning_int(tuning_map, "star_performance_threshold")
    underperformer_threshold = _tuning_int(tuning_map, "underperformer_threshold")
    severe_underperformer_threshold = _tuning_int(
        tuning_map,
        "severe_underperformer_threshold",
    )
    high_cost_salary_share_threshold = _tuning_float(tuning_map, "high_cost_salary_share")
    very_high_cost_salary_share_threshold = _tuning_float(
        tuning_map,
        "very_high_cost_salary_share",
    )
    high_cost_salary_threshold = _tuning_int(tuning_map, "high_cost_salary")
    very_high_cost_salary_threshold = _tuning_int(tuning_map, "very_high_cost_salary")
    max_raise_pct = _tuning_float(tuning_map, "max_raise_pct")

    is_star = (
        talent_score >= star_talent_threshold
        or performance_score >= star_performance_threshold
    )
    high_cost = (
        salary_share >= high_cost_salary_share_threshold
        or current_salary >= high_cost_salary_threshold
    )
    very_high_cost = (
        salary_share >= very_high_cost_salary_share_threshold
        or current_salary >= very_high_cost_salary_threshold
    )
    underperforming = performance_score <= underperformer_threshold
    severe_underperforming = performance_score <= severe_underperformer_threshold

    if profile == PROFILE_CONTEND:
        if is_star:
            bump += 0.07 if level == AI_LEVEL_ADVANCED else 0.05
            return ArbitrationDecision(
                applied_bump=min(max_raise_pct, bump),
                decision_code="cpu_retain_star",
                non_tender=False,
            )
        if high_cost and underperforming and talent_score < 62:
            if very_high_cost and severe_underperforming and budget_tone == _BUDGET_CAUTIOUS:
                return ArbitrationDecision(
                    applied_bump=0.0,
                    decision_code="cpu_non_tender_high_cost_underperformer",
                    non_tender=True,
                )
            return ArbitrationDecision(
                applied_bump=max(0.0, bump - 0.06),
                decision_code="cpu_hold_salary_underperformer",
                non_tender=False,
            )
        if underperforming and talent_score < 58:
            return ArbitrationDecision(
                applied_bump=max(0.0, bump - 0.08),
                decision_code="cpu_cautious_raise",
                non_tender=False,
            )
        return ArbitrationDecision(
            applied_bump=min(max_raise_pct, bump),
            decision_code="cpu_standard",
            non_tender=False,
        )

    if profile == PROFILE_REBUILD:
        if is_star:
            bump += 0.03 if level == AI_LEVEL_ADVANCED else 0.02
            return ArbitrationDecision(
                applied_bump=min(max_raise_pct, bump),
                decision_code="cpu_retain_star",
                non_tender=False,
            )
        if high_cost and underperforming and talent_score < 67:
            should_non_tender = very_high_cost or (
                salary_share >= 0.24 and budget_tone == _BUDGET_CAUTIOUS
            )
            if should_non_tender:
                return ArbitrationDecision(
                    applied_bump=0.0,
                    decision_code="cpu_non_tender_high_cost_underperformer",
                    non_tender=True,
                )
            return ArbitrationDecision(
                applied_bump=0.0,
                decision_code="cpu_hold_salary_underperformer",
                non_tender=False,
            )
        if underperforming and talent_score < 62:
            return ArbitrationDecision(
                applied_bump=max(0.0, bump - 0.10),
                decision_code="cpu_cautious_raise",
                non_tender=False,
            )
        return ArbitrationDecision(
            applied_bump=min(max_raise_pct, bump),
            decision_code="cpu_standard",
            non_tender=False,
        )

    # Balanced profile
    if is_star:
        bump += 0.06 if level == AI_LEVEL_ADVANCED else 0.04
        return ArbitrationDecision(
            applied_bump=min(max_raise_pct, bump),
            decision_code="cpu_retain_star",
            non_tender=False,
        )
    if high_cost and underperforming and talent_score < 65:
        if very_high_cost:
            return ArbitrationDecision(
                applied_bump=0.0,
                decision_code="cpu_non_tender_high_cost_underperformer",
                non_tender=True,
            )
        return ArbitrationDecision(
            applied_bump=0.0,
            decision_code="cpu_hold_salary_underperformer",
            non_tender=False,
        )
    if underperforming and talent_score < 60:
        return ArbitrationDecision(
            applied_bump=max(0.0, bump - 0.08),
            decision_code="cpu_cautious_raise",
            non_tender=False,
        )
    return ArbitrationDecision(
        applied_bump=min(max_raise_pct, bump),
        decision_code="cpu_standard",
        non_tender=False,
    )


def estimate_free_agent_salary_band(
    team_strategy: TeamFinanceStrategy | None,
    *,
    ai_level: str,
) -> tuple[float, float]:
    """Return min/max salary multipliers for CPU free-agency offers."""

    level = str(ai_level or "").strip().lower()
    if level == AI_LEVEL_OFF:
        return (0.75, 1.10)
    if team_strategy is None:
        return (0.70, 1.15)

    profile = team_strategy.profile
    tone = team_strategy.budget_tone
    if profile == PROFILE_CONTEND:
        if tone == _BUDGET_AGGRESSIVE:
            return (0.90, 1.28)
        if tone == _BUDGET_CAUTIOUS:
            return (0.75, 1.08)
        return (0.85, 1.20)
    if profile == PROFILE_REBUILD:
        if tone == _BUDGET_CAUTIOUS:
            return (0.55, 0.92)
        return (0.62, 1.00)
    if tone == _BUDGET_AGGRESSIVE:
        return (0.80, 1.18)
    if tone == _BUDGET_CAUTIOUS:
        return (0.65, 1.00)
    return (0.72, 1.10)


def build_cpu_free_agent_bid_book(
    player: object,
    teams: list[object] | tuple[object, ...],
    *,
    ai_level: str,
    data_dir: Path | str | None = None,
    rng: random.Random | None = None,
) -> Dict[str, int]:
    """Build strategy-aware salary offers for CPU teams."""

    level = str(ai_level or "").strip().lower()
    if level not in {AI_LEVEL_BASIC, AI_LEVEL_ADVANCED}:
        return {}

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
    )
    if (not settings.enabled) or settings.module_level("gm_free_agency") == AI_LEVEL_OFF:
        return {}

    strategy_map = load_team_finance_strategies(data_dir=resolved_data_dir)
    generator = rng if rng is not None else random.Random()
    ask_salary = max(DEFAULT_MIN_SALARY, estimate_salary_for_player(player))
    player_quality = _free_agent_quality_score(player)
    tuning_map = _merge_tuning(settings.finance_ai_tuning)
    fa_star_quality_threshold = _tuning_int(tuning_map, "fa_star_quality_threshold")

    bids: Dict[str, int] = {}
    for team in teams:
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id or not _is_cpu_team(team):
            continue
        strategy = strategy_map.get(team_id)
        raw_strategy_profile = _raw_strategy_profile(strategy)
        fit_score = _strategy_fit_score(player, raw_strategy_profile=raw_strategy_profile)
        if not _strategy_profile_accepts_player(
            player,
            raw_strategy_profile=raw_strategy_profile,
            fit_score=fit_score,
            player_quality=player_quality,
            fa_star_quality_threshold=fa_star_quality_threshold,
        ):
            continue
        if not _should_submit_bid(
            strategy,
            ask_salary=ask_salary,
            player_quality=player_quality,
            tuning=tuning_map,
        ):
            continue
        low_mul, high_mul = estimate_free_agent_salary_band(
            strategy,
            ai_level=level,
        )
        fit_adjust = (fit_score - 0.5) * 0.24
        low_mul = max(0.45, low_mul + (fit_adjust * 0.60))
        high_mul = max(low_mul, high_mul + fit_adjust)
        if (
            strategy is not None
            and strategy.profile == PROFILE_CONTEND
            and player_quality >= fa_star_quality_threshold
        ):
            high_mul += 0.06
        if strategy is not None and strategy.profile == PROFILE_REBUILD and player_quality < 72:
            low_mul = max(0.50, low_mul - 0.05)
            high_mul = max(low_mul, high_mul - 0.04)

        min_offer = max(DEFAULT_MIN_SALARY, int(round(ask_salary * low_mul)))
        max_offer = max(min_offer, int(round(ask_salary * high_mul)))
        if strategy is not None:
            cap_target = _team_payroll_cap_target(
                strategy,
                tuning=tuning_map,
            )
            if strategy.annual_payroll + min_offer > cap_target:
                if strategy.profile == PROFILE_CONTEND and player_quality >= 80:
                    max_offer = min(max_offer, max(DEFAULT_MIN_SALARY, cap_target - strategy.annual_payroll + 2_000_000))
                    min_offer = min(min_offer, max_offer)
                else:
                    continue

        offer = int(generator.randint(min_offer, max_offer))
        bids[team_id] = max(DEFAULT_MIN_SALARY, offer)

    return bids


def _load_standings(data_dir: Path) -> Dict[str, Mapping[str, object]]:
    invalidate_standings(base_path=data_dir)
    payload = load_standings(base_path=data_dir, normalize=False)
    if not isinstance(payload, Mapping):
        return {}
    standings: Dict[str, Mapping[str, object]] = {}
    for team_id, value in payload.items():
        key = str(team_id or "").strip()
        if not key or not isinstance(value, Mapping):
            continue
        standings[key] = value
    return standings


def _load_team_financials(data_dir: Path) -> Dict[str, object]:
    path = data_dir / "team_financials.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _win_pct(record: object) -> float:
    row = record if isinstance(record, Mapping) else {}
    wins = _safe_int(row.get("wins"), fallback=0)
    losses = _safe_int(row.get("losses"), fallback=0)
    games = wins + losses
    if games <= 0:
        return 0.5
    return max(0.0, min(1.0, float(wins) / float(games)))


def _resolve_profile(
    win_pct: float,
    *,
    cash_on_hand: int,
    debt: int,
    projected_net: int,
) -> str:
    profile = PROFILE_BALANCED
    if win_pct >= 0.565:
        profile = PROFILE_CONTEND
    elif win_pct <= 0.445:
        profile = PROFILE_REBUILD

    liquidity = cash_on_hand - debt
    if liquidity < -4_000_000 and projected_net < -150_000:
        if profile == PROFILE_CONTEND:
            return PROFILE_BALANCED
        return PROFILE_REBUILD
    if liquidity > 8_000_000 and projected_net > 150_000:
        if profile == PROFILE_BALANCED and win_pct >= 0.520:
            return PROFILE_CONTEND
    return profile


def _resolve_budget_tone(
    *,
    cash_on_hand: int,
    debt: int,
    projected_net: int,
) -> str:
    liquidity = cash_on_hand - debt
    if liquidity < -2_000_000 or projected_net < -150_000:
        return _BUDGET_CAUTIOUS
    if liquidity > 8_000_000 and projected_net > 200_000:
        return _BUDGET_AGGRESSIVE
    return _BUDGET_NEUTRAL


def _is_cpu_team(team: object) -> bool:
    owner = str(getattr(team, "owner_id", "") or "").strip().lower()
    return owner in {"", "cpu", "ai", "none", "computer", "bot"}


def _free_agent_quality_score(player: object) -> int:
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).strip().upper() == "P"
    if is_pitcher:
        values = [
            _safe_int(getattr(player, "arm", 0), fallback=0),
            _safe_int(getattr(player, "control", 0), fallback=0),
            _safe_int(getattr(player, "movement", 0), fallback=0),
            _safe_int(getattr(player, "endurance", 0), fallback=0),
        ]
    else:
        values = [
            _safe_int(getattr(player, "ch", 0), fallback=0),
            _safe_int(getattr(player, "ph", 0), fallback=0),
            _safe_int(getattr(player, "sp", 0), fallback=0),
            _safe_int(getattr(player, "eye", 0), fallback=0),
            _safe_int(getattr(player, "fa", 0), fallback=0),
            _safe_int(getattr(player, "arm", 0), fallback=0),
        ]
    values = [value for value in values if value > 0]
    if not values:
        return 60
    return max(20, min(95, int(round(sum(values) / len(values)))))


def _raw_strategy_profile(strategy: TeamFinanceStrategy | None) -> str:
    if strategy is None:
        return "balanced"
    token = str(strategy.raw_strategy_profile or "").strip().lower()
    if token in {
        "balanced",
        "win_now",
        "development_focus",
        "defense_first",
        "power_offense",
    }:
        return token
    return "balanced"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _norm_rating(value: object) -> float:
    return _clamp01(float(_safe_int(value, fallback=0)) / 99.0)


def _player_age_years(player: object) -> int | None:
    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if not birthdate:
        return None
    token = birthdate.split("T", 1)[0]
    try:
        born = date.fromisoformat(token)
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _strategy_fit_score(player: object, *, raw_strategy_profile: str) -> float:
    profile = str(raw_strategy_profile or "balanced").strip().lower()
    if profile == "balanced":
        return 0.5

    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).strip().upper() == "P"
    age = _player_age_years(player)
    youth = 0.0 if age is None else _clamp01(float(28 - age) / 10.0)
    veteran = 0.0 if age is None else _clamp01(float(age - 24) / 10.0)

    if is_pitcher:
        arm = _norm_rating(getattr(player, "arm", getattr(player, "fb", 0)))
        control = _norm_rating(getattr(player, "control", 0))
        movement = _norm_rating(getattr(player, "movement", 0))
        endurance = _norm_rating(getattr(player, "endurance", 0))
        hold = _norm_rating(getattr(player, "hold_runner", 0))
        if profile == "win_now":
            return _clamp01(
                (1.3 * control + 1.2 * movement + 0.8 * endurance + 0.5 * veteran)
                / 3.8
            )
        if profile == "development_focus":
            return _clamp01((1.2 * arm + 0.9 * control + 0.7 * movement + 0.9 * youth) / 3.7)
        if profile == "defense_first":
            return _clamp01((1.5 * control + 1.4 * movement + 1.0 * hold + 0.5 * endurance) / 4.4)
        if profile == "power_offense":
            return _clamp01((1.4 * arm + 1.0 * movement + 0.8 * endurance + 0.4 * veteran) / 3.6)
        return 0.5

    ch = _norm_rating(getattr(player, "ch", 0))
    ph = _norm_rating(getattr(player, "ph", 0))
    sp = _norm_rating(getattr(player, "sp", 0))
    eye = _norm_rating(getattr(player, "eye", 0))
    fa = _norm_rating(getattr(player, "fa", 0))
    arm = _norm_rating(getattr(player, "arm", 0))
    gf = _norm_rating(getattr(player, "gf", 0))
    if profile == "win_now":
        return _clamp01((1.2 * ch + 1.1 * ph + 0.9 * eye + 0.7 * fa + 0.5 * veteran) / 4.4)
    if profile == "development_focus":
        return _clamp01((1.0 * sp + 0.9 * ch + 0.8 * eye + 0.8 * fa + 0.9 * youth) / 4.4)
    if profile == "defense_first":
        return _clamp01((1.5 * fa + 1.1 * arm + 1.0 * gf + 0.5 * sp + 0.3 * ch) / 4.4)
    if profile == "power_offense":
        return _clamp01((1.6 * ph + 1.0 * ch + 0.7 * eye + 0.5 * sp + 0.3 * veteran) / 4.1)
    return 0.5


def _strategy_profile_accepts_player(
    player: object,
    *,
    raw_strategy_profile: str,
    fit_score: float,
    player_quality: int,
    fa_star_quality_threshold: int,
) -> bool:
    profile = str(raw_strategy_profile or "balanced").strip().lower()
    if profile == "balanced":
        return True
    if player_quality >= (fa_star_quality_threshold + 6):
        return True

    age = _player_age_years(player)
    if profile == "development_focus":
        if age is not None and age >= 31 and player_quality < (fa_star_quality_threshold + 2):
            return False
        return fit_score >= 0.34
    if profile == "win_now":
        if age is not None and age <= 22 and player_quality < (fa_star_quality_threshold + 3):
            return False
        return fit_score >= 0.38
    if profile == "defense_first":
        return fit_score >= 0.40
    if profile == "power_offense":
        return fit_score >= 0.40
    return True


def _should_submit_bid(
    strategy: TeamFinanceStrategy | None,
    *,
    ask_salary: int,
    player_quality: int,
    tuning: Mapping[str, object] | None = None,
) -> bool:
    tuning_map = _merge_tuning(tuning)
    rebuild_avoid_salary = _tuning_int(tuning_map, "fa_rebuild_avoid_salary")
    cautious_avoid_salary = _tuning_int(tuning_map, "fa_cautious_avoid_salary")
    hard_avoid_salary = _tuning_int(tuning_map, "fa_hard_avoid_salary")
    fa_star_quality_threshold = _tuning_int(tuning_map, "fa_star_quality_threshold")
    future_year_commitment_ratio_limit = _tuning_float(
        tuning_map,
        "future_year_commitment_ratio_limit",
    )
    future_year_hard_commitment_ratio_limit = _tuning_float(
        tuning_map,
        "future_year_hard_commitment_ratio_limit",
    )
    if strategy is None:
        return ask_salary <= 12_000_000
    cap_target = _team_payroll_cap_target(strategy, tuning=tuning_map)
    ratio = 0.0
    if cap_target > 0:
        ratio = float(strategy.next_year_commitment + ask_salary) / float(cap_target)
    if ratio >= future_year_hard_commitment_ratio_limit:
        return False
    if (
        ratio >= future_year_commitment_ratio_limit
        and strategy.profile != PROFILE_CONTEND
    ):
        return False
    if strategy.profile == PROFILE_REBUILD:
        if ask_salary >= rebuild_avoid_salary and player_quality < (fa_star_quality_threshold + 4):
            return False
        if strategy.budget_tone == _BUDGET_CAUTIOUS and ask_salary >= cautious_avoid_salary:
            return False
    if (
        strategy.budget_tone == _BUDGET_CAUTIOUS
        and ask_salary >= hard_avoid_salary
        and player_quality < (fa_star_quality_threshold + 10)
    ):
        return False
    return True


def _team_payroll_cap_target(
    strategy: TeamFinanceStrategy,
    *,
    tuning: Mapping[str, object] | None = None,
) -> int:
    if strategy.profile == PROFILE_CONTEND:
        target = 225_000_000
    elif strategy.profile == PROFILE_REBUILD:
        target = 155_000_000
    else:
        target = 185_000_000
    if strategy.budget_tone == _BUDGET_AGGRESSIVE:
        target += 18_000_000
    elif strategy.budget_tone == _BUDGET_CAUTIOUS:
        target -= 16_000_000
    tuning_map = _merge_tuning(tuning)
    commitment_pressure_ratio = _tuning_float(tuning_map, "commitment_pressure_ratio")
    commitment_relief_ratio = _tuning_float(tuning_map, "commitment_relief_ratio")
    commitment_pressure_penalty = _tuning_int(tuning_map, "commitment_pressure_penalty")
    commitment_relief_bonus = _tuning_int(tuning_map, "commitment_relief_bonus")
    next_year_ratio = 0.0
    if target > 0:
        next_year_ratio = float(strategy.next_year_commitment) / float(target)
    if next_year_ratio >= commitment_pressure_ratio:
        target -= commitment_pressure_penalty
    elif next_year_ratio <= commitment_relief_ratio:
        target += commitment_relief_bonus
    return max(90_000_000, target)


def _load_multi_year_commitments(data_dir: Path) -> Dict[str, Dict[str, int]]:
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, Mapping):
        return {}
    commitments: Dict[str, Dict[str, int]] = {}
    for raw in players.values():
        if not isinstance(raw, Mapping):
            continue
        team_id = str(raw.get("team_id") or "").strip()
        if not team_id:
            continue
        years_left = max(1, _safe_int(raw.get("years_left"), fallback=1))
        annual_value = max(
            DEFAULT_MIN_SALARY,
            _safe_int(contract_payroll_value(raw), fallback=DEFAULT_MIN_SALARY),
        )
        bucket = commitments.setdefault(
            team_id,
            {
                "next_year": 0,
                "two_year": 0,
            },
        )
        if years_left >= 2:
            bucket["next_year"] += annual_value
        if years_left >= 3:
            bucket["two_year"] += annual_value
    return commitments


def _safe_int(value: object, *, fallback: int) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return fallback


def _merge_tuning(raw: Mapping[str, object] | None) -> Dict[str, object]:
    tuning = dict(DEFAULT_FINANCE_AI_TUNING)
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if key in tuning:
                tuning[key] = value
    return tuning


def _tuning_int(tuning: Mapping[str, object], key: str) -> int:
    value = tuning.get(key, DEFAULT_FINANCE_AI_TUNING.get(key, 0))
    try:
        return int(round(float(value)))
    except Exception:
        return int(DEFAULT_FINANCE_AI_TUNING.get(key, 0))


def _tuning_float(tuning: Mapping[str, object], key: str) -> float:
    value = tuning.get(key, DEFAULT_FINANCE_AI_TUNING.get(key, 0.0))
    try:
        return float(value)
    except Exception:
        return float(DEFAULT_FINANCE_AI_TUNING.get(key, 0.0))
