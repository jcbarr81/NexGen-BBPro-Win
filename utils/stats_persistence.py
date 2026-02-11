"""Utilities for persisting season statistics.

Reads and writes to ``season_stats.json`` are guarded by an inter-process
file lock to prevent concurrent writers from corrupting the data.  On Unix
systems the lock is implemented with :mod:`fcntl`; on Windows it falls back
to :mod:`msvcrt`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

import contextlib
import errno
import os
import tempfile
import time
from datetime import date as _date
from datetime import datetime as _dt

if os.name == "nt":  # pragma: no cover - Windows specific
    import msvcrt

    @contextlib.contextmanager
    def _locked(file):
        """Lock ``file`` using :mod:`msvcrt` semantics.

        ``msvcrt.locking`` cannot lock a file of zero length.  When the lock
        file is opened with ``"w"`` its size is truncated to ``0`` which would
        trigger ``OSError: [Errno 36]`` on Windows.  To avoid this we write a
        single byte before acquiring the lock.  The function also retries when
        the lock is temporarily unavailable, which can otherwise raise
        ``OSError: [Errno 36]`` (resource deadlock avoided).
        """
        # Ensure the file is at least one byte long before attempting to lock
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write("0")
            file.flush()
            file.seek(0)

        while True:
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:  # pragma: no cover - depends on timing
                if exc.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
                time.sleep(0.01)

        try:
            yield
        finally:
            try:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
else:  # Unix
    import fcntl

    @contextlib.contextmanager
    def _locked(file):
        """Lock ``file`` using :mod:`fcntl` semantics."""
        try:
            fcntl.flock(file, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)

from utils.path_utils import get_data_dir, resolve_app_path
from utils.sim_date import get_current_sim_date


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return resolve_app_path(p)


def _truthy_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _season_history_dir(base_dir: Path | None = None) -> Path:
    d = get_data_dir() / "season_history" if base_dir is None else base_dir / "data" / "season_history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _current_sim_date_str() -> str:
    # Prefer the simulator's current date; fall back to today.
    sim = get_current_sim_date()
    if sim:
        return str(sim)
    return _dt.utcnow().date().isoformat()


def write_daily_snapshot(
    players: Iterable[Any],
    teams: Iterable[Any],
    *,
    date_str: str | None = None,
    shards_dir: str | Path | None = None,
) -> Path:
    """Write a per-day snapshot of season stats and return its path.

    The snapshot contains the same structure as a single entry in
    ``history``: a dict with ``players`` and ``teams`` mappings. Writing
    a daily snapshot avoids unbounded growth of the canonical history file
    and keeps per-game I/O bounded.
    """

    out_dir = _season_history_dir() if shards_dir is None else _resolve_path(shards_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    d = str(date_str or _current_sim_date_str())
    # Use ISO date as filename; if multiple leagues or runs need separation
    # later, we can include a league token.
    path = out_dir / f"{d}.json"
    snapshot = {
        "players": {p.player_id: getattr(p, "season_stats", {}) for p in players},
        "teams": {t.team_id: getattr(t, "season_stats", {}) for t in teams},
        "date": d,
    }
    # Best-effort write; if interrupted mid-day, later calls overwrite.
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
    except Exception:
        pass
    return path


def merge_daily_history(
    *,
    path: str | Path = "data/season_stats.json",
    shards_dir: str | Path = "data/season_history",
) -> Path:
    """Incrementally merge per-day snapshots into the canonical history.

    - Appends only new shards beyond the last merged date to the ``history``
      list to keep merges O(1) per day.
    - Keeps ``players``/``teams`` equal to the latest snapshot values.
    """

    file_path = _resolve_path(path)
    shards_path = _resolve_path(shards_dir)
    # Load current canonical to preserve any existing content.
    stats = load_stats(file_path)
    players = stats.get("players", {})
    teams = stats.get("teams", {})
    history: list[dict[str, Any]] = list(stats.get("history", []) or [])

    # Determine last merged date if present
    last_date = None
    if history:
        try:
            last_date_val = history[-1].get("date")
            if last_date_val:
                last_date = str(last_date_val)
        except Exception:
            last_date = None

    # Build a set of already merged dates to guard against duplicates
    merged_dates = set()
    for entry in history:
        try:
            d = entry.get("date")
            if d:
                merged_dates.add(str(d))
        except Exception:
            continue

    # Limit merges to shard dates within the current schedule window when
    # a schedule is present. This prevents stale shards from previous seasons
    # re-populating the canonical history after a reset.
    season_start: str | None = None
    season_end: str | None = None
    try:
        import csv as _csv
        sched_path = get_data_dir() / "schedule.csv"
        if sched_path.exists():
            with sched_path.open("r", encoding="utf-8", newline="") as _fh:
                rows = list(_csv.DictReader(_fh))
            if rows:
                dates = [str(r.get("date") or "").strip() for r in rows]
                dates = [d for d in dates if d]
                if dates:
                    season_start = min(dates)
                    season_end = max(dates)
    except Exception:
        # Best effort only
        season_start = season_start or None
        season_end = season_end or None

    shard_files = sorted([p for p in shards_path.glob("*.json") if p.is_file()])
    for sf in shard_files:
        date_token = sf.stem  # YYYY-MM-DD
        if season_start and season_end and not (season_start <= date_token <= season_end):
            # Outside active schedule window; skip
            continue
        if last_date and date_token <= last_date:
            # Skip shards up to and including last merged date
            continue
        if date_token in merged_dates:
            continue
        try:
            with sf.open("r", encoding="utf-8") as fh:
                snap = json.load(fh)
            if not isinstance(snap, dict):
                continue
            h_entry = {
                "players": snap.get("players", {}),
                "teams": snap.get("teams", {}),
                "date": str(snap.get("date") or date_token),
            }
            history.append(h_entry)
            merged_dates.add(h_entry["date"])  # keep set in sync
            # Do not overwrite canonical players/teams with a single shard's
            # snapshot. The canonical file already accumulates per-game
            # updates via save_stats(); keep those intact here.
        except Exception:
            continue

    # Persist merged canonical file
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump({"players": players, "teams": teams, "history": history}, f, indent=2)
    return file_path


def reset_stats(path: str | Path = "data/season_stats.json") -> Path:
    """Overwrite the season stats file with an empty payload.

    Uses the shared lock file to avoid clobbering concurrent writes and
    replaces the target atomically to minimize the risk of partial writes.
    """

    file_path = _resolve_path(path)
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"players": {}, "teams": {}, "history": []}

    attempts = 0
    while True:
        attempts += 1
        try:
            with lock_path.open("a+") as lock_file:
                with _locked(lock_file):
                    fd, tmp_name = tempfile.mkstemp(
                        dir=str(file_path.parent),
                        prefix=f"{file_path.name}.",
                        suffix=".tmp",
                    )
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                            json.dump(payload, tmp_file, indent=2)
                        os.replace(tmp_name, file_path)
                    finally:
                        try:
                            os.unlink(tmp_name)
                        except FileNotFoundError:
                            pass
            return file_path
        except OSError as exc:
            if attempts >= 3:
                raise
            time.sleep(0.05)


def load_stats(path: str | Path = "data/season_stats.json") -> Dict[str, Any]:
    file_path = _resolve_path(path)
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    return {
        "players": data.get("players", {}),
        "teams": data.get("teams", {}),
        "history": data.get("history", []),
    }


def save_stats(
    players: Iterable[Any],
    teams: Iterable[Any],
    path: str | Path = "data/season_stats.json",
) -> None:
    """Persist season statistics with an inter-process file lock."""

    file_path = _resolve_path(path)
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # ``"w"`` would truncate the file and prevent other processes from
    # opening it on Windows, leading to ``PermissionError`` when multiple
    # simulations attempt to write stats concurrently.  Using ``"a+"`` keeps
    # the file length intact and allows concurrent opens while the explicit
    # lock below serializes writes.
    with lock_path.open("a+") as lock_file:
        with _locked(lock_file):
            stats = load_stats(file_path)
            player_stats = stats.get("players", {})
            for player in players:
                season = getattr(player, "season_stats", None)
                if season:
                    player_stats[player.player_id] = season
            team_stats = stats.get("teams", {})
            for team in teams:
                season = getattr(team, "season_stats", None)
                if season:
                    team_stats[team.team_id] = season
            history = stats.get("history", [])

            # If sharding is enabled, write a bounded per-day snapshot instead of
            # appending to the canonical history list. This keeps per-game writes
            # small while preserving the ability to merge a full history later.
            # Daily sharding is enabled by default to keep writes bounded.
            if _truthy_env("PB_SHARD_HISTORY", True):
                try:
                    write_daily_snapshot(players, teams)
                except Exception:
                    # Best effort: even if sharded write fails, continue to update
                    # canonical players/teams below to avoid losing state.
                    pass
            else:
                # Optional: disable or cap history growth to avoid ever-growing writes.
                disable_history = _truthy_env("PB_DISABLE_HISTORY", False)
                if not disable_history:
                    history.append(
                        {
                            "players": {
                                p.player_id: getattr(p, "season_stats", {}) for p in players
                            },
                            "teams": {
                                t.team_id: getattr(t, "season_stats", {}) for t in teams
                            },
                            "date": _current_sim_date_str(),
                        }
                    )
                    # Cap history length if PB_HISTORY_MAX is set (non-negative int).
                    max_hist_raw = os.getenv("PB_HISTORY_MAX") or os.getenv(
                        "SEASON_HISTORY_MAX"
                    )
                    if max_hist_raw is not None:
                        try:
                            max_hist = int(str(max_hist_raw).strip())
                            if max_hist >= 0:
                                history = history[-max_hist:] if max_hist > 0 else []
                        except ValueError:
                            # Ignore invalid values
                            pass
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "players": player_stats,
                        "teams": team_stats,
                        "history": history,
                    },
                    f,
                    indent=2,
                )
