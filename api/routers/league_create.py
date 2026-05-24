"""League creation wizard endpoints (admin-only).

GET  /leagues/presets        Rule + schedule + quick-start preset catalog.
POST /leagues/random-team    One `{city, name}` pair from the generator.
POST /leagues/create         Create (and register + activate) a league.
GET  /leagues/first-run      True when no leagues are registered yet.
POST /admin/bootstrap        Force-set the admin password on first run.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status

from playbalance.league_creator import create_league
from playbalance.team_name_generator import random_team, reset_name_pool
from services import league_presets as presets
from services import league_registry
from services.league_lifecycle import switch_active_league
from services.league_presets import (
    apply_rule_preset,
    generate_schedule_from_template,
)
from services import injury_settings
from services import trade_settings
from services.finance_settings import apply_financial_preset
from utils.user_manager import set_admin_password

from ..security import require_bearer

router = APIRouter(prefix="/leagues", tags=["league-create"])


def _require_admin(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    role = str(identity.get("r", "")).lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required."
        )
    return identity


AdminIdentity = Depends(_require_admin)


@router.get("/first-run")
def first_run() -> Dict[str, Any]:
    """Public: lets the splash gate decide whether to bounce to the wizard."""
    try:
        leagues = league_registry.list_leagues()
    except Exception:
        leagues = []
    return {"has_leagues": bool(leagues), "count": len(leagues)}


@router.get("/presets")
def get_presets(_: Dict[str, Any] = AdminIdentity) -> Dict[str, Any]:
    return {
        "rule_presets": [asdict(p) for p in presets.load_rule_presets()],
        "schedule_templates": [asdict(t) for t in presets.load_schedule_templates()],
        "quickstart_presets": [asdict(q) for q in presets.load_quickstart_presets()],
    }


@router.post("/random-team")
def random_team_name(_: Dict[str, Any] = AdminIdentity) -> Dict[str, str]:
    city, name = random_team()
    return {"city": city, "name": name}


@router.post("/random-team/reset")
def reset_random_pool(_: Dict[str, Any] = AdminIdentity) -> Dict[str, str]:
    reset_name_pool()
    return {"status": "reset"}


# ---------------------------------------------------------------------------
# Create league
#
# Body shape:
# {
#   "display_name": "2028 Test League",
#   "league_id": "optional-slug",
#   "mode": "single_player" | "owner_league",
#   "template_league_id": "optional-clone-source",
#   "divisions": {
#     "East": [{"city": "Boston", "name": "Pilgrims"}, ...],
#     "West": [...],
#   },
#   "rule_preset_id":     "...",
#   "schedule_template_id": "...",
#   "finance": {"enabled": true, "preset": "simple", "enforcement_mode": "warn"},
#   "trades": {"trades_enabled": true, ...},
#   "injury_level":       "normal",
# }


@router.post("/create", status_code=status.HTTP_201_CREATED)
def create_league_wizard(
    payload: Dict[str, Any] = Body(...),
    _: Dict[str, Any] = AdminIdentity,
) -> Dict[str, Any]:
    display_name = str(payload.get("display_name", "")).strip()
    if not display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="display_name is required."
        )
    league_id = str(payload.get("league_id", "")).strip() or None
    mode = str(payload.get("mode", "single_player")).strip() or "single_player"
    template_league_id = (
        str(payload.get("template_league_id", "")).strip() or None
    )

    raw_divs = payload.get("divisions")
    if not isinstance(raw_divs, dict) or not raw_divs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="divisions must be an object mapping division -> list of teams.",
        )
    structure: Dict[str, List[tuple[str, str]]] = {}
    total = 0
    for division, teams in raw_divs.items():
        if not isinstance(teams, list):
            continue
        tuples: List[tuple[str, str]] = []
        for entry in teams:
            if not isinstance(entry, dict):
                continue
            city = str(entry.get("city", "")).strip()
            name = str(entry.get("name", "")).strip()
            if not (city and name):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Every team in {division!r} needs city + name.",
                )
            tuples.append((city, name))
            total += 1
        if tuples:
            structure[str(division)] = tuples
    if total < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A league needs at least 2 teams.",
        )

    # 1. Register + pick data dir.
    try:
        from services.league_lifecycle import create_league_entry

        record = create_league_entry(
            display_name=display_name,
            league_id=league_id,
            mode=mode,
            template_league_id=template_league_id,
            overwrite=bool(payload.get("overwrite", False)),
            activate=False,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    data_dir = league_registry.get_league_data_dir(record.id, create=True)

    # 2. Flip to active FIRST so player_generator's NAME_PATH / PLAYER_PATH
    # resolve to this league's data dir. get_data_dir() seeds names.csv
    # into it as a side effect; without this, every generated player
    # falls back to the "John Doe" sentinel because the name pool loads
    # from data_root/names.csv (which isn't seeded).
    switch_active_league(record.id)

    # 3. Build teams.csv + initial roster files.
    try:
        create_league(str(data_dir), structure, display_name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"League data generation failed: {exc}",
        ) from exc

    # 4. Apply the optional preset bundle.
    rule_preset_id = str(payload.get("rule_preset_id", "")).strip()
    if rule_preset_id:
        try:
            apply_rule_preset(rule_preset_id)
        except Exception:
            pass

    # Always generate a schedule so the league is playable the moment
    # creation finishes. Without this the Season page shows "No
    # schedule loaded" and the owner has to send an admin to League
    # Admin → Regenerate Schedule before any sim button works. If the
    # wizard didn't supply a template id (older client, or someone
    # POST'd directly), fall back to the standard MLB-162 layout.
    schedule_template_id = str(payload.get("schedule_template_id", "")).strip() or "mlb_162"
    schedule_generated = False

    def _team_ids_from_structure() -> List[str]:
        ids: List[str] = []
        for teams_in_div in structure.values():
            for city, name in teams_in_div:
                ids.append(f"{city} {name}".strip())
        return ids

    # Prefer team_ids that ``create_league`` actually wrote to teams.csv
    # so the schedule references the same identifiers used everywhere
    # else (rosters, standings, news). Fall back to deriving from the
    # wizard structure if the loader is unavailable mid-creation.
    try:
        from utils.team_loader import load_teams

        team_id_list = [t.team_id for t in load_teams(data_dir / "teams.csv")]
    except Exception:
        team_id_list = _team_ids_from_structure()

    from playbalance.schedule_generator import save_schedule

    schedule_path = data_dir / "schedule.csv"
    for candidate in (schedule_template_id, "mlb_162"):
        if not candidate:
            continue
        try:
            schedule = generate_schedule_from_template(candidate, team_id_list)
        except Exception:
            schedule = []
        if schedule:
            try:
                save_schedule(schedule, schedule_path)
                schedule_generated = True
                break
            except Exception:
                continue

    # Mark the preseason "schedule" checklist item complete so the UI
    # doesn't keep nagging the owner about a missing schedule.
    if schedule_generated:
        try:
            import json as _json

            progress_path = data_dir / "season_progress.json"
            progress: Dict[str, Any] = {}
            if progress_path.exists():
                try:
                    progress = _json.loads(progress_path.read_text(encoding="utf-8"))
                    if not isinstance(progress, dict):
                        progress = {}
                except Exception:
                    progress = {}
            done_block = progress.get("preseason_done") or {}
            if not isinstance(done_block, dict):
                done_block = {}
            done_block["schedule"] = True
            progress["preseason_done"] = done_block
            progress_path.write_text(_json.dumps(progress, indent=2), encoding="utf-8")
        except Exception:
            pass

    # 5. Settings blocks.
    finance_cfg = payload.get("finance") or {}
    if isinstance(finance_cfg, dict):
        # Apply the named preset first so module defaults seed properly,
        # then layer any per-module / AI tuning overrides on top.
        if finance_cfg.get("preset"):
            try:
                apply_financial_preset(str(finance_cfg["preset"]))
            except Exception:
                pass
        modules_override = finance_cfg.get("modules")
        ai_override = finance_cfg.get("finance_ai_tuning")
        enabled_override = finance_cfg.get("enabled")
        enforcement_override = finance_cfg.get("enforcement_mode")
        # Only call update_financial_settings when the wizard actually
        # forwarded overrides — apply_financial_preset above already
        # covers the simple "preset only" case.
        if (
            (isinstance(modules_override, dict) and modules_override)
            or (isinstance(ai_override, dict) and ai_override)
            or enabled_override is not None
            or (enforcement_override and finance_cfg.get("preset") is None)
        ):
            try:
                from services.finance_settings import update_financial_settings

                update_financial_settings(
                    enabled=(
                        bool(enabled_override)
                        if enabled_override is not None
                        else None
                    ),
                    enforcement_mode=(
                        str(enforcement_override)
                        if enforcement_override
                        else None
                    ),
                    modules=(
                        {str(k): str(v) for k, v in modules_override.items()}
                        if isinstance(modules_override, dict)
                        else None
                    ),
                    finance_ai_tuning=(
                        {str(k): v for k, v in ai_override.items()}
                        if isinstance(ai_override, dict)
                        else None
                    ),
                )
            except Exception:
                pass

    scouting_cfg = payload.get("scouting") or {}
    if isinstance(scouting_cfg, dict) and scouting_cfg:
        try:
            from services.scouting_service import update_scouting_settings

            kwargs: Dict[str, Any] = {}
            if "enabled" in scouting_cfg:
                kwargs["enabled"] = bool(scouting_cfg.get("enabled"))
            for key in (
                "base_monthly_credits",
                "finance_off_multiplier",
                "monthly_decay",
                "passive_gain",
                "max_banked_credits",
                "auto_spend_cap",
            ):
                if key in scouting_cfg and scouting_cfg[key] is not None:
                    try:
                        kwargs[key] = float(scouting_cfg[key])
                    except (TypeError, ValueError):
                        continue
            if kwargs:
                update_scouting_settings(**kwargs)
        except Exception:
            pass

    trades_cfg = payload.get("trades") or {}
    if isinstance(trades_cfg, dict) and trades_cfg:
        try:
            trade_settings.update_trade_settings(**{
                k: v
                for k, v in trades_cfg.items()
                if k
                in {
                    "trades_enabled",
                    "draft_pick_trading_enabled",
                    "require_commissioner_approval",
                    "cpu_initiated_trades_enabled",
                    "cpu_proposal_cadence",
                    "max_pick_trade_years",
                }
            })
        except Exception:
            pass

    injury_level = str(payload.get("injury_level", "")).strip()
    if injury_level:
        try:
            injury_settings.set_injury_level(injury_level)
        except Exception:
            pass

    draft_cfg = payload.get("draft") or {}
    if isinstance(draft_cfg, dict) and draft_cfg:
        try:
            from services.draft_settings import DraftSettings, save_draft_settings

            save_draft_settings(
                DraftSettings(
                    rounds=int(draft_cfg.get("rounds", 10) or 10),
                    pool_size=int(draft_cfg.get("pool_size", 200) or 200),
                )
            )
        except Exception:
            pass

    return {
        "league_id": record.id,
        "display_name": record.display_name,
        "mode": record.mode,
        "data_dir": str(data_dir),
        "teams_total": total,
    }


# ---------------------------------------------------------------------------
# Admin bootstrap
#
# First-run flow forces setting an admin password. This is a separate
# router path so the wizard can call it BEFORE any protected endpoint.


admin_router = APIRouter(prefix="/admin", tags=["admin-bootstrap"])


@admin_router.post("/bootstrap")
def bootstrap_admin(
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Allow setting the admin password when the default `pass` is still in place.

    This is intentionally anonymous (no bearer check) but only accepts the
    call while the admin account has its default sentinel password. Once
    an explicit password is set, this endpoint refuses further updates.
    """

    from utils.user_manager import load_users, verify_user_password

    password = str(payload.get("password", "")).strip()
    if not password or len(password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="password must be at least 4 characters.",
        )

    users = load_users()
    admin = next((u for u in users if u["username"] == "admin"), None)
    # First-run / fresh-data scenarios leave no admin account at all.
    # In that case we just create one with the supplied password — that's
    # literally what the wizard is asking for. When an admin does exist,
    # we still only permit reset if the current password is the default
    # sentinel, to avoid letting an anonymous caller hijack an account
    # that's already been set up.
    if admin is not None:
        stored = str(admin.get("password") or "").strip()
        if stored and stored not in {"pass", "__setup_required__"}:
            if verify_user_password("pass", stored):
                pass  # still default
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Admin password already set. Use the Users admin page to change it.",
                )

    try:
        set_admin_password(password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"status": "ok"}
