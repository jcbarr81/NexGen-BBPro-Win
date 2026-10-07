"""Per-team owner play settings (Release 3, 2026-10 engine audit).

One store for the game-day choices an owner makes for their own club:

``auto_rest_days``
    The engine sits overworked regulars at game time (the saved lineup is
    never changed). Default ON.
``rest_subs_similar_positions``
    A resting regular may be replaced by a player from a similar position
    (LF/RF, CF to a corner, SS to 2B/3B, any infielder to 1B) when nobody
    lists the exact position. Default ON.
``il_auto_activate_15``
    Players come off the 15-day IL on their own when their minimum lapses.
    Default: the league's ``auto_activate_il`` setting, i.e. what the league
    does today.
``il_auto_activate_60``
    The same for the 60-day IL. Default OFF (60-day returns are manual today).

Only an owner's explicit choices are stored; a missing team or key reads as
the default at the time of the read, so ``il_auto_activate_15`` follows the
league setting until the owner picks a value. CPU-owned clubs are not
governed by this store -- the consumers always rest, substitute and
auto-activate for them.

File: ``<league data dir>/team_play_settings.json``::

    {"version": 1, "teams": {"ABC": {"il_auto_activate_60": true}}}

Nothing in the sim reads these settings yet; Release 3 items C, E and F wire
them in.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping

from utils.path_utils import get_data_dir

__all__ = [
    "AUTO_REST_DAYS",
    "REST_SUBS_SIMILAR_POSITIONS",
    "IL_AUTO_ACTIVATE_15",
    "IL_AUTO_ACTIVATE_60",
    "TEAM_PLAY_SETTING_KEYS",
    "SETTINGS_FILENAME",
    "default_team_play_settings",
    "load_team_play_overrides",
    "load_team_play_settings",
    "save_team_play_settings",
    "get_team_play_setting",
]

VERSION = 1
SETTINGS_FILENAME = "team_play_settings.json"

AUTO_REST_DAYS = "auto_rest_days"
REST_SUBS_SIMILAR_POSITIONS = "rest_subs_similar_positions"
IL_AUTO_ACTIVATE_15 = "il_auto_activate_15"
IL_AUTO_ACTIVATE_60 = "il_auto_activate_60"

TEAM_PLAY_SETTING_KEYS: tuple[str, ...] = (
    AUTO_REST_DAYS,
    REST_SUBS_SIMILAR_POSITIONS,
    IL_AUTO_ACTIVATE_15,
    IL_AUTO_ACTIVATE_60,
)

# Values that clear a stored choice so the team follows the default again.
_DEFAULT_TOKENS = {"", "default", "league_default", "inherit"}
_TRUE_TOKENS = {"1", "true", "yes", "on", "enabled", "enable"}
_FALSE_TOKENS = {"0", "false", "no", "off", "disabled", "disable"}

# Serialises read-modify-write cycles within one process.
_LOCK = threading.Lock()


def default_team_play_settings(
    *, data_dir: Path | str | None = None
) -> dict[str, bool]:
    """Return the defaults every team starts from, for the league at ``data_dir``."""

    return {
        AUTO_REST_DAYS: True,
        REST_SUBS_SIMILAR_POSITIONS: True,
        IL_AUTO_ACTIVATE_15: _league_auto_activate_il(data_dir),
        IL_AUTO_ACTIVATE_60: False,
    }


def load_team_play_overrides(
    team_id: str | None, *, data_dir: Path | str | None = None
) -> dict[str, bool]:
    """Return only the settings the owner of ``team_id`` has explicitly chosen."""

    clean_team_id = _normalize_team_id(team_id)
    if not clean_team_id:
        return {}
    teams = _load_payload(data_dir).get("teams")
    if not isinstance(teams, Mapping):
        return {}
    return _clean_overrides(teams.get(clean_team_id))


def load_team_play_settings(
    team_id: str | None, *, data_dir: Path | str | None = None
) -> dict[str, bool]:
    """Return every setting for ``team_id``: stored choices over the defaults."""

    settings = default_team_play_settings(data_dir=data_dir)
    settings.update(load_team_play_overrides(team_id, data_dir=data_dir))
    return settings


def save_team_play_settings(
    team_id: str | None,
    updates: Mapping[str, object],
    *,
    data_dir: Path | str | None = None,
) -> dict[str, bool]:
    """Store the owner's choices for ``team_id`` and return the resolved settings.

    ``updates`` maps setting keys to booleans (or "on"/"off"-style tokens).
    ``None`` or ``"default"`` clears a stored choice so the team follows the
    default again. Keys not named in ``updates`` keep their stored value.
    Raises ``ValueError`` for an unknown key, an unreadable value or a missing
    team id; nothing is written in that case.
    """

    clean_team_id = _normalize_team_id(team_id)
    if not clean_team_id:
        raise ValueError("Team id is required.")
    parsed: dict[str, bool | None] = {}
    for key, value in dict(updates or {}).items():
        if key not in TEAM_PLAY_SETTING_KEYS:
            raise ValueError(f"Unknown team play setting: {key!r}")
        parsed[key] = _parse_setting(key, value)

    with _LOCK:
        payload = _load_payload(data_dir)
        teams = payload.get("teams")
        if not isinstance(teams, dict):
            teams = {}
        current = _clean_overrides(teams.get(clean_team_id))
        for key, value in parsed.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        if current:
            teams[clean_team_id] = current
        else:
            teams.pop(clean_team_id, None)
        payload["version"] = VERSION
        payload["teams"] = teams
        _write_payload(payload, data_dir)
    return load_team_play_settings(clean_team_id, data_dir=data_dir)


def get_team_play_setting(
    team_id: str | None, key: str, *, data_dir: Path | str | None = None
) -> bool:
    """Return one setting for ``team_id``, falling back to its default.

    A missing file, team or key reads as the default. Raises ``KeyError`` for
    a key that is not a team play setting.
    """

    if key not in TEAM_PLAY_SETTING_KEYS:
        raise KeyError(key)
    stored = load_team_play_overrides(team_id, data_dir=data_dir)
    if key in stored:
        return stored[key]
    return default_team_play_settings(data_dir=data_dir)[key]


def _league_auto_activate_il(data_dir: Path | str | None) -> bool:
    from utils.league_settings import auto_activate_il, load_league_settings

    path = None if data_dir is None else Path(data_dir) / "league_settings.json"
    try:
        return bool(auto_activate_il(load_league_settings(path)))
    except Exception:
        return True


def _normalize_team_id(team_id: object) -> str:
    return str(team_id or "").strip().upper()


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return None


def _parse_setting(key: str, value: object) -> bool | None:
    """Return the boolean to store, or ``None`` to clear the stored choice."""

    if value is None or (
        isinstance(value, str) and value.strip().lower() in _DEFAULT_TOKENS
    ):
        return None
    parsed = _coerce_bool(value)
    if parsed is None:
        raise ValueError(f"Invalid value for {key}: {value!r}")
    return parsed


def _clean_overrides(raw: object) -> dict[str, bool]:
    """Keep the known keys whose stored values read as booleans."""

    if not isinstance(raw, Mapping):
        return {}
    clean: dict[str, bool] = {}
    for key in TEAM_PLAY_SETTING_KEYS:
        if key not in raw:
            continue
        value = _coerce_bool(raw[key])
        if value is not None:
            clean[key] = value
    return clean


def _payload_path(data_dir: Path | str | None) -> Path:
    base = get_data_dir() if data_dir is None else Path(data_dir)
    return base / SETTINGS_FILENAME


def _load_payload(data_dir: Path | str | None) -> dict[str, Any]:
    path = _payload_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return {"version": VERSION, "teams": {}}
    return payload


def _write_payload(payload: Mapping[str, object], data_dir: Path | str | None) -> None:
    path = _payload_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
