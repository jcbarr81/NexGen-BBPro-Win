"""Authentication endpoints backed by the existing ``users.txt`` store."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from utils.user_manager import load_users, verify_user_password

from ..schemas import LoginRequest, LoginResponse
from ..security import issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    users = load_users()
    candidate = next(
        (u for u in users if u["username"].lower() == payload.username.strip().lower()),
        None,
    )
    if candidate is None or not verify_user_password(payload.password, candidate["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = issue_token(
        username=candidate["username"],
        role=candidate.get("role", ""),
        team_id=candidate.get("team_id", "") or "",
    )
    return LoginResponse(
        token=token,
        username=candidate["username"],
        role=candidate.get("role", ""),
        team_id=candidate.get("team_id", "") or "",
    )
