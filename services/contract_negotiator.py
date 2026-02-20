"""Utilities for handling contract decisions during the offseason.

The functions in this module provide very small abstractions that help with
common contract related tasks in simulations:

* :func:`find_expiring_contracts` identifies which players need new deals.
* :func:`evaluate_free_agent_bids` picks the winning team for an unsigned
  player based on competing salary offers.

These routines are intentionally lightweight – they do not attempt to model
complex negotiations or arbitration systems but rather serve as building
blocks for a more detailed front office simulation.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Mapping

from models.player import Player


def find_expiring_contracts(
    players: Iterable[Player], current_year: int
) -> List[Player]:
    """Return players whose contracts expire in *current_year*.

    A player is considered to have an expiring contract if they have an
    attribute ``contract_expiration`` equal to ``current_year``.  Players
    lacking the attribute are ignored.
    """

    return [
        player
        for player in players
        if getattr(player, "contract_expiration", -1) == current_year
    ]


def evaluate_free_agent_bids(
    player: Player, bids: Mapping[object, float]
) -> object:
    """Select the winning bid for a free agent.

    Parameters
    ----------
    player:
        The free agent being bid on.
    bids:
        Mapping of team-like keys to salary offers. Keys can be
        :class:`~models.team.Team` objects or team-id strings.

    Returns
    -------
    object
        The key that wins the bidding. The player's ``team_id`` attribute
        is updated to reflect the winning team id.
    """

    if not bids:
        raise ValueError("No bids submitted")

    max_offer = max(bids.values())
    top_teams = [team for team, offer in bids.items() if offer == max_offer]
    winner = random.choice(top_teams)

    winner_team_id = str(getattr(winner, "team_id", winner) or "").strip()
    player.team_id = winner_team_id
    player.salary = max_offer
    return winner
