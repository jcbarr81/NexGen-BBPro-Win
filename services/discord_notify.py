"""Post league activity to Discord from the server.

``scripts/announce_release.py`` posts release notes from a developer's machine.
This is the server-side equivalent: it runs inside Cloud Run, where the
git-ignored ``scripts/.discord_webhook`` file does not exist, so the webhook
comes from the ``NEXGEN_DISCORD_WEBHOOK_URL`` environment variable only.

Amateur draft posts (on the clock, picks) go to their own channel when
``NEXGEN_DISCORD_DRAFT_WEBHOOK_URL`` is set (8.6.6), else to the main one.

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
DRAFT_WEBHOOK_ENV = "NEXGEN_DISCORD_DRAFT_WEBHOOK_URL"

# Channels a post can go to: the main league channel and the draft channel.
GENERAL = "general"
DRAFT = "draft"

# Discord rejects anything longer; we truncate rather than lose the post.
MAX_CONTENT = 1900

USER_AGENT = "NexGen-BBPro-Server/1.0"

_TIMEOUT_SECONDS = 10


def webhook_url(channel: str = GENERAL) -> Optional[str]:
    """The webhook for ``channel``, or ``None`` when Discord posting is off.

    The draft channel falls back to the main webhook when it has none of its
    own."""

    if channel == DRAFT:
        value = (os.environ.get(DRAFT_WEBHOOK_ENV) or "").strip()
        if value:
            return value
    value = (os.environ.get(WEBHOOK_ENV) or "").strip()
    return value or None


def is_configured(channel: str = GENERAL) -> bool:
    return webhook_url(channel) is not None


def post(content: str, *, username: str = "NexGen BBPro", channel: str = GENERAL) -> bool:
    """Post *content* to ``channel``. Returns True when Discord accepted it.

    Never raises: callers are reporting on work that has already happened.
    """

    url = webhook_url(channel)
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


__all__ = [
    "DRAFT",
    "DRAFT_WEBHOOK_ENV",
    "GENERAL",
    "WEBHOOK_ENV",
    "is_configured",
    "post",
    "webhook_url",
]
