"""Who was called up to cover each injured player, so he goes back down.

When a CPU club's player is activated onto a full active roster, someone has
to be optioned. Picking "the most recent same-type active player" was wrong:
trades, earlier returns and monthly call-ups append to the active list too, so
a returning starting catcher could be the one sent down while both injury
call-ups stayed (audit H9 review). This records the real replacement at injury
time -- and the level he came from -- in ``injury_replacements.json`` under
the league's data dir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from utils.path_utils import get_data_dir

__all__ = ["record_replacement", "pop_replacement"]

_FILENAME = "injury_replacements.json"


def _path() -> Path:
    return get_data_dir() / _FILENAME


def _load() -> Dict[str, Dict[str, str]]:
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: Dict[str, Dict[str, str]]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def record_replacement(
    team_id: str, injured_id: str, replacement_id: str, from_level: str
) -> None:
    """Remember that ``replacement_id`` came up from ``from_level`` for him."""

    if not (team_id and injured_id and replacement_id):
        return
    data = _load()
    data[str(injured_id)] = {
        "team_id": str(team_id),
        "replacement_id": str(replacement_id),
        "from_level": str(from_level or "aaa").lower(),
    }
    _save(data)


def pop_replacement(team_id: str, injured_id: str) -> Optional[Dict[str, str]]:
    """Return and forget the replacement recorded for ``injured_id``."""

    data = _load()
    entry = data.pop(str(injured_id), None)
    if entry is None:
        return None
    _save(data)
    if str(entry.get("team_id", "")) != str(team_id):
        return None  # he changed clubs while hurt; that call-up is not ours
    return entry
