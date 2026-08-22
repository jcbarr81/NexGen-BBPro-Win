"""Firestore-backed multi-tenant control plane.

Holds the data that must be durable and concurrency-safe across many leagues and
owners — and that we explicitly DON'T trust to the working-copy/GCS sync layer
(which once silently deleted whole leagues):

    accounts/{uid}                                  global account profile
    leagues/{league_id}                             control-plane catalog (visibility, commissioner)
    leagues/{league_id}/members/{uid}               membership (role, team)
    leagues/{league_id}/invites/{code}              invite codes
    leagues/{league_id}/join_requests/{request_id}  public-league join requests

Bulky per-league GAME data (players.csv, rosters, standings, season_state,
users.txt, ...) stays on the working-copy/GCS model.

All access goes through firebase-admin's Firestore client (ADC on Cloud Run).
Guarded by NEXGEN_FIREBASE=1; callers handle the disabled/local case.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

_LOG = logging.getLogger("nexgen.firestore")

# ---------------------------------------------------------------------------
# Membership TTL cache.
#
# get_member() runs on EVERY authenticated request (require_bearer resolves the
# caller's league role), so an uncached Firestore round trip added tens of ms
# to every API call. Memberships change rarely (invite accepted, team claimed,
# role edit) — a short TTL plus explicit invalidation from the mutators keeps
# identity fresh while eliminating the per-request RTT.
# ---------------------------------------------------------------------------
_MEMBER_CACHE: Dict[Tuple[str, str], Tuple[float, Optional[Dict[str, Any]]]] = {}
_MEMBER_CACHE_TTL_SECONDS = 45.0
_MEMBER_CACHE_MAX = 4096
_MEMBER_CACHE_LOCK = threading.Lock()


def invalidate_member_cache(league_id: str | None = None, uid: str | None = None) -> None:
    """Drop cached membership rows. With both args, one entry; with only
    league_id, every member of that league; with neither, everything."""
    with _MEMBER_CACHE_LOCK:
        if league_id and uid:
            _MEMBER_CACHE.pop((league_id, uid), None)
        elif league_id:
            for key in [k for k in _MEMBER_CACHE if k[0] == league_id]:
                _MEMBER_CACHE.pop(key, None)
        else:
            _MEMBER_CACHE.clear()


def _db():
    from api.firebase_auth import init_firebase

    init_firebase()
    from firebase_admin import firestore

    return firestore.client()


def _server_ts():
    from firebase_admin import firestore

    return firestore.SERVER_TIMESTAMP


def new_request_id() -> str:
    return uuid.uuid4().hex[:10]


def _doc_to_dict(doc) -> Optional[Dict[str, Any]]:
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data


# --- Accounts --------------------------------------------------------------

def get_account(uid: str) -> Optional[Dict[str, Any]]:
    return _doc_to_dict(_db().collection("accounts").document(uid).get())


def list_accounts() -> List[Dict[str, Any]]:
    """Every registered account (uid, email, handle, ...). Small collection;
    used by the commissioner invite-by-email recipient picker."""
    return [_doc_to_dict(d) for d in _db().collection("accounts").stream()]


def upsert_account(uid: str, *, email: str, handle: str, package: str) -> Dict[str, Any]:
    ref = _db().collection("accounts").document(uid)
    existing = ref.get()
    payload: Dict[str, Any] = {
        "email": email,
        "handle": handle,
        "package": package,
        "updated_at": _server_ts(),
    }
    if not existing.exists:
        payload["created_at"] = _server_ts()
    ref.set(payload, merge=True)
    return _doc_to_dict(ref.get()) or {}


# --- League catalog (control plane) ----------------------------------------

def upsert_league(
    league_id: str,
    *,
    display_name: str,
    visibility: str,
    commissioner_uid: str,
    status: str = "active",
) -> Dict[str, Any]:
    ref = _db().collection("leagues").document(league_id)
    existing = ref.get()
    payload: Dict[str, Any] = {
        "display_name": display_name,
        "visibility": visibility,
        "commissioner_uid": commissioner_uid,
        "status": status,
        "updated_at": _server_ts(),
    }
    if not existing.exists:
        payload["created_at"] = _server_ts()
    ref.set(payload, merge=True)
    return _doc_to_dict(ref.get()) or {}


def get_league(league_id: str) -> Optional[Dict[str, Any]]:
    return _doc_to_dict(_db().collection("leagues").document(league_id).get())


def set_league_visibility(league_id: str, visibility: str) -> None:
    _db().collection("leagues").document(league_id).set(
        {"visibility": visibility, "updated_at": _server_ts()}, merge=True
    )


def delete_league(league_id: str) -> None:
    # Best-effort: remove subcollections then the league doc. (Small collections.)
    db = _db()
    league_ref = db.collection("leagues").document(league_id)
    # Members first — also tear down each member's reverse mirror under their
    # account, or the deleted league lingers in their "My Leagues" view.
    for d in league_ref.collection("members").stream():
        try:
            _membership_mirror_ref(db, d.id, league_id).delete()
        except Exception:  # pragma: no cover - best effort
            pass
        d.reference.delete()
    for sub in ("invites", "join_requests"):
        for d in league_ref.collection(sub).stream():
            d.reference.delete()
    league_ref.delete()
    invalidate_member_cache(league_id)


def list_all_leagues() -> List[Dict[str, Any]]:
    """Every league in the control plane (super-admin / platform-owner view)."""
    return [_doc_to_dict(d) for d in _db().collection("leagues").stream()]


def list_public_leagues() -> List[Dict[str, Any]]:
    # Single-field filter (auto-indexed); filter status in Python to avoid a
    # composite index requirement.
    out: List[Dict[str, Any]] = []
    for doc in _db().collection("leagues").where("visibility", "==", "public").stream():
        rec = _doc_to_dict(doc)
        if rec and rec.get("status", "active") != "archived":
            out.append(rec)
    return out


# --- Memberships -----------------------------------------------------------

def get_member(league_id: str, uid: str) -> Optional[Dict[str, Any]]:
    key = (str(league_id), str(uid))
    now = time.monotonic()
    with _MEMBER_CACHE_LOCK:
        hit = _MEMBER_CACHE.get(key)
        if hit is not None and (now - hit[0]) < _MEMBER_CACHE_TTL_SECONDS:
            return dict(hit[1]) if hit[1] is not None else None
    member = _doc_to_dict(
        _db().collection("leagues").document(league_id).collection("members").document(uid).get()
    )
    with _MEMBER_CACHE_LOCK:
        if len(_MEMBER_CACHE) >= _MEMBER_CACHE_MAX:
            # Crude but bounded: drop everything; the cache refills within one TTL.
            _MEMBER_CACHE.clear()
        _MEMBER_CACHE[key] = (now, dict(member) if member is not None else None)
    return member


def _membership_mirror_ref(db, uid: str, league_id: str):
    """Reverse index of a membership under the account, so 'which leagues does
    this user belong to' is a plain subcollection read (no collection-group index)."""
    return db.collection("accounts").document(uid).collection("memberships").document(league_id)


