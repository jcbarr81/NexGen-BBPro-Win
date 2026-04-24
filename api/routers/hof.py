"""Hall of Fame endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services import hall_of_fame as hof

from ..security import CurrentIdentity, require_bearer

router = APIRouter(prefix="/hall-of-fame", tags=["hof"], dependencies=[CurrentIdentity])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("")
def get_hall_of_fame() -> Dict[str, Any]:
    inductees = hof.list_inductees()
    candidates = [asdict(c) for c in hof.list_candidates()]
    return {
        "inductees": inductees,
        "candidates": candidates,
    }


@router.post("/induct")
def induct(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="player_id is required."
        )
    try:
        result = hof.add_manual_inductee(player_id, note=payload.get("note"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"result": result}


@router.post("/remove")
def remove(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    player_id = str(payload.get("player_id", "")).strip()
    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="player_id is required."
        )
    try:
        result = hof.remove_inductee(player_id, reason=payload.get("reason"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"result": result}


@router.post("/refresh")
def refresh(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    try:
        result = hof.update_hall_of_fame()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return {"result": result}


@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    """Return the currently-saved eligibility + scoring settings.

    Ports ``HallOfFameSettingsDialog`` from
    ``ui/hall_of_fame_settings_dialog.py`` — ``min_years_retired`` and
    ``score_threshold``, plus the hard-coded defaults so the UI can
    show a "reset to default" affordance.
    """

    payload = hof.load_hall_of_fame()
    settings = payload.get("settings", {}) if isinstance(payload, dict) else {}
    return {
        "min_years_retired": int(
            settings.get("min_years_retired", hof.DEFAULT_MIN_YEARS_RETIRED)
        ),
        "score_threshold": float(
            settings.get("score_threshold", hof.DEFAULT_SCORE_THRESHOLD)
        ),
        "defaults": {
            "min_years_retired": int(hof.DEFAULT_MIN_YEARS_RETIRED),
            "score_threshold": float(hof.DEFAULT_SCORE_THRESHOLD),
        },
    }


@router.put("/settings")
def update_settings(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Persist ``min_years_retired`` and ``score_threshold`` and rerun the
    inductee list so the UI reflects the new bar immediately."""

    try:
        years = int(payload.get("min_years_retired", hof.DEFAULT_MIN_YEARS_RETIRED))
        threshold = float(payload.get("score_threshold", hof.DEFAULT_SCORE_THRESHOLD))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if years < 0 or threshold < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_years_retired and score_threshold must be non-negative.",
        )

    current = hof.load_hall_of_fame()
    settings = dict(current.get("settings") or {})
    settings["min_years_retired"] = years
    settings["score_threshold"] = threshold
    current["settings"] = settings
    hof.save_hall_of_fame(current)

    # Re-run eligibility against the new bar so newly-qualifying players
    # show up immediately.
    try:
        hof.update_hall_of_fame()
    except Exception:
        pass
    return get_settings()
