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
from services import scouting_service as scout
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


_MODULE_LABELS: Dict[str, str] = {
    "owner_revenue": "Owner: Revenue Model",
    "owner_market_model": "Owner: Market / Fan Interest",
    "owner_budgets": "Owner: Budget Buckets",
    "owner_expenses": "Owner: Operating Expenses",
    "gm_contracts": "GM: Contracts",
    "gm_payroll_rules": "GM: Payroll Rules",
    "gm_arbitration": "GM: Arbitration",
    "gm_free_agency": "GM: Free Agency",
    "gm_roster_cost_enforcement": "GM: Roster Cost Enforcement",
    "gm_finance_ai": "GM AI: Financial Behavior",
}

_MODULE_ORDER = (
    "owner_revenue",
    "owner_market_model",
    "owner_budgets",
    "owner_expenses",
    "gm_contracts",
    "gm_payroll_rules",
    "gm_arbitration",
    "gm_free_agency",
    "gm_roster_cost_enforcement",
    "gm_finance_ai",
)


def _serialize_finance_modules() -> list[Dict[str, Any]]:
    return [
        {
            "id": module,
            "label": _MODULE_LABELS.get(module, module),
            "help": fs.FINANCE_MODULE_HELP.get(module, ""),
            "levels": list(fs.MODULE_LEVELS.get(module, ())),
            # Per-level plain-language descriptions so the UI can explain what
            # each dropdown choice actually changes (Basic vs MLB-Like etc.).
            "level_help": {
                level: fs.describe_module_level(module, level)
                for level in fs.MODULE_LEVELS.get(module, ())
            },
        }
        for module in _MODULE_ORDER
    ]


def _serialize_scouting(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "league_id": str(settings.get("league_id", "")),
        "enabled": bool(settings.get("enabled", False)),
        "base_monthly_credits": float(
            settings.get("base_monthly_credits", scout.DEFAULT_BASE_MONTHLY_CREDITS)
        ),
        "finance_off_multiplier": float(
            settings.get(
                "finance_off_multiplier", scout.DEFAULT_FINANCE_OFF_MULTIPLIER
            )
        ),
        "monthly_decay": float(
            settings.get("monthly_decay", scout.DEFAULT_MONTHLY_DECAY)
        ),
        "passive_gain": float(
            settings.get("passive_gain", scout.DEFAULT_PASSIVE_GAIN)
        ),
        "max_banked_credits": float(
            settings.get("max_banked_credits", scout.DEFAULT_MAX_BANKED_CREDITS)
        ),
        "auto_spend_cap": float(
            settings.get("auto_spend_cap", scout.DEFAULT_AUTO_SPEND_CAP)
        ),
    }


def _serialize() -> Dict[str, Any]:
    trade = ts.load_trade_settings()
    injury = insj.load_injury_settings()
    finance = fs.load_financial_settings()
    scouting = scout.load_scouting_settings()

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
            "finance_ai_tuning": dict(finance.finance_ai_tuning),
        },
        "scouting": _serialize_scouting(scouting),
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
                fs.ENFORCEMENT_ON,
            ],
            "finance_modules": _serialize_finance_modules(),
            "finance_ai_tuning_defaults": dict(fs.DEFAULT_FINANCE_AI_TUNING),
            # What each preset sets, so the UI can reflect a preset's module
            # levels + enforcement the moment it's selected (before saving).
            "finance_preset_profiles": {
                name: {
                    "enabled": bool(profile.get("enabled", False)),
                    "enforcement_mode": str(
                        profile.get("enforcement_mode", fs.ENFORCEMENT_OFF)
                    ),
                    "modules": dict(profile.get("modules", {})),
                }
                for name, profile in fs.PRESET_PROFILES.items()
            },
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
    modules = payload.get("modules")
    finance_ai_tuning = payload.get("finance_ai_tuning")
    try:
        fs.update_financial_settings(
            enabled=payload.get("enabled"),
            preset=payload.get("preset"),
            enforcement_mode=payload.get("enforcement_mode"),
            modules=modules if isinstance(modules, dict) else None,
            finance_ai_tuning=(
                finance_ai_tuning if isinstance(finance_ai_tuning, dict) else None
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _serialize()


@router.put("/settings/scouting")
def save_scouting_settings(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    """Update league-wide scouting fog-of-war tuning."""

    def _maybe_float(key: str) -> float | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be numeric.",
            ) from exc

    try:
        scout.update_scouting_settings(
            enabled=payload.get("enabled"),
            base_monthly_credits=_maybe_float("base_monthly_credits"),
            finance_off_multiplier=_maybe_float("finance_off_multiplier"),
            monthly_decay=_maybe_float("monthly_decay"),
            passive_gain=_maybe_float("passive_gain"),
            max_banked_credits=_maybe_float("max_banked_credits"),
            auto_spend_cap=_maybe_float("auto_spend_cap"),
        )
    except HTTPException:
        raise
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
