"""Pitching-staff slot names and the one relief-role normaliser.

A club's ``{team}_pitching.csv`` labels each arm with a staff slot. Eleven
slots are required (five starters, the long man, three middle relievers, the
setup man and the closer); MR4 and MR5 are optional homes for a 12th and 13th
arm. Existing staff files are never migrated to them.

The engine only needs to know what *kind* of arm a slot is.
:func:`canonical_relief_role` collapses every label onto the handful of roles
the usage rules understand, so ``MR4``, ``RP``, an empty cell and a stale
``"P"`` all pitch exactly like ``MR``.
"""

from __future__ import annotations

import re
from typing import Any, Tuple

REQUIRED_PITCHING_ROLES: Tuple[str, ...] = (
    "SP1",
    "SP2",
    "SP3",
    "SP4",
    "SP5",
    "LR",
    "MR1",
    "MR2",
    "MR3",
    "SU",
    "CL",
)

OPTIONAL_PITCHING_ROLES: Tuple[str, ...] = ("MR4", "MR5")

# Display/edit order: the required eleven, then the optional slots.
STAFF_ROLES: Tuple[str, ...] = REQUIRED_PITCHING_ROLES + OPTIONAL_PITCHING_ROLES

# Relief roles the usage rules treat on their own terms; every other relief
# label is a middle reliever.
_KEPT_RELIEF_ROLES = frozenset({"CL", "SU", "LR", "MR"})
_STARTER_PATTERN = re.compile(r"^SP\d*$")


def canonical_relief_role(role: Any) -> str:
    """Return the usage role for a staff label.

    ``SP``/``SP1``-``SP5`` (any ``SP`` plus digits) come back unchanged, as do
    ``CL``, ``SU``, ``LR`` and ``MR``. Everything else -- ``MR1``-``MR5``,
    ``RP``, ``R``, ``P``, an empty or missing label and any unknown token --
    is ``"MR"``. Case and surrounding whitespace are ignored.
    """

    token = str(role or "").strip().upper()
    if _STARTER_PATTERN.match(token) or token in _KEPT_RELIEF_ROLES:
        return token
    return "MR"


__all__ = [
    "OPTIONAL_PITCHING_ROLES",
    "REQUIRED_PITCHING_ROLES",
    "STAFF_ROLES",
    "canonical_relief_role",
]
