"""Exports + asset-generation endpoints.

All are blocking sync wrappers around the existing service helpers, run in
a worker thread so the event loop stays responsive. Admin-only; reports
can take seconds, logos/avatars can take minutes on CPU.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..security import require_bearer

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
    return _coerce(result)


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
    return _coerce(result)


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
    return _coerce(result)


@router.post("/logos")
async def generate_logos(
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        from utils.logo_generator import generate_team_logos
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    allow_auto_logo = bool(payload.get("allow_auto_logo", True))
    raw_engine = str(payload.get("force_engine", "") or "").strip().lower()
    force_engine = raw_engine if raw_engine in {"openai", "auto_logo"} else None
    engine_used: Dict[str, str] = {"value": "auto_logo"}

    def _track(value: str) -> None:
        engine_used["value"] = value

    try:
        out_dir = await asyncio.to_thread(
            generate_team_logos,
            allow_auto_logo=allow_auto_logo,
            status_callback=_track,
            force_engine=force_engine,
        )
    except RuntimeError as exc:
        # Raised when OpenAI is not configured and allow_auto_logo=False.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return {
        "output_dir": str(out_dir),
        "generated_at": int(time.time()),
        "engine": engine_used["value"],
    }


@router.post("/avatars")
async def generate_avatars(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        from utils.avatar_generator import generate_player_avatars
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    try:
        result = await asyncio.to_thread(generate_player_avatars)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return _coerce(result or {"status": "completed"})
