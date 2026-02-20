"""Offseason finance workflow: snapshot, arbitration, and budget reset."""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, Mapping

from playbalance.season_context import SeasonContext
from services.contracts_service import (
    DEFAULT_MIN_SALARY,
    load_contracts_payload,
    release_contracts_to_free_agency,
    save_contracts_payload,
)
from services.finance_ledger import post_arb_award
from services.finance_settings import (
    FinancialSettings,
    LEVEL_ADVANCED,
    LEVEL_OFF,
    TEAM_FINANCIALS_FILENAME,
    ensure_financial_defaults,
    load_financial_settings,
)
from services.finance_ai import (
    load_team_finance_strategies,
    recommend_cpu_arbitration_decision,
)
from services.free_agency import list_unsigned_players_from_files
from services.gm_finance_queue import (
    apply_approved_queue_decisions,
    list_queue_decisions,
    summarize_queue_decisions,
)
from services.owner_finance_engine import project_monthly_owner_finance
from services.payroll_engine import calculate_annual_payroll_totals
from services.payroll_policy import (
    apply_payroll_rule_accounting_effects,
    evaluate_payroll_delta,
    record_payroll_policy_result,
)
from utils.league_settings import is_owner_league, load_league_settings
from utils.path_utils import get_data_dir

__all__ = [
    "run_offseason_financial_rollover",
    "collect_offseason_finance_overview",
    "get_offseason_checklist",
    "mark_offseason_stage",
    "get_offseason_stage_details",
]

_SERVICE_VERSION = 1
_OFFSEASON_SERVICE_DAYS = 172
_ARB_BUMP_BASIC = 0.12
_ARB_BUMP_ADVANCED = 0.22
_SUPER_TWO_ELIGIBILITY_DAYS = (2 * _OFFSEASON_SERVICE_DAYS) + 120
_STATE_FILENAME = "offseason_finance_state.json"
_CHECKLIST_STAGE_ORDER = (
    "run_pipeline",
    "contracts_review",
    "arbitration_review",
    "gm_finance_review",
    "budgets_review",
    "free_agency_kickoff",
    "finalize",
)
_STAGE_FIELD_MAP = {
    "contracts_review": "contracts_reviewed",
    "arbitration_review": "arbitration_reviewed",
    "gm_finance_review": "gm_finance_reviewed",
    "budgets_review": "budgets_reviewed",
    "free_agency_kickoff": "free_agency_started",
    "finalize": "offseason_finalized",
}


