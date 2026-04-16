"""Cross-process file locking so the sidecar and the legacy PyQt app can
safely share the same ``%LOCALAPPDATA%/NexGen-BBPro/data`` directory.

Uses ``portalocker`` when available (preferred) and falls back to ``msvcrt``
on Windows / ``fcntl`` on POSIX so the sidecar still functions in environments
where portalocker hasn't been installed yet.

Use :func:`locked_write` for atomic writes (write to ``<path>.tmp``, fsync,
rename) under an exclusive lock; use :func:`locked_read` for shared reads.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import IO, Iterator

try:  # pragma: no cover - optional dep
    import portalocker  # type: ignore

    _HAS_PORTALOCKER = True
except Exception:  # pragma: no cover
    portalocker = None  # type: ignore
    _HAS_PORTALOCKER = False


@contextlib.contextmanager
def _lock(handle: IO[bytes], *, exclusive: bool) -> Iterator[None]:
    if _HAS_PORTALOCKER:
        flag = portalocker.LOCK_EX if exclusive else portalocker.LOCK_SH
        portalocker.lock(handle, flag)
        try:
            yield
        finally:
            portalocker.unlock(handle)
        return

    if sys.platform == "win32":  # pragma: no cover - platform specific
        import msvcrt

        # msvcrt has no shared-lock concept; fall back to exclusive.
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        return

    import fcntl  # pragma: no cover

    fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked_read(path: Path) -> Iterator[bytes]:
    """Yield the raw bytes of *path* under a shared lock."""

    path = Path(path)
    with path.open("rb") as handle:
        with _lock(handle, exclusive=False):
            yield handle.read()


def locked_write(path: Path, data: bytes) -> None:
    """Atomically write *data* to *path* under an exclusive lock.

    Uses temp-file + ``os.replace`` so concurrent readers never see a partial
    file. The exclusive lock is held on a sibling ``.lock`` file so we don't
    have to juggle locking the target across the rename.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    # Ensure the lock file exists.
    lock_path.touch(exist_ok=True)

    with lock_path.open("rb+") as lock_handle:
        with _lock(lock_handle, exclusive=True):
            with tmp_path.open("wb") as out:
                out.write(data)
                out.flush()
                try:
                    os.fsync(out.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, path)
