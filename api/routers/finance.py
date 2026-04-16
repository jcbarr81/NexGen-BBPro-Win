"""Team finance endpoints.

Reuses :func:`services.owner_finance_engine.get_team_finance_snapshot` and
:func:`services.owner_finance_engine.list_team_financial_transactions`, so
the Electron page renders the same numbers as the PyQt
``ui/owner_finance_page.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status

from services.owner_finance_engine import (
    get_team_finance_snapshot,
    list_team_financial_transactions,
)

from ..security import CurrentIdentity

router = APIRouter(
    prefix="/teams/{team_id}/finance",
    tags=["finance"],
    dependencies=[CurrentIdentity],
)


@router.get("/snapshot")
def team_finance_snapshot(team_id: str) -> Dict[str, Any]:
    try:
        snapshot = get_team_finance_snapshot(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute finance snapshot: {exc}",
        ) from exc
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No finance data for team {team_id}",
        )
    return snapshot.as_dict()


@router.get("/transactions")
def team_finance_transactions(
    team_id: str,
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    try:
        rows = list_team_financial_transactions(team_id, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load ledger: {exc}",
        ) from exc
    # Coerce each row's values to JSON-friendly primitives. The ledger may
    # contain Decimals / dates that the default serializer rejects.
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry: Dict[str, Any] = {}
        for key, value in row.items():
            if value is None or isinstance(value, (bool, int, float, str)):
                entry[str(key)] = value
            else:
                entry[str(key)] = str(value)
        cleaned.append(entry)
    return {"team_id": team_id, "count": len(cleaned), "transactions": cleaned}
