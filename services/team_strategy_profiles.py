"""League-scoped team strategy profile persistence and resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Mapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "TeamStrategyProfile",
    "DEFAULT_PROFILE",
    "STRATEGY_PROFILES",
    "load_team_strategy_settings",
    "save_team_strategy_settings",
    "update_league_default_strategy",
    "set_team_strategy_profile",
    "resolve_team_strategy_profile",
    "to_finance_strategy_profile",
]

VERSION = 1
SETTINGS_FILENAME = "team_strategy_profiles.json"

PROFILE_BALANCED = "balanced"
PROFILE_WIN_NOW = "win_now"
PROFILE_DEVELOPMENT_FOCUS = "development_focus"
PROFILE_DEFENSE_FIRST = "defense_first"
PROFILE_POWER_OFFENSE = "power_offense"
DEFAULT_PROFILE = PROFILE_BALANCED

STRATEGY_PROFILES: Dict[str, Dict[str, str]] = {
    PROFILE_BALANCED: {
        "label": "Balanced",
        "description": "Even talent usage with no extreme roster bias.",
    },
    PROFILE_WIN_NOW: {
        "label": "Win Now",
        "description": "Prioritize current-season performance and veteran readiness.",
    },
    PROFILE_DEVELOPMENT_FOCUS: {
        "label": "Development Focus",
        "description": "Prioritize growth runway and prospect-friendly decisions.",
    },
    PROFILE_DEFENSE_FIRST: {
        "label": "Defense First",
        "description": "Lean toward run prevention, coverage, and stable fielding.",
    },
    PROFILE_POWER_OFFENSE: {
        "label": "Power Offense",
        "description": "Lean toward extra-base impact and middle-order run production.",
    },
}

_FINANCE_PROFILE_MAP: Dict[str, str] = {
    PROFILE_BALANCED: "balanced",
    PROFILE_WIN_NOW: "contend",
    PROFILE_DEVELOPMENT_FOCUS: "rebuild",
    PROFILE_DEFENSE_FIRST: "balanced",
    PROFILE_POWER_OFFENSE: "contend",
}


@dataclass(frozen=True)
class TeamStrategyProfile:
    team_id: str
    profile: str
    label: str
    description: str
    source: str


def load_team_strategy_settings(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Return normalized team strategy settings for one league."""

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, Mapping):
        raw = {}
    if not raw and isinstance(leagues, Mapping) and len(leagues) == 1:
        only_league_id, only_data = next(iter(leagues.items()))
        if isinstance(only_league_id, str) and only_league_id.strip():
            resolved_league_id = only_league_id
        if isinstance(only_data, Mapping):
            raw = only_data
    default_profile = _normalize_profile(raw.get("default_profile"))
    team_overrides: dict[str, str] = {}
    raw_teams = raw.get("teams")
    if isinstance(raw_teams, Mapping):
        for team_id, profile in raw_teams.items():
            clean_team_id = str(team_id or "").strip().upper()
            if not clean_team_id:
                continue
            clean_profile = _normalize_profile(profile)
            if clean_profile == default_profile:
                continue
            team_overrides[clean_team_id] = clean_profile
    return {
        "league_id": resolved_league_id,
        "default_profile": default_profile,
        "team_overrides": team_overrides,
    }