def set_member(
    league_id: str,
    uid: str,
    *,
    handle: str,
    role: str,
    team_id: str = "",
    status: str = "active",
    joined_via: str = "invite",
) -> Dict[str, Any]:
    db = _db()
    ref = db.collection("leagues").document(league_id).collection("members").document(uid)
    existing = ref.get()
    payload: Dict[str, Any] = {
        "uid": uid,
        "league_id": league_id,
        "handle": handle,
        "role": role,
        "team_id": team_id,
        "status": status,
        "joined_via": joined_via,
        "updated_at": _server_ts(),
    }
    if not existing.exists:
        payload["joined_at"] = _server_ts()
    ref.set(payload, merge=True)
    _membership_mirror_ref(db, uid, league_id).set(
        {
            "league_id": league_id,
            "role": role,
            "team_id": team_id,
            "status": status,
            "updated_at": _server_ts(),
        },
        merge=True,
    )
    invalidate_member_cache(league_id, uid)
    return _doc_to_dict(ref.get()) or {}


def set_member_team(league_id: str, uid: str, team_id: str) -> None:
    db = _db()
    db.collection("leagues").document(league_id).collection("members").document(uid).set(
        {"team_id": team_id, "status": "active", "updated_at": _server_ts()}, merge=True
    )
    _membership_mirror_ref(db, uid, league_id).set(
        {"team_id": team_id, "status": "active", "updated_at": _server_ts()}, merge=True
    )
    invalidate_member_cache(league_id, uid)


