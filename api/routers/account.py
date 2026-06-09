"""Global account endpoints — Firebase-authenticated, no league context required.

A signed-in Firebase user registers their app profile here: a display ``handle``
and a ``package`` (commissioner = can create/run leagues, owner = joins leagues).
Profiles live in Firestore (``accounts/{uid}``).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..security import require_account

router = APIRouter(prefix="/account", tags=["account"])

_PACKAGES = {"commissioner", "owner"}


@router.post("/signup")
def signup(
    payload: Dict[str, Any] = Body(...),
    account: Dict[str, Any] = Depends(require_account),
) -> Dict[str, Any]:
    from services import firestore_store

    uid = account.get("uid")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    handle = str(payload.get("handle", "")).strip()
    package = str(payload.get("package", "")).strip().lower()
    if not handle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A display name (handle) is required."
        )
    if package not in _PACKAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="package must be 'commissioner' or 'owner'.",
        )
    email = account.get("email") or ""
    firestore_store.upsert_account(uid, email=email, handle=handle, package=package)
    return {"uid": uid, "handle": handle, "package": package, "email": email}


@router.get("/me")
def me(account: Dict[str, Any] = Depends(require_account)) -> Dict[str, Any]:
    from services import firestore_store
    from ..security import is_super_admin

    uid = account.get("uid")
    acct = firestore_store.get_account(uid)
    leagues = []
    for m in firestore_store.list_user_memberships(uid):
        if not m:
            continue
        lid = m.get("league_id")
        cat = firestore_store.get_league(lid) if lid else None
        leagues.append(
            {
                "league_id": lid,
                "role": m.get("role"),
                "team_id": m.get("team_id"),
                "status": m.get("status"),
                "display_name": (cat or {}).get("display_name"),
                "visibility": (cat or {}).get("visibility"),
            }
        )
    result: Dict[str, Any] = {"account": acct, "leagues": leagues}
    if is_super_admin(account.get("email")):
        result["super_admin"] = True
        result["all_leagues"] = [
            {
                "league_id": lg.get("id"),
                "display_name": lg.get("display_name"),
                "visibility": lg.get("visibility"),
                "commissioner_uid": lg.get("commissioner_uid"),
            }
            for lg in firestore_store.list_all_leagues()
            if lg
        ]
    return result
