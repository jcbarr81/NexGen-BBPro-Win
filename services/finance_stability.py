"""Multi-season finance stability simulation and guardrail checks."""

from __future__ import annotations

import json
from pathlib import Path
import random
import shutil
import tempfile
from typing import Dict, Mapping

from services.contracts_service import rollover_contracts_for_new_season
from services.finance_settings import (
    PRESET_STANDARD,
    apply_financial_preset,
    ensure_financial_defaults,
    load_financial_settings,
)
from services.free_agency import (
    list_unsigned_players_from_files,
    run_cpu_free_agency_market,
)
from services.offseason_finance_flow import run_offseason_financial_rollover
from services.owner_finance_engine import apply_monthly_owner_finance
from services.payroll_engine import calculate_annual_payroll_totals
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv

__all__ = [
    "DEFAULT_STABILITY_GUARDRAILS",
    "CORE_COMPARISON_PRESETS",
    "run_finance_stability_simulation",
    "run_finance_stability_preset_comparison",
    "evaluate_finance_stability_guardrails",
]


DEFAULT_STABILITY_GUARDRAILS: Dict[str, float] = {
    "max_distressed_debt_ratio": 0.60,
    "max_negative_cash_ratio": 0.65,
    "max_unsigned_ratio": 0.70,
    "max_payroll_spread_ratio": 7.00,
    "min_star_retention_rate": 0.65,
}
CORE_COMPARISON_PRESETS = ("simple", "standard", "mlb_like")


def run_finance_stability_simulation(
    *,
    seasons: int,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    preset: str | None = PRESET_STANDARD,
    seed: int | None = None,
    max_fa_rounds: int | None = None,
    guardrails: Mapping[str, float] | None = None,
    warmup_seasons: int = 0,
) -> Dict[str, object]:
    """Run multi-season finance cycles and return metrics + guardrail status."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    ensure_financial_defaults(data_dir=resolved_data_dir, league_id=league_id)
    settings_path = resolved_data_dir / "league_financial_settings.json"
    if preset:
        apply_financial_preset(preset, path=settings_path, league_id=league_id)
    settings = load_financial_settings(path=settings_path, league_id=league_id)
    effective_league_id = settings.league_id

    start_year = _resolve_year(resolved_data_dir)
    total_players = _count_players(resolved_data_dir)
    randomizer = random.Random(seed)
    season_metrics: list[Dict[str, object]] = []

    for offset in range(max(0, int(seasons))):
        season_year = start_year + offset
        monthly_summary = _apply_yearly_monthly_cycles(
            season_year=season_year,
            data_dir=resolved_data_dir,
            league_id=effective_league_id,
        )
        contract_rollover = rollover_contracts_for_new_season(
            season_year=season_year + 1,
            data_dir=resolved_data_dir,
        )
        offseason = run_offseason_financial_rollover(
            ended_season_year=season_year,
            next_season_year=season_year + 1,
            contract_rollover=contract_rollover,
            data_dir=resolved_data_dir,
            league_id=effective_league_id,
        )
        free_agency = run_cpu_free_agency_market(
            data_dir=resolved_data_dir,
            league_id=effective_league_id,
            max_rounds=max_fa_rounds,
            rng=randomizer,
        )
        metrics = _collect_season_metrics(
            season_year=season_year,
            data_dir=resolved_data_dir,
            settings=settings,
            total_players=total_players,
            monthly_summary=monthly_summary,
            offseason_summary=offseason,
            free_agency_summary=free_agency,
        )
        season_metrics.append(metrics)

    guardrail_report = evaluate_finance_stability_guardrails(
        season_metrics,
        thresholds=guardrails,
        warmup_seasons=warmup_seasons,
    )
    return {
        "league_id": effective_league_id,
        "seasons_requested": max(0, int(seasons)),
        "seasons_run": len(season_metrics),
        "start_year": start_year,
        "preset": settings.preset,
        "financials_enabled": bool(settings.enabled),
        "season_metrics": season_metrics,
        "guardrails": guardrail_report,
    }


def run_finance_stability_preset_comparison(
    *,
    seasons: int,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    presets: list[str] | tuple[str, ...] | None = None,
    seed: int | None = None,
    max_fa_rounds: int | None = None,
    guardrails: Mapping[str, float] | None = None,
) -> Dict[str, object]:
    """Run isolated stability simulations for multiple preset profiles."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    requested_presets = [str(token or "").strip().lower() for token in (presets or CORE_COMPARISON_PRESETS)]
    requested_presets = [token for token in requested_presets if token]
    if not requested_presets:
        requested_presets = list(CORE_COMPARISON_PRESETS)

    results: list[Dict[str, object]] = []
    for index, preset_token in enumerate(requested_presets):
        with tempfile.TemporaryDirectory(prefix=f"nexgen_fin_stability_{index}_") as temp_root:
            sandbox_data_dir = Path(temp_root) / "data"
            shutil.copytree(resolved_data_dir, sandbox_data_dir, dirs_exist_ok=True)
            preset_arg: str | None
            if preset_token in {"current", "__current__", "current_preset"}:
                preset_arg = None
                settings = load_financial_settings(
                    path=sandbox_data_dir / "league_financial_settings.json",
                    league_id=league_id,
                )
                effective_preset = settings.preset
            else:
                preset_arg = preset_token
                effective_preset = preset_token

            run_result = run_finance_stability_simulation(
                seasons=seasons,
                data_dir=sandbox_data_dir,
                league_id=league_id,
                preset=preset_arg,
                seed=seed,
                max_fa_rounds=max_fa_rounds,
                guardrails=guardrails,
            )
            guardrail_report = run_result.get("guardrails")
            guardrail_payload = guardrail_report if isinstance(guardrail_report, Mapping) else {}
            results.append(
                {
                    "preset": preset_token,
                    "effective_preset": effective_preset,
                    "seasons_run": _safe_int(run_result.get("seasons_run"), fallback=0),
                    "guardrails_passed": bool(guardrail_payload.get("passed", False)),
                    "result": run_result,
                }
            )

    return {
        "mode": "preset_comparison",
        "seasons_requested": max(0, int(seasons)),
        "presets_requested": requested_presets,
        "results": results,
        "all_passed": all(bool(row.get("guardrails_passed")) for row in results),
    }


