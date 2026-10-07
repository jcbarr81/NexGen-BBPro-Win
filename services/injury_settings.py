"""Persistence helpers for league-wide injury settings."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
from typing import Dict, Mapping, MutableMapping, Optional

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "InjurySettings",
    "DEFAULT_LEVEL",
    "LEVEL_OPTIONS",
    "DURABILITY_CENTER_FILENAME",
    "load_injury_settings",
    "save_injury_settings",
    "set_injury_level",
    "get_injury_tuning_overrides",
    "league_pitcher_durability_center",
    "active_pitcher_mean_durability",
]

VERSION = 1
DURABILITY_CENTER_FILENAME = "pitcher_durability_center.json"
# (league dir, season) -> centre; the file is the source of truth.
_CENTER_CACHE: Dict[tuple, float] = {}
_CENTER_LOCK = threading.Lock()


def _settings_path() -> Path:
    return get_data_dir() / "injury_settings.json"

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
    """Return physics-sim tuning overrides for the current injury settings.

    Besides the level, this carries the league's pitcher durability centre
    for the arm-injury hazard (``pitcher_arm_durability_center``), so a
    pitcher's durability is read against his own league (audit decision 2).
    """

    settings = load_injury_settings()
    overrides = settings.tuning_overrides()
    try:
        center = league_pitcher_durability_center()
    except Exception:  # pragma: no cover - defensive
        center = None
    if center is not None:
        overrides["pitcher_arm_durability_center"] = center
    return overrides


def league_pitcher_durability_center(
    *,
    data_dir: Path | str | None = None,
    season: str | int | None = None,
) -> Optional[float]:
    """Mean durability of the league's active-roster pitchers, fixed per season.

    Computed the first time a season asks for it and stored in
    ``<league>/pitcher_durability_center.json``, so it never moves mid-season
    (decision 2: "computed once per season") and every process -- serial,
    parallel workers, a fresh Cloud Run instance -- reads the same number.
    ``None`` when the league has no active pitchers to average.
    """

    base = Path(data_dir) if data_dir is not None else get_data_dir()
    season_key = str(season) if season is not None else _season_key(base)
    cache_key = (str(base.resolve(strict=False)), season_key)
    with _CENTER_LOCK:
        cached = _CENTER_CACHE.get(cache_key)
        if cached is not None:
            return cached
        path = base / DURABILITY_CENTER_FILENAME
        payload = _read_json(path)
        seasons = payload.get("seasons") if isinstance(payload, dict) else None
        if not isinstance(seasons, dict):
            seasons = {}
        stored = seasons.get(season_key)
        try:
            value = float(stored) if stored is not None else None
        except (TypeError, ValueError):
            value = None
        if value is None:
            value = active_pitcher_mean_durability(base)
            if value is None:
                return None
            # Keep the last few seasons for reference; the current one rules.
            seasons[season_key] = value
            keep = sorted(seasons)[-5:]
            _write_json_atomic(
                path,
                {"version": VERSION, "seasons": {k: seasons[k] for k in keep}},
            )
        _CENTER_CACHE[cache_key] = value
        return value


def _season_key(base: Path) -> str:
    """The current season's year, from the league's sim date."""

    try:
        from utils.sim_date import get_current_sim_date

        token = str(get_current_sim_date() or "").strip()
        if base.resolve(strict=False) != get_data_dir().resolve(strict=False):
            token = ""
        if len(token) >= 4 and token[:4].isdigit():
            return token[:4]
    except Exception:  # pragma: no cover - defensive
        pass
    return "default"


def active_pitcher_mean_durability(base: Path) -> Optional[float]:
    """Average durability over every club's ACT pitchers (players.csv rows)."""

    from utils.roster_rules import counts_as_pitcher

    players_path = base / "players.csv"
    roster_dir = base / "rosters"
    if not players_path.exists() or not roster_dir.is_dir():
        return None
    active: set[str] = set()
    for roster_file in sorted(roster_dir.glob("*.csv")):
        if "_" in roster_file.stem:
            continue  # <team>_pitching.csv and other side files
        try:
            with roster_file.open(newline="", encoding="utf-8") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[1].strip().upper() == "ACT":
                        active.add(row[0].strip())
        except OSError:
            continue
    values: list[float] = []
    try:
        with players_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if str(row.get("player_id") or "").strip() not in active:
                    continue
                if not counts_as_pitcher(row):
                    continue
                try:
                    values.append(float(row.get("durability") or 50.0))
                except (TypeError, ValueError):
                    values.append(50.0)
    except OSError:
        return None
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _read_json(path: Path) -> Dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:  # pragma: no cover - best effort; the value is still used
        pass


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
    settings_path = _settings_path()
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_payload(payload: MutableMapping[str, object]) -> None:
    settings_path = _settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
