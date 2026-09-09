"""Which team a player belongs to.

``players.csv`` has no ``team_id`` column — roster membership lives in the
per-team roster CSVs. Anything reading ``player.team_id`` therefore gets an
empty string, which is why the league leaderboards showed no teams: the client
renders the team chip conditionally, so it simply vanished with no error
anywhere.

One pass over the roster files builds the mapping for every player at once,
rather than re-scanning per player.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Optional

from utils.path_utils import get_data_dir

# Staff-role files (``<team>_pitching.csv``) sit alongside the roster files and
# carry SP1/CL/etc, not roster membership. Their stem would yield a team id of
# "CHI_pitching", so they are skipped rather than merely losing a race with
# their sibling on glob order.
_STAFF_SUFFIX = "_pitching"


def player_team_index(data_dir: Optional[Path] = None) -> Dict[str, str]:
    """Return ``player_id -> team_id`` for every rostered player.

    Every level counts (ACT / AAA / LOW / DL / IR); the first roster file
    containing a player wins. Never raises — a missing or unreadable roster
    directory yields an empty mapping and callers degrade to no team.
    """

    base = Path(data_dir) if data_dir is not None else get_data_dir()
    rosters_dir = base / "rosters"
    if not rosters_dir.exists():
        return {}

    index: Dict[str, str] = {}
    for roster_file in sorted(rosters_dir.glob("*.csv")):
        if roster_file.stem.endswith(_STAFF_SUFFIX):
            continue
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if not row:
                        continue
                    pid = (row[0] or "").strip()
                    if pid:
                        index.setdefault(pid, roster_file.stem)
        except OSError:
            continue
    return index


def team_for_player(player_id: str, index: Optional[Dict[str, str]] = None) -> str:
    """Team id for one player. Pass a prebuilt *index* when resolving many."""

    lookup = index if index is not None else player_team_index()
    return lookup.get(str(player_id or "").strip(), "")


__all__ = ["player_team_index", "team_for_player"]