def list_members(league_id: str) -> List[Dict[str, Any]]:
    return [
        _doc_to_dict(d)
        for d in _db().collection("leagues").document(league_id).collection("members").stream()
    ]


def list_user_memberships(uid: str) -> List[Dict[str, Any]]:
    """Every league this uid belongs to. Reads the per-account mirror
    (accounts/{uid}/memberships) — a plain subcollection read, no index needed."""
    out: List[Dict[str, Any]] = []
    for d in _db().collection("accounts").document(uid).collection("memberships").stream():
        rec = _doc_to_dict(d)
        if rec:
            out.append(rec)
    return out


# --- Invites ---------------------------------------------------------------

# Invites live in a TOP-LEVEL ``invites/{code}`` collection (keyed by code) so a
# user redeeming a code for a PRIVATE league can be resolved to the league without
# knowing the league id. ``league_id`` is a field (single-field auto-index).

def create_invite(
    league_id: str,
    *,
    code: str,
    team_id: str,
    created_by: str,
    max_uses: int = 1,
    email: str = "",
) -> Dict[str, Any]:
    ref = _db().collection("invites").document(code)
    ref.set(
        {
            "code": code,
            "league_id": league_id,
            "team_id": team_id or "",
            "status": "open",
            "created_by": created_by,
            "max_uses": max_uses,
            "uses": 0,
            # Recorded when the invite was emailed to a specific address, so the
            # invites list can show who it was sent to (delivery is not tracked).
            "email": (email or "").strip(),
            "created_at": _server_ts(),
        }
    )
    return _doc_to_dict(ref.get()) or {}


def get_invite(code: str) -> Optional[Dict[str, Any]]:
    return _doc_to_dict(_db().collection("invites").document(code).get())


def list_invites(league_id: str) -> List[Dict[str, Any]]:
    return [
        _doc_to_dict(d)
        for d in _db().collection("invites").where("league_id", "==", league_id).stream()
    ]


def mark_invite_redeemed(code: str, *, redeemed_by: str) -> None:
    from firebase_admin import firestore

    _db().collection("invites").document(code).update(
        {
            "uses": firestore.Increment(1),
            "status": "redeemed",
            "redeemed_by": redeemed_by,
            "redeemed_at": _server_ts(),
        }
    )


def revoke_invite(code: str) -> None:
    _db().collection("invites").document(code).set(
        {"status": "revoked", "updated_at": _server_ts()}, merge=True
    )


# --- Join requests ---------------------------------------------------------

def create_join_request(
    league_id: str, *, uid: str, handle: str, note: str = ""
) -> Dict[str, Any]:
    rid = new_request_id()
    ref = (
        _db()
        .collection("leagues")
        .document(league_id)
        .collection("join_requests")
        .document(rid)
    )
    ref.set(
        {
            "request_id": rid,
            "uid": uid,
            "handle": handle,
            "status": "pending",
            "assigned_team_id": "",
            "note": note,
            "created_at": _server_ts(),
            "updated_at": _server_ts(),
        }
    )
    return _doc_to_dict(ref.get()) or {}


def list_join_requests(league_id: str, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
    col = _db().collection("leagues").document(league_id).collection("join_requests")
    docs = col.where("status", "==", status).stream() if status else col.stream()
    return [_doc_to_dict(d) for d in docs]


def get_join_request(league_id: str, request_id: str) -> Optional[Dict[str, Any]]:
    return _doc_to_dict(
        _db()
        .collection("leagues")
        .document(league_id)
        .collection("join_requests")
        .document(request_id)
        .get()
    )


def update_join_request(
    league_id: str, request_id: str, *, status: str, assigned_team_id: str = ""
) -> None:
    _db().collection("leagues").document(league_id).collection("join_requests").document(
        request_id
    ).set(
        {"status": status, "assigned_team_id": assigned_team_id, "updated_at": _server_ts()},
        merge=True,
    )
