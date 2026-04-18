"""OpenAI client status + key management (admin-only).

Lets the Electron UI tell the operator whether the detailed logo/avatar
renderer (gpt-image-1) is available, and write an API key into
``config.ini`` without having to edit the file by hand.
"""

from __future__ import annotations

import configparser
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from utils.path_utils import get_base_dir

from ..security import require_bearer

router = APIRouter(prefix="/ai", tags=["ai"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


def _client_snapshot() -> Dict[str, Any]:
    """Read the *current* client status. Deferred import because
    ``utils.openai_client`` does its init at import time."""

    from utils import openai_client

    return {
        "status": openai_client.CLIENT_STATUS,
        "ok": openai_client.CLIENT_STATUS == openai_client.CLIENT_STATUS_OK,
        "message": openai_client.get_client_status_message(),
    }


@router.get("/status")
def ai_status(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    return _client_snapshot()


@router.post("/api-key")
def set_api_key(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Persist the OpenAI API key to ``config.ini`` and reinitialise the client.

    We deliberately do NOT echo the key back in the response. The only
    feedback the caller gets is the new client status snapshot.
    """

    key = str(payload.get("api_key", "")).strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_key is required.",
        )

    config_path = get_base_dir() / "config.ini"
    parser = configparser.ConfigParser()
    if config_path.exists():
        try:
            parser.read(config_path, encoding="utf-8")
        except configparser.Error:
            parser = configparser.ConfigParser()
    if not parser.has_section("OpenAIkey"):
        parser.add_section("OpenAIkey")
    parser.set("OpenAIkey", "key", key)
    try:
        with config_path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not write config.ini: {exc}",
        ) from exc

    # Rebuild the cached client so subsequent logo/avatar calls pick up the key.
    try:
        import importlib

        from utils import openai_client

        importlib.reload(openai_client)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Key saved but client reload failed: {exc}",
        ) from exc

    return _client_snapshot()
