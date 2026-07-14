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
``200`` knows its change persisted. A crash mid-sim loses only the in-flight
sim, never the prior committed state.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

# Remote top-level entries we never need on the active node — skipping them keeps
# the startup pull small (bounded to the live footprint, not archives/backups).
# These are also never pulled into ``_known``, so the delete pass can never touch
# them on the remote.
_SKIP_TOP_NAMES = {"system"}
_SKIP_LEAGUE_PREFIX = "legacy"

# FUSE ops are I/O-bound (GIL released during the syscall), so threads overlap
# the GCS round-trips effectively.
_WORKERS = 32

# Timestamp of the last successful pull/push. Files modified after this are the
# ones a push needs to flush.
_last_sync: float = 0.0

# Relative posix paths we have synced (present in the working copy as of the last
# pull/push). A push diffs the current local tree against this to find deletions.
_known: Set[str] = set()

# Per-segment flush times for SCOPED pushes. Keys: "" for root-level files
# (direct children of the data root), otherwise a league id. A scoped push
# advances only its own segments — never the global ``_last_sync`` — so a
# pending change in league B can't be hidden behind a cutoff advanced by a
# push scoped to league A. Segments without an entry fall back to
# ``_last_sync`` (the last full pull/push, which covered everything).
_scope_sync: Dict[str, float] = {}

# Serialize pushes so concurrent mutating requests don't race on _known / the
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
    global _known
    _known = {rel for rel in _known if not rel.startswith(f"leagues/{league_id}/")}
    _scope_sync.pop(league_id, None)
    # (was `_log`, an undefined name — NameError on every super-admin delete)
    _emit(f"deleted league {league_id!r} from remote+local")
    return removed


def _copy_one(pair: Tuple[Path, Path]) -> int:
    src, dst = pair
    try:
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
    global _last_sync, _known
    remote, local = _remote(), _local()
    if not remote.exists():
        _emit(f"remote {remote} not present; skipping pull")
        return

    local.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rels = list(_iter_pull_files(remote))
    walk_s = time.time() - t0
    copied = _parallel_copy((remote / rel, local / rel) for rel in rels)
    # Seed _known from what's ACTUALLY in the local copy (not the intended pull
    # set): a file that failed to copy down must not later be seen as "deleted
    # locally" and wrongly removed from the durable remote.
    _known = {
        p.relative_to(local).as_posix() for p in local.rglob("*") if p.is_file()
    }
    _last_sync = time.time()
    # A pull refreshes every segment; scoped cutoffs restart from _last_sync.
    _scope_sync.clear()

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


def push_changes(league_id: Optional[str] = None) -> int:
    """Flush local changes back to the remote: copy new/modified files, and
    delete remote files that were removed locally.

    Walks only the *local* tree (fast disk); the changed/deleted sets are then
    the only things that cross the slow FUSE boundary, and they cross in parallel.

    When the triggering request is bound to a league (cloud multi-tenant
    ``X-League-Id`` — passed in by the middleware, or read from the same
    ContextVar ``utils.path_utils`` uses), the walk is SCOPED to that league's
    dir plus root-level files (direct children of the data root) plus any
    league dir never synced before (e.g. a league this request just created),
    instead of rglob-ing the entire multi-league root. Deletion sync and the
    ``_known`` bookkeeping are narrowed to the same scope so out-of-scope
    leagues are never touched. No league context → the original full walk.
    """
    global _last_sync, _known
    remote, local = _remote(), _local()
    if not local.exists():
        return 0

    league_id = _safe_league_id(league_id) or _request_league_id()

    with _push_lock:
        t0 = time.time()
        # Scope of this push: None → full walk; otherwise the set of league
        # ids whose trees we walk (plus root-level files, always in scope).
        scope_league_ids: Optional[Set[str]] = None
        if league_id and (local / "leagues" / league_id).is_dir():
            scope_league_ids = {league_id}
            # Also walk league dirs with NO synced files yet: a brand-new
            # league (possibly created by this very request while bound to
            # another league's context) exists only locally, and skipping it
            # would leave it un-persisted — losing it on restart.
            known_league_ids = {
                rel.split("/", 2)[1] for rel in _known if rel.startswith("leagues/")
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

        def _scan(src: Path, cutoff: float) -> None:
            if not src.is_file():
                return
            rel = src.relative_to(local)
            current.add(rel.as_posix())
            try:
                if src.stat().st_mtime > cutoff:
                    changed.append((src, remote / rel))
            except OSError:
                return

        if scope_league_ids is None:
            cutoff = _last_sync
            for src in local.rglob("*"):
                _scan(src, cutoff)
        else:
            root_cutoff = _scope_sync.get("", _last_sync)
            try:
                for entry in local.iterdir():
                    _scan(entry, root_cutoff)
            except OSError:
                pass
            for lid in scope_league_ids:
                league_cutoff = _scope_sync.get(lid, _last_sync)
                for src in (local / "leagues" / lid).rglob("*"):
                    _scan(src, league_cutoff)

        pushed = _parallel_copy(changed)
        # Anything we previously synced but is gone locally → delete on remote,
        # EXCEPT files of a league no longer present locally AT ALL. That means
        # the league simply wasn't pulled this run (selective/partial pull), not
        # that it was deleted — wiping it from the durable bucket is catastrophic
        # data loss (this is exactly how cbl/usabl were lost). Within-league file
        # deletions (the league dir is still present) are still propagated.
        if scope_league_ids is None:
            known_in_scope = _known
        else:
            # Only diff what this push actually walked: root-level files and
            # the in-scope league trees. Everything else in _known is out of
            # scope — absent from ``current`` merely because we didn't walk it.
            known_in_scope = {
                rel
                for rel in _known
                if "/" not in rel
                or (
                    rel.startswith("leagues/")
                    and rel.split("/", 2)[1] in scope_league_ids
                )
            }
        deleted = []
        for rel in (known_in_scope - current):
            parts = rel.split("/")
            if (
                len(parts) >= 2
                and parts[0] == "leagues"
                and not (local / "leagues" / parts[1]).is_dir()
            ):
                continue
            deleted.append(remote / Path(rel))
        removed = _parallel_delete(deleted)

        if scope_league_ids is None:
            _known = current
            _last_sync = time.time()
            # A full push refreshed every segment.
            _scope_sync.clear()
        else:
            _known = (_known - known_in_scope) | current
            now = time.time()
            _scope_sync[""] = now
            for lid in scope_league_ids:
                _scope_sync[lid] = now
        if pushed or removed:
            scope_note = "" if scope_league_ids is None else f" (scope={league_id})"
            _emit(
                f"pushed {pushed}, deleted {removed} "
                f"in {time.time() - t0:.1f}s{scope_note}"
            )
        return pushed
