"""Exports + asset-generation endpoints.

All are blocking sync wrappers around the existing service helpers, run in
a worker thread so the event loop stays responsive. Admin-only; reports
can take seconds, logos/avatars can take minutes on CPU.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..security import require_bearer
from ..services import job_registry

router = APIRouter(prefix="/exports", tags=["exports"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


def _coerce(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return _coerce(asdict(value))
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    return str(value)


def _coerce_top_level(value: Any) -> Dict[str, Any]:
    """Every export endpoint declares ``Dict[str, Any]`` as its response
    type, so we must always return a dict. Several underlying services
    return a plain string (the output directory) — wrap those so FastAPI's
    response validator doesn't blow up.
    """

    coerced = _coerce(value)
    if isinstance(coerced, dict):
        return coerced
    if coerced is None:
        return {"status": "completed"}
    if isinstance(coerced, (list, tuple, set)):
        return {"status": "completed", "items": list(coerced)}
    return {"status": "completed", "output": coerced}


@router.post("/reports")
async def export_reports(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        from services.report_exporter import export_reports as _export_reports
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report exporter unavailable: {exc}",
        ) from exc
    try:
        result = await asyncio.to_thread(
            _export_reports,
            report_format=str(payload.get("format", "csv")),
            include_pdf=bool(payload.get("include_pdf", True)),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return _coerce_top_level(result)


@router.post("/almanac")
async def export_almanac(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        from services.almanac_exporter import export_almanac as _export_almanac
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    try:
        result = await asyncio.to_thread(_export_almanac)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return _coerce_top_level(result)


@router.post("/snapshot")
async def export_snapshot(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        from services.league_snapshot import export_league_snapshot
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    try:
        result = await asyncio.to_thread(export_league_snapshot)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return _coerce_top_level(result)


@router.post("/logos")
async def generate_logos(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Kick off team-logo generation in a background thread.

    Returns a ``job_id`` immediately. Poll ``/exports/jobs/{job_id}`` for
    progress and the final ``output_dir`` / ``engine`` payload.
    """

    try:
        from utils.logo_generator import generate_team_logos
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    from utils import path_utils

    allow_auto_logo = bool(payload.get("allow_auto_logo", True))
    raw_engine = str(payload.get("force_engine", "") or "").strip().lower()
    force_engine = raw_engine if raw_engine in {"openai", "vertex", "auto_logo"} else None
    # Capture the league in the request context (ContextVars don't reach the
    # run_in_executor thread); rebind it inside _run so logos write to it.
    league = path_utils.get_active_league_id()

    job_id = job_registry.create("logos")

    def _run() -> None:
        token = path_utils.set_request_league(league) if league else None
        engine_used: Dict[str, str] = {"value": "auto_logo"}

        def _track_engine(value: str) -> None:
            engine_used["value"] = value
            job_registry.update_phase(job_id, f"engine:{value}")

        def _track_progress(done: int, total: int) -> None:
            job_registry.update_progress(job_id, done, total)

        try:
            out_dir = generate_team_logos(
                allow_auto_logo=allow_auto_logo,
                status_callback=_track_engine,
                force_engine=force_engine,
                progress_callback=_track_progress,
            )
        except RuntimeError as exc:
            job_registry.fail(job_id, str(exc))
            return
        except Exception as exc:
            logging.exception("Logo generation failed")
            job_registry.fail(
                job_id, f"{exc}\n\n{traceback.format_exc()}"
            )
            return
        finally:
            if token is not None:
                path_utils.reset_request_league(token)
        # Persist generated logos to durable storage (GCS) so a restart keeps them.
        try:
            from api import working_copy

            if working_copy.is_enabled():
                working_copy.push_changes()
        except Exception:
            logging.exception("logo working-copy push failed")
        job_registry.complete(
            job_id,
            output_dir=str(out_dir) if out_dir else None,
            result={
                "engine": engine_used["value"],
                "generated_at": int(time.time()),
            },
        )

    asyncio.get_running_loop().run_in_executor(None, _run)
    return {"job_id": job_id, "kind": "logos"}


