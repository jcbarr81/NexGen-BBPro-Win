"""A club's notifications are its owner's (8.8.2, backlog #71).

``GET /notifications/history/{team_id}`` and ``/settings/{team_id}`` were
gated by sign-in only, so any member could read another club's history,
which since 8.8.0 names the free agents it bid on and its terms. Both now
call ``require_team_owner``: the club's owner and the commissioner only.

The sweep reads the live router table, so a read endpoint added later under
``/notifications/.../{team_id}`` fails until it is guarded.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import api.routers.notifications as notifications

OWNER = {"u": "me", "r": "user", "t": "MINE"}
RIVAL = {"u": "rival", "r": "user", "t": "THEIRS"}
COMMISH = {"u": "commish", "r": "admin", "t": ""}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(
        notifications, "load_history", lambda team_id, limit: [{"title": "Outbid"}]
    )
    monkeypatch.setattr(
        notifications,
        "load_notification_settings",
        lambda team_id: type("S", (), {"to_dict": lambda self: {"rules": []}})(),
    )


def test_every_team_scoped_read_is_guarded():
    found = 0
    for route in notifications.router.routes:
        if "{team_id}" not in getattr(route, "path", ""):
            continue
        found += 1
        assert "require_team_owner(" in inspect.getsource(route.endpoint), route.path
    assert found >= 3


def test_a_rival_cannot_read_another_clubs_history_or_settings(served):
    with pytest.raises(HTTPException) as exc:
        notifications.history("MINE", limit=10, identity=RIVAL)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        notifications.get_settings("MINE", identity=RIVAL)
    assert exc.value.status_code == 403


def test_the_owner_and_the_commissioner_can(served):
    for who in (OWNER, COMMISH):
        out = notifications.history("MINE", limit=10, identity=who)
        assert out["count"] == 1
        assert notifications.get_settings("MINE", identity=who) == {"rules": []}
