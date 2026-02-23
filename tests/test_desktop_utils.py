from __future__ import annotations

from pathlib import Path

import pytest

from utils import desktop_utils


def test_open_containing_folder_for_file_path(monkeypatch, tmp_path: Path) -> None:
    export_file = tmp_path / "exports" / "report.zip"
    export_file.parent.mkdir(parents=True, exist_ok=True)
    export_file.write_text("ok", encoding="utf-8")

    opened: list[Path] = []
    monkeypatch.setattr(
        desktop_utils,
        "open_path_in_file_manager",
        lambda path: opened.append(Path(path)),
    )

    folder = desktop_utils.open_containing_folder(export_file)

    assert folder == export_file.parent
    assert opened == [export_file.parent]


def test_open_containing_folder_for_directory(monkeypatch, tmp_path: Path) -> None:
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    opened: list[Path] = []
    monkeypatch.setattr(
        desktop_utils,
        "open_path_in_file_manager",
        lambda path: opened.append(Path(path)),
    )

    folder = desktop_utils.open_containing_folder(exports_dir)

    assert folder == exports_dir
    assert opened == [exports_dir]


def test_open_containing_folder_raises_for_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "not_there" / "output.zip"
    with pytest.raises(FileNotFoundError):
        desktop_utils.open_containing_folder(missing)
