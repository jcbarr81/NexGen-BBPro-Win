"""Run the app on a fast local working copy, persisting to a slow durable mount.

Cloud Run mounts the league-data GCS bucket as a FUSE filesystem. Operating the
simulator directly on it is slow: a single day-sim performs hundreds of tiny
reads/writes and every one is a network round-trip. Instead we:

* on startup, **pull** the active data from the durable mount
  (``NEXGEN_SYNC_REMOTE``) into a fast local dir (``NEXGEN_DATA_ROOT``);
* serve every request off that local dir (native disk speed);
* after each *mutating* request, **push** the changed files back to the durable
  mount so nothing is lost — and **delete** from the mount anything removed
  locally (e.g. a deleted league), so deletions persist too.

All transfers copy/delete files **concurrently** (a thread pool): FUSE latency
is per-operation, so overlapping many of them turns a serial wall of round-trips
into a handful of parallel batches.

Activated only when ``NEXGEN_WORKING_COPY=1`` (set on Cloud Run). Local desktop
/ Electron / dev runs never set it, so this module is a complete no-op there.

Durability model (single-instance, ``max-instances=1``): writes are flushed to
the durable mount before the mutating request returns, so a client that sees
``200`` knows its change persisted. Background jobs push when they finish, and
a graceful shutdown (a deploy, an instance recycle) flushes whatever is left --
unless a background job is still mid-write, in which case it stands down rather
than push a half-written league. A crash mid-sim loses only the in-flight sim,
never the prior committed state.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

# Remote top-level entries we never need on the active node — skipping them keeps
# the startup pull small (bounded to the live footprint, not archives/backups).
# These are also never pulled into ``_synced``, so the delete pass can never touch
# them on the remote.
_SKIP_TOP_NAMES = {"system"}
_SKIP_LEAGUE_PREFIX = "legacy"

# FUSE ops are I/O-bound (GIL released during the syscall), so threads overlap
# the GCS round-trips effectively.
_WORKERS = 32

# Signature (mtime_ns, size) of every file as of its last successful sync --
# pulled down at startup or pushed up since -- keyed by posix path relative to
# the data root. A push copies every file whose current signature differs from
# (or is missing in) this map, and deletes on the remote anything recorded here
# that is gone locally.
#
# This used to be one "saved up to here" time cutoff: push whatever has an
# mtime after it. But a copy keeps its SOURCE's mtime (shutil.copy2/copytree),
# so a file copied to a new path -- the season-end archive, a cloned league, a
# roster-lock snapshot, a backup restored over a live file -- sat below the
# cutoff, was never pushed, and vanished at the next restart. Comparing per
# file catches any change, new path or not; a file whose copy fails keeps its
# old signature and is simply retried by the next push.
_synced: Dict[str, Tuple[int, int]] = {}

# Background jobs (sims, CPU free agency, avatar generation) writing to the
# working copy right now: name -> count. See ``background_writer``.
_busy: Dict[str, int] = {}
_busy_lock = threading.Lock()

# Serialize pushes so concurrent mutating requests don't race on _synced / the
# remote. Pushes are quick, so this is cheap insurance on a single instance.
_push_lock = threading.Lock()


def _emit(msg: str) -> None:
    # Print to stdout so it lands in Cloud Logging. The app's root logger writes
    # to a file under the (now local) data dir, which Cloud Run never sees.
    print(f"[working-copy] {msg}", flush=True)


def is_enabled() -> bool:
    return os.environ.get("NEXGEN_WORKING_COPY") == "1"


def _remote() -> Path:
    return Path(os.environ["NEXGEN_SYNC_REMOTE"])


def _local() -> Path:
    return Path(os.environ["NEXGEN_DATA_ROOT"])


def delete_league_remote(league_id: str) -> bool:
    """Permanently remove a league's data from the durable remote (GCS) AND the
    local working copy. Used by the super-admin platform delete — the automatic
    push delete-sync deliberately REFUSES to delete a league absent locally (the
    safety guard added after a data-loss bug), so deletions must be explicit.

    Returns True if anything was removed. No-op (returns False) when the working
    copy is disabled (local desktop), where the on-disk dir is the only copy and
    the caller's own delete already handled it.
    """
    import shutil

    if not is_enabled():
        return False
    league_id = str(league_id or "").strip()
    if not league_id or "/" in league_id or "\\" in league_id or league_id in {".", ".."}:
        raise ValueError(f"Unsafe league_id {league_id!r}")
    removed = False
    for root in (_remote(), _local()):
        target = root / "leagues" / league_id
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed = True
    # Forget any cached knowledge of this league so a later push won't trip over it.
    global _synced
    prefix = f"leagues/{league_id}/"
    _synced = {rel: sig for rel, sig in _synced.items() if not rel.startswith(prefix)}
    # (was `_log`, an undefined name — NameError on every super-admin delete)
    _emit(f"deleted league {league_id!r} from remote+local")
    return removed


# Critical per-league finance files that must never be clobbered by an EMPTY
# copy. A partially-hydrated working copy once let a finance read zero these, and
# the push then overwrote the real bucket data. This guard refuses to overwrite a
# non-empty one with an empty one (in either sync direction).
_CRITICAL_FINANCE_JSON = {"contracts.json", "team_financials.json"}


def _finance_json_is_empty(path: Path) -> bool:
    """True when a contracts/team_financials JSON carries no real data."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False  # unreadable → don't treat as a known-empty; don't block
    if not isinstance(data, dict):
        return False
    if path.name == "contracts.json":
        players = data.get("players")
        return not (isinstance(players, dict) and players)
    # team_financials.json: empty if no teams, or every team entry is all-zero.
    teams = data.get("teams")
    if not isinstance(teams, dict) or not teams:
        return True

    def _has_money(entry: object) -> bool:
        if not isinstance(entry, dict):
            return False
        for value in entry.values():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value:
                return True
            if isinstance(value, dict) and any(
                isinstance(v, (int, float)) and not isinstance(v, bool) and v
                for v in value.values()
            ):
                return True
        return False

    return not any(_has_money(entry) for entry in teams.values())


