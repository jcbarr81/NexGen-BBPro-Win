"""Public-league discovery — Firebase-authenticated, no membership required.

Owners without an invite code browse PUBLIC leagues here and request to join
(see join_requests). PRIVATE leagues are never returned; they're only reachable
with a specific invite code.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..security import require_account

router = APIRouter(prefix="/leagues", tags=["discovery"])


@router.get("/public")
def public_leagues(account: Dict[str, Any] = Depends(require_account)) -> Dict[str, Any]:
    from services import firestore_store

    uid = account.get("uid")
    mine = {
        m.get("league_id") for m in firestore_store.list_user_memberships(uid) if m
    }
    out = []
    for lg in firestore_store.list_public_leagues():
        if not lg or lg.get("id") in mine:
            continue
        out.append(
            {
                "league_id": lg.get("id"),
                "display_name": lg.get("display_name"),
            }
        )
    return {"leagues": out}
