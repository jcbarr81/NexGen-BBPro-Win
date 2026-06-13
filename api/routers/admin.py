"""Admin-only endpoints.

Currently covers user management (list / add / edit) using
:mod:`utils.user_manager`. All routes require the caller's session role to be
``"admin"`` -- owner-role tokens get a 403.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from utils import user_manager

from ..security import require_bearer

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return identity


AdminIdentity = Depends(_require_admin)


class NewUserPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(admin|owner)$")
    team_id: str = ""


class EditUserPayload(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|owner)$")
    team_id: Optional[str] = None


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    # Never ship the stored password hash -- not useful, potentially sensitive.
    return {
        "username": user.get("username", ""),
        "role": user.get("role", ""),
        "team_id": user.get("team_id", "") or "",
    }


def _handle_map() -> Dict[str, str]:
    """uid -> display-name (handle) for this league's members, from Firestore.
    Empty in local/single-tenant mode. Lets the admin Users list show readable
    names instead of raw Firebase uids."""
    try:
        from api import firebase_auth

        if not firebase_auth.is_enabled():
            return {}
        from utils import path_utils
        from services import firestore_store

        league = path_utils.get_active_league_id()
        if not league:
            return {}
        out: Dict[str, str] = {}
        for m in firestore_store.list_members(league):
            uid = (m or {}).get("uid")
            handle = (m or {}).get("handle")
            if uid and handle:
                out[uid] = handle
        return out
    except Exception:
        return {}


@router.get("/users")
def list_users(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    handles = _handle_map()
    users: List[Dict[str, Any]] = []
    for u in user_manager.load_users():
        pub = _public_user(u)
        # Display name = Firestore handle if we have one, else the username.
        pub["display_name"] = handles.get(pub["username"]) or pub["username"]
        users.append(pub)
    users.sort(key=lambda u: u["display_name"].lower())
    return {"count": len(users), "users": users}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: NewUserPayload,
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        user_manager.add_user(
            payload.username,
            payload.password,
            payload.role,
            payload.team_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _public_user(
        {
            "username": payload.username,
            "role": payload.role,
            "team_id": payload.team_id,
        }
    )


@router.patch("/users/{username}")
def edit_user(
    username: str,
    payload: EditUserPayload,
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        user_manager.update_user(
            username=username,
            new_password=payload.password,
            new_team_id=payload.team_id,
            new_role=payload.role,
        )
    except ValueError as exc:
        message = str(exc).lower()
        if "not found" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Keep the Firestore membership in sync so the owner's "My Leagues" (and the
    # identity bridge when they enter) reflect the new team — users.txt alone
    # isn't what owners read in the cloud.
    if payload.team_id is not None:
        try:
            from api import firebase_auth

            if firebase_auth.is_enabled():
                from utils import path_utils
                from services import firestore_store

                league = path_utils.get_active_league_id()
                if league and firestore_store.get_member(league, username):
                    firestore_store.set_member_team(league, username, payload.team_id)
        except Exception:
            logging.getLogger("nexgen.admin").exception(
                "firestore member-team sync failed for %s", username
            )

    updated = next(
        (_public_user(u) for u in user_manager.load_users() if u.get("username") == username),
        None,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return updated