@router.post("/logos/normalize")
async def normalize_logos(
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Re-frame existing team logos in place (no AI) — trims each logo's
    background margin so all teams' mascots fill the frame consistently."""
    from utils import path_utils

    league = path_utils.get_active_league_id()
    try:
        from utils.logo_generator import normalize_team_logos
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    job_id = job_registry.create("logos-normalize")

    def _run() -> None:
        token = path_utils.set_request_league(league) if league else None

        def _track_progress(done: int, total: int) -> None:
            job_registry.update_progress(job_id, done, total)

        try:
            out_dir = normalize_team_logos(progress_callback=_track_progress)
        except Exception as exc:
            logging.exception("Logo normalize failed")
            job_registry.fail(job_id, f"{exc}\n\n{traceback.format_exc()}")
            return
        finally:
            if token is not None:
                path_utils.reset_request_league(token)
        try:
            from api import working_copy

            if working_copy.is_enabled():
                working_copy.push_changes()
        except Exception:
            logging.exception("logo-normalize push failed")
        job_registry.complete(
            job_id,
            output_dir=str(out_dir) if out_dir else None,
            result={"normalized": True},
        )

    asyncio.get_running_loop().run_in_executor(None, _run)
    return {"job_id": job_id, "kind": "logos-normalize"}


@router.post("/avatars")
async def generate_avatars(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Kick off player-avatar generation in a background thread.

    ``initial_creation`` (default False): when True, wipes every existing
    avatar in the output dir (except the Template/ tree + default.png)
    before regenerating. When False, only players without an avatar get
    one generated — matches the PyQt "yes = wipe-and-regen, no = fill-
    in-only" prompt semantics.

    Returns a ``job_id`` immediately. Poll ``/exports/jobs/{job_id}`` for
    progress and the final ``output_dir``.
    """

    from utils import path_utils

    initial = bool(payload.get("initial_creation", False))
    raw_engine = str(payload.get("engine", "") or "").strip().lower()
    engine = raw_engine if raw_engine in {"ai", "template"} else "template"
    # Capture the request's league HERE (in the request context); ContextVars do
    # NOT propagate into the run_in_executor thread, so we rebind it inside _run.
    league = path_utils.get_active_league_id()
    try:
        from utils.avatar_generator import generate_player_avatars
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Avatar engine unavailable: {exc}\n{traceback.format_exc()}",
        ) from exc

    job_id = job_registry.create("avatars")

    def _run() -> None:
        token = path_utils.set_request_league(league) if league else None
        engine_used: Dict[str, str] = {"value": engine}

        def _track_engine(value: str) -> None:
            engine_used["value"] = value
            job_registry.update_phase(job_id, f"engine:{value}")

        def _track_progress(done: int, total: int) -> None:
            job_registry.update_progress(job_id, done, total)

        try:
            out_dir = generate_player_avatars(
                initial_creation=initial,
                engine=engine,
                progress_callback=_track_progress,
                status_callback=_track_engine,
            )
        except Exception as exc:
            logging.exception("Avatar generation failed")
            job_registry.fail(job_id, f"{exc}\n\n{traceback.format_exc()}")
            return
        finally:
            if token is not None:
                path_utils.reset_request_league(token)
        # Persist generated avatars to durable storage (GCS) so an instance
        # restart never loses — and re-bills — AI-generated images.
        try:
            from api import working_copy

            if working_copy.is_enabled():
                working_copy.push_changes()
        except Exception:
            logging.exception("avatar working-copy push failed")
        job_registry.complete(
            job_id,
            output_dir=str(out_dir) if out_dir else None,
            result={"engine": engine_used["value"], "initial_creation": initial},
        )

    asyncio.get_running_loop().run_in_executor(None, _run)
    return {"job_id": job_id, "kind": "avatars"}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Return the current state of a background export/generation job.

    Status is one of ``running``, ``completed``, or ``failed``. While
    running, clients should poll every ~500ms and render progress from
    ``done`` / ``total``. When finished, ``output_dir`` and ``result``
    are populated (or ``error`` on failure).
    """

    job = job_registry.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown job id"
        )
    return job
