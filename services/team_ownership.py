"""Who actually controls a team — human or CPU.

There are two places a team's owner can appear and they disagree. In the cloud,
ownership is written to ``users.txt`` by the memberships bridge; ``teams.csv``
keeps an ``owner_id`` column that is left EMPTY for every team. So a check that
reads only ``teams.csv`` concludes that a league full of human owners is
entirely CPU-run — in alpha-test that is 7 real owners reported as bots.

``services/finance_ai.py`` documented the trap and worked around it privately so
CPU free agency would not bid on a human's behalf. Everything else that asks the
question needs the same answer, so it lives here once: consult ``users.txt``
first, fall back to ``teams.csv`` for single-tenant leagues that never had a
memberships bridge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Set

# An owner_id that means "nobody is driving this team".
CPU_OWNER_IDS = {"", "cpu", "ai", "none", "computer", "bot"}

# Accounts that are not a team owner even though they appear in users.txt.
_NON_OWNER_ROLES = {"admin"}


def _data_dir(data_dir: Path | str | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    from utils.path_utils import get_data_dir

    return get_data_dir()


def human_owned_team_ids(data_dir: Path | str | None = None) -> Set[str]:
    """Every team id bound to a real person, upper-cased.

    Reads ``users.txt`` (the cloud's source of truth). A user row with no team
    — the commissioner account, typically — binds no team and is skipped.
    """

    root = _data_dir(data_dir)
    ids: Set[str] = set()
    try:
        from utils.user_manager import load_users

        users = load_users(str(root / "users.txt"))
    except Exception:
        users = []
    for user in users or []:
        try:
            role = str(user.get("role", "") or "").strip().lower()
            team_id = str(user.get("team_id", "") or "").strip().upper()
        except AttributeError:
            continue
        if not team_id or role in _NON_OWNER_ROLES:
            continue
        ids.add(team_id)

    if ids:
        return ids

    # No memberships bridge (a local single-tenant league): fall back to the
    # teams.csv column, which in that setup is the only record there is.
    return _owner_ids_from_teams_csv(root)


def _owner_ids_from_teams_csv(root: Path) -> Set[str]:
    import csv

    ids: Set[str] = set()
    path = root / "teams.csv"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                owner = str(row.get("owner_id", "") or "").strip().lower()
                team_id = str(row.get("team_id", "") or "").strip().upper()
                if team_id and owner not in CPU_OWNER_IDS:
                    ids.add(team_id)
    except OSError:
        return set()
    return ids


def is_human_owned(
    team_id: Optional[str],
    *,
    human_ids: Optional[Set[str]] = None,
    data_dir: Path | str | None = None,
) -> bool:
    """True when a real person controls *team_id*.

    Pass ``human_ids`` when asking about many teams at once; otherwise every
    call re-reads ``users.txt``.
    """

    token = str(team_id or "").strip().upper()
    if not token:
        return False
    ids = human_ids if human_ids is not None else human_owned_team_ids(data_dir)
    return token in ids


def is_cpu_owned(
    team_id: Optional[str],
    *,
    human_ids: Optional[Set[str]] = None,
    data_dir: Path | str | None = None,
) -> bool:
    """True when no person controls *team_id*.

    An unknown or empty team id is NOT reported as CPU: callers use this to
    decide whether to act on a team's behalf, and acting for a team we cannot
    identify is the worse failure.
    """

    token = str(team_id or "").strip().upper()
    if not token:
        return False
    return not is_human_owned(token, human_ids=human_ids, data_dir=data_dir)


__all__ = [
    "CPU_OWNER_IDS",
    "human_owned_team_ids",
    "is_cpu_owned",
    "is_human_owned",
]
