"""GM finance queue endpoints (commissioner review).

Wraps :mod:`services.gm_finance_queue`:

- List pending owner decisions (arbitration + free-agency).
- Approve / reject individual rows.
- Apply approved decisions as a batch (writes contracts, rosters, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.gm_finance_queue import (
    apply_approved_queue_decisions,
    list_pending_queue_decisions,
    set_queue_review_status,
)

from ..security import require_bearer

router = APIRouter(prefix="/finance-queue", tags=["finance-queue"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)

# Plain-language labels for owner queue actions so the commissioner sees
# "Non-tender (release to free agency)" instead of the raw token.
_ACTION_LABELS = {
    "offer_raise": "Offer raise (tender at projected salary)",
    "hold": "Hold at current salary",
    "non_tender": "Non-tender (release to free agency)",
    "target": "Sign free agent",
    "monitor": "Monitor (no signing)",
    "pass": "Pass",
}


def _enrich_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach player names, salary context, and action labels to queue rows.

    item_id is the player id for both queue types; the raw rows are opaque
    (ids + tokens), which made review error-prone. Best-effort — a missing
    players file must not break the queue.
    """

    names: Dict[str, str] = {}
    try:
        from utils.player_loader import load_players_from_csv

        names = {
            p.player_id: f"{p.first_name} {p.last_name}".strip()
            for p in load_players_from_csv("data/players.csv")
        }
    except Exception:
        pass
    contracts: Dict[str, Any] = {}
    try:
        from services.contracts_service import load_contracts_payload

        raw = load_contracts_payload().get("players")
        if isinstance(raw, dict):
            contracts = raw
    except Exception:
        pass

    for row in rows:
        pid = str(row.get("item_id") or "").strip()
        row["player_name"] = names.get(pid) or pid
        contract = contracts.get(pid)
        row["current_salary"] = (
            contract.get("annual_salary") if isinstance(contract, dict) else None
        )
        payload = row.get("payload")
        row["projected_salary"] = (
            payload.get("projected_salary") if isinstance(payload, dict) else None
        )
        action = str(row.get("action") or "").strip()
        row["action_label"] = _ACTION_LABELS.get(action, action.replace("_", " "))
    return rows


@router.get("")
def list_queue(
    queue_type: Optional[str] = None,
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    rows = _enrich_rows(list_pending_queue_decisions(queue_type=queue_type))
    return {"count": len(rows), "rows": rows}


@router.post("/review")
def review(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    team_id = str(payload.get("team_id", "")).strip()
    queue_type = str(payload.get("queue_type", "")).strip()
    item_id = str(payload.get("item_id", "")).strip()
    review_status = str(payload.get("review_status", "")).strip()
    notes = payload.get("notes")
    if not (team_id and queue_type and item_id and review_status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team_id, queue_type, item_id, review_status are required.",
        )
    try:
        row = set_queue_review_status(
            team_id,
            queue_type=queue_type,
            item_id=item_id,
            review_status=review_status,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision {item_id} not found for {team_id}.",
        )
    return {"row": row}


@router.post("/apply-approved")
def apply_approved(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        result = apply_approved_queue_decisions()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    if not isinstance(result, dict):
        result = {"result": str(result)}
    return result
