from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from models.base_player import BasePlayer
from playbalance.aging import age_player, calculate_age, get_sim_date
from utils.rating_scale import LEGACY_RATING_SCALE, rating_scale_of

RETIREMENT_AGE = 40


def age_and_retire(
    players: Dict[str, BasePlayer],
    *,
    development_multiplier_by_player: Mapping[str, float] | None = None,
    intensity_by_player: Mapping[str, float] | None = None,
    weights_by_player: Mapping[str, Any] | None = None,
    season: Optional[int] = None,
    develop_scale_2: bool = True,
) -> List[BasePlayer]:
    """Age ``players`` and remove those meeting retirement criteria.

    Parameters
    ----------
    players:
        Mapping of player ids to :class:`~models.base_player.BasePlayer` objects.
        Players are aged in place and any who meet the retirement threshold are
        removed from the mapping and returned.

    A player on rating scale 1 is aged by the aging table, as before. A
    player on rating scale 2 develops instead (``playbalance.development``):
    his club's development multiplier, training intensity and training
    weights (``weights_by_player``) shape it, and ``season`` (default: the
    sim date's year) seeds it. A caller whose season rollover already
    develops them (``LeagueRolloverService``) passes ``develop_scale_2=False``
    so they develop once a year, not twice.
    """

    retired: List[BasePlayer] = []
    multipliers = (
        development_multiplier_by_player
        if isinstance(development_multiplier_by_player, Mapping)
        else {}
    )
    for pid, player in list(players.items()):
        multiplier = float(multipliers.get(str(pid), 1.0))
        if rating_scale_of(player) == LEGACY_RATING_SCALE:
            age_player(
                player,
                development_multiplier=multiplier,
            )
        elif develop_scale_2:
            _develop(
                player,
                development=multiplier,
                intensity=float((intensity_by_player or {}).get(str(pid), 1.0)),
                weights=(weights_by_player or {}).get(str(pid)),
                season=season,
            )
        if calculate_age(player.birthdate) >= RETIREMENT_AGE:
            retired.append(players.pop(pid))
    return retired


def _develop(player, *, development, intensity, weights, season) -> None:
    from playbalance.development import develop_player

    if season is None:
        sim_date = get_sim_date()
        season = sim_date.year if sim_date is not None else None
    develop_player(
        player,
        age=calculate_age(player.birthdate),
        season=season,
        development=development,
        intensity=intensity,
        weights=weights,
    )
