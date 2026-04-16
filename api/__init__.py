"""FastAPI sidecar for NexGen-BBPro Electron UI.

This package exposes the existing services/models over HTTP + WebSocket so a
Node.js / Electron frontend can drive the game without replacing any of the
current PyQt6 code. It is purely additive -- the PyQt app in ``main.py`` is not
affected by anything here.

Run locally::

    python -m api --port 8765
    # or, for hot reload during development:
    uvicorn api.app:app --reload --port 8765
"""

from __future__ import annotations

__all__ = ["create_app"]


def create_app():  # pragma: no cover - thin re-export
    from .app import create_app as _create_app

    return _create_app()
