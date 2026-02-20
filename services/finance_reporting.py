"""Commissioner-facing finance reporting and alert helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping

from services.finance_settings import LEVEL_OFF, load_financial_settings
from services.offseason_finance_flow import (
    collect_offseason_finance_overview,
    get_offseason_checklist,
)
from services.owner_finance_engine import project_monthly_owner_finance
from services.payroll_engine import calculate_annual_payroll_totals
from services.payroll_policy import build_payroll_limit_context
from utils.path_utils import get_data_dir

__all__ = [
    "build_commissioner_projection_report",
    "build_finance_alerts",
]

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def build_commissioner_projection_report(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    top_n: int = 5,
) -> Dict[str, object]:
    """Build a compact commissioner finance report for UI preview panels."""

    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    projections = project_monthly_owner_finance(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    payroll_totals = calculate_annual_payroll_totals(data_dir=resolved_data_dir)
    payroll_context = build_payroll_limit_context(
        data_dir=resolved_data_dir,
        league_id=league_id,
        annual_totals=payroll_totals,
        monthly_projection=projections,
    )
    overview = collect_offseason_finance_overview(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    checklist = get_offseason_checklist(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    stage_labels = _stage_labels(checklist.get("stages"))
    next_stage_id = str(checklist.get("next_stage_id") or "").strip()

    team_ids = set(str(team_id).strip() for team_id in projections.keys())
    team_ids.update(str(team_id).strip() for team_id in payroll_totals.keys())
    team_ids.update(
        str(team_id).strip()
        for team_id in (payroll_context.get("teams") or {}).keys()
    )
    team_ids.discard("")

    rows: list[Dict[str, object]] = []
    total_cash = 0
    total_debt = 0
    for team_id in sorted(team_ids):
        snapshot = projections.get(team_id)
        projected_net = _safe_int(getattr(snapshot, "projected_net", 0))
        cash_on_hand = _safe_int(getattr(snapshot, "cash_on_hand", 0))
        debt = _safe_int(getattr(snapshot, "debt", 0))
        annual_payroll = max(0, _safe_int(payroll_totals.get(team_id, 0)))
        payroll_row = _as_mapping((payroll_context.get("teams") or {}).get(team_id))
        threshold = max(0, _safe_int(payroll_row.get("threshold", 0)))
        floor = max(0, _safe_int(payroll_row.get("floor", 0)))
        over_threshold = max(0, _safe_int(payroll_row.get("over_threshold", 0)))
        under_floor = max(0, _safe_int(payroll_row.get("under_floor", 0)))
        threshold_ratio = _safe_float(payroll_row.get("threshold_ratio", 0.0))
        floor_ratio = _safe_float(payroll_row.get("floor_ratio", 0.0))

        rows.append(
            {
                "team_id": team_id,
                "cash_on_hand": cash_on_hand,
                "debt": debt,
                "projected_net": projected_net,
                "annual_payroll": annual_payroll,
                "payroll_threshold": threshold,
                "payroll_floor": floor,
                "over_threshold": over_threshold,
                "under_floor": under_floor,
                "threshold_ratio": threshold_ratio,
                "floor_ratio": floor_ratio,
            }
        )
        total_cash += cash_on_hand
        total_debt += debt

    rows_by_net_desc = sorted(rows, key=lambda row: int(row.get("projected_net", 0)), reverse=True)
    rows_by_net_asc = sorted(rows, key=lambda row: int(row.get("projected_net", 0)))
    top_count = max(1, int(top_n))
    top_surplus = rows_by_net_desc[:top_count]
    top_deficit = rows_by_net_asc[:top_count]

    teams_with_negative_net = sum(1 for row in rows if int(row.get("projected_net", 0)) < 0)
    teams_with_cash_risk = sum(
        1
        for row in rows
        if int(row.get("cash_on_hand", 0)) <= 1_500_000 and int(row.get("projected_net", 0)) < 0
    )
    teams_over_threshold = sum(1 for row in rows if int(row.get("over_threshold", 0)) > 0)
    teams_under_floor = sum(1 for row in rows if int(row.get("under_floor", 0)) > 0)
    avg_net = int(round(sum(int(row.get("projected_net", 0)) for row in rows) / float(len(rows)))) if rows else 0

    return {
        "league_id": settings.league_id,
        "enabled": bool(settings.enabled),
        "preset": settings.preset,
        "enforcement_mode": settings.enforcement_mode,
        "modules": dict(settings.modules),
        "payroll_rule_level": str(payroll_context.get("level") or LEVEL_OFF),
        "summary": {
            "team_count": len(rows),
            "average_projected_net": avg_net,
            "total_cash_on_hand": total_cash,
            "total_debt": total_debt,
            "teams_negative_net": teams_with_negative_net,
            "teams_cash_risk": teams_with_cash_risk,
            "teams_over_threshold": teams_over_threshold,
            "teams_under_floor": teams_under_floor,
        },
        "teams": rows,
        "top_surplus_teams": top_surplus,
        "top_deficit_teams": top_deficit,
        "offseason": {
            "phase": str(overview.get("phase", "UNKNOWN")),
            "can_run_now": bool(overview.get("can_run_now", False)),
            "requires_commissioner_finance_review": bool(
                overview.get("requires_commissioner_finance_review", False)
            ),
            "gm_queue_pending": _safe_int(overview.get("gm_queue_pending", 0)),
            "gm_queue_approved_unapplied": _safe_int(
                overview.get("gm_queue_approved_unapplied", 0)
            ),
            "arbitration_candidates": _safe_int(overview.get("arbitration_candidates", 0)),
            "unsigned_players": _safe_int(overview.get("unsigned_players", 0)),
            "next_stage_id": next_stage_id,
            "next_stage_label": stage_labels.get(next_stage_id, "None"),
        },
    }


def build_finance_alerts(
    *,
    report: Mapping[str, object] | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    limit: int = 12,
) -> list[Dict[str, str]]:
    """Return prioritized finance alerts with explicit next-step guidance."""

    active_report = (
        dict(report)
        if isinstance(report, Mapping)
        else build_commissioner_projection_report(
            data_dir=data_dir,
            league_id=league_id,
        )
    )
    alerts: list[Dict[str, str]] = []

    teams = active_report.get("teams")
    rows = [row for row in teams if isinstance(row, Mapping)] if isinstance(teams, list) else []
    modules = _as_mapping(active_report.get("modules"))
    offseason = _as_mapping(active_report.get("offseason"))
    payroll_rule_level = str(active_report.get("payroll_rule_level") or LEVEL_OFF).strip().lower()

    for row in rows:
        team_id = str(row.get("team_id") or "").strip()
        if not team_id:
            continue
        cash = _safe_int(row.get("cash_on_hand", 0))
        debt = _safe_int(row.get("debt", 0))
        net = _safe_int(row.get("projected_net", 0))
        over_threshold = _safe_int(row.get("over_threshold", 0))
        under_floor = _safe_int(row.get("under_floor", 0))
        threshold_ratio = _safe_float(row.get("threshold_ratio", 0.0))
        floor_ratio = _safe_float(row.get("floor_ratio", 0.0))

        if cash <= 1_500_000 and net < 0:
            alerts.append(
                _alert(
                    severity="critical",
                    title=f"{team_id}: Cashflow Risk",
                    message=(
                        f"Cash is ${cash:,} with projected monthly net {net:+,}. "
                        "Current trend can force additional debt."
                    ),
                    next_step=(
                        "Increase owner budgets selectively, reduce payroll commitments, "
                        "or move high-salary contracts."
                    ),
                )
            )
        elif debt >= 30_000_000 and net < 0:
            alerts.append(
                _alert(
                    severity="warning",
                    title=f"{team_id}: Debt Pressure",
                    message=f"Debt is ${debt:,} and projected monthly net is {net:+,}.",
                    next_step="Cut recurring expenses or clear salary before adding new contracts.",
                )
            )

        if over_threshold > 0:
            alerts.append(
                _alert(
                    severity="critical",
                    title=f"{team_id}: Payroll Over Threshold",
                    message=(
                        f"Payroll exceeds threshold by ${over_threshold:,} "
                        f"(current ratio {threshold_ratio:.2f}x)."
                    ),
                    next_step="Use trades/non-tenders or delay signings to return under threshold.",
                )
            )
        elif payroll_rule_level != LEVEL_OFF and threshold_ratio >= 0.90:
            alerts.append(
                _alert(
                    severity="warning",
                    title=f"{team_id}: Payroll Near Threshold",
                    message=f"Payroll is at {threshold_ratio:.0%} of threshold.",
                    next_step="Review pending arbitration/free-agency actions before approving.",
                )
            )

        if under_floor > 0:
            alerts.append(
                _alert(
                    severity="critical",
                    title=f"{team_id}: Payroll Under Floor",
                    message=(
                        f"Payroll is ${under_floor:,} under floor "
                        f"(current ratio {floor_ratio:.2f}x)."
                    ),
                    next_step="Add contracts or retain arbitration players before offseason finalization.",
                )
            )
        elif payroll_rule_level == "mlb_like" and floor_ratio > 0 and floor_ratio < 1.10:
            alerts.append(
                _alert(
                    severity="warning",
                    title=f"{team_id}: Payroll Near Floor",
                    message=f"Payroll is only {floor_ratio:.0%} of floor target.",
                    next_step="Track free-agency and arbitration outcomes to avoid floor penalties.",
                )
            )

    if bool(offseason.get("can_run_now", False)):
        next_stage_id = str(offseason.get("next_stage_id") or "").strip()
        next_stage_label = str(offseason.get("next_stage_label") or "None").strip()
        if next_stage_id:
            alerts.append(
                _alert(
                    severity="warning",
                    title="Offseason Checklist Pending",
                    message=f"Next required stage is '{next_stage_label}'.",
                    next_step=f"Open Offseason Finance Workflow and complete '{next_stage_label}'.",
                )
            )
        gm_pending = _safe_int(offseason.get("gm_queue_pending", 0))
        gm_unapplied = _safe_int(offseason.get("gm_queue_approved_unapplied", 0))
        if bool(offseason.get("requires_commissioner_finance_review", False)) and (
            gm_pending > 0 or gm_unapplied > 0
        ):
            alerts.append(
                _alert(
                    severity="warning",
                    title="GM Finance Queue Needs Review",
                    message=(
                        f"Pending decisions: {gm_pending}; approved-not-applied: {gm_unapplied}."
                    ),
                    next_step="Open GM Finance Queue and resolve all pending/approved items.",
                )
            )
        if _safe_int(offseason.get("arbitration_candidates", 0)) > 0 and str(
            modules.get("gm_arbitration", LEVEL_OFF)
        ).strip().lower() != LEVEL_OFF:
            alerts.append(
                _alert(
                    severity="info",
                    title="Arbitration Deadline Window",
                    message=(
                        f"{_safe_int(offseason.get('arbitration_candidates', 0))} arbitration candidate(s) "
                        "are in the current offseason window."
                    ),
                    next_step="Review arbitration details before free-agency kickoff.",
                )
            )
        if _safe_int(offseason.get("unsigned_players", 0)) > 0 and str(
            modules.get("gm_free_agency", LEVEL_OFF)
        ).strip().lower() != LEVEL_OFF:
            alerts.append(
                _alert(
                    severity="info",
                    title="Free-Agency Market Active",
                    message=(
                        f"{_safe_int(offseason.get('unsigned_players', 0))} unsigned player(s) available."
                    ),
                    next_step="Review FA queue recommendations and launch Free Agency Hub.",
                )
            )

    if not alerts:
        alerts.append(
            _alert(
                severity="info",
                title="No Immediate Finance Alerts",
                message="No threshold, cash-risk, or deadline issues detected right now.",
                next_step="Continue monitoring projections and re-check after major transactions.",
            )
        )

    alerts.sort(
        key=lambda row: (
            _SEVERITY_ORDER.get(str(row.get("severity") or "info"), 3),
            str(row.get("title") or ""),
        )
    )
    return alerts[: max(1, int(limit))]


def _stage_labels(stages: object) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    if not isinstance(stages, list):
        return labels
    for row in stages:
        if not isinstance(row, Mapping):
            continue
        stage_id = str(row.get("id") or "").strip()
        if not stage_id:
            continue
        labels[stage_id] = str(row.get("label") or stage_id).strip()
    return labels


def _alert(*, severity: str, title: str, message: str, next_step: str) -> Dict[str, str]:
    return {
        "severity": str(severity or "info").strip().lower(),
        "title": str(title or "").strip(),
        "message": str(message or "").strip(),
        "next_step": str(next_step or "").strip(),
    }


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0

