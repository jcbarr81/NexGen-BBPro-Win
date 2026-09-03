"""Notification engine — runs after each simulated day.

Two execution patterns are supported:

* ``capture_pre_state`` snapshots whatever pre-day state the detectors
  need (size of news file, current standings, roster files, finance
  cash). The snapshot is opaque to callers — it just gets passed back to
  ``detect_events`` after the day finishes.

* ``detect_events`` reads new news lines + the post-day state, compares
  it against the pre snapshot, and returns a list of
  :class:`NotificationEvent` objects whose ``rule_id`` matches an
  enabled rule for the team.

Each event also carries a ``stop_sim`` flag derived from the rule
settings; ``simulate/days`` halts as soon as one fires so the owner can
review before any more days tick over.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from services.notification_settings import NotificationSettings
from services.standings_repository import load_standings
from utils.news_logger import _news_file as _news_file_path  # noqa: F401  (re-export safe)
from utils.path_utils import get_data_dir

__all__ = [
    "NotificationEvent",
    "DaySnapshot",
    "capture_pre_state",
    "detect_events",
    "append_history",
    "load_history",
]


_NEWS_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s*"
    r"(?:\[(?P<category>[^\]]+)\]\s*)?"
    r"(?:\[(?P<team_id>[^\]]+)\]\s*)?"
    r"(?P<message>.*)$"
)


@dataclass
class NotificationEvent:
    rule_id: str
    severity: str  # "info" | "warning" | "critical"
    title: str
    message: str
    sim_date: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds") + "Z")
    payload: Dict[str, Any] = field(default_factory=dict)
    stop_sim: bool = False
    notify: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DaySnapshot:
    """Opaque pre-day snapshot used by detectors."""

    news_size: int = 0
    standings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    phase: Optional[str] = None
    cash_on_hand: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers


def _news_path() -> Path:
    return get_data_dir() / "news_feed.txt"


def _read_news_tail(prev_size: int) -> List[Dict[str, Any]]:
    """Return news lines added since the snapshot, parsed into dicts."""

    path = _news_path()
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= prev_size:
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(prev_size)
            chunk = handle.read()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for raw in chunk.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _NEWS_LINE_RE.match(line)
        if not m:
            continue
        out.append(
            {
                "timestamp": m.group("ts"),
                "category": (m.group("category") or "").strip().lower() or None,
                "team_id": (m.group("team_id") or "").strip().upper() or None,
                "message": (m.group("message") or "").strip(),
            }
        )
    return out


def _news_size() -> int:
    path = _news_path()
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _standings_for(team_id: str) -> Dict[str, Any]:
    try:
        all_rows = load_standings()
    except Exception:
        return {}
    if not isinstance(all_rows, Mapping):
        return {}
    return all_rows.get(team_id, {}) or {}


def _team_finance_cash(team_id: str) -> Optional[int]:
    """Cheap probe for cash on hand. Returns None if finance is off."""

    path = get_data_dir() / "team_financials.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    teams = raw.get("teams") if isinstance(raw, dict) else None
    if not isinstance(teams, Mapping):
        return None
    entry = teams.get(team_id)
    if not isinstance(entry, Mapping):
        return None
    cash = entry.get("cash_on_hand")
    try:
        return int(cash)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API


def capture_pre_state(team_id: str, *, phase: Optional[str] = None) -> DaySnapshot:
    """Snapshot the bits of state detectors need before the day runs."""

    return DaySnapshot(
        news_size=_news_size(),
        standings=_standings_for(team_id),
        phase=phase,
        cash_on_hand=_team_finance_cash(team_id),
    )


# ---------------------------------------------------------------------------
# Detectors


# Rule ids are deliberately unchanged even though the lists were renamed:
# per-team notification settings are stored against these keys, so renaming them
# would silently reset everyone's preferences. MLB's 7/10/15-day lists all map
# onto the short-list rule, and the 60-day list onto the long one.
_INJURY_TIER_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Order matters: more-specific tiers first. Day-to-day is now checked BEFORE
    # the list patterns, so a "day-to-day" description can never be promoted
    # into a stop-the-sim rule by the word "day".
    ("injury_season_ending", re.compile(r"\bseason[- ]ending\b", re.IGNORECASE)),
    ("injury_day_to_day", re.compile(r"\bday[- ]to[- ]day\b", re.IGNORECASE)),
    ("injury_ir60", re.compile(r"\b60[- ]day\b|\bil60\b|\bir(?:60)?\b", re.IGNORECASE)),
    ("injury_dl45", re.compile(r"\b45[- ]day\b", re.IGNORECASE)),
    (
        "injury_dl15",
        re.compile(
            r"\b(?:7|10|15)[- ]day\b|\bil(?:7|10|15)\b|\bdl(?:15)?\b"
            r"|injured list|disabled list",
            re.IGNORECASE,
        ),
    ),
]

_INJURY_RETURN_PATTERN = re.compile(
    r"\bready to return\b|\bactivated\b|\breturn(?:ed)?\b",
    re.IGNORECASE,
)


def _classify_injury_line(message: str) -> Optional[str]:
    if _INJURY_RETURN_PATTERN.search(message):
        return "injury_returned"
    for rule_id, pattern in _INJURY_TIER_PATTERNS:
        if pattern.search(message):
            return rule_id
    # Fall back: a plain "injured" line we couldn't classify defaults to
    # day-to-day so the user still gets a heads-up.
    if re.search(r"\binjur", message, re.IGNORECASE):
        return "injury_day_to_day"
    return None


def _injury_severity(rule_id: str) -> str:
    if rule_id == "injury_returned":
        return "info"
    if rule_id in {"injury_dl15", "injury_day_to_day"}:
        return "warning"
    return "critical"


def _detect_news_events(
    team_id: str,
    settings: NotificationSettings,
    news_lines: Iterable[Mapping[str, Any]],
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    events: List[NotificationEvent] = []
    for line in news_lines:
        category = (line.get("category") or "").lower()
        line_team = (line.get("team_id") or "").upper()
        message = line.get("message") or ""
        # Only fire team-scoped events when the line's team matches (or
        # the line carries no team — global league news).
        if line_team and line_team != team_id.upper():
            continue
        if category == "injury":
            rule_id = _classify_injury_line(message)
            if rule_id is None:
                continue
            rule = settings.rule(rule_id)
            if not rule.enabled or not rule.notify:
                continue
            events.append(
                NotificationEvent(
                    rule_id=rule_id,
                    severity=_injury_severity(rule_id),
                    title=_rule_title(rule_id),
                    message=message,
                    sim_date=sim_date,
                    payload={"team_id": team_id, "category": category},
                    stop_sim=bool(rule.stop_sim),
                )
            )
        elif category == "special_event":
            rule = settings.rule("player_milestone")
            if rule.enabled and rule.notify:
                events.append(
                    NotificationEvent(
                        rule_id="player_milestone",
                        severity="info",
                        title="Player milestone",
                        message=message,
                        sim_date=sim_date,
                        payload={"team_id": team_id},
                        stop_sim=bool(rule.stop_sim),
                    )
                )
        elif category == "record":
            rule = settings.rule("player_milestone")
            if rule.enabled and rule.notify:
                events.append(
                    NotificationEvent(
                        rule_id="player_milestone",
                        severity="info",
                        title="League record",
                        message=message,
                        sim_date=sim_date,
                        payload={"team_id": team_id, "kind": "record"},
                        stop_sim=bool(rule.stop_sim),
                    )
                )
        elif category == "trade":
            rule = settings.rule("trade_decided")
            if rule.enabled and rule.notify:
                events.append(
                    NotificationEvent(
                        rule_id="trade_decided",
                        severity="info",
                        title="Trade outcome",
                        message=message,
                        sim_date=sim_date,
                        payload={"team_id": team_id},
                        stop_sim=bool(rule.stop_sim),
                    )
                )
    return events


def _detect_streak(
    team_id: str,
    settings: NotificationSettings,
    pre_state: DaySnapshot,
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    events: List[NotificationEvent] = []
    post = _standings_for(team_id)
    if not post:
        return events
    streak = post.get("streak") if isinstance(post, Mapping) else None
    if not isinstance(streak, Mapping):
        return events
    result = str(streak.get("result") or "").upper()
    length = int(streak.get("length") or 0)
    pre_streak = (
        pre_state.standings.get("streak")
        if isinstance(pre_state.standings, Mapping)
        else None
    )
    pre_length = (
        int(pre_streak.get("length") or 0)
        if isinstance(pre_streak, Mapping)
        else 0
    )

    # Only fire on the day the threshold is crossed (not every day after).
    rule_id = "win_streak" if result == "W" else "losing_streak" if result == "L" else None
    if rule_id is None:
        return events
    rule = settings.rule(rule_id)
    if not rule.enabled or not rule.notify:
        return events
    threshold = int(rule.threshold or 0)
    if threshold <= 0:
        return events
    # Crossed threshold today (length >= threshold and pre_length < threshold).
    if length >= threshold and pre_length < threshold:
        events.append(
            NotificationEvent(
                rule_id=rule_id,
                severity="info" if rule_id == "win_streak" else "warning",
                title=("Win streak" if rule_id == "win_streak" else "Losing streak"),
                message=f"{team_id} {result}{length} streak.",
                sim_date=sim_date,
                payload={"team_id": team_id, "length": length, "threshold": threshold},
                stop_sim=bool(rule.stop_sim),
            )
        )
    return events


def _detect_finance_payroll_over(
    team_id: str,
    settings: NotificationSettings,
    pre_state: DaySnapshot,
    new_phase: Optional[str],
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    """Fire when a team is over the luxury threshold. Computed only on a
    phase-change day so the (heavier) payroll projection never runs every
    sim day."""

    rule = settings.rule("finance_payroll_over")
    if not rule.enabled or not rule.notify:
        return []
    if not new_phase or new_phase == pre_state.phase:
        return []
    try:
        from services.payroll_policy import evaluate_payroll_delta

        policy = evaluate_payroll_delta(team_id, annual_delta=0)
    except Exception:
        return []
    violation = (policy.violations or {}).get(team_id)
    if not violation or str(violation.get("kind")) != "max":
        return []
    over = int(violation.get("over", 0) or 0)
    if over <= 0:
        return []
    return [
        NotificationEvent(
            rule_id="finance_payroll_over",
            severity="warning",
            title="Payroll over the luxury threshold",
            message=(
                f"Payroll is ${over:,} over the luxury threshold — the tax "
                "will apply at settlement."
            ),
            sim_date=sim_date,
            payload={"team_id": team_id, "over": over},
            stop_sim=bool(rule.stop_sim),
        )
    ]


def _detect_finance_negative_net(
    team_id: str,
    settings: NotificationSettings,
    pre_state: DaySnapshot,
    new_phase: Optional[str],
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    """Fire when projected monthly net is negative. Phase-change days only."""

    rule = settings.rule("finance_negative_net")
    if not rule.enabled or not rule.notify:
        return []
    if not new_phase or new_phase == pre_state.phase:
        return []
    try:
        from services.owner_finance_engine import get_team_finance_snapshot

        snapshot = get_team_finance_snapshot(team_id)
    except Exception:
        return []
    if snapshot is None:
        return []
    net = int(getattr(snapshot, "projected_net", 0) or 0)
    if net >= 0:
        return []
    return [
        NotificationEvent(
            rule_id="finance_negative_net",
            severity="warning",
            title="Projected net is negative",
            message=(
                f"Projected monthly net is -${abs(net):,}. Review your budgets "
                "on the Finance page."
            ),
            sim_date=sim_date,
            payload={"team_id": team_id, "projected_net": net},
            stop_sim=bool(rule.stop_sim),
        )
    ]


def _detect_phase_transition(
    team_id: str,
    settings: NotificationSettings,
    pre_state: DaySnapshot,
    new_phase: Optional[str],
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    if not new_phase or new_phase == pre_state.phase:
        return []
    rule = settings.rule("phase_transition")
    if not rule.enabled or not rule.notify:
        return []
    return [
        NotificationEvent(
            rule_id="phase_transition",
            severity="warning",
            title="Season phase change",
            message=f"Phase changed: {pre_state.phase or 'UNKNOWN'} → {new_phase}",
            sim_date=sim_date,
            payload={"team_id": team_id, "previous": pre_state.phase, "current": new_phase},
            stop_sim=bool(rule.stop_sim),
        )
    ]


def _detect_finance_cash_low(
    team_id: str,
    settings: NotificationSettings,
    pre_state: DaySnapshot,
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    rule = settings.rule("finance_cash_low")
    if not rule.enabled or not rule.notify:
        return []
    cash = _team_finance_cash(team_id)
    if cash is None:
        return []
    threshold = int(rule.threshold or 0)
    if threshold <= 0:
        return []
    pre_cash = pre_state.cash_on_hand if pre_state.cash_on_hand is not None else cash
    # Fire only when crossing threshold (yesterday above, today below).
    if cash <= threshold and pre_cash > threshold:
        return [
            NotificationEvent(
                rule_id="finance_cash_low",
                severity="critical",
                title="Cash running low",
                message=f"Cash on hand fell to ${cash:,} (threshold ${threshold:,}).",
                sim_date=sim_date,
                payload={"team_id": team_id, "cash": cash, "threshold": threshold},
                stop_sim=bool(rule.stop_sim),
            )
        ]
    return []


def _detect_lineup_validity(
    team_id: str,
    settings: NotificationSettings,
    sim_date: Optional[str],
) -> List[NotificationEvent]:
    """Run the lineup + pitching validators against the saved files."""

    rule_lineup = settings.rule("lineup_invalid")
    rule_pitching = settings.rule("pitching_staff_invalid")
    rule_cap = settings.rule("roster_cap_violation")
    if not (
        (rule_lineup.enabled and rule_lineup.notify)
        or (rule_pitching.enabled and rule_pitching.notify)
        or (rule_cap.enabled and rule_cap.notify)
    ):
        return []

    events: List[NotificationEvent] = []
    try:
        from services.roster_validation import (
            validate_lineup,
            validate_pitching_staff,
        )
        from utils.roster_loader import load_roster
        from utils.lineup_loader import load_lineup
        from utils.player_loader import load_players_from_csv
    except Exception:
        return []

    try:
        players_list = load_players_from_csv("data/players.csv")
        players_map = {
            getattr(p, "player_id", ""): {
                "primary_position": getattr(p, "primary_position", ""),
                "other_positions": getattr(p, "other_positions", []),
                "is_pitcher": getattr(p, "is_pitcher", False),
            }
            for p in players_list
        }
    except Exception:
        players_map = {}

    if rule_lineup.enabled and rule_lineup.notify:
        for vs in ("lhp", "rhp"):
            try:
                lineup = load_lineup(team_id, vs)
            except Exception:
                continue
            if not lineup:
                continue
            try:
                rows = [
                    {"order": i + 1, "player_id": pid, "position": pos}
                    for i, (pid, pos) in enumerate(lineup)
                ]
                result = validate_lineup(lineup_rows=rows, players=players_map, vs=vs)
            except Exception:
                continue
            if not result.ok:
                events.append(
                    NotificationEvent(
                        rule_id="lineup_invalid",
                        severity="warning",
                        title=f"Lineup invalid (vs {vs.upper()})",
                        message="; ".join(result.errors[:3]) or "Lineup has errors.",
                        sim_date=sim_date,
                        payload={"team_id": team_id, "vs": vs, "errors": list(result.errors)},
                        stop_sim=bool(rule_lineup.stop_sim),
                    )
                )

    if rule_pitching.enabled and rule_pitching.notify:
        try:
            pitching_path = get_data_dir() / "rosters" / f"{team_id}_pitching.csv"
            staff_rows = []
            if pitching_path.exists():
                import csv
                with pitching_path.open("r", encoding="utf-8", newline="") as fh:
                    for row in csv.reader(fh):
                        if len(row) >= 2:
                            staff_rows.append({"player_id": row[0].strip(), "role": row[1].strip().upper()})
            try:
                roster_obj = load_roster(team_id)
                roster_ids = (
                    list(roster_obj.act)
                    + list(roster_obj.aaa)
                    + list(roster_obj.low)
                    + list(roster_obj.dl)
                    + list(roster_obj.ir)
                )
            except Exception:
                roster_ids = []
            result = validate_pitching_staff(
                staff=staff_rows,
                players=players_map,
                roster_ids=roster_ids,
            )
            if not result.ok:
                events.append(
                    NotificationEvent(
                        rule_id="pitching_staff_invalid",
                        severity="warning",
                        title="Pitching staff incomplete",
                        message="; ".join(result.errors[:3]) or "Pitching staff has errors.",
                        sim_date=sim_date,
                        payload={"team_id": team_id, "errors": list(result.errors)},
                        stop_sim=bool(rule_pitching.stop_sim),
                    )
                )
        except Exception:
            pass

    if rule_cap.enabled and rule_cap.notify:
        try:
            roster_obj = load_roster(team_id)
            cap_errors: List[str] = []
            if len(list(roster_obj.act)) > 25:
                cap_errors.append(f"Active roster has {len(list(roster_obj.act))} players (max 25).")
            if len(list(roster_obj.aaa)) > 15:
                cap_errors.append(f"AAA has {len(list(roster_obj.aaa))} players (max 15).")
            if len(list(roster_obj.low)) > 10:
                cap_errors.append(f"LOW-A has {len(list(roster_obj.low))} players (max 10).")
            if cap_errors:
                events.append(
                    NotificationEvent(
                        rule_id="roster_cap_violation",
                        severity="warning",
                        title="Roster cap violation",
                        message="; ".join(cap_errors),
                        sim_date=sim_date,
                        payload={"team_id": team_id, "errors": cap_errors},
                        stop_sim=bool(rule_cap.stop_sim),
                    )
                )
        except Exception:
            pass

    return events


def _rule_title(rule_id: str) -> str:
    titles = {
        "injury_day_to_day": "Player day-to-day",
        "injury_dl15": "Player on 15-day DL",
        "injury_dl45": "Player on 45-day DL",
        "injury_ir60": "Player on 60-day IR",
        "injury_season_ending": "Season-ending injury",
        "injury_returned": "Player returned from injury",
        "lineup_invalid": "Lineup invalid",
        "pitching_staff_invalid": "Pitching staff incomplete",
        "roster_cap_violation": "Roster cap violation",
        "win_streak": "Win streak",
        "losing_streak": "Losing streak",
        "player_milestone": "Player milestone",
        "clinched_division": "Division clinched",
        "eliminated": "Eliminated from contention",
        "trade_offer_received": "Trade offer received",
        "trade_decided": "Trade outcome",
        "fa_signed_elsewhere": "Free agent signed elsewhere",
        "contract_expiring": "Contract expiring",
        "trade_deadline_approaching": "Trade deadline approaching",
        "phase_transition": "Phase transition",
        "all_star_break": "All-Star break",
        "finance_cash_low": "Cash running low",
        "finance_payroll_over": "Payroll over threshold",
        "finance_negative_net": "Projected negative net",
        "commissioner_action_required": "Commissioner action required",
        "schedule_regenerated": "Schedule regenerated",
        "draft_approaching": "Draft approaching",
        "draft_results_posted": "Draft results posted",
    }
    return titles.get(rule_id, rule_id.replace("_", " ").title())


def detect_events(
    team_id: str,
    settings: NotificationSettings,
    pre_state: DaySnapshot,
    *,
    sim_date: Optional[str] = None,
    new_phase: Optional[str] = None,
    run_lineup_validators: bool = False,
) -> List[NotificationEvent]:
    """Run every detector and return events whose rule is enabled.

    ``run_lineup_validators`` is opt-in because the validators load
    every player file, so we don't want to run them every day. The
    season runner triggers them on phase transitions instead.
    """

    new_news = _read_news_tail(pre_state.news_size)
    events: List[NotificationEvent] = []
    events.extend(_detect_news_events(team_id, settings, new_news, sim_date))
    events.extend(_detect_streak(team_id, settings, pre_state, sim_date))
    events.extend(_detect_phase_transition(team_id, settings, pre_state, new_phase, sim_date))
    events.extend(_detect_finance_cash_low(team_id, settings, pre_state, sim_date))
    events.extend(_detect_finance_payroll_over(team_id, settings, pre_state, new_phase, sim_date))
    events.extend(_detect_finance_negative_net(team_id, settings, pre_state, new_phase, sim_date))
    if run_lineup_validators:
        events.extend(_detect_lineup_validity(team_id, settings, sim_date))
    return events


# ---------------------------------------------------------------------------
# History persistence


def _history_path(team_id: str) -> Path:
    base = get_data_dir() / "notifications"
    base.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in team_id if ch.isalnum() or ch in {"-", "_"}) or "team"
    return base / f"{safe}.history.jsonl"


def append_history(team_id: str, events: Iterable[NotificationEvent]) -> int:
    path = _history_path(team_id)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict()) + "\n")
            count += 1
    return count


def load_history(team_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    path = _history_path(team_id)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for raw in lines[-limit:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    out.reverse()  # newest first
    return out
