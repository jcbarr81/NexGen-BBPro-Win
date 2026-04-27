"""Depth chart editor endpoints.

Wraps :mod:`utils.depth_chart`. Per-position ordered priority lists that
lineup autofill + injury replacement use.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException, status

from utils.depth_chart import (
    DEPTH_CHART_POSITIONS,
    MAX_DEPTH,
    load_depth_chart,
    save_depth_chart,
)
from utils.depth_chart_autofill import auto_generate_depth_chart

from ..security import CurrentIdentity

router = APIRouter(prefix="/teams/{team_id}/depth-chart", tags=["depth-chart"], dependencies=[CurrentIdentity])


@router.get("")
def get_depth_chart(team_id: str) -> Dict[str, Any]:
    chart = load_depth_chart(team_id)
    return {
        "team_id": team_id,
        "positions": list(DEPTH_CHART_POSITIONS),
        "max_depth": MAX_DEPTH,
        "chart": {pos: list(chart.get(pos, [])) for pos in DEPTH_CHART_POSITIONS},
    }


@router.put("")
def save(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    raw = payload.get("chart")
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chart must be an object mapping position -> player id list.",
        )
    cleaned: Dict[str, List[str]] = {}
    for pos in DEPTH_CHART_POSITIONS:
        entries = raw.get(pos)
        if isinstance(entries, list):
            cleaned[pos] = [str(pid).strip() for pid in entries if str(pid).strip()]

    from services.roster_validation import validate_depth_chart

    from .validation import load_players_map, load_team_levels

    players = load_players_map()
    levels = load_team_levels(team_id)
    roster_ids: List[str] = []
    for v in levels.values():
        roster_ids.extend(v)
    result = validate_depth_chart(
        chart=cleaned, players=players, roster_ids=roster_ids
    )
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Depth chart has validation errors.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    save_depth_chart(team_id, cleaned)
    return get_depth_chart(team_id)


@router.post("/auto-fill")
def auto_fill(team_id: str) -> Dict[str, Any]:
    """Auto-generate the depth chart from the current roster + ratings.

    Mirrors the PyQt depth-chart dialog's "Auto Populate" button: each
    position is seeded with up to ``MAX_DEPTH`` best-fit non-pitchers,
    preferring primary-position players from the active roster sorted
    by overall rating.
    """

    try:
        auto_generate_depth_chart(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Auto-generate failed: {exc}",
        ) from exc
    return get_depth_chart(team_id)