def _copy_one(pair: Tuple[Path, Path]) -> int:
    src, dst = pair
    try:
        # Never overwrite a non-empty critical finance file with an empty one.
        if (
            src.name in _CRITICAL_FINANCE_JSON
            and dst.exists()
            and dst.stat().st_size > 0
            and _finance_json_is_empty(src)
            and not _finance_json_is_empty(dst)
        ):
            _emit(
                f"skip empty-overwrite: {src.name} local is empty but remote has "
                f"data ({dst})"
            )
            return 1  # treated as handled so the sync cutoff still advances
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1
    except OSError as exc:
        _emit(f"copy failed {src} -> {dst}: {exc}")
        return 0


def _parallel_copy(pairs: Iterable[Tuple[Path, Path]]) -> int:
    pairs = list(pairs)
    if not pairs:
        return 0
    copied = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for result in ex.map(_copy_one, pairs):
            copied += result
    return copied


def _copy_each(pairs: List[Tuple[Path, Path]]) -> List[bool]:
    """Copy each pair concurrently; report, per pair, whether it landed."""
    if not pairs:
        return []
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        return [bool(result) for result in ex.map(_copy_one, pairs)]


def _signature(path: Path) -> Optional[Tuple[int, int]]:
    """(mtime_ns, size) of ``path``, or None if it can't be stat'ed."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _delete_one(path: Path) -> int:
    try:
        path.unlink()
        return 1
    except FileNotFoundError:
        return 0
    except OSError as exc:
        _emit(f"delete failed {path}: {exc}")
        return 0


def _parallel_delete(paths: Iterable[Path]) -> int:
    paths = list(paths)
    if not paths:
        return 0
    removed = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for result in ex.map(_delete_one, paths):
            removed += result
    return removed


def _iter_pull_files(remote: Path) -> Iterator[Path]:
    """Yield each file's path under the selective pull set (relative to remote)."""
    for entry in remote.iterdir():
        if entry.name in _SKIP_TOP_NAMES:
            continue
        if entry.name == "leagues" and entry.is_dir():
            for league in entry.iterdir():
                if league.name.startswith(_SKIP_LEAGUE_PREFIX):
                    continue
                for f in league.rglob("*"):
                    if f.is_file():
                        yield f.relative_to(remote)
        elif entry.is_dir():
            for f in entry.rglob("*"):
                if f.is_file():
                    yield f.relative_to(remote)
        elif entry.is_file():
            yield entry.relative_to(remote)


