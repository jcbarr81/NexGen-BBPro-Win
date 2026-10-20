"""Queue of player pictures to redo in a new club's colors (8.3.0).

A player's picture shows the cap and jersey of the club he was on when it was
made. When he joins another club (a trade, a free-agent signing) or his club
changes its colors, he is queued here, and a background worker redoes the
picture with :func:`utils.avatar_generator.recolor_avatar` -- an image EDIT
of an AI portrait (same face, new colors) or a template re-render.

The queue is ``avatar_recolor_queue.json`` in the league's data dir, so it
syncs to durable storage with the league and survives a restart:

    {"pending": [{"player_id", "reason", "queued_at", "attempts"}],
     "active": {...} | null,          # the entry being worked on right now
     "done": n, "failed": n, "skipped": n, "ai_edits": n,
     "recent": [last results, newest last]}

The target club is decided when an entry is PROCESSED: the club whose roster
lists him then (so two quick moves cost one edit). A player on no roster (a
free agent) is dropped: free agents keep their last club's look.

The worker drains one entry at a time (Vertex pacing comes from
``utils.vertex_image``). It starts after an enqueue, and the scheduler tick
(``POST /season/schedule/tick``) restarts it for any league whose queue is not
empty -- which is how a queue left by a restarted instance is picked up. An
entry that was mid-edit when an instance died is put back at the head of the
queue. Nothing here ever fails or blocks the action that enqueued.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOG = logging.getLogger("nexgen.avatars")

QUEUE_FILE = "avatar_recolor_queue.json"
MAX_ATTEMPTS = 3
_RECENT_LIMIT = 25

# Pictures written / statuses that count as done; everything else that is not
# a failure is a skip (already right, free agent, no engine for it).
_DONE = {"ai_edited", "template"}
_FAILED = {"failed"}

# One lock per queue file for read-modify-write, and one per picture so the
# worker and the commissioner's "Refresh picture" never edit the same file.
_file_locks: Dict[str, threading.Lock] = {}
_player_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Running workers, keyed by data dir. Guarded by _workers_lock, which is also
# held while a worker decides to exit, so an enqueue can never be stranded
# between "queue looked empty" and "worker gone".
_workers: Dict[str, threading.Thread] = {}
_workers_lock = threading.Lock()


def _keyed_lock(table: Dict[str, threading.Lock], key: str) -> threading.Lock:
    with _locks_guard:
        lock = table.get(key)
        if lock is None:
            lock = table[key] = threading.Lock()
        return lock


def _base(data_dir: Path | str | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    from utils.path_utils import get_data_dir

    return get_data_dir()


def _queue_path(base: Path) -> Path:
    return base / QUEUE_FILE


def _empty_state() -> Dict[str, Any]:
    return {
        "pending": [],
        "active": None,
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "ai_edits": 0,
        "recent": [],
        # club -> when its last colors-change batch may run (cost cap)
        "team_batches": {},
    }


def _read(base: Path) -> Dict[str, Any]:
    state = _empty_state()
    try:
        payload = json.loads(_queue_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(payload, dict):
        for key in state:
            if key in payload:
                state[key] = payload[key]
    if not isinstance(state["pending"], list):
        state["pending"] = []
    if not isinstance(state["recent"], list):
        state["recent"] = []
    if not isinstance(state["team_batches"], dict):
        state["team_batches"] = {}
    return state


def _write(base: Path, state: Dict[str, Any]) -> None:
    path = _queue_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")  # *.tmp is never synced
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def worker_enabled() -> bool:
    """False when ``NEXGEN_AVATAR_RECOLOR_WORKER=0`` (the test suite sets it):
    entries are still queued, but no background thread starts."""
    return os.environ.get("NEXGEN_AVATAR_RECOLOR_WORKER", "1") != "0"


def enqueue(
    player_ids: Iterable[str],
    reason: str,
    *,
    data_dir: Path | str | None = None,
    start: bool = True,
    not_before: Optional[str] = None,
) -> int:
    """Queue ``player_ids`` for a picture in their club's colors.

    ``not_before`` (an ISO UTC time) holds the entries until then.

    Deduplicated by player (an already-pending player keeps his place). The
    worker is started unless ``start`` is False. Never raises: a failure is
    logged and 0 returned, so the trade or signing that called this always
    goes through. Returns the number of players newly queued.
    """
    try:
        ids = [str(pid or "").strip() for pid in (player_ids or [])]
        ids = [pid for pid in dict.fromkeys(ids) if pid]
        if not ids:
            return 0
        base = _base(data_dir)
        with _keyed_lock(_file_locks, str(base)):
            state = _read(base)
            pending = {str(e.get("player_id")) for e in state["pending"] if isinstance(e, dict)}
            added = 0
            for pid in ids:
                if pid in pending:
                    continue
                entry = {"player_id": pid, "reason": str(reason), "queued_at": _now(), "attempts": 0}
                if not_before:
                    entry["not_before"] = not_before
                state["pending"].append(entry)
                pending.add(pid)
                added += 1
            if added:
                _write(base, state)
        if start:
            kick(data_dir=base)
        return added
    except Exception:
        _LOG.exception("avatar recolor: could not queue %s (%s)", player_ids, reason)
        return 0


# A club's whole roster (up to ~50 paid edits) is redone at most once per
# this many seconds, however often its colors change: an owner can save new
# colors, and each batch costs about $2. A change inside the window is held
# until it ends; the pictures use the colors in force when they are made, so
# several changes in a day cost one batch.
TEAM_BATCH_COOLDOWN_S = 24 * 3600


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _parse_iso(text: Any) -> Optional[float]:
    import calendar

    try:
        return float(calendar.timegm(time.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError, OverflowError):
        return None


def enqueue_team(team_id: str, reason: str, *, data_dir: Path | str | None = None) -> int:
    """Queue every player on ``team_id``'s roster file (any level), at most
    one batch per club per ``TEAM_BATCH_COOLDOWN_S``."""
    try:
        from utils.roster_ownership import read_roster_rows

        base = _base(data_dir)
        tid = str(team_id).strip().upper()
        now = time.time()
        with _keyed_lock(_file_locks, str(base)):
            state = _read(base)
            last = _parse_iso(state["team_batches"].get(tid))
            run_at = now if last is None else max(now, last + TEAM_BATCH_COOLDOWN_S)
            state["team_batches"][tid] = _iso(run_at)
            _write(base, state)
        rows = read_roster_rows(base / "rosters" / f"{str(team_id).strip()}.csv")
        return enqueue(
            [pid for pid, _level in rows],
            reason,
            data_dir=base,
            not_before=None if run_at <= now else _iso(run_at),
        )
    except Exception:
        _LOG.exception("avatar recolor: could not queue club %s", team_id)
        return 0


def status(*, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """Counts for the commissioner: pending, done, failed, skipped, AI edits."""
    base = _base(data_dir)
    state = _read(base)
    with _workers_lock:
        thread = _workers.get(str(base))
        running = bool(thread is not None and thread.is_alive())
    return {
        "pending": len(state["pending"]) + (1 if state.get("active") else 0),
        "done": int(state.get("done") or 0),
        "failed": int(state.get("failed") or 0),
        "skipped": int(state.get("skipped") or 0),
        "ai_edits": int(state.get("ai_edits") or 0),
        "active": state.get("active"),
        "worker_running": running,
        "recent": list(state.get("recent") or [])[-10:],
    }


def process_player(
    player_id: str,
    *,
    data_dir: Path | str | None = None,
    write_guard: Any = None,
) -> Dict[str, Any]:
    """Redo one player's picture in the colors of the club whose roster lists
    him now. ``"free_agent"`` (nothing done) when no roster does."""
    from utils.avatar_generator import recolor_avatar
    from utils.roster_ownership import owning_club

    base = _base(data_dir)
    pid = str(player_id or "").strip()
    with _keyed_lock(_player_locks, f"{base}|{pid}"):
        club = owning_club(pid, base, include_contracts=False)
        if club is None:
            return {"player_id": pid, "team_id": "", "status": "free_agent", "colors": ""}
        return recolor_avatar(pid, club[0], data_dir=base, write_guard=write_guard)


def record_result(result: Dict[str, Any], *, data_dir: Path | str | None = None) -> None:
    """Add one result to the queue file's counters (also for a recolor run
    outside the queue, so the AI-edit count stays the full cost record)."""
    base = _base(data_dir)
    status_ = str(result.get("status") or "")
    with _keyed_lock(_file_locks, str(base)):
        state = _read(base)
        _count(state, result)
        _write(base, state)
    if status_ == "ai_edited":
        _note_ai_edit(state, result)


def _note_ai_edit(state: Dict[str, Any], result: Dict[str, Any]) -> None:
    """The running count of paid AI edits, in the logs. print() so it lands
    in Cloud Logging (nexgen.* logger output does not)."""
    print(
        f"[avatar-recolor] AI edit #{int(state.get('ai_edits') or 0)}: "
        f"{result.get('player_id')} -> {result.get('team_id')} {result.get('colors', '')}",
        flush=True,
    )


def _count(state: Dict[str, Any], result: Dict[str, Any]) -> None:
    status_ = str(result.get("status") or "")
    if status_ in _DONE:
        state["done"] = int(state.get("done") or 0) + 1
    elif status_ in _FAILED:
        state["failed"] = int(state.get("failed") or 0) + 1
    else:
        state["skipped"] = int(state.get("skipped") or 0) + 1
    if status_ == "ai_edited":
        state["ai_edits"] = int(state.get("ai_edits") or 0) + 1
    entry = {
        "player_id": result.get("player_id"),
        "team_id": result.get("team_id"),
        "status": status_,
        "at": _now(),
    }
    if result.get("error"):
        entry["error"] = str(result["error"])[:300]
    state["recent"] = (list(state.get("recent") or []) + [entry])[-_RECENT_LIMIT:]


def _claim(base: Path) -> Optional[Dict[str, Any]]:
    """Move the head of the queue to ``active`` and return it (None if empty).
    An ``active`` entry left by a dead instance goes back to the head first."""
    with _keyed_lock(_file_locks, str(base)):
        state = _read(base)
        leftover = state.get("active")
        if isinstance(leftover, dict) and leftover.get("player_id"):
            state["pending"].insert(0, leftover)
        state["active"] = None
        entry = None
        now = time.time()
        kept: List[Any] = []
        for item in state["pending"]:
            if entry is not None or not isinstance(item, dict) or not item.get("player_id"):
                if isinstance(item, dict) and item.get("player_id"):
                    kept.append(item)
                continue
            held = _parse_iso(item.get("not_before"))
            if held is not None and held > now:
                kept.append(item)  # held (a club's colors batch); later
                continue
            entry = item
        state["pending"] = kept
        state["active"] = entry
        if entry is not None or leftover:
            _write(base, state)
        return entry


def _finish(base: Path, entry: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Clear ``active`` and count the result; a failure goes back to the end
    of the queue until it has had MAX_ATTEMPTS tries."""
    with _keyed_lock(_file_locks, str(base)):
        state = _read(base)
        state["active"] = None
        if result.get("status") in _FAILED:
            attempts = int(entry.get("attempts") or 0) + 1
            pid = str(entry.get("player_id"))
            queued = {str(e.get("player_id")) for e in state["pending"] if isinstance(e, dict)}
            if attempts < MAX_ATTEMPTS and pid not in queued:
                state["pending"].append({**entry, "attempts": attempts})
                state["recent"] = (list(state.get("recent") or []) + [{
                    "player_id": pid,
                    "status": "retry",
                    "error": str(result.get("error") or "")[:300],
                    "at": _now(),
                }])[-_RECENT_LIMIT:]
                _write(base, state)
                return
        _count(state, result)
        _write(base, state)
    if result.get("status") == "ai_edited":
        _note_ai_edit(state, result)


