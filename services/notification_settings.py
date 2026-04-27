"""Per-team notification preferences.

The owner picks which league events are worth flagging while the sim
runs day-by-day. Each rule has three knobs:

* ``enabled``  — log to the notification history at all.
* ``notify``   — push a banner/toast in the UI.
* ``stop_sim`` — break a multi-day ``simulate/days`` run early so the
                 owner can review and react before any more days tick.

Some rules carry a numeric ``threshold`` (streak length, days-out
horizon, etc.) — those are rendered as a number input on the
NotificationsPage.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from utils.path_utils import get_data_dir

__all__ = [
    "DEFAULT_RULES",
    "RULE_CATEGORIES",
    "NotificationRule",
    "NotificationSettings",
    "load_notification_settings",
    "save_notification_settings",
    "rules_index",
]


# Rule schema --------------------------------------------------------------
# Every rule has a stable id; the UI renders categories in the order
# defined here. Adding a new rule just needs a new dict entry plus a
# detector implementation in services.notification_engine.
RULE_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "health_roster",
        "label": "Health & roster",
        "rules": [
            {
                "id": "injury_day_to_day",
                "label": "Player day-to-day",
                "default_notify": True,
                "default_stop": False,
            },
            {
                "id": "injury_dl15",
                "label": "Player placed on 15-day DL",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "injury_dl45",
                "label": "Player placed on 45-day DL",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "injury_ir60",
                "label": "Player placed on 60-day IR",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "injury_season_ending",
                "label": "Season-ending injury",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "injury_returned",
                "label": "Player returned from injury",
                "default_notify": True,
                "default_stop": False,
            },
            {
                "id": "lineup_invalid",
                "label": "Lineup invalid",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "pitching_staff_invalid",
                "label": "Pitching staff incomplete",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "roster_cap_violation",
                "label": "Roster cap violation",
                "default_notify": True,
                "default_stop": True,
            },
        ],
    },
    {
        "id": "performance",
        "label": "Performance & milestones",
        "rules": [
            {
                "id": "win_streak",
                "label": "Win streak",
                "default_notify": True,
                "default_stop": False,
                "threshold": 5,
                "threshold_label": "Notify at length",
                "threshold_min": 2,
                "threshold_max": 30,
            },
            {
                "id": "losing_streak",
                "label": "Losing streak",
                "default_notify": True,
                "default_stop": False,
                "threshold": 5,
                "threshold_label": "Notify at length",
                "threshold_min": 2,
                "threshold_max": 30,
            },
            {
                "id": "player_milestone",
                "label": "Player milestone (no-hitter, perfect game, hitting streak, etc.)",
                "default_notify": True,
                "default_stop": False,
            },
            {
                "id": "clinched_division",
                "label": "Division clinched",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "eliminated",
                "label": "Eliminated from playoff contention",
                "default_notify": True,
                "default_stop": False,
            },
        ],
    },
    {
        "id": "transactions",
        "label": "Transactions",
        "rules": [
            {
                "id": "trade_offer_received",
                "label": "Trade offer received",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "trade_decided",
                "label": "Trade approved or vetoed",
                "default_notify": True,
                "default_stop": False,
            },
            {
                "id": "fa_signed_elsewhere",
                "label": "Watched free agent signed elsewhere",
                "default_notify": True,
                "default_stop": False,
            },
            {
                "id": "contract_expiring",
                "label": "Player entering final contract year",
                "default_notify": True,
                "default_stop": False,
            },
        ],
    },
    {
        "id": "calendar",
        "label": "Calendar & deadlines",
        "rules": [
            {
                "id": "trade_deadline_approaching",
                "label": "Trade deadline approaching",
                "default_notify": True,
                "default_stop": False,
                "threshold": 7,
                "threshold_label": "Notify N days out",
                "threshold_min": 1,
                "threshold_max": 30,
            },
            {
                "id": "phase_transition",
                "label": "Season phase change (preseason / regular / playoffs / offseason)",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "all_star_break",
                "label": "All-Star break",
                "default_notify": True,
                "default_stop": False,
            },
        ],
    },
    {
        "id": "finance",
        "label": "Finance",
        "rules": [
            {
                "id": "finance_cash_low",
                "label": "Cash on hand running low",
                "default_notify": True,
                "default_stop": True,
                "threshold": 2_000_000,
                "threshold_label": "Trigger at cash <= $",
                "threshold_min": 0,
                "threshold_max": 50_000_000,
            },
            {
                "id": "finance_payroll_over",
                "label": "Payroll over luxury threshold",
                "default_notify": True,
                "default_stop": False,
            },
            {
                "id": "finance_negative_net",
                "label": "Projected monthly net is negative",
                "default_notify": True,
                "default_stop": False,
            },
        ],
    },
    {
        "id": "league_admin",
        "label": "League & admin",
        "rules": [
            {
                "id": "commissioner_action_required",
                "label": "Commissioner action required (admin role only)",
                "default_notify": True,
                "default_stop": True,
            },
            {
                "id": "schedule_regenerated",
                "label": "Schedule regenerated (hard reset notice)",
                "default_notify": True,
                "default_stop": False,
            },
        ],
    },
    {
        "id": "draft",
        "label": "Draft",
        "rules": [
            {
                "id": "draft_approaching",
                "label": "Amateur draft approaching",
                "default_notify": True,
                "default_stop": False,
                "threshold": 14,
                "threshold_label": "Notify N days out",
                "threshold_min": 1,
                "threshold_max": 60,
            },
            {
                "id": "draft_results_posted",
                "label": "Draft results posted",
                "default_notify": True,
                "default_stop": False,
            },
        ],
    },
]


def _flat_rule_specs() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cat in RULE_CATEGORIES:
        for spec in cat["rules"]:
            entry = dict(spec)
            entry["category"] = cat["id"]
            out.append(entry)
    return out


_RULE_SPECS: List[Dict[str, Any]] = _flat_rule_specs()
_RULE_BY_ID: Dict[str, Dict[str, Any]] = {spec["id"]: spec for spec in _RULE_SPECS}


@dataclass
class NotificationRule:
    enabled: bool = True
    notify: bool = True
    stop_sim: bool = False
    threshold: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "enabled": bool(self.enabled),
            "notify": bool(self.notify),
            "stop_sim": bool(self.stop_sim),
        }
        if self.threshold is not None:
            out["threshold"] = self.threshold
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], spec: Mapping[str, Any]) -> "NotificationRule":
        threshold = raw.get("threshold", spec.get("threshold"))
        if threshold is not None:
            try:
                threshold = float(threshold)
            except (TypeError, ValueError):
                threshold = float(spec.get("threshold", 0))
        return cls(
            enabled=bool(raw.get("enabled", True)),
            notify=bool(raw.get("notify", spec.get("default_notify", True))),
            stop_sim=bool(raw.get("stop_sim", spec.get("default_stop", False))),
            threshold=threshold,
        )


@dataclass
class NotificationSettings:
    team_id: str
    rules: Dict[str, NotificationRule] = field(default_factory=dict)

    def rule(self, rule_id: str) -> NotificationRule:
        return self.rules.get(rule_id) or NotificationRule(enabled=False, notify=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_id": self.team_id,
            "rules": {rid: r.to_dict() for rid, r in self.rules.items()},
        }


# Defaults -----------------------------------------------------------------


def _default_rule(spec: Mapping[str, Any]) -> NotificationRule:
    threshold = spec.get("threshold")
    return NotificationRule(
        enabled=True,
        notify=bool(spec.get("default_notify", True)),
        stop_sim=bool(spec.get("default_stop", False)),
        threshold=float(threshold) if threshold is not None else None,
    )


def DEFAULT_RULES() -> Dict[str, NotificationRule]:
    return {spec["id"]: _default_rule(spec) for spec in _RULE_SPECS}


def rules_index() -> List[Dict[str, Any]]:
    """Return the full rule schema for the UI to render checkboxes/inputs."""

    return [
        {
            "id": cat["id"],
            "label": cat["label"],
            "rules": [
                {
                    "id": spec["id"],
                    "label": spec["label"],
                    "default_notify": bool(spec.get("default_notify", True)),
                    "default_stop": bool(spec.get("default_stop", False)),
                    "threshold": spec.get("threshold"),
                    "threshold_label": spec.get("threshold_label"),
                    "threshold_min": spec.get("threshold_min"),
                    "threshold_max": spec.get("threshold_max"),
                }
                for spec in cat["rules"]
            ],
        }
        for cat in RULE_CATEGORIES
    ]


# Persistence --------------------------------------------------------------


def _path(team_id: str) -> Path:
    base = get_data_dir() / "notifications"
    base.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in team_id if ch.isalnum() or ch in {"-", "_"}) or "team"
    return base / f"{safe}.json"


def load_notification_settings(team_id: str) -> NotificationSettings:
    path = _path(team_id)
    if not path.exists():
        return NotificationSettings(team_id=team_id, rules=DEFAULT_RULES())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return NotificationSettings(team_id=team_id, rules=DEFAULT_RULES())

    rules_raw = raw.get("rules") if isinstance(raw, dict) else {}
    rules: Dict[str, NotificationRule] = {}
    for spec in _RULE_SPECS:
        rid = spec["id"]
        existing = rules_raw.get(rid) if isinstance(rules_raw, dict) else None
        if isinstance(existing, dict):
            rules[rid] = NotificationRule.from_dict(existing, spec)
        else:
            rules[rid] = _default_rule(spec)
    return NotificationSettings(team_id=team_id, rules=rules)


def save_notification_settings(
    team_id: str, payload: Mapping[str, Any]
) -> NotificationSettings:
    """Merge ``payload`` (raw rule dict from the UI) onto the saved file."""

    settings = load_notification_settings(team_id)
    rules_raw = payload.get("rules") if isinstance(payload, Mapping) else None
    if isinstance(rules_raw, Mapping):
        for rid, raw in rules_raw.items():
            spec = _RULE_BY_ID.get(rid)
            if spec is None or not isinstance(raw, Mapping):
                continue
            settings.rules[rid] = NotificationRule.from_dict(raw, spec)

    path = _path(team_id)
    path.write_text(
        json.dumps(settings.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return settings
