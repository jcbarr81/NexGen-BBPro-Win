"""Public-league join requests + commissioner team assignment.

Owners request to join a PUBLIC league (X-League-Id from discovery); the
commissioner approves (assigning a team) or denies. Commissioners can also
(re)assign a member's team directly.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from utils import path_utils

from ..security import require_account, require_bearer

router = APIRouter(tags=["join-requests"])


def _require_commissioner(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
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


def _validate_and_provision(league: str, uid: str, role: str, team_id: str) -> None:
    """Validate team_id belongs to *league* and mirror the owner into users.txt.
    Runs inside the league's request context so get_data_dir() resolves correctly.
    """
    from services import memberships as memberships_bridge
    from utils.team_loader import load_teams

    token = path_utils.set_request_league(league)
    try:
        data_dir = path_utils.get_data_dir()
        valid = {t.team_id for t in load_teams(data_dir / "teams.csv")}
        if team_id not in valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown team_id {team_id!r} for this league.",
            )
        memberships_bridge.provision_user(uid, role, team_id)
    finally:
        path_utils.reset_request_league(token)


@router.post("/join-requests", status_code=status.HTTP_201_CREATED)
def request_to_join(
    payload: Dict[str, Any] = Body(default={}),
    account: Dict[str, Any] = Depends(require_account),
) -> Dict[str, Any]:
    from services import firestore_store

    uid = account.get("uid")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    league = path_utils.get_active_league_id()
    if not league:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing league context (X-League-Id).")
    cat = firestore_store.get_league(league)
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found.")
    if cat.get("visibility") != "public":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This league is private; you need an invite code to join.",
        )
    if firestore_store.get_member(league, uid):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are already a member of this league.")
    acct = firestore_store.get_account(uid)
    handle = (acct or {}).get("handle") or uid
    note = str((payload or {}).get("note", "")).strip()
    req = firestore_store.create_join_request(league, uid=uid, handle=handle, note=note)
    return {"request_id": req.get("request_id"), "status": "pending"}


@router.get("/join-requests")
def list_requests(identity: Dict[str, Any] = Depends(_require_commissioner)) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    return {"requests": [r for r in firestore_store.list_join_requests(league, status="pending") if r]}


@router.post("/join-requests/{request_id}/approve")
def approve_request(
    request_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    req = firestore_store.get_join_request(league, request_id)
    if not req or req.get("status") != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found or not pending.")
    team_id = str((payload or {}).get("team_id", "")).strip()
    if not team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A team_id is required to approve.")
    member_uid = req.get("uid")
    acct = firestore_store.get_account(member_uid)
    handle = (acct or {}).get("handle") or req.get("handle") or member_uid

    _validate_and_provision(league, member_uid, "owner", team_id)
    firestore_store.set_member(
        league, member_uid, handle=handle, role="owner", team_id=team_id,
        status="active", joined_via="request",
    )
    firestore_store.update_join_request(league, request_id, status="approved", assigned_team_id=team_id)
    return {"request_id": request_id, "status": "approved", "team_id": team_id}


@router.post("/join-requests/{request_id}/deny")
def deny_request(
    request_id: str, identity: Dict[str, Any] = Depends(_require_commissioner)
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    req = firestore_store.get_join_request(league, request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    firestore_store.update_join_request(league, request_id, status="rejected")
    return {"request_id": request_id, "status": "rejected"}


@router.post("/members/{member_uid}/assign-team")
def assign_team(
    member_uid: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    from services import firestore_store

    league = _league_of(identity)
    member = firestore_store.get_member(league, member_uid)
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in this league.")
    team_id = str((payload or {}).get("team_id", "")).strip()
    if not team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A team_id is required.")
    _validate_and_provision(league, member_uid, str(member.get("role") or "owner"), team_id)
    firestore_store.set_member_team(league, member_uid, team_id)
    return {"uid": member_uid, "team_id": team_id, "status": "active"}


def _league_member_emails(league: str) -> list[dict]:
    """Unique {uid, handle, email} for this league's members that have an email
    on file (from their account). De-duplicated by email."""
    from services import firestore_store

    seen: set[str] = set()
    out: list[dict] = []
    for m in firestore_store.list_members(league):
        if not m:
            continue
        uid = str(m.get("uid") or "")
        if not uid:
            continue
        acct = firestore_store.get_account(uid) or {}
        email = str(acct.get("email") or "").strip()
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        out.append(
            {
                "uid": uid,
                "handle": m.get("handle") or acct.get("handle") or email.split("@")[0],
                "email": email,
            }
        )
    return out


@router.post("/league/message")
def message_league(
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(_require_commissioner),
) -> Dict[str, Any]:
    """Commissioner broadcast: email every league member who has an address on
    file. Replies go back to the commissioner (Reply-To), and each member is a
    separate send so recipients never see each other's addresses.
    """
    from services import email_sender, firestore_store

    if not email_sender.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Email isn't configured yet. Set SENDGRID_API_KEY and "
                "INVITE_EMAIL_FROM on the server to message the league."
            ),
        )

    subject = str((payload or {}).get("subject", "")).strip()
    body = str((payload or {}).get("body", "")).strip()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A subject is required."
        )
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A message body is required."
        )

    league = _league_of(identity)
    recipients = _league_member_emails(league)
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No league members have an email address on file.",
        )

    league_rec = firestore_store.get_league(league) or {}
    league_name = league_rec.get("display_name") or league
    reply_to = str(identity.get("email") or "").strip() or None

    # Escape the body for HTML and keep the author's line breaks.
    import html as _html

    body_html = _html.escape(body).replace("\n", "<br>")
    html = (
        f"<div style=\"font-family:sans-serif\">"
        f"<p>{body_html}</p>"
        f"<hr style=\"border:none;border-top:1px solid #ddd;margin:16px 0\">"
        f"<p style=\"color:#888;font-size:12px\">"
        f"Sent by the commissioner of {_html.escape(league_name)} via NexGen BBPro."
        f"</p></div>"
    )
    text = f"{body}\n\n—\nSent by the commissioner of {league_name} via NexGen BBPro."

    results = []
    for r in recipients:
        try:
            email_sender.send_email(
                to=r["email"], subject=subject, html=html, text=text, reply_to=reply_to
            )
            results.append({"email": r["email"], "handle": r["handle"], "sent": True, "error": None})
        except email_sender.EmailError as exc:
            results.append(
                {"email": r["email"], "handle": r["handle"], "sent": False, "error": str(exc)}
            )
        except Exception as exc:  # pragma: no cover - defensive
            results.append(
                {"email": r["email"], "handle": r["handle"], "sent": False,
                 "error": f"Unexpected error: {exc}"}
            )

    sent = sum(1 for r in results if r["sent"])
    return {"results": results, "sent_count": sent, "failed_count": len(results) - sent}
