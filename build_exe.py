"""Build an executable for NexGen-BBPro using PyInstaller."""

from __future__ import annotations

import os
import PyInstaller.__main__


def main() -> None:
    """Run PyInstaller to create a standalone executable."""
    # Bundle only the minimal runtime assets needed for UI and boxscores.
    # Large generated avatar PNGs are excluded; a default avatar + templates
    # are included so users can regenerate on demand.
    data_dirs = ["data", "logo", "assets", "samples"]
    data_files = [
        (os.path.join("images", "avatars", "default.png"), os.path.join("images", "avatars")),
        (os.path.join("images", "avatars", "Template"), os.path.join("images", "avatars", "Template")),
    ]
    # --noconsole prevents a console window from appearing when the app runs
    params = [
        "main.py",
        "--onefile",
        "--name",
        "NexGen-BBPro",
        "--noconsole",
    ]
    for d in data_dirs:
        params += ["--add-data", f"{d}{os.pathsep}{d}"]
    for src, dest in data_files:
        params += ["--add-data", f"{src}{os.pathsep}{dest}"]
    PyInstaller.__main__.run(params)


if __name__ == "__main__":
    main()
