"""Team dashboard endpoints.

Phase 4 focus: the headline metrics and division standings rendered by
``ui/owner_home_page.py`` via ``ui/analytics/quick_metrics.py``. We reuse the
existing Python implementation (no reimplementation in the sidecar) and
surface a trimmed JSON subset tailored to the Electron owner dashboard.

Heavier widgets (bullpen readiness, hot/cold performers, leaders, finance)
land in later Phase 4 iterations.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from ui.analytics.quick_metrics import gather_owner_quick_metrics

from ..security import CurrentIdentity

router = APIRouter(prefix="/teams/{team_id}", tags=["dashboard"], dependencies=[CurrentIdentity])


def _safe_metrics(team_id: str) -> Dict[str, Any]:
    try:
        return gather_owner_quick_metrics(team_id, roster=None, players=None)
    except Exception as exc:  # defensive: never let a helper failure 500 the UI
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to gather metrics for {team_id}: {exc}",
        ) from exc


@router.get("/snapshot")
def team_snapshot(team_id: str) -> Dict[str, Any]:
    """Headline numbers for the owner dashboard hero card."""

    metrics = _safe_metrics(team_id)
    return {
        "team_id": team_id,
        "record": metrics.get("record", "--"),
        "run_diff": metrics.get("run_diff", "--"),
        "streak": metrics.get("streak", "--"),
        "last10": metrics.get("last10", "--"),
        "next_opponent": metrics.get("next_opponent", "--"),
        "next_date": metrics.get("next_date", "--"),
        "injuries": metrics.get("injuries", 0),
        "prob_sp": metrics.get("prob_sp"),
    }


@router.get("/division")
def team_division_standings(team_id: str) -> Dict[str, Any]:
    """Division standings table with the caller's team highlighted."""

    metrics = _safe_metrics(team_id)
    division = metrics.get("division_standings") or {"division": "--", "teams": []}
    rows: List[Dict[str, Any]] = []
    for row in division.get("teams", []) or []:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "team_id": row.get("team_id", ""),
                "label": row.get("label") or row.get("name") or row.get("team_id", ""),
                "name": row.get("name") or row.get("label") or row.get("team_id", ""),
                "wins": int(row.get("wins", 0) or 0),
                "losses": int(row.get("losses", 0) or 0),
                "pct": float(row.get("pct", 0.0) or 0.0),
                "gb": str(row.get("gb", "0")),
                "streak": str(row.get("streak", "--")),
                "last10": str(row.get("last10", "--")),
                "is_current": bool(row.get("is_current", False)),
            }
        )
    return {"division": str(division.get("division", "--")), "teams": rows}
