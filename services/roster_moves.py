from __future__ import annotations

"""Helpers for common roster moves (cuts, assignments)."""

from typing import Tuple

from models.roster import Roster
from services.transaction_log import record_transaction
from utils.roster_loader import load_roster, save_roster



VALID_LEVELS = {"act", "aaa", "low", "dl", "ir"}


def move_player_between_rosters(player_id: str, roster: Roster, from_level: str, to_level: str) -> None:
    """Move *player_id* from one roster level to another."""

    src_level = str(from_level).lower()
    dst_level = str(to_level).lower()
    if src_level not in VALID_LEVELS:
        raise ValueError(f"Unknown source level: {from_level}")
    if dst_level not in VALID_LEVELS:
        raise ValueError(f"Unknown destination level: {to_level}")
    if src_level == dst_level:
        return

    source = getattr(roster, src_level, None)
    target = getattr(roster, dst_level, None)
    if source is None or target is None:
        raise ValueError("Invalid roster level provided.")
    if player_id not in source:
        raise ValueError(f"Player {player_id} not found in {from_level} roster.")

    source.remove(player_id)
    target.append(player_id)

def cut_player(team_id: str, player_id: str, roster: Roster | None = None) -> Tuple[Roster, str]:
    """Remove *player_id* from *team_id*'s roster and log the transaction.

    Returns a tuple of (mutated_roster, removed_level).
    """

    roster_obj = roster or load_roster(team_id)
    removed_level: str | None = None
    for level in ("act", "aaa", "low", "dl", "ir"):
        group = getattr(roster_obj, level, [])
        if player_id in group:
            group.remove(player_id)
            removed_level = level
            break
    if removed_level is None:
        raise ValueError(f"Player {player_id} not found on roster {team_id}.")

    save_roster(team_id, roster_obj)

    try:
        record_transaction(
            action="cut",
            team_id=team_id,
            player_id=player_id,
            from_level=removed_level.upper(),
            to_level="FA",
            details="Released to free agency",
        )
    except Exception:
        pass

    return roster_obj, removed_level


__all__ = ["move_player_between_rosters", "cut_player"]
