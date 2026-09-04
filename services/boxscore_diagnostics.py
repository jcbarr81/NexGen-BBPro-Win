"""Record why a box score failed to save.

Box scores are written by the sim and their path stored in the schedule, but
every save site wrapped the write in a bare ``except Exception: pass``. In
production not one box score has ever been written — 1,620 played games in one
league, zero files — and the reason was swallowed at each of the three call
sites, so there was nothing to go on.

``nexgen.*`` logging does not surface in Cloud Run, so this writes to a file in
the league's data directory instead: it rides the normal working-copy push to
durable storage, where it can be read back directly without a login. Failures
are recorded with the exception type and message; a successful save clears the
log so a fixed league stops reporting stale problems.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_FILENAME = "boxscore_errors.json"

# Enough to see a pattern across a day's games without unbounded growth.
MAX_ENTRIES = 50


def _log_path(data_dir: Optional[Path] = None) -> Path:
    if data_dir is None:
        from utils.path_utils import get_data_dir

        data_dir = Path(get_data_dir())
    return Path(data_dir) / LOG_FILENAME


def record_failure(
    stage: str,
    game_id: str,
    exc: BaseException,
    *,
    data_dir: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one box-score save failure. Never raises."""

    try:
        path = _log_path(data_dir)
        entries: List[Dict[str, Any]] = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    entries = [e for e in loaded if isinstance(e, dict)]
            except Exception:
                entries = []
        entry: Dict[str, Any] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "game_id": game_id,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        if extra:
            entry.update({k: str(v)[:300] for k, v in extra.items()})
        entries.append(entry)
        # Keep the most recent; a season's worth of identical failures is noise.
        entries = entries[-MAX_ENTRIES:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception:  # pragma: no cover - diagnostics must never break a sim
        pass


def record_success(*, data_dir: Optional[Path] = None) -> None:
    """Clear the log once a box score saves, so it only ever shows live problems."""

    try:
        path = _log_path(data_dir)
        if path.exists():
            path.unlink()
    except Exception:  # pragma: no cover - defensive
        pass


def read_failures(*, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    try:
        path = _log_path(data_dir)
        if not path.exists():
            return []
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return [e for e in loaded if isinstance(e, dict)] if isinstance(loaded, list) else []
    except Exception:  # pragma: no cover - defensive
        return []
