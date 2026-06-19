"""Payroll policy checks for signings and trade execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Dict, Mapping

from services.contracts_service import (
    DEFAULT_MIN_SALARY,
    estimate_salary_for_player,
    load_contracts_payload,
)
from services.finance_settings import (
    ENFORCEMENT_BLOCK,
    ENFORCEMENT_OFF,
    ENFORCEMENT_ON,
    ENFORCEMENT_WARN,
    FinancialSettings,
    LEVEL_BASIC,
    LEVEL_MLB_LIKE,
    PRESET_MLB_LIKE,
    PRESET_SIMPLE,
    PRESET_STANDARD,
    TEAM_FINANCIALS_FILENAME,
    PRESET_OFF,
    load_financial_settings,
)
from services.finance_ledger import (
    CATEGORY_FINANCE_CYCLE,
    LEDGER_TEAM_SYSTEM,
    append_financial_rows,
    build_finance_cycle_marker_row,
    ledger_has_entry,
    post_payroll_policy_event,
    post_team_expense,
)
from services.payroll_engine import calculate_annual_payroll_totals
from services.owner_finance_engine import project_monthly_owner_finance
from utils.path_utils import get_data_dir

__all__ = [
    "PayrollPolicyResult",
    "evaluate_free_agent_signing",
    "evaluate_payroll_delta",
    "evaluate_trade_payroll_impact",
    "evaluate_opening_day_payroll",
    "build_payroll_limit_context",
    "format_payroll_policy_message",
    "estimate_mlb_like_cbt_tax",
    "record_payroll_policy_result",
    "apply_payroll_rule_accounting_effects",
]

_BASIC_FALLBACK_MAX = 120_000_000
_MLB_LIKE_FALLBACK_MAX = 220_000_000
_MLB_LIKE_FALLBACK_MIN = 90_000_000
_BASIC_REVENUE_RATIO = 0.65
_MLB_LIKE_REVENUE_RATIO = 0.80
_MLB_LIKE_FLOOR_REVENUE_RATIO = 0.35
_MLB_CBT_TIERS: tuple[tuple[int, float], ...] = (
    (20_000_000, 0.20),
    (20_000_000, 0.32),
    (20_000_000, 0.625),
)
_BASIC_OVERAGE_FEE_RATE = 0.05
_MLB_LIKE_FLOOR_FEE_RATE = 0.25
_PAYROLL_ACCOUNTING_MARKER_PREFIX = "payroll_accounting"
_VIOLATION_MAX = "max"
_VIOLATION_MIN = "min"
_VIOLATION_DEBT = "debt"
_DEBT_CAP_BY_PRESET: dict[str, int] = {
    PRESET_SIMPLE: 25_000_000,
    PRESET_STANDARD: 80_000_000,
    PRESET_MLB_LIKE: 150_000_000,
}


@dataclass(frozen=True)
class PayrollPolicyResult:
    allowed: bool
    warning: bool
    mode: str
    level: str
    violations: Dict[str, Dict[str, object]]


def estimate_mlb_like_cbt_tax(projected: int, threshold: int) -> int:
    """Return estimated CBT tax for a payroll overage at MLB-like level."""

    over = max(0, int(projected) - int(threshold))
    if over <= 0:
        return 0
    remaining = over
    tax_total = 0.0
    for band_size, rate in _MLB_CBT_TIERS:
        if remaining <= 0:
            break
        taxable = min(remaining, band_size)
        tax_total += float(taxable) * float(rate)
        remaining -= taxable
    if remaining > 0:
        tax_total += float(remaining) * 0.95
    return int(round(tax_total))


def evaluate_free_agent_signing(
    team_id: str,
    *,
    annual_salary: int | None = None,
    player: object | None = None,
    data_dir=None,
    league_id: str | None = None,
) -> PayrollPolicyResult:
    """Evaluate payroll impact for signing one free agent to *team_id*."""

    salary = annual_salary
    if salary is None:
        salary = estimate_salary_for_player(player)
    salary = max(DEFAULT_MIN_SALARY, int(salary))
    return _evaluate_policy(
        team_deltas={str(team_id or "").strip(): salary},
        data_dir=data_dir,
        league_id=league_id,
    )


def evaluate_payroll_delta(
    team_id: str,
    *,
    annual_delta: int,
    data_dir=None,
    league_id: str | None = None,
    annual_totals: Mapping[str, int] | None = None,
    monthly_projection: Mapping[str, object] | None = None,
) -> PayrollPolicyResult:
    """Evaluate payroll-policy impact for a direct annual payroll delta."""

    return _evaluate_policy(
        team_deltas={str(team_id or "").strip(): int(annual_delta or 0)},
        data_dir=data_dir,
        league_id=league_id,
        annual_totals=annual_totals,
        monthly_projection=monthly_projection,
    )


def evaluate_trade_payroll_impact(
    trade: object,
    *,
    players_by_id: Mapping[str, object] | None = None,
    data_dir=None,
    league_id: str | None = None,
) -> PayrollPolicyResult:
    """Evaluate payroll impact for a trade execution."""

    from_team = str(getattr(trade, "from_team", "") or "").strip()
    to_team = str(getattr(trade, "to_team", "") or "").strip()
    if not from_team or not to_team:
        return PayrollPolicyResult(
            allowed=True,
            warning=False,
            mode="off",
            level="off",
            violations={},
        )

    payload = load_contracts_payload(data_dir=data_dir)
    contracts = payload.get("players")
    players = contracts if isinstance(contracts, Mapping) else {}
    source_players = players_by_id if isinstance(players_by_id, Mapping) else {}

    give_ids = [str(pid or "").strip() for pid in getattr(trade, "give_player_ids", []) or []]
    recv_ids = [str(pid or "").strip() for pid in getattr(trade, "receive_player_ids", []) or []]

    outgoing_from = _sum_salaries(give_ids, players, source_players)
    incoming_from = _sum_salaries(recv_ids, players, source_players)
    delta_from = incoming_from - outgoing_from
    delta_to = -delta_from

    return _evaluate_policy(
        team_deltas={
            from_team: delta_from,
            to_team: delta_to,
        },
        data_dir=data_dir,
        league_id=league_id,
    )


def evaluate_opening_day_payroll(
    team_id: str,
    *,
    data_dir=None,
    league_id: str | None = None,
) -> PayrollPolicyResult:
    """Hard Opening-Day solvency check for a team's current commitments.

    Being over the luxury threshold is fine (it's taxed); this blocks only when
    the team would start the season insolvent — projected debt over its cap.
    Returns allowed=True when enforcement is off or the team is solvent.
    """

    return _evaluate_policy(
        team_deltas={str(team_id or "").strip(): 0},
        data_dir=data_dir,
        league_id=league_id,
        deadline=True,
    )


def build_payroll_limit_context(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    annual_totals: Mapping[str, int] | None = None,
    monthly_projection: Mapping[str, object] | None = None,
) -> Dict[str, object]:
    """Return per-team payroll threshold/floor context for commissioner reporting."""

    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    level = settings.module_level("gm_payroll_rules")
    totals = (
        dict(annual_totals)
        if isinstance(annual_totals, Mapping)
        else calculate_annual_payroll_totals(data_dir=resolved_data_dir)
    )
    projections = (
        dict(monthly_projection)
        if isinstance(monthly_projection, Mapping)
        else project_monthly_owner_finance(data_dir=resolved_data_dir)
    )
    team_ids = set(str(team_id).strip() for team_id in totals.keys())
    team_ids.update(str(team_id).strip() for team_id in projections.keys())
    team_ids.discard("")

    rows: Dict[str, Dict[str, int | float]] = {}
    for team_id in sorted(team_ids):
        payroll = max(0, int(totals.get(team_id, 0) or 0))
        threshold = _payroll_threshold(team_id, level, projections)
        floor = _payroll_floor(team_id, level, projections)
        over = max(0, payroll - threshold)
        under = max(0, floor - payroll)
        threshold_ratio = 0.0
        floor_ratio = 0.0
        if threshold > 0:
            threshold_ratio = float(payroll) / float(threshold)
        if floor > 0:
            floor_ratio = float(payroll) / float(floor)
        rows[team_id] = {
            "payroll": payroll,
            "threshold": threshold,
            "floor": floor,
            "over_threshold": over,
            "under_floor": under,
            "threshold_ratio": threshold_ratio,
            "floor_ratio": floor_ratio,
        }

    return {
        "enabled": bool(settings.enabled),
        "preset": settings.preset,
        "level": level,
        "teams": rows,
    }


def format_payroll_policy_message(result: PayrollPolicyResult) -> str:
    """Render a user-facing summary of payroll policy checks."""

    if not result.violations:
        return "Payroll policy check passed."
    lines = []
    if not result.allowed:
        lines.append(
            "Payroll policy blocked this action — the team must be solvent at Opening Day."
        )
    else:
        lines.append(
            "Payroll is over the luxury threshold — the tax will apply at settlement."
        )
    lines.append("")
    for team_id, details in result.violations.items():
        kind = str(details.get("kind") or _VIOLATION_MAX)
        if kind == _VIOLATION_MIN:
            lines.append(
                (
                    f"{team_id}: projected payroll ${details['projected']:,} "
                    f"(min ${details['threshold']:,}, under by ${details['under']:,})"
                )
            )
            continue
        if kind == _VIOLATION_DEBT:
            lines.append(
                (
                    f"{team_id}: projected debt ${details['projected']:,} "
                    f"(cap ${details['threshold']:,}, over by ${details['over']:,})"
                )
            )
            continue
        tax = int(details.get("estimated_tax", 0) or 0)
        suffix = f", est. CBT tax ${tax:,}" if tax > 0 else ""
        lines.append(
            (
                f"{team_id}: projected payroll ${details['projected']:,} "
                f"(max ${details['threshold']:,}, over by ${details['over']:,}{suffix})"
            )
        )
    return "\n".join(lines)


def record_payroll_policy_result(
    result: PayrollPolicyResult,
    *,
    action: str,
    data_dir: Path | str | None = None,
    season_year: int | None = None,
) -> int:
    """Persist payroll-policy warning/block audit rows."""

    if not result.violations:
        return 0
    # "blocked" = a hard deadline failure (insolvency). "over_limit" = allowed
    # in-season but over the luxury threshold / under the floor, which settles
    # economically (tax / floor fee) rather than blocking.
    outcome = "blocked" if not result.allowed else "over_limit"
    written = 0
    for team_id, details in result.violations.items():
        projected = int(details.get("projected", 0) or 0)
        threshold = int(details.get("threshold", 0) or 0)
        if projected <= 0 and threshold <= 0:
            continue
        if post_payroll_policy_event(
            team_id=str(team_id or "").strip(),
            season_year=season_year,
            action=action,
            outcome=outcome,
            kind=str(details.get("kind") or _VIOLATION_MAX),
            projected=projected,
            threshold=threshold,
            delta=int(details.get("delta", 0) or 0),
            over=int(details.get("over", 0) or 0),
            under=int(details.get("under", 0) or 0),
            estimated_tax=int(details.get("estimated_tax", 0) or 0),
            data_dir=data_dir,
        ):
            written += 1
    return written


def apply_payroll_rule_accounting_effects(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    season_year: int | None = None,
) -> Dict[str, object]:
    """Apply deterministic payroll-rule accounting effects and persist ledger rows."""

    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    level = settings.module_level("gm_payroll_rules")
    if (not settings.enabled) or settings.preset == PRESET_OFF or level not in {LEVEL_BASIC, LEVEL_MLB_LIKE}:
        return {
            "applied": False,
            "level": level,
            "teams_evaluated": 0,
            "teams_penalized": 0,
            "tax_total": 0,
            "floor_fee_total": 0,
            "details": [],
        }

    projections = project_monthly_owner_finance(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    annual_totals = calculate_annual_payroll_totals(data_dir=resolved_data_dir)
    payload = _load_team_financials_payload(resolved_data_dir / TEAM_FINANCIALS_FILENAME)
    teams_payload = payload.get("teams")
    teams_map = teams_payload if isinstance(teams_payload, Mapping) else {}
    team_ids = sorted(
        set(str(team_id).strip() for team_id in annual_totals.keys())
        | set(str(team_id).strip() for team_id in teams_map.keys())
    )
    season_token = int(season_year) if season_year is not None else _safe_int(
        payload.get("season_year", 0)
    )
    if season_token <= 0:
        season_token = 0
    changed_financials = False
    teams_penalized = 0
    tax_total = 0
    floor_fee_total = 0
    details: list[Dict[str, object]] = []

    for team_id in team_ids:
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            continue
        marker = f"{_PAYROLL_ACCOUNTING_MARKER_PREFIX}:{season_token}:{clean_team_id}:{level}"
        if ledger_has_entry(
            team_id=LEDGER_TEAM_SYSTEM,
            category=CATEGORY_FINANCE_CYCLE,
            memo=marker,
            data_dir=resolved_data_dir,
        ):
            details.append(
                {
                    "team_id": clean_team_id,
                    "payroll": int(annual_totals.get(clean_team_id, 0) or 0),
                    "threshold": 0,
                    "floor": 0,
                    "tax_penalty": 0,
                    "floor_fee": 0,
                    "applied": False,
                    "skipped": "already_accounted",
                }
            )
            continue

        payroll = max(0, int(annual_totals.get(clean_team_id, 0) or 0))
        threshold = _payroll_threshold(clean_team_id, level, projections)
        floor = _payroll_floor(clean_team_id, level, projections)
        over = max(0, payroll - threshold)
        under = max(0, floor - payroll) if level == LEVEL_MLB_LIKE else 0

        tax_penalty = 0
        floor_fee = 0
        if over > 0:
            if level == LEVEL_MLB_LIKE:
                tax_penalty = estimate_mlb_like_cbt_tax(payroll, threshold)
            else:
                tax_penalty = int(round(float(over) * _BASIC_OVERAGE_FEE_RATE))
        if level == LEVEL_MLB_LIKE and under > 0:
            floor_fee = int(round(float(under) * _MLB_LIKE_FLOOR_FEE_RATE))

        applied = False
        if tax_penalty > 0:
            applied = True
            tax_total += tax_penalty
            teams_penalized += 1
            overage_expense_type = (
                "payroll_tax"
                if level == LEVEL_MLB_LIKE
                else "payroll_overage_fee"
            )
            overage_outcome = (
                "applied_tax"
                if level == LEVEL_MLB_LIKE
                else "applied_overage_fee"
            )
            changed_financials = _apply_team_penalty_to_financials(
                payload=payload,
                team_id=clean_team_id,
                amount=tax_penalty,
            ) or changed_financials
            post_team_expense(
                team_id=clean_team_id,
                season_year=season_token,
                expense_type=overage_expense_type,
                amount=tax_penalty,
                memo=f"Payroll over threshold accounting ({season_token})",
                data_dir=resolved_data_dir,
            )
            post_payroll_policy_event(
                team_id=clean_team_id,
                season_year=season_token,
                action="season_payroll_accounting",
                outcome=overage_outcome,
                kind=_VIOLATION_MAX,
                projected=payroll,
                threshold=threshold,
                delta=0,
                over=over,
                under=0,
                estimated_tax=tax_penalty if level == LEVEL_MLB_LIKE else 0,
                data_dir=resolved_data_dir,
            )

        if floor_fee > 0:
            applied = True
            floor_fee_total += floor_fee
            if tax_penalty <= 0:
                teams_penalized += 1
            changed_financials = _apply_team_penalty_to_financials(
                payload=payload,
                team_id=clean_team_id,
                amount=floor_fee,
            ) or changed_financials
            post_team_expense(
                team_id=clean_team_id,
                season_year=season_token,
                expense_type="payroll_floor_fee",
                amount=floor_fee,
                memo=f"Payroll floor shortfall fee ({season_token})",
                data_dir=resolved_data_dir,
            )
            post_payroll_policy_event(
                team_id=clean_team_id,
                season_year=season_token,
                action="season_payroll_accounting",
                outcome="applied_floor_fee",
                kind=_VIOLATION_MIN,
                projected=payroll,
                threshold=floor,
                delta=0,
                over=0,
                under=under,
                estimated_tax=0,
                data_dir=resolved_data_dir,
            )

        marker_row = build_finance_cycle_marker_row(
            season_year=season_token,
            period_key=marker,
        )
        if marker_row is not None:
            append_financial_rows([marker_row], data_dir=resolved_data_dir)

        details.append(
            {
                "team_id": clean_team_id,
                "payroll": payroll,
                "threshold": threshold,
                "floor": floor,
                "tax_penalty": tax_penalty,
                "floor_fee": floor_fee,
                "applied": applied,
            }
        )

    if changed_financials:
        _save_team_financials_payload(
            resolved_data_dir / TEAM_FINANCIALS_FILENAME,
            payload,
        )

    return {
        "applied": teams_penalized > 0,
        "level": level,
        "teams_evaluated": len([team_id for team_id in team_ids if str(team_id or "").strip()]),
        "teams_penalized": teams_penalized,
        "tax_total": tax_total,
        "floor_fee_total": floor_fee_total,
        "details": details,
    }


def _evaluate_policy(
    *,
    team_deltas: Mapping[str, int],
    data_dir=None,
    league_id: str | None = None,
    annual_totals: Mapping[str, int] | None = None,
    monthly_projection: Mapping[str, object] | None = None,
    deadline: bool = False,
) -> PayrollPolicyResult:
    """Evaluate a payroll change against the league's financial rules.

    Hybrid enforcement (7.0+):
    - During the season (``deadline=False``) nothing is blocked — going over the
      luxury threshold / under the floor / into debt is allowed and settles
      economically (tax, floor fee, accruing debt). The returned ``violations``
      are informational (for notifications/UI).
    - At a hard deadline (``deadline=True``, i.e. Opening Day) the action is
      blocked only if the team would be **insolvent** (projected debt over its
      cap). Exceeding the luxury threshold is still allowed (it's taxed).
    """
    settings_path = None
    if data_dir is not None:
        settings_path = Path(data_dir) / "league_financial_settings.json"
    settings = load_financial_settings(league_id=league_id, path=settings_path)
    mode = _enforcement_mode(settings)
    level = settings.module_level("gm_payroll_rules")
    if not settings.enabled or settings.preset == PRESET_OFF:
        return PayrollPolicyResult(True, False, mode, level, {})
    if level not in {LEVEL_BASIC, LEVEL_MLB_LIKE}:
        return PayrollPolicyResult(True, False, mode, level, {})
    if mode != ENFORCEMENT_ON:
        return PayrollPolicyResult(True, False, mode, level, {})

    resolved_annual_totals = (
        dict(annual_totals)
        if isinstance(annual_totals, Mapping)
        else calculate_annual_payroll_totals(data_dir=data_dir)
    )
    resolved_monthly_projection = (
        dict(monthly_projection)
        if isinstance(monthly_projection, Mapping)
        else project_monthly_owner_finance(
            data_dir=data_dir,
            league_id=league_id,
        )
    )
    financial_map = _load_team_financial_map(data_dir=data_dir)
    debt_cap = _debt_cap_for_preset(settings.preset)

    violations: Dict[str, Dict[str, int]] = {}
    for raw_team_id, raw_delta in team_deltas.items():
        team_id = str(raw_team_id or "").strip()
        if not team_id:
            continue
        delta = int(raw_delta or 0)
        current = int(resolved_annual_totals.get(team_id, 0))
        projected = current + delta
        threshold = _payroll_threshold(team_id, level, resolved_monthly_projection)
        floor = _payroll_floor(team_id, level, resolved_monthly_projection)
        if level == LEVEL_MLB_LIKE and projected < floor and delta < 0:
            violations[team_id] = {
                "kind": _VIOLATION_MIN,
                "current": current,
                "projected": projected,
                "threshold": floor,
                "delta": delta,
                "under": floor - projected,
            }
            continue
        if projected > threshold:
            estimated_tax = (
                estimate_mlb_like_cbt_tax(projected, threshold)
                if level == LEVEL_MLB_LIKE
                else 0
            )
            violations[team_id] = {
                "kind": _VIOLATION_MAX,
                "current": current,
                "projected": projected,
                "threshold": threshold,
                "delta": delta,
                "over": projected - threshold,
                "estimated_tax": estimated_tax,
            }
            continue

        projected_debt = _projected_debt_after_delta(
            team_id=team_id,
            annual_delta=delta,
            team_financial_map=financial_map,
        )
        if projected_debt > debt_cap:
            violations[team_id] = {
                "kind": _VIOLATION_DEBT,
                "current": int(_safe_int(financial_map.get(team_id, {}).get("debt", 0))),
                "projected": projected_debt,
                "threshold": debt_cap,
                "delta": delta,
                "over": projected_debt - debt_cap,
            }

    if not violations:
        return PayrollPolicyResult(True, False, mode, level, {})
    # Only a hard deadline (Opening Day) blocks, and only on insolvency
    # (projected debt over cap). Luxury-threshold / floor violations are
    # economic — they never block, just tax/fee at settlement.
    blocking = deadline and any(
        str(v.get("kind")) == _VIOLATION_DEBT for v in violations.values()
    )
    return PayrollPolicyResult(not blocking, False, mode, level, violations)


def _enforcement_mode(settings: FinancialSettings) -> str:
    """Return the binary enforcement state: ENFORCEMENT_ON or ENFORCEMENT_OFF.

    Legacy warn/block normalize to "on"; the warn-vs-block distinction is gone.
    """
    token = settings.module_level("gm_roster_cost_enforcement")
    if token in {ENFORCEMENT_ON, ENFORCEMENT_WARN, ENFORCEMENT_BLOCK}:
        return ENFORCEMENT_ON
    if token == ENFORCEMENT_OFF:
        return ENFORCEMENT_OFF
    legacy = str(getattr(settings, "enforcement_mode", "") or "").strip().lower()
    if legacy in {ENFORCEMENT_ON, ENFORCEMENT_WARN, ENFORCEMENT_BLOCK}:
        return ENFORCEMENT_ON
    return ENFORCEMENT_OFF


def _payroll_threshold(
    team_id: str,
    level: str,
    monthly_projection: Mapping[str, object],
) -> int:
    if level == LEVEL_MLB_LIKE:
        fallback = _MLB_LIKE_FALLBACK_MAX
        ratio = _MLB_LIKE_REVENUE_RATIO
    else:
        fallback = _BASIC_FALLBACK_MAX
        ratio = _BASIC_REVENUE_RATIO

    snapshot = monthly_projection.get(team_id)
    if snapshot is None:
        return fallback
    projected_revenue = getattr(snapshot, "projected_revenue", None)
    if not isinstance(projected_revenue, Mapping):
        return fallback
    monthly_revenue = sum(int(value or 0) for value in projected_revenue.values())
    annual_revenue = monthly_revenue * 12
    if annual_revenue <= 0:
        return fallback
    return max(fallback, int(round(annual_revenue * ratio)))


def _payroll_floor(
    team_id: str,
    level: str,
    monthly_projection: Mapping[str, object],
) -> int:
    if level != LEVEL_MLB_LIKE:
        return 0
    fallback = _MLB_LIKE_FALLBACK_MIN
    snapshot = monthly_projection.get(team_id)
    if snapshot is None:
        return fallback
    projected_revenue = getattr(snapshot, "projected_revenue", None)
    if not isinstance(projected_revenue, Mapping):
        return fallback
    monthly_revenue = sum(int(value or 0) for value in projected_revenue.values())
    annual_revenue = monthly_revenue * 12
    if annual_revenue <= 0:
        return fallback
    return max(fallback, int(round(annual_revenue * _MLB_LIKE_FLOOR_REVENUE_RATIO)))


def _debt_cap_for_preset(preset: str) -> int:
    token = str(preset or "").strip().lower()
    return int(_DEBT_CAP_BY_PRESET.get(token, _DEBT_CAP_BY_PRESET[PRESET_STANDARD]))


def _load_team_financial_map(*, data_dir: Path | str | None) -> Dict[str, Dict[str, int]]:
    if data_dir is None:
        path = get_data_dir() / TEAM_FINANCIALS_FILENAME
    else:
        path = Path(data_dir) / TEAM_FINANCIALS_FILENAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for team_id, raw in teams.items():
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            continue
        row = raw if isinstance(raw, Mapping) else {}
        out[clean_team_id] = {
            "cash_on_hand": _safe_int(row.get("cash_on_hand", 0)),
            "debt": _safe_int(row.get("debt", 0)),
        }
    return out


def _projected_debt_after_delta(
    *,
    team_id: str,
    annual_delta: int,
    team_financial_map: Mapping[str, Mapping[str, int]],
) -> int:
    row = team_financial_map.get(team_id) if isinstance(team_financial_map, Mapping) else None
    cash_on_hand = _safe_int((row or {}).get("cash_on_hand", 0))
    debt = max(0, _safe_int((row or {}).get("debt", 0)))
    delta = int(annual_delta or 0)
    if delta <= 0:
        return debt
    monthly_burden = max(DEFAULT_MIN_SALARY // 12, int(round(delta / 12.0)))
    remaining_cash = cash_on_hand - monthly_burden
    if remaining_cash >= 0:
        return debt
    return debt + abs(remaining_cash)


def _sum_salaries(
    player_ids: list[str],
    contracts: Mapping[str, object],
    players_by_id: Mapping[str, object],
) -> int:
    total = 0
    for pid in player_ids:
        if not pid:
            continue
        raw = contracts.get(pid)
        if isinstance(raw, Mapping):
            try:
                total += int(round(float(raw.get("annual_salary", DEFAULT_MIN_SALARY) or DEFAULT_MIN_SALARY)))
                continue
            except Exception:
                pass
        player = players_by_id.get(pid)
        total += estimate_salary_for_player(player)
    return total


def _load_team_financials_payload(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"version": 1, "season_year": 0, "teams": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        payload["teams"] = {}
    return payload


def _save_team_financials_payload(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")


def _apply_team_penalty_to_financials(
    *,
    payload: Dict[str, object],
    team_id: str,
    amount: int,
) -> bool:
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        teams = {}
        payload["teams"] = teams
    entry_raw = teams.get(team_id)
    entry = dict(entry_raw) if isinstance(entry_raw, Mapping) else {}
    before_cash = _safe_int(entry.get("cash_on_hand", 0))
    before_debt = max(0, _safe_int(entry.get("debt", 0)))
    expenses_raw = entry.get("expenses")
    expenses = dict(expenses_raw) if isinstance(expenses_raw, Mapping) else {}
    before_payroll_expense = _safe_int(expenses.get("payroll", 0))
    penalty = max(0, _safe_int(amount))
    if penalty <= 0:
        teams[team_id] = entry
        return False
    remaining_cash = before_cash - penalty
    if remaining_cash >= 0:
        entry["cash_on_hand"] = remaining_cash
        entry["debt"] = before_debt
    else:
        entry["cash_on_hand"] = 0
        entry["debt"] = before_debt + abs(remaining_cash)
    expenses["payroll"] = before_payroll_expense + penalty
    entry["expenses"] = expenses
    teams[team_id] = entry
    return True


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0
