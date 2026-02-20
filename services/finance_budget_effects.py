"""Budget-to-gameplay effect helpers for finance-enabled leagues."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Dict, Mapping

from services.finance_settings import LEVEL_OFF, load_financial_settings
from services.owner_finance_engine import project_monthly_owner_finance
from utils.path_utils import get_data_dir

__all__ = [
    "TeamBudgetEffects",
    "ScoutingDisplayProfile",
    "list_team_budget_effects",
    "training_camp_multiplier_for_team",
    "training_camp_multiplier_by_player",
    "development_multiplier_by_player",
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
        camp = (
            (training * 0.45)
            + (development * 0.35)
            + (facilities * 0.20)
        )
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


def scouting_display_profile_for_team(
    team_id: str | None,
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
) -> ScoutingDisplayProfile:
    """Return scouting-confidence metadata for display-only rating uncertainty."""

    clean_team_id = str(team_id or "").strip().upper()
    resolved_data_dir = _resolve_data_dir(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    if (not settings.enabled) or settings.module_level("owner_budgets") == LEVEL_OFF:
        return ScoutingDisplayProfile(
            team_id=clean_team_id,
            scouting_multiplier=1.0,
            confidence_score=100,
            confidence_label="Exact",
            max_rating_error=0,
        )

    profile = list_team_budget_effects(
        data_dir=resolved_data_dir,
        league_id=league_id,
    ).get(clean_team_id)
    scouting_multiplier = (
        float(profile.scouting_multiplier) if profile is not None else 1.0
    )
    normalized = _clamp((scouting_multiplier - 0.85) / 0.30, 0.0, 1.0)
    confidence = int(round(normalized * 100))
    if confidence >= 85:
        label = "Elite"
    elif confidence >= 65:
        label = "High"
    elif confidence >= 35:
        label = "Moderate"
    else:
        label = "Low"

    raw_error = 1.0 + (((1.15 - scouting_multiplier) / 0.30) * 3.0)
    max_rating_error = int(round(_clamp(raw_error, 1.0, 4.0)))
    return ScoutingDisplayProfile(
        team_id=clean_team_id,
        scouting_multiplier=round(scouting_multiplier, 4),
        confidence_score=max(0, min(100, confidence)),
        confidence_label=label,
        max_rating_error=max_rating_error,
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
    """Return a deterministic scouting-adjusted display value."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value

    profile = scouting_display_profile_for_team(
        team_id,
        data_dir=data_dir,
        league_id=league_id,
    )
    if profile.max_rating_error <= 0:
        rounded = int(round(numeric))
        return int(_clamp(float(rounded), float(minimum), float(maximum)))

    clean_player_id = str(player_id or "").strip() or "unknown"
    clean_team_id = str(team_id or "").strip().upper() or "NA"
    clean_key = str(metric_key or "").strip().upper() or "RATING"
    spread = profile.max_rating_error
    offset = _deterministic_offset(
        f"{clean_player_id}|{clean_team_id}|{clean_key}",
        spread,
    )
    adjusted = int(round(numeric + offset))
    return int(_clamp(float(adjusted), float(minimum), float(maximum)))


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


def _deterministic_offset(token: str, spread: int) -> int:
    if spread <= 0:
        return 0
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:4], byteorder="big", signed=False)
    span = (spread * 2) + 1
    return (raw % span) - spread


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
