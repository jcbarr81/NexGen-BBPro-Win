"""Owner-finance projection and monthly accrual helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, Mapping
import calendar

from services.finance_ledger import (
    CATEGORY_FINANCE_CYCLE,
    LEDGER_TEAM_SYSTEM,
    append_financial_rows,
    build_finance_cycle_marker_row,
    build_team_expense_row,
    build_team_revenue_row,
    ledger_has_entry,
    list_financial_rows,
)
from services.finance_settings import (
    load_financial_settings,
    ensure_financial_defaults,
)
from services.payroll_engine import calculate_monthly_payroll_totals
from utils.path_utils import get_data_dir

__all__ = [
    "TeamFinanceSnapshot",
    "project_monthly_owner_finance",
    "get_team_finance_snapshot",
    "list_team_financial_transactions",
    "update_team_budget_targets",
    "apply_owner_finance_cadence_for_dates",
    "apply_monthly_owner_finance",
    "period_keys_from_dates",
    "apply_monthly_owner_finance_for_dates",
]

_REVENUE_CATEGORIES = ("tickets", "concessions", "media", "sponsorship")
_EXPENSE_CATEGORIES = ("payroll", "training", "scouting", "facilities", "operations")
_BUDGET_CATEGORIES = ("training", "scouting", "development", "facilities")
_OFF = "off"

_BASIC_MONTHLY_REVENUE = {
    "tickets": 900_000,
    "concessions": 180_000,
    "media": 250_000,
    "sponsorship": 150_000,
}
_BASIC_MONTHLY_EXPENSES = {
    "training": 110_000,
    "scouting": 90_000,
    "facilities": 95_000,
    "operations": 240_000,
}
_ADVANCED_MONTHLY_REVENUE = {
    "tickets": 1_050_000,
    "concessions": 230_000,
    "media": 320_000,
    "sponsorship": 220_000,
}
_ADVANCED_MONTHLY_EXPENSES = {
    "training": 140_000,
    "scouting": 120_000,
    "facilities": 130_000,
    "operations": 290_000,
}
_BASIC_BUDGET_SPLIT = {
    "training": 0.10,
    "scouting": 0.08,
    "development": 0.07,
    "facilities": 0.08,
}
_ADVANCED_BUDGET_SPLIT = {
    "training": 0.12,
    "scouting": 0.10,
    "development": 0.09,
    "facilities": 0.10,
}

_DEFAULT_HOME_GAMES_PER_MONTH = 13.5
_DEFAULT_AWAY_GAMES_PER_MONTH = 13.5
_HOME_GAME_VOLUME_MIN = 0.75
_HOME_GAME_VOLUME_MAX = 1.35
_HOME_FORM_MIN = 0.85
_HOME_FORM_MAX = 1.15
_ATTENDANCE_MIN = 0.70
_ATTENDANCE_MAX = 1.55
_FAN_INTEREST_MIN = 0.82
_FAN_INTEREST_MAX = 1.22
_AWAY_TRAVEL_MIN = 0.80
_AWAY_TRAVEL_MAX = 1.25
_FACILITY_LOAD_MIN = 0.85
_FACILITY_LOAD_MAX = 1.20


@dataclass(frozen=True)
class TeamFinanceSnapshot:
    team_id: str
    cash_on_hand: int
    debt: int
    revenue_totals: Dict[str, int]
    expense_totals: Dict[str, int]
    budgets: Dict[str, int]
    projected_revenue: Dict[str, int]
    projected_expenses: Dict[str, int]
    projected_budgets: Dict[str, int]
    projected_net: int
    financials_enabled: bool
    preset: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "team_id": self.team_id,
            "cash_on_hand": self.cash_on_hand,
            "debt": self.debt,
            "revenue_totals": dict(self.revenue_totals),
            "expense_totals": dict(self.expense_totals),
            "budgets": dict(self.budgets),
            "projected_revenue": dict(self.projected_revenue),
            "projected_expenses": dict(self.projected_expenses),
            "projected_budgets": dict(self.projected_budgets),
            "projected_net": self.projected_net,
            "financials_enabled": self.financials_enabled,
            "preset": self.preset,
        }


def project_monthly_owner_finance(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, TeamFinanceSnapshot]:
    """Return monthly projections for all teams in the current league."""

    resolved_data_dir = _resolve_data_dir(data_dir)
    ensure_financial_defaults(data_dir=resolved_data_dir, league_id=league_id)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    financials = _load_team_financials(resolved_data_dir)
    standings = _load_standings(resolved_data_dir)
    schedule_metrics = _load_schedule_team_metrics(resolved_data_dir)
    payroll = calculate_monthly_payroll_totals(data_dir=resolved_data_dir)

    snapshots: Dict[str, TeamFinanceSnapshot] = {}
    teams = financials.get("teams")
    if not isinstance(teams, Mapping):
        return snapshots
    for team_id, raw_entry in teams.items():
        clean_team_id = str(team_id).strip()
        if not clean_team_id:
            continue
        entry = _normalize_team_entry(raw_entry)
        projected_revenue = _project_revenue(
            settings=settings,
            team_id=clean_team_id,
            standings=standings,
            schedule_team_metric=schedule_metrics.get(clean_team_id, {}),
        )
        projected_expenses = _project_expenses(
            settings=settings,
            team_id=clean_team_id,
            standings=standings,
            payroll_monthly=payroll.get(clean_team_id, 0),
            schedule_team_metric=schedule_metrics.get(clean_team_id, {}),
        )
        projected_budgets = _project_budgets(
            settings=settings,
            projected_revenue=projected_revenue,
        )
        projected_net = sum(projected_revenue.values()) - sum(projected_expenses.values())

        snapshots[clean_team_id] = TeamFinanceSnapshot(
            team_id=clean_team_id,
            cash_on_hand=_safe_int(entry.get("cash_on_hand", 0)),
            debt=_safe_int(entry.get("debt", 0)),
            revenue_totals=_normalize_money_map(entry.get("revenue"), _REVENUE_CATEGORIES),
            expense_totals=_normalize_money_map(entry.get("expenses"), _EXPENSE_CATEGORIES),
            budgets=_normalize_money_map(entry.get("budgets"), _BUDGET_CATEGORIES),
            projected_revenue=projected_revenue,
            projected_expenses=projected_expenses,
            projected_budgets=projected_budgets,
            projected_net=projected_net,
            financials_enabled=bool(settings.enabled),
            preset=settings.preset,
        )
    return snapshots


def get_team_finance_snapshot(
    team_id: str,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> TeamFinanceSnapshot | None:
    """Return a single-team snapshot for the owner finance readout."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return None
    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id=league_id)
    return snapshots.get(clean_team_id)


