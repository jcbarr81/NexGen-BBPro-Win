"""Utilities for assigning pitchers to staff roles.

This module provides logic used by the ``PitchingEditor`` UI to automatically
assign available pitchers to staff roles in a sensible manner.  Starters are
chosen for the rotation before relievers, and relievers are distributed to the
bullpen with closers favoring low endurance arms.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, Tuple

from .pitcher_role import get_role

# Type aliases for clarity
PlayerEntry = Tuple[str, dict]
Assignments = Dict[str, str]


def autofill_pitching_staff(players: Iterable[PlayerEntry]) -> Assignments:
    """Return a mapping of pitching roles to player IDs.

    Parameters
    ----------
    players:
        An iterable of ``(player_id, data)`` pairs where ``data`` is a mapping
        containing at least ``endurance`` and attributes usable by
        :func:`utils.pitcher_role.get_role`.

    The algorithm prefers starting pitchers (``SP``) for the rotation.  If
    there are not enough starters, the highest-endurance relievers are used to
    fill any remaining rotation spots.  Bullpen roles are then assigned using
    the remaining relievers, with the long reliever getting the highest
    endurance and the closer getting the lowest endurance.
    """

    def _entry(pid: str, endurance: int, preferred: str = "") -> dict:
        return {"pid": pid, "endurance": endurance, "preferred": preferred.upper()}

    sps_entries: list[dict] = []
    rps_entries: list[dict] = []
    for pid, pdata in players:
        role = get_role(pdata)
        if not role:
            continue
        try:
            endurance = int(pdata.get("endurance", 0))
        except (TypeError, ValueError):
            endurance = 0
        preferred = str(pdata.get("preferred_pitching_role", "") or "").upper()
        entry = _entry(pid, endurance, preferred)
        if role == "SP" or preferred == "SP":
            sps_entries.append(entry)
        else:
            rps_entries.append(entry)

    def _sorted_deque(entries: list[dict], *, reverse: bool) -> deque[dict]:
        return deque(sorted(entries, key=lambda e: e["endurance"], reverse=reverse))

    sps_high = _sorted_deque(sps_entries, reverse=True)
    sps_low = _sorted_deque(sps_entries, reverse=False)
    rps_high = _sorted_deque(rps_entries, reverse=True)
    rps_low = _sorted_deque(rps_entries, reverse=False)
    closer_entries = [entry for entry in rps_entries if entry["preferred"] == "CL"]
    closer_high = _sorted_deque(closer_entries, reverse=True)
    closer_low = _sorted_deque(closer_entries, reverse=False)
    noncloser_entries = [entry for entry in rps_entries if entry["preferred"] != "CL"]
    noncloser_high = _sorted_deque(noncloser_entries, reverse=True)
    noncloser_low = _sorted_deque(noncloser_entries, reverse=False)

    assigned: set[str] = set()

    def _pop(pool: deque[dict]) -> str | None:
        while pool:
            entry = pool.popleft()
            pid = entry["pid"]
            if pid in assigned:
                continue
            assigned.add(pid)
            return pid
        return None

    def _pop_relief_high(prefer_closer: bool = False) -> str | None:
        pools = [closer_high, noncloser_high] if prefer_closer else [noncloser_high, closer_high]
        for pool in pools:
            pid = _pop(pool)
            if pid is not None:
                return pid
        pid = _pop(rps_high)
        if pid is not None:
            return pid
        return _pop(sps_high)

    def _pop_relief_low(prefer_closer: bool = False) -> str | None:
        pools = [closer_low, noncloser_low] if prefer_closer else [noncloser_low, closer_low]
        for pool in pools:
            pid = _pop(pool)
            if pid is not None:
                return pid
        pid = _pop(rps_low)
        if pid is not None:
            return pid
        return _pop(sps_low)

    assignment: Assignments = {}

    # Fill the starting rotation (SP1-SP5)
    for i in range(5):
        pid = _pop(sps_high)
        if pid is None:
            pid = _pop_relief_high()
        if pid is None:
            break
        assignment[f"SP{i + 1}"] = pid

    # Bullpen roles use remaining relievers (unique by pid).
    # The simulator slots are: LR, MR1, MR2, MR3, SU, CL — match the
    # eleven-row PyQt pitching-staff layout. Fill in priority order so
    # the essentials (LR / CL / SU) are claimed before optional MR2/MR3
    # spots, and so a thin pool still produces a usable staff:
    #   LR  — long relief (high endurance)
    #   CL  — closer (low endurance, prefers preferred_pitching_role="CL")
    #   SU  — setup (low-ish endurance, just before closer)
    #   MR1 — primary middle relief (high endurance)
    #   MR2 — depth middle relief (high endurance)
    #   MR3 — depth middle relief (high endurance)
    pid = _pop_relief_high()
    if pid is not None:
        assignment["LR"] = pid
    pid = _pop_relief_low(prefer_closer=True)
    if pid is None:
        pid = _pop_relief_low()
    if pid is not None:
        assignment["CL"] = pid
    pid = _pop_relief_low()
    if pid is not None:
        assignment["SU"] = pid
    for slot in ("MR1", "MR2", "MR3"):
        pid = _pop_relief_high()
        if pid is None:
            break
        assignment[slot] = pid

    return assignment
