"""Draft endpoints.

Read-only surface over ``services.draft_state`` plus the finalized results
CSV. If no state exists yet (pre-draft or in-memory only), the response
still returns a well-formed empty structure so the UI can render gracefully.
"""

from __future__ import annotations

import csv
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from services import draft_state
from services.trade_settings import current_league_year
from utils.path_utils import get_data_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/draft", tags=["draft"], dependencies=[CurrentIdentity])


def _resolve_year(year: Optional[int]) -> int:
    if year and year > 0:
        return year
    try:
        return int(current_league_year())
    except Exception:
        from datetime import date

        return date.today().year


def _load_results(year: int) -> List[Dict[str, Any]]:
    path = get_data_dir() / f"draft_results_{year}.csv"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(
                    {
                        "overall": int(row.get("overall", 0) or 0),
                        "round": int(row.get("round", 0) or 0),
                        "team_id": str(row.get("team_id", "")).strip(),
                        "player_id": str(row.get("player_id", "")).strip(),
                    }
                )
    except OSError:
        return []
    rows.sort(key=lambda r: r["overall"])
    return rows


@router.get("/state")
def draft_state_view(
    year: Optional[int] = Query(default=None, description="Defaults to current league year"),
) -> Dict[str, Any]:
    y = _resolve_year(year)
    state = draft_state.load_state(y) or {}
    order = list(state.get("order") or [])
    selected = list(state.get("selected") or [])
    return {
        "year": y,
        "round": int(state.get("round", 1) or 1),
        "overall_pick": int(state.get("overall_pick", 1) or 1),
        "seed": state.get("seed"),
        "order": order,
        "selected": selected,
        "exists": bool(state),
    }


@router.get("/results")
def draft_results_view(
    year: Optional[int] = Query(default=None, description="Defaults to current league year"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Dict[str, Any]:
    y = _resolve_year(year)
    rows = _load_results(y)[:limit]
    return {"year": y, "count": len(rows), "picks": rows}
