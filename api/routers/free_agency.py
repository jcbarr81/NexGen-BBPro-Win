"""Free-agency endpoints.

GET  /free-agents                        List unsigned players.
POST /free-agents/{player_id}/evaluate   Preview a contract offer:
                                         shows fair-market salary +
                                         likely competing CPU bids.
POST /teams/{team_id}/sign               Submit an offer to a free
                                         agent. The player evaluates
                                         the offer (accept / counter /
                                         reject). On accept the
                                         contract + roster move both
                                         persist. Phase-gated so FA
                                         signings are only available
                                         during the league's FA window
                                         (regular season + offseason +
                                         preseason).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.contract_negotiator import (
    FA_SERVICE_DAYS,
    REJECTION_COOLDOWN_DAYS,
    evaluate_extension_offer,
    fair_market_salary,
    fair_market_years,
)
from services.contracts_service import (
    estimate_salary_for_player,
    sign_free_agent_contract,
)
from services.free_agency import list_unsigned_players_from_files
from services.payroll_policy import evaluate_free_agent_signing
from services.transaction_log import record_transaction
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster

from ..security import CurrentIdentity, require_bearer, require_team_owner
from ._rating_presentation import compute_overall, rating_context, scale_rating

router = APIRouter(tags=["free-agency"], dependencies=[CurrentIdentity])

_LEVEL_ATTR = {"ACT": "act", "AAA": "aaa", "LOW": "low"}

_SUMMARY_RATING_KEYS = (
    "ch", "ph", "sp", "eye", "fa", "arm",
    "fb", "control", "movement", "endurance",
)


def _summarize(player: Any) -> Dict[str, Any]:
    is_pitcher = bool(getattr(player, "is_pitcher", False))
    position = getattr(player, "primary_position", None)

    ratings: Dict[str, Any] = {}
    ratings_context: Dict[str, Dict[str, Any]] = {}
    for key in _SUMMARY_RATING_KEYS:
        raw = getattr(player, key, None)
        if raw is None:
            continue
        ratings[key] = scale_rating(
            raw, key=key, position=position, is_pitcher=is_pitcher
        )
        ctx = rating_context(
            raw, key=key, position=position, is_pitcher=is_pitcher
        )
        if ctx is not None:
            ratings_context[key] = ctx

    overall = compute_overall(
        lambda k: getattr(player, k, None),
        is_pitcher=is_pitcher,
        position=position,
    )

    return {
        "player_id": getattr(player, "player_id", ""),
        "first_name": getattr(player, "first_name", ""),
        "last_name": getattr(player, "last_name", ""),
        "primary_position": getattr(player, "primary_position", ""),
        "other_positions": getattr(player, "other_positions", "") or "",
        "bats": getattr(player, "bats", "") or "",
        "is_pitcher": is_pitcher,
        "role": getattr(player, "role", "") or "",
        "ratings": ratings,
        "ratings_context": ratings_context,
        "overall_raw": overall["overall_raw"],
        "overall_display": overall["overall_display"],
        "overall_stars_text": overall["overall_stars_text"],
    }


@router.get("/free-agents")
def list_free_agents(limit: int = 1000) -> Dict[str, Any]:
    try:
        players = list_unsigned_players_from_files()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load free agents: {exc}",
        ) from exc
    rows = [_summarize(p) for p in players]
    rows.sort(key=lambda r: (r["last_name"], r["first_name"]))
    return {"count": len(rows), "limit": limit, "free_agents": rows[:limit]}


def _find_player(player_id: str) -> Any:
    """Return the player record from players.csv, or None."""

    try:
        for p in load_players_from_csv("data/players.csv"):
            if getattr(p, "player_id", "") == player_id:
                return p
    except Exception:
        return None
    return None


# Phases during which the free-agent market is open. Drafts and
# playoffs are blocked so the owner can't sign free agents while the
# league is supposed to be focused elsewhere — same model as the
# extension phase gate.
_FA_OPEN_PHASES = {"REGULAR_SEASON", "OFFSEASON", "PRESEASON"}


def _current_league_phase() -> Optional[str]:
    try:
        from playbalance.season_manager import SeasonManager

        return SeasonManager().phase.value
    except Exception:
        return None


def _phase_gate_for_fa() -> Optional[Dict[str, str]]:
    """Return a 409 detail body if the FA market is closed right now."""

    phase = _current_league_phase()
    if phase and phase.upper() not in _FA_OPEN_PHASES:
        nice = phase.replace("_", " ").title()
        return {
            "code": "fa_window_closed",
            "message": (
                f"Free-agent signings are paused during {nice}. The market "
                "reopens in the regular season, offseason, or preseason."
            ),
            "phase": phase,
        }
    return None


def _competing_bids(
    player: Any,
    *,
    exclude_team_id: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Compute what other CPU teams would offer, top N by bid amount.

    Used by the FA evaluate endpoint to show the human owner who they're
    bidding against. Returns ``[]`` when the finance/FA module is off
    or no team would seriously bid.
    """

    try:
        from services.finance_ai import build_cpu_free_agent_bid_book
        from utils.team_loader import load_teams
    except Exception:
        return []

    # Pull the AI level from finance settings so we mirror what the
    # actual offseason auction would use.
    try:
        from services.finance_settings import load_financial_settings

        settings = load_financial_settings()
        ai_level = settings.module_level("gm_finance_ai") or "basic"
    except Exception:
        ai_level = "basic"

    try:
        teams = load_teams()
    except Exception:
        teams = []
    if not teams:
        return []

    try:
        bids = build_cpu_free_agent_bid_book(player, teams, ai_level=ai_level)
    except Exception:
        return []
    if not bids:
        return []

    rows = [
        {"team_id": tid, "salary": int(amt)}
        for tid, amt in bids.items()
        if tid != (exclude_team_id or "") and int(amt) > 0
    ]
    rows.sort(key=lambda r: -int(r["salary"]))
    return rows[:limit]


