"""How many times this process has written each ``players.csv``.

Caches keyed on a players file (``utils.rating_display``: the scale a
league's pages are on, each rating's league distribution) put this count in
their key next to the file's nanosecond mtime and size, so a rewrite is seen
even when two writes land in one timestamp tick with the same size. Every
writer of the file calls :func:`note_players_file_written`: the one writer
(``utils.player_writer``), the draft append (``services.draft_assignment``),
the injury-date repair tool and the working copy's file copies
(``api.working_copy``).

Standard library only, so any module can call it.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_WRITES: Dict[str, int] = {}


def _key(path: Any) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def note_players_file_written(path: Any) -> None:
    """Record that ``path`` (a ``players.csv``) was just (re)written."""

    key = _key(path)
    _WRITES[key] = _WRITES.get(key, 0) + 1


def players_file_write_count(path: Any) -> int:
    """How many times this process has recorded a write of ``path``."""

    return _WRITES.get(_key(path), 0)


__all__ = ["note_players_file_written", "players_file_write_count"]
