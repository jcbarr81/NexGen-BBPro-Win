"""Zero-league bootstrap: a platform super-admin must stay authenticated when no
league is active, so the create-league wizard's endpoints work after every league
has been deleted. Regression for the 400 "Missing league context" that bricked
/leagues, /commissioner/settings and /leagues/presets once all leagues were gone.
"""

import pytest

from api import security


def _no_league(monkeypatch):
    monkeypatch.setattr("utils.path_utils.get_active_league_id", lambda *a, **k: None)


def _league(monkeypatch, league_id):
    monkeypatch.setattr("utils.path_utils.get_active_league_id", lambda *a, **k: league_id)


def test_super_admin_authenticates_with_no_active_league(monkeypatch):
    _no_league(monkeypatch)
    monkeypatch.setattr(security, "super_admin_emails", lambda: {"admin@x.com"})
    ident = security._identity_from_membership(
        {"uid": "u1", "email": "Admin@X.com", "name": "A"}  # case-insensitive
    )
    assert ident["r"] == "admin"
    assert ident["super_admin"] is True
    assert ident["league_id"] == ""  # empty, not a crash


def test_super_admin_with_league_unchanged(monkeypatch):
    _league(monkeypatch, "lg1")
    monkeypatch.setattr(security, "super_admin_emails", lambda: {"admin@x.com"})
    ident = security._identity_from_membership({"uid": "u1", "email": "admin@x.com"})
    assert ident["r"] == "admin"
    assert ident["league_id"] == "lg1"


def test_non_admin_no_league_still_400(monkeypatch):
    _no_league(monkeypatch)
    monkeypatch.setattr(security, "super_admin_emails", lambda: {"admin@x.com"})
    with pytest.raises(security.HTTPException) as exc:
        security._identity_from_membership({"uid": "u2", "email": "user@x.com"})
    assert exc.value.status_code == 400


def test_member_with_league_resolves(monkeypatch):
    _league(monkeypatch, "lg1")
    monkeypatch.setattr(security, "super_admin_emails", lambda: set())
    monkeypatch.setattr(
        "services.firestore_store.get_member",
        lambda lg, uid: {"role": "owner", "team_id": "BOS", "handle": "h"},
    )
    ident = security._identity_from_membership({"uid": "u3", "email": "o@x.com"})
    assert ident["r"] == "owner"
    assert ident["t"] == "BOS"
