"""Firebase Authentication ID-token verification (cloud multi-tenant only).

The SPA signs users in with the Firebase JS SDK and sends the resulting ID token
as ``Authorization: Bearer <idToken>``. Here we verify it with the firebase-admin
SDK, which fetches + caches Google's public keys and checks signature / audience /
expiry. On Cloud Run the SDK auto-initializes from the runtime service account
(ADC) and the ambient project id — no key file needed.

Everything is gated by ``NEXGEN_FIREBASE=1`` so local desktop / Electron / dev
runs never import firebase-admin or touch the network.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

_LOG = logging.getLogger("nexgen.firebase")
_init_lock = threading.Lock()
_initialized = False


def is_enabled() -> bool:
    return os.environ.get("NEXGEN_FIREBASE") == "1"


def init_firebase() -> None:
    """Initialize the firebase-admin app once (idempotent). No-op when disabled."""
    global _initialized
    if _initialized or not is_enabled():
        return
    with _init_lock:
        if _initialized:
            return
        try:
            import firebase_admin

            if not firebase_admin._apps:  # not yet initialized in this process
                firebase_admin.initialize_app()
            _initialized = True
            _LOG.info("firebase-admin initialized")
        except Exception:
            _LOG.exception("firebase-admin initialization failed")


def verify_firebase_token(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """Verify a ``Bearer <idToken>`` header. Returns the decoded claims
    (``uid``, ``email``, ...) or ``None`` when disabled / missing / invalid.

    Returning ``None`` (rather than raising) lets the caller fall back to the
    legacy HMAC token path for Electron / single-tenant.
    """
    if not is_enabled():
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    init_firebase()
    try:
        from firebase_admin import auth as fb_auth

        decoded = fb_auth.verify_id_token(token)
        # Normalize: firebase-admin uses "uid"; ensure email present (may be None).
        decoded.setdefault("uid", decoded.get("user_id"))
        return decoded
    except Exception:
        # Not a valid Firebase token (could be a legacy HMAC token) — let the
        # caller decide. Don't log at error level; this path is normal.
        return None
