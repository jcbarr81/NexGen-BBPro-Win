"""Which club owns a player: the one place that answers it from the files.

A player belongs to a club when he is on ANY level of that club's roster file
(``rosters/<TEAM>.csv``): the active roster, AAA, Low-A and every injured
list level (``DL`` / ``DL15`` / ``DL45`` / ``IR``) -- and, as a second
source, when ``contracts.json`` holds a contract for him with a club. The
pitching-staff files (``<TEAM>_pitching.csv``) only label roles and never
make a player a club's.

Free agency used to count only ACT / AAA / LOW, so a player on a club's
injured list was listed as a free agent, signed by another club (his contract
overwritten) and, once healthy, activated by both clubs. Everything that
offers a player to a club now asks :func:`owning_club`, and
:func:`check_roster_write` (called by ``utils.roster_loader.save_roster``)
refuses any roster write that would put a player on a second club.

Nothing here writes a file.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# Imported by utils.roster_loader: this module must not import it (or any
# service) back.

logger = logging.getLogger(__name__)

# Every level a club's roster file may hold. Any other token found in a
# roster file still counts as the club's (an unknown level is never a free
# agent); this tuple is for messages and tests.
CLUB_ROSTER_LEVELS = ("ACT", "AAA", "LOW", "DL", "DL15", "DL45", "IR")

_ROSTER_ATTRS = ("act", "aaa", "low", "dl", "ir")


class DoubleRosterError(ValueError):
    """A roster write would put a player on two clubs at once."""

    def __init__(self, team_id: str, conflicts: Sequence[Tuple[str, str, str]]):
        self.team_id = str(team_id)
        # (player_id, other_team, other_level)
        self.conflicts = [tuple(c) for c in conflicts]
        parts = [
            f"{pid} is already on {other}'s roster ({level})"
            for pid, other, level in self.conflicts
        ]
        super().__init__(
            f"Refused to save {self.team_id}'s roster: "
            + "; ".join(parts)
            + ". A player can belong to only one club; take him off the "
            "other club's roster first."
        )


def is_roster_file(path: Path) -> bool:
    """A club roster file: ``<TEAM>.csv``, not a staff file or a registry."""

    name = path.name
    return (
        path.suffix.lower() == ".csv"
        and not path.stem.endswith("_pitching")
        and not name.startswith("_")
        and not name.startswith(".")
    )


def read_roster_rows(path: Path) -> List[Tuple[str, str]]:
    """``(player_id, LEVEL)`` rows of one roster file ([] when unreadable)."""

    rows: List[Tuple[str, str]] = []
    try:
        with Path(path).open(mode="r", newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if len(row) < 2:
                    continue
                pid = row[0].strip()
                level = row[1].strip().upper()
                if not pid or pid.lower() == "player_id":
                    continue
                rows.append((pid, level))
    except (OSError, UnicodeDecodeError):
        return []
    return rows


def roster_memberships(roster_dir: Path | str) -> Dict[str, List[Tuple[str, str]]]:
    """Every player in the roster files: ``{pid: [(team_id, LEVEL), ...]}``.

    Clubs are listed in file-name order, so the result is deterministic.
    """

    directory = Path(roster_dir)
    out: Dict[str, List[Tuple[str, str]]] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not is_roster_file(path):
            continue
        team_id = path.stem
        for pid, level in read_roster_rows(path):
            out.setdefault(pid, []).append((team_id, level))
    return out


def contract_teams(data_dir: Path | str) -> Dict[str, str]:
    """``{pid: team_id}`` for every contract in ``contracts.json`` with a club
    and at least one year left."""

    path = Path(data_dir) / "contracts.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    players = payload.get("players") if isinstance(payload, Mapping) else None
    if not isinstance(players, Mapping):
        return {}
    out: Dict[str, str] = {}
    for pid, contract in players.items():
        if not isinstance(contract, Mapping):
            continue
        team = str(contract.get("team_id") or "").strip()
        if not team:
            continue
        try:
            years = int(contract.get("years_left", 1) or 0)
        except (TypeError, ValueError):
            years = 1
        if years <= 0:
            continue
        out[str(pid).strip()] = team
    return out


def club_owned_players(
    data_dir: Path | str,
    *,
    include_contracts: bool = True,
) -> Dict[str, Tuple[str, str]]:
    """``{pid: (team_id, LEVEL)}`` for every player some club owns.

    The roster files decide; a player on no roster file but under contract
    with a club is that club's too (level ``"CONTRACT"``). A player on two
    clubs' files (a state the guard now refuses) is reported with the first.
    """

    base = Path(data_dir)
    owned: Dict[str, Tuple[str, str]] = {}
    for pid, places in roster_memberships(base / "rosters").items():
        owned[pid] = places[0]
    if include_contracts:
        for pid, team in contract_teams(base).items():
            owned.setdefault(pid, (team, "CONTRACT"))
    return owned


def unrostered_contracts(
    data_dir: Path | str, *, team_id: Optional[str] = None
) -> Dict[str, str]:
    """``{pid: team_id}``: under contract with a club, on no roster file.

    The club owns him (no one else may sign him) and may put him back on its
    roster (``services.free_agency.restore_contracted_player``): a qualifying
    offer accepted after the rollover took him off, or an older build's
    leftover. ``team_id`` limits it to one club.
    """

    base = Path(data_dir)
    rostered = roster_memberships(base / "rosters")
    out: Dict[str, str] = {}
    for pid, team in contract_teams(base).items():
        if pid in rostered:
            continue
        if team_id is not None and team != str(team_id):
            continue
        out[pid] = team
    return out


def owning_club(
    player_id: str,
    data_dir: Path | str,
    *,
    include_contracts: bool = True,
) -> Optional[Tuple[str, str]]:
    """``(team_id, LEVEL)`` of the club that owns ``player_id``, or None."""

    pid = str(player_id or "").strip()
    if not pid:
        return None
    base = Path(data_dir)
    for team_id, level in roster_memberships(base / "rosters").get(pid, []):
        return team_id, level
    if include_contracts:
        team = contract_teams(base).get(pid)
        if team:
            return team, "CONTRACT"
    return None


def roster_player_ids(roster: object) -> List[str]:
    """Every player id on a ``Roster`` object, any level, in order."""

    seen: List[str] = []
    for attr in _ROSTER_ATTRS:
        for pid in getattr(roster, attr, None) or []:
            text = str(pid or "").strip()
            if text and text not in seen:
                seen.append(text)
    return seen


def check_roster_writes(
    writes: Mapping[str, Iterable[str]],
    roster_dir: Path | str,
) -> None:
    """Refuse roster writes that would put a player on two clubs.

    ``writes`` maps each club being saved to the player ids its file will
    hold. A player who is NEW to a club's file (not on it now) must be on no
    other club's roster -- where every club in ``writes`` counts as written,
    so a trade's two rosters are checked together. Players already on the
    club's file are not re-judged: a league that already holds a player on
    two clubs (written by an older build) keeps simulating, and
    ``scripts/find_double_rostered_players.py`` lists those for the owner.

    Raises :class:`DoubleRosterError` naming every conflict.
    """

    directory = Path(roster_dir)
    pending = {str(team): [str(p) for p in ids] for team, ids in writes.items()}
    added: Dict[str, List[str]] = {}
    for team_id, ids in pending.items():
        current = {pid for pid, _ in read_roster_rows(directory / f"{team_id}.csv")}
        new = [pid for pid in ids if pid not in current]
        if new:
            added[team_id] = new
    if not added:
        return

    # The state after the writes: written clubs from ``writes``, the rest
    # from their files.
    places: Dict[str, List[Tuple[str, str]]] = {}
    for pid, memberships in roster_memberships(directory).items():
        for team_id, level in memberships:
            if team_id in pending:
                continue
            places.setdefault(pid, []).append((team_id, level))
    for team_id, ids in pending.items():
        for pid in ids:
            places.setdefault(pid, []).append((team_id, "PENDING"))

    for team_id, new_ids in added.items():
        conflicts = []
        for pid in new_ids:
            for other, level in places.get(pid, []):
                if other != team_id:
                    conflicts.append((pid, other, level))
        if conflicts:
            error = DoubleRosterError(team_id, conflicts)
            logger.warning("%s", error)
            raise error


__all__ = [
    "CLUB_ROSTER_LEVELS",
    "DoubleRosterError",
    "check_roster_writes",
    "club_owned_players",
    "contract_teams",
    "is_roster_file",
    "owning_club",
    "read_roster_rows",
    "roster_memberships",
    "roster_player_ids",
    "unrostered_contracts",
]
