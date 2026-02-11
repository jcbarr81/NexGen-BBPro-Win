"""Persistence helpers for hitter/pitcher training focus allocations."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict, Mapping, MutableMapping, Tuple

from playbalance.player_development import TrainingWeights
from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "TrainingSettings",
    "DEFAULT_HITTER_ALLOCATIONS",
    "DEFAULT_PITCHER_ALLOCATIONS",
    "load_training_settings",
    "save_training_settings",
    "get_training_weights",
    "set_player_training_weights",
    "clear_player_training_weights",
    "set_team_training_weights",
    "clear_team_training_weights",
    "update_league_training_defaults",
    "MIN_PERCENT",
    "HITTER_TRACKS",
    "PITCHER_TRACKS",
]

VERSION = 2
SETTINGS_PATH = get_data_dir() / "training_settings.json"
MIN_PERCENT = 5

HITTER_TRACKS: Tuple[str, ...] = ("contact", "power", "speed", "discipline", "defense")
PITCHER_TRACKS: Tuple[str, ...] = (
    "command",
    "movement",
    "stamina",
    "velocity",
    "hold",
    "pitch_lab",
)

DEFAULT_HITTER_ALLOCATIONS: Dict[str, int] = {
    "contact": 30,
    "power": 25,
    "speed": 15,
    "discipline": 15,
    "defense": 15,
}

DEFAULT_PITCHER_ALLOCATIONS: Dict[str, int] = {
    "command": 25,
    "movement": 20,
    "stamina": 20,
    "velocity": 20,
    "hold": 5,
    "pitch_lab": 10,
}


@dataclass
class TrainingSettings:
    league_id: str
    defaults: TrainingWeights
    team_overrides: Dict[str, TrainingWeights] = field(default_factory=dict)
    player_overrides: Dict[str, TrainingWeights] = field(default_factory=dict)

    def for_team(self, team_id: str | None) -> TrainingWeights:
        if team_id and team_id in self.team_overrides:
            return self.team_overrides[team_id]
        return self.defaults

    def for_player(
        self,
        player_id: str | None,
        team_id: str | None = None,
    ) -> TrainingWeights:
        if player_id:
            pid = str(player_id)
            if pid in self.player_overrides:
                return self.player_overrides[pid]
        return self.for_team(team_id)


def load_training_settings() -> TrainingSettings:
    """Return training allocations for the active league."""

    payload = _load_payload()
    league_id = _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    data = leagues.get(league_id, {})

    defaults = _coerce_weights(
        data.get("defaults", {}),
        fallback_hitters=DEFAULT_HITTER_ALLOCATIONS,
        fallback_pitchers=DEFAULT_PITCHER_ALLOCATIONS,
        strict=False,
    )
    overrides: Dict[str, TrainingWeights] = {}
    team_block = data.get("teams", {})
    if isinstance(team_block, Mapping):
        for key, value in team_block.items():
            weights = _coerce_weights(
                value,
                fallback_hitters=defaults.hitters,
                fallback_pitchers=defaults.pitchers,
                strict=False,
            )
            overrides[str(key)] = weights

    players: Dict[str, TrainingWeights] = {}
    player_block = data.get("players", {})
    if isinstance(player_block, Mapping):
        for key, value in player_block.items():
            weights = _coerce_weights(
                value,
                fallback_hitters=defaults.hitters,
                fallback_pitchers=defaults.pitchers,
                strict=False,
            )
            players[str(key)] = weights

    return TrainingSettings(
        league_id=league_id,
        defaults=defaults,
        team_overrides=overrides,
        player_overrides=players,
    )


def save_training_settings(settings: TrainingSettings) -> None:
    """Persist ``settings`` to disk."""

    payload = _load_payload()
    leagues = payload.setdefault("leagues", {})
    leagues[settings.league_id] = {
        "defaults": _weights_to_dict(settings.defaults),
        "teams": {team_id: _weights_to_dict(weights) for team_id, weights in settings.team_overrides.items()},
        "players": {
            player_id: _weights_to_dict(weights)
            for player_id, weights in settings.player_overrides.items()
        },
    }
    payload["version"] = VERSION
    _write_payload(payload)


def get_training_weights(team_id: str | None) -> TrainingWeights:
    """Convenience helper returning weights for ``team_id`` (or league defaults)."""

    settings = load_training_settings()
    return settings.for_team(team_id)


def set_player_training_weights(
    player_id: str,
    hitters: Mapping[str, float],
    pitchers: Mapping[str, float],
) -> TrainingWeights:
    """Persist a player-specific override; raise ``ValueError`` on invalid data."""

    if not player_id:
        raise ValueError("player_id is required")
    settings = load_training_settings()
    weights = _coerce_weights(
        {"hitters": hitters, "pitchers": pitchers},
        fallback_hitters=settings.defaults.hitters,
        fallback_pitchers=settings.defaults.pitchers,
        strict=True,
    )
    settings.player_overrides[str(player_id)] = weights
    save_training_settings(settings)
    return weights


def clear_player_training_weights(player_id: str) -> None:
    """Remove the override for ``player_id``."""

    settings = load_training_settings()
    pid = str(player_id)
    if pid in settings.player_overrides:
        del settings.player_overrides[pid]
        save_training_settings(settings)


def set_team_training_weights(
    team_id: str,
    hitters: Mapping[str, float],
    pitchers: Mapping[str, float],
) -> TrainingWeights:
    """Persist a team-specific override; raise ``ValueError`` on invalid data."""

    if not team_id:
        raise ValueError("team_id is required")
    settings = load_training_settings()
    weights = _coerce_weights(
        {"hitters": hitters, "pitchers": pitchers},
        fallback_hitters=settings.defaults.hitters,
        fallback_pitchers=settings.defaults.pitchers,
        strict=True,
    )
    settings.team_overrides[team_id] = weights
    save_training_settings(settings)
    return weights


def clear_team_training_weights(team_id: str) -> None:
    """Remove the override for ``team_id``."""

    settings = load_training_settings()
    if team_id in settings.team_overrides:
        del settings.team_overrides[team_id]
        save_training_settings(settings)


def update_league_training_defaults(
    hitters: Mapping[str, float],
    pitchers: Mapping[str, float],
) -> TrainingWeights:
    """Replace the league-wide defaults and persist them."""

    settings = load_training_settings()
    weights = _coerce_weights(
        {"hitters": hitters, "pitchers": pitchers},
        fallback_hitters=settings.defaults.hitters,
        fallback_pitchers=settings.defaults.pitchers,
        strict=True,
    )
    settings.defaults = weights
    save_training_settings(settings)
    return weights


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _coerce_weights(
    data: Mapping[str, object],
    *,
    fallback_hitters: Mapping[str, float],
    fallback_pitchers: Mapping[str, float],
    strict: bool,
) -> TrainingWeights:
    hitters = _prepare_allocations(
        data.get("hitters"),
        required=HITTER_TRACKS,
        fallback=fallback_hitters,
        strict=strict,
    )
    pitchers = _prepare_allocations(
        data.get("pitchers"),
        required=PITCHER_TRACKS,
        fallback=fallback_pitchers,
        strict=strict,
    )
    return TrainingWeights(hitters=hitters, pitchers=pitchers)


def _prepare_allocations(
    raw: object,
    *,
    required: Tuple[str, ...],
    fallback: Mapping[str, float],
    strict: bool,
) -> Dict[str, int]:
    if not isinstance(raw, Mapping):
        if strict:
            raise ValueError("allocations must be a mapping")
        return {key: int(fallback[key]) for key in required}

    allocations: Dict[str, int] = {}
    for key in required:
        if key not in raw:
            if strict:
                raise ValueError(f"missing allocation for {key}")
            allocations[key] = int(fallback[key])
            continue
        try:
            value = int(round(float(raw[key])))
        except (TypeError, ValueError):
            if strict:
                raise ValueError(f"invalid allocation for {key}")
            value = int(fallback[key])
        allocations[key] = value

    total = sum(allocations.values())
    if total != 100:
        if strict:
            raise ValueError(f"allocations must total 100 (got {total})")
        return {key: int(fallback[key]) for key in required}

    for key, value in allocations.items():
        if value < MIN_PERCENT:
            if strict:
                raise ValueError(
                    f"{key} allocation must be at least {MIN_PERCENT} (got {value})"
                )
            return {k: int(fallback[k]) for k in required}

    return allocations


def _weights_to_dict(weights: TrainingWeights) -> Dict[str, Dict[str, int]]:
    return {
        "hitters": {key: int(value) for key, value in weights.hitters.items()},
        "pitchers": {key: int(value) for key, value in weights.pitchers.items()},
    }
