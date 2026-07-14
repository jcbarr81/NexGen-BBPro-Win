"""Shared mtime-keyed parse cache (S1-05, deep_review_plan.md).

Generalizes the token pattern from ``utils.player_loader``: a parsed value is
cached against the (mtime_ns, size) of the file(s) it was derived from and
reused until any of them changes on disk. This kills the "re-read the same
CSV/JSON on every call" pattern that made dashboard requests do dozens of
full-file parses.

IMPORTANT: cached values are SHARED between callers. Only route read-only
consumers through this cache — a caller that mutates the returned object
would poison every other reader. Mutating code paths must keep using their
uncached loaders.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Iterable

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple, Any]] = {}
_MAX_ENTRIES = 256


def file_token(path: Path) -> tuple:
    """(resolved, mtime_ns, size) — or (resolved, None, None) if missing."""
    resolved = str(Path(path).resolve(strict=False))
    try:
        stat = Path(path).stat()
    except OSError:
        return (resolved, None, None)
    mtime_ns = getattr(stat, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat.st_mtime * 1_000_000_000)
    return (resolved, mtime_ns, stat.st_size)


def cached_read(
    key: str,
    paths: Iterable[Path],
    loader: Callable[[], Any],
) -> Any:
    """Return ``loader()``'s result, cached until any of *paths* changes.

    *key* namespaces independent caches that watch the same files. The
    loader runs outside the lock (parse work must not serialize readers);
    concurrent misses may parse twice — last write wins, both are correct.
    """

    import os

    if str(os.getenv("PB_DISABLE_FILE_CACHE", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return loader()
    token = tuple(file_token(p) for p in paths)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == token:
            return hit[1]
    value = loader()
    with _LOCK:
        if len(_CACHE) >= _MAX_ENTRIES:
            _CACHE.clear()  # crude but bounded; refills on demand
        _CACHE[key] = (token, value)
    return value


def invalidate(key_prefix: str | None = None) -> None:
    """Drop cached entries (all, or those whose key starts with the prefix)."""
    with _LOCK:
        if key_prefix is None:
            _CACHE.clear()
        else:
            for key in [k for k in _CACHE if k.startswith(key_prefix)]:
                _CACHE.pop(key, None)
