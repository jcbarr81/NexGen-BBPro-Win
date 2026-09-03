"""Every team-scoped write endpoint must enforce ownership server-side.

These endpoints were gated by authentication ONLY, which meant any signed-in
user could act on any club: rewrite a rival's batting order and rotation before
a sim, wipe their training focus, or release their players. Ownership was
checked client-side, which is no check at all.

The sweep below is deliberately written against the live router table rather
than a hand-written list, so an endpoint added later fails this test until it
is guarded.
"""

import importlib
import inspect
import pkgutil

import pytest
from fastapi import HTTPException

import api.routers as routers_pkg
from api.security import require_team_owner

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints that take a team id but do not mutate that team's data. Validation
# runs the shared validators and returns errors; it changes nothing.
EXEMPT_PREFIXES = ("api.routers.validation",)


def _team_scoped_writes():
    """Yield (module, endpoint function, path) for every team-scoped write."""
    found = []
    for mod_info in pkgutil.iter_modules(routers_pkg.__path__):
        name = f"api.routers.{mod_info.name}"
        if name in EXEMPT_PREFIXES:
            continue
        try:
            module = importlib.import_module(name)
        except Exception:  # pragma: no cover - a broken router fails elsewhere
            continue
        for attr in ("router", "machine_router", "player_router", "league_router"):
            router = getattr(module, attr, None)
            if router is None:
                continue
            for route in router.routes:
                methods = set(getattr(route, "methods", []) or [])
                path = getattr(route, "path", "")
                endpoint = getattr(route, "endpoint", None)
                if not (methods & WRITE_METHODS) or "{team_id}" not in path:
                    continue
                if endpoint is None:
                    continue
                found.append((name, endpoint, path))
    return found


def test_the_sweep_actually_finds_endpoints():
    """Guard against the test silently passing because it found nothing."""
    assert len(_team_scoped_writes()) >= 10


@pytest.mark.parametrize(
    "module_name,endpoint,path",
    _team_scoped_writes(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_team_scoped_write_enforces_ownership(module_name, endpoint, path):
    source = inspect.getsource(endpoint)
    assert "require_team_owner(" in source, (
        f"{module_name} {path} writes to a team's data but never calls "
        "require_team_owner — any signed-in user could act on another club."
    )


# --- the guard itself -------------------------------------------------------


def test_an_outsider_is_refused():
    with pytest.raises(HTTPException) as exc:
        require_team_owner({"u": "rival", "r": "user", "t": "THEIRS"}, "MINE")
    assert exc.value.status_code == 403


def test_the_owner_is_allowed():
    require_team_owner({"u": "me", "r": "user", "t": "MINE"}, "MINE")


def test_an_admin_is_allowed_anywhere():
    """Commissioner tooling has to keep working across every club."""
    require_team_owner({"u": "commish", "r": "admin", "t": ""}, "ANY")


def test_a_team_less_user_cannot_slip_through_on_an_empty_id():
    """A super-admin's bound team is empty; an ordinary user's must not match
    an empty team_id by accident."""
    with pytest.raises(HTTPException):
        require_team_owner({"u": "nobody", "r": "user", "t": ""}, "SOMETEAM")
