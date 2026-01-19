"""Build an executable for NexGen-BBPro using PyInstaller."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import PyInstaller.__main__


_MINIMAL_DATA_FILES = (
    "names.csv",
    "ballparks.py",
    "draft_config.json",
    "injury_catalog.json",
)
_MINIMAL_DATA_DIRS = (
    "MLB_avg",
    "parks",
)


def _safe_copy(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _safe_copytree(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dest)


def _stage_runtime_data(base_dir: Path, staging_root: Path) -> Path:
    data_root = staging_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)

    for name in _MINIMAL_DATA_FILES:
        _safe_copy(base_dir / "data" / name, data_root / name)

    for name in _MINIMAL_DATA_DIRS:
        _safe_copytree(base_dir / "data" / name, data_root / name)

    (data_root / "users.txt").write_text("admin,pass,admin,\n", encoding="utf-8")
    return data_root


def main() -> None:
    """Run PyInstaller to create a standalone executable."""
    base_dir = Path(__file__).resolve().parent
    # Bundle only the minimal runtime assets needed for UI and boxscores.
    # Large generated avatar PNGs are excluded; a default avatar + templates
    # are included so users can regenerate on demand.
    data_dirs = [
        "logo",
        "assets",
        "samples",
        "config",
        os.path.join("ui", "icons"),
    ]
    data_files = [
        ("VERSION", "."),
        (
            os.path.join("images", "avatars", "default.png"),
            os.path.join("images", "avatars"),
        ),
        (
            os.path.join("images", "avatars", "Template"),
            os.path.join("images", "avatars", "Template"),
        ),
        (os.path.join("playbalance", "PBINI.txt"), "playbalance"),
        (os.path.join("playbalance", "draft_pool.csv"), "playbalance"),
    ]
    # --noconsole prevents a console window from appearing when the app runs.
    # Use --onedir so runtime data stays writable in the install folder.
    params = [
        "main.py",
        "--onedir",
        "--name",
        "NexGen-BBPro",
        "--noconsole",
        "--icon",
        os.path.join("packaging", "NexGen-BBPro.ico"),
        "--hidden-import",
        "ui.admin_dashboard",
        "--hidden-import",
        "ui.owner_dashboard",
        "--collect-submodules",
        "ui.admin_dashboard",
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        staged_data = _stage_runtime_data(base_dir, Path(temp_dir))
        params += ["--add-data", f"{staged_data}{os.pathsep}data"]
        for d in data_dirs:
            params += ["--add-data", f"{d}{os.pathsep}{d}"]
        for src, dest in data_files:
            params += ["--add-data", f"{src}{os.pathsep}{dest}"]
        PyInstaller.__main__.run(params)


if __name__ == "__main__":
    main()