@router.post("/free-agents/{player_id}/evaluate-offer")
def evaluate_fa_offer(
    player_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Preview a free-agent contract offer.

    Returns: fair-market salary + length, the player's likely response
    to the proposed terms (accepted / countered / rejected), and the
    top competing CPU bids so the owner knows who they're up against.
    Pure preview — no roster mutation, no contract creation.
    """

    pid = str(player_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )
    player = _find_player(pid)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {pid} not found.",
        )

    try:
        offered_years = max(1, int(payload.get("years", 1) or 1))
    except (TypeError, ValueError):
        offered_years = 1
    salary_raw = payload.get("annual_salary")
    if salary_raw in (None, ""):
        offered_salary = fair_market_salary(
            player, service_time_days=FA_SERVICE_DAYS
        )
    else:
        try:
            offered_salary = int(salary_raw)
        except (TypeError, ValueError):
            offered_salary = fair_market_salary(
                player, service_time_days=FA_SERVICE_DAYS
            )

    evaluation = evaluate_extension_offer(
        player,
        offered_years=offered_years,
        offered_annual_salary=offered_salary,
        service_time_days=FA_SERVICE_DAYS,
    )

    callers_team = str(identity.get("t", "")).strip() or None
    competition = _competing_bids(player, exclude_team_id=callers_team)

    # Payroll impact preview for the caller's team: where payroll stands now,
    # where this offer would put it, and the tax/cash/solvency consequences.
    # Best-effort — the offer preview must still work if finance data is absent.
    payroll_impact: Optional[Dict[str, Any]] = None
    if callers_team:
        try:
            from services.payroll_policy import build_team_payroll_outlook

            try:
                bonus = max(0, int(payload.get("signing_bonus") or 0))
            except (TypeError, ValueError):
                bonus = 0
            payroll_impact = build_team_payroll_outlook(
                callers_team,
                extra_annual_salary=offered_salary,
                signing_bonus=bonus,
            )
        except Exception:
            payroll_impact = None

    phase_gate = _phase_gate_for_fa()
    return {
        "player_id": pid,
        "fair_market_salary": evaluation.fair_market_salary,
        "fair_market_years": evaluation.fair_market_years,
        "decision": evaluation.decision,
        "counter_salary": evaluation.counter_salary,
        "counter_years": evaluation.counter_years,
        "reason": evaluation.reason,
        "service_tier": evaluation.service_tier,
        "competing_bids": competition,
        "payroll_impact": payroll_impact,
        "phase_gate": phase_gate,
    }


@router.post("/teams/{team_id}/sign")
def sign_free_agent(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    require_team_owner(identity, team_id)
    player_id = str(payload.get("player_id", "")).strip()
    level_raw = str(payload.get("level", "ACT")).strip().upper()
    # Optional override: caller can supply a salary / years from the
    # contract-offer dialog. When omitted we fall back to the player's
    # fair-market value rather than the simple estimator so the offer
    # has a chance of being accepted.
    salary_override = payload.get("annual_salary")
    years_override = payload.get("years")
    # Optional up-front signing bonus that debits team cash on signing.
    try:
        signing_bonus = max(0, int(payload.get("signing_bonus") or 0))
    except (TypeError, ValueError):
        signing_bonus = 0
    # When the user has already seen the warning and wants to proceed
    # anyway, send acknowledge_warning=true.
    acknowledge_warning = bool(payload.get("acknowledge_warning", False))
    # Admin-only escape hatch: bypass negotiation + phase gate.
    force = bool(payload.get("force", False))
    role = str(identity.get("r", "")).lower()
    can_force = force and role == "admin"

    if not player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )
    if level_raw not in _LEVEL_ATTR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="level must be one of ACT / AAA / LOW.",
        )

    # FA window gate (skipped for admin force).
    if not can_force:
        phase_block = _phase_gate_for_fa()
        if phase_block:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=phase_block,
            )

    try:
        roster = load_roster(team_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load roster: {exc}",
        ) from exc

    # Make sure the player isn't already on this team somewhere.
    for attr in ("act", "aaa", "low", "dl", "ir"):
        if player_id in getattr(roster, attr, []):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{player_id} is already on {team_id}'s {attr.upper()} roster.",
            )

    # Resolve the player record once so payroll evaluation + contract
    # creation share the same source.
    player_record = _find_player(player_id)
    try:
        salary = (
            int(salary_override)
            if salary_override is not None
            else fair_market_salary(player_record, service_time_days=FA_SERVICE_DAYS)
            if player_record is not None
            else estimate_salary_for_player(player_record)
        )
    except (TypeError, ValueError):
        salary = estimate_salary_for_player(player_record)
    try:
        years = max(1, int(years_override)) if years_override is not None else (
            fair_market_years(player_record, service_time_days=FA_SERVICE_DAYS)
            if player_record is not None
            else 1
        )
    except (TypeError, ValueError):
        years = 1

    # Run the negotiation. Same engine as contract extensions — the
    # player evaluates the offer based on talent, age, and FA-tier
    # market expectations. Admin force bypasses.
    negotiation: Optional[Dict[str, Any]] = None
    if not can_force and player_record is not None:
        evaluation = evaluate_extension_offer(
            player_record,
            offered_years=years,
            offered_annual_salary=salary,
            service_time_days=FA_SERVICE_DAYS,
        )
        negotiation = evaluation.to_dict()
        if evaluation.decision != "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": evaluation.decision,
                    "message": evaluation.reason,
                    "player_id": player_id,
                    "negotiation": negotiation,
                    "competing_bids": _competing_bids(
                        player_record, exclude_team_id=team_id
                    ),
                },
            )

    # Payroll headroom check. Run BEFORE roster mutation so the user can
    # back out without dirty state. Honors the league's enforcement
    # mode: "block" rejects, "warn" lets the call proceed but surfaces
    # the warning in the response, "off" skips entirely. The
    # acknowledge_warning flag lets a UI re-submit the same request to
    # bypass a previously-shown warning without changing enforcement.
    payroll_warning: Dict[str, Any] | None = None
    try:
        eval_result = evaluate_free_agent_signing(
            team_id,
            annual_salary=salary,
            player=player_record,
        )
        if not eval_result.allowed and not acknowledge_warning:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "payroll_violation",
                    "message": (
                        f"Signing {player_id} for ${salary:,} would violate "
                        f"this team's payroll policy."
                    ),
                    "violations": eval_result.violations,
                    "mode": eval_result.mode,
                    "level": eval_result.level,
                },
            )
        if eval_result.warning or (not eval_result.allowed and acknowledge_warning):
            payroll_warning = {
                "violations": eval_result.violations,
                "mode": eval_result.mode,
                "level": eval_result.level,
                "acknowledged": acknowledge_warning,
            }
    except HTTPException:
        raise
    except Exception:
        # Payroll service unavailable — don't block the signing on a
        # bookkeeping bug; the contract still gets created below.
        payroll_warning = None

    # We don't re-validate "free agent" here because the roster_loader's
    # placeholder pool re-assigns IDs at signing time; trust the caller and
    # let save_roster + the placeholder reconciler resolve conflicts the
    # same way trades do.
    target_attr = _LEVEL_ATTR[level_raw]
    getattr(roster, target_attr).append(player_id)

    try:
        save_roster(team_id, roster)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save roster: {exc}",
        ) from exc

    # Create the contract. Without this the player sits on the roster
    # with $0 owed and finance pages misreport payroll until the next
    # offseason rollover backfills.
    contract: Dict[str, Any] | None = None
    try:
        years = max(1, int(years_override)) if years_override is not None else 1
    except (TypeError, ValueError):
        years = 1
    try:
        contract = sign_free_agent_contract(
            player_id,
            team_id,
            years_left=years,
            annual_salary=salary,
            signing_bonus=signing_bonus,
            player=player_record,
        )
    except Exception:
        contract = None

    # The signing bonus actually moves money: debit the team's cash now.
    bonus_charged = 0
    if signing_bonus > 0:
        try:
            from services.owner_finance_engine import charge_team_one_time_cost

            charged = charge_team_one_time_cost(
                team_id,
                signing_bonus,
                expense_type="signing_bonus",
                memo=f"FA signing bonus: {player_id}",
            )
            if charged.get("applied"):
                bonus_charged = int(charged.get("amount", 0) or 0)
        except Exception:
            bonus_charged = 0

    # Qualifying-offer compensation: a declined-QO player signing with a new
    # team earns his former team a draft-compensation slot.
    try:
        from services.qualifying_offers import track_qo_signing

        track_qo_signing(player_id, team_id)
    except Exception:
        pass

    try:
        record_transaction(
            action="sign",
            team_id=team_id,
            player_id=player_id,
            from_level="FA",
            to_level=level_raw,
            details=f"Signed as free agent to {level_raw} (${salary:,}/yr × {years})",
        )
    except Exception:
        pass

    return {
        "team_id": team_id,
        "player_id": player_id,
        "level": level_raw,
        "signed": True,
        "annual_salary": salary,
        "years": years,
        "signing_bonus": bonus_charged,
        "contract": contract,
        "payroll_warning": payroll_warning,
        "negotiation": negotiation,
        "forced": can_force,
    }
