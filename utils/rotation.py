"""The one place that decides who is in a club's five-man rotation.

Moved out of :mod:`utils.pitcher_recovery` so the tracker, the default
lineup builder and the physics harness can share a single rotation builder
instead of each picking their own five. :func:`game_staff_roles` turns a
rotation plus the staff file into the role map one game is played with. Pure
functions only: nothing here reads or writes league files.
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


def is_starter_capable(pitcher: object) -> bool:
    """The one "can this arm start?" test for every rotation builder.

    :func:`utils.pitcher_role.get_role` is ``"SP"``. A physics-engine
    ``PitcherRatings`` carries its declared role as ``preferred_role`` (the
    ``preferred_pitching_role`` column), so it is read under that name; the
    stored ``role`` column is only the last fallback, as in ``get_role``.
    """

    from utils.pitcher_role import get_role

    if hasattr(pitcher, "preferred_pitching_role") or isinstance(pitcher, dict):
        return get_role(pitcher) == "SP"
    view = {
        "primary_position": getattr(pitcher, "primary_position", ""),
        "preferred_pitching_role": getattr(pitcher, "preferred_role", ""),
        "endurance": getattr(pitcher, "endurance", None),
        "role": getattr(pitcher, "role", ""),
    }
    return get_role(view) == "SP"


def _endurance(pitcher: object) -> int:
    try:
        return int(getattr(pitcher, "endurance", 0) or 0)
    except (TypeError, ValueError):
        return 0


def staff_rotation(
    pitchers: Sequence[object],
    staff_roles: Mapping[str, str],
) -> list[str]:
    """The five who start for a club, from its active arms and staff file.

    The single entry point the recovery tracker, the default lineup builder
    and the harness staff builder all call, with the same inputs, so they can
    never pick different fives (Release 3 fix round). ``pitchers`` are the
    active arms (objects with ``player_id`` and ``endurance``) and
    ``staff_roles`` the staff file as pid -> label. The staff file's SP1-SP5
    come first in slot order; holes are filled by :func:`choose_rotation` from
    starter-capable arms (:func:`is_starter_capable`), then by endurance. The
    closer is never a candidate unless he is the only arm. Nothing here
    depends on what was picked yesterday, so a rotation is a pure function of
    today's roster and staff file; ties break on player id, never on the
    order a caller happened to list the arms in.
    """

    by_id: dict[str, object] = {}
    for pitcher in pitchers:
        pid = str(getattr(pitcher, "player_id", "") or "")
        if pid and pid not in by_id:
            by_id[pid] = pitcher
    ids = sorted(by_id)
    labels = {
        pid: str(staff_roles.get(pid) or "").strip().upper() for pid in ids
    }
    saved = sorted(
        (label, pid) for pid, label in labels.items() if label in _SAVED_SLOTS
    )
    capable = [(pid, _endurance(by_id[pid])) for pid in ids if is_starter_capable(by_id[pid])]
    capable_ids = {pid for pid, _ in capable}
    built = sorted(
        ids, key=lambda pid: (pid not in capable_ids, -_endurance(by_id[pid]), pid)
    )
    eligible = [pid for pid in ids if labels[pid] != "CL"] or ids
    return choose_rotation(
        saved_rotation=[pid for _, pid in saved],
        existing_rotation=[],
        starter_capable=capable,
        staff_roles=labels,
        built=built,
        eligible=eligible,
    )


_SAVED_SLOTS = frozenset({"SP1", "SP2", "SP3", "SP4", "SP5"})


def game_staff_roles(
    staff_roles: Mapping[str, str],
    active_pitcher_ids: Sequence[str],
    rotation: Sequence[str],
) -> dict[str, str]:
    """The role each active arm pitches under in one game.

    ``rotation`` members are SP1, SP2, ... in rotation order. Everyone else
    keeps his staff-file relief label (``CL``, ``SU``, ``LR``, ``MR2``...), and
    an arm the file lists as a starter but who is not in the rotation, or who
    is not listed at all, is a middle reliever. The stored ``role`` column is
    never consulted: it reads "RP" for every pitcher in an older league.

    Returns a fresh mapping; no player object is touched.
    """

    active = [str(pid) for pid in active_pitcher_ids if pid]
    allowed = set(active)
    roles: dict[str, str] = {}
    slot = 0
    for pid in rotation:
        if not pid or pid not in allowed or pid in roles:
            continue
        slot += 1
        roles[pid] = f"SP{slot}"
    for pid in active:
        if pid in roles:
            continue
        label = str(staff_roles.get(pid) or "").strip().upper()
        if not label or label.startswith("SP"):
            label = "MR"
        roles[pid] = label
    return roles


__all__ = [
    "ROTATION_SLOTS",
    "choose_rotation",
    "game_staff_roles",
    "is_starter_capable",
    "staff_rotation",
    "_is_relief_role",
    "_spot_start_rank",
]