def evaluate_finance_stability_guardrails(
    season_metrics: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
    *,
    thresholds: Mapping[str, float] | None = None,
    warmup_seasons: int = 0,
) -> Dict[str, object]:
    """Evaluate stability guardrails over one or more season metric rows.

    ``warmup_seasons`` drops the first N rows before computing maxes/mins so
    cold-start transients (empty rosters, first-cycle FA) don't trip the
    steady-state checks. Falls back to the full series if skipping would
    leave nothing to evaluate.
    """

    all_rows = [row for row in season_metrics if isinstance(row, Mapping)]
    skip = max(0, int(warmup_seasons))
    rows = all_rows[skip:] if skip < len(all_rows) else all_rows
    merged = dict(DEFAULT_STABILITY_GUARDRAILS)
    if isinstance(thresholds, Mapping):
        for key, value in thresholds.items():
            if key not in merged:
                continue
            try:
                merged[key] = float(value)
            except Exception:
                continue

    if not rows:
        return {
            "passed": False,
            "reason": "no_season_metrics",
            "checks": [],
            "thresholds": merged,
            "warmup_seasons": skip,
        }

    max_distressed = max(_safe_float(row.get("distressed_debt_ratio"), fallback=0.0) for row in rows)
    max_negative_cash = max(_safe_float(row.get("negative_cash_ratio"), fallback=0.0) for row in rows)
    max_unsigned = max(_safe_float(row.get("unsigned_ratio"), fallback=0.0) for row in rows)
    max_payroll_spread = max(_safe_float(row.get("payroll_spread_ratio"), fallback=0.0) for row in rows)
    star_rows = [row for row in rows if _safe_int(row.get("star_candidates"), fallback=0) > 0]
    min_star_retention = (
        min(_safe_float(row.get("star_retention_rate"), fallback=1.0) for row in star_rows)
        if star_rows
        else 1.0
    )

    checks = [
        {
            "name": "distressed_debt_ratio",
            "value": round(max_distressed, 4),
            "threshold": merged["max_distressed_debt_ratio"],
            "comparator": "<=",
            "passed": max_distressed <= merged["max_distressed_debt_ratio"],
        },
        {
            "name": "negative_cash_ratio",
            "value": round(max_negative_cash, 4),
            "threshold": merged["max_negative_cash_ratio"],
            "comparator": "<=",
            "passed": max_negative_cash <= merged["max_negative_cash_ratio"],
        },
        {
            "name": "unsigned_ratio",
            "value": round(max_unsigned, 4),
            "threshold": merged["max_unsigned_ratio"],
            "comparator": "<=",
            "passed": max_unsigned <= merged["max_unsigned_ratio"],
        },
        {
            "name": "payroll_spread_ratio",
            "value": round(max_payroll_spread, 4),
            "threshold": merged["max_payroll_spread_ratio"],
            "comparator": "<=",
            "passed": max_payroll_spread <= merged["max_payroll_spread_ratio"],
        },
        {
            "name": "star_retention_rate",
            "value": round(min_star_retention, 4),
            "threshold": merged["min_star_retention_rate"],
            "comparator": ">=",
            "passed": min_star_retention >= merged["min_star_retention_rate"],
        },
    ]
    return {
        "passed": all(bool(item.get("passed")) for item in checks),
        "checks": checks,
        "thresholds": merged,
        "warmup_seasons": skip,
        "seasons_evaluated": len(rows),
    }


