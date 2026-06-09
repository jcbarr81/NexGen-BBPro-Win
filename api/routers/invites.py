"""Invite codes — commissioner generates, owner redeems (auto-admits).

Generate/list/revoke require the request's league (X-League-Id) + commissioner.
Redeem only needs a signed-in account + the code itself: the code resolves to its
league (top-level ``invites/{code}`` collection), so private-league codes work
without the redeemer knowing the league id.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from utils import path_utils

from ..security import require_account, require_bearer

router = APIRouter(tags=["invites"])

# Unambiguous alphabet (no 0/O/1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _require_commissioner(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    # require_bearer maps a commissioner membership to r="admin".
    if str(identity.get("r", "")).lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Commissioner access required."
        )
    return identity


def _league_of(identity: Dict[str, Any]) -> str:
    league = identity.get("league_id") or path_utils.get_active_league_id()
    if not league:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing league context."
        )
    return league


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def generate_invite(
    payload: Dict[str, Any] = Body(default={}),
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    team_id = str((payload or {}).get("team_id", "")).strip()
    code = _gen_code()
    firestore_store.create_invite(
        league, code=code, team_id=team_id, created_by=identity.get("u")
    )
    return {"code": code, "league_id": league, "team_id": team_id, "status": "open"}


@router.get("/invites")
def list_invites(identity: Dict[str, Any] = Depends(_require_commissioner)) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    return {"invites": [i for i in firestore_store.list_invites(league) if i]}


@router.post("/invites/{code}/revoke")
def revoke_invite(
    code: str, identity: Dict[str, Any] = Depends(_require_commissioner)
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    inv = firestore_store.get_invite(code)
    if not inv or inv.get("league_id") != league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found in this league."
        )
    firestore_store.revoke_invite(code)
    return {"code": code, "status": "revoked"}


@router.post("/invites/redeem")
def redeem_invite(
    payload: Dict[str, Any] = Body(...),
    account: Dict[str, Any] = Depends(require_account),
) -> Dict[str, Any]:
    from services import firestore_store
    from services import memberships as memberships_bridge

    uid = account.get("uid")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    code = str((payload or {}).get("code", "")).strip().upper()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An invite code is required.")
    inv = firestore_store.get_invite(code)
    if not inv or inv.get("status") != "open":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid, revoked, or already-used invite code."
        )
    if int(inv.get("uses", 0)) >= int(inv.get("max_uses", 1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invite has already been used.")

    league = inv.get("league_id")
    team_id = str(inv.get("team_id", "") or "")
    if firestore_store.get_member(league, uid):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already a member of this league.")

    acct = firestore_store.get_account(uid)
    handle = (acct or {}).get("handle") or uid
    member_status = "active" if team_id else "pending_team"
    firestore_store.set_member(
        league, uid, handle=handle, role="owner", team_id=team_id,
        status=member_status, joined_via="invite",
    )
    firestore_store.mark_invite_redeemed(code, redeemed_by=uid)

    if team_id:
        token = path_utils.set_request_league(league)
        try:
            memberships_bridge.provision_user(uid, "owner", team_id)
        finally:
            path_utils.reset_request_league(token)

    return {"league_id": league, "team_id": team_id, "status": member_status}
