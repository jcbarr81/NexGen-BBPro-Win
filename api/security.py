"""Authentication + session-token plumbing for the sidecar.

The Electron parent spawns the sidecar and reads a per-launch token that it
must present on every subsequent request. Because the sidecar only binds
127.0.0.1 this is primarily belt-and-braces protection against other local
processes poking at the port.

Tokens are HMAC-signed ``(username, role, team_id, issued_at)`` payloads using
a secret generated fresh each process start and written to
``%LOCALAPPDATA%/NexGen-BBPro/session.token`` so Electron can read it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, Header, HTTPException, status

from utils.path_utils import get_data_root


_SECRET: bytes = secrets.token_bytes(32)
_LAUNCH_TOKEN: str | None = None
_DEFAULT_TTL_SECONDS = 60 * 60 * 12  # 12h


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload: bytes) -> str:
    mac = hmac.new(_SECRET, payload, hashlib.sha256).digest()
    return _b64url_encode(mac)


def issue_token(
    *,
    username: str,
    role: str,
    team_id: str = "",
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Create a signed session token for *username*."""

    body = {
        "u": username,
        "r": role,
        "t": team_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + int(ttl_seconds),
    }
    payload = _b64url_encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(payload.encode('ascii'))}"


def decode_token(token: str) -> Dict[str, Any]:
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token"
        ) from exc

    expected = _sign(payload_b64.encode("ascii"))
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature"
        )

    try:
        body = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        ) from exc

    if int(body.get("exp", 0)) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    return body


def issue_launch_token() -> str:
    """Mint and persist the per-launch token Electron reads at startup."""

    global _LAUNCH_TOKEN
    token = issue_token(username="__electron__", role="launch", ttl_seconds=_DEFAULT_TTL_SECONDS)
    _LAUNCH_TOKEN = token

    try:
        target: Path = get_data_root() / "session.token"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(token, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except OSError:
        # Non-fatal: Electron can still read the token off stdout.
        pass
    return token


def get_launch_token() -> str | None:
    return _LAUNCH_TOKEN


def _legacy_bearer(authorization: str | None) -> Dict[str, Any]:
    """Decode a legacy per-process HMAC token (Electron / single-tenant)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    return decode_token(token)


def super_admin_emails() -> set[str]:
    """Allow-list of platform-owner emails (global admins), from the
    NEXGEN_SUPER_ADMINS env var (comma-separated)."""
    raw = os.environ.get("NEXGEN_SUPER_ADMINS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_super_admin(email: str | None) -> bool:
    e = str(email or "").strip().lower()
    return bool(e) and e in super_admin_emails()


def _identity_from_membership(decoded: Dict[str, Any]) -> Dict[str, Any]:
    """Map a verified Firebase user + the request's league → the legacy identity
    dict (``{u, r, t}``) the existing routers expect.

    A commissioner membership is surfaced as ``r="admin"`` so the ~15
    ``_require_admin`` checks pass unchanged; the true membership role is kept as
    ``mr`` for endpoints that must tell a league commissioner from a global admin.
    """
    from utils import path_utils
    from services import firestore_store

    uid = decoded.get("uid")
    email = str(decoded.get("email") or "").strip().lower()
    league = path_utils.get_active_league_id()
    if not league:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing league context (X-League-Id header required).",
        )
    # Global super-admin (platform owner): admin in EVERY league, no membership
    # required. Allow-list of emails from the NEXGEN_SUPER_ADMINS env var.
    if email and email in super_admin_emails():
        return {
            "u": uid,
            "r": "admin",
            "t": "",
            "mr": "super_admin",
            "email": email,
            "handle": decoded.get("name"),
            "league_id": league,
            "super_admin": True,
        }
    member = firestore_store.get_member(league, uid)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this league.",
        )
    role = str(member.get("role") or "owner")
    return {
        "u": uid,
        "r": "admin" if role == "commissioner" else role,
        "t": str(member.get("team_id") or ""),
        "mr": role,
        "email": decoded.get("email"),
        "handle": member.get("handle"),
        "league_id": league,
    }


def require_bearer(
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    """League-scoped identity. Cloud: verify a Firebase ID token and resolve the
    caller's membership in the request's league. Local/Electron: legacy HMAC token.
    Same ``{u, r, t}`` shape either way, so existing routers are unchanged.

    Deliberately a plain ``def``: token verification + the Firestore membership
    lookup are synchronous network I/O. As an ``async def`` they ran ON the
    event loop, serializing every concurrent request behind each auth RTT —
    sync dependencies get FastAPI's threadpool instead. (The lookup itself is
    also TTL-cached in ``services.firestore_store``.)
    """
    from api import firebase_auth

    if firebase_auth.is_enabled():
        decoded = firebase_auth.verify_firebase_token(authorization)
        if decoded is not None:
            return _identity_from_membership(decoded)
    return _legacy_bearer(authorization)


def require_account(
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    """Identity WITHOUT requiring league membership — for signup / discovery /
    invite-redeem / create-league endpoints. Returns ``{uid, email}``.
    """
    from api import firebase_auth

    if firebase_auth.is_enabled():
        decoded = firebase_auth.verify_firebase_token(authorization)
        if decoded is not None:
            return {"uid": decoded.get("uid"), "email": decoded.get("email")}
    # Local/dev fallback: accept a legacy token and treat its username as the uid.
    legacy = _legacy_bearer(authorization)
    return {"uid": legacy.get("u"), "email": None, "_legacy": legacy}


CurrentIdentity = Depends(require_bearer)
CurrentAccount = Depends(require_account)
