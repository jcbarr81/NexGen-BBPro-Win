from __future__ import annotations

from typing import Dict, List, Mapping

from models.base_player import BasePlayer
from playbalance.aging import age_player, calculate_age

RETIREMENT_AGE = 40


def age_and_retire(
    players: Dict[str, BasePlayer],
    *,
    development_multiplier_by_player: Mapping[str, float] | None = None,
) -> List[BasePlayer]:
    """Age ``players`` and remove those meeting retirement criteria.

    Parameters
    ----------
    players:
        Mapping of player ids to :class:`~models.base_player.BasePlayer` objects.
        Players are aged in place and any who meet the retirement threshold are
        removed from the mapping and returned.
    """

    retired: List[BasePlayer] = []
    multipliers = (
        development_multiplier_by_player
        if isinstance(development_multiplier_by_player, Mapping)
        else {}
    )
    for pid, player in list(players.items()):
        multiplier = float(multipliers.get(str(pid), 1.0))
        age_player(
            player,
            development_multiplier=multiplier,
        )
        if calculate_age(player.birthdate) >= RETIREMENT_AGE:
            retired.append(players.pop(pid))
    return retired
