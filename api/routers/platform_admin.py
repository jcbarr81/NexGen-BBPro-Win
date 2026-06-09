"""Platform-owner (super-admin) operations that span the whole deployment.

Guarded by the NEXGEN_SUPER_ADMINS email allow-list (see security.is_super_admin),
NOT by per-league membership — this is the global "in case anything goes wrong"
escape hatch. Cloud-only (Firebase identity); a no-op surface locally.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from ..security import is_super_admin, require_account

router = APIRouter(prefix="/platform", tags=["platform-admin"])

_LOG = logging.getLogger("nexgen.platform_admin")


def _require_super_admin(account: Dict[str, Any] = Depends(require_account)) -> Dict[str, Any]:
    if not is_super_admin(account.get("email")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform-admin (super-admin) access required.",
        )
    return account


@router.get("/leagues")
def list_all_leagues(_: Dict[str, Any] = Depends(_require_super_admin)) -> Dict[str, Any]:
    """Every league in the control plane (platform-owner view)."""
    from services import firestore_store

    return {"leagues": [lg for lg in firestore_store.list_all_leagues() if lg]}


@router.delete("/leagues/{league_id}")
def delete_league(
    league_id: str,
    _: Dict[str, Any] = Depends(_require_super_admin),
) -> Dict[str, Any]:
    """Permanently delete ANY league: control plane (Firestore catalog, members,
    invites, join-requests + each member's account mirror), the game data
    (registry + local working copy), and the durable remote (GCS) copy.
    """
    league_id = str(league_id or "").strip()
    if not league_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="league_id is required."
        )

    errors: list[str] = []

    # 1. Control plane (Firestore) — removes it from discovery + everyone's
    #    "My Leagues". Best-effort so a partial state can still be cleaned up.
    try:
        from services import firestore_store

        firestore_store.delete_league(league_id)
    except Exception as exc:  # pragma: no cover - best effort
        _LOG.exception("firestore delete failed for %s", league_id)
        errors.append(f"firestore: {exc}")

    # 2. Game data: registry entry + local on-disk data.
    try:
        from services import league_lifecycle, league_registry

        if league_registry.get_league(league_id) is not None:
            league_lifecycle.delete_league(
                league_id, delete_data=True, force_if_active=True
            )
    except Exception as exc:  # pragma: no cover - best effort
        _LOG.exception("registry/local delete failed for %s", league_id)
        errors.append(f"registry: {exc}")

    # 3. Durable remote (GCS) — the automatic push-sync refuses to delete a
    #    league absent locally (safety guard), so purge it explicitly.
    try:
        from api import working_copy

        working_copy.delete_league_remote(league_id)
    except Exception as exc:  # pragma: no cover - best effort
        _LOG.exception("remote delete failed for %s", league_id)
        errors.append(f"remote: {exc}")

    return {"deleted": True, "league_id": league_id, "errors": errors}
