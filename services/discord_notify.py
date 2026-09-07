"""Post league activity to Discord from the server.

``scripts/announce_release.py`` posts release notes from a developer's machine.
This is the server-side equivalent: it runs inside Cloud Run, where the
git-ignored ``scripts/.discord_webhook`` file does not exist, so the webhook
comes from the ``NEXGEN_DISCORD_WEBHOOK_URL`` environment variable only.

Posting must never affect the thing being reported on. Every entry point here
swallows its own failures: a Discord outage, a revoked webhook or a network
blip must not fail a simulation that has already been persisted.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

WEBHOOK_ENV = "NEXGEN_DISCORD_WEBHOOK_URL"

# Discord rejects anything longer; we truncate rather than lose the post.
MAX_CONTENT = 1900

USER_AGENT = "NexGen-BBPro-Server/1.0"

_TIMEOUT_SECONDS = 10


def webhook_url() -> Optional[str]:
    """The configured webhook, or ``None`` when Discord posting is off."""

    value = (os.environ.get(WEBHOOK_ENV) or "").strip()
    return value or None


def is_configured() -> bool:
    return webhook_url() is not None


def post(content: str, *, username: str = "NexGen BBPro") -> bool:
    """Post *content*. Returns True when Discord accepted it.

    Never raises: callers are reporting on work that has already happened.
    """

    url = webhook_url()
    if not url:
        return False
    text = (content or "").strip()
    if not text:
        return False
    if len(text) > MAX_CONTENT:
        text = text[: MAX_CONTENT - 1] + "…"

    payload = json.dumps({"content": text, "username": username}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            # Discord sits behind Cloudflare, which rejects the default
            # "Python-urllib/x" User-Agent with HTTP 403 / error 1010. Send a
            # real one. scripts/announce_release.py hit this first.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            # Discord returns 204 No Content on a successful webhook post.
            return 200 <= int(response.status) < 300
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        _record(f"HTTP {exc.code} from Discord")
        return False
    except Exception as exc:  # pragma: no cover - network dependent
        _record(f"{type(exc).__name__}: {exc}")
        return False


def _record(message: str) -> None:
    """Leave a breadcrumb where it can actually be read.

    ``nexgen.*`` logging does not surface in Cloud Run, so a failed post writes
    into the league's data directory, which rides the normal push to durable
    storage — the same trick the box score diagnostics use.
    """

    try:
        from datetime import datetime, timezone

        from utils.path_utils import get_data_dir

        path = get_data_dir() / "discord_errors.log"
        stamp = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except Exception:  # pragma: no cover - diagnostics must never raise
        pass


__all__ = ["WEBHOOK_ENV", "is_configured", "post", "webhook_url"]