def _apply_yearly_monthly_cycles(
    *,
    season_year: int,
    data_dir: Path,
    league_id: str,
) -> Dict[str, object]:
    applied = 0
    skipped = 0
    total_net_change = 0
    for month in range(1, 13):
        period_key = f"{season_year:04d}-{month:02d}"
        result = apply_monthly_owner_finance(
            period_key=period_key,
            data_dir=data_dir,
            league_id=league_id,
        )
        if bool(result.get("applied", False)):
            applied += 1
            total_net_change += _safe_int(result.get("total_net_change"), fallback=0)
        else:
            skipped += 1
    return {
        "applied_periods": applied,
        "skipped_periods": skipped,
        "total_net_change": total_net_change,
    }


def _collect_season_metrics(
    *,
    season_year: int,
    data_dir: Path,
    settings,
    total_players: int,
    monthly_summary: Mapping[str, object],
    offseason_summary: Mapping[str, object],
    free_agency_summary: Mapping[str, object],
) -> Dict[str, object]:
    team_financials = _load_team_financials(data_dir)
    teams = team_financials.get("teams")
    team_map = teams if isinstance(teams, Mapping) else {}
    team_count = len(team_map)

    debt_values = []
    cash_values = []
    for team in team_map.values():
        row = team if isinstance(team, Mapping) else {}
        debt_values.append(_safe_int(row.get("debt"), fallback=0))
        cash_values.append(_safe_int(row.get("cash_on_hand"), fallback=0))

    distressed_debt_cut = 40_000_000
    negative_cash_cut = 0
    distressed_count = sum(1 for amount in debt_values if amount >= distressed_debt_cut)
    negative_cash_count = sum(1 for amount in cash_values if amount < negative_cash_cut)
    distressed_ratio = (float(distressed_count) / float(team_count)) if team_count > 0 else 0.0
    negative_cash_ratio = (float(negative_cash_count) / float(team_count)) if team_count > 0 else 0.0

    payroll_totals = calculate_annual_payroll_totals(data_dir=data_dir)
    payroll_values = sorted(int(value) for value in payroll_totals.values() if int(value) > 0)
    if payroll_values:
        min_payroll = payroll_values[0]
        max_payroll = payroll_values[-1]
        payroll_spread = (float(max_payroll) / float(min_payroll)) if min_payroll > 0 else 0.0
    else:
        min_payroll = 0
        max_payroll = 0
        payroll_spread = 0.0

    unsigned_players = len(list_unsigned_players_from_files(data_dir=data_dir))
    unsigned_ratio = (float(unsigned_players) / float(total_players)) if total_players > 0 else 0.0

    arbitration = offseason_summary.get("arbitration")
    arbitration_summary = arbitration if isinstance(arbitration, Mapping) else {}
    details = arbitration_summary.get("details")
    detail_rows = details if isinstance(details, list) else []
    star_talent = _safe_int(settings.finance_ai_tuning.get("star_talent_threshold"), fallback=76)
    star_perf = _safe_int(settings.finance_ai_tuning.get("star_performance_threshold"), fallback=78)

    star_candidates = 0
    star_non_tenders = 0
    for raw in detail_rows:
        row = raw if isinstance(raw, Mapping) else {}
        if str(row.get("strategy_profile", "")).strip().lower() == "human":
            continue
        talent_score = _safe_int(row.get("talent_score"), fallback=0)
        perf_score = _safe_int(row.get("performance_score"), fallback=0)
        is_star = talent_score >= star_talent or perf_score >= star_perf
        if not is_star:
            continue
        star_candidates += 1
        if str(row.get("decision", "")).strip() == "cpu_non_tender_high_cost_underperformer":
            star_non_tenders += 1
    star_retained = max(0, star_candidates - star_non_tenders)
    star_retention_rate = (
        float(star_retained) / float(star_candidates)
        if star_candidates > 0
        else 1.0
    )

    return {
        "season_year": season_year,
        "team_count": team_count,
        "total_players": total_players,
        "unsigned_players": unsigned_players,
        "unsigned_ratio": round(unsigned_ratio, 4),
        "average_debt": _avg(debt_values),
        "average_cash": _avg(cash_values),
        "distressed_debt_teams": distressed_count,
        "distressed_debt_ratio": round(distressed_ratio, 4),
        "negative_cash_teams": negative_cash_count,
        "negative_cash_ratio": round(negative_cash_ratio, 4),
        "min_payroll": min_payroll,
        "max_payroll": max_payroll,
        "payroll_spread_ratio": round(payroll_spread, 4),
        "monthly_cycles_applied": _safe_int(monthly_summary.get("applied_periods"), fallback=0),
        "monthly_net_change": _safe_int(monthly_summary.get("total_net_change"), fallback=0),
        "arbitration_awards": _safe_int(arbitration_summary.get("awards"), fallback=0),
        "arbitration_salary_delta": _safe_int(arbitration_summary.get("salary_delta"), fallback=0),
        "cpu_non_tenders": _safe_int(arbitration_summary.get("cpu_non_tenders"), fallback=0),
        "cpu_releases": _safe_int(arbitration_summary.get("cpu_releases"), fallback=0),
        "star_candidates": star_candidates,
        "star_retained": star_retained,
        "star_retention_rate": round(star_retention_rate, 4),
        "fa_signed_players": _safe_int(free_agency_summary.get("signed_players"), fallback=0),
        "fa_rounds_run": _safe_int(free_agency_summary.get("rounds_run"), fallback=0),
    }


def _resolve_year(data_dir: Path) -> int:
    payload = _load_team_financials(data_dir)
    return _safe_int(payload.get("season_year"), fallback=2026)


def _count_players(data_dir: Path) -> int:
    try:
        return len(load_players_from_csv(data_dir / "players.csv"))
    except Exception:
        return 0


def _load_team_financials(data_dir: Path) -> Dict[str, object]:
    path = data_dir / "team_financials.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


def _avg(values: list[int]) -> int:
    if not values:
        return 0
    return int(round(sum(values) / float(len(values))))


def _safe_int(value: object, *, fallback: int) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return fallback


def _safe_float(value: object, *, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback
