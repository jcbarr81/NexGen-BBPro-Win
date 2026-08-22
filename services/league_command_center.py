"""League Command Center data contract + aggregation service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping
import csv
import json

from playbalance.season_manager import SeasonManager
from services.finance_reporting import (
    build_commissioner_projection_report,
    build_finance_alerts,
)
from services.gm_finance_queue import summarize_queue_decisions
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.roster_validation import missing_positions
from utils.team_loader import load_teams
from utils.trade_utils import load_trades, trade_deadline_for_year

__all__ = [
    "CommandCenterCard",
    "LeagueCommandCenterSnapshot",
    "build_league_command_center_snapshot",
]


@dataclass
class CommandCenterCard:
    card_id: str
    title: str
    severity: str
    summary: str
    count: int
    items: list[dict[str, Any]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "severity": self.severity,
            "summary": self.summary,
            "count": int(self.count),
            "items": list(self.items),
            "actions": list(self.actions),
        }


@dataclass
class LeagueCommandCenterSnapshot:
    generated_at_utc: str
    league_id: str
    phase: str
    sim_date: str | None
    overview: dict[str, int]
    cards: list[CommandCenterCard]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "league_id": self.league_id,
            "phase": self.phase,
            "sim_date": self.sim_date,
            "overview": dict(self.overview),
            "cards": [card.to_dict() for card in self.cards],
        }


def build_league_command_center_snapshot(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    max_items_per_card: int = 8,
) -> dict[str, Any]:
    """Return a normalized payload for League Command Center UI cards."""

    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    phase = _resolve_phase(resolved_data_dir)
    sim_date = _resolve_current_sim_date(resolved_data_dir)
    report = _safe_finance_report(resolved_data_dir, league_id=league_id)

    injuries_card = _build_injuries_card(
        resolved_data_dir,
        max_items=max_items_per_card,
    )
    approvals_card = _build_pending_approvals_card(
        resolved_data_dir,
        max_items=max_items_per_card,
    )
    roster_card = _build_roster_conflicts_card(
        resolved_data_dir,
        max_items=max_items_per_card,
    )
    deadlines_card = _build_deadlines_card(
        resolved_data_dir,
        phase=phase,
        sim_date=sim_date,
        report=report,
    )
    finance_card = _build_finance_risks_card(
        resolved_data_dir,
        league_id=league_id,
        report=report,
        max_items=max_items_per_card,
    )

    cards = [injuries_card, approvals_card, roster_card, deadlines_card, finance_card]
    overview = {
        "critical_cards": sum(1 for card in cards if card.severity == "critical"),
        "warning_cards": sum(1 for card in cards if card.severity == "warning"),
        "total_attention_items": sum(max(0, int(card.count)) for card in cards),
    }

    snapshot = LeagueCommandCenterSnapshot(
        generated_at_utc=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        league_id=_resolve_league_id(report, league_id),
        phase=phase,
        sim_date=sim_date,
        overview=overview,
        cards=cards,
    )
    return snapshot.to_dict()


def _safe_finance_report(
    data_dir: Path,
    *,
    league_id: str | None,
) -> Mapping[str, Any]:
    try:
        return build_commissioner_projection_report(
            data_dir=data_dir,
            league_id=league_id,
        )
    except Exception:
        return {}


def _resolve_league_id(report: Mapping[str, Any], fallback: str | None) -> str:
    token = str(report.get("league_id") or fallback or "").strip()
    return token or "league"


def _resolve_phase(data_dir: Path) -> str:
    try:
        manager = SeasonManager(path=data_dir / "season_state.json", enable_rollover=False)
        return str(manager.phase.name)
    except Exception:
        return "UNKNOWN"


def _resolve_current_sim_date(data_dir: Path) -> str | None:
    schedule_path = data_dir / "schedule.csv"
    if not schedule_path.exists():
        return None
    dates: list[str] = []
    seen: set[str] = set()
    try:
        with schedule_path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return None
    for row in rows:
        token = str(row.get("date") or "").strip()
        if token and token not in seen:
            seen.add(token)
            dates.append(token)
    if not dates:
        return None

    progress_path = data_dir / "season_progress.json"
    index = 0
    if progress_path.exists():
        try:
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
            index = int(payload.get("sim_index", 0) or 0)
        except Exception:
            index = 0
    index = max(0, min(index, len(dates) - 1))
    return dates[index]


def _build_injuries_card(data_dir: Path, *, max_items: int) -> CommandCenterCard:
    players_path = data_dir / "players.csv"
    try:
        players = list(load_players_from_csv(players_path))
    except Exception:
        players = []

    injured = [
        player
        for player in players
        if bool(getattr(player, "injured", False))
        or bool(str(getattr(player, "injury_list", "") or "").strip())
    ]
    by_team: Dict[str, int] = {}
    for player in injured:
        team_id = str(getattr(player, "team_id", "") or "").strip() or "Unknown"
        by_team[team_id] = by_team.get(team_id, 0) + 1
    items = [
        {"team_id": team_id, "injury_count": count}
        for team_id, count in sorted(by_team.items(), key=lambda row: row[1], reverse=True)[:max_items]
    ]
    count = len(injured)
    severity = "warning" if count > 0 else "info"
    summary = (
        f"{count} injured player(s) across the league."
        if count > 0
        else "No active injuries reported."
    )
    return CommandCenterCard(
        card_id="injuries",
        title="Injuries",
        severity=severity,
        summary=summary,
        count=count,
        items=items,
        actions=["Open Injury Center"],
    )


def _build_pending_approvals_card(data_dir: Path, *, max_items: int) -> CommandCenterCard:
    try:
        trades = load_trades(data_dir / "trades_pending.csv")
    except Exception:
        trades = []
    pending_trades = sum(
        1 for trade in trades if str(getattr(trade, "status", "")).lower() in {"pending", "owner_accepted"}
    )
    owner_accepted = sum(
        1 for trade in trades if str(getattr(trade, "status", "")).lower() == "owner_accepted"
    )

    try:
        queue = summarize_queue_decisions(data_dir=data_dir)
    except Exception:
        queue = {}
    gm_pending = int(queue.get("pending", 0) or 0)
    gm_unapplied = int(queue.get("approved_unapplied", 0) or 0)

    total = pending_trades + gm_pending + gm_unapplied
    severity = "critical" if total >= 8 else ("warning" if total > 0 else "info")
    summary = (
        f"{total} approval item(s) pending commissioner action."
        if total > 0
        else "No pending approvals."
    )
    items = [
        {"label": "Pending/Owner-Accepted Trades", "count": pending_trades},
        {"label": "GM Finance Queue Pending", "count": gm_pending},
        {"label": "GM Queue Approved Not Applied", "count": gm_unapplied},
    ][:max_items]
    return CommandCenterCard(
        card_id="pending_approvals",
        title="Pending Approvals",
        severity=severity,
        summary=summary,
        count=total,
        items=items,
        actions=["Review Pending Trades", "Review GM Finance Queue"],
    )


def _build_roster_conflicts_card(data_dir: Path, *, max_items: int) -> CommandCenterCard:
    teams = _safe_iter(load_teams, data_dir / "teams.csv")
    players = {
        player.player_id: player
        for player in _safe_iter(load_players_from_csv, data_dir / "players.csv")
    }
    conflicts: list[dict[str, Any]] = []
    for team in teams:
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id:
            continue
        try:
            roster = load_roster(team_id, data_dir / "rosters")
        except Exception:
            continue
        missing = missing_positions(roster, players)
        if not missing:
            continue
        conflicts.append(
            {
                "team_id": team_id,
                "missing_positions": list(missing),
                "missing_count": len(missing),
            }
        )
    conflicts.sort(key=lambda row: int(row.get("missing_count", 0)), reverse=True)
    count = len(conflicts)
    severity = "warning" if count > 0 else "info"
    summary = (
        f"{count} team(s) missing defensive coverage on active roster."
        if count > 0
        else "No active-roster defensive conflicts detected."
    )
    return CommandCenterCard(
        card_id="roster_conflicts",
        title="Roster Conflicts",
        severity=severity,
        summary=summary,
        count=count,
        items=conflicts[:max_items],
        actions=["Open Team Roster", "Run Auto-Reassign"],
    )


def _build_deadlines_card(
    data_dir: Path,
    *,
    phase: str,
    sim_date: str | None,
    report: Mapping[str, Any],
) -> CommandCenterCard:
    items: list[dict[str, Any]] = []
    attention_count = 0
    critical_count = 0
    modules = report.get("modules") if isinstance(report, Mapping) else {}
    modules_map = modules if isinstance(modules, Mapping) else {}
    offseason = report.get("offseason") if isinstance(report, Mapping) else {}
    offseason_map = offseason if isinstance(offseason, Mapping) else {}

    season_year = _resolve_year_from_date(sim_date) or date.today().year
    trade_deadline = trade_deadline_for_year(season_year)
    days_to_deadline: int | None = None
    sim_dt: date | None = None
    if sim_date:
        try:
            sim_dt = date.fromisoformat(sim_date)
            days_to_deadline = (trade_deadline - sim_dt).days
        except Exception:
            days_to_deadline = None
            sim_dt = None
    trade_status = "upcoming"
    if days_to_deadline is None:
        trade_status = "unknown"
    elif days_to_deadline < 0:
        trade_status = "passed"
    elif days_to_deadline == 0:
        trade_status = "today"
        attention_count += 1
        critical_count += 1
    elif days_to_deadline <= 7:
        trade_status = "urgent"
        attention_count += 1
    elif days_to_deadline <= 14:
        trade_status = "near"
        attention_count += 1
    items.append(
        {
            "label": "Trade Deadline",
            "date": trade_deadline.isoformat(),
            "days_remaining": days_to_deadline,
            "status": trade_status,
        }
    )

    draft_date = _compute_draft_date_for_year(season_year)
    draft_completed = _is_draft_completed(data_dir, season_year)
    days_to_draft: int | None = None
    if sim_dt is not None:
        try:
            days_to_draft = (date.fromisoformat(draft_date) - sim_dt).days
        except Exception:
            days_to_draft = None
    draft_status = "completed" if draft_completed else "upcoming"
    if not draft_completed:
        if days_to_draft is None:
            draft_status = "unknown"
        elif days_to_draft < 0:
            draft_status = "ready"
            attention_count += 1
            if str(phase).upper() == "AMATEUR_DRAFT":
                critical_count += 1
        elif days_to_draft == 0:
            draft_status = "today"
            attention_count += 1
        elif days_to_draft <= 7:
            draft_status = "near"
            attention_count += 1
        elif days_to_draft <= 14:
            draft_status = "upcoming_soon"
    items.append(
        {
            "label": "Amateur Draft",
            "date": draft_date,
            "days_remaining": days_to_draft,
            "status": draft_status,
        }
    )

    next_stage = str(offseason_map.get("next_stage_label") or "None").strip()
    can_run = bool(offseason_map.get("can_run_now", False))
    if can_run and next_stage and next_stage != "None":
        items.append(
            {
                "label": "Offseason Finance Workflow",
                "status": "pending",
                "next_stage": next_stage,
            }
        )
        attention_count += 1

    arbitration_candidates = int(offseason_map.get("arbitration_candidates", 0) or 0)
    if arbitration_candidates > 0 and _is_finance_module_enabled(
        modules_map.get("gm_arbitration")
    ):
        items.append(
            {
                "label": "Arbitration Decisions",
                "status": "active",
                "count": arbitration_candidates,
            }
        )
        attention_count += 1

    unsigned_players = int(offseason_map.get("unsigned_players", 0) or 0)
    if unsigned_players > 0 and _is_finance_module_enabled(
        modules_map.get("gm_free_agency")
    ):
        items.append(
            {
                "label": "Free-Agency Market",
                "status": "active",
                "count": unsigned_players,
            }
        )
        attention_count += 1

    if str(phase).upper() == "AMATEUR_DRAFT" and draft_status in {
        "today",
        "ready",
        "near",
        "upcoming_soon",
    }:
        critical_count += 1

    severity = "info"
    if critical_count > 0:
        severity = "critical"
    elif attention_count > 0:
        severity = "warning"

    summary = (
        f"{attention_count} deadline item(s) need near-term attention."
        if attention_count > 0
        else "No urgent deadlines."
    )
    return CommandCenterCard(
        card_id="deadlines",
        title="Deadlines",
        severity=severity,
        summary=summary,
        count=attention_count,
        items=items,
        actions=[
            "Open Season Progress",
            "Open Draft Console",
            "Open Offseason Finance Workflow",
        ],
    )


def _is_finance_module_enabled(value: object) -> bool:
    token = str(value or "").strip().lower()
    return token not in {"", "off", "disabled", "none"}


def _build_finance_risks_card(
    data_dir: Path,
    *,
    league_id: str | None,
    report: Mapping[str, Any],
    max_items: int,
) -> CommandCenterCard:
    alerts = _safe_iter(
        build_finance_alerts,
        report=report,
        data_dir=data_dir,
        league_id=league_id,
        limit=max_items,
    )
    rows = [dict(item) for item in alerts if isinstance(item, Mapping)]

    if len(rows) == 1 and str(rows[0].get("title") or "").strip() == "No Immediate Finance Alerts":
        return CommandCenterCard(
            card_id="finance_risks",
            title="Finance Risks",
            severity="info",
            summary="No immediate finance risk alerts.",
            count=0,
            items=rows,
            actions=["Open Finance Hub"],
        )

    critical = sum(1 for row in rows if str(row.get("severity", "")).lower() == "critical")
    warning = sum(1 for row in rows if str(row.get("severity", "")).lower() == "warning")
    info = sum(1 for row in rows if str(row.get("severity", "")).lower() == "info")
    count = len(rows)
    severity = "critical" if critical > 0 else ("warning" if warning > 0 else "info")
    summary = (
        f"{count} finance alert(s): {critical} critical, {warning} warning, {info} info."
        if count > 0
        else "No finance alerts."
    )
    actions = [
        "Open Finance Hub",
        "Open Finance Settings",
        "Open Offseason Finance Workflow",
    ]
    if any(
        "gm finance queue" in str(row.get("title") or "").strip().lower()
        for row in rows
    ):
        actions.append("Review GM Finance Queue")
    return CommandCenterCard(
        card_id="finance_risks",
        title="Finance Risks",
        severity=severity,
        summary=summary,
        count=count,
        items=rows[:max_items],
        actions=actions,
    )


def _is_draft_completed(data_dir: Path, year: int) -> bool:
    progress_path = data_dir / "season_progress.json"
    if not progress_path.exists():
        return False
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    years = payload.get("draft_completed_years")
    if not isinstance(years, list):
        return False
    return year in set(int(item) for item in years if str(item).strip().isdigit())


def _compute_draft_date_for_year(year: int) -> str:
    # Matches owner/admin dashboard draft-day helper:
    # third Tuesday in July.
    current = date(year, 7, 1)
    while current.weekday() != 1:
        current = current.replace(day=current.day + 1)
    return (current.replace(day=current.day + 14)).isoformat()


def _resolve_year_from_date(token: str | None) -> int | None:
    try:
        return int(str(token or "").split("-", 1)[0])
    except Exception:
        return None


def _safe_iter(func, *args, **kwargs):
    try:
        result = func(*args, **kwargs)
    except Exception:
        return []
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
        return list(result)
    return result