def _background_writer(name: str):
    """``api.working_copy.background_writer`` when the API is importable."""
    try:
        from api import working_copy

        return working_copy.background_writer(name)
    except Exception:
        return contextlib.nullcontext()


def _push(league_id: Optional[str]) -> None:
    try:
        from api import working_copy

        if working_copy.is_enabled():
            working_copy.push_changes(league_id)
    except Exception:
        _LOG.exception("avatar recolor: working-copy push failed")


def drain(
    *,
    data_dir: Path | str | None = None,
    league_id: Optional[str] = None,
    max_items: Optional[int] = None,
    push_every: int = 10,
) -> Dict[str, int]:
    """Process queued entries one at a time until the queue is empty (or
    ``max_items``). Each entry is marked as a ``background_writer`` only
    while it writes (the claim, the picture swap, the result) -- never
    through the image request -- so a long catch-up never holds off the
    shutdown flush; the league's files are pushed after every AI edit and
    every ``push_every`` entries. Returns counts by status."""
    base = _base(data_dir)
    counts: Dict[str, int] = {}
    since_push = 0
    processed = 0
    while max_items is None or processed < max_items:
        # Marked as a background writer only while files change (the claim,
        # the picture swap, the result): the image request in between can
        # take minutes, and a mark held through it would hold off every
        # shutdown flush for the whole catch-up.
        with _background_writer("avatar-recolor"):
            entry = _claim(base)
        if entry is None:
            break
        try:
            result = process_player(
                str(entry["player_id"]),
                data_dir=base,
                write_guard=lambda: _background_writer("avatar-recolor"),
            )
        except Exception as exc:  # never let one picture stop the queue
            _LOG.exception("avatar recolor failed for %s", entry.get("player_id"))
            result = {
                "player_id": entry.get("player_id"),
                "status": "failed",
                "error": str(exc),
            }
        with _background_writer("avatar-recolor"):
            _finish(base, entry, result)
        processed += 1
        since_push += 1
        status_ = str(result.get("status") or "")
        counts[status_] = counts.get(status_, 0) + 1
        if status_ == "ai_edited" or since_push >= push_every:
            _push(league_id)
            since_push = 0
    if since_push:
        _push(league_id)
    return counts


