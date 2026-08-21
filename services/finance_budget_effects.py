"""Budget-to-gameplay effect helpers for finance-enabled leagues."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Mapping

from services.finance_settings import LEVEL_OFF, load_financial_settings
from services.owner_finance_engine import project_monthly_owner_finance
from services.scouting_service import (
    TeamScoutingProfile,
    scouting_observed_value,
    team_scouting_profile,
)
from utils.path_utils import get_data_dir

__all__ = [
    "TeamBudgetEffects",
    "ScoutingDisplayProfile",
    "FacilitiesInjuryEffect",
    "list_team_budget_effects",
    "training_camp_multiplier_for_team",
    "training_camp_multiplier_by_player",
    "development_multiplier_by_player",
    "facilities_injury_effects_by_team",
    "scouting_display_profile_for_team",
    "scouting_display_value",
]

_BUDGET_KEYS: tuple[str, ...] = ("training", "scouting", "development", "facilities")


@dataclass(frozen=True)
class TeamBudgetEffects:
    team_id: str
    training_multiplier: float
    scouting_multiplier: float
    development_multiplier: float
    facilities_multiplier: float
    training_camp_multiplier: float


@dataclass(frozen=True)
class ScoutingDisplayProfile:
    team_id: str
    scouting_multiplier: float
    confidence_score: int
    confidence_label: str
    max_rating_error: int


@dataclass(frozen=True)
class FacilitiesInjuryEffect:
    """Facilities budget → injury outcomes (applied post-game, not in the sim
    engine, so injury FREQUENCY / calibration is untouched).

    ``recovery_days_factor`` scales DL/injury durations (well-funded < 1.0 =
    faster recovery; underfunded > 1.0 = slower). ``void_chance`` is the chance a
    would-be DL stint is downgraded to a one-game day-to-day scare (prevention);
    it's only positive when facilities are funded above target. Both collapse to
    a no-op (1.0 / 0.0) when finance/owner_budgets are off, so calibration runs
    (neutral budgets) see zero change.
    """

    team_id: str
    recovery_days_factor: float
    void_chance: float


def list_team_budget_effects(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, TeamBudgetEffects]:
    """Return per-team budget effect multipliers."""

    resolved_data_dir = _resolve_data_dir(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    snapshots = project_monthly_owner_finance(
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    budgets_by_team = _load_team_budgets(resolved_data_dir)

    team_ids = set(snapshots.keys()) | set(budgets_by_team.keys())
    effects: Dict[str, TeamBudgetEffects] = {}
    for team_id in sorted(team_ids):
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            continue
        if (not settings.enabled) or settings.module_level("owner_budgets") == LEVEL_OFF:
            effects[clean_team_id] = TeamBudgetEffects(
                team_id=clean_team_id,
                training_multiplier=1.0,
                scouting_multiplier=1.0,
                development_multiplier=1.0,
                facilities_multiplier=1.0,
                training_camp_multiplier=1.0,
            )
            continue
        snapshot = snapshots.get(clean_team_id)
        target_budgets = (
            dict(getattr(snapshot, "projected_budgets", {}))
            if snapshot is not None
            else {}
        )
        current_budgets = budgets_by_team.get(clean_team_id, {})
        training = _budget_multiplier(
            current_budgets.get("training", 0),
            target_budgets.get("training", 0),
        )
        scouting = _budget_multiplier(
            current_budgets.get("scouting", 0),
            target_budgets.get("scouting", 0),
        )
        development = _budget_multiplier(
            current_budgets.get("development", 0),
            target_budgets.get("development", 0),
        )
        facilities = _budget_multiplier(
            current_budgets.get("facilities", 0),
            target_budgets.get("facilities", 0),
        )
        # Training camp intensity blends training + development only. Facilities
        # is no longer folded in here — it now owns injury outcomes (see
        # facilities_injury_effects_by_team) so each budget line has one clear
        # identity for the Finance UI.
        camp = (training * 0.55) + (development * 0.45)
        effects[clean_team_id] = TeamBudgetEffects(
            team_id=clean_team_id,
            training_multiplier=round(training, 4),
            scouting_multiplier=round(scouting, 4),
            development_multiplier=round(development, 4),
            facilities_multiplier=round(facilities, 4),
            training_camp_multiplier=round(_clamp(camp, 0.85, 1.15), 4),
        )
    return effects


def training_camp_multiplier_for_team(
    team_id: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> float:
    """Return the training-camp intensity multiplier for one team."""

    clean_team_id = str(team_id or "").strip()
    if not clean_team_id:
        return 1.0
    effects = list_team_budget_effects(data_dir=data_dir, league_id=league_id)
    profile = effects.get(clean_team_id)
    if profile is None:
        return 1.0
    return float(profile.training_camp_multiplier)


def training_camp_multiplier_by_player(
    player_team_lookup: Mapping[str, str | None],
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, float]:
    """Map player ids to training-camp multipliers based on team budgets."""

    effects = list_team_budget_effects(data_dir=data_dir, league_id=league_id)
    out: Dict[str, float] = {}
    for player_id, team_id in player_team_lookup.items():
        pid = str(player_id or "").strip()
        if not pid:
            continue
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            out[pid] = 1.0
            continue
        profile = effects.get(clean_team_id)
        out[pid] = float(profile.training_camp_multiplier) if profile else 1.0
    return out


def development_multiplier_by_player(
    player_team_lookup: Mapping[str, str | None],
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, float]:
    """Map player ids to development multipliers based on team budgets."""

    effects = list_team_budget_effects(data_dir=data_dir, league_id=league_id)
    out: Dict[str, float] = {}
    for player_id, team_id in player_team_lookup.items():
        pid = str(player_id or "").strip()
        if not pid:
            continue
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            out[pid] = 1.0
            continue
        profile = effects.get(clean_team_id)
        out[pid] = float(profile.development_multiplier) if profile else 1.0
    return out


def facilities_injury_effects_by_team(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> Dict[str, "FacilitiesInjuryEffect"]:
    """Return per-team facilities → injury effects (recovery + prevention).

    Derived from each team's facilities_multiplier (0.85–1.15, 1.0 neutral):
    - recovery_days_factor = clamp(2 - m, 0.85, 1.20): m=1.15 → 0.85 (≈15%
      faster), m=0.85 → 1.15 (≈15% slower), m=1.0 → 1.0.
    - void_chance = clamp((m - 1) * 2, 0, 0.30): only well-funded facilities
      (m>1) get a chance to prevent a DL stint; at/below target it's 0.
    """

    effects = list_team_budget_effects(data_dir=data_dir, league_id=league_id)
    out: Dict[str, FacilitiesInjuryEffect] = {}
    for team_id, eff in effects.items():
        m = float(eff.facilities_multiplier)
        out[team_id] = FacilitiesInjuryEffect(
            team_id=team_id,
            recovery_days_factor=round(_clamp(2.0 - m, 0.85, 1.20), 4),
            void_chance=round(_clamp((m - 1.0) * 2.0, 0.0, 0.30), 4),
        )
    return out


def scouting_display_profile_for_team(
    team_id: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> ScoutingDisplayProfile:
    """Return scouting-confidence metadata for rating uncertainty display."""

    clean_team_id = str(team_id or "").strip().upper()
    resolved_data_dir = _resolve_data_dir(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    finance_enabled = bool(settings.enabled) and settings.module_level("owner_budgets") != LEVEL_OFF
    if finance_enabled:
        budget_profile = list_team_budget_effects(
            data_dir=resolved_data_dir,
            league_id=league_id,
        ).get(clean_team_id)
        scouting_multiplier = float(budget_profile.scouting_multiplier) if budget_profile is not None else 1.0
    else:
        scouting_multiplier = 1.0
    profile = team_scouting_profile(
        clean_team_id,
        finance_enabled=finance_enabled,
        finance_multiplier=scouting_multiplier,
        data_dir=resolved_data_dir,
        league_id=league_id,
    )
    return ScoutingDisplayProfile(
        team_id=clean_team_id,
        scouting_multiplier=round(float(profile.scouting_multiplier), 4),
        confidence_score=max(0, min(100, int(profile.confidence_score))),
        confidence_label=str(profile.confidence_label or "Low"),
        max_rating_error=max(0, int(profile.max_rating_error)),
    )


def scouting_display_value(
    value: object,
    *,
    player_id: str | None,
    metric_key: str,
    team_id: str | None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    minimum: int = 0,
    maximum: int = 99,
) -> object:
    """Return deterministic scouting-adjusted display value."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value

    profile = scouting_display_profile_for_team(
        team_id,
        data_dir=data_dir,
        league_id=league_id,
    )
    return scouting_observed_value(
        numeric,
        team_profile=TeamScoutingProfile(
            enabled=profile.max_rating_error > 0,
            team_id=str(profile.team_id or ""),
            scouting_multiplier=float(profile.scouting_multiplier),
            confidence_score=int(profile.confidence_score),
            confidence_label=str(profile.confidence_label or ""),
            max_rating_error=int(profile.max_rating_error),
        ),
        player_id=player_id,
        metric_key=metric_key,
        team_id=team_id,
        minimum=minimum,
        maximum=maximum,
    )


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    if data_dir is None:
        return get_data_dir()
    return Path(data_dir)


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, float(value)))


def _budget_multiplier(current: object, target: object) -> float:
    current_value = max(0, _safe_int(current))
    target_value = max(0, _safe_int(target))
    if target_value <= 0:
        if current_value <= 0:
            return 1.0
        return 1.05
    ratio = current_value / float(target_value)
    if ratio <= 1.0:
        return _clamp(0.85 + (0.15 * ratio), 0.85, 1.0)
    return _clamp(1.0 + (0.10 * (ratio - 1.0)), 1.0, 1.15)


def _load_team_budgets(data_dir: Path) -> Dict[str, Dict[str, int]]:
    path = data_dir / "team_financials.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    teams = payload.get("teams")
    if not isinstance(teams, Mapping):
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for team_id, raw_entry in teams.items():
        clean_team_id = str(team_id or "").strip()
        if not clean_team_id:
            continue
        entry = raw_entry if isinstance(raw_entry, Mapping) else {}
        raw_budgets = entry.get("budgets")
        budgets = raw_budgets if isinstance(raw_budgets, Mapping) else {}
        out[clean_team_id] = {
            key: max(0, _safe_int(budgets.get(key, 0)))
            for key in _BUDGET_KEYS
        }
    return out
