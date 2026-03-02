"""League-scoped scouting fog-of-war state and projection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir
from utils.sim_date import get_current_sim_date
from utils.team_loader import load_teams

VERSION = 1
DEFAULT_ENABLED = False
DEFAULT_BASE_MONTHLY_CREDITS = 120.0
DEFAULT_FINANCE_OFF_MULTIPLIER = 0.90
DEFAULT_MONTHLY_DECAY = 0.003
DEFAULT_CONFIDENCE = 0.35
DEFAULT_CONFIDENCE_FLOOR = 0.05
DEFAULT_CONFIDENCE_CEILING = 0.98
DEFAULT_MAX_BANKED_CREDITS = 500.0
DEFAULT_AUTO_SPEND_CAP = 80.0
DEFAULT_INTENSITY = "normal"
DEFAULT_PASSIVE_GAIN = 0.003

INTENSITY_MULTIPLIERS = {
    "low": 0.80,
    "normal": 1.00,
    "high": 1.25,
}

SCOUTING_STATE_FILENAME = "scouting_state.json"


@dataclass(frozen=True)
class TeamScoutingProfile:
    enabled: bool
    team_id: str
    scouting_multiplier: float
    confidence_score: int
    confidence_label: str
    max_rating_error: int


def load_scouting_settings(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Return normalized scouting settings for the target league."""

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    settings = _normalize_settings(raw.get("settings"))
    return {
        "league_id": resolved_league_id,
        "enabled": bool(raw.get("enabled", DEFAULT_ENABLED)),
        **settings,
    }


