"""Commissioner invite-by-email: the SendGrid sender + the batch-send endpoint."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import services.email_sender as email_sender
import api.routers.invites as invites
import api.routers.join_requests as join_requests


# --- email_sender config + send ---------------------------------------------

def test_email_sender_enabled_toggles_on_env(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("INVITE_EMAIL_FROM", raising=False)
    assert email_sender.is_enabled() is False

    monkeypatch.setenv("SENDGRID_API_KEY", "SG.key")
    monkeypatch.setenv("INVITE_EMAIL_FROM", "commish@example.com")
    assert email_sender.is_enabled() is True
    assert email_sender.status()["from_address"] == "commish@example.com"


def test_send_email_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("INVITE_EMAIL_FROM", raising=False)
    with pytest.raises(email_sender.EmailError):
        email_sender.send_email(to="a@b.com", subject="x", html="<p>x</p>")


def test_send_email_posts_and_accepts_202(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.key")
    monkeypatch.setenv("INVITE_EMAIL_FROM", "commish@example.com")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["auth"] = headers.get("Authorization")
        return SimpleNamespace(status_code=202, json=lambda: {}, text="")

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    email_sender.send_email(to="a@b.com", subject="Hi", html="<p>hi</p>", text="hi")
    assert captured["url"].endswith("/v3/mail/send")
    assert captured["auth"] == "Bearer SG.key"
    assert captured["json"]["personalizations"][0]["to"][0]["email"] == "a@b.com"


def test_send_email_raises_on_provider_error(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.key")
    monkeypatch.setenv("INVITE_EMAIL_FROM", "commish@example.com")

    def fake_post(url, json=None, headers=None, timeout=None):
        return SimpleNamespace(
            status_code=401,
            json=lambda: {"errors": [{"message": "unauthorized"}]},
            text="unauthorized",
        )

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(email_sender.EmailError) as exc:
        email_sender.send_email(to="a@b.com", subject="x", html="<p>x</p>")
    assert "unauthorized" in str(exc.value)


# --- endpoint: POST /invites/email ------------------------------------------

def _ident():
    return {"r": "admin", "u": "boss", "league_id": "alpha"}


def test_email_invites_blocks_when_not_configured(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: False)
    with pytest.raises(HTTPException) as exc:
        invites.email_invites(
            payload={"recipients": ["a@b.com"]}, identity=_ident()
        )
    assert exc.value.status_code == 400


def test_email_invites_generates_and_sends(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: True)
    monkeypatch.setattr(email_sender, "app_base_url", lambda: "https://app.test")
    monkeypatch.setattr(
        email_sender, "status",
        lambda: {"from_name": "NexGen BBPro", "from_address": "c@x.com"},
    )
    created = []
    monkeypatch.setattr(
        invites, "_gen_code", lambda: "CODE" + str(len(created))
    )
    sent = []

    import services.firestore_store as fs
    monkeypatch.setattr(fs, "get_league", lambda lid: {"display_name": "Alpha"})
    monkeypatch.setattr(
        fs, "create_invite",
        lambda league, **kw: created.append((league, kw)) or {},
    )
    monkeypatch.setattr(
        email_sender, "send_email",
        lambda **kw: sent.append(kw),
    )

    out = invites.email_invites(
        payload={
            "team_id": "NYY",
            "recipients": ["alice@x.com", {"email": "bob@y.com", "team_id": "BOS"}],
        },
        identity=_ident(),
    )
    assert out["sent_count"] == 2 and out["failed_count"] == 0
    # Per-recipient team override respected.
    teams = {c[1]["email"]: c[1]["team_id"] for c in created}
    assert teams == {"alice@x.com": "NYY", "bob@y.com": "BOS"}
    assert len(sent) == 2


def test_email_invites_flags_bad_address(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: True)
    monkeypatch.setattr(email_sender, "app_base_url", lambda: "https://app.test")
    monkeypatch.setattr(
        email_sender, "status", lambda: {"from_name": "NexGen BBPro"}
    )
    import services.firestore_store as fs
    monkeypatch.setattr(fs, "get_league", lambda lid: {})
    monkeypatch.setattr(fs, "create_invite", lambda league, **kw: {})
    monkeypatch.setattr(email_sender, "send_email", lambda **kw: None)

    out = invites.email_invites(
        payload={"recipients": ["not-an-email"]}, identity=_ident()
    )
    assert out["sent_count"] == 0 and out["failed_count"] == 1
    assert out["results"][0]["error"]


# --- endpoint: POST /league/message (commissioner broadcast) -----------------

def _msg_ident():
    return {"r": "admin", "u": "boss", "league_id": "alpha", "email": "commish@x.com"}


def test_message_league_blocks_when_not_configured(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: False)
    with pytest.raises(HTTPException) as exc:
        join_requests.message_league(
            payload={"subject": "Hi", "body": "There"}, identity=_msg_ident()
        )
    assert exc.value.status_code == 400


def test_message_league_requires_subject_and_body(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: True)
    with pytest.raises(HTTPException):
        join_requests.message_league(
            payload={"subject": "", "body": "x"}, identity=_msg_ident()
        )
    with pytest.raises(HTTPException):
        join_requests.message_league(
            payload={"subject": "x", "body": ""}, identity=_msg_ident()
        )


def test_message_league_sends_to_members_with_email(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: True)
    import services.firestore_store as fs

    monkeypatch.setattr(
        fs, "list_members",
        lambda lid: [
            {"uid": "u1", "handle": "Alice"},
            {"uid": "u2", "handle": "Bob"},
            {"uid": "u3", "handle": "NoEmail"},
        ],
    )
    emails = {"u1": "alice@x.com", "u2": "bob@y.com", "u3": ""}
    monkeypatch.setattr(fs, "get_account", lambda uid: {"email": emails[uid]})
    monkeypatch.setattr(fs, "get_league", lambda lid: {"display_name": "Alpha"})

    sent = []
    monkeypatch.setattr(email_sender, "send_email", lambda **kw: sent.append(kw))

    out = join_requests.message_league(
        payload={"subject": "News", "body": "Play ball"}, identity=_msg_ident()
    )
    assert out["sent_count"] == 2 and out["failed_count"] == 0
    # Member without an email is skipped; replies routed to the commissioner.
    assert {s["to"] for s in sent} == {"alice@x.com", "bob@y.com"}
    assert all(s["reply_to"] == "commish@x.com" for s in sent)


def test_message_league_400_when_no_member_emails(monkeypatch):
    monkeypatch.setattr(email_sender, "is_enabled", lambda: True)
    import services.firestore_store as fs

    monkeypatch.setattr(fs, "list_members", lambda lid: [{"uid": "u1", "handle": "A"}])
    monkeypatch.setattr(fs, "get_account", lambda uid: {"email": ""})
    with pytest.raises(HTTPException) as exc:
        join_requests.message_league(
            payload={"subject": "x", "body": "y"}, identity=_msg_ident()
        )
    assert exc.value.status_code == 400
