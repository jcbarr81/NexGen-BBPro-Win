"""Bridge Firestore memberships → the per-league ``users.txt`` the game reads.

Auth + the source-of-truth membership live in Firestore (see firestore_store).
But lots of existing game logic (team ownership, season progression, change
requests, lineups) reads the per-league ``users.txt``. So whenever a member is
admitted or has a team assigned, we mirror them into ``users.txt`` (keyed by
Firebase uid; the password column is unused because auth is Firebase).

Role mapping into users.txt (which only knows ``admin``/``owner``):
  * owner                       -> owner (team_id)
  * commissioner WITHOUT a team -> admin  (runs the league, no team)
  * commissioner WITH a team    -> owner  (so the game treats them as that team's
                                   owner); their commissioner powers come from the
                                   identity bridge (membership role=commissioner
                                   -> r="admin"), not from users.txt.
"""

from __future__ import annotations

import logging
import secrets

from utils import user_manager

_LOG = logging.getLogger("nexgen.memberships")


def _game_role(membership_role: str, team_id: str) -> str:
    if membership_role == "commissioner" and not team_id:
        return "admin"
    return "owner"


def provision_user(uid: str, membership_role: str, team_id: str = "") -> None:
    """Ensure the active league's users.txt has *uid* with the right role/team.

    Idempotent: creates the entry if missing, else updates role/team. Safe to call
    on every admit / team (re)assignment.
    """
    team_id = team_id or ""
    game_role = _game_role(membership_role, team_id)
    try:
        users = user_manager.load_users()
    except Exception:
        users = []
    exists = any(str(u.get("username")) == uid for u in users)
    try:
        if not exists:
            # Password is never used (auth is Firebase) — store a random value.
            user_manager.add_user(uid, secrets.token_hex(16), game_role, team_id)
        else:
            user_manager.update_user(
                uid, new_role=game_role, new_team_id=team_id
            )
    except ValueError:
        # e.g. one-owner-per-team conflict — surface to the caller as a clean error.
        raise
    except Exception:
        _LOG.exception("provision_user failed for uid=%s team=%s", uid, team_id)
        raise
