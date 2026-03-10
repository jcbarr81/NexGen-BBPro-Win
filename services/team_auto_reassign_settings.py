"""League-scoped auto-reassign settings and helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "TeamAutoReassignPreference",
    "DEFAULT_ENABLED",
    "load_team_auto_reassign_settings",
    "save_team_auto_reassign_settings",
    "update_league_default_auto_reassign",
    "set_team_auto_reassign",
    "resolve_team_auto_reassign",
    "is_team_auto_reassign_enabled",
    "auto_reassign_team_if_enabled",
]

VERSION = 1
SETTINGS_FILENAME = "team_auto_reassign_settings.json"
DEFAULT_ENABLED = False


@dataclass(frozen=True)
class TeamAutoReassignPreference:
    """Resolved auto-reassign preference for one team."""

    team_id: str
    enabled: bool
    source: str


def load_team_auto_reassign_settings(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Return normalized auto-reassign settings for one league."""

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

    default_enabled = _normalize_enabled(raw.get("default_enabled"), DEFAULT_ENABLED)
    team_overrides: dict[str, bool] = {}
    raw_teams = raw.get("teams")
    if isinstance(raw_teams, Mapping):
        for team_id_key, enabled in raw_teams.items():
            clean_team_id = str(team_id_key or "").strip().upper()
            if not clean_team_id:
                continue
            resolved_enabled = _normalize_enabled(enabled, default_enabled)
            if resolved_enabled == default_enabled:
                continue
            team_overrides[clean_team_id] = resolved_enabled
    return {
        "league_id": resolved_league_id,
        "default_enabled": default_enabled,
        "team_overrides": team_overrides,
    }


def save_team_auto_reassign_settings(
    *,
    default_enabled: bool | None = None,
    team_overrides: Mapping[str, object] | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Persist full auto-reassign settings for one league."""

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    existing = load_team_auto_reassign_settings(
        data_dir=data_dir,
        league_id=resolved_league_id,
    )
    resolved_default = _normalize_enabled(
        default_enabled,
        bool(existing.get("default_enabled", DEFAULT_ENABLED)),
    )

    source_overrides = (
        team_overrides
        if team_overrides is not None
        else existing.get("team_overrides", {})
    )
    clean_overrides: dict[str, bool] = {}
    if isinstance(source_overrides, Mapping):
        for team_id_key, enabled in source_overrides.items():
            clean_team_id = str(team_id_key or "").strip().upper()
            if not clean_team_id:
                continue
            resolved_enabled = _normalize_enabled(enabled, resolved_default)
            if resolved_enabled == resolved_default:
                continue
            clean_overrides[clean_team_id] = resolved_enabled

    raw["default_enabled"] = resolved_default
    raw["teams"] = clean_overrides
    leagues[resolved_league_id] = raw
    _write_payload(payload, data_dir=data_dir)
    return load_team_auto_reassign_settings(
        data_dir=data_dir,
        league_id=resolved_league_id,
    )


def update_league_default_auto_reassign(
    enabled: bool,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Update only the league default auto-reassign setting."""

    return save_team_auto_reassign_settings(
        default_enabled=bool(enabled),
        data_dir=data_dir,
        league_id=league_id,
    )


def set_team_auto_reassign(
    team_id: str | None,
    setting: object,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Persist one team override, or clear it when set to league default."""

    clean_team_id = str(team_id or "").strip().upper()
    if not clean_team_id:
        return {"saved": False, "message": "Team id is required."}

    settings = load_team_auto_reassign_settings(data_dir=data_dir, league_id=league_id)
    default_enabled = bool(settings.get("default_enabled", DEFAULT_ENABLED))
    overrides = dict(settings.get("team_overrides", {}))

    use_default = False
    if setting is None:
        use_default = True
    else:
        token = str(setting).strip().lower()
        if token in {"", "default", "league_default", "inherit"}:
            use_default = True

    if use_default:
        overrides.pop(clean_team_id, None)
        enabled = default_enabled
        source = "league_default"
    else:
        enabled = _normalize_enabled(setting, default_enabled)
        if enabled == default_enabled:
            overrides.pop(clean_team_id, None)
            source = "league_default"
        else:
            overrides[clean_team_id] = enabled
            source = "team_override"

    save_team_auto_reassign_settings(
        default_enabled=default_enabled,
        team_overrides=overrides,
        data_dir=data_dir,
        league_id=league_id,
    )
    return {
        "saved": True,
        "team_id": clean_team_id,
        "enabled": enabled,
        "source": source,
    }


def resolve_team_auto_reassign(
    team_id: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> TeamAutoReassignPreference:
    """Return resolved auto-reassign preference for one team."""

    clean_team_id = str(team_id or "").strip().upper()
    settings = load_team_auto_reassign_settings(data_dir=data_dir, league_id=league_id)
    default_enabled = bool(settings.get("default_enabled", DEFAULT_ENABLED))
    enabled = default_enabled
    source = "league_default"
    overrides = settings.get("team_overrides", {})
    if clean_team_id and isinstance(overrides, Mapping) and clean_team_id in overrides:
        enabled = bool(overrides.get(clean_team_id))
        source = "team_override"
    return TeamAutoReassignPreference(
        team_id=clean_team_id,
        enabled=enabled,
        source=source,
    )


def is_team_auto_reassign_enabled(
    team_id: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> bool:
    """Return whether auto-reassign is enabled for ``team_id``."""

    return bool(
        resolve_team_auto_reassign(
            team_id,
            data_dir=data_dir,
            league_id=league_id,
        ).enabled
    )


def auto_reassign_team_if_enabled(
    team_id: str | None,
    *,
    players_file: str | Path = "data/players.csv",
    roster_dir: str | Path = "data/rosters",
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> bool:
    """Run policy-based team auto-reassign when enabled for ``team_id``."""

    clean_team_id = str(team_id or "").strip().upper()
    if not clean_team_id:
        return False
    preference = resolve_team_auto_reassign(
        clean_team_id,
        data_dir=data_dir,
        league_id=league_id,
    )
    if not preference.enabled:
        return False

    resolved_data_dir = _resolve_data_dir(data_dir)
    resolved_players_file = _resolve_child_path(players_file, resolved_data_dir)
    resolved_roster_dir = _resolve_child_path(roster_dir, resolved_data_dir)

    from services.roster_auto_assign import auto_assign_team
    from utils.roster_loader import load_roster

    auto_assign_team(
        clean_team_id,
        players_file=str(resolved_players_file),
        roster_dir=str(resolved_roster_dir),
    )
    try:
        load_roster.cache_clear(team_id=clean_team_id, roster_dir=resolved_roster_dir)  # type: ignore[attr-defined]
    except Exception:
        try:
            load_roster.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass
    return True


def _normalize_enabled(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = str(value or "").strip().lower()
    if token in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if token in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return bool(fallback)


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


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    if data_dir is None:
        return get_data_dir()
    return Path(data_dir)


def _resolve_child_path(raw_path: str | Path, data_dir: Path) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and str(parts[0]).lower() == "data":
        suffix = parts[1:]
        if suffix:
            return data_dir.joinpath(*suffix)
        return data_dir
    return path


def _payload_path(data_dir: Path | str | None = None) -> Path:
    base = _resolve_data_dir(data_dir)
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


def _write_payload(
    payload: Mapping[str, object],
    *,
    data_dir: Path | str | None = None,
) -> None:
    path = _payload_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
