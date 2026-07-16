"""League history endpoint.

Season-history aggregation lives in ``services.league_history`` (a server-safe
port of the retired ``ui.league_history_window`` loader — removed when the PyQt
UI was retired in v6.14.52). Keeping it in a service module means this endpoint
works in the headless Cloud/Electron-sidecar runtime, which does not ship PyQt.
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
        from services.league_history import load_history_entries

        entries = load_history_entries()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load league history: {exc}",
        ) from exc

    seasons: List[Dict[str, Any]] = [asdict(entry) for entry in entries]
    return {"count": len(seasons), "seasons": seasons}
