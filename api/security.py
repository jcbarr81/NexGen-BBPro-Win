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


async def require_bearer(
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    """FastAPI dependency enforcing a valid bearer token."""

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    return decode_token(token)


CurrentIdentity = Depends(require_bearer)
