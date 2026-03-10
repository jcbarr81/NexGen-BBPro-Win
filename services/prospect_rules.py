"""Prospect protection and roster-move eligibility rule enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from playbalance.season_context import SeasonContext
from services.decision_explanations import (
    append_decision_log,
    explanation,
    reason,
    should_persist_decision_logs,
)
from services.prospect_event_log import record_protection_event
from services.team_strategy_profiles import resolve_team_strategy_profile
from utils.path_utils import get_data_dir

__all__ = [
    "ProspectRulesSettings",
    "ProspectMoveDecision",
    "DEFAULT_ENABLED",
    "DEFAULT_REQUIRE_PROTECTION_FOR_ACT_PROMOTION",
    "DEFAULT_AUTO_PROTECT_ON_PROMOTION",
    "DEFAULT_ENFORCE_OPTION_LIMITS",
    "DEFAULT_OPTION_YEARS",
    "load_prospect_rules",
    "save_prospect_rules",
    "update_prospect_rules",
    "is_player_protected",
    "set_player_protection",
    "evaluate_roster_move",
    "apply_roster_move",
    "remaining_options",
]

VERSION = 1
DEFAULT_ENABLED = False
DEFAULT_REQUIRE_PROTECTION_FOR_ACT_PROMOTION = True
DEFAULT_AUTO_PROTECT_ON_PROMOTION = False
DEFAULT_ENFORCE_OPTION_LIMITS = True
DEFAULT_OPTION_YEARS = 3
MIN_OPTION_YEARS = 0
MAX_OPTION_YEARS = 10
_STRATEGY_DEVELOPMENT_FOCUS = "development_focus"


@dataclass
class ProspectRulesSettings:
    league_id: str
    enabled: bool = DEFAULT_ENABLED
    require_protection_for_act_promotion: bool = (
        DEFAULT_REQUIRE_PROTECTION_FOR_ACT_PROMOTION
    )
    auto_protect_on_promotion: bool = DEFAULT_AUTO_PROTECT_ON_PROMOTION
    enforce_option_limits: bool = DEFAULT_ENFORCE_OPTION_LIMITS
    default_option_years: int = DEFAULT_OPTION_YEARS
    protected_players: dict[str, list[str]] = field(default_factory=dict)
    player_option_limits: dict[str, int] = field(default_factory=dict)
    option_assignments: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)

    def normalized(self) -> "ProspectRulesSettings":
        protected: dict[str, list[str]] = {}
        for raw_team_id, raw_players in (self.protected_players or {}).items():
            team_id = str(raw_team_id or "").strip()
            if not team_id:
                continue
            values = sorted(
                {
                    str(player_id or "").strip()
                    for player_id in (raw_players or [])
                    if str(player_id or "").strip()
                }
            )
            if values:
                protected[team_id] = values
        option_limits: dict[str, int] = {}
        for raw_player_id, raw_value in (self.player_option_limits or {}).items():
            player_id = str(raw_player_id or "").strip()
            if not player_id:
                continue
            option_limits[player_id] = _normalize_option_years(raw_value)

        assignments: dict[str, dict[str, dict[str, int]]] = {}
        for raw_season, raw_teams in (self.option_assignments or {}).items():
            season_id = str(raw_season or "").strip()
            if not season_id or not isinstance(raw_teams, Mapping):
                continue
            team_payload: dict[str, dict[str, int]] = {}
            for raw_team_id, raw_players in raw_teams.items():
                team_id = str(raw_team_id or "").strip()
                if not team_id or not isinstance(raw_players, Mapping):
                    continue
                player_payload: dict[str, int] = {}
                for raw_player_id, raw_count in raw_players.items():
                    player_id = str(raw_player_id or "").strip()
                    if not player_id:
                        continue
                    try:
                        count = int(raw_count)
                    except Exception:
                        count = 0
                    player_payload[player_id] = max(0, count)
                if player_payload:
                    team_payload[team_id] = player_payload
            if team_payload:
                assignments[season_id] = team_payload

        return ProspectRulesSettings(
            league_id=_normalize_league_id(self.league_id),
            enabled=bool(self.enabled),
            require_protection_for_act_promotion=bool(
                self.require_protection_for_act_promotion
            ),
            auto_protect_on_promotion=bool(self.auto_protect_on_promotion),
            enforce_option_limits=bool(self.enforce_option_limits),
            default_option_years=_normalize_option_years(self.default_option_years),
            protected_players=protected,
            player_option_limits=option_limits,
            option_assignments=assignments,
        )


@dataclass
class ProspectMoveDecision:
    allowed: bool
    reason: str = ""
    requires_auto_protect: bool = False
    from_level: str = ""
    to_level: str = ""
    reason_tag: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    decision_explanation: dict[str, Any] = field(default_factory=dict)


def _build_move_decision(
    *,
    allowed: bool,
    reason_message: str = "",
    reason_tag: str = "",
    requires_auto_protect: bool = False,
    from_level: str = "",
    to_level: str = "",
    team_id: str = "",
    player_id: str = "",
    details: Mapping[str, object] | None = None,
    context: Mapping[str, object] | None = None,
    rules_enabled: bool = True,
) -> ProspectMoveDecision:
    normalized_reason = str(reason_message or "").strip()
    normalized_tag = str(reason_tag or "").strip()
    if not normalized_tag:
        normalized_tag = "move_allowed" if allowed else "move_blocked"
    detail_payload = dict(details or {})
    context_payload: dict[str, object] = {
        "from_level": str(from_level or "").strip(),
        "to_level": str(to_level or "").strip(),
        "requires_auto_protect": bool(requires_auto_protect),
        "prospect_rules_enabled": bool(rules_enabled),
    }
    context_payload.update(dict(context or {}))

    reasons_payload = []
    if normalized_reason:
        reasons_payload.append(
            reason(
                normalized_tag,
                normalized_reason,
                details=detail_payload,
            )
        )
    elif detail_payload:
        reasons_payload.append(
            reason(
                normalized_tag,
                "Prospect move decision evaluated.",
                details=detail_payload,
            )
        )

    payload = explanation(
        "prospect_roster_move",
        "allowed" if allowed else "blocked",
        actor="system",
        team_id=str(team_id or "").strip() or None,
        subject_id=str(player_id or "").strip() or None,
        context=context_payload,
        reasons=reasons_payload,
    ).to_dict()
    if should_persist_decision_logs():
        append_decision_log(payload)
    return ProspectMoveDecision(
        allowed=bool(allowed),
        reason=normalized_reason,
        requires_auto_protect=bool(requires_auto_protect),
        from_level=str(from_level or "").strip(),
        to_level=str(to_level or "").strip(),
        reason_tag=normalized_tag,
        details=detail_payload,
        decision_explanation=payload,
    )


def _resolve_season_id(season_id: str | None = None) -> str:
    if season_id:
        return str(season_id).strip()
    try:
        ctx = SeasonContext.load()
        current = ctx.ensure_current_season()
        token = str(current.get("season_id") or "").strip()
        if token:
            return token
    except Exception:
        pass
    return f"season-{datetime.now().year}"


def _resolve_league_id() -> str:
    try:
        ctx = SeasonContext.load()
        if ctx.league_id:
            return _normalize_league_id(ctx.league_id)
        return _normalize_league_id(ctx.ensure_league())
    except Exception:
        return "league"


def _normalize_league_id(value: object) -> str:
    token = str(value or "").strip()
    return token or "league"


def _settings_path(path: Path | str | None = None) -> Path:
    return Path(path) if path is not None else (get_data_dir() / "prospect_rules.json")


def _strategy_data_dir(path: Path | str | None = None) -> Path | None:
    if path is None:
        return None
    try:
        raw = Path(path)
    except Exception:
        return None
    if raw.exists() and raw.is_dir():
        return raw
    return raw.parent


def _team_strategy_profile(
    team_id: str,
    *,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> str:
    try:
        resolved = resolve_team_strategy_profile(
            team_id,
            data_dir=_strategy_data_dir(path),
            league_id=league_id,
        )
        return str(getattr(resolved, "profile", "balanced") or "balanced").strip().lower()
    except Exception:
        return "balanced"


def _strategy_auto_protect_on_promotion(
    team_id: str,
    *,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> bool:
    return _team_strategy_profile(
        team_id,
        path=path,
        league_id=league_id,
    ) == _STRATEGY_DEVELOPMENT_FOCUS


def _load_payload(path: Path | str | None = None) -> dict[str, object]:
    target_path = _settings_path(path)
    if target_path.exists():
        try:
            payload = json.loads(target_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_payload(payload: Mapping[str, object], path: Path | str | None = None) -> None:
    target_path = _settings_path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalize_level(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in {"act", "active"}:
        return "act"
    if token in {"aaa", "triple-a", "triplea"}:
        return "aaa"
    if token in {"low", "a", "single-a", "singlea"}:
        return "low"
    return token


def _normalize_option_years(value: object) -> int:
    try:
        years = int(value)  # type: ignore[arg-type]
    except Exception:
        return DEFAULT_OPTION_YEARS
    return max(MIN_OPTION_YEARS, min(years, MAX_OPTION_YEARS))


def load_prospect_rules(
    path: Path | str | None = None,
    *,
    league_id: str | None = None,
) -> ProspectRulesSettings:
    payload = _load_payload(path=path)
    leagues = payload.setdefault("leagues", {})
    resolved_league_id = _normalize_league_id(league_id) if league_id else _resolve_league_id()
    data = leagues.get(resolved_league_id, {})
    if not data and isinstance(leagues, dict) and len(leagues) == 1:
        data = next(iter(leagues.values()), {})
    if not isinstance(data, dict):
        data = {}
    settings = ProspectRulesSettings(
        league_id=resolved_league_id,
        enabled=bool(data.get("enabled", DEFAULT_ENABLED)),
        require_protection_for_act_promotion=bool(
            data.get(
                "require_protection_for_act_promotion",
                DEFAULT_REQUIRE_PROTECTION_FOR_ACT_PROMOTION,
            )
        ),
        auto_protect_on_promotion=bool(
            data.get("auto_protect_on_promotion", DEFAULT_AUTO_PROTECT_ON_PROMOTION)
        ),
        enforce_option_limits=bool(
            data.get("enforce_option_limits", DEFAULT_ENFORCE_OPTION_LIMITS)
        ),
        default_option_years=_normalize_option_years(
            data.get("default_option_years", DEFAULT_OPTION_YEARS)
        ),
        protected_players=dict(data.get("protected_players", {})),
        player_option_limits=dict(data.get("player_option_limits", {})),
        option_assignments=dict(data.get("option_assignments", {})),
    )
    return settings.normalized()


def save_prospect_rules(
    settings: ProspectRulesSettings,
    path: Path | str | None = None,
    *,
    league_id: str | None = None,
) -> ProspectRulesSettings:
    payload = _load_payload(path=path)
    leagues = payload.setdefault("leagues", {})
    normalized = settings.normalized()
    target_league_id = _normalize_league_id(league_id) if league_id else normalized.league_id
    leagues[target_league_id] = {
        "enabled": normalized.enabled,
        "require_protection_for_act_promotion": normalized.require_protection_for_act_promotion,
        "auto_protect_on_promotion": normalized.auto_protect_on_promotion,
        "enforce_option_limits": normalized.enforce_option_limits,
        "default_option_years": normalized.default_option_years,
        "protected_players": normalized.protected_players,
        "player_option_limits": normalized.player_option_limits,
        "option_assignments": normalized.option_assignments,
    }
    payload["version"] = VERSION
    _write_payload(payload, path=path)
    return normalized


def update_prospect_rules(
    *,
    enabled: bool | None = None,
    require_protection_for_act_promotion: bool | None = None,
    auto_protect_on_promotion: bool | None = None,
    enforce_option_limits: bool | None = None,
    default_option_years: int | None = None,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> ProspectRulesSettings:
    settings = load_prospect_rules(path=path, league_id=league_id)
    if enabled is not None:
        settings.enabled = bool(enabled)
    if require_protection_for_act_promotion is not None:
        settings.require_protection_for_act_promotion = bool(
            require_protection_for_act_promotion
        )
    if auto_protect_on_promotion is not None:
        settings.auto_protect_on_promotion = bool(auto_protect_on_promotion)
    if enforce_option_limits is not None:
        settings.enforce_option_limits = bool(enforce_option_limits)
    if default_option_years is not None:
        settings.default_option_years = _normalize_option_years(default_option_years)
    return save_prospect_rules(settings, path=path, league_id=league_id)


def is_player_protected(
    team_id: str,
    player_id: str,
    *,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> bool:
    settings = load_prospect_rules(path=path, league_id=league_id)
    team_key = str(team_id or "").strip()
    player_key = str(player_id or "").strip()
    if not team_key or not player_key:
        return False
    return player_key in set(settings.protected_players.get(team_key, []))


def set_player_protection(
    team_id: str,
    player_id: str,
    *,
    protected: bool,
    actor: str = "system",
    trigger: str = "",
    path: Path | str | None = None,
    league_id: str | None = None,
) -> ProspectRulesSettings:
    settings = load_prospect_rules(path=path, league_id=league_id)
    team_key = str(team_id or "").strip()
    player_key = str(player_id or "").strip()
    if not team_key or not player_key:
        return settings
    team_players = set(settings.protected_players.get(team_key, []))
    previous = player_key in team_players
    if protected:
        team_players.add(player_key)
    else:
        team_players.discard(player_key)
    if team_players:
        settings.protected_players[team_key] = sorted(team_players)
    else:
        settings.protected_players.pop(team_key, None)
    saved = save_prospect_rules(settings, path=path, league_id=league_id)
    if previous != protected:
        try:
            record_protection_event(
                team_id=team_key,
                player_id=player_key,
                status="protected" if protected else "unprotected",
                actor=actor,
                trigger=trigger,
            )
        except Exception:
            pass
    return saved


def _option_limit_for_player(
    settings: ProspectRulesSettings,
    player_id: str,
) -> int:
    player_key = str(player_id or "").strip()
    if not player_key:
        return settings.default_option_years
    return _normalize_option_years(
        settings.player_option_limits.get(player_key, settings.default_option_years)
    )


def _option_assignments_used(
    settings: ProspectRulesSettings,
    *,
    season_id: str,
    team_id: str,
    player_id: str,
) -> int:
    season_payload = settings.option_assignments.get(season_id, {})
    team_payload = season_payload.get(team_id, {})
    try:
        return max(0, int(team_payload.get(player_id, 0)))
    except Exception:
        return 0


def remaining_options(
    team_id: str,
    player_id: str,
    *,
    season_id: str | None = None,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> int:
    settings = load_prospect_rules(path=path, league_id=league_id)
    season_key = _resolve_season_id(season_id)
    team_key = str(team_id or "").strip()
    player_key = str(player_id or "").strip()
    limit = _option_limit_for_player(settings, player_key)
    used = _option_assignments_used(
        settings,
        season_id=season_key,
        team_id=team_key,
        player_id=player_key,
    )
    return max(0, limit - used)


def evaluate_roster_move(
    team_id: str,
    player_id: str,
    *,
    from_level: str,
    to_level: str,
    season_id: str | None = None,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> ProspectMoveDecision:
    """Validate whether a roster move is allowed by prospect rules."""

    settings = load_prospect_rules(path=path, league_id=league_id)
    src = _normalize_level(from_level)
    dst = _normalize_level(to_level)
    if src == dst:
        return _build_move_decision(
            allowed=True,
            reason_message="No roster-level change required.",
            reason_tag="no_level_change",
            from_level=src,
            to_level=dst,
            rules_enabled=settings.enabled,
        )
    if not settings.enabled:
        return _build_move_decision(
            allowed=True,
            reason_message="Prospect rules are disabled for this league.",
            reason_tag="rules_disabled",
            from_level=src,
            to_level=dst,
            rules_enabled=False,
        )

    team_key = str(team_id or "").strip()
    player_key = str(player_id or "").strip()
    if not team_key or not player_key:
        return _build_move_decision(
            allowed=True,
            reason_message=(
                "Move allowed because team/player context was incomplete for "
                "prospect-rule checks."
            ),
            reason_tag="missing_context",
            from_level=src,
            to_level=dst,
            team_id=team_key,
            player_id=player_key,
            rules_enabled=settings.enabled,
        )

    if (
        settings.require_protection_for_act_promotion
        and src in {"aaa", "low"}
        and dst == "act"
    ):
        if is_player_protected(team_key, player_key, path=path, league_id=league_id):
            return _build_move_decision(
                allowed=True,
                reason_message=(
                    "Player is protected and eligible for promotion to ACT."
                ),
                reason_tag="protected_promotion",
                from_level=src,
                to_level=dst,
                team_id=team_key,
                player_id=player_key,
                rules_enabled=settings.enabled,
            )
        strategy_auto_protect = _strategy_auto_protect_on_promotion(
            team_key,
            path=path,
            league_id=league_id,
        )
        if settings.auto_protect_on_promotion or strategy_auto_protect:
            auto_reason = (
                "Team strategy auto-protects this promotion."
                if strategy_auto_protect and not settings.auto_protect_on_promotion
                else "League setting auto-protects this promotion."
            )
            return _build_move_decision(
                allowed=True,
                requires_auto_protect=True,
                reason_message=auto_reason,
                reason_tag=(
                    "strategy_auto_protect"
                    if strategy_auto_protect and not settings.auto_protect_on_promotion
                    else "league_auto_protect"
                ),
                from_level=src,
                to_level=dst,
                team_id=team_key,
                player_id=player_key,
                details={
                    "auto_protect_on_promotion": bool(settings.auto_protect_on_promotion),
                    "strategy_auto_protect": bool(strategy_auto_protect),
                },
                rules_enabled=settings.enabled,
            )
        return _build_move_decision(
            allowed=False,
            reason_message=(
                "Player is not protected and cannot be promoted to ACT while "
                "prospect protection rules are enabled."
            ),
            reason_tag="protection_required",
            from_level=src,
            to_level=dst,
            team_id=team_key,
            player_id=player_key,
            details={"require_protection_for_act_promotion": True},
            rules_enabled=settings.enabled,
        )

    if settings.enforce_option_limits and src == "act" and dst in {"aaa", "low"}:
        season_key = _resolve_season_id(season_id)
        option_limit = _option_limit_for_player(settings, player_key)
        used = _option_assignments_used(
            settings,
            season_id=season_key,
            team_id=team_key,
            player_id=player_key,
        )
        if used >= option_limit:
            return _build_move_decision(
                allowed=False,
                reason_message=(
                    f"Player has no option assignments remaining this season "
                    f"({used}/{option_limit} used)."
                ),
                reason_tag="option_limit_reached",
                from_level=src,
                to_level=dst,
                team_id=team_key,
                player_id=player_key,
                details={
                    "season_id": season_key,
                    "options_used": used,
                    "option_limit": option_limit,
                    "options_remaining": max(0, option_limit - used),
                },
                rules_enabled=settings.enabled,
            )
        return _build_move_decision(
            allowed=True,
            reason_message=(
                f"Player has option assignments remaining "
                f"({used}/{option_limit} used)."
            ),
            reason_tag="option_available",
            from_level=src,
            to_level=dst,
            team_id=team_key,
            player_id=player_key,
            details={
                "season_id": season_key,
                "options_used": used,
                "option_limit": option_limit,
                "options_remaining": max(0, option_limit - used),
            },
            rules_enabled=settings.enabled,
        )

    return _build_move_decision(
        allowed=True,
        reason_message="Move allowed by current prospect rule settings.",
        reason_tag="rules_passed",
        from_level=src,
        to_level=dst,
        team_id=team_key,
        player_id=player_key,
        rules_enabled=settings.enabled,
    )


def apply_roster_move(
    team_id: str,
    player_id: str,
    *,
    from_level: str,
    to_level: str,
    decision: ProspectMoveDecision | None = None,
    season_id: str | None = None,
    actor: str = "system",
    trigger: str = "",
    path: Path | str | None = None,
    league_id: str | None = None,
) -> ProspectRulesSettings:
    """Persist rule-side effects after a successful roster move."""

    settings = load_prospect_rules(path=path, league_id=league_id)
    if not settings.enabled:
        return settings
    team_key = str(team_id or "").strip()
    player_key = str(player_id or "").strip()
    src = _normalize_level(from_level)
    dst = _normalize_level(to_level)
    if not team_key or not player_key or src == dst:
        return settings
    verdict = decision or evaluate_roster_move(
        team_key,
        player_key,
        from_level=src,
        to_level=dst,
        season_id=season_id,
        path=path,
        league_id=league_id,
    )
    if not verdict.allowed:
        return settings

    changed = False
    if verdict.requires_auto_protect and src in {"aaa", "low"} and dst == "act":
        team_players = set(settings.protected_players.get(team_key, []))
        if player_key not in team_players:
            team_players.add(player_key)
            settings.protected_players[team_key] = sorted(team_players)
            changed = True
            try:
                record_protection_event(
                    team_id=team_key,
                    player_id=player_key,
                    status="protected",
                    actor=actor,
                    trigger=trigger or "auto_protect_on_promotion",
                    details={"source": "prospect_rules"},
                )
            except Exception:
                pass

    if settings.enforce_option_limits and src == "act" and dst in {"aaa", "low"}:
        season_key = _resolve_season_id(season_id)
        season_payload = settings.option_assignments.setdefault(season_key, {})
        team_payload = season_payload.setdefault(team_key, {})
        try:
            used = int(team_payload.get(player_key, 0))
        except Exception:
            used = 0
        team_payload[player_key] = max(0, used) + 1
        changed = True

    if changed:
        return save_prospect_rules(settings, path=path, league_id=league_id)
    return settings