def update_scouting_settings(
    *,
    enabled: bool | None = None,
    base_monthly_credits: float | None = None,
    finance_off_multiplier: float | None = None,
    monthly_decay: float | None = None,
    passive_gain: float | None = None,
    max_banked_credits: float | None = None,
    auto_spend_cap: float | None = None,
    confidence_floor: float | None = None,
    confidence_ceiling: float | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Persist scouting settings for the target league and return them."""

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    settings = _normalize_settings(raw.get("settings"))
    if base_monthly_credits is not None:
        settings["base_monthly_credits"] = max(0.0, float(base_monthly_credits))
    if finance_off_multiplier is not None:
        settings["finance_off_multiplier"] = _clamp(float(finance_off_multiplier), 0.50, 1.50)
    if monthly_decay is not None:
        settings["monthly_decay"] = _clamp(float(monthly_decay), 0.0, 0.10)
    if passive_gain is not None:
        settings["passive_gain"] = _clamp(float(passive_gain), 0.0, 0.10)
    if max_banked_credits is not None:
        settings["max_banked_credits"] = _clamp(float(max_banked_credits), 50.0, 10_000.0)
    if auto_spend_cap is not None:
        settings["auto_spend_cap"] = _clamp(float(auto_spend_cap), 10.0, 1_000.0)
    if confidence_floor is not None:
        settings["confidence_floor"] = _clamp(float(confidence_floor), 0.01, 0.90)
    if confidence_ceiling is not None:
        settings["confidence_ceiling"] = _clamp(float(confidence_ceiling), 0.20, 0.99)
    raw["settings"] = settings
    if enabled is not None:
        raw["enabled"] = bool(enabled)
    leagues[resolved_league_id] = raw
    _write_payload(payload, data_dir=data_dir)
    return load_scouting_settings(data_dir=data_dir, league_id=resolved_league_id)


def set_team_scouting_intensity(
    team_id: str | None,
    intensity: str,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> dict[str, object]:
    """Persist owner scouting intensity preference for one team."""

    clean_team_id = str(team_id or "").strip().upper()
    if not clean_team_id:
        return {"saved": False, "message": "Team id is required."}

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    settings = _normalize_settings(raw.get("settings"))
    teams = raw.get("teams")
    if not isinstance(teams, dict):
        teams = {}
    period = _period_token(None)
    team_state = _normalize_team_state(teams.get(clean_team_id), period=period, settings=settings)
    team_state["intensity"] = _normalize_intensity(intensity)
    teams[clean_team_id] = team_state

    raw["settings"] = settings
    raw["teams"] = teams
    leagues[resolved_league_id] = raw
    _write_payload(payload, data_dir=data_dir)
    return {
        "saved": True,
        "team_id": clean_team_id,
        "intensity": str(team_state["intensity"]),
    }


def load_team_scouting_controls(
    team_id: str | None,
    *,
    finance_enabled: bool = False,
    finance_multiplier: float = 1.0,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    current_date: str | None = None,
) -> dict[str, object]:
    """Return owner-facing scouting controls/status for one team."""

    clean_team_id = str(team_id or "").strip().upper()
    if not clean_team_id:
        return {
            "team_id": "",
            "enabled": False,
            "intensity": DEFAULT_INTENSITY,
            "credits": 0.0,
            "confidence": float(DEFAULT_CONFIDENCE),
            "confidence_score": 100,
            "confidence_label": "Exact",
            "max_rating_error": 0,
            "scouting_multiplier": 1.0,
            "estimated_monthly_income": 0.0,
        }

    profile = team_scouting_profile(
        clean_team_id,
        finance_enabled=finance_enabled,
        finance_multiplier=finance_multiplier,
        data_dir=data_dir,
        league_id=league_id,
        current_date=current_date,
    )

    payload = _load_payload(data_dir=data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    settings = _normalize_settings(raw.get("settings"))
    teams = raw.get("teams")
    if not isinstance(teams, dict):
        teams = {}
    team_state = _normalize_team_state(
        teams.get(clean_team_id),
        period=_period_token(current_date),
        settings=settings,
    )
    intensity = _normalize_intensity(team_state.get("intensity", DEFAULT_INTENSITY))
    team_state["intensity"] = intensity
    intensity_multiplier = float(INTENSITY_MULTIPLIERS.get(intensity, 1.0))
    active_multiplier = float(finance_multiplier) if finance_enabled else float(
        settings["finance_off_multiplier"]
    )
    monthly_income = max(
        0.0,
        float(settings["base_monthly_credits"]) * intensity_multiplier * active_multiplier,
    )
    return {
        "team_id": clean_team_id,
        "enabled": bool(profile.enabled),
        "intensity": intensity,
        "credits": round(float(team_state.get("credits", 0.0) or 0.0), 4),
        "confidence": round(float(team_state.get("confidence", DEFAULT_CONFIDENCE)), 4),
        "confidence_score": int(profile.confidence_score),
        "confidence_label": str(profile.confidence_label),
        "max_rating_error": int(profile.max_rating_error),
        "scouting_multiplier": round(float(profile.scouting_multiplier), 4),
        "estimated_monthly_income": round(float(monthly_income), 4),
    }


def team_scouting_profile(
    team_id: str | None,
    *,
    finance_enabled: bool,
    finance_multiplier: float = 1.0,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    current_date: str | None = None,
) -> TeamScoutingProfile:
    """Return current fog-of-war profile for ``team_id``."""

    clean_team_id = str(team_id or "").strip().upper()
    if not clean_team_id:
        return TeamScoutingProfile(
            enabled=False,
            team_id="",
            scouting_multiplier=1.0,
            confidence_score=100,
            confidence_label="Exact",
            max_rating_error=0,
        )

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    payload = _load_payload(data_dir=resolved_data_dir)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    raw = leagues.get(resolved_league_id, {})
    if not isinstance(raw, dict):
        raw = {}
    settings = _normalize_settings(raw.get("settings"))
    enabled = bool(raw.get("enabled", DEFAULT_ENABLED))
    teams = raw.get("teams")
    if not isinstance(teams, dict):
        teams = {}

    period = _period_token(current_date)
    changed = _seed_missing_teams(
        teams,
        period=period,
        settings=settings,
        data_dir=resolved_data_dir,
    )
    previous_team_state = teams.get(clean_team_id)
    team_state = _normalize_team_state(previous_team_state, period=period, settings=settings)
    if previous_team_state != team_state:
        teams[clean_team_id] = team_state
        changed = True
    else:
        teams[clean_team_id] = team_state

    if enabled:
        months_elapsed = _month_delta(str(team_state["last_period"]), period)
        if months_elapsed > 0:
            _apply_monthly_progression(
                team_state,
                months_elapsed=months_elapsed,
                settings=settings,
                finance_enabled=finance_enabled,
                finance_multiplier=finance_multiplier,
            )
            team_state["last_period"] = period
            changed = True

    raw["settings"] = settings
    raw["teams"] = teams
    leagues[resolved_league_id] = raw
    if changed:
        _write_payload(payload, data_dir=resolved_data_dir)

    confidence = float(team_state["confidence"])
    confidence_score = int(round(confidence * 100.0))
    if confidence_score >= 85:
        label = "Elite"
    elif confidence_score >= 65:
        label = "High"
    elif confidence_score >= 35:
        label = "Moderate"
    else:
        label = "Low"
    max_error = int(
        round(
            _clamp(
                1.0 + (((1.0 - confidence) ** 2) * 8.0),
                1.0,
                9.0,
            )
        )
    )

    if not enabled:
        return TeamScoutingProfile(
            enabled=False,
            team_id=clean_team_id,
            scouting_multiplier=1.0,
            confidence_score=100,
            confidence_label="Exact",
            max_rating_error=0,
        )

    return TeamScoutingProfile(
        enabled=True,
        team_id=clean_team_id,
        scouting_multiplier=float(finance_multiplier if finance_enabled else settings["finance_off_multiplier"]),
        confidence_score=max(0, min(100, confidence_score)),
        confidence_label=label,
        max_rating_error=max(1, max_error),
    )


def scouting_observed_value(
    value: object,
    *,
    team_profile: TeamScoutingProfile,
    player_id: str | None,
    metric_key: str,
    team_id: str | None,
    minimum: int = 0,
    maximum: int = 99,
) -> object:
    """Return deterministic observed scouting value for a metric."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value

    if not team_profile.enabled or team_profile.max_rating_error <= 0:
        rounded = int(round(numeric))
        return int(_clamp(float(rounded), float(minimum), float(maximum)))

    clean_player_id = str(player_id or "").strip() or "unknown"
    clean_team_id = str(team_id or "").strip().upper() or "NA"
    clean_key = str(metric_key or "").strip().upper() or "RATING"
    spread = int(team_profile.max_rating_error)
    offset = _deterministic_offset(
        f"{clean_player_id}|{clean_team_id}|{clean_key}",
        spread,
    )
    adjusted = int(round(numeric + offset))
    return int(_clamp(float(adjusted), float(minimum), float(maximum)))


def _apply_monthly_progression(
    team_state: dict[str, object],
    *,
    months_elapsed: int,
    settings: Mapping[str, object],
    finance_enabled: bool,
    finance_multiplier: float,
) -> None:
    confidence = float(team_state.get("confidence", DEFAULT_CONFIDENCE) or DEFAULT_CONFIDENCE)
    credits = float(team_state.get("credits", 0.0) or 0.0)
    intensity = str(team_state.get("intensity", DEFAULT_INTENSITY) or DEFAULT_INTENSITY).strip().lower()
    intensity_mult = float(INTENSITY_MULTIPLIERS.get(intensity, 1.0))
    confidence_floor = float(settings.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR))
    confidence_ceiling = float(settings.get("confidence_ceiling", DEFAULT_CONFIDENCE_CEILING))
    base_income = float(settings.get("base_monthly_credits", DEFAULT_BASE_MONTHLY_CREDITS))
    monthly_decay = float(settings.get("monthly_decay", DEFAULT_MONTHLY_DECAY))
    passive_gain = float(settings.get("passive_gain", DEFAULT_PASSIVE_GAIN))
    max_banked = float(settings.get("max_banked_credits", DEFAULT_MAX_BANKED_CREDITS))
    auto_spend_cap = float(settings.get("auto_spend_cap", DEFAULT_AUTO_SPEND_CAP))
    finance_off_mult = float(settings.get("finance_off_multiplier", DEFAULT_FINANCE_OFF_MULTIPLIER))
    active_multiplier = float(finance_multiplier) if finance_enabled else finance_off_mult
    monthly_income = max(0.0, base_income * intensity_mult * active_multiplier)
    effective_spend_cap = max(10.0, auto_spend_cap * active_multiplier)

    for _ in range(max(0, int(months_elapsed))):
        credits = min(max_banked, credits + monthly_income)
        spend = min(effective_spend_cap, credits)
        credits -= spend
        active_gain = min(0.08, 0.04 * math.sqrt(max(0.0, spend) / 25.0))
        gain = max(0.0, active_gain + passive_gain)
        confidence = _clamp(
            confidence + ((1.0 - confidence) * gain) - (confidence * monthly_decay),
            confidence_floor,
            confidence_ceiling,
        )

    team_state["credits"] = round(max(0.0, credits), 4)
    team_state["confidence"] = round(float(confidence), 4)


