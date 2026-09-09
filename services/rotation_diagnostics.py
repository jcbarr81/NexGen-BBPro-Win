"""Record how each start was awarded, so the rotation can be reasoned about.

An owner reported his top two starters taking roughly double the starts of the
other three. That reproduced exactly — 17 of 20 teams in the live league show an
identical 13/12/6/6/6 split — but replaying ``assign_starter`` against the real
schedule and the real rest values produces an even 9/9/9/8/8. The live behaviour
differs from the code as read, and no amount of further reasoning was going to
close that gap.

So this records the decision itself: which slot the pointer was on, which slot
was chosen, what every slot's rest looked like at that moment, and whether the
"everyone is tired" fallback fired. Rows land in the league's data directory,
which rides the normal working-copy push to durable storage and can be read back
without a login — the same approach that settled the box score bug.

Off unless ``NEXGEN_ROTATION_DIAGNOSTICS`` is set, since this sits in the path
of every game. Recording can never raise: it is describing work the simulation
has already decided to do.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

LOG_FILENAME = "rotation_decisions.json"
ENABLE_ENV = "NEXGEN_ROTATION_DIAGNOSTICS"

# A week of a 20-team league is ~280 decisions; this holds a bit over one.
MAX_ENTRIES = 400

# Written rows are buffered so a 140-game day is not 280 read-modify-writes.
_buffer: List[Dict[str, Any]] = []


def is_enabled() -> bool:
    return bool((os.environ.get(ENABLE_ENV) or "").strip())


def _log_path(data_dir: Optional[Path] = None) -> Path:
    if data_dir is None:
        from utils.path_utils import get_data_dir

        data_dir = Path(get_data_dir())
    return Path(data_dir) / LOG_FILENAME


def record_decision(
    *,
    team_id: str,
    date_str: str,
    rotation: Sequence[str],
    next_index_in: int,
    chosen_index: int,
    next_index_out: int,
    availability: Sequence[str],
    used_fallback: bool,
    data_dir: Optional[Path] = None,
) -> None:
    """Append one starter decision. A no-op when disabled; never raises.

    ``availability`` is each rotation slot's ``available_on`` in slot order, so
    a reader can tell a genuine rest skip from a pointer that moved on its own.
    """

    if not is_enabled():
        return
    try:
        total = max(1, len(rotation))
        _buffer.append(
            {
                "date": str(date_str),
                "team": str(team_id),
                "slot_in": int(next_index_in),
                "slot_chosen": int(chosen_index),
                "slot_out": int(next_index_out),
                "skipped": int((chosen_index - next_index_in) % total),
                "fallback": bool(used_fallback),
                "starter": str(rotation[chosen_index]) if rotation else "",
                "rotation": [str(p) for p in rotation],
                "available_on": [str(a) for a in availability],
            }
        )
        _flush(data_dir)
    except Exception:  # pragma: no cover - diagnostics must never break a sim
        pass


def _flush(data_dir: Optional[Path] = None) -> None:
    """Merge the buffer into the on-disk log.

    Rewritten in full each time rather than appended to, because a sim runs
    across processes and the parent is the only writer of a given league's
    decisions; a whole-file write keeps the log valid JSON at every instant.
    """

    global _buffer
    if not _buffer:
        return
    path = _log_path(data_dir)
    entries: List[Dict[str, Any]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = [e for e in loaded if isinstance(e, dict)]
        except Exception:
            entries = []
    entries.extend(_buffer)
    _buffer = []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries[-MAX_ENTRIES:]), encoding="utf-8")


def read_decisions(*, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    try:
        path = _log_path(data_dir)
        if not path.exists():
            return []
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return [e for e in loaded if isinstance(e, dict)] if isinstance(loaded, list) else []
    except Exception:  # pragma: no cover - defensive
        return []


def summarize(entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Starts per slot and how often the fallback fired, for a quick read."""

    per_slot: Dict[int, int] = {}
    skips = fallbacks = 0
    for entry in entries:
        slot = int(entry.get("slot_chosen", -1))
        per_slot[slot] = per_slot.get(slot, 0) + 1
        if int(entry.get("skipped", 0)):
            skips += 1
        if entry.get("fallback"):
            fallbacks += 1
    return {
        "decisions": len(entries),
        "starts_by_slot": {slot: per_slot[slot] for slot in sorted(per_slot)},
        "skipped": skips,
        "fallbacks": fallbacks,
    }


__all__ = [
    "ENABLE_ENV",
    "LOG_FILENAME",
    "is_enabled",
    "read_decisions",
    "record_decision",
    "summarize",
]