def bulk_pull() -> None:
    """Populate the local working copy from the durable remote mount.

    Selective: root-level seed files + non-legacy leagues, skipping
    archive/backup trees so cold-start stays quick.
    """
    global _synced
    remote, local = _remote(), _local()
    if not remote.exists():
        _emit(f"remote {remote} not present; skipping pull")
        return

    local.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rels = list(_iter_pull_files(remote))
    walk_s = time.time() - t0
    copied = _parallel_copy((remote / rel, local / rel) for rel in rels)
    # Record what is ACTUALLY in the local copy (not the intended pull set): a
    # file that failed to copy down must not later be seen as "deleted
    # locally" and wrongly removed from the durable remote.
    synced: Dict[str, Tuple[int, int]] = {}
    for p in local.rglob("*"):
        if p.is_file():
            sig = _signature(p)
            if sig is not None:
                synced[p.relative_to(local).as_posix()] = sig
    _synced = synced

    # The working copy is now populated (active-league pointer, registry, league
    # dirs). Invalidate path_utils' cached active-league data dir: it may have
    # been computed earlier (at import / before this pull) when the copy was
    # empty and no active league was resolvable, which pins get_data_dir() to the
    # data ROOT. Left stale, the app reads the wrong (root) users.txt, standings,
    # etc. The cache key doesn't reflect the pointer, so it won't self-heal.
    try:
        from utils import path_utils

        path_utils._DATA_DIR_CACHE.clear()
    except Exception:
        pass

    _emit(
        f"pulled {copied} files (walk {walk_s:.1f}s, total {time.time() - t0:.1f}s)"
    )


def _safe_league_id(value: object) -> Optional[str]:
    """Validate a league id for use as a path segment (never escapes leagues/)."""

    league_id = str(value or "").strip()
    if not league_id or "/" in league_id or "\\" in league_id or league_id in {".", ".."}:
        return None
    return league_id


def _request_league_id() -> Optional[str]:
    """League bound to the current request (X-League-Id ContextVar), if any."""

    try:
        from utils.path_utils import get_request_league

        return _safe_league_id(get_request_league())
    except Exception:
        return None


