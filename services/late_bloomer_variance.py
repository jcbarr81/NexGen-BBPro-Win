"""Late-bloomer development variance tied to scouting uncertainty."""

from __future__ import annotations

from datetime import date
import hashlib
from typing import Dict, Mapping

from playbalance.aging import calculate_age
from services.finance_budget_effects import scouting_display_profile_for_team
from utils.sim_date import get_current_sim_date

BASE_VARIANCE = 0.12
NEGATIVE_DAMPING = 0.65
MAX_VARIANCE = 0.18
MIN_DEVELOPMENT_MULTIPLIER = 0.70
MAX_DEVELOPMENT_MULTIPLIER = 1.45

__all__ = [
    "BASE_VARIANCE",
    "NEGATIVE_DAMPING",
    "MAX_VARIANCE",
    "apply_late_bloomer_variance",
    "late_bloomer_adjustment",
]


def late_bloomer_adjustment(
    *,
    player_id: str,
    team_id: str,
    age: int,
    uncertainty_score: float,
    season_token: str,
) -> float:
    """Return additive development adjustment in ``[-MAX_VARIANCE, MAX_VARIANCE]``."""

    uncertainty = _clamp(float(uncertainty_score), 0.0, 1.0)
    if uncertainty <= 0.0:
        return 0.0
    age_factor = _age_factor(int(age))
    if age_factor <= 0.0:
        return 0.0

    base_roll = (_hash_unit(f"{season_token}|{team_id}|{player_id}|late_bloomer") * 2.0) - 1.0
    if base_roll >= 0.0:
        directional = base_roll
    else:
        directional = base_roll * NEGATIVE_DAMPING

    adjustment = directional * BASE_VARIANCE * uncertainty * age_factor

    # Reward high positive outliers in late-prime ages to create "late bloomers".
    if age >= 26 and base_roll > 0.40:
        bonus = (base_roll - 0.40) * 0.08 * uncertainty * age_factor
        adjustment += bonus

    return _clamp(adjustment, -MAX_VARIANCE, MAX_VARIANCE)


def apply_late_bloomer_variance(
    *,
    players_by_id: Mapping[str, object],
    player_team_lookup: Mapping[str, str | None],
    base_multipliers: Mapping[str, float],
    data_dir=None,
    league_id: str | None = None,
    season_token: str | None = None,
) -> Dict[str, float]:
    """Apply scouting-uncertainty late-bloomer variance to development multipliers."""

    resolved_token = season_token or _season_token()
    result: Dict[str, float] = {}
    team_uncertainty: Dict[str, float] = {}

    for raw_player_id, raw_base in base_multipliers.items():
        player_id = str(raw_player_id or "").strip()
        if not player_id:
            continue
        base = _clamp(float(raw_base), MIN_DEVELOPMENT_MULTIPLIER, MAX_DEVELOPMENT_MULTIPLIER)
        team_id = str(player_team_lookup.get(player_id) or "").strip().upper()
        if not team_id:
            result[player_id] = base
            continue

        uncertainty = team_uncertainty.get(team_id)
        if uncertainty is None:
            profile = scouting_display_profile_for_team(
                team_id,
                data_dir=data_dir,
                league_id=league_id,
            )
            uncertainty = _clamp(float(profile.max_rating_error) / 9.0, 0.0, 1.0)
            team_uncertainty[team_id] = uncertainty
        if uncertainty <= 0.0:
            result[player_id] = base
            continue

        player = players_by_id.get(player_id)
        age = _player_age(player)
        adjustment = late_bloomer_adjustment(
            player_id=player_id,
            team_id=team_id,
            age=age,
            uncertainty_score=uncertainty,
            season_token=resolved_token,
        )
        adjusted = base * (1.0 + adjustment)
        result[player_id] = _clamp(
            adjusted,
            MIN_DEVELOPMENT_MULTIPLIER,
            MAX_DEVELOPMENT_MULTIPLIER,
        )

    return result


def _player_age(player: object) -> int:
    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if not birthdate:
        return 26
    try:
        return int(calculate_age(birthdate))
    except Exception:
        return 26


def _age_factor(age: int) -> float:
    if age <= 20:
        return 0.45
    if age <= 24:
        return 0.85
    if age <= 29:
        return 1.00
    if age <= 33:
        return 0.70
    if age <= 37:
        return 0.45
    return 0.25


def _season_token() -> str:
    raw_date = str(get_current_sim_date() or "").strip()
    if raw_date:
        parts = raw_date.split("-")
        if len(parts) >= 1 and parts[0].isdigit():
            return f"season-{int(parts[0]):04d}"
    return f"season-{date.today().year:04d}"


def _hash_unit(token: str) -> float:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value / float((1 << 64) - 1)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))