def list_team_financial_transactions(
    team_id: str,
    *,
    limit: int = 25,
    data_dir: Path | str | None = None,
) -> list[Dict[str, object]]:
    """Return recent finance ledger rows for a single team."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return []
    resolved_data_dir = _resolve_data_dir(data_dir)
    normalized_limit = limit if limit > 0 else 0
    return list_financial_rows(
        team_id=clean_team_id,
        limit=normalized_limit,
        newest_first=True,
        data_dir=resolved_data_dir,
    )


def update_team_budget_targets(
    team_id: str,
    budgets: Mapping[str, object],
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Persist owner budget targets for one team."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return {
            "saved": False,
            "message": "Team id is required.",
        }

    resolved_data_dir = _resolve_data_dir(data_dir)
    ensure_financial_defaults(data_dir=resolved_data_dir, league_id=league_id)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    if (not settings.enabled) or settings.module_level("owner_budgets") == _OFF:
        return {
            "saved": False,
            "message": "Owner budget controls are disabled by league settings.",
        }

    payload = _load_team_financials(resolved_data_dir)
    teams = payload.get("teams")
    if not isinstance(teams, dict):
        teams = {}
        payload["teams"] = teams

    current = _normalize_team_entry(teams.get(clean_team_id, {}))
    updated_budgets = dict(current.get("budgets", {}))
    source = budgets if isinstance(budgets, Mapping) else {}
    for key in _BUDGET_CATEGORIES:
        if key not in source:
            continue
        updated_budgets[key] = max(0, _safe_int(source.get(key, 0)))
    current["budgets"] = _normalize_money_map(updated_budgets, _BUDGET_CATEGORIES)
    teams[clean_team_id] = current

    financials_path = resolved_data_dir / "team_financials.json"
    financials_path.parent.mkdir(parents=True, exist_ok=True)
    financials_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "saved": True,
        "team_id": clean_team_id,
        "budgets": dict(current["budgets"]),
        "message": "Budget targets saved.",
    }


def apply_owner_finance_cadence_for_dates(
    dates: list[object] | tuple[object, ...],
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Apply daily, weekly, and monthly finance cadence updates."""

    resolved_data_dir = _resolve_data_dir(data_dir)
    normalized_dates = _normalize_unique_dates(dates)
    applied_daily_dates: list[str] = []
    skipped_daily_dates: list[str] = []
    applied_weeks: list[str] = []
    skipped_weeks: list[str] = []

    for date_key in normalized_dates:
        daily_result = _apply_daily_owner_finance(
            date_key,
            data_dir=resolved_data_dir,
            league_id=league_id,
        )
        if bool(daily_result.get("applied")):
            applied_daily_dates.append(date_key)
        else:
            skipped_daily_dates.append(date_key)

    week_pairs = _weekly_periods_from_dates(normalized_dates)
    for week_key, date_sample in week_pairs:
        weekly_result = _apply_weekly_owner_finance(
            week_key=week_key,
            date_sample=date_sample,
            data_dir=resolved_data_dir,
            league_id=league_id,
        )
        if bool(weekly_result.get("applied")):
            applied_weeks.append(week_key)
        else:
            skipped_weeks.append(week_key)

    monthly = apply_monthly_owner_finance_for_dates(
        normalized_dates,
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    return {
        "dates": normalized_dates,
        "applied_daily_dates": applied_daily_dates,
        "skipped_daily_dates": skipped_daily_dates,
        "applied_weeks": applied_weeks,
        "skipped_weeks": skipped_weeks,
        **monthly,
    }


def _apply_daily_owner_finance(
    date_key: str,
    *,
    data_dir: Path,
    league_id: str | None = None,
) -> Dict[str, object]:
    settings = load_financial_settings(
        path=data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    if (
        (not settings.enabled)
        or settings.module_level("owner_revenue") != "advanced"
    ):
        return {"applied": False, "date": date_key, "reason": "disabled"}
    marker = f"daily:{date_key}"
    if ledger_has_entry(
        team_id=LEDGER_TEAM_SYSTEM,
        category=CATEGORY_FINANCE_CYCLE,
        memo=marker,
        data_dir=data_dir,
    ):
        return {"applied": False, "date": date_key, "reason": "already_applied"}

    payload = _load_team_financials(data_dir)
    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id=league_id)
    teams = payload.get("teams")
    if not isinstance(teams, dict) or not snapshots:
        return {"applied": False, "date": date_key, "reason": "no_teams"}
    year, month, _day = _parse_date_parts(date_key)
    days_in_month = max(28, _days_in_month(year, month))
    season_year = _safe_int(payload.get("season_year", year))
    timestamp = _timestamp()
    rows_to_append: list[tuple[str, int, str, str, int, str]] = []
    applied_teams = 0
    total_net_change = 0

    for team_id, snapshot in snapshots.items():
        current = _normalize_team_entry(teams.get(team_id, {}))
        daily_tickets = _safe_int(
            round(snapshot.projected_revenue.get("tickets", 0) / float(days_in_month))
        )
        daily_concessions = _safe_int(
            round(snapshot.projected_revenue.get("concessions", 0) / float(days_in_month))
        )
        if daily_tickets <= 0 and daily_concessions <= 0:
            continue
        if daily_tickets > 0:
            current["revenue"]["tickets"] = (
                _safe_int(current["revenue"].get("tickets", 0)) + daily_tickets
            )
            row = build_team_revenue_row(
                team_id=team_id,
                season_year=season_year,
                revenue_type="tickets",
                amount=daily_tickets,
                memo=marker,
                timestamp=timestamp,
            )
            if row is not None:
                rows_to_append.append(row)
        if daily_concessions > 0:
            current["revenue"]["concessions"] = (
                _safe_int(current["revenue"].get("concessions", 0)) + daily_concessions
            )
            row = build_team_revenue_row(
                team_id=team_id,
                season_year=season_year,
                revenue_type="concessions",
                amount=daily_concessions,
                memo=marker,
                timestamp=timestamp,
            )
            if row is not None:
                rows_to_append.append(row)
        daily_total = daily_tickets + daily_concessions
        current["cash_on_hand"] = _safe_int(current.get("cash_on_hand", 0)) + daily_total
        teams[team_id] = current
        applied_teams += 1
        total_net_change += daily_total

    if applied_teams <= 0:
        return {"applied": False, "date": date_key, "reason": "no_daily_revenue"}
    marker_row = build_finance_cycle_marker_row(
        season_year=season_year,
        period_key=marker,
        timestamp=timestamp,
    )
    if marker_row is not None:
        rows_to_append.append(marker_row)
    (data_dir / "team_financials.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    append_financial_rows(rows_to_append, data_dir=data_dir)
    return {
        "applied": True,
        "date": date_key,
        "applied_teams": applied_teams,
        "total_net_change": total_net_change,
    }


def _apply_weekly_owner_finance(
    *,
    week_key: str,
    date_sample: str,
    data_dir: Path,
    league_id: str | None = None,
) -> Dict[str, object]:
    settings = load_financial_settings(
        path=data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    if (
        (not settings.enabled)
        or settings.module_level("owner_expenses") != "advanced"
    ):
        return {"applied": False, "week_key": week_key, "reason": "disabled"}
    marker = f"weekly:{week_key}"
    if ledger_has_entry(
        team_id=LEDGER_TEAM_SYSTEM,
        category=CATEGORY_FINANCE_CYCLE,
        memo=marker,
        data_dir=data_dir,
    ):
        return {"applied": False, "week_key": week_key, "reason": "already_applied"}

    payload = _load_team_financials(data_dir)
    snapshots = project_monthly_owner_finance(data_dir=data_dir, league_id=league_id)
    teams = payload.get("teams")
    if not isinstance(teams, dict) or not snapshots:
        return {"applied": False, "week_key": week_key, "reason": "no_teams"}
    year, month, _ = _parse_date_parts(date_sample)
    weeks_in_month = max(4, round(_days_in_month(year, month) / 7))
    season_year = _safe_int(payload.get("season_year", year))
    timestamp = _timestamp()
    rows_to_append: list[tuple[str, int, str, str, int, str]] = []
    applied_teams = 0
    total_net_change = 0
    expense_keys = ("training", "scouting", "facilities")

    for team_id, snapshot in snapshots.items():
        current = _normalize_team_entry(teams.get(team_id, {}))
        weekly_total = 0
        for key in expense_keys:
            monthly_amount = _safe_int(snapshot.projected_expenses.get(key, 0))
            weekly_amount = _safe_int(round(monthly_amount / float(weeks_in_month)))
            if weekly_amount <= 0:
                continue
            current["expenses"][key] = _safe_int(current["expenses"].get(key, 0)) + weekly_amount
            row = build_team_expense_row(
                team_id=team_id,
                season_year=season_year,
                expense_type=key,
                amount=weekly_amount,
                memo=marker,
                timestamp=timestamp,
            )
            if row is not None:
                rows_to_append.append(row)
            weekly_total += weekly_amount
        if weekly_total <= 0:
            continue
        current["cash_on_hand"] = _safe_int(current.get("cash_on_hand", 0)) - weekly_total
        teams[team_id] = current
        applied_teams += 1
        total_net_change -= weekly_total

    if applied_teams <= 0:
        return {"applied": False, "week_key": week_key, "reason": "no_weekly_expense"}
    marker_row = build_finance_cycle_marker_row(
        season_year=season_year,
        period_key=marker,
        timestamp=timestamp,
    )
    if marker_row is not None:
        rows_to_append.append(marker_row)
    (data_dir / "team_financials.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    append_financial_rows(rows_to_append, data_dir=data_dir)
    return {
        "applied": True,
        "week_key": week_key,
        "applied_teams": applied_teams,
        "total_net_change": total_net_change,
    }


def apply_monthly_owner_finance(
    *,
    period_key: str | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Apply one monthly finance cycle to all teams (idempotent per period)."""

    resolved_data_dir = _resolve_data_dir(data_dir)
    ensure_financial_defaults(data_dir=resolved_data_dir, league_id=league_id)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    financials_path = resolved_data_dir / "team_financials.json"
    payload = _load_team_financials(resolved_data_dir)
    snapshots = project_monthly_owner_finance(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    period = _normalize_period_key(period_key)
    daily_applied_for_period = _ledger_has_cycle_prefix(
        f"daily:{period}-",
        data_dir=resolved_data_dir,
    )
    weekly_applied_for_period = _ledger_has_cycle_prefix(
        f"weekly:{period}:",
        data_dir=resolved_data_dir,
    )
    revenue_level = settings.module_level("owner_revenue")
    expenses_level = settings.module_level("owner_expenses")

    if ledger_has_entry(
        team_id=LEDGER_TEAM_SYSTEM,
        category=CATEGORY_FINANCE_CYCLE,
        memo=period,
        data_dir=resolved_data_dir,
    ):
        return {
            "applied": False,
            "period_key": period,
            "applied_teams": 0,
            "total_net_change": 0,
            "message": "Finance cycle already applied for this period.",
        }

    teams = payload.get("teams")
    if not isinstance(teams, dict):
        teams = {}
        payload["teams"] = teams

    if not snapshots:
        return {
            "applied": False,
            "period_key": period,
            "applied_teams": 0,
            "total_net_change": 0,
            "message": "No teams available for finance cycle.",
        }

    total_net_change = 0
    applied_teams = 0
    rows_to_append: list[tuple[str, int, str, str, int, str]] = []
    season_year = _safe_int(payload.get("season_year", datetime.now().year))

    for team_id, snapshot in snapshots.items():
        current = _normalize_team_entry(teams.get(team_id, {}))
        for category, amount in snapshot.projected_revenue.items():
            if (
                daily_applied_for_period
                and revenue_level == "advanced"
                and category in {"tickets", "concessions"}
            ):
                continue
            current["revenue"][category] = _safe_int(current["revenue"].get(category, 0)) + amount
            if amount:
                revenue_row = build_team_revenue_row(
                    team_id=team_id,
                    season_year=season_year,
                    revenue_type=category,
                    amount=amount,
                    memo=period,
                    timestamp=_timestamp(),
                )
                if revenue_row is not None:
                    rows_to_append.append(revenue_row)
        for category, amount in snapshot.projected_expenses.items():
            if (
                weekly_applied_for_period
                and expenses_level == "advanced"
                and category in {"training", "scouting", "facilities"}
            ):
                continue
            current["expenses"][category] = _safe_int(current["expenses"].get(category, 0)) + amount
            if amount:
                expense_row = build_team_expense_row(
                    team_id=team_id,
                    season_year=season_year,
                    expense_type=category,
                    amount=amount,
                    memo=period,
                    timestamp=_timestamp(),
                )
                if expense_row is not None:
                    rows_to_append.append(expense_row)
        for category, amount in snapshot.projected_budgets.items():
            current["budgets"][category] = amount

        net_change = snapshot.projected_net
        current["cash_on_hand"] = _safe_int(current.get("cash_on_hand", 0)) + net_change
        teams[team_id] = current
        total_net_change += net_change
        applied_teams += 1

    payload_path = Path(financials_path)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    cycle_marker_row = build_finance_cycle_marker_row(
        season_year=season_year,
        period_key=period,
        timestamp=_timestamp(),
    )
    if cycle_marker_row is not None:
        rows_to_append.append(cycle_marker_row)
    append_financial_rows(rows_to_append, data_dir=resolved_data_dir)

    return {
        "applied": True,
        "period_key": period,
        "applied_teams": applied_teams,
        "total_net_change": total_net_change,
        "message": "Finance cycle applied.",
    }


def period_keys_from_dates(dates: list[object] | tuple[object, ...]) -> list[str]:
    """Return unique ``YYYY-MM`` periods in first-seen order."""

    periods: list[str] = []
    seen: set[str] = set()
    for raw in dates:
        token = str(raw or "").strip()
        if not token:
            continue
        date_token = token[:10]
        try:
            parsed = datetime.strptime(date_token, "%Y-%m-%d")
        except ValueError:
            continue
        period = parsed.strftime("%Y-%m")
        if period in seen:
            continue
        seen.add(period)
        periods.append(period)
    return periods


def _normalize_unique_dates(dates: list[object] | tuple[object, ...]) -> list[str]:
    """Return valid ``YYYY-MM-DD`` values in first-seen order."""

    out: list[str] = []
    seen: set[str] = set()
    for raw in dates:
        token = str(raw or "").strip()
        if not token:
            continue
        date_token = token[:10]
        try:
            datetime.strptime(date_token, "%Y-%m-%d")
        except ValueError:
            continue
        if date_token in seen:
            continue
        seen.add(date_token)
        out.append(date_token)
    return out


def _weekly_periods_from_dates(dates: list[str]) -> list[tuple[str, str]]:
    """Return unique weekly keys with one sample date for each week."""

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for date_key in dates:
        year, month, _ = _parse_date_parts(date_key)
        iso = datetime(year, month, int(date_key[-2:])).isocalendar()
        week_key = f"{year:04d}-{month:02d}:W{int(iso.week):02d}"
        if week_key in seen:
            continue
        seen.add(week_key)
        out.append((week_key, date_key))
    return out


def apply_monthly_owner_finance_for_dates(
    dates: list[object] | tuple[object, ...],
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, object]:
    """Apply finance cycles for each unique month represented by *dates*."""

    periods = period_keys_from_dates(dates)
    applied_periods: list[str] = []
    skipped_periods: list[str] = []
    total_net_change = 0
    for period in periods:
        result = apply_monthly_owner_finance(
            period_key=period,
            data_dir=data_dir,
            league_id=league_id,
        )
        if bool(result.get("applied")):
            applied_periods.append(period)
            total_net_change += _safe_int(result.get("total_net_change", 0))
        else:
            skipped_periods.append(period)
    return {
        "periods": periods,
        "applied_periods": applied_periods,
        "skipped_periods": skipped_periods,
        "total_net_change": total_net_change,
    }


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    if data_dir is None:
        return get_data_dir()
    return Path(data_dir)


def _load_team_financials(data_dir: Path) -> Dict[str, object]:
    path = data_dir / "team_financials.json"
    if not path.exists():
        return {"version": 1, "season_year": datetime.now().year, "teams": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "season_year": datetime.now().year, "teams": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "season_year": datetime.now().year, "teams": {}}
    if not isinstance(payload.get("teams"), dict):
        payload["teams"] = {}
    return payload


def _load_standings(data_dir: Path) -> Dict[str, Mapping[str, object]]:
    path = data_dir / "standings.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    standings: Dict[str, Mapping[str, object]] = {}
    for team_id, value in payload.items():
        if isinstance(value, Mapping):
            standings[str(team_id).strip()] = value
    return standings


def _load_schedule_team_metrics(data_dir: Path) -> Dict[str, Dict[str, float]]:
    """Return team-level schedule cadence metrics (home/away)."""

    path = data_dir / "schedule.csv"
    if not path.exists():
        return {}

    home_totals: Dict[str, int] = {}
    away_totals: Dict[str, int] = {}
    home_games_by_month: Dict[str, Dict[str, int]] = {}
    away_games_by_month: Dict[str, Dict[str, int]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not isinstance(row, Mapping):
                    continue
                home_team_id = str(row.get("home", "") or "").strip()
                away_team_id = str(row.get("away", "") or "").strip()
                date_token = str(row.get("date", "") or "").strip()
                if len(date_token) >= 7 and date_token[4] == "-":
                    month = date_token[:7]
                else:
                    month = ""
                if home_team_id:
                    home_totals[home_team_id] = home_totals.get(home_team_id, 0) + 1
                    if month:
                        bucket = home_games_by_month.setdefault(home_team_id, {})
                        bucket[month] = bucket.get(month, 0) + 1
                if away_team_id:
                    away_totals[away_team_id] = away_totals.get(away_team_id, 0) + 1
                    if month:
                        bucket = away_games_by_month.setdefault(away_team_id, {})
                        bucket[month] = bucket.get(month, 0) + 1
    except Exception:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    team_ids = set(home_totals.keys()) | set(away_totals.keys())
    for team_id in team_ids:
        home_total = int(home_totals.get(team_id, 0))
        away_total = int(away_totals.get(team_id, 0))
        if home_total <= 0 and away_total <= 0:
            continue
        home_months = home_games_by_month.get(team_id, {})
        away_months = away_games_by_month.get(team_id, {})
        home_month_count = max(1, len(home_months))
        away_month_count = max(1, len(away_months))
        avg_monthly_home = float(home_total) / float(home_month_count)
        avg_monthly_away = float(away_total) / float(away_month_count)
        out[team_id] = {
            "total_home_games": float(home_total),
            "total_away_games": float(away_total),
            "avg_monthly_home_games": avg_monthly_home,
            "avg_monthly_away_games": avg_monthly_away,
        }
    return out


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _normalize_money_map(raw: object, keys: tuple[str, ...]) -> Dict[str, int]:
    source = raw if isinstance(raw, Mapping) else {}
    return {key: _safe_int(source.get(key, 0)) for key in keys}


def _normalize_team_entry(raw: object) -> Dict[str, object]:
    source = raw if isinstance(raw, Mapping) else {}
    return {
        "cash_on_hand": _safe_int(source.get("cash_on_hand", 0)),
        "debt": _safe_int(source.get("debt", 0)),
        "revenue": _normalize_money_map(source.get("revenue"), _REVENUE_CATEGORIES),
        "expenses": _normalize_money_map(source.get("expenses"), _EXPENSE_CATEGORIES),
        "budgets": _normalize_money_map(source.get("budgets"), _BUDGET_CATEGORIES),
    }


def _market_multiplier(team_id: str, level: str) -> float:
    if level == _OFF:
        return 1.0
    seed = sum(ord(ch) for ch in team_id.strip().upper())
    if level == "basic":
        shift = (seed % 21) - 10
        return max(0.90, min(1.10, 1.0 + (shift / 100.0)))
    shift = (seed % 31) - 15
    return max(0.85, min(1.20, 1.0 + (shift / 100.0)))


def _performance_multiplier(team_id: str, standings: Mapping[str, Mapping[str, object]]) -> float:
    record = standings.get(team_id)
    if not isinstance(record, Mapping):
        return 1.0
    wins = _safe_int(record.get("wins", 0))
    losses = _safe_int(record.get("losses", 0))
    games = wins + losses
    if games <= 0:
        return 1.0
    win_pct = wins / games
    delta = (win_pct - 0.5) * 0.40
    return max(0.85, min(1.20, 1.0 + delta))


def _project_revenue(
    *,
    settings,
    team_id: str,
    standings: Mapping[str, Mapping[str, object]],
    schedule_team_metric: Mapping[str, object],
) -> Dict[str, int]:
    revenue_level = settings.module_level("owner_revenue")
    market_level = settings.module_level("owner_market_model")
    if not settings.enabled or revenue_level == _OFF:
        return {category: 0 for category in _REVENUE_CATEGORIES}

    baseline = (
        _BASIC_MONTHLY_REVENUE
        if revenue_level == "basic"
        else _ADVANCED_MONTHLY_REVENUE
    )
    market = _market_multiplier(team_id, market_level)
    perf = 1.0
    if revenue_level == "advanced" or market_level == "advanced":
        perf = _performance_multiplier(team_id, standings)
    totals = {
        category: _safe_int(amount * market * perf)
        for category, amount in baseline.items()
    }
    if revenue_level == "advanced":
        attendance = _attendance_multiplier(
            team_id,
            standings=standings,
            schedule_team_metric=schedule_team_metric,
        )
        for category in ("tickets", "concessions"):
            totals[category] = _safe_int(totals.get(category, 0) * attendance)
        fan_interest = _fan_interest_multiplier(
            team_id,
            standings=standings,
        )
        for category in ("media", "sponsorship"):
            totals[category] = _safe_int(totals.get(category, 0) * fan_interest)
    return totals


def _project_expenses(
    *,
    settings,
    team_id: str,
    standings: Mapping[str, Mapping[str, object]],
    payroll_monthly: int,
    schedule_team_metric: Mapping[str, object],
) -> Dict[str, int]:
    if not settings.enabled:
        return {category: 0 for category in _EXPENSE_CATEGORIES}

    expense_level = settings.module_level("owner_expenses")
    market_level = settings.module_level("owner_market_model")
    contracts_level = settings.module_level("gm_contracts")

    expenses = {category: 0 for category in _EXPENSE_CATEGORIES}
    if contracts_level != _OFF:
        expenses["payroll"] = _safe_int(payroll_monthly)

    if expense_level == _OFF:
        return expenses

    baseline = (
        _BASIC_MONTHLY_EXPENSES
        if expense_level == "basic"
        else _ADVANCED_MONTHLY_EXPENSES
    )
    market = _market_multiplier(team_id, market_level)
    perf = 1.0
    if expense_level == "advanced" or market_level == "advanced":
        perf = _performance_multiplier(team_id, standings)
    for category, amount in baseline.items():
        expenses[category] = _safe_int(amount * market * perf)
    if expense_level == "advanced":
        away_travel = _away_travel_multiplier(schedule_team_metric)
        facility_load = _facility_load_multiplier(schedule_team_metric)
        expenses["operations"] = _safe_int(expenses.get("operations", 0) * away_travel)
        expenses["facilities"] = _safe_int(expenses.get("facilities", 0) * facility_load)
    return expenses


def _project_budgets(
    *,
    settings,
    projected_revenue: Mapping[str, int],
) -> Dict[str, int]:
    budget_level = settings.module_level("owner_budgets")
    if not settings.enabled or budget_level == _OFF:
        return {category: 0 for category in _BUDGET_CATEGORIES}
    split = _BASIC_BUDGET_SPLIT if budget_level == "basic" else _ADVANCED_BUDGET_SPLIT
    revenue_total = sum(projected_revenue.values())
    return {
        category: _safe_int(revenue_total * ratio)
        for category, ratio in split.items()
    }


def _parse_date_parts(date_key: str) -> tuple[int, int, int]:
    try:
        year = int(date_key[0:4])
        month = int(date_key[5:7])
        day = int(date_key[8:10])
    except Exception:
        now = datetime.utcnow()
        return now.year, now.month, now.day
    return year, month, day


def _days_in_month(year: int, month: int) -> int:
    try:
        return int(calendar.monthrange(int(year), int(month))[1])
    except Exception:
        return 30


def _ledger_has_cycle_prefix(prefix: str, *, data_dir: Path) -> bool:
    rows = list_financial_rows(
        team_id=LEDGER_TEAM_SYSTEM,
        category=CATEGORY_FINANCE_CYCLE,
        limit=0,
        newest_first=False,
        data_dir=data_dir,
    )
    for row in rows:
        memo = str(row.get("memo", "") or "").strip()
        if memo.startswith(prefix):
            return True
    return False


def _attendance_multiplier(
    team_id: str,
    *,
    standings: Mapping[str, Mapping[str, object]],
    schedule_team_metric: Mapping[str, object],
) -> float:
    """Return attendance-driven multiplier for gate/concessions projections."""

    game_volume = 1.0
    avg_monthly_home = float(
        schedule_team_metric.get("avg_monthly_home_games", _DEFAULT_HOME_GAMES_PER_MONTH) or 0.0
    )
    if avg_monthly_home > 0:
        game_volume = _clamp(
            avg_monthly_home / _DEFAULT_HOME_GAMES_PER_MONTH,
            _HOME_GAME_VOLUME_MIN,
            _HOME_GAME_VOLUME_MAX,
        )

    home_form = 1.0
    record = standings.get(team_id)
    if isinstance(record, Mapping):
        home_wins = _safe_int(record.get("home_wins", 0))
        home_losses = _safe_int(record.get("home_losses", 0))
        home_games = home_wins + home_losses
        if home_games > 0:
            home_pct = float(home_wins) / float(home_games)
            home_form = _clamp(
                1.0 + ((home_pct - 0.5) * 0.50),
                _HOME_FORM_MIN,
                _HOME_FORM_MAX,
            )

    return _clamp(game_volume * home_form, _ATTENDANCE_MIN, _ATTENDANCE_MAX)


def _fan_interest_multiplier(
    team_id: str,
    *,
    standings: Mapping[str, Mapping[str, object]],
) -> float:
    """Return team fan-interest signal for advanced media/sponsorship revenue."""

    record = standings.get(team_id)
    if not isinstance(record, Mapping):
        return 1.0
    wins = _safe_int(record.get("wins", 0))
    losses = _safe_int(record.get("losses", 0))
    games = wins + losses
    if games <= 0:
        return 1.0
    win_pct = float(wins) / float(games)
    win_component = _clamp(1.0 + ((win_pct - 0.5) * 0.30), 0.90, 1.12)

    runs_for = _safe_int(record.get("runs_for", 0))
    runs_against = _safe_int(record.get("runs_against", 0))
    run_diff_per_game = float(runs_for - runs_against) / float(max(1, games))
    run_component = _clamp(1.0 + (run_diff_per_game * 0.015), 0.92, 1.10)

    home_wins = _safe_int(record.get("home_wins", 0))
    home_losses = _safe_int(record.get("home_losses", 0))
    home_games = home_wins + home_losses
    home_component = 1.0
    if home_games > 0:
        home_pct = float(home_wins) / float(home_games)
        home_component = _clamp(1.0 + ((home_pct - 0.5) * 0.18), 0.94, 1.06)

    return _clamp(
        win_component * run_component * home_component,
        _FAN_INTEREST_MIN,
        _FAN_INTEREST_MAX,
    )


def _away_travel_multiplier(schedule_team_metric: Mapping[str, object]) -> float:
    avg_monthly_away = float(
        schedule_team_metric.get("avg_monthly_away_games", _DEFAULT_AWAY_GAMES_PER_MONTH) or 0.0
    )
    if avg_monthly_away <= 0:
        return 1.0
    return _clamp(
        avg_monthly_away / _DEFAULT_AWAY_GAMES_PER_MONTH,
        _AWAY_TRAVEL_MIN,
        _AWAY_TRAVEL_MAX,
    )


def _facility_load_multiplier(schedule_team_metric: Mapping[str, object]) -> float:
    avg_monthly_home = float(
        schedule_team_metric.get("avg_monthly_home_games", _DEFAULT_HOME_GAMES_PER_MONTH) or 0.0
    )
    if avg_monthly_home <= 0:
        return 1.0
    return _clamp(
        avg_monthly_home / _DEFAULT_HOME_GAMES_PER_MONTH,
        _FACILITY_LOAD_MIN,
        _FACILITY_LOAD_MAX,
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _normalize_period_key(period_key: str | None) -> str:
    token = str(period_key or "").strip()
    if token:
        return token
    return datetime.now().strftime("%Y-%m")


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
