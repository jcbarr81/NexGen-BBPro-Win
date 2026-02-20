"""GM/Coach finance queue helpers for owner decision workflows."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Dict, Mapping

from services.contracts_service import (
    DEFAULT_MIN_SALARY,
    estimate_salary_for_player,
    load_contracts_payload,
    release_contracts_to_free_agency,
    save_contracts_payload,
    sign_free_agent_contract,
)
from services.finance_ai import (
    estimate_free_agent_salary_band,
    load_team_finance_strategies,
    recommend_cpu_arbitration_decision,
)
from services.finance_settings import (
    LEVEL_OFF,
    load_financial_settings,
)
from services.free_agency import _add_player_to_team_roster
from services.free_agency import list_unsigned_players_from_files
from services.transaction_log import record_transaction
from services.payroll_engine import calculate_annual_payroll_totals, load_contracts
from services.payroll_policy import (
    evaluate_free_agent_signing,
    evaluate_payroll_delta,
    record_payroll_policy_result,
)
from utils.league_settings import is_owner_league, load_league_settings
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv

__all__ = [
    "build_arbitration_queue",
    "build_free_agency_queue",
    "list_queue_decisions",
    "list_team_queue_decisions",
    "list_pending_queue_decisions",
    "summarize_queue_decisions",
    "save_team_queue_decision",
    "set_queue_review_status",
    "apply_approved_queue_decisions",
    "apply_recommended_arbitration_decisions",
    "apply_recommended_free_agency_targets",
]

_VERSION = 1
_FILENAME = "gm_finance_decisions.json"
_ARB_BUMP_BASIC = 0.12
_ARB_BUMP_ADVANCED = 0.22
_OFFSEASON_SERVICE_DAYS = 172
_ARB_ELIGIBILITY_DAYS = 3 * _OFFSEASON_SERVICE_DAYS
_SUPER_TWO_ELIGIBILITY_DAYS = (2 * _OFFSEASON_SERVICE_DAYS) + 120
_QUEUE_ARBITRATION = "arbitration"
_QUEUE_FREE_AGENCY = "free_agency"
_ACTION_OFFER_RAISE = "offer_raise"
_ACTION_HOLD = "hold"
_ACTION_NON_TENDER = "non_tender"
_ACTION_TARGET = "target"
_ACTION_MONITOR = "monitor"
_ACTION_PASS = "pass"
_REVIEW_PENDING = "pending_commissioner"
_REVIEW_APPROVED = "approved_local"
_REVIEW_APPROVED_COMMISSIONER = "approved_commissioner"
_REVIEW_REJECTED_COMMISSIONER = "rejected_commissioner"


def build_arbitration_queue(
    team_id: str,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> list[Dict[str, object]]:
    """Return arbitration decision queue rows for one team."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return []
    resolved_data_dir = _resolve_data_dir(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    if (
        (not settings.enabled)
        or settings.module_level("gm_contracts") == LEVEL_OFF
        or settings.module_level("gm_arbitration") == LEVEL_OFF
    ):
        return []

    payroll_totals = calculate_annual_payroll_totals(data_dir=resolved_data_dir)
    team_payroll = max(
        DEFAULT_MIN_SALARY,
        _safe_int(payroll_totals.get(clean_team_id), fallback=DEFAULT_MIN_SALARY),
    )
    ai_level = settings.module_level("gm_finance_ai")
    strategy_map = load_team_finance_strategies(data_dir=resolved_data_dir)
    team_strategy = strategy_map.get(clean_team_id)
    base_bump = _ARB_BUMP_ADVANCED
    arbitration_level = settings.module_level("gm_arbitration")
    if arbitration_level == "basic":
        base_bump = _ARB_BUMP_BASIC

    players = _load_players_by_id(resolved_data_dir)
    decisions = list_team_queue_decisions(
        clean_team_id,
        queue_type=_QUEUE_ARBITRATION,
        data_dir=resolved_data_dir,
    )
    decisions_by_player = {
        str(row.get("item_id") or "").strip(): row
        for row in decisions
    }

    payload = load_contracts(data_dir=resolved_data_dir)
    contracts = payload.get("players")
    if not isinstance(contracts, Mapping):
        return []

    queue: list[Dict[str, object]] = []
    for player_id, raw_contract in contracts.items():
        if not isinstance(raw_contract, Mapping):
            continue
        contract_team = str(raw_contract.get("team_id") or "").strip()
        if contract_team != clean_team_id:
            continue
        years_left = max(1, _safe_int(raw_contract.get("years_left"), fallback=1))
        service_time_days = max(
            0,
            _safe_int(raw_contract.get("service_time_days"), fallback=0),
        )
        if not _is_arb_eligible(
            years_left,
            service_time_days,
            arbitration_level=arbitration_level,
        ):
            continue

        clean_player_id = str(player_id or "").strip()
        current_salary = max(
            DEFAULT_MIN_SALARY,
            _safe_int(raw_contract.get("annual_salary"), fallback=DEFAULT_MIN_SALARY),
        )
        player = players.get(clean_player_id)
        talent_score = _player_talent_score(player)
        performance_score = _player_performance_score(player)
        salary_share = float(current_salary) / float(team_payroll)
        recommendation = recommend_cpu_arbitration_decision(
            ai_level=ai_level,
            team_strategy=team_strategy,
            base_bump=base_bump,
            current_salary=current_salary,
            salary_share=salary_share,
            talent_score=talent_score,
            performance_score=performance_score,
            tuning=settings.finance_ai_tuning,
        )
        projected_salary = max(
            DEFAULT_MIN_SALARY,
            int(round(current_salary * (1.0 + float(recommendation.applied_bump)))),
        )
        recommended_action = _ACTION_OFFER_RAISE
        if recommendation.non_tender:
            recommended_action = _ACTION_NON_TENDER
        elif projected_salary <= current_salary:
            recommended_action = _ACTION_HOLD

        decision_row = decisions_by_player.get(clean_player_id, {})
        queue.append(
            {
                "player_id": clean_player_id,
                "player_name": _player_name(player, fallback=clean_player_id),
                "years_left": years_left,
                "service_time_days": service_time_days,
                "current_salary": current_salary,
                "projected_salary": projected_salary,
                "recommended_raise_pct": round(
                    max(0.0, float(recommendation.applied_bump)) * 100.0,
                    2,
                ),
                "recommended_action": recommended_action,
                "decision_code": str(recommendation.decision_code or "cpu_standard"),
                "talent_score": talent_score,
                "performance_score": performance_score,
                "queued_action": str(decision_row.get("action") or "").strip(),
                "queued_at": str(decision_row.get("updated_at") or "").strip(),
                "queued_status": str(decision_row.get("review_status") or "").strip(),
            }
        )
    queue.sort(
        key=lambda row: (
            _arb_priority(str(row.get("recommended_action") or "")),
            -_safe_int(row.get("current_salary"), fallback=0),
            str(row.get("player_name") or row.get("player_id") or ""),
        )
    )
    return queue


def build_free_agency_queue(
    team_id: str,
    *,
    limit: int = 25,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> list[Dict[str, object]]:
    """Return free-agency target queue rows for one team."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return []
    resolved_data_dir = _resolve_data_dir(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    if (not settings.enabled) or settings.module_level("gm_free_agency") == LEVEL_OFF:
        return []

    ai_level = settings.module_level("gm_finance_ai")
    strategy_map = load_team_finance_strategies(data_dir=resolved_data_dir)
    team_strategy = strategy_map.get(clean_team_id)
    min_mul, max_mul = estimate_free_agent_salary_band(
        team_strategy,
        ai_level=ai_level,
    )
    payroll_total = _safe_int(
        calculate_annual_payroll_totals(data_dir=resolved_data_dir).get(clean_team_id),
        fallback=0,
    )
    payroll_limit = _payroll_limit_for_level(settings.module_level("gm_payroll_rules"))
    decisions = list_team_queue_decisions(
        clean_team_id,
        queue_type=_QUEUE_FREE_AGENCY,
        data_dir=resolved_data_dir,
    )
    decisions_by_player = {
        str(row.get("item_id") or "").strip(): row
        for row in decisions
    }

    try:
        unsigned_players = list_unsigned_players_from_files(data_dir=resolved_data_dir)
    except Exception:
        unsigned_players = []

    queue: list[Dict[str, object]] = []
    for player in unsigned_players:
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        expected_salary = max(DEFAULT_MIN_SALARY, estimate_salary_for_player(player))
        suggested_offer = max(
            DEFAULT_MIN_SALARY,
            int(round(expected_salary * max_mul)),
        )
        affordable = True
        if payroll_limit > 0:
            affordable = (payroll_total + suggested_offer) <= payroll_limit
        policy_check = evaluate_free_agent_signing(
            clean_team_id,
            annual_salary=suggested_offer,
            data_dir=resolved_data_dir,
            league_id=league_id,
        )
        if not policy_check.allowed:
            affordable = False

        quality = _player_talent_score(player)
        recommended_action = _ACTION_PASS
        if affordable and quality >= 74:
            recommended_action = _ACTION_TARGET
        elif affordable and quality >= 62:
            recommended_action = _ACTION_MONITOR

        decision_row = decisions_by_player.get(player_id, {})
        queue.append(
            {
                "player_id": player_id,
                "player_name": _player_name(player, fallback=player_id),
                "position": str(getattr(player, "primary_position", "") or ""),
                "age": _player_age(player),
                "quality": quality,
                "expected_salary": expected_salary,
                "salary_band_min": max(
                    DEFAULT_MIN_SALARY,
                    int(round(expected_salary * min_mul)),
                ),
                "salary_band_max": max(
                    DEFAULT_MIN_SALARY,
                    int(round(expected_salary * max_mul)),
                ),
                "suggested_offer": suggested_offer,
                "affordable": affordable,
                "policy_warning": bool(policy_check.warning),
                "policy_mode": str(policy_check.mode or ""),
                "recommended_action": recommended_action,
                "queued_action": str(decision_row.get("action") or "").strip(),
                "queued_at": str(decision_row.get("updated_at") or "").strip(),
                "queued_status": str(decision_row.get("review_status") or "").strip(),
            }
        )

    queue.sort(
        key=lambda row: (
            _fa_priority(str(row.get("recommended_action") or "")),
            -_safe_int(row.get("quality"), fallback=0),
            -_safe_int(row.get("expected_salary"), fallback=0),
            str(row.get("player_name") or row.get("player_id") or ""),
        )
    )
    max_rows = max(0, int(limit))
    if max_rows <= 0:
        return []
    return queue[:max_rows]


def list_team_queue_decisions(
    team_id: str,
    *,
    queue_type: str | None = None,
    data_dir: Path | str | None = None,
) -> list[Dict[str, object]]:
    """Return persisted queue decisions for *team_id*."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return []
    payload = _load_decisions_payload(data_dir=data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        return []
    team_payload = teams.get(clean_team_id)
    if not isinstance(team_payload, Mapping):
        return []

    rows: list[Dict[str, object]] = []
    queue_types = [_QUEUE_ARBITRATION, _QUEUE_FREE_AGENCY]
    if queue_type:
        queue_types = [str(queue_type or "").strip().lower()]
    for bucket_name in queue_types:
        bucket = team_payload.get(bucket_name)
        if not isinstance(bucket, Mapping):
            continue
        for item_id, raw in bucket.items():
            if not isinstance(raw, Mapping):
                continue
            rows.append(
                {
                    "team_id": clean_team_id,
                    "queue_type": bucket_name,
                    "item_id": str(item_id or "").strip(),
                    "action": str(raw.get("action") or "").strip(),
                    "notes": str(raw.get("notes") or "").strip(),
                    "updated_at": str(raw.get("updated_at") or "").strip(),
                    "review_status": _normalize_review_status(
                        raw.get("review_status")
                    ),
                    "applied": bool(
                        isinstance(raw.get("payload"), Mapping)
                        and bool(raw.get("payload", {}).get("applied"))
                    ),
                    "applied_at": (
                        str(raw.get("payload", {}).get("applied_at") or "").strip()
                        if isinstance(raw.get("payload"), Mapping)
                        else ""
                    ),
                    "payload": dict(raw.get("payload"))
                    if isinstance(raw.get("payload"), Mapping)
                    else {},
                }
            )
    rows.sort(
        key=lambda row: (
            str(row.get("queue_type") or ""),
            str(row.get("item_id") or ""),
        )
    )
    return rows


def list_queue_decisions(
    *,
    team_id: str | None = None,
    queue_type: str | None = None,
    review_status: str | None = None,
    data_dir: Path | str | None = None,
) -> list[Dict[str, object]]:
    """Return queue decisions across all teams with optional filters."""

    payload = _load_decisions_payload(data_dir=data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        return []
    clean_team_id = str(team_id or "").strip()
    queue_filters = {_QUEUE_ARBITRATION, _QUEUE_FREE_AGENCY}
    if queue_type:
        queue_filters = {_normalize_queue_type(queue_type)}
    status_filter = _normalize_review_status(review_status)
    rows: list[Dict[str, object]] = []
    for raw_team_id, team_payload in teams.items():
        if not isinstance(team_payload, Mapping):
            continue
        clean_row_team_id = str(raw_team_id or "").strip()
        if not clean_row_team_id:
            continue
        if clean_team_id and clean_row_team_id != clean_team_id:
            continue
        for bucket_name in queue_filters:
            bucket = team_payload.get(bucket_name)
            if not isinstance(bucket, Mapping):
                continue
            for item_id, raw in bucket.items():
                if not isinstance(raw, Mapping):
                    continue
                clean_item_id = str(item_id or "").strip()
                if not clean_item_id:
                    continue
                clean_status = _normalize_review_status(raw.get("review_status"))
                if status_filter and clean_status != status_filter:
                    continue
                payload_map = raw.get("payload")
                decision_payload = dict(payload_map) if isinstance(payload_map, Mapping) else {}
                rows.append(
                    {
                        "team_id": clean_row_team_id,
                        "queue_type": bucket_name,
                        "item_id": clean_item_id,
                        "action": str(raw.get("action") or "").strip(),
                        "notes": str(raw.get("notes") or "").strip(),
                        "updated_at": str(raw.get("updated_at") or "").strip(),
                        "review_status": clean_status,
                        "applied": bool(decision_payload.get("applied")),
                        "applied_at": str(decision_payload.get("applied_at") or "").strip(),
                        "payload": decision_payload,
                    }
                )
    rows.sort(
        key=lambda row: (
            _queue_status_priority(str(row.get("review_status") or "")),
            str(row.get("queue_type") or ""),
            str(row.get("team_id") or ""),
            str(row.get("item_id") or ""),
        )
    )
    return rows


def list_pending_queue_decisions(
    *,
    queue_type: str | None = None,
    data_dir: Path | str | None = None,
) -> list[Dict[str, object]]:
    """Return all pending-commissioner decisions across teams."""

    payload = _load_decisions_payload(data_dir=data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        return []
    queue_types = [_QUEUE_ARBITRATION, _QUEUE_FREE_AGENCY]
    if queue_type:
        queue_types = [str(queue_type or "").strip().lower()]

    rows: list[Dict[str, object]] = []
    for team_id, team_payload in teams.items():
        if not isinstance(team_payload, Mapping):
            continue
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            continue
        for bucket_name in queue_types:
            bucket = team_payload.get(bucket_name)
            if not isinstance(bucket, Mapping):
                continue
            for item_id, raw in bucket.items():
                if not isinstance(raw, Mapping):
                    continue
                review_status = _normalize_review_status(raw.get("review_status"))
                if review_status != _REVIEW_PENDING:
                    continue
                rows.append(
                    {
                        "team_id": clean_team_id,
                        "queue_type": bucket_name,
                        "item_id": str(item_id or "").strip(),
                        "action": str(raw.get("action") or "").strip(),
                        "notes": str(raw.get("notes") or "").strip(),
                        "updated_at": str(raw.get("updated_at") or "").strip(),
                        "review_status": review_status,
                        "payload": dict(raw.get("payload"))
                        if isinstance(raw.get("payload"), Mapping)
                        else {},
                    }
                )
    rows.sort(
        key=lambda row: (
            str(row.get("queue_type") or ""),
            str(row.get("team_id") or ""),
            str(row.get("item_id") or ""),
        )
    )
    return rows


def summarize_queue_decisions(
    *,
    team_id: str | None = None,
    queue_type: str | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, int]:
    """Return queue decision counts by review/applied status."""

    payload = _load_decisions_payload(data_dir=data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        return {
            "total": 0,
            "pending": 0,
            "approved": 0,
            "approved_unapplied": 0,
            "approved_applied": 0,
            "rejected": 0,
        }

    clean_team_id = str(team_id or "").strip()
    queue_filters = {_QUEUE_ARBITRATION, _QUEUE_FREE_AGENCY}
    if queue_type:
        queue_filters = {_normalize_queue_type(queue_type)}
    counters = {
        "total": 0,
        "pending": 0,
        "approved": 0,
        "approved_unapplied": 0,
        "approved_applied": 0,
        "rejected": 0,
    }
    for raw_team_id, team_payload in teams.items():
        if not isinstance(team_payload, Mapping):
            continue
        row_team_id = str(raw_team_id or "").strip()
        if not row_team_id:
            continue
        if clean_team_id and row_team_id != clean_team_id:
            continue
        for bucket_name in queue_filters:
            bucket = team_payload.get(bucket_name)
            if not isinstance(bucket, Mapping):
                continue
            for row in bucket.values():
                if not isinstance(row, Mapping):
                    continue
                counters["total"] += 1
                review_status = _normalize_review_status(row.get("review_status"))
                decision_payload = row.get("payload")
                applied = bool(
                    isinstance(decision_payload, Mapping)
                    and decision_payload.get("applied")
                )
                if review_status == _REVIEW_PENDING:
                    counters["pending"] += 1
                elif review_status in {_REVIEW_APPROVED, _REVIEW_APPROVED_COMMISSIONER}:
                    counters["approved"] += 1
                    if applied:
                        counters["approved_applied"] += 1
                    else:
                        counters["approved_unapplied"] += 1
                elif review_status == _REVIEW_REJECTED_COMMISSIONER:
                    counters["rejected"] += 1
    return counters


def set_queue_review_status(
    team_id: str,
    *,
    queue_type: str,
    item_id: str,
    review_status: str,
    notes: str | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object] | None:
    """Update review status for an existing queue decision row."""

    clean_team_id = str(team_id or "").strip()
    clean_item_id = str(item_id or "").strip()
    if not clean_team_id or not clean_item_id:
        return None
    clean_queue_type = _normalize_queue_type(queue_type)
    status = _normalize_review_status(review_status)
    if status not in {
        _REVIEW_PENDING,
        _REVIEW_APPROVED_COMMISSIONER,
        _REVIEW_REJECTED_COMMISSIONER,
        _REVIEW_APPROVED,
    }:
        raise ValueError(f"Unsupported review_status: {review_status}")

    payload = _load_decisions_payload(data_dir=data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        return None
    team_payload = teams.get(clean_team_id)
    if not isinstance(team_payload, dict):
        return None
    bucket = team_payload.get(clean_queue_type)
    if not isinstance(bucket, dict):
        return None
    row = bucket.get(clean_item_id)
    if not isinstance(row, dict):
        return None

    row["review_status"] = status
    if notes is not None:
        row["notes"] = str(notes or "").strip()
    row["updated_at"] = _timestamp()
    bucket[clean_item_id] = row
    team_payload[clean_queue_type] = bucket
    teams[clean_team_id] = team_payload
    payload["teams"] = teams
    _save_decisions_payload(payload, data_dir=data_dir)
    return {
        "team_id": clean_team_id,
        "queue_type": clean_queue_type,
        "item_id": clean_item_id,
        "action": str(row.get("action") or "").strip(),
        "notes": str(row.get("notes") or "").strip(),
        "updated_at": str(row.get("updated_at") or "").strip(),
        "review_status": str(row.get("review_status") or "").strip(),
        "payload": dict(row.get("payload")) if isinstance(row.get("payload"), Mapping) else {},
    }


def apply_approved_queue_decisions(
    *,
    team_id: str | None = None,
    queue_type: str | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Apply commissioner/local approved queue decisions in bulk."""

    resolved_data_dir = _resolve_data_dir(data_dir)
    payload = _load_decisions_payload(data_dir=resolved_data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        return {
            "applied": 0,
            "considered": 0,
            "skipped": 0,
            "by_queue": {},
            "message": "No queue decisions found.",
        }

    queue_filters = {_QUEUE_ARBITRATION, _QUEUE_FREE_AGENCY}
    if queue_type:
        queue_filters = {_normalize_queue_type(queue_type)}
    team_filter = str(team_id or "").strip()

    unsigned_map = _unsigned_players_by_id(resolved_data_dir)
    contracts_payload = load_contracts_payload(data_dir=resolved_data_dir)
    contracts = contracts_payload.get("players")
    if not isinstance(contracts, dict):
        contracts = {}
        contracts_payload["players"] = contracts

    applied = 0
    considered = 0
    skipped = 0
    by_queue = {
        _QUEUE_ARBITRATION: {"applied": 0, "considered": 0, "skipped": 0},
        _QUEUE_FREE_AGENCY: {"applied": 0, "considered": 0, "skipped": 0},
    }
    contracts_dirty = False
    touched_payload = False

    for raw_team_id, team_bucket in teams.items():
        clean_team_id = str(raw_team_id or "").strip()
        if not clean_team_id:
            continue
        if team_filter and clean_team_id != team_filter:
            continue
        if not isinstance(team_bucket, dict):
            continue
        for bucket_name in list(queue_filters):
            bucket = team_bucket.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            for item_id, row in bucket.items():
                clean_item_id = str(item_id or "").strip()
                if not clean_item_id:
                    continue
                if not isinstance(row, dict):
                    continue
                review_status = _normalize_review_status(row.get("review_status"))
                if review_status not in {
                    _REVIEW_APPROVED,
                    _REVIEW_APPROVED_COMMISSIONER,
                }:
                    continue
                decision_payload = row.get("payload")
                decision_payload = (
                    dict(decision_payload)
                    if isinstance(decision_payload, Mapping)
                    else {}
                )
                if bool(decision_payload.get("applied")):
                    continue
                considered += 1
                by_queue[bucket_name]["considered"] += 1
                action = _normalize_action(
                    bucket_name,
                    str(row.get("action") or "").strip(),
                )
                if contracts_dirty and _requires_external_contract_write(
                    bucket_name, action
                ):
                    save_contracts_payload(contracts_payload, data_dir=resolved_data_dir)
                    contracts_dirty = False
                if bucket_name == _QUEUE_ARBITRATION:
                    result = _apply_arbitration_decision(
                        clean_team_id,
                        clean_item_id,
                        action=action,
                        row_payload=decision_payload,
                        contracts=contracts,
                        data_dir=resolved_data_dir,
                    )
                else:
                    result = _apply_free_agency_decision(
                        clean_team_id,
                        clean_item_id,
                        action=action,
                        row_payload=decision_payload,
                        unsigned_map=unsigned_map,
                        data_dir=resolved_data_dir,
                    )
                contracts_dirty = contracts_dirty or bool(result.get("contracts_dirty"))
                if bool(result.get("contracts_external_write")):
                    contracts_payload = load_contracts_payload(data_dir=resolved_data_dir)
                    contracts = contracts_payload.get("players")
                    if not isinstance(contracts, dict):
                        contracts = {}
                        contracts_payload["players"] = contracts

                success = bool(result.get("applied"))
                if success:
                    applied += 1
                    by_queue[bucket_name]["applied"] += 1
                else:
                    skipped += 1
                    by_queue[bucket_name]["skipped"] += 1

                decision_payload["applied"] = success
                decision_payload["applied_at"] = _timestamp()
                decision_payload["execution"] = str(result.get("outcome") or "unknown")
                decision_payload["execution_note"] = str(
                    result.get("note") or ""
                ).strip()
                row["payload"] = decision_payload
                row["updated_at"] = _timestamp()
                bucket[clean_item_id] = row
                touched_payload = True
            team_bucket[bucket_name] = bucket
        teams[clean_team_id] = team_bucket

    if contracts_dirty:
        save_contracts_payload(contracts_payload, data_dir=resolved_data_dir)
    if touched_payload:
        payload["teams"] = teams
        _save_decisions_payload(payload, data_dir=resolved_data_dir)

    return {
        "applied": applied,
        "considered": considered,
        "skipped": skipped,
        "by_queue": by_queue,
        "message": f"Applied {applied} approved queue decisions (skipped {skipped}).",
    }


def save_team_queue_decision(
    team_id: str,
    *,
    queue_type: str,
    item_id: str,
    action: str,
    notes: str = "",
    review_status: str | None = None,
    payload: Mapping[str, object] | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Persist one queue decision and return the normalized row."""

    clean_team_id = str(team_id or "").strip()
    clean_item_id = str(item_id or "").strip()
    clean_queue_type = _normalize_queue_type(queue_type)
    if not clean_team_id:
        raise ValueError("team_id is required")
    if not clean_item_id:
        raise ValueError("item_id is required")
    clean_action = _normalize_action(clean_queue_type, action)
    clean_review_status = _normalize_review_status(review_status)
    if not clean_review_status:
        clean_review_status = _default_review_status(data_dir=data_dir)

    data = _load_decisions_payload(data_dir=data_dir)
    teams = data.get("teams")
    if not isinstance(teams, dict):
        teams = {}
        data["teams"] = teams
    team_payload = teams.get(clean_team_id)
    if not isinstance(team_payload, dict):
        team_payload = {}
        teams[clean_team_id] = team_payload
    bucket = team_payload.get(clean_queue_type)
    if not isinstance(bucket, dict):
        bucket = {}
        team_payload[clean_queue_type] = bucket

    row = {
        "action": clean_action,
        "notes": str(notes or "").strip(),
        "review_status": clean_review_status,
        "updated_at": _timestamp(),
        "payload": dict(payload) if isinstance(payload, Mapping) else {},
    }
    bucket[clean_item_id] = row
    _save_decisions_payload(data, data_dir=data_dir)

    return {
        "team_id": clean_team_id,
        "queue_type": clean_queue_type,
        "item_id": clean_item_id,
        "action": clean_action,
        "notes": row["notes"],
        "review_status": row["review_status"],
        "updated_at": row["updated_at"],
        "payload": dict(row["payload"]),
    }


def apply_recommended_arbitration_decisions(
    team_id: str,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Persist recommended arbitration actions for all queue rows."""

    requires_review = _requires_commissioner_review(data_dir=data_dir)
    review_status = _REVIEW_PENDING if requires_review else _REVIEW_APPROVED
    queue = build_arbitration_queue(
        team_id,
        data_dir=data_dir,
        league_id=league_id,
    )
    queued = 0
    for row in queue:
        action = str(row.get("recommended_action") or "").strip()
        player_id = str(row.get("player_id") or "").strip()
        if not action or not player_id:
            continue
        save_team_queue_decision(
            team_id,
            queue_type=_QUEUE_ARBITRATION,
            item_id=player_id,
            action=action,
            notes="Applied recommended arbitration action",
            review_status=review_status,
            payload={
                "decision_code": row.get("decision_code"),
                "projected_salary": row.get("projected_salary"),
                "current_salary": row.get("current_salary"),
            },
            data_dir=data_dir,
        )
        queued += 1
    auto_applied = False
    apply_summary = {
        "applied": 0,
        "considered": 0,
        "skipped": 0,
        "by_queue": {},
        "message": "",
    }
    if (not requires_review) and queued > 0:
        apply_summary = apply_approved_queue_decisions(
            team_id=team_id,
            queue_type=_QUEUE_ARBITRATION,
            data_dir=data_dir,
        )
        auto_applied = True
    return {
        "queued_count": queued,
        "total_candidates": len(queue),
        "review_status": review_status,
        "auto_applied": auto_applied,
        "apply_summary": apply_summary,
        "message": (
            f"Queued {queued} arbitration decisions for commissioner review."
            if requires_review
            else (
                f"Applied {int(apply_summary.get('applied', 0) or 0)} arbitration decisions "
                f"for single-player mode."
            )
        ),
    }


def apply_recommended_free_agency_targets(
    team_id: str,
    *,
    limit: int = 10,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Persist recommended free-agency actions for target rows."""

    requires_review = _requires_commissioner_review(data_dir=data_dir)
    review_status = _REVIEW_PENDING if requires_review else _REVIEW_APPROVED
    queue = build_free_agency_queue(
        team_id,
        limit=max(0, int(limit)),
        data_dir=data_dir,
        league_id=league_id,
    )
    queued = 0
    for row in queue:
        action = str(row.get("recommended_action") or "").strip()
        if action not in {_ACTION_TARGET, _ACTION_MONITOR, _ACTION_PASS}:
            continue
        player_id = str(row.get("player_id") or "").strip()
        if not player_id:
            continue
        save_team_queue_decision(
            team_id,
            queue_type=_QUEUE_FREE_AGENCY,
            item_id=player_id,
            action=action,
            notes="Applied recommended free-agency action",
            review_status=review_status,
            payload={
                "expected_salary": row.get("expected_salary"),
                "suggested_offer": row.get("suggested_offer"),
                "quality": row.get("quality"),
            },
            data_dir=data_dir,
        )
        queued += 1
    auto_applied = False
    apply_summary = {
        "applied": 0,
        "considered": 0,
        "skipped": 0,
        "by_queue": {},
        "message": "",
    }
    if (not requires_review) and queued > 0:
        apply_summary = apply_approved_queue_decisions(
            team_id=team_id,
            queue_type=_QUEUE_FREE_AGENCY,
            data_dir=data_dir,
        )
        auto_applied = True
    return {
        "queued_count": queued,
        "total_candidates": len(queue),
        "review_status": review_status,
        "auto_applied": auto_applied,
        "apply_summary": apply_summary,
        "message": (
            f"Queued {queued} free-agency decisions for commissioner review."
            if requires_review
            else (
                f"Applied {int(apply_summary.get('applied', 0) or 0)} free-agency decisions "
                f"for single-player mode."
            )
        ),
    }


def _apply_arbitration_decision(
    team_id: str,
    player_id: str,
    *,
    action: str,
    row_payload: Mapping[str, object],
    contracts: dict[str, object],
    data_dir: Path,
) -> Dict[str, object]:
    contract = contracts.get(player_id)
    if not isinstance(contract, dict):
        return {
            "applied": False,
            "outcome": "missing_contract",
            "note": "Contract not found for decision item.",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }
    if str(contract.get("team_id") or "").strip() != team_id:
        return {
            "applied": False,
            "outcome": "team_mismatch",
            "note": "Contract team no longer matches decision team.",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }

    current_salary = max(
        DEFAULT_MIN_SALARY,
        _safe_int(contract.get("annual_salary"), fallback=DEFAULT_MIN_SALARY),
    )
    if action == _ACTION_NON_TENDER:
        policy = evaluate_payroll_delta(
            team_id,
            annual_delta=-current_salary,
            data_dir=data_dir,
        )
        if not policy.allowed:
            record_payroll_policy_result(
                policy,
                action="gm_queue_non_tender",
                data_dir=data_dir,
            )
            return {
                "applied": False,
                "outcome": "policy_blocked",
                "note": "Payroll policy blocked non-tender decision.",
                "contracts_dirty": False,
                "contracts_external_write": False,
            }
        if policy.warning:
            record_payroll_policy_result(
                policy,
                action="gm_queue_non_tender",
                data_dir=data_dir,
            )
        summary = release_contracts_to_free_agency([player_id], data_dir=data_dir)
        contracts.pop(player_id, None)
        try:
            record_transaction(
                action="gm_finance_non_tender",
                team_id=team_id,
                player_id=player_id,
                from_level="ACT",
                to_level="FA",
                details="Applied approved GM finance non-tender decision",
                path=data_dir / "transactions.csv",
            )
        except Exception:
            pass
        return {
            "applied": True,
            "outcome": "non_tendered",
            "note": (
                f"Released contract (removed {int(summary.get('released_contracts', 0) or 0)} contract row)."
            ),
            "contracts_dirty": False,
            "contracts_external_write": True,
        }

    if action == _ACTION_OFFER_RAISE:
        target_salary = _safe_int(
            row_payload.get("projected_salary"),
            fallback=current_salary,
        )
        target_salary = max(DEFAULT_MIN_SALARY, target_salary)
        delta = max(0, target_salary - current_salary)
        policy = evaluate_payroll_delta(
            team_id,
            annual_delta=delta,
            data_dir=data_dir,
        )
        if not policy.allowed:
            record_payroll_policy_result(
                policy,
                action="gm_queue_arb_raise",
                data_dir=data_dir,
            )
            return {
                "applied": False,
                "outcome": "policy_blocked",
                "note": "Payroll policy blocked arbitration raise.",
                "contracts_dirty": False,
                "contracts_external_write": False,
            }
        if policy.warning:
            record_payroll_policy_result(
                policy,
                action="gm_queue_arb_raise",
                data_dir=data_dir,
            )
        contract["annual_salary"] = target_salary
        contracts[player_id] = contract
        try:
            record_transaction(
                action="gm_finance_arb_update",
                team_id=team_id,
                player_id=player_id,
                from_level="ARB",
                to_level="ARB",
                details=f"Approved arbitration salary update to ${target_salary:,}",
                path=data_dir / "transactions.csv",
            )
        except Exception:
            pass
        return {
            "applied": True,
            "outcome": "salary_updated",
            "note": f"Updated salary from ${current_salary:,} to ${target_salary:,}.",
            "contracts_dirty": True,
            "contracts_external_write": False,
        }

    # hold
    try:
        record_transaction(
            action="gm_finance_arb_hold",
            team_id=team_id,
            player_id=player_id,
            from_level="ARB",
            to_level="ARB",
            details="Approved arbitration hold decision (no salary change)",
            path=data_dir / "transactions.csv",
        )
    except Exception:
        pass
    return {
        "applied": True,
        "outcome": "salary_held",
        "note": "Held salary at current value.",
        "contracts_dirty": False,
        "contracts_external_write": False,
    }


def _apply_free_agency_decision(
    team_id: str,
    player_id: str,
    *,
    action: str,
    row_payload: Mapping[str, object],
    unsigned_map: Mapping[str, object],
    data_dir: Path,
) -> Dict[str, object]:
    if action in {_ACTION_MONITOR, _ACTION_PASS}:
        return {
            "applied": True,
            "outcome": action,
            "note": "Decision recorded without signing.",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }

    if action != _ACTION_TARGET:
        return {
            "applied": False,
            "outcome": "unsupported_action",
            "note": f"Unsupported free-agency action: {action}",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }

    player = unsigned_map.get(player_id)
    if player is None:
        return {
            "applied": False,
            "outcome": "player_not_unsigned",
            "note": "Player is no longer unsigned.",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }

    roster_level = _add_player_to_team_roster(
        team_id,
        player_id,
        data_dir=data_dir,
    )
    if not roster_level:
        return {
            "applied": False,
            "outcome": "roster_full",
            "note": "No roster slot available for target signing.",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }

    annual_salary = _safe_int(
        row_payload.get("suggested_offer"),
        fallback=estimate_salary_for_player(player),
    )
    annual_salary = max(DEFAULT_MIN_SALARY, annual_salary)
    policy = evaluate_free_agent_signing(
        team_id,
        annual_salary=annual_salary,
        data_dir=data_dir,
    )
    if not policy.allowed:
        record_payroll_policy_result(
            policy,
            action="gm_queue_target_signing",
            data_dir=data_dir,
        )
        return {
            "applied": False,
            "outcome": "policy_blocked",
            "note": "Payroll policy blocked free-agent target signing.",
            "contracts_dirty": False,
            "contracts_external_write": False,
        }
    if policy.warning:
        record_payroll_policy_result(
            policy,
            action="gm_queue_target_signing",
            data_dir=data_dir,
        )
    sign_free_agent_contract(
        player_id,
        team_id,
        annual_salary=annual_salary,
        player=player,
        data_dir=data_dir,
    )
    try:
        record_transaction(
            action="gm_finance_target_signing",
            team_id=team_id,
            player_id=player_id,
            from_level="FA",
            to_level=roster_level,
            details=f"Approved GM finance target signing (${annual_salary:,})",
            path=data_dir / "transactions.csv",
        )
    except Exception:
        pass
    return {
        "applied": True,
        "outcome": "signed",
        "note": f"Signed target to {roster_level} at ${annual_salary:,}.",
        "contracts_dirty": False,
        "contracts_external_write": True,
    }


def _requires_external_contract_write(queue_type: str, action: str) -> bool:
    return (
        (queue_type == _QUEUE_ARBITRATION and action == _ACTION_NON_TENDER)
        or (queue_type == _QUEUE_FREE_AGENCY and action == _ACTION_TARGET)
    )


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    return get_data_dir() if data_dir is None else Path(data_dir)


def _decisions_path(*, data_dir: Path | str | None = None) -> Path:
    return _resolve_data_dir(data_dir) / _FILENAME


def _load_decisions_payload(*, data_dir: Path | str | None = None) -> Dict[str, object]:
    path = _decisions_path(data_dir=data_dir)
    if not path.exists():
        return {"version": _VERSION, "teams": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": _VERSION, "teams": {}}
    if not isinstance(payload, dict):
        return {"version": _VERSION, "teams": {}}
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        payload["teams"] = {}
    payload["version"] = _VERSION
    return payload


def _save_decisions_payload(
    payload: Mapping[str, object],
    *,
    data_dir: Path | str | None = None,
) -> None:
    path = _decisions_path(data_dir=data_dir)
    teams = payload.get("teams") if isinstance(payload, Mapping) else None
    normalized = {
        "version": _VERSION,
        "teams": dict(teams) if isinstance(teams, Mapping) else {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def _normalize_queue_type(queue_type: str) -> str:
    token = str(queue_type or "").strip().lower()
    if token in {_QUEUE_ARBITRATION, _QUEUE_FREE_AGENCY}:
        return token
    raise ValueError(f"Unsupported queue_type: {queue_type}")


def _normalize_action(queue_type: str, action: str) -> str:
    token = str(action or "").strip().lower()
    allowed = {
        _QUEUE_ARBITRATION: {
            _ACTION_OFFER_RAISE,
            _ACTION_HOLD,
            _ACTION_NON_TENDER,
        },
        _QUEUE_FREE_AGENCY: {
            _ACTION_TARGET,
            _ACTION_MONITOR,
            _ACTION_PASS,
        },
    }
    choices = allowed.get(queue_type, set())
    if token in choices:
        return token
    if queue_type == _QUEUE_ARBITRATION:
        return _ACTION_HOLD
    return _ACTION_MONITOR


def _requires_commissioner_review(*, data_dir: Path | str | None = None) -> bool:
    resolved = _resolve_data_dir(data_dir)
    settings = load_league_settings(resolved / "league_settings.json")
    return bool(is_owner_league(settings))


def _default_review_status(*, data_dir: Path | str | None = None) -> str:
    return _REVIEW_PENDING if _requires_commissioner_review(data_dir=data_dir) else _REVIEW_APPROVED


def _normalize_review_status(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in {
        _REVIEW_PENDING,
        _REVIEW_APPROVED,
        _REVIEW_APPROVED_COMMISSIONER,
        _REVIEW_REJECTED_COMMISSIONER,
    }:
        return token
    return ""


def _safe_int(value: object, *, fallback: int) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return fallback


def _load_players_by_id(data_dir: Path) -> Dict[str, object]:
    try:
        players = load_players_from_csv(data_dir / "players.csv")
    except Exception:
        return {}
    result: Dict[str, object] = {}
    for player in players:
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        result[player_id] = player
    return result


def _unsigned_players_by_id(data_dir: Path) -> Dict[str, object]:
    try:
        players = list_unsigned_players_from_files(data_dir=data_dir)
    except Exception:
        return {}
    result: Dict[str, object] = {}
    for player in players:
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        result[player_id] = player
    return result


def _player_name(player: object | None, *, fallback: str) -> str:
    if player is None:
        return fallback
    first_name = str(getattr(player, "first_name", "") or "").strip()
    last_name = str(getattr(player, "last_name", "") or "").strip()
    return f"{first_name} {last_name}".strip() or fallback


def _is_arb_eligible(
    years_left: int,
    service_time_days: int,
    *,
    arbitration_level: str,
) -> bool:
    token = str(arbitration_level or "").strip().lower()
    if years_left <= 1 and service_time_days >= _ARB_ELIGIBILITY_DAYS:
        return True
    if token == "advanced" and years_left <= 2 and service_time_days >= _SUPER_TWO_ELIGIBILITY_DAYS:
        return True
    return False


def _player_talent_score(player: object | None) -> int:
    if player is None:
        return 60
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).upper() == "P"
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
    ratings = [value for value in values if value > 0]
    if not ratings:
        return 60
    return max(20, min(95, int(round(sum(ratings) / len(ratings)))))


def _player_performance_score(player: object | None) -> int:
    if player is None:
        return 55
    season_stats = getattr(player, "season_stats", None)
    if not isinstance(season_stats, Mapping):
        return max(40, min(90, _player_talent_score(player) - 5))
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).upper() == "P"
    if is_pitcher:
        era = _safe_float(season_stats.get("era"), fallback=4.20)
        if era <= 2.60:
            return 82
        if era <= 3.50:
            return 72
        if era >= 5.30:
            return 40
        if era >= 4.60:
            return 48
        return 60
    ops = _safe_float(season_stats.get("ops"), fallback=0.0)
    if ops <= 0.0:
        obp = _safe_float(season_stats.get("obp"), fallback=0.0)
        slg = _safe_float(season_stats.get("slg"), fallback=0.0)
        ops = obp + slg
    if ops >= 0.900:
        return 82
    if ops >= 0.800:
        return 72
    if ops <= 0.650 and ops > 0:
        return 40
    if ops <= 0.720 and ops > 0:
        return 48
    return 60


def _safe_float(value: object, *, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _arb_priority(action: str) -> int:
    if action == _ACTION_NON_TENDER:
        return 0
    if action == _ACTION_OFFER_RAISE:
        return 1
    return 2


def _fa_priority(action: str) -> int:
    if action == _ACTION_TARGET:
        return 0
    if action == _ACTION_MONITOR:
        return 1
    return 2


def _queue_status_priority(status: str) -> int:
    token = str(status or "").strip().lower()
    if token == _REVIEW_PENDING:
        return 0
    if token == _REVIEW_APPROVED_COMMISSIONER:
        return 1
    if token == _REVIEW_APPROVED:
        return 2
    if token == _REVIEW_REJECTED_COMMISSIONER:
        return 3
    return 4


def _payroll_limit_for_level(level: str) -> int:
    token = str(level or "").strip().lower()
    if token == LEVEL_OFF:
        return 0
    if token == "basic":
        return 220_000_000
    if token == "mlb_like":
        return 260_000_000
    return 240_000_000


def _player_age(player: object) -> int:
    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if not birthdate:
        return 0
    try:
        born = datetime.strptime(birthdate[:10], "%Y-%m-%d").date()
        today = datetime.utcnow().date()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return 0


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
