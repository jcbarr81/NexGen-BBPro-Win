"""Write a text file so readers never see it half-written.

``open(path, "w")`` truncates the file first and fills it as rows are
written, so a reader in another process (a parallel-day sim worker loading
``players.csv``, say) can see an empty or partial file -- and a cut that lands
on a row boundary parses cleanly, silently dropping players. The writer here
fills a temporary file in the same directory and swaps it in with
``os.replace``, which readers see as all-old or all-new.

On Windows the swap fails with ``PermissionError`` while another process has
the target open (or it is read-only); it is retried with a short backoff and,
as a last resort, the finished temp file is copied over the target in place
(the old behaviour) rather than losing the write.
"""

from __future__ import annotations

import os
import shutil
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

__all__ = ["atomic_text_writer"]

#: Backoff (seconds) between ``os.replace`` attempts; ~1.5s in all.
_REPLACE_BACKOFF = (0.01, 0.02, 0.04, 0.08, 0.15, 0.25, 0.4, 0.5)


def _temp_path(path: Path) -> Path:
    return path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )


def _copy_mode(src: Path, dst: Path) -> None:
    """Give the new file the old one's permissions (kept writable)."""

    try:
        mode = stat.S_IMODE(os.stat(src).st_mode)
        os.chmod(dst, mode | stat.S_IWUSR)
    except OSError:
        pass


def _make_writable(path: Path) -> None:
    try:
        if path.exists() and not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWUSR)
    except OSError:
        pass


def _replace(tmp: Path, path: Path) -> None:
    # Windows will not replace a read-only file; the in-place write this
    # replaces could (callers chmod the target first), so clear the flag.
    _make_writable(path)
    for delay in _REPLACE_BACKOFF + (None,):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if delay is None:
                break
            time.sleep(delay)
    # Last resort: an in-place copy (a reader may see it mid-write, as
    # before) beats dropping the data.
    shutil.copyfile(tmp, path)


@contextmanager
def atomic_text_writer(
    path: str | Path,
    *,
    newline: str | None = "",
    encoding: str | None = None,
) -> Iterator[IO[str]]:
    """Yield a text handle; on a clean exit its content replaces ``path``.

    The handle writes a temp file beside ``path``. If the ``with`` body
    raises, the temp file is removed and ``path`` is left untouched.
    ``newline`` / ``encoding`` are passed to :func:`open` unchanged (the
    defaults match ``open(path, "w", newline="")``).
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temp_path(target)
    try:
        with open(tmp, mode="w", newline=newline, encoding=encoding) as handle:
            yield handle
        if target.exists():
            _copy_mode(target, tmp)
        _replace(tmp, target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
