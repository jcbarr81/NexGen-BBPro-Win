"""League activity feed (transaction ledger).

Wraps :func:`services.transaction_log.load_transactions`. Every roster
move, trade leg, signing, and DL placement we record on the server flows
into ``data/transactions.csv`` -- this endpoint surfaces it for the
React feed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from services.transaction_log import load_transactions

from ..security import CurrentIdentity

router = APIRouter(prefix="/activity", tags=["activity"], dependencies=[CurrentIdentity])


@router.get("")
def get_activity(
    team_id: Optional[str] = Query(default=None, description="Filter by team"),
    action: Optional[str] = Query(
        default=None,
        description="Comma-separated action types (e.g. trade_in,trade_out,assign,cut)",
    ),
    limit: int = Query(default=200, ge=1, le=2000),
) -> Dict[str, Any]:
    actions: Optional[List[str]] = None
    if action:
        actions = [a.strip() for a in action.split(",") if a.strip()]
    rows = load_transactions(team_id=team_id, actions=actions, limit=limit)
    return {"count": len(rows), "transactions": rows}
