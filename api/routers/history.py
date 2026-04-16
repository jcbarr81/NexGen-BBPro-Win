"""League history endpoint.

Reuses the existing PyQt history loader to keep one source of truth:
``ui.league_history_window._load_history_entries`` already walks the
season context, resolves artifacts (awards, champions, playoffs
bracket, record book), and builds a dataclass per archived season.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from ..security import CurrentIdentity

router = APIRouter(prefix="/league", tags=["history"], dependencies=[CurrentIdentity])


@router.get("/history")
def league_history() -> Dict[str, Any]:
    try:
        from ui.league_history_window import _load_history_entries
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"History loader unavailable: {exc}",
        ) from exc

    try:
        entries = _load_history_entries()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load league history: {exc}",
        ) from exc

    seasons: List[Dict[str, Any]] = [asdict(entry) for entry in entries]
    return {"count": len(seasons), "seasons": seasons}
