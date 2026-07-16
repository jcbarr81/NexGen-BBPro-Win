#!/usr/bin/env python3
"""Run the test suite with per-file process isolation (green gate).

This repo's tests share a lot of process-global state (the active ``data/``
league dir, module-level singletons/caches, and several tests that
``importlib.reload`` modules — which breaks later monkeypatches). That makes a
single ``pytest`` invocation flaky across files even though **every file passes
on its own**. Windows has no ``os.fork``, so pytest-forked / true per-test
isolation isn't available.

This driver runs each ``tests/test_*.py`` file in its own pytest **subprocess**
(a fresh interpreter → no cross-file leakage) with ``PYTHONHASHSEED=0`` for
determinism, restores the shared ``data/`` dir between files, and aggregates the
results. Exit code is non-zero if any file fails — use it as the green gate.

Usage:
    python scripts/run_tests_isolated.py                # all test files
    python scripts/run_tests_isolated.py -k trade       # only files matching
    python scripts/run_tests_isolated.py --list         # list files, don't run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# Files that require an explicit opt-in env and are intentionally not part of the
# default green gate.
SKIP_FILES = {
    "test_auto_tune_solver.py",  # archived legacy engine (PB_ALLOW_LEGACY_ENGINE)
    "test_build_exe.py",         # PyInstaller packaging, not a runtime concern
}


def _restore_data_dir() -> None:
    subprocess.run(["git", "checkout", "--", "data"], cwd=ROOT, capture_output=True)
    subprocess.run(["git", "clean", "-fdq", "--", "data/leagues"], cwd=ROOT, capture_output=True)


def _discover(filter_substr: str | None) -> list[Path]:
    files = sorted(TESTS.glob("test_*.py"))
    files = [f for f in files if f.name not in SKIP_FILES]
    if filter_substr:
        files = [f for f in files if filter_substr in f.name]
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-k", dest="filter", default=None, help="only run files whose name contains this substring")
    parser.add_argument("--list", action="store_true", help="list the files that would run and exit")
    args = parser.parse_args()

    files = _discover(args.filter)
    if args.list:
        for f in files:
            print(f.relative_to(ROOT).as_posix())
        print(f"\n{len(files)} files")
        return 0

    env = dict(os.environ, PYTHONHASHSEED="0")
    failed: list[str] = []
    total_pass = total_fail = total_skip = total_xfail = 0
    start = time.time()

    for idx, f in enumerate(files, 1):
        rel = f.relative_to(ROOT).as_posix()
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", rel, "-q", "-p", "no:cacheprovider",
             "-p", "no:warnings", "--no-header"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        _restore_data_dir()
        # Parse the last non-empty line, e.g. "12 passed, 1 xfailed in 0.5s".
        summary = ""
        for line in reversed(proc.stdout.splitlines()):
            if line.strip():
                summary = line.strip()
                break
        ok = proc.returncode == 0
        marker = "ok  " if ok else "FAIL"
        print(f"[{idx:3}/{len(files)}] {marker}  {rel:<52} {summary}")
        if not ok:
            failed.append(rel)

    dur = time.time() - start
    print("\n" + "=" * 70)
    print(f"{len(files) - len(failed)}/{len(files)} files green in {dur:.0f}s")
    if failed:
        print(f"\n{len(failed)} file(s) FAILED:")
        for rel in failed:
            print(f"  - {rel}")
        return 1
    print("ALL FILES GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
