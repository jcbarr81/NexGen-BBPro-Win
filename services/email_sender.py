"""Transactional email sender (SendGrid HTTP API).

The cloud deployment has no built-in mail transport — Cloud Run blocks port 25
and there is no GCP email service — so outbound email goes through SendGrid's
v3 REST API over HTTPS (using ``httpx``, already a dependency; no SMTP).

Configuration is read from the environment, matching the app's existing
``os.environ`` convention (see ``NEXGEN_*`` vars):

* ``SENDGRID_API_KEY``      — SendGrid API key with Mail Send permission.
* ``INVITE_EMAIL_FROM``     — a verified single-sender / domain address.
* ``INVITE_EMAIL_FROM_NAME``— optional display name (default "NexGen BBPro").
* ``APP_BASE_URL``          — optional, for links in email bodies
                              (default "https://nexgen-bbpro.web.app").

Until ``SENDGRID_API_KEY`` and ``INVITE_EMAIL_FROM`` are both set, ``is_enabled``
returns False and callers surface a "not configured" message rather than failing
mysteriously.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

__all__ = ["EmailError", "is_enabled", "status", "app_base_url", "send_email"]

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_DEFAULT_FROM_NAME = "NexGen BBPro"
_DEFAULT_BASE_URL = "https://nexgen-bbpro.web.app"


class EmailError(RuntimeError):
    """Raised when an email send fails (misconfig or provider error)."""


def _api_key() -> str:
    return (os.environ.get("SENDGRID_API_KEY") or "").strip()


def _from_address() -> str:
    return (os.environ.get("INVITE_EMAIL_FROM") or "").strip()


def _from_name() -> str:
    return (os.environ.get("INVITE_EMAIL_FROM_NAME") or _DEFAULT_FROM_NAME).strip()


def app_base_url() -> str:
    return (os.environ.get("APP_BASE_URL") or _DEFAULT_BASE_URL).strip().rstrip("/")


def is_enabled() -> bool:
    """True when both the API key and a verified from-address are configured."""
    return bool(_api_key() and _from_address())


def status() -> Dict[str, Any]:
    """Config summary for the UI (never exposes the API key)."""
    return {
        "configured": is_enabled(),
        "from_address": _from_address() or None,
        "from_name": _from_name(),
        "provider": "sendgrid",
    }


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    """Send one email via SendGrid. Raises :class:`EmailError` on any failure.

    ``reply_to`` sets a Reply-To header (e.g. so a league broadcast's replies go
    back to the commissioner rather than the shared sender address).
    """
    to = (to or "").strip()
    if not to:
        raise EmailError("A recipient email address is required.")
    if not is_enabled():
        raise EmailError(
            "Email isn't configured yet — set SENDGRID_API_KEY and "
            "INVITE_EMAIL_FROM on the server."
        )

    import httpx

    content = []
    if text:
        content.append({"type": "text/plain", "value": text})
    content.append({"type": "text/html", "value": html})

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": _from_address(), "name": _from_name()},
        "subject": subject,
        "content": content,
    }
    reply_to = (reply_to or "").strip()
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    try:
        resp = httpx.post(
            _SENDGRID_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise EmailError(f"Could not reach the email provider: {exc}") from exc

    # SendGrid returns 202 Accepted on success.
    if resp.status_code not in (200, 201, 202):
        detail = ""
        try:
            body = resp.json()
            errors = body.get("errors") if isinstance(body, dict) else None
            if errors:
                detail = "; ".join(
                    str(e.get("message", e)) for e in errors if isinstance(e, dict)
                )
        except Exception:
            detail = (resp.text or "")[:200]
        raise EmailError(
            f"Email provider rejected the send (HTTP {resp.status_code})"
            + (f": {detail}" if detail else ".")
        )
