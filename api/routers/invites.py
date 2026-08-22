"""Invite codes — commissioner generates, owner redeems (auto-admits).

Generate/list/revoke require the request's league (X-League-Id) + commissioner.
Redeem only needs a signed-in account + the code itself: the code resolves to its
league (top-level ``invites/{code}`` collection), so private-league codes work
without the redeemer knowing the league id.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from utils import path_utils

from ..security import require_account, require_bearer

router = APIRouter(tags=["invites"])

# Unambiguous alphabet (no 0/O/1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _require_commissioner(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    # require_bearer maps a commissioner membership to r="admin".
    if str(identity.get("r", "")).lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Commissioner access required."
        )
    return identity


def _league_of(identity: Dict[str, Any]) -> str:
    league = identity.get("league_id") or path_utils.get_active_league_id()
    if not league:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing league context."
        )
    return league


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _valid_email(addr: str) -> bool:
    addr = (addr or "").strip()
    return "@" in addr and "." in addr.split("@")[-1] and " " not in addr


def _invite_email_body(
    *, league_name: str, code: str, team_id: str, redeem_url: str, from_name: str
) -> tuple[str, str]:
    """Return (text, html) for an invite email."""
    team_line = (
        f"to own the {team_id} club" if team_id else "to own a team"
    )
    # A direct link that pre-fills the code on the redeem page.
    link = f"{redeem_url}?code={code}"
    text = (
        f"You've been invited {team_line} in {league_name} on NexGen BBPro.\n\n"
        f"Your invite code: {code}\n\n"
        f"To accept:\n"
        f"1. Open {link}\n"
        f"   (or go to {redeem_url} and enter the code)\n"
        f"2. Sign in (or create a free account).\n"
        f"3. The code claims your team.\n\n"
        f"— {from_name}"
    )
    html = (
        f"<p>You've been invited <b>{team_line}</b> in "
        f"<b>{league_name}</b> on NexGen BBPro.</p>"
        f"<p>Your invite code:</p>"
        f"<p style=\"font-size:22px;font-weight:700;letter-spacing:3px;"
        f"font-family:monospace\">{code}</p>"
        f"<p><a href=\"{link}\" style=\"display:inline-block;padding:10px 18px;"
        f"background:#c8811f;color:#fff;text-decoration:none;border-radius:6px;"
        f"font-weight:600\">Accept invite</a></p>"
        f"<p style=\"color:#888\">Or go to "
        f"<a href=\"{redeem_url}\">{redeem_url}</a> and enter the code after "
        f"signing in (or creating a free account).</p>"
        f"<p style=\"color:#888\">— {from_name}</p>"
    )
    return text, html


@router.get("/invites/email/status")
def invite_email_status(
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    """Whether server-side email is configured (so the UI can show a setup hint
    instead of letting the commissioner try to send into a void)."""
    from services import email_sender

    return email_sender.status()


@router.get("/invites/recipients")
def invite_recipients(
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    """Registered accounts (with email) the commissioner can pick to invite,
    each flagged with whether they're already in this league.

    Privacy: only a platform super-admin sees the full user directory. A regular
    league commissioner sees just their own league's members (so one league's
    commissioner can't harvest every user's email) — for anyone else they use
    the free-text "invite by email" box.
    """
    from services import firestore_store

    league = _league_of(identity)
    members = {
        str(m.get("uid")): m
        for m in firestore_store.list_members(league)
        if m and m.get("uid")
    }

    out = []
    if identity.get("super_admin"):
        for acct in firestore_store.list_accounts():
            if not acct:
                continue
            email = str(acct.get("email") or "").strip()
            if not email:
                continue
            uid = str(acct.get("uid") or acct.get("id") or "")
            mem = members.get(uid)
            out.append(
                {
                    "uid": uid,
                    "email": email,
                    "handle": acct.get("handle") or email.split("@")[0],
                    "in_league": mem is not None,
                    "team_id": (mem or {}).get("team_id") or "",
                }
            )
    else:
        # Regular commissioner: only this league's own members, hydrated with
        # their account email.
        for uid, mem in members.items():
            acct = firestore_store.get_account(uid) or {}
            email = str(acct.get("email") or "").strip()
            if not email:
                continue
            out.append(
                {
                    "uid": uid,
                    "email": email,
                    "handle": mem.get("handle") or acct.get("handle") or email.split("@")[0],
                    "in_league": True,
                    "team_id": mem.get("team_id") or "",
                }
            )

    out.sort(key=lambda r: (r["in_league"], r["handle"].lower()))
    return {"recipients": out, "count": len(out)}


@router.post("/invites/email")
def email_invites(
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    """Generate a unique single-use invite code for each recipient and email it.

    Body: ``{"team_id": "NYY"?, "recipients": ["a@x.com", {"email": "b@y.com",
    "team_id": "BOS"}]}``. ``team_id`` at the top level is the default for
    recipients that don't specify their own. Returns a per-recipient result.
    """
    from services import email_sender, firestore_store

    if not email_sender.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Email isn't configured yet. Set SENDGRID_API_KEY and "
                "INVITE_EMAIL_FROM on the server to send invites by email."
            ),
        )

    league = _league_of(identity)
    default_team = str((payload or {}).get("team_id", "")).strip()
    raw = (payload or {}).get("recipients") or []
    if not isinstance(raw, list) or not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one recipient is required.",
        )
    if len(raw) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please send to at most 50 recipients at a time.",
        )

    # Normalize + dedupe by email.
    norm: Dict[str, str] = {}  # email -> team_id
    for item in raw:
        if isinstance(item, str):
            email, team = item, default_team
        elif isinstance(item, dict):
            email = str(item.get("email", "")).strip()
            team = str(item.get("team_id", "") or default_team).strip()
        else:
            continue
        email = email.strip()
        if email and email.lower() not in {k.lower() for k in norm}:
            norm[email] = team

    league_rec = firestore_store.get_league(league) or {}
    league_name = league_rec.get("display_name") or league
    redeem_url = f"{email_sender.app_base_url()}/discover"
    from_name = email_sender.status().get("from_name") or "NexGen BBPro"

    results = []
    for email, team in norm.items():
        if not _valid_email(email):
            results.append(
                {"email": email, "team_id": team, "code": None, "sent": False,
                 "error": "Not a valid email address."}
            )
            continue
        code = _gen_code()
        try:
            firestore_store.create_invite(
                league, code=code, team_id=team,
                created_by=identity.get("u"), email=email,
            )
            text, html = _invite_email_body(
                league_name=league_name, code=code, team_id=team,
                redeem_url=redeem_url, from_name=from_name,
            )
            email_sender.send_email(
                to=email,
                subject=f"You're invited to own a team in {league_name}",
                html=html,
                text=text,
            )
            results.append(
                {"email": email, "team_id": team, "code": code, "sent": True, "error": None}
            )
        except email_sender.EmailError as exc:
            # Revoke the just-created code so a failed send doesn't leave a live
            # orphan invite lying around.
            try:
                firestore_store.revoke_invite(code)
            except Exception:
                pass
            results.append(
                {"email": email, "team_id": team, "code": None, "sent": False,
                 "error": str(exc)}
            )
        except Exception as exc:  # pragma: no cover - defensive
            results.append(
                {"email": email, "team_id": team, "code": None, "sent": False,
                 "error": f"Unexpected error: {exc}"}
            )

    sent = sum(1 for r in results if r["sent"])
    return {
        "results": results,
        "sent_count": sent,
        "failed_count": len(results) - sent,
    }


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def generate_invite(
    payload: Dict[str, Any] = Body(default={}),
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    team_id = str((payload or {}).get("team_id", "")).strip()
    code = _gen_code()
    firestore_store.create_invite(
        league, code=code, team_id=team_id, created_by=identity.get("u")
    )
    return {"code": code, "league_id": league, "team_id": team_id, "status": "open"}


@router.get("/invites")
def list_invites(identity: Dict[str, Any] = Depends(_require_commissioner)) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    return {"invites": [i for i in firestore_store.list_invites(league) if i]}


@router.post("/invites/{code}/revoke")
def revoke_invite(
    code: str, identity: Dict[str, Any] = Depends(_require_commissioner)
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    inv = firestore_store.get_invite(code)
    if not inv or inv.get("league_id") != league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found in this league."
        )
    firestore_store.revoke_invite(code)
    return {"code": code, "status": "revoked"}


@router.post("/invites/redeem")
def redeem_invite(
    payload: Dict[str, Any] = Body(...),
    account: Dict[str, Any] = Depends(require_account),
) -> Dict[str, Any]:
    from services import firestore_store
    from services import memberships as memberships_bridge

    uid = account.get("uid")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    code = str((payload or {}).get("code", "")).strip().upper()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An invite code is required.")
    inv = firestore_store.get_invite(code)
    if not inv or inv.get("status") != "open":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid, revoked, or already-used invite code."
        )
    if int(inv.get("uses", 0)) >= int(inv.get("max_uses", 1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invite has already been used.")

    league = inv.get("league_id")
    team_id = str(inv.get("team_id", "") or "")
    if firestore_store.get_member(league, uid):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already a member of this league.")

    acct = firestore_store.get_account(uid)
    handle = (acct or {}).get("handle") or uid
    member_status = "active" if team_id else "pending_team"
    firestore_store.set_member(
        league, uid, handle=handle, role="owner", team_id=team_id,
        status=member_status, joined_via="invite",
    )
    firestore_store.mark_invite_redeemed(code, redeemed_by=uid)

    if team_id:
        token = path_utils.set_request_league(league)
        try:
            memberships_bridge.provision_user(uid, "owner", team_id)
        finally:
            path_utils.reset_request_league(token)

    return {"league_id": league, "team_id": team_id, "status": member_status}
