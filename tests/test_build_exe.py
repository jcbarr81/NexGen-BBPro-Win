from __future__ import annotations

import os
from pathlib import Path

import build_exe


def _collect_add_data_args(params: list[str]) -> list[str]:
    add_data: list[str] = []
    for index, value in enumerate(params):
        if value != "--add-data":
            continue
        if index + 1 < len(params):
            add_data.append(params[index + 1])
    return add_data


def test_build_exe_bundles_ui_resources(monkeypatch):
    captured: dict[str, list[str]] = {}

    def _fake_stage_runtime_data(_base_dir: Path, staging_root: Path) -> Path:
        return staging_root / "data"

    def _fake_run(params: list[str]) -> None:
        captured["params"] = list(params)

    monkeypatch.setattr(build_exe, "_stage_runtime_data", _fake_stage_runtime_data)
    monkeypatch.setattr(build_exe.PyInstaller.__main__, "run", _fake_run)

    build_exe.main()

    params = captured.get("params", [])
    add_data_args = _collect_add_data_args(params)
    assert (
        f"{os.path.join('ui', 'resources')}{os.pathsep}"
        f"{os.path.join('ui', 'resources')}"
    ) in add_data_args