def _seed_missing_teams(
    teams: dict[str, object],
    *,
    period: str,
    settings: Mapping[str, object],
    data_dir: Path,
) -> bool:
    changed = False
    try:
        known_teams = load_teams(data_dir / "teams.csv")
    except Exception:
        known_teams = []
    for team in known_teams:
        team_id = str(getattr(team, "team_id", "") or "").strip().upper()
        if not team_id or team_id in teams:
            continue
        teams[team_id] = _normalize_team_state(None, period=period, settings=settings)
        changed = True
    return changed


def _normalize_team_state(
    raw: object,
    *,
    period: str,
    settings: Mapping[str, object],
) -> dict[str, object]:
    source = raw if isinstance(raw, Mapping) else {}
    intensity = _normalize_intensity(source.get("intensity", DEFAULT_INTENSITY))
    confidence_floor = float(settings.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR))
    confidence_ceiling = float(settings.get("confidence_ceiling", DEFAULT_CONFIDENCE_CEILING))
    return {
        "credits": round(max(0.0, float(source.get("credits", 0.0) or 0.0)), 4),
        "intensity": intensity,
        "confidence": round(
            _clamp(
                float(source.get("confidence", DEFAULT_CONFIDENCE) or DEFAULT_CONFIDENCE),
                confidence_floor,
                confidence_ceiling,
            ),
            4,
        ),
        "last_period": str(source.get("last_period") or period),
    }


