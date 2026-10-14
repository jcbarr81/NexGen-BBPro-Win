"""One lock for a league's ``players.csv``: every writer and the 8.0.0 move.

``save_players`` REPLACES the file and a draft pick APPENDS to it; the move
to rating scale 2 (``services.rating_scale_migration``) reads the whole
file, converts it and replaces it. A write landing between the move's read
and its replace would be lost (the move writes what it read). So every
writer of ``players.csv`` -- ``utils.player_writer.save_players_to_csv``,
``services.players_repository.update_players`` (read, merge and write as
one), ``services.draft_assignment._append_players`` -- and the move itself
hold this lock while they work.

The lock is two layers:

* a re-entrant lock per file inside the process (a writer called while the
  same thread already holds it does not wait for itself);
* a lock FILE beside ``players.csv`` (``.players.csv.lock``) across
  processes, holding ``{"pid", "host", "at"}``. A lock file is STALE -- and
  is broken, with a log line -- when its owner is a process on this host
  that is no longer running, or when it has not been refreshed for
  :data:`STALE_SECONDS` (the holder refreshes it, :func:`heartbeat`). A move
  takes seconds, an ordinary save milliseconds.

:func:`players_file_lock` waits ``timeout`` seconds for a live holder and
then raises :class:`PlayersFileBusy`. Callers that hold another lock while
they ask (the rating centres' lock) pass a short timeout, so they never
block the process for long; the move then makes its game retry instead of
deciding anything.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator

__all__ = [
    "LOCK_SUFFIX",
    "PlayersFileBusy",
    "STALE_SECONDS",
    "heartbeat",
    "lock_path_for",
    "players_file_lock",
]

_LOGGER = logging.getLogger(__name__)
LOCK_SUFFIX = ".lock"
# A lock file nobody has refreshed for this long belongs to a dead holder.
STALE_SECONDS = 60.0
DEFAULT_TIMEOUT = 30.0

_LOCAL: Dict[str, threading.RLock] = {}
_HELD: Dict[str, int] = {}
_REGISTRY_LOCK = threading.Lock()


class PlayersFileBusy(RuntimeError):
    """Another live process holds the league's players-file lock."""


def lock_path_for(players_path: Path | str) -> Path:
    path = Path(players_path)
    return path.with_name(f".{path.name}{LOCK_SUFFIX}")


def _key(players_path: Path | str) -> str:
    return str(Path(players_path).resolve(strict=False))


@contextmanager
def players_file_lock(
    players_path: Path | str, *, timeout: float = DEFAULT_TIMEOUT
) -> Iterator[Path]:
    """Hold the lock of ``players_path`` (re-entrant within a thread)."""

    key = _key(players_path)
    with _REGISTRY_LOCK:
        local = _LOCAL.setdefault(key, threading.RLock())
    if not local.acquire(timeout=max(0.0, timeout)):
        raise PlayersFileBusy(f"{players_path} is being written by another thread")
    lock_file = lock_path_for(players_path)
    try:
        outermost = _HELD.get(key, 0) == 0
        if outermost:
            _acquire_file(lock_file, timeout)
        _HELD[key] = _HELD.get(key, 0) + 1
        try:
            yield lock_file
        finally:
            _HELD[key] -= 1
            if _HELD[key] == 0:
                del _HELD[key]
                try:
                    lock_file.unlink()
                except OSError:
                    pass
    finally:
        local.release()


def heartbeat(lock_file: Path) -> None:
    """Refresh a held lock file, so a long holder is never taken for dead."""

    try:
        os.utime(lock_file, None)
    except OSError:
        pass


def _acquire_file(lock_file: Path, timeout: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout)
    payload = json.dumps({"pid": os.getpid(), "host": _host(), "at": time.time()})
    while True:
        try:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            reason = _stale_reason(lock_file)
            if reason:
                _LOGGER.warning("breaking a stale players-file lock %s (%s)", lock_file, reason)
                try:
                    print(f"[players-lock] breaking stale {lock_file} ({reason})", flush=True)
                except Exception:  # pragma: no cover
                    pass
                try:
                    lock_file.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise PlayersFileBusy(
                    f"{lock_file.name} is held by a running process ({_describe(lock_file)})"
                ) from None
            time.sleep(0.05)
            continue
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        return


def _read_owner(lock_file: Path) -> dict:
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _describe(lock_file: Path) -> str:
    owner = _read_owner(lock_file)
    return f"pid {owner.get('pid', '?')} on {owner.get('host', '?')}"


def _stale_reason(lock_file: Path) -> str:
    """Why ``lock_file`` belongs to a dead holder, or "" while it is live."""

    try:
        age = time.time() - lock_file.stat().st_mtime
    except OSError:
        return "gone"  # released meanwhile: just try again
    if age > STALE_SECONDS:
        return f"not refreshed for {age:.0f}s"
    owner = _read_owner(lock_file)
    pid = owner.get("pid")
    if owner.get("host") == _host() and isinstance(pid, int):
        if pid != os.getpid() and not _pid_alive(pid):
            return f"pid {pid} is not running on this host"
    elif not owner and age > 2.0:
        # Not a lock this module wrote (an older build's, or a torn write).
        return "no owner recorded"
    return ""


def _host() -> str:
    try:
        return socket.gethostname()
    except OSError:  # pragma: no cover
        return "?"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
