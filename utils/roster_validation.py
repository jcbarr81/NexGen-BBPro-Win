from __future__ import annotations

"""Roster validation helpers.

Functions in this module check whether an Active roster can field a legal
defense by verifying that at least one eligible player exists for each
defensive position.
"""

from typing import Iterable, Mapping, Sequence, Set

from models.base_player import BasePlayer
from models.roster import Roster


# Positions that must be represented by at least one player
REQUIRED_DEF_POSITIONS: Sequence[str] = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")


def _eligible_positions(player: BasePlayer) -> Set[str]:
    primary = str(getattr(player, "primary_position", "")).upper()
    others = getattr(player, "other_positions", []) or []
    positions: Set[str] = set()
    if primary:
        positions.add(primary)
    for pos in others:
        if pos:
            positions.add(str(pos).upper())
    # Exclude pitchers
    positions.discard("P")
    # A CF covers LF and RF, an RF covers LF (utils.position_coverage).
    from utils.position_coverage import with_implied

    return with_implied(positions)


def missing_positions(roster: Roster, players_by_id: Mapping[str, BasePlayer]) -> list[str]:
    """Return list of defensive positions missing on the Active roster.

    A position is considered covered if any non-pitcher on ``roster.act`` has
    that position listed as their primary or in ``other_positions``.
    """

    covered: Set[str] = set()
    for pid in roster.act:
        player = players_by_id.get(pid)
        if not player:
            continue
        covered |= _eligible_positions(player)
    return [pos for pos in REQUIRED_DEF_POSITIONS if pos not in covered]


__all__ = ["REQUIRED_DEF_POSITIONS", "missing_positions"]