def push_changes(league_id: Optional[str] = None, *, full: bool = False) -> int:
    """Flush local changes back to the remote: copy new/modified files, and
    delete remote files that were removed locally.

    Walks only the *local* tree (fast disk); the changed/deleted sets are then
    the only things that cross the slow FUSE boundary, and they cross in parallel.
    A file is "changed" when its (mtime, size) differs from the one recorded at
    its last sync, or it has never been synced -- see ``_synced``.

    When the triggering request is bound to a league (cloud multi-tenant
    ``X-League-Id`` -- passed in by the middleware, or read from the same
    ContextVar ``utils.path_utils`` uses), the walk is SCOPED to that league's
    dir plus root-level files (direct children of the data root) plus any
    league dir never synced before (e.g. a league this request just created),
    instead of rglob-ing the entire multi-league root. Deletion sync is
    narrowed to the same scope so out-of-scope leagues are never touched; their
    pending changes stay pending until a push walks them. No league context, or
    ``full=True``, walks everything.
    """
    remote, local = _remote(), _local()
    if not local.exists():
        return 0

    league_id = None if full else (_safe_league_id(league_id) or _request_league_id())

    with _push_lock:
        t0 = time.time()
        # Scope of this push: None -> full walk; otherwise the set of league
        # ids whose trees we walk (plus root-level files, always in scope).
        scope_league_ids: Optional[Set[str]] = None
        if league_id and (local / "leagues" / league_id).is_dir():
            scope_league_ids = {league_id}
            # Also walk league dirs with NO synced files yet: a brand-new
            # league (possibly created by this very request while bound to
            # another league's context) exists only locally, and skipping it
            # would leave it un-persisted -- losing it on restart.
            known_league_ids = {
                rel.split("/", 2)[1] for rel in _synced if rel.startswith("leagues/")
            }
            try:
                leagues_root = local / "leagues"
                if leagues_root.is_dir():
                    for entry in leagues_root.iterdir():
                        if entry.is_dir() and entry.name not in known_league_ids:
                            scope_league_ids.add(entry.name)
            except OSError:
                pass

        current: Set[str] = set()
        changed: List[Tuple[Path, Path]] = []
        changed_sigs: List[Tuple[str, Tuple[int, int]]] = []

        def _scan(src: Path) -> None:
            if not src.is_file():
                return
            rel = src.relative_to(local).as_posix()
            current.add(rel)
            sig = _signature(src)
            if sig is None or _synced.get(rel) == sig:
                return
            changed.append((src, remote / rel))
            changed_sigs.append((rel, sig))

        if scope_league_ids is None:
            for src in local.rglob("*"):
                _scan(src)
        else:
            try:
                for entry in local.iterdir():
                    _scan(entry)
            except OSError:
                pass
            for lid in scope_league_ids:
                for src in (local / "leagues" / lid).rglob("*"):
                    _scan(src)

        # Record the signature seen at SCAN time, and only for copies that
        # landed. A file rewritten while the copy ran then differs next push
        # and is copied again (this is what once dropped the playoff bracket);
        # one whose copy failed -- the remote/FUSE briefly unavailable, the 503
        # that stranded a 2-hour avatar run -- is retried.
        landed = _copy_each(changed)
        pushed = sum(landed)
        for (rel, sig), ok in zip(changed_sigs, landed):
            if ok:
                _synced[rel] = sig

        # Anything we previously synced but is gone locally -> delete on remote,
        # EXCEPT files of a league no longer present locally AT ALL. That means
        # the league simply wasn't pulled this run (selective/partial pull), not
        # that it was deleted -- wiping it from the durable bucket is catastrophic
        # data loss (this is exactly how cbl/usabl were lost). Within-league file
        # deletions (the league dir is still present) are still propagated.
        if scope_league_ids is None:
            known_in_scope = set(_synced)
        else:
            # Only diff what this push actually walked: root-level files and
            # the in-scope league trees. Everything else is out of scope --
            # absent from ``current`` merely because we didn't walk it.
            known_in_scope = {
                rel
                for rel in _synced
                if "/" not in rel
                or (
                    rel.startswith("leagues/")
                    and rel.split("/", 2)[1] in scope_league_ids
                )
            }
        gone: List[str] = []
        for rel in known_in_scope - current:
            parts = rel.split("/")
            if (
                len(parts) >= 2
                and parts[0] == "leagues"
                and not (local / "leagues" / parts[1]).is_dir()
            ):
                continue
            gone.append(rel)
        removed = _parallel_delete(remote / Path(rel) for rel in gone)
        for rel in gone:
            _synced.pop(rel, None)

        if pushed or removed:
            scope_note = "" if scope_league_ids is None else f" (scope={league_id})"
            _emit(
                f"pushed {pushed}, deleted {removed} "
                f"in {time.time() - t0:.1f}s{scope_note}"
            )
        return pushed


@contextmanager
def background_writer(name: str) -> Iterator[None]:
    """Mark a background job as writing to the working copy while it runs.

    Wrap the body of any thread that writes league data after its request has
    returned (the job still pushes its own writes when it finishes). While one
    is active, ``flush_on_shutdown`` stands down instead of pushing the job's
    half-written state.
    """
    with _busy_lock:
        _busy[name] = _busy.get(name, 0) + 1
    try:
        yield
    finally:
        with _busy_lock:
            left = _busy.get(name, 0) - 1
            if left > 0:
                _busy[name] = left
            else:
                _busy.pop(name, None)


def as_background_writer(name: str, fn):
    """``fn`` wrapped in ``background_writer(name)``, for use as a thread target."""

    def _run() -> None:
        with background_writer(name):
            fn()

    return _run


def flush_on_shutdown() -> int:
    """Push everything still unsaved before the instance goes away.

    Saves happen after mutating requests and at the end of background jobs, so
    a write made during a read request, or by a job after its last push, used
    to exist only on the dying instance's disk. A deploy or an instance recycle
    sends SIGTERM first; uvicorn runs the app's shutdown handlers, which call
    this. Cloud Run allows ~10s before SIGKILL; a full walk is a local stat
    pass plus whatever is actually pending.

    If a background job is mid-write (a sim halfway through a day), pushing
    would leave a half-written league in durable storage -- schedule results
    without their stats -- so it stands down and that job's work is lost,
    exactly as before this existed.
    """
    if not is_enabled():
        return 0
    with _busy_lock:
        busy = sorted(_busy)
    if busy:
        _emit(f"shutdown: not flushing, background work in progress ({', '.join(busy)})")
        return 0
    pushed = push_changes(full=True)
    _emit(f"shutdown: flushed {pushed} files")
    return pushed
