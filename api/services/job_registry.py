"""In-memory job registry for long-running export/generation endpoints.

The avatar and team-logo pipelines can take minutes. Rather than hold the
HTTP request open (and leave the UI looking frozen), the export endpoints
spawn the work in a background thread, return a ``job_id`` immediately,
and let the client poll ``/exports/jobs/{job_id}`` for progress + result.

Scope is intentionally tiny: a process-local dict guarded by a lock, plus
a best-effort cleanup of finished jobs older than an hour. No persistence,
no cross-process sharing — this is a single-user desktop sidecar.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional


_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_AGE_SECONDS = 60 * 60  # keep finished jobs for an hour


def create(kind: str) -> str:
    """Register a new running job and return its id."""

    job_id = uuid.uuid4().hex
    now = time.time()
    with _LOCK:
        _cleanup_locked(now)
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "done": 0,
            "total": 0,
            "phase": "",
            "output_dir": None,
            "result": None,
            "error": None,
            "started_at": now,
            "finished_at": None,
        }
    return job_id


def update_progress(job_id: str, done: int, total: int) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] != "running":
            return
        job["done"] = int(done)
        job["total"] = int(total)


def update_phase(job_id: str, phase: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] != "running":
            return
        job["phase"] = str(phase)


def complete(
    job_id: str,
    *,
    output_dir: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "completed"
        job["output_dir"] = output_dir
        if result is not None:
            job["result"] = result
        # Leave done/total as-is; if the runner hit total items successfully,
        # mirror done up to total so the client sees 100%.
        if job["total"] and job["done"] < job["total"]:
            job["done"] = job["total"]
        job["finished_at"] = time.time()


def fail(job_id: str, error: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "failed"
        job["error"] = error
        job["finished_at"] = time.time()


def get(job_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _cleanup_locked(now: float) -> None:
    expired = [
        jid
        for jid, job in _JOBS.items()
        if job.get("finished_at") and (now - job["finished_at"]) > _MAX_AGE_SECONDS
    ]
    for jid in expired:
        del _JOBS[jid]