def run_offseason_financial_rollover(
    *,
    ended_season_year: int | None,
    next_season_year: int | None,
    contract_rollover: Mapping[str, object] | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Run offseason financial transitions and return a structured summary."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    ensure_financial_defaults(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    settings_path = resolved_data_dir / "league_financial_settings.json"
    settings = load_financial_settings(path=settings_path, league_id=league_id)

    team_financials_path = resolved_data_dir / TEAM_FINANCIALS_FILENAME
    team_financials = _load_team_financials(team_financials_path)
    ended_year = _safe_int(
        ended_season_year,
        fallback=_safe_int(team_financials.get("season_year"), fallback=datetime.utcnow().year),
    )
    next_year = _safe_int(next_season_year, fallback=ended_year + 1)
    state_path = resolved_data_dir / _STATE_FILENAME
    state = _load_state(state_path)
    year_state = _state_year(state, ended_year)
    snapshot_path = resolved_data_dir / "finance_snapshots" / f"{ended_year}.json"

    if bool(year_state.get("completed", False)):
        return {
            "version": _SERVICE_VERSION,
            "applied": bool(settings.enabled),
            "already_completed": True,
            "ended_season_year": ended_year,
            "next_season_year": _safe_int(year_state.get("next_season_year"), fallback=next_year),
            "snapshot_path": _to_rel_path(snapshot_path, resolved_data_dir),
            "snapshot_created": snapshot_path.exists(),
            "arbitration": {
                "enabled": settings.enabled,
                "level": settings.module_level("gm_arbitration"),
                "updated_players": 0,
                "awards": 0,
                "salary_delta": 0,
                "skipped": "already_completed",
            },
            "team_reset": {
                "teams_reset": 0,
                "budgets_refreshed": 0,
                "season_year": _safe_int(year_state.get("next_season_year"), fallback=next_year),
                "skipped": "already_completed",
            },
            "payroll_accounting": {
                "applied": False,
                "level": settings.module_level("gm_payroll_rules"),
                "teams_evaluated": 0,
                "teams_penalized": 0,
                "tax_total": 0,
                "floor_fee_total": 0,
                "skipped": "already_completed",
                "details": [],
            },
        }

    payroll_totals = calculate_annual_payroll_totals(data_dir=resolved_data_dir)
    snapshot_path = _write_snapshot(
        data_dir=resolved_data_dir,
        ended_year=ended_year,
        next_year=next_year,
        settings=settings,
        team_financials=team_financials,
        payroll_totals=payroll_totals,
        contract_rollover=contract_rollover,
    )

    arbitration_summary = _apply_arbitration_updates(
        settings=settings,
        next_year=next_year,
        data_dir=resolved_data_dir,
    )
    reset_summary = _reset_financial_year(
        settings=settings,
        next_year=next_year,
        data_dir=resolved_data_dir,
    )
    payroll_accounting_summary = apply_payroll_rule_accounting_effects(
        data_dir=resolved_data_dir,
        league_id=league_id,
        season_year=next_year,
    )
    state = _mark_state_completed(
        state,
        ended_year=ended_year,
        next_year=next_year,
        snapshot_path=_to_rel_path(snapshot_path, resolved_data_dir),
        arbitration=arbitration_summary,
        team_reset=reset_summary,
        payroll_accounting=payroll_accounting_summary,
    )
    _save_state(state_path, state)

    return {
        "version": _SERVICE_VERSION,
        "applied": bool(settings.enabled),
        "already_completed": False,
        "ended_season_year": ended_year,
        "next_season_year": next_year,
        "snapshot_path": _to_rel_path(snapshot_path, resolved_data_dir),
        "snapshot_created": True,
        "arbitration": arbitration_summary,
        "team_reset": reset_summary,
        "payroll_accounting": payroll_accounting_summary,
    }


def get_offseason_checklist(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Return ordered offseason checklist stages with next actionable step."""

    overview = collect_offseason_finance_overview(data_dir=data_dir, league_id=league_id)
    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    ended_year = _safe_int(overview.get("ended_season_year"), fallback=datetime.utcnow().year - 1)
    state = _load_state(resolved_data_dir / _STATE_FILENAME)
    year_state = _state_year(state, ended_year)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    league_settings = load_league_settings(resolved_data_dir / "league_settings.json")
    owner_mode = bool(is_owner_league(league_settings))
    gm_queue = summarize_queue_decisions(data_dir=resolved_data_dir)
    completed = bool(year_state.get("completed", False))
    contracts_required = completed
    arbitration_required = completed and settings.enabled and settings.module_level("gm_arbitration") != LEVEL_OFF
    gm_finance_required = completed and owner_mode and gm_queue["total"] > 0
    gm_finance_ready = (
        int(gm_queue.get("pending", 0)) <= 0
        and int(gm_queue.get("approved_unapplied", 0)) <= 0
    )
    budgets_required = completed and settings.enabled and settings.module_level("owner_budgets") != LEVEL_OFF

    stages: list[Dict[str, object]] = [
        {
            "id": "run_pipeline",
            "label": "Run Offseason Finance Pipeline",
            "required": True,
            "done": completed,
            "description": "Create snapshot, apply arbitration, and reset finance ledgers for next year.",
            "action_label": "Run Pipeline",
        },
        {
            "id": "contracts_review",
            "label": "Review Contract Expirations",
            "required": contracts_required,
            "done": completed and bool(year_state.get("contracts_reviewed", False)),
            "description": "Confirm expired contracts moved players to free agency and active contracts carried over.",
            "action_label": "Mark Contracts Reviewed",
        },
        {
            "id": "arbitration_review",
            "label": "Review Arbitration Awards",
            "required": arbitration_required,
            "done": (not arbitration_required) or bool(year_state.get("arbitration_reviewed", False)),
            "description": "Validate arbitration outcomes and payroll impact before offseason signings.",
            "action_label": "Mark Arbitration Reviewed",
        },
        {
            "id": "gm_finance_review",
            "label": "Resolve GM Finance Queue",
            "required": gm_finance_required,
            "done": (not gm_finance_required) or gm_finance_ready,
            "description": (
                "In multi-owner leagues, resolve pending commissioner GM finance decisions "
                "and apply approved arbitration/free-agency queue actions."
            ),
            "action_label": "Apply Approved GM Queue Decisions",
        },
        {
            "id": "budgets_review",
            "label": "Review Owner Budgets",
            "required": budgets_required,
            "done": (not budgets_required) or bool(year_state.get("budgets_reviewed", False)),
            "description": "Review budget targets/carryover for the new season year.",
            "action_label": "Mark Budgets Reviewed",
        },
        {
            "id": "free_agency_kickoff",
            "label": "Kick Off Free Agency",
            "required": completed,
            "done": completed and bool(year_state.get("free_agency_started", False)),
            "description": "Open free agency workflows and confirm unsigned-player market is active.",
            "action_label": "Mark Free Agency Started",
        },
        {
            "id": "finalize",
            "label": "Finalize Offseason Finance",
            "required": completed,
            "done": completed and bool(year_state.get("offseason_finalized", False)),
            "description": "Lock offseason finance checklist for this year and proceed with preseason operations.",
            "action_label": "Finalize Offseason Finance",
        },
    ]

    next_stage_id = None
    for stage in stages:
        if not bool(stage.get("required", False)):
            continue
        if bool(stage.get("done", False)):
            continue
        next_stage_id = str(stage.get("id") or "")
        break

    return {
        "ended_season_year": ended_year,
        "next_season_year": _safe_int(overview.get("next_season_year"), fallback=ended_year + 1),
        "phase": overview.get("phase", "UNKNOWN"),
        "can_run_now": bool(overview.get("can_run_now", False)),
        "workflow_completed": completed,
        "next_stage_id": next_stage_id,
        "stages": stages,
    }


def mark_offseason_stage(
    stage_id: str,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Mark one offseason checklist stage complete, enforcing stage order."""

    clean_stage = str(stage_id or "").strip()
    if clean_stage not in _CHECKLIST_STAGE_ORDER:
        return {
            "ok": False,
            "reason": "Unknown offseason stage.",
            "stage_id": clean_stage,
            "checklist": get_offseason_checklist(data_dir=data_dir, league_id=league_id),
        }

    checklist = get_offseason_checklist(data_dir=data_dir, league_id=league_id)
    next_stage_id = str(checklist.get("next_stage_id") or "")
    can_run_now = bool(checklist.get("can_run_now", False))
    if not can_run_now:
        return {
            "ok": False,
            "reason": "Offseason finance checklist can only be updated during OFFSEASON/PRESEASON.",
            "stage_id": clean_stage,
            "checklist": checklist,
        }

    if clean_stage == "run_pipeline":
        if next_stage_id not in {"", "run_pipeline"}:
            return {
                "ok": False,
                "reason": "Pipeline already completed for this offseason year.",
                "stage_id": clean_stage,
                "checklist": checklist,
            }
        result = run_offseason_financial_rollover(
            ended_season_year=_safe_int(checklist.get("ended_season_year"), fallback=datetime.utcnow().year - 1),
            next_season_year=_safe_int(checklist.get("next_season_year"), fallback=datetime.utcnow().year),
            data_dir=data_dir,
            league_id=league_id,
        )
        return {
            "ok": True,
            "stage_id": clean_stage,
            "pipeline_result": result,
            "checklist": get_offseason_checklist(data_dir=data_dir, league_id=league_id),
        }

    if next_stage_id and clean_stage != next_stage_id:
        return {
            "ok": False,
            "reason": f"Next required stage is '{next_stage_id}'.",
            "stage_id": clean_stage,
            "checklist": checklist,
        }

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    if clean_stage == "gm_finance_review":
        apply_summary = apply_approved_queue_decisions(data_dir=resolved_data_dir)
        queue_summary = summarize_queue_decisions(data_dir=resolved_data_dir)
        pending_count = int(queue_summary.get("pending", 0))
        unapplied_count = int(queue_summary.get("approved_unapplied", 0))
        if pending_count > 0 or unapplied_count > 0:
            return {
                "ok": False,
                "reason": (
                    "GM finance queue still has unresolved decisions "
                    f"(pending: {pending_count}, approved-not-applied: {unapplied_count})."
                ),
                "stage_id": clean_stage,
                "apply_summary": apply_summary,
                "checklist": get_offseason_checklist(data_dir=data_dir, league_id=league_id),
            }
        field_name = _STAGE_FIELD_MAP.get(clean_stage)
        _mark_stage_field(
            ended_year=_safe_int(
                checklist.get("ended_season_year"),
                fallback=datetime.utcnow().year - 1,
            ),
            field_name=str(field_name or ""),
            data_dir=resolved_data_dir,
        )
        return {
            "ok": True,
            "stage_id": clean_stage,
            "apply_summary": apply_summary,
            "checklist": get_offseason_checklist(data_dir=data_dir, league_id=league_id),
        }

    field_name = _STAGE_FIELD_MAP.get(clean_stage)
    if not field_name:
        return {
            "ok": False,
            "reason": "Stage cannot be marked directly.",
            "stage_id": clean_stage,
            "checklist": checklist,
        }

    _mark_stage_field(
        ended_year=_safe_int(
            checklist.get("ended_season_year"),
            fallback=datetime.utcnow().year - 1,
        ),
        field_name=field_name,
        data_dir=resolved_data_dir,
    )

    return {
        "ok": True,
        "stage_id": clean_stage,
        "checklist": get_offseason_checklist(data_dir=data_dir, league_id=league_id),
    }


def get_offseason_stage_details(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Return detailed review rows for offseason checklist stages."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    overview = collect_offseason_finance_overview(data_dir=resolved_data_dir, league_id=league_id)
    ended_year = _safe_int(overview.get("ended_season_year"), fallback=datetime.utcnow().year - 1)
    league_settings = load_league_settings(resolved_data_dir / "league_settings.json")
    owner_mode = bool(is_owner_league(league_settings))

    contracts_payload = load_contracts_payload(data_dir=resolved_data_dir)
    contracts = contracts_payload.get("players")
    contract_map = contracts if isinstance(contracts, Mapping) else {}
    name_lookup = _player_name_lookup(resolved_data_dir)
    contract_rows: list[Dict[str, object]] = []
    for player_id, raw_contract in contract_map.items():
        if not isinstance(raw_contract, Mapping):
            continue
        years_left = max(1, _safe_int(raw_contract.get("years_left"), fallback=1))
        if years_left > 1:
            continue
        team_id = str(raw_contract.get("team_id") or "").strip()
        contract_rows.append(
            {
                "player_id": str(player_id),
                "player_name": name_lookup.get(str(player_id), str(player_id)),
                "team_id": team_id,
                "years_left": years_left,
                "annual_salary": max(
                    DEFAULT_MIN_SALARY,
                    _safe_int(raw_contract.get("annual_salary"), fallback=DEFAULT_MIN_SALARY),
                ),
                "service_time_days": max(0, _safe_int(raw_contract.get("service_time_days"), fallback=0)),
                "arb_eligible": bool(raw_contract.get("arb_eligible", False)),
            }
        )
    contract_rows.sort(
        key=lambda row: (
            str(row.get("team_id") or ""),
            -_safe_int(row.get("annual_salary"), fallback=0),
            str(row.get("player_name") or ""),
        )
    )

    state = _load_state(resolved_data_dir / _STATE_FILENAME)
    year_state = _state_year(state, ended_year)
    arbitration_raw = year_state.get("arbitration_details")
    arbitration_rows = []
    if isinstance(arbitration_raw, list):
        for row in arbitration_raw:
            if not isinstance(row, Mapping):
                continue
            player_id = str(row.get("player_id") or "").strip()
            arbitration_rows.append(
                {
                    "player_id": player_id,
                    "player_name": name_lookup.get(player_id, player_id),
                    "team_id": str(row.get("team_id") or "").strip(),
                    "old_salary": max(
                        DEFAULT_MIN_SALARY,
                        _safe_int(row.get("old_salary"), fallback=DEFAULT_MIN_SALARY),
                    ),
                    "new_salary": max(
                        DEFAULT_MIN_SALARY,
                        _safe_int(row.get("new_salary"), fallback=DEFAULT_MIN_SALARY),
                    ),
                    "delta": _safe_int(row.get("delta"), fallback=0),
                }
            )
    arbitration_rows.sort(
        key=lambda row: (
            str(row.get("team_id") or ""),
            -_safe_int(row.get("delta"), fallback=0),
            str(row.get("player_name") or ""),
        )
    )
    payroll_raw = year_state.get("payroll_accounting_details")
    payroll_rows = []
    if isinstance(payroll_raw, list):
        for row in payroll_raw:
            if not isinstance(row, Mapping):
                continue
            payroll_rows.append(
                {
                    "team_id": str(row.get("team_id") or "").strip(),
                    "payroll": _safe_int(row.get("payroll"), fallback=0),
                    "threshold": _safe_int(row.get("threshold"), fallback=0),
                    "floor": _safe_int(row.get("floor"), fallback=0),
                    "tax_penalty": _safe_int(row.get("tax_penalty"), fallback=0),
                    "floor_fee": _safe_int(row.get("floor_fee"), fallback=0),
                    "applied": bool(row.get("applied", False)),
                }
            )
    payroll_rows.sort(
        key=lambda row: (
            str(row.get("team_id") or ""),
            -_safe_int(row.get("tax_penalty"), fallback=0),
            -_safe_int(row.get("floor_fee"), fallback=0),
        )
    )

    snapshot = _load_snapshot(resolved_data_dir / "finance_snapshots" / f"{ended_year}.json")
    previous_financials = snapshot.get("team_financials")
    previous_teams = (
        previous_financials.get("teams")
        if isinstance(previous_financials, Mapping)
        else {}
    )
    previous_team_map = previous_teams if isinstance(previous_teams, Mapping) else {}
    current_financials = _load_team_financials(resolved_data_dir / TEAM_FINANCIALS_FILENAME)
    current_teams = current_financials.get("teams")
    current_team_map = current_teams if isinstance(current_teams, Mapping) else {}
    team_ids = sorted(
        set(str(team_id).strip() for team_id in previous_team_map.keys())
        | set(str(team_id).strip() for team_id in current_team_map.keys())
    )
    budget_rows = []
    for team_id in team_ids:
        if not team_id:
            continue
        previous_budget = _budget_map_for_team(previous_team_map.get(team_id))
        current_budget = _budget_map_for_team(current_team_map.get(team_id))
        previous_total = sum(previous_budget.values())
        current_total = sum(current_budget.values())
        budget_rows.append(
            {
                "team_id": team_id,
                "previous_total": previous_total,
                "current_total": current_total,
                "delta": current_total - previous_total,
                "training_delta": current_budget["training"] - previous_budget["training"],
                "scouting_delta": current_budget["scouting"] - previous_budget["scouting"],
                "development_delta": current_budget["development"] - previous_budget["development"],
                "facilities_delta": current_budget["facilities"] - previous_budget["facilities"],
            }
        )
    budget_rows.sort(key=lambda row: str(row.get("team_id") or ""))
    gm_queue_rows = (
        list_queue_decisions(data_dir=resolved_data_dir)
        if owner_mode
        else []
    )

    return {
        "ended_season_year": ended_year,
        "next_season_year": _safe_int(overview.get("next_season_year"), fallback=ended_year + 1),
        "contract_expirations": contract_rows,
        "arbitration_details": arbitration_rows,
        "payroll_accounting_details": payroll_rows,
        "budget_deltas": budget_rows,
        "gm_finance_queue": gm_queue_rows,
    }


def collect_offseason_finance_overview(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Return a dashboard-friendly offseason finance status payload."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    ensure_financial_defaults(data_dir=resolved_data_dir, league_id=league_id)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    current_year = _resolve_current_year(resolved_data_dir)
    phase = _resolve_phase(resolved_data_dir)
    ended_year = current_year - 1
    next_year = current_year

    contracts_payload = load_contracts_payload(data_dir=resolved_data_dir)
    players = contracts_payload.get("players")
    contracts = players if isinstance(players, dict) else {}
    expiring_count = 0
    arb_candidate_count = 0
    total_contracts = 0
    for contract in contracts.values():
        if not isinstance(contract, dict):
            continue
        total_contracts += 1
        years_left = max(1, _safe_int(contract.get("years_left"), fallback=1))
        service_days = max(0, _safe_int(contract.get("service_time_days"), fallback=0))
        if years_left <= 1:
            expiring_count += 1
        if years_left <= 1 and service_days + _OFFSEASON_SERVICE_DAYS >= (3 * _OFFSEASON_SERVICE_DAYS):
            arb_candidate_count += 1

    try:
        unsigned_count = len(list_unsigned_players_from_files(data_dir=resolved_data_dir))
    except Exception:
        unsigned_count = 0

    state = _load_state(resolved_data_dir / _STATE_FILENAME)
    completed = bool(_state_year(state, ended_year).get("completed", False))
    snapshot_path = resolved_data_dir / "finance_snapshots" / f"{ended_year}.json"
    league_settings = load_league_settings(resolved_data_dir / "league_settings.json")
    owner_mode = bool(is_owner_league(league_settings))
    gm_queue = summarize_queue_decisions(data_dir=resolved_data_dir)

    return {
        "financials_enabled": bool(settings.enabled),
        "preset": settings.preset,
        "phase": phase,
        "ended_season_year": ended_year,
        "next_season_year": next_year,
        "workflow_completed": completed,
        "snapshot_exists": snapshot_path.exists(),
        "snapshot_path": _to_rel_path(snapshot_path, resolved_data_dir),
        "contracts_total": total_contracts,
        "contracts_expiring": expiring_count,
        "arbitration_candidates": arb_candidate_count,
        "unsigned_players": unsigned_count,
        "requires_commissioner_finance_review": owner_mode,
        "gm_queue_total": int(gm_queue.get("total", 0)),
        "gm_queue_pending": int(gm_queue.get("pending", 0)),
        "gm_queue_approved": int(gm_queue.get("approved", 0)),
        "gm_queue_approved_unapplied": int(gm_queue.get("approved_unapplied", 0)),
        "gm_queue_approved_applied": int(gm_queue.get("approved_applied", 0)),
        "gm_queue_rejected": int(gm_queue.get("rejected", 0)),
        "can_run_now": phase in {"OFFSEASON", "PRESEASON"},
    }


def _apply_arbitration_updates(
    *,
    settings: FinancialSettings,
    next_year: int,
    data_dir: Path,
) -> Dict[str, object]:
    level = settings.module_level("gm_arbitration")
    contracts_level = settings.module_level("gm_contracts")
    if (not settings.enabled) or level == LEVEL_OFF or contracts_level == LEVEL_OFF:
        return {
            "enabled": False,
            "level": level,
            "updated_players": 0,
            "awards": 0,
            "salary_delta": 0,
            "details": [],
        }

    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        return {
            "enabled": True,
            "level": level,
            "updated_players": 0,
            "awards": 0,
            "salary_delta": 0,
            "details": [],
        }

    bump = _ARB_BUMP_ADVANCED if level == LEVEL_ADVANCED else _ARB_BUMP_BASIC
    updated_players = 0
    awards = 0
    salary_delta = 0
    awards_by_team: Dict[str, int] = {}
    details: list[Dict[str, object]] = []
    cpu_non_tender_ids: list[str] = []
    human_owned_teams = _human_owned_team_ids(data_dir)
    finance_ai_level = settings.module_level("gm_finance_ai")
    team_strategies = (
        load_team_finance_strategies(data_dir=data_dir)
        if finance_ai_level != LEVEL_OFF
        else {}
    )
    player_profiles = _build_player_profiles(data_dir)
    payroll_totals = calculate_annual_payroll_totals(data_dir=data_dir)
    monthly_projection = project_monthly_owner_finance(data_dir=data_dir)

    for player_id, contract in players.items():
        if not isinstance(contract, dict):
            continue
        updated_players += 1
        team_id = str(contract.get("team_id") or "").strip()
        service_days = _safe_int(contract.get("service_time_days"), fallback=0) + _OFFSEASON_SERVICE_DAYS
        contract["service_time_days"] = service_days
        years_left = max(1, _safe_int(contract.get("years_left"), fallback=1))
        contract["fa_year"] = next_year + years_left
        arb_eligible = _is_arb_eligible(
            years_left=years_left,
            service_time_days=service_days,
            arbitration_level=level,
        )
        contract["arb_eligible"] = bool(arb_eligible)
        if not arb_eligible:
            continue

        current_salary = max(DEFAULT_MIN_SALARY, _safe_int(contract.get("annual_salary"), fallback=DEFAULT_MIN_SALARY))
        team_payroll = max(DEFAULT_MIN_SALARY, _safe_int(payroll_totals.get(team_id), fallback=DEFAULT_MIN_SALARY))
        salary_share = float(current_salary) / float(team_payroll)
        profile = player_profiles.get(str(player_id), {})
        talent_score = _safe_int(profile.get("talent"), fallback=60)
        performance_score = _safe_int(profile.get("performance"), fallback=55)
        is_human_team = team_id in human_owned_teams

        decision = "manual_default" if is_human_team else "cpu_standard"
        applied_bump = bump
        arb_tier = "standard"
        if level == LEVEL_ADVANCED and years_left > 1:
            # Super-two class uses a moderated raise baseline.
            applied_bump = min(applied_bump, 0.16)
            arb_tier = "super_two"
        strategy_profile = "human"
        budget_tone = "n/a"
        if not is_human_team:
            team_strategy = team_strategies.get(team_id)
            if team_strategy is not None:
                strategy_profile = str(getattr(team_strategy, "profile", "balanced") or "balanced")
                budget_tone = str(getattr(team_strategy, "budget_tone", "neutral") or "neutral")
            else:
                strategy_profile = "balanced"
                budget_tone = "neutral"
            cpu_decision = recommend_cpu_arbitration_decision(
                ai_level=finance_ai_level,
                team_strategy=team_strategy,
                base_bump=applied_bump,
                current_salary=current_salary,
                salary_share=salary_share,
                talent_score=talent_score,
                performance_score=performance_score,
                tuning=settings.finance_ai_tuning,
            )
            applied_bump = max(0.0, float(cpu_decision.applied_bump))
            decision = str(cpu_decision.decision_code or "cpu_standard")
            if cpu_decision.non_tender:
                non_tender_policy = evaluate_payroll_delta(
                    team_id,
                    annual_delta=-current_salary,
                    data_dir=data_dir,
                    annual_totals=payroll_totals,
                    monthly_projection=monthly_projection,
                )
                if not non_tender_policy.allowed:
                    record_payroll_policy_result(
                        non_tender_policy,
                        action="offseason_arbitration_non_tender",
                        data_dir=data_dir,
                        season_year=next_year,
                    )
                    decision = "policy_block_hold"
                    applied_bump = 0.0
                else:
                    if non_tender_policy.warning:
                        record_payroll_policy_result(
                            non_tender_policy,
                            action="offseason_arbitration_non_tender",
                            data_dir=data_dir,
                            season_year=next_year,
                        )
                    cpu_non_tender_ids.append(str(player_id))
                    details.append(
                        {
                            "player_id": str(player_id),
                            "team_id": team_id,
                            "old_salary": current_salary,
                            "new_salary": 0,
                            "delta": -current_salary,
                            "decision": decision,
                            "talent_score": talent_score,
                            "performance_score": performance_score,
                            "salary_share": round(salary_share, 4),
                            "strategy_profile": strategy_profile,
                            "budget_tone": budget_tone,
                            "arb_tier": arb_tier,
                        }
                    )
                    continue

        next_salary = max(DEFAULT_MIN_SALARY, int(round(current_salary * (1.0 + applied_bump))))
        delta = max(0, next_salary - current_salary)
        raise_policy = evaluate_payroll_delta(
            team_id,
            annual_delta=delta,
            data_dir=data_dir,
            annual_totals=payroll_totals,
            monthly_projection=monthly_projection,
        )
        if not raise_policy.allowed:
            record_payroll_policy_result(
                raise_policy,
                action="offseason_arbitration_raise",
                data_dir=data_dir,
                season_year=next_year,
            )
            next_salary = current_salary
            delta = 0
            decision = "policy_block_hold"
        elif raise_policy.warning:
            record_payroll_policy_result(
                raise_policy,
                action="offseason_arbitration_raise",
                data_dir=data_dir,
                season_year=next_year,
            )
        contract["annual_salary"] = next_salary
        if delta > 0:
            awards += 1
            salary_delta += delta
            if team_id:
                awards_by_team[team_id] = awards_by_team.get(team_id, 0) + delta
                payroll_totals[team_id] = int(payroll_totals.get(team_id, 0) or 0) + delta

        details.append(
            {
                "player_id": str(player_id),
                "team_id": team_id,
                "old_salary": current_salary,
                "new_salary": next_salary,
                "delta": delta,
                "decision": decision,
                "talent_score": talent_score,
                "performance_score": performance_score,
                "salary_share": round(salary_share, 4),
                "strategy_profile": strategy_profile,
                "budget_tone": budget_tone,
                "arb_tier": arb_tier,
            }
        )

    save_contracts_payload(payload, data_dir=data_dir)
    non_tender_summary = release_contracts_to_free_agency(
        cpu_non_tender_ids,
        data_dir=data_dir,
    ) if cpu_non_tender_ids else {
        "released_contracts": 0,
        "released_from_rosters": 0,
        "release_teams": [],
    }
    if awards_by_team:
        for team_id, delta in sorted(awards_by_team.items()):
            post_arb_award(
                team_id=team_id,
                season_year=next_year,
                salary_delta=delta,
                memo=f"Offseason arbitration awards ({next_year})",
                timestamp=_timestamp(),
                data_dir=data_dir,
            )

    return {
        "enabled": True,
        "level": level,
        "updated_players": updated_players,
        "awards": awards,
        "salary_delta": salary_delta,
        "details": details,
        "cpu_non_tenders": int(non_tender_summary.get("released_contracts", 0)),
        "cpu_releases": int(non_tender_summary.get("released_from_rosters", 0)),
    }


def _reset_financial_year(
    *,
    settings: FinancialSettings,
    next_year: int,
    data_dir: Path,
) -> Dict[str, object]:
    path = data_dir / TEAM_FINANCIALS_FILENAME
    payload = _load_team_financials(path)
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        teams = {}
        payload["teams"] = teams

    budget_enabled = settings.enabled and settings.module_level("owner_budgets") != LEVEL_OFF
    projections = project_monthly_owner_finance(data_dir=data_dir) if budget_enabled else {}

    reset_count = 0
    budget_refresh_count = 0
    for team_id, raw in teams.items():
        if not isinstance(raw, dict):
            continue
        reset_count += 1
        raw["revenue"] = {
            "tickets": 0,
            "concessions": 0,
            "media": 0,
            "sponsorship": 0,
        }
        raw["expenses"] = {
            "payroll": 0,
            "training": 0,
            "scouting": 0,
            "facilities": 0,
            "operations": 0,
        }
        snapshot = projections.get(str(team_id).strip())
        if snapshot is not None:
            raw["budgets"] = dict(snapshot.projected_budgets)
            budget_refresh_count += 1

    payload["season_year"] = next_year
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "teams_reset": reset_count,
        "budgets_refreshed": budget_refresh_count,
        "season_year": next_year,
    }


def _write_snapshot(
    *,
    data_dir: Path,
    ended_year: int,
    next_year: int,
    settings: FinancialSettings,
    team_financials: Mapping[str, object],
    payroll_totals: Mapping[str, int],
    contract_rollover: Mapping[str, object] | None,
) -> Path:
    snapshot_dir = data_dir / "finance_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{ended_year}.json"
    payload = {
        "version": _SERVICE_VERSION,
        "created_at": _timestamp(),
        "ended_season_year": ended_year,
        "next_season_year": next_year,
        "financials_enabled": bool(settings.enabled),
        "preset": settings.preset,
        "enforcement_mode": settings.enforcement_mode,
        "modules": dict(settings.modules),
        "contract_rollover": dict(contract_rollover or {}),
        "annual_payroll_totals": {str(k): int(v) for k, v in payroll_totals.items()},
        "team_financials": team_financials,
    }
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return snapshot_path


def _load_team_financials(path: Path) -> Dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(payload.get("teams"), dict):
        payload["teams"] = {}
    return payload


def _load_snapshot(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _player_name_lookup(data_dir: Path) -> Dict[str, str]:
    try:
        from utils.player_loader import load_players_from_csv

        players = load_players_from_csv(data_dir / "players.csv")
    except Exception:
        return {}
    names: Dict[str, str] = {}
    for player in players:
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        first_name = str(getattr(player, "first_name", "") or "").strip()
        last_name = str(getattr(player, "last_name", "") or "").strip()
        full_name = f"{first_name} {last_name}".strip() or player_id
        names[player_id] = full_name
    return names


def _build_player_profiles(data_dir: Path) -> Dict[str, Dict[str, int]]:
    profiles: Dict[str, Dict[str, int]] = {}
    try:
        from utils.player_loader import load_players_from_csv

        players = load_players_from_csv(data_dir / "players.csv")
    except Exception:
        players = []
    stats_payload = _load_snapshot(data_dir / "season_stats.json")
    stats_map = stats_payload.get("players")
    stats_by_player = stats_map if isinstance(stats_map, Mapping) else {}

    for player in players:
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
            getattr(player, "primary_position", "") or ""
        ).upper() == "P"
        talent = _player_talent_score(player, is_pitcher=is_pitcher)
        performance = _player_performance_score(
            stats_by_player.get(player_id),
            is_pitcher=is_pitcher,
        )
        profiles[player_id] = {
            "talent": talent,
            "performance": performance,
        }
    return profiles


def _player_talent_score(player: object, *, is_pitcher: bool) -> int:
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
        return 55
    return max(20, min(95, int(round(sum(values) / len(values)))))


def _player_performance_score(raw_stats: object, *, is_pitcher: bool) -> int:
    stats = raw_stats if isinstance(raw_stats, Mapping) else {}
    if not stats:
        return 55
    if is_pitcher:
        era = _safe_float(stats.get("era"), fallback=4.20)
        score = 60
        if era <= 2.50:
            score += 20
        elif era <= 3.50:
            score += 10
        elif era >= 5.50:
            score -= 20
        elif era >= 4.70:
            score -= 10

        strikeouts = _safe_float(stats.get("k"), fallback=0.0)
        innings = _safe_float(stats.get("ip"), fallback=0.0)
        k_per_nine = (strikeouts * 9.0 / innings) if innings > 0 else 0.0
        if k_per_nine >= 9.0:
            score += 8
        elif k_per_nine >= 7.0:
            score += 4
        elif k_per_nine <= 5.0 and innings > 0:
            score -= 6
        return max(20, min(95, int(round(score))))

    ops = _safe_float(stats.get("ops"), fallback=0.0)
    if ops <= 0:
        obp = _safe_float(stats.get("obp"), fallback=0.0)
        slg = _safe_float(stats.get("slg"), fallback=0.0)
        ops = obp + slg
    score = 58
    if ops >= 0.900:
        score += 20
    elif ops >= 0.800:
        score += 10
    elif ops <= 0.650 and ops > 0:
        score -= 20
    elif ops <= 0.720 and ops > 0:
        score -= 10
    return max(20, min(95, int(round(score))))


def _safe_float(value: object, *, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _is_arb_eligible(
    *,
    years_left: int,
    service_time_days: int,
    arbitration_level: str,
) -> bool:
    if years_left <= 1 and service_time_days >= (3 * _OFFSEASON_SERVICE_DAYS):
        return True
    token = str(arbitration_level or "").strip().lower()
    if token == LEVEL_ADVANCED and years_left <= 2 and service_time_days >= _SUPER_TWO_ELIGIBILITY_DAYS:
        return True
    return False


def _human_owned_team_ids(data_dir: Path) -> set[str]:
    team_ids: set[str] = set()
    try:
        from utils.user_manager import load_users

        users = load_users(data_dir / "users.txt")
        for user in users:
            if not isinstance(user, Mapping):
                continue
            role = str(user.get("role") or "").strip().lower()
            team_id = str(user.get("team_id") or "").strip()
            if role == "owner" and team_id:
                team_ids.add(team_id)
    except Exception:
        pass
    try:
        with (data_dir / "teams.csv").open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                owner = str(row.get("owner_id") or "").strip()
                team_id = str(row.get("team_id") or "").strip()
                if not team_id:
                    continue
                if owner and owner.lower() not in {"cpu", "ai", "none"}:
                    team_ids.add(team_id)
    except Exception:
        pass
    return team_ids


def _budget_map_for_team(raw_entry: object) -> Dict[str, int]:
    entry = raw_entry if isinstance(raw_entry, Mapping) else {}
    budgets_raw = entry.get("budgets")
    budgets = budgets_raw if isinstance(budgets_raw, Mapping) else {}
    return {
        "training": _safe_int(budgets.get("training"), fallback=0),
        "scouting": _safe_int(budgets.get("scouting"), fallback=0),
        "development": _safe_int(budgets.get("development"), fallback=0),
        "facilities": _safe_int(budgets.get("facilities"), fallback=0),
    }


def _safe_int(value: object, *, fallback: int) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return fallback


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _to_rel_path(path: Path, base_dir: Path) -> str:
    try:
        return path.relative_to(base_dir).as_posix()
    except Exception:
        return path.as_posix()


def _resolve_current_year(data_dir: Path) -> int:
    try:
        ctx = SeasonContext.load(path=data_dir / "career_index.json")
        current = ctx.current if isinstance(ctx.current, dict) else {}
        raw_year = current.get("league_year")
        if raw_year is not None:
            return _safe_int(raw_year, fallback=datetime.utcnow().year)
    except Exception:
        pass
    payload = _load_team_financials(data_dir / TEAM_FINANCIALS_FILENAME)
    return _safe_int(payload.get("season_year"), fallback=datetime.utcnow().year)


def _resolve_phase(data_dir: Path) -> str:
    try:
        payload = json.loads((data_dir / "season_state.json").read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            phase = str(payload.get("phase") or "").strip().upper()
            if phase:
                return phase
    except Exception:
        pass
    return "UNKNOWN"


def _load_state(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"version": _SERVICE_VERSION, "years": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    years = payload.get("years")
    if not isinstance(years, dict):
        years = {}
    return {
        "version": _SERVICE_VERSION,
        "years": years,
    }


def _mark_stage_field(*, ended_year: int, field_name: str, data_dir: Path) -> None:
    if not field_name:
        return
    state_path = data_dir / _STATE_FILENAME
    state = _load_state(state_path)
    years = state.get("years")
    years_map = dict(years) if isinstance(years, Mapping) else {}
    year_state = years_map.get(str(ended_year))
    year_payload = dict(year_state) if isinstance(year_state, Mapping) else {}
    year_payload[field_name] = True
    years_map[str(ended_year)] = year_payload
    state["years"] = years_map
    _save_state(state_path, state)


def _save_state(path: Path, state: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(state), indent=2), encoding="utf-8")


def _state_year(state: Mapping[str, object], ended_year: int) -> Dict[str, object]:
    years = state.get("years")
    if not isinstance(years, Mapping):
        return {}
    raw = years.get(str(ended_year))
    if isinstance(raw, dict):
        return raw
    return {}


def _mark_state_completed(
    state: Mapping[str, object],
    *,
    ended_year: int,
    next_year: int,
    snapshot_path: str,
    arbitration: Mapping[str, object],
    team_reset: Mapping[str, object],
    payroll_accounting: Mapping[str, object],
) -> Dict[str, object]:
    years_raw = state.get("years")
    years = dict(years_raw) if isinstance(years_raw, Mapping) else {}
    existing = years.get(str(ended_year))
    existing_state = dict(existing) if isinstance(existing, Mapping) else {}
    contracts_reviewed = bool(existing_state.get("contracts_reviewed", False))
    arbitration_reviewed = bool(existing_state.get("arbitration_reviewed", False))
    budgets_reviewed = bool(existing_state.get("budgets_reviewed", False))
    free_agency_started = bool(existing_state.get("free_agency_started", False))
    offseason_finalized = bool(existing_state.get("offseason_finalized", False))
    raw_details = arbitration.get("details")
    arbitration_details = (
        [dict(item) for item in raw_details if isinstance(item, Mapping)]
        if isinstance(raw_details, list)
        else []
    )
    payroll_raw = payroll_accounting.get("details")
    payroll_details = (
        [dict(item) for item in payroll_raw if isinstance(item, Mapping)]
        if isinstance(payroll_raw, list)
        else []
    )
    years[str(ended_year)] = {
        "completed": True,
        "completed_at": _timestamp(),
        "next_season_year": next_year,
        "snapshot_path": snapshot_path,
        "arbitration_awards": _safe_int(arbitration.get("awards"), fallback=0),
        "arbitration_salary_delta": _safe_int(arbitration.get("salary_delta"), fallback=0),
        "teams_reset": _safe_int(team_reset.get("teams_reset"), fallback=0),
        "arbitration_details": arbitration_details,
        "payroll_accounting_level": str(payroll_accounting.get("level") or ""),
        "payroll_accounting_teams_penalized": _safe_int(
            payroll_accounting.get("teams_penalized"),
            fallback=0,
        ),
        "payroll_accounting_tax_total": _safe_int(
            payroll_accounting.get("tax_total"),
            fallback=0,
        ),
        "payroll_accounting_floor_fee_total": _safe_int(
            payroll_accounting.get("floor_fee_total"),
            fallback=0,
        ),
        "payroll_accounting_details": payroll_details,
        "contracts_reviewed": contracts_reviewed,
        "arbitration_reviewed": arbitration_reviewed,
        "budgets_reviewed": budgets_reviewed,
        "free_agency_started": free_agency_started,
        "offseason_finalized": offseason_finalized,
    }
    return {
        "version": _SERVICE_VERSION,
        "years": years,
    }
