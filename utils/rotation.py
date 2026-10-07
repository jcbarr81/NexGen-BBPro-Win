"""The one place that decides who is in a club's five-man rotation.

Moved out of :mod:`utils.pitcher_recovery` so the tracker, the default
lineup builder and the physics harness can share a single rotation builder
instead of each picking their own five. Pure functions only: nothing here
reads or writes league files.
"""

from __future__ import annotations

from typing import Mapping, Sequence

_RELIEF_STAFF_ROLES = {"CL", "SU", "LR"}

# How naturally a relief label converts to a spot start. The long man exists
# for exactly this; the closer is the last arm you want opening a game.
_SPOT_START_RANK = {"LR": 0, "MR": 1, "SU": 2, "CL": 3}


def _spot_start_rank(staff_role: str | None) -> int:
    token = str(staff_role or "").strip().upper()
    if token.startswith("MR"):
        token = "MR"
    return _SPOT_START_RANK.get(token, 1)


def _is_relief_role(staff_role: str | None) -> bool:
    """True when the owner's staff file labels this arm as relief.

    Roles are the tokens in ``{team}_pitching.csv``: SP1-SP5, CL, SU, LR and
    MR1/MR2/... Anything unlabelled is not treated as relief, so a pitcher the
    owner never assigned can still fill a rotation hole.
    """

    token = str(staff_role or "").strip().upper()
    if not token:
        return False
    return token in _RELIEF_STAFF_ROLES or token.startswith("MR")


ROTATION_SLOTS = 5


def choose_rotation(
    *,
    saved_rotation: Sequence[str],
    existing_rotation: Sequence[str],
    starter_capable: Sequence[tuple[str, int]],
    staff_roles: Mapping[str, str],
    built: Sequence[str],
    eligible: Sequence[str],
) -> list[str]:
    """Pick the five who will start, best claim first.

    ``starter_capable`` is ``(player_id, endurance)`` for every active arm whose
    resolved role is SP; ``eligible`` is everyone allowed in a slot (the active
    roster), and nobody outside it can be chosen.

    The order of preference matters more than it looks. A fill that merely
    "already holds the slot" used to outrank every better candidate, and since
    it re-qualified the next day too, one bad choice was permanent -- which is
    how a closer kept a rotation spot on the live league while three starters
    sat on the active roster.
    """

    capable = {pid: endurance for pid, endurance in starter_capable if pid}
    by_strength = sorted(capable, key=lambda pid: -capable[pid])
    # Arms the owner has not committed to the bullpen.
    free_starters = [pid for pid in by_strength if not _is_relief_role(staff_roles.get(pid))]
    # Then arms who can start but are assigned to relief. A thin staff may have
    # nothing else, and there the long man is the answer and the closer is not.
    bullpen_starters = sorted(
        (pid for pid in by_strength if _is_relief_role(staff_roles.get(pid))),
        key=lambda pid: (_spot_start_rank(staff_roles.get(pid)), -capable[pid]),
    )

    candidates: list[str] = []
    candidates.extend(saved_rotation)                                    # the owner's own five
    candidates.extend(pid for pid in existing_rotation if pid in free_starters)
    candidates.extend(free_starters)
    candidates.extend(bullpen_starters)
    candidates.extend(existing_rotation)   # keep a thin staff stable rather than churning
    candidates.extend(built)
    candidates.extend(eligible)            # last resort: anyone with a pulse

    allowed = set(eligible)
    rotation: list[str] = []
    seen: set[str] = set()
    for pid in candidates:
        if len(rotation) >= ROTATION_SLOTS:
            break
        if not pid or pid not in allowed or pid in seen:
            continue
        rotation.append(pid)
        seen.add(pid)
    return rotation


__all__ = [
    "ROTATION_SLOTS",
    "choose_rotation",
    "_is_relief_role",
    "_spot_start_rank",
]