def _has_work(base: Path) -> bool:
    state = _read(base)
    return bool(state["pending"]) or bool(state.get("active"))


def kick(
    league_id: Optional[str] = None,
    *,
    data_dir: Path | str | None = None,
) -> bool:
    """Start the background worker for this league if its queue has work and
    no worker is running. Returns True when a worker was started.

    ``league_id`` defaults to the current request's league; the worker
    rebinds it (ContextVars do not cross threads). A ``data_dir`` that is not
    that league's data dir is left for the league's own tick.
    """
    if not worker_enabled():
        return False
    try:
        from utils import path_utils

        lid = league_id or path_utils.get_active_league_id()
        token = path_utils.set_request_league(lid) if lid else None
        try:
            league_base = path_utils.get_data_dir()
        finally:
            if token is not None:
                path_utils.reset_request_league(token)
        base = Path(data_dir) if data_dir is not None else league_base
        if base.resolve() != Path(league_base).resolve():
            return False
        key = str(base)
        with _workers_lock:
            thread = _workers.get(key)
            if thread is not None and thread.is_alive():
                return False
            if not _has_work(base):
                return False
            thread = threading.Thread(
                target=_worker_main,
                args=(lid, base),
                name=f"avatar-recolor-{lid or 'default'}",
                daemon=True,
            )
            _workers[key] = thread
            thread.start()
        return True
    except Exception:
        _LOG.exception("avatar recolor: could not start the worker")
        return False


def _worker_main(league_id: Optional[str], base: Path) -> None:
    from utils import path_utils

    key = str(base)
    token = path_utils.set_request_league(league_id) if league_id else None
    try:
        while True:
            drain(data_dir=base, league_id=league_id)
            with _workers_lock:
                if _has_work(base):
                    continue  # queued while the last entry ran
                if _workers.get(key) is threading.current_thread():
                    _workers.pop(key, None)
                return
    except Exception:
        _LOG.exception("avatar recolor worker stopped")
        with _workers_lock:
            if _workers.get(key) is threading.current_thread():
                _workers.pop(key, None)
    finally:
        if token is not None:
            path_utils.reset_request_league(token)


def resume(league_id: Optional[str] = None) -> bool:
    """For the scheduler tick: restart this league's worker if its queue has
    work (a queue left by a restarted instance). Cheap when there is none."""
    try:
        return kick(league_id)
    except Exception:
        return False


__all__: List[str] = [
    "QUEUE_FILE",
    "drain",
    "enqueue",
    "enqueue_team",
    "kick",
    "process_player",
    "record_result",
    "resume",
    "status",
    "worker_enabled",
]
