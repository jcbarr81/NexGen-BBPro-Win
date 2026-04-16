"""Admin-only endpoints.

Currently covers user management (list / add / edit) using
:mod:`utils.user_manager`. All routes require the caller's session role to be
``"admin"`` -- owner-role tokens get a 403.
"""

from __future__ import annotations

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


@router.get("/users")
def list_users(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    users: List[Dict[str, Any]] = [_public_user(u) for u in user_manager.load_users()]
    users.sort(key=lambda u: u["username"].lower())
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

    updated = next(
        (_public_user(u) for u in user_manager.load_users() if u.get("username") == username),
        None,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return updated
