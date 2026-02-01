from __future__ import annotations

import random
from datetime import date, datetime
import os
from typing import Iterable

from models.pitcher import Pitcher

# Aging adjustments derived from ARR lines 227-262 in pgend_original_converted.txt.
# Values represent annual rating changes for players at a given age.
# Keys map to player attributes: ch, ph, sp, arm, hold_runner, control, endurance, fa.
_AGING_TABLE = {
    18: (18, 5, 1, 1, 2, 5, 1, 2),
    19: (15, 5, 1, 1, 3, 5, 1, 3),
    20: (12, 5, 1, 1, 4, 5, 1, 4),
    21: (10, 5, 1, 1, 5, 5, 1, 5),
    22: (8, 5, 1, 1, 6, 5, 1, 6),
    23: (6, 7, 1, 1, 7, 7, 1, 7),
    24: (4, 9, 1, 1, 6, 9, 1, 6),
    25: (3, 11, 1, 1, 5, 11, 1, 5),
    26: (2, 9, 1, 1, 4, 9, 1, 4),
    27: (1, 7, 1, 1, 3, 7, 1, 3),
    28: (1, 5, 0, 0, 2, 5, 0, 2),
    29: (0, 3, -1, 0, 2, 3, 0, 2),
    30: (0, 2, -2, 0, 1, 2, 0, 1),
    31: (0, 1, -2, 0, 0, 1, 0, 0),
    32: (-1, 1, -3, 0, 0, 1, 0, 0),
    33: (-2, 0, -3, 0, 0, 0, -1, -1),
    34: (-3, -1, -4, 0, 0, 0, -1, -1),
    35: (-4, -2, -4, -1, -1, -1, -1, -2),
    36: (-5, -2, -5, -1, -1, -1, -1, -2),
    37: (-5, -3, -5, -2, -2, -2, -1, -3),
    38: (-6, -3, -6, -2, -2, -2, -1, -3),
    39: (-6, -4, -6, -3, -3, -3, -2, -4),
    40: (-6, -4, -6, -3, -3, -3, -2, -4),
    41: (-6, -5, -6, -4, -4, -4, -2, -5),
    42: (-7, -5, -6, -4, -4, -4, -3, -5),
    43: (-7, -6, -6, -5, -5, -4, -3, -6),
    44: (-7, -6, -6, -5, -5, -4, -4, -7),
    45: (-8, -7, -6, -5, -6, -4, -5, -8),
    46: (-8, -8, -6, -5, -6, -4, -5, -9),
    47: (-8, -8, -8, -5, -7, -5, -6, -10),
    48: (-8, -9, -8, -5, -7, -5, -6, -11),
    49: (-8, -9, -8, -5, -7, -5, -6, -12),
}

_ATTRS = [
    "ch",
    "ph",
    "sp",
    "arm",
    "hold_runner",
    "control",
    "endurance",
    "fa",
]

AGE_ADJUSTMENTS = {
    age: dict(zip(_ATTRS, values)) for age, values in _AGING_TABLE.items()
}

_PITCH_ATTRS = ["fb", "cu", "cb", "sl", "si", "scb", "kn"]


def spring_training_pitch(pitcher: Pitcher) -> None:
    """Boost one pitch by 35% to simulate spring training development.

    According to ARR lines 264-269, each pitcher spends 15% of training
    camp developing a single pitch, increasing that pitch's rating by 35%.
    """

    pitches = [attr for attr in _PITCH_ATTRS if getattr(pitcher, attr, 0) > 0]
    if not pitches:
        return
    pitch = random.choice(pitches)
    current = getattr(pitcher, pitch)
    boosted = int(round(current * 1.35))
    setattr(pitcher, pitch, boosted)


def calculate_age(birthdate: str) -> int:
    """Return age in years given a birthdate ISO string."""

    born = datetime.strptime(birthdate, "%Y-%m-%d").date()
    today = _resolve_sim_date() or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _resolve_sim_date() -> date | None:
    raw = os.getenv("PB_SIM_DATE")
    if raw:
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            pass
    raw_year = os.getenv("PB_SIM_YEAR")
    if raw_year:
        try:
            year = int(str(raw_year).strip())
        except ValueError:
            return None
        return date(year, 7, 1)
    try:
        from utils.sim_date import get_current_sim_date

        sim_date = get_current_sim_date()
        if sim_date:
            return date.fromisoformat(sim_date.strip())
    except Exception:
        pass
    try:
        from playbalance.season_context import SeasonContext

        ctx = SeasonContext.load()
        current = ctx.current if isinstance(ctx.current, dict) else {}
        year = current.get("league_year")
        if year is not None:
            return date(int(year), 7, 1)
    except Exception:
        pass
    return None


def age_player(player) -> None:
    """Apply aging adjustments to ``player`` in place."""

    age = calculate_age(player.birthdate)
    adjustments = AGE_ADJUSTMENTS.get(age)
    if adjustments:
        for attr, change in adjustments.items():
            if hasattr(player, attr):
                value = getattr(player, attr)
                setattr(player, attr, max(0, value + change))
    if isinstance(player, Pitcher):
        spring_training_pitch(player)


def age_players(players: Iterable) -> None:
    """Age all players in ``players`` according to the aging table."""

    for player in players:
        age_player(player)
