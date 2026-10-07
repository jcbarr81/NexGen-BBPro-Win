"""Release 3 fix round: stray physics rest-state files never survive a run.

Dated sims persist ``physics_usage.json`` in the league they ran against --
including the tracked league folders under ``data/leagues``. A hidden copy
there was loaded by the next run, so fatigue built up across test runs
(review finding A-rest, tests/conftest.py). The session cleanup must remove
every copy under ``data/``, and git must show a stray inside a league folder
(so ``git status`` reports it and ``git clean -fdq data/leagues`` removes it).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import tests.conftest as conftest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_session_cleanup_removes_every_stray_usage_file(tmp_path):
    data = tmp_path / "data"
    strays = [
        data / "physics_usage.json",
        data / "leagues" / "cbl" / "data" / "physics_usage.json",
        data / "leagues" / "other" / "data" / "physics_usage.json",
        data / "calibration_league" / "physics_usage.json",
    ]
    keep = data / "leagues" / "cbl" / "data" / "pitcher_recovery.json"
    for path in strays + [keep]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    conftest._remove_stray_usage_files(tmp_path)

    assert [p for p in strays if p.exists()] == []
    assert keep.exists()


def test_session_cleanup_tolerates_a_missing_data_dir(tmp_path):
    conftest._remove_stray_usage_files(tmp_path)  # no data/ at all


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_gitignore_shows_strays_inside_league_folders():
    def _ignored(rel: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", rel],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0

    # The base data dir's file (a desktop league) stays ignored ...
    assert _ignored("data/physics_usage.json")
    # ... but a stray inside a tracked league folder must be visible, so
    # git status reports it and the documented git clean removes it.
    assert not _ignored("data/leagues/cbl/data/physics_usage.json")