def _normalize_settings(raw: object) -> dict[str, object]:
    source = raw if isinstance(raw, Mapping) else {}
    return {
        "base_monthly_credits": max(
            0.0,
            float(source.get("base_monthly_credits", DEFAULT_BASE_MONTHLY_CREDITS) or DEFAULT_BASE_MONTHLY_CREDITS),
        ),
        "finance_off_multiplier": _clamp(
            float(source.get("finance_off_multiplier", DEFAULT_FINANCE_OFF_MULTIPLIER) or DEFAULT_FINANCE_OFF_MULTIPLIER),
            0.50,
            1.50,
        ),
        "monthly_decay": _clamp(
            float(source.get("monthly_decay", DEFAULT_MONTHLY_DECAY) or DEFAULT_MONTHLY_DECAY),
            0.0,
            0.10,
        ),
        "passive_gain": _clamp(
            float(source.get("passive_gain", DEFAULT_PASSIVE_GAIN) or DEFAULT_PASSIVE_GAIN),
            0.0,
            0.10,
        ),
        "confidence_floor": _clamp(
            float(source.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR) or DEFAULT_CONFIDENCE_FLOOR),
            0.01,
            0.90,
        ),
        "confidence_ceiling": _clamp(
            float(source.get("confidence_ceiling", DEFAULT_CONFIDENCE_CEILING) or DEFAULT_CONFIDENCE_CEILING),
            0.20,
            0.99,
        ),
        "max_banked_credits": _clamp(
            float(source.get("max_banked_credits", DEFAULT_MAX_BANKED_CREDITS) or DEFAULT_MAX_BANKED_CREDITS),
            50.0,
            10_000.0,
        ),
        "auto_spend_cap": _clamp(
            float(source.get("auto_spend_cap", DEFAULT_AUTO_SPEND_CAP) or DEFAULT_AUTO_SPEND_CAP),
            10.0,
            1_000.0,
        ),
    }


def _normalize_intensity(value: object) -> str:
    token = str(value or DEFAULT_INTENSITY).strip().lower()
    if token not in INTENSITY_MULTIPLIERS:
        return DEFAULT_INTENSITY
    return token


def _period_token(current_date: str | None = None) -> str:
    token = str(current_date or "").strip() or str(get_current_sim_date() or "").strip()
    if token:
        parts = token.split("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}"
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _month_delta(old_period: str, new_period: str) -> int:
    try:
        old_year, old_month = [int(part) for part in str(old_period).split("-", 1)]
        new_year, new_month = [int(part) for part in str(new_period).split("-", 1)]
    except Exception:
        return 0
    old_key = (old_year * 12) + old_month
    new_key = (new_year * 12) + new_month
    return max(0, new_key - old_key)


def _normalize_league_id(value: object) -> str:
    token = str(value or "").strip()
    return token


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
    return base / SCOUTING_STATE_FILENAME


def _load_payload(*, data_dir: Path | str | None = None) -> dict[str, object]:
    path = _payload_path(data_dir)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_payload(payload: Mapping[str, object], *, data_dir: Path | str | None = None) -> None:
    path = _payload_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")


def _deterministic_offset(token: str, spread: int) -> int:
    if spread <= 0:
        return 0
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:4], byteorder="big", signed=False)
    span = (spread * 2) + 1
    return (raw % span) - spread


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


__all__ = [
    "TeamScoutingProfile",
    "load_scouting_settings",
    "update_scouting_settings",
    "set_team_scouting_intensity",
    "load_team_scouting_controls",
    "team_scouting_profile",
    "scouting_observed_value",
]
