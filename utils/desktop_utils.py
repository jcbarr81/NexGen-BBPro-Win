"""Desktop integration helpers (open files/folders with OS defaults)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path_in_file_manager(path: Path) -> None:
    """Open *path* using the system's default file manager integration."""

    target = Path(path)
    if os.name == "nt":
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "", str(target)])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target)])


def open_containing_folder(path: Path | str) -> Path:
    """Open the folder containing *path* (or *path* itself when it is a folder)."""

    raw_path = Path(path).expanduser()
    target = raw_path if raw_path.is_dir() else raw_path.parent
    if not str(target).strip():
        raise FileNotFoundError("No folder available for the provided path.")
    if not target.exists():
        raise FileNotFoundError(f"Folder does not exist: {target}")
    open_path_in_file_manager(target)
    return target


__all__ = ["open_containing_folder", "open_path_in_file_manager"]
