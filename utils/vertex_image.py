"""Google Vertex AI Imagen image generation (cloud-native logo/avatar renderer).

The GCP-native alternative to the OpenAI gpt-image-1 path: on Cloud Run it
authenticates with the runtime service account (ADC) — no external API key. We
call Imagen's ``:predict`` REST endpoint directly with ``httpx`` + ``google-auth``
(both already in the cloud image via firebase-admin) rather than pulling in the
heavy ``google-cloud-aiplatform`` SDK.

Gated by ``NEXGEN_VERTEX_IMAGES=1`` so local desktop / dev runs never touch the
network or require GCP credentials.

Public surface mirrors what ``logo_generator`` needs:
  * ``is_available()`` -> bool
  * ``status()``       -> {"status", "ok", "message"}
  * ``generate_png(prompt, size)`` -> PNG bytes
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

_LOG = logging.getLogger("nexgen.vertex_image")

# Imagen model + region. Overridable via env without a code change.
# Default to a "fast" model: the base ``imagen-3.0-generate`` quota is only
# 1 req/min (instant 429 on a batch); ``imagen-4.0-fast-generate`` allows
# 20/min and is cheaper — plenty for logos/avatars.
_MODEL = os.environ.get("NEXGEN_VERTEX_IMAGE_MODEL", "imagen-4.0-fast-generate-001")
_LOCATION = os.environ.get("NEXGEN_VERTEX_LOCATION", "us-central1")
_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Pace requests to stay under the per-minute quota (20/min ≈ 1 per 3s; use a bit
# more headroom) and retry on 429 with exponential backoff. The logo/avatar jobs
# call this sequentially from one worker thread, so a simple lock + timestamp is
# enough.
_MIN_INTERVAL_S = float(os.environ.get("NEXGEN_VERTEX_MIN_INTERVAL", "3.5"))
_MAX_RETRIES = int(os.environ.get("NEXGEN_VERTEX_MAX_RETRIES", "5"))
_pace_lock = threading.Lock()
_last_call_ts = 0.0

_creds = None  # cached google.auth credentials


def is_enabled() -> bool:
    return os.environ.get("NEXGEN_VERTEX_IMAGES") == "1"


def _project() -> Optional[str]:
    """Resolve the GCP project: explicit env first, else Application Default
    Credentials (the Cloud Run runtime service account)."""
    for var in ("NEXGEN_VERTEX_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
        val = os.environ.get(var)
        if val:
            return val
    try:
        import google.auth

        _, project = google.auth.default()
        return project
    except Exception:  # pragma: no cover - defensive
        return None


def _deps_importable() -> bool:
    try:
        import google.auth  # noqa: F401
        import httpx  # noqa: F401

        return True
    except Exception:
        return False


def is_available() -> bool:
    """True when Vertex image generation can run (enabled, deps present, project)."""
    return is_enabled() and _deps_importable() and bool(_project())


def status() -> Dict[str, Any]:
    if not is_enabled():
        return {"status": "disabled", "ok": False, "message": "Vertex image generation is disabled."}
    if not _deps_importable():
        return {
            "status": "missing_dependency",
            "ok": False,
            "message": "google-auth / httpx are not available in this image.",
        }
    if not _project():
        return {
            "status": "missing_project",
            "ok": False,
            "message": "Could not resolve a GCP project for Vertex AI.",
        }
    return {
        "status": "ok",
        "ok": True,
        "message": f"Vertex AI Imagen ready ({_MODEL} @ {_LOCATION}).",
    }


def _access_token() -> Tuple[str, str]:
    """Return (access_token, project) from Application Default Credentials,
    refreshing the cached credential as needed."""
    global _creds
    import google.auth
    from google.auth.transport.requests import Request

    if _creds is None:
        _creds, _ = google.auth.default(scopes=[_SCOPE])
    if not _creds.valid:
        _creds.refresh(Request())
    project = _project()
    if not project:
        raise RuntimeError("No GCP project for Vertex AI.")
    return _creds.token, project


def _throttle() -> None:
    """Block until at least ``_MIN_INTERVAL_S`` has elapsed since the last call,
    keeping us under the per-minute quota across sequential generations."""
    global _last_call_ts
    with _pace_lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.monotonic()


def generate_png(prompt: str, size: int = 1024) -> bytes:
    """Generate a single square image for *prompt* and return PNG bytes.

    Paces requests + retries on 429 (rate limit) with exponential backoff.
    Raises RuntimeError if Vertex isn't available / the request keeps failing so
    the caller can fall back to another engine.
    """
    if not is_available():
        raise RuntimeError("Vertex AI Imagen is not available.")
    import httpx

    token, project = _access_token()
    url = (
        f"https://{_LOCATION}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{_LOCATION}/publishers/google/models/{_MODEL}:predict"
    )
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    backoff = 8.0
    last_err = ""
    for attempt in range(_MAX_RETRIES + 1):
        _throttle()
        resp = httpx.post(url, headers=headers, json=body, timeout=120.0)
        if resp.status_code == 200:
            preds = (resp.json() or {}).get("predictions") or []
            if not preds:
                raise RuntimeError("Vertex AI returned no image (prompt may have been filtered).")
            b64 = preds[0].get("bytesBase64Encoded")
            if not b64:
                raise RuntimeError("Vertex AI prediction had no image bytes.")
            return base64.b64decode(b64)
        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            # Rate limited — wait out the per-minute window and retry.
            _LOG.warning("Vertex Imagen 429 (attempt %d); backing off %.0fs", attempt + 1, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue
        last_err = f"{resp.status_code}: {resp.text[:300]}"
        break
    raise RuntimeError(f"Vertex Imagen error {last_err}")
