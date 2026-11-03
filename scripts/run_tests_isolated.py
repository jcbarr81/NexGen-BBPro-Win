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

``-j N`` (8.8.3) runs N files at a time. Many tests write into the checkout's
``data/`` dir, so files cannot share one checkout: the driver snapshots the
working tree (uncommitted and untracked files included, ``.gitignore``
respected, stray ``data/leagues`` dirs left out; your index is not touched),
checks the snapshot out into N fresh git worktrees under the temp dir, feeds
each worktree the next file (slowest first, by the previous run's times),
restores that worktree's ``data/`` after every file, and removes the worktrees
at the end. The worktrees are clean, so the false failures a main checkout's
stray ``data/leagues`` dirs cause do not appear.

Usage:
    python scripts/run_tests_isolated.py                # all files, one at a time
    python scripts/run_tests_isolated.py -j 12          # all files, 12 at a time (~3.5 min)
    python scripts/run_tests_isolated.py -k trade       # only files matching
    python scripts/run_tests_isolated.py --list         # list files, don't run
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
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

_GIT = ["git", "-c", "core.longpaths=true", "-c", "gc.auto=0"]


def _git(*args: str, cwd: Path = ROOT, env: dict | None = None) -> str:
    proc = subprocess.run(
        [*_GIT, *args], cwd=cwd, env=env, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _restore_data_dir(root: Path = ROOT) -> None:
    subprocess.run([*_GIT, "checkout", "--", "data"], cwd=root, capture_output=True)
    subprocess.run([*_GIT, "clean", "-fdq", "--", "data/leagues"], cwd=root, capture_output=True)


def _discover(filter_substr: str | None) -> list[Path]:
    files = sorted(TESTS.glob("test_*.py"))
    files = [f for f in files if f.name not in SKIP_FILES]
    if filter_substr:
        files = [f for f in files if filter_substr in f.name]
    return files


def _run_file(rel: str, cwd: Path, env: dict, extra: list[str] = ()) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", rel, "-q", "-p", "no:cacheprovider",
         "-p", "no:warnings", "--no-header", *extra],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    _restore_data_dir(cwd)
    # Parse the last non-empty line, e.g. "12 passed, 1 xfailed in 0.5s".
    summary = ""
    for line in reversed(proc.stdout.splitlines()):
        if line.strip():
            summary = line.strip()
            break
    return proc.returncode == 0, summary


def _report(files_total: int, failed: list[str], start: float) -> int:
    dur = time.time() - start
    print("\n" + "=" * 70)
    print(f"{files_total - len(failed)}/{files_total} files green in {dur:.0f}s")
    if failed:
        print(f"\n{len(failed)} file(s) FAILED:")
        for rel in sorted(failed):
            print(f"  - {rel}")
        return 1
    print("ALL FILES GREEN")
    return 0


def _run_serial(files: list[Path], env: dict) -> int:
    failed: list[str] = []
    start = time.time()
    for idx, f in enumerate(files, 1):
        rel = f.relative_to(ROOT).as_posix()
        ok, summary = _run_file(rel, ROOT, env)
        marker = "ok  " if ok else "FAIL"
        print(f"[{idx:3}/{len(files)}] {marker}  {rel:<52} {summary}")
        if not ok:
            failed.append(rel)
    return _report(len(files), failed, start)


# --- parallel (-j N) ---------------------------------------------------------


def _durations_path() -> Path:
    common = Path(_git("rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = ROOT / common
    return common / "nexgen-test-durations.json"


def _load_durations() -> dict[str, float]:
    try:
        return {str(k): float(v) for k, v in json.loads(_durations_path().read_text()).items()}
    except Exception:
        return {}


def _save_durations(durations: dict[str, float]) -> None:
    try:
        merged = {**_load_durations(), **durations}
        _durations_path().write_text(json.dumps(merged, indent=1, sort_keys=True))
    except Exception:
        pass


def _snapshot_commit() -> str:
    """A commit of the working tree as it is now, made with a throwaway index
    so the real one is untouched. Stray ``data/leagues`` dirs a run left in
    this checkout stay out (tracked edits there are kept)."""

    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / "index"))
        _git("read-tree", "HEAD", env=env)
        _git("add", "-A", "--", ".", ":(exclude)data/leagues", env=env)
        _git("add", "-u", "--", "data/leagues", env=env)
        tree = _git("write-tree", env=env)
    return _git("commit-tree", tree, "-p", "HEAD", "-m", "run_tests_isolated snapshot")


def _remove_tree(path: Path) -> None:
    def _writable(func, p, _exc):
        # Windows: git marks object files read-only. S_IWRITE alone is right
        # here (Windows only honours the read-only bit); on Linux it would
        # also strip a directory's execute bit, so only use it on Windows.
        if os.name == "nt":
            os.chmod(p, stat.S_IWRITE)
        func(p)

    try:
        shutil.rmtree(path, onerror=_writable)
    except Exception:
        pass


def _run_parallel(files: list[Path], env: dict, jobs: int, work_root: Path | None) -> int:
    start = time.time()
    base = Path(work_root) if work_root else Path(tempfile.gettempdir()) / "nexgen-test-shards"
    base = base / f"run-{os.getpid()}"
    base.mkdir(parents=True, exist_ok=True)

    print(f"Snapshotting the working tree into {jobs} worktrees under {base} ...")
    commit = _snapshot_commit()
    trees: list[Path] = [base / f"w{i}" for i in range(jobs)]
    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(
                lambda wt: _git("worktree", "add", "--detach", "-q", str(wt), commit),
                trees,
            ))
        print(f"Ready in {time.time() - start:.0f}s; running {len(files)} files.\n")

        known = _load_durations()
        rels = [f.relative_to(ROOT).as_posix() for f in files]
        # Slowest first so a long file never starts last; files with no time
        # yet go first too (they may be slow).
        rels.sort(key=lambda r: -known.get(r, 1e9))
        work: "queue.Queue[str]" = queue.Queue()
        for rel in rels:
            work.put(rel)

        lock = threading.Lock()
        failed: list[str] = []
        durations: dict[str, float] = {}
        done = [0]

        def _worker(wt: Path, slot: int) -> None:
            # Each worker gets its own pytest basetemp: pytest prunes old
            # numbered temp dirs, which would delete a neighbour's in use.
            basetemp = base / f"tmp{slot}"
            while True:
                try:
                    rel = work.get_nowait()
                except queue.Empty:
                    return
                t0 = time.time()
                ok, summary = _run_file(rel, wt, env, ["--basetemp", str(basetemp)])
                with lock:
                    durations[rel] = time.time() - t0
                    done[0] += 1
                    if not ok:
                        failed.append(rel)
                    marker = "ok  " if ok else "FAIL"
                    print(f"[{done[0]:3}/{len(rels)}] {marker}  {rel:<52} {summary}",
                          flush=True)

        threads = [
            threading.Thread(target=_worker, args=(wt, i), daemon=True)
            for i, wt in enumerate(trees)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        _save_durations(durations)
        return _report(len(rels), failed, start)
    finally:
        for wt in trees:
            subprocess.run([*_GIT, "worktree", "remove", "--force", str(wt)],
                           cwd=ROOT, capture_output=True)
        _remove_tree(base)
        subprocess.run([*_GIT, "worktree", "prune"], cwd=ROOT, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-k", dest="filter", default=None, help="only run files whose name contains this substring")
    parser.add_argument("--list", action="store_true", help="list the files that would run and exit")
    parser.add_argument("-j", "--jobs", type=int, default=1,
                        help="files to run at a time, each in its own temporary worktree (default 1: in place)")
    parser.add_argument("--work-root", default=None,
                        help="where -j puts its worktrees (default: the system temp dir)")
    args = parser.parse_args()

    files = _discover(args.filter)
    if args.list:
        for f in files:
            print(f.relative_to(ROOT).as_posix())
        print(f"\n{len(files)} files")
        return 0

    env = dict(os.environ, PYTHONHASHSEED="0")
    jobs = max(1, min(args.jobs, len(files) or 1))
    if jobs == 1:
        return _run_serial(files, env)
    return _run_parallel(files, env, jobs, args.work_root)


if __name__ == "__main__":
    raise SystemExit(main())