def save_team_strategy_settings(
    *,
    default_profile: str | None = None,
    team_overrides: Mapping[str, str] | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Persist full strategy settings for one league."""

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    existing = load_team_strategy_settings(data_dir=data_dir, league_id=resolved_league_id)
    resolved_default = _normalize_profile(
        default_profile if default_profile is not None else existing["default_profile"]
    )

    clean_overrides: dict[str, str] = {}
    source_overrides = team_overrides
    if source_overrides is None:
        source_overrides = existing.get("team_overrides", {})
    if isinstance(source_overrides, Mapping):
        for team_id, profile in source_overrides.items():
            clean_team_id = str(team_id or "").strip().upper()
            if not clean_team_id:
                continue
            clean_profile = _normalize_profile(profile)
            if clean_profile == resolved_default:
                continue
            clean_overrides[clean_team_id] = clean_profile

    raw["default_profile"] = resolved_default
    raw["teams"] = clean_overrides
    leagues[resolved_league_id] = raw
    _write_payload(payload, data_dir=data_dir)
    return load_team_strategy_settings(data_dir=data_dir, league_id=resolved_league_id)


def update_league_default_strategy(
    profile: str,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Update only the league default strategy profile."""

    return save_team_strategy_settings(
        default_profile=profile,
        data_dir=data_dir,
        league_id=league_id,
    )


def set_team_strategy_profile(
    team_id: str | None,
    profile: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Persist one team override. Empty/default clears the override."""

    clean_team_id = str(team_id or "").strip().upper()
    if not clean_team_id:
        return {"saved": False, "message": "Team id is required."}

    settings = load_team_strategy_settings(data_dir=data_dir, league_id=league_id)
    default_profile = str(settings.get("default_profile") or DEFAULT_PROFILE)
    overrides = dict(settings.get("team_overrides", {}))
    raw_profile = str(profile or "").strip().lower()
    if raw_profile in {"", "default", "league_default"}:
        overrides.pop(clean_team_id, None)
        target_profile = default_profile
        source = "league_default"
    else:
        target_profile = _normalize_profile(raw_profile)
        if target_profile == default_profile:
            overrides.pop(clean_team_id, None)
            source = "league_default"
        else:
            overrides[clean_team_id] = target_profile
            source = "team_override"

    save_team_strategy_settings(
        default_profile=default_profile,
        team_overrides=overrides,
        data_dir=data_dir,
        league_id=league_id,
    )
    meta = STRATEGY_PROFILES.get(target_profile, STRATEGY_PROFILES[DEFAULT_PROFILE])
    return {
        "saved": True,
        "team_id": clean_team_id,
        "profile": target_profile,
        "source": source,
        "label": str(meta.get("label", "Balanced")),
    }


def resolve_team_strategy_profile(
    team_id: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> TeamStrategyProfile:
    """Return resolved profile metadata for one team."""

    clean_team_id = str(team_id or "").strip().upper()
    settings = load_team_strategy_settings(data_dir=data_dir, league_id=league_id)
    default_profile = str(settings.get("default_profile") or DEFAULT_PROFILE)
    overrides = settings.get("team_overrides", {})
    source = "league_default"
    profile = default_profile
    if clean_team_id and isinstance(overrides, Mapping):
        team_profile = overrides.get(clean_team_id)
        if isinstance(team_profile, str) and team_profile.strip():
            profile = _normalize_profile(team_profile)
            source = "team_override"
    meta = STRATEGY_PROFILES.get(profile, STRATEGY_PROFILES[DEFAULT_PROFILE])
    return TeamStrategyProfile(
        team_id=clean_team_id,
        profile=profile,
        label=str(meta.get("label", "Balanced")),
        description=str(meta.get("description", "")),
        source=source,
    )


def to_finance_strategy_profile(profile: str | None) -> str:
    """Map team strategy profile to finance AI profile family."""

    token = _normalize_profile(profile)
    mapped = _FINANCE_PROFILE_MAP.get(token)
    if isinstance(mapped, str) and mapped.strip():
        return mapped
    return "balanced"


def _normalize_profile(profile: object) -> str:
    token = str(profile or "").strip().lower()
    if token in STRATEGY_PROFILES:
        return token
    return DEFAULT_PROFILE


def _normalize_league_id(value: object) -> str:
    return str(value or "").strip()


def _resolve_league_id() -> str:
    try:
        ctx = SeasonContext.load()
        league_id = str(getattr(ctx, "league_id", "") or "").strip()
        if league_id:
            return league_id
        return str(ctx.ensure_league() or "league")
    except Exception:
        return "league"


def _payload_path(data_dir: Path | str | None = None) -> Path:
    if data_dir is None:
        base = get_data_dir()
    else:
        base = Path(data_dir)
    return base / SETTINGS_FILENAME


def _load_payload(*, data_dir: Path | str | None = None) -> dict[str, object]:
    path = _payload_path(data_dir)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_payload(payload: Mapping[str, object], *, data_dir: Path | str | None = None) -> None:
    path = _payload_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
