"""Roster size rules: the single source of truth (owner decision 8, 7.46.0).

MLB's 26-man active roster with at most 13 pitchers; from Sept 1 through the
end of the regular season, 28 active with at most 14 pitchers. The
organisation (active + AAA + LOW; injured lists excluded) holds 51.

This module imports nothing from the project, so dependency-free modules
such as ``services.roster_validation`` can use it. Date- and phase-aware helpers
(``active_roster_cap``, ``active_pitcher_cap``, ``effective_level_caps``)
live in ``utils.roster_loader``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "ACTIVE_ROSTER_SIZE",
    "SEPTEMBER_ROSTER_SIZE",
    "MAX_ACTIVE_PITCHERS",
    "SEPTEMBER_MAX_ACTIVE_PITCHERS",
    "AAA_CAP",
    "LOW_CAP",
    "ORG_LIMIT",
    "ACT_HITTER_TARGET",
    "BASE_LEVEL_CAPS",
    "MIN_ACTIVE_CATCHERS",
    "counts_as_pitcher",
    "is_catcher",
]

ACTIVE_ROSTER_SIZE = 26
SEPTEMBER_ROSTER_SIZE = 28
MAX_ACTIVE_PITCHERS = 13
SEPTEMBER_MAX_ACTIVE_PITCHERS = 14
AAA_CAP = 15
LOW_CAP = 10
# Active + AAA + LOW. Players on the DL/IR do not count. Owner decision:
# 51 (26 + 15 + 10) so the move to 26 forces no cuts.
ORG_LIMIT = ACTIVE_ROSTER_SIZE + AAA_CAP + LOW_CAP
# Position players a full active roster carries (26 - 13).
ACT_HITTER_TARGET = ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS

BASE_LEVEL_CAPS = {"act": ACTIVE_ROSTER_SIZE, "aaa": AAA_CAP, "low": LOW_CAP}
# Catchers a CPU club carries on the active roster (Release 3, owner
# decision 10). Owner teams with fewer get a non-blocking warning only.
MIN_ACTIVE_CATCHERS = 2

_TRUE = {"1", "true", "yes", "t", "y"}
_PITCHER_POSITIONS = {"P", "SP", "RP"}


def _field(player: Any, name: str) -> Any:
    if isinstance(player, Mapping):
        return player.get(name)
    return getattr(player, name, None)


def counts_as_pitcher(player: Any) -> bool:
    """True when ``player`` counts toward the active-roster pitcher limit.

    The ``is_pitcher`` flag, or a primary position of P/SP/RP. Works on a
    player object or a mapping (a players.csv row). Deliberately ignores the
    stored ``role`` column (stale "RP" in older leagues) and the endurance
    guess in ``get_role``, which can reclassify a player over time. There is
    no two-way exemption: the data has no two-way designation.
    """

    if player is None:
        return False
    flag = _field(player, "is_pitcher")
    if isinstance(flag, bool):
        if flag:
            return True
    elif flag is not None and str(flag).strip().lower() in _TRUE:
        return True
    primary = str(_field(player, "primary_position") or "").strip().upper()
    return primary in _PITCHER_POSITIONS


def _position_tokens(value: Any) -> list[str]:
    """Positions in an ``other_positions`` value, upper-cased.

    Accepts a list, a ``|``/``,``/``/``-separated string or a Python list
    literal (``"['C', '1B']"``), as older players.csv rows hold.
    """

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip().strip("[]")
        for sep in ("|", "/"):
            text = text.replace(sep, ",")
        items = text.split(",")
    else:
        try:
            items = list(value)
        except TypeError:
            items = [value]
    out: list[str] = []
    for item in items:
        token = str(item or "").strip().strip("'\"").strip().upper()
        if token:
            out.append(token)
    return out


def is_catcher(player: Any) -> bool:
    """True when ``player`` can catch: a position player whose primary
    position is C or who lists C among ``other_positions``.

    The one catcher predicate (Release 3): CPU roster upkeep, auto-assign,
    the lineup auto-fill and the engine's defence fallback all use it, so a
    utility player who lists C counts the same everywhere. Pitchers never
    count.
    """

    if player is None or counts_as_pitcher(player):
        return False
    primary = str(_field(player, "primary_position") or "").strip().upper()
    if primary == "C":
        return True
    return "C" in _position_tokens(_field(player, "other_positions"))
