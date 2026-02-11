from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from utils.path_utils import get_data_dir, resolve_app_path


def _recovery_root() -> Path:
    root = get_data_dir() / "recovery"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _relative_to_data(path: Path) -> Path | None:
    data_dir = get_data_dir().resolve(strict=False)
    try:
        return path.resolve(strict=False).relative_to(data_dir)
    except ValueError:
        return None


def recovery_path_for_data_file(path: str | Path) -> Path:
    """Return the recovery path matching the provided data file."""
    data_path = resolve_app_path(path)
    relative = _relative_to_data(data_path)
    root = _recovery_root()
    if relative is not None:
        return root / relative
    safe_name = data_path.name or "recovery"
    return root / "misc" / safe_name


def needs_recovery(path: str | Path) -> bool:
    """Return True when a recovery file exists and is newer than saved data."""
    data_path = resolve_app_path(path)
    recovery_path = recovery_path_for_data_file(path)
    if not recovery_path.exists():
        return False
    if not data_path.exists():
        return True
    try:
        return recovery_path.stat().st_mtime > data_path.stat().st_mtime
    except OSError:
        return True


def clear_recovery(path: str | Path) -> None:
    """Remove any recovery file for the provided data file path."""
    recovery_path = recovery_path_for_data_file(path)
    try:
        recovery_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return

    root = _recovery_root()
    parent = recovery_path.parent
    while parent != root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _atomic_write_text(path: Path, rows: Iterable[Sequence[str]], header: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if header:
                writer.writerow(list(header))
            for row in rows:
                writer.writerow(list(row))
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def write_recovery_csv(
    data_path: str | Path,
    rows: Iterable[Sequence[str]],
    *,
    header: Sequence[str] | None = None,
) -> Path:
    """Persist CSV recovery data alongside the canonical data file."""
    recovery_path = recovery_path_for_data_file(data_path)
    _atomic_write_text(recovery_path, rows, header=header)
    return recovery_path


__all__ = [
    "clear_recovery",
    "needs_recovery",
    "recovery_path_for_data_file",
    "write_recovery_csv",
]
