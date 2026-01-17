"""Persistence helpers for league-wide injury settings."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, MutableMapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_base_dir

__all__ = [
    "InjurySettings",
    "DEFAULT_LEVEL",
    "LEVEL_OPTIONS",
    "load_injury_settings",
    "save_injury_settings",
    "set_injury_level",
    "get_injury_tuning_overrides",
]

VERSION = 1
SETTINGS_PATH = get_base_dir() / "data" / "injury_settings.json"

LEVEL_OPTIONS: Dict[str, Dict[str, float]] = {
    "off": {"injuries_enabled": 0.0, "injury_rate_scale": 0.0},
    "low": {"injuries_enabled": 1.0, "injury_rate_scale": 0.05},
    "normal": {"injuries_enabled": 1.0, "injury_rate_scale": 0.1},
}
DEFAULT_LEVEL = "normal"


@dataclass
class InjurySettings:
    league_id: str
    level: str

    def tuning_overrides(self) -> Dict[str, float]:
        level_key = _normalize_level(self.level)
        return dict(LEVEL_OPTIONS[level_key])


def load_injury_settings() -> InjurySettings:
    """Return the league-wide injury settings."""

    payload = _load_payload()
    league_id = _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    data = leagues.get(league_id, {})
    level = _normalize_level(str(data.get("level") or DEFAULT_LEVEL))
    return InjurySettings(league_id=league_id, level=level)


def save_injury_settings(settings: InjurySettings) -> None:
    """Persist ``settings`` to disk."""

    payload = _load_payload()
    leagues = payload.setdefault("leagues", {})
    leagues[settings.league_id] = {"level": _normalize_level(settings.level)}
    payload["version"] = VERSION
    _write_payload(payload)


def set_injury_level(level: str) -> InjurySettings:
    """Set the current league's injury level and persist it."""

    settings = load_injury_settings()
    settings.level = _normalize_level(level)
    save_injury_settings(settings)
    return settings


def get_injury_tuning_overrides() -> Dict[str, float]:
    """Return physics-sim tuning overrides for the current injury settings."""

    settings = load_injury_settings()
    return settings.tuning_overrides()


def _normalize_level(value: str) -> str:
    key = str(value or "").strip().lower()
    if key in LEVEL_OPTIONS:
        return key
    return DEFAULT_LEVEL


def _resolve_league_id() -> str:
    try:
        ctx = SeasonContext.load()
        league_id = ctx.league_id
        if league_id:
            return league_id
        return ctx.ensure_league()
    except Exception:
        return "league"


def _load_payload() -> Dict[str, object]:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_payload(payload: MutableMapping[str, object]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
