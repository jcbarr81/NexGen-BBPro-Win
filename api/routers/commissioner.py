"""Commissioner-only settings endpoint.

Bundles league-wide knobs from three services so the Electron page can
read + write them in one place:

- :mod:`services.trade_settings`  (trade toggles + CPU cadence)
- :mod:`services.injury_settings` (off/low/normal level)
- :mod:`services.finance_settings` (preset + enforcement + enabled)

All writes are admin-gated.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services import finance_settings as fs
from services import injury_settings as insj
from services import team_auto_reassign_settings as tar
from services import team_strategy_profiles as tsp
from services import trade_settings as ts

from ..security import require_bearer

router = APIRouter(prefix="/commissioner", tags=["commissioner"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


def _serialize() -> Dict[str, Any]:
    trade = ts.load_trade_settings()
    injury = insj.load_injury_settings()
    finance = fs.load_financial_settings()

    strategy_settings = tsp.load_team_strategy_settings()
    auto_reassign_settings = tar.load_team_auto_reassign_settings()
    strategy_options = [
        {
            "id": pid,
            "label": str(meta.get("label", pid.title())),
            "description": str(meta.get("description", "")),
        }
        for pid, meta in tsp.STRATEGY_PROFILES.items()
    ]

    return {
        "trade": asdict(trade),
        "injury": asdict(injury),
        "finance": {
            "league_id": finance.league_id,
            "enabled": finance.enabled,
            "preset": finance.preset,
            "enforcement_mode": finance.enforcement_mode,
            "modules": dict(finance.modules),
        },
        "strategy": {
            "default_profile": strategy_settings.get("default_profile"),
            "teams": strategy_settings.get("teams") or {},
        },
        "auto_reassign": {
            "default_enabled": bool(
                auto_reassign_settings.get("default_enabled", tar.DEFAULT_ENABLED)
            ),
            "teams": auto_reassign_settings.get("teams") or {},
        },
        "options": {
            "trade_cadences": list(ts.CPU_PROPOSAL_CADENCE_VALUES),
            "injury_levels": list(insj.LEVEL_OPTIONS.keys()),
            "finance_presets": [
                fs.PRESET_OFF,
                fs.PRESET_SIMPLE,
                fs.PRESET_STANDARD,
                fs.PRESET_MLB_LIKE,
                fs.PRESET_CUSTOM,
            ],
            "finance_enforcement": [
                fs.ENFORCEMENT_OFF,
                fs.ENFORCEMENT_WARN,
                fs.ENFORCEMENT_BLOCK,
            ],
            "strategy_profiles": strategy_options,
        },
    }


@router.get("/settings")
def get_commissioner_settings(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    return _serialize()


@router.put("/settings/trade")
def save_trade_settings(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        ts.update_trade_settings(
            trades_enabled=payload.get("trades_enabled"),
            draft_pick_trading_enabled=payload.get("draft_pick_trading_enabled"),
            require_commissioner_approval=payload.get("require_commissioner_approval"),
            cpu_initiated_trades_enabled=payload.get("cpu_initiated_trades_enabled"),
            cpu_proposal_cadence=payload.get("cpu_proposal_cadence"),
            max_pick_trade_years=payload.get("max_pick_trade_years"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize()


@router.put("/settings/injury")
def save_injury_settings(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    level = str(payload.get("level", "")).strip()
    if not level:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="level is required."
        )
    try:
        insj.set_injury_level(level)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize()


@router.put("/settings/finance")
def save_finance_settings(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    try:
        fs.update_financial_settings(
            enabled=payload.get("enabled"),
            preset=payload.get("preset"),
            enforcement_mode=payload.get("enforcement_mode"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize()


@router.put("/settings/strategy")
def save_strategy_defaults(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Update league-default strategy + auto-reassign, and optionally a
    batch of per-team overrides in one call. Mirrors PyQt's
    ``TeamStrategySettingsDialog`` which let commissioners edit both
    defaults and each team's override in a single save.
    """

    default_profile = payload.get("default_profile")
    default_auto_reassign = payload.get("default_auto_reassign")
    team_strategies = payload.get("team_strategies") or {}
    team_auto_reassigns = payload.get("team_auto_reassigns") or {}

    try:
        if default_profile is not None:
            tsp.update_league_default_strategy(str(default_profile))
        if default_auto_reassign is not None:
            tar.update_league_default_auto_reassign(bool(default_auto_reassign))

        if isinstance(team_strategies, dict):
            for team_id, profile in team_strategies.items():
                tsp.set_team_strategy_profile(str(team_id), profile)
        if isinstance(team_auto_reassigns, dict):
            for team_id, enabled in team_auto_reassigns.items():
                tar.set_team_auto_reassign(str(team_id), enabled)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize()
