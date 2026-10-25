"""Contract endpoints — owner-facing extension + league-wide tracker.

POST /contracts/{player_id}/extend     Extend an existing contract with
                                       optional salary / guaranteed /
                                       buyout / options / incentives
                                       overrides.
GET  /contracts                        Mid-season contract tracker:
                                       list every contract with derived
                                       fields (years remaining, expiry
                                       year, arb-eligible flag, option
                                       deadline summary). Used by the
                                       Contracts page to plan ahead.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from services.contract_negotiator import check_extension_eligibility
from services.contracts_service import (
    extend_contract,
    load_contracts_payload,
)
from services.extension_talks import TalksResponse, respond_to_offer, talks_view
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.rating_display import display_scale_for
from utils.sim_date import get_current_sim_date

from ._rating_presentation import compute_overall, page_scale
from ..security import CurrentIdentity, require_bearer, require_team_owner

router = APIRouter(prefix="/contracts", tags=["contracts"], dependencies=[CurrentIdentity])


def _resolve_current_year() -> int:
    """Best-effort current league year — falls back to today's year."""

    try:
        from services.trade_settings import current_league_year

        return int(current_league_year())
    except Exception:
        return datetime.utcnow().year


def _player_lookup() -> Dict[str, Any]:
    try:
        return {
            getattr(p, "player_id", ""): p
            for p in load_players_from_csv("data/players.csv")
        }
    except Exception:
        return {}


def _roster_team_index() -> Dict[str, str]:
    """``player_id -> team_id`` from the roster CSVs.

    Delegates to the shared lookup so the leaderboards and the contract tracker
    resolve teams identically — players.csv has no team_id column, so roster
    membership is the only source.
    """

    from services.team_lookup import player_team_index

    return player_team_index()


def _team_for(player_id: str, players: Dict[str, Any]) -> str:
    """Best-effort lookup of which team currently rosters a player.

    Kept for signature compatibility; prefer :func:`_roster_team_index` when
    resolving many players in one request.
    """

    return _roster_team_index().get(player_id, "")


def _age_of_player(player: Any) -> Optional[int]:
    """Player age from birthdate, or None when it can't be determined."""

    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if not birthdate:
        return None
    try:
        from playbalance.aging import calculate_age

        return calculate_age(birthdate)
    except Exception:
        return None


def _resolve_player(player_id: str) -> Any:
    try:
        for p in load_players_from_csv("data/players.csv"):
            if getattr(p, "player_id", "") == player_id:
                return p
    except Exception:
        return None
    return None


_EXTENSION_HISTORY_FILE = "extension_history.json"


def _extension_history_path() -> Path:
    return get_data_dir() / _EXTENSION_HISTORY_FILE


def _load_extension_history() -> Dict[str, Dict[str, Any]]:
    import json

    path = _extension_history_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for pid, entry in payload.items():
        if isinstance(entry, dict):
            out[str(pid)] = entry
    return out


def _save_extension_history(history: Dict[str, Dict[str, Any]]) -> None:
    import json

    from utils.atomic_write import atomic_text_writer

    path = _extension_history_path()
    try:
        with atomic_text_writer(path, encoding="utf-8") as fh:
            fh.write(json.dumps(history, indent=2))
    except Exception:
        pass


def _record_extension_outcome(player_id: str, decision: str) -> None:
    """Log the latest extension outcome (the talks state itself lives in
    services.extension_talks)."""

    history = _load_extension_history()
    entry = history.get(player_id) or {}
    sim_date = get_current_sim_date() or ""
    entry["last_decision"] = decision
    entry["last_offer_at"] = sim_date
    if decision == "rejected":
        entry["last_rejected_at"] = sim_date
    history[player_id] = entry
    _save_extension_history(history)


def _current_league_phase() -> Optional[str]:
    """Best-effort lookup of the active SeasonPhase string."""

    try:
        from playbalance.season_manager import SeasonManager

        return SeasonManager().phase.value
    except Exception:
        return None


def _service_for(player_id: str) -> tuple[int, int, int]:
    """Look up (service_time_days, current_salary, current_years_left)."""

    payload = load_contracts_payload()
    players = payload.get("players")
    if not isinstance(players, dict):
        return (0, 0, 0)
    raw = players.get(player_id)
    if not isinstance(raw, dict):
        return (0, 0, 0)
    return (
        int(raw.get("service_time_days", 0) or 0),
        int(raw.get("annual_salary", 0) or 0),
        int(raw.get("years_left", 0) or 0),
    )


@router.post("/{player_id}/evaluate-extension")
def evaluate_extension(
    player_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """What the owner sees before making an extension offer.

    ``{eligibility, payroll_impact, ask_salary, preferred_years, mood,
    status, shutdown_left, shutdown_unit, temperament, offers,
    service_tier, current_*}`` (``services.extension_talks.talks_view``).
    Since 8.5.0 it never says how the player would answer a given figure:
    the ask is above what he will take, and only a real offer finds out.
    Read-only.
    """

    pid = str(player_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )

    player = _resolve_player(pid)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {pid} not found.",
        )

    service_days, current_salary, current_years = _service_for(pid)
    phase = _current_league_phase()

    # House-rule eligibility check first — short-circuit the simulation
    # of an offer for players who can't legally receive one right now.
    # 8.5.0: the flat 30-day rejection cooldown is gone; a player's patience
    # and shutdowns live in services.extension_talks.
    eligibility = check_extension_eligibility(
        service_time_days=service_days,
        current_years_left=current_years,
        current_phase=phase,
    )

    try:
        offered_years = max(1, int(payload.get("years", 1) or 1))
    except (TypeError, ValueError):
        offered_years = 1

    # 8.5.0: the preview shows the player's ASK and his mood, never how he
    # would answer a given figure (that let an owner find his exact price
    # without risk). services.extension_talks has the negotiation.
    talks = talks_view(
        player,
        pid,
        team_id=_roster_team_index().get(pid, ""),
        years=offered_years,
        service_time_days=service_days,
        current_annual_salary=current_salary,
        current_years_left=current_years,
        phase=phase,
    )
    salary_raw = payload.get("annual_salary")
    if salary_raw in (None, ""):
        offered_salary = int(talks["ask_salary"])
    else:
        try:
            offered_salary = int(salary_raw)
        except (TypeError, ValueError):
            offered_salary = int(talks["ask_salary"])

    # Payroll impact of the RAISE this extension represents (the delta over the
    # player's current salary — they already count toward payroll) so the owner
    # sees how re-signing moves the books, matching the FA offer flow (#10).
    payroll_impact: Optional[Dict[str, Any]] = None
    # Honor an explicit team_id from the dialog — a commissioner/super-admin has
    # no bound identity["t"], so without it the payroll panel never shows.
    callers_team = (
        str(payload.get("team_id") or identity.get("t") or "").strip() or None
    )
    if callers_team:
        try:
            from services.payroll_policy import build_team_payroll_outlook

            delta = max(0, int(offered_salary) - int(current_salary or 0))
            payroll_impact = build_team_payroll_outlook(
                callers_team, extra_annual_salary=delta
            )
        except Exception:
            payroll_impact = None

    return {
        "player_id": pid,
        "current_annual_salary": current_salary,
        "current_years_left": current_years,
        "service_time_days": service_days,
        "eligibility": eligibility.to_dict(),
        "payroll_impact": payroll_impact,
        **talks,
    }


@router.post("/{player_id}/extend")
def extend_player_contract(
    player_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Extend a player's existing contract — runs negotiation first.

    Body fields:
      - additional_years: int, default 1 — years to tack on
      - annual_salary: int — overrides the existing salary going forward
      - force: bool — bypass the player's response and apply anyway
        (admins can use this to set up scenarios; default is false)

    Without ``force``, the player evaluates the offer:
      - "accepted" → contract updated, returned with ``negotiation``
      - "countered" / "shutdown" / "refused" / "blocked" → 409 with the
        player's answer in ``negotiation`` (``services.extension_talks``:
        his new ask, his mood, how long a shutdown lasts)
    """

    pid = str(player_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )
    # Server-side ownership: only the team that rosters this player (or an
    # admin/commissioner) may extend him.
    require_team_owner(identity, _roster_team_index().get(pid, ""))

    try:
        years = int(payload.get("additional_years", 1) or 1)
    except (TypeError, ValueError):
        years = 1
    salary_raw = payload.get("annual_salary")
    salary: Optional[int] = None
    if salary_raw is not None and salary_raw != "":
        try:
            salary = int(salary_raw)
        except (TypeError, ValueError):
            salary = None
    guaranteed_raw = payload.get("guaranteed")
    guaranteed = bool(guaranteed_raw) if guaranteed_raw is not None else None
    buyout_raw = payload.get("buyout_guarantee")
    buyout: Optional[int] = None
    if buyout_raw is not None:
        try:
            buyout = int(buyout_raw)
        except (TypeError, ValueError):
            buyout = None
    force = bool(payload.get("force", False))

    # Negotiate unless force is set. Force is gated to admins so an
    # owner can't bypass their own player's counter-offer.
    role = str(identity.get("r", "")).lower()
    evaluation: Optional[TalksResponse] = None
    if not force or role != "admin":
        player = _resolve_player(pid)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Player {pid} not found.",
            )
        service_days, current_salary, current_years = _service_for(pid)
        phase = _current_league_phase()

        # House-rule eligibility check first. Phase gating, FA-year
        # lockout and the years-remaining cap live here — admins with
        # force=true can still bypass. Patience, shutdowns and in-season
        # refusals are the player's (services.extension_talks, 8.5.0).
        eligibility = check_extension_eligibility(
            service_time_days=service_days,
            current_years_left=current_years,
            current_phase=phase,
        )
        if not eligibility.eligible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": eligibility.code,
                    "message": eligibility.reason,
                    "player_id": pid,
                    "eligibility": eligibility.to_dict(),
                    "current_annual_salary": current_salary,
                    "current_years_left": current_years,
                },
            )

        team_id = _roster_team_index().get(pid, "")
        if salary is None:
            # No figure given: offer his current ask.
            salary = int(talks_view(
                player, pid, team_id=team_id, years=years,
                service_time_days=service_days,
                current_annual_salary=current_salary,
                current_years_left=current_years, phase=phase,
            )["ask_salary"])
        evaluation = respond_to_offer(
            player,
            pid,
            team_id=team_id,
            years=years,
            salary=salary,
            service_time_days=service_days,
            current_annual_salary=current_salary,
            current_years_left=current_years,
            phase=phase,
        )
        if evaluation.decision != "accepted":
            _record_extension_outcome(pid, evaluation.decision)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": evaluation.decision,
                    "message": evaluation.reason,
                    "player_id": pid,
                    "negotiation": evaluation.to_dict(),
                    "current_annual_salary": current_salary,
                    "current_years_left": current_years,
                },
            )

    contract = extend_contract(
        pid,
        additional_years=years,
        annual_salary=salary,
        guaranteed=guaranteed,
        buyout_guarantee=buyout,
    )
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No active contract for {pid} — only existing contracts can "
                "be extended (sign the player first)."
            ),
        )

    # Acceptance recorded too so the offer log is complete and the
    # last_offer_at field stays current. Doesn't affect cooldown
    # (cooldown only triggers on "rejected").
    _record_extension_outcome(pid, "accepted" if evaluation else "forced")

    return {
        "player_id": pid,
        "extended_by": str(identity.get("u", "") or ""),
        "contract": contract,
        "negotiation": evaluation.to_dict() if evaluation else None,
        "forced": force and role == "admin",
    }


def _require_advanced_contracts() -> None:
    """Gate options/renew to leagues on the ADVANCED gm_contracts model (D2)."""
    from services.finance_settings import load_financial_settings

    settings = load_financial_settings(
        path=get_data_dir() / "league_financial_settings.json"
    )
    if not settings.enabled or settings.module_level("gm_contracts") != "advanced":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This action requires the advanced contracts finance model.",
        )


@router.post("/{player_id}/option")
def decide_contract_option(
    player_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Owner action: exercise or decline a contract option (team/player/mutual/
    vesting). Requires the advanced contracts model + team ownership."""

    pid = str(player_id or "").strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="player_id is required.")
    require_team_owner(identity, _roster_team_index().get(pid, ""))
    _require_advanced_contracts()

    decision = str(payload.get("decision", "")).strip().lower()
    if decision not in {"exercised", "declined"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'exercised' or 'declined'.",
        )
    try:
        option_index = int(payload.get("option_index", 0) or 0)
    except (TypeError, ValueError):
        option_index = 0

    from services.contracts_service import set_contract_option_decision

    result = set_contract_option_decision(
        pid, decision=decision, option_index=option_index, data_dir=get_data_dir()
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such contract option for this player.",
        )
    return {"player_id": pid, "decision": decision, "option_index": option_index, "contract": result}


@router.post("/{player_id}/renew")
def renew_pre_arb_contract(
    player_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Owner action: renew a PRE-ARB player's salary for the coming year (pre-arb
    players don't negotiate — the team sets the renewal salary). Requires the
    advanced contracts model + team ownership."""

    pid = str(player_id or "").strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="player_id is required.")
    require_team_owner(identity, _roster_team_index().get(pid, ""))
    _require_advanced_contracts()

    salary_raw = payload.get("annual_salary")
    if salary_raw is None or salary_raw == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="annual_salary is required.")
    try:
        annual_salary = int(salary_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="annual_salary must be a number.")

    from services.contracts_service import renew_pre_arb_salary

    result = renew_pre_arb_salary(pid, annual_salary=annual_salary, data_dir=get_data_dir())
    if not result.get("renewed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(result.get("message") or "Could not renew this contract."),
        )
    return result


@router.get("")
def list_contracts(
    team_id: Optional[str] = None,
    expiring_only: bool = False,
) -> Dict[str, Any]:
    """League-wide contract tracker.

    Each row carries the canonical contract fields plus derived helpers
    the UI needs (player name, position, expiry year, "expires soon"
    flag, current team).

    Filters:
      - team_id: only contracts where the player is rostered on this team
      - expiring_only: only contracts with years_left <= 1
    """

    payload = load_contracts_payload()
    players_block = payload.get("players")
    if not isinstance(players_block, dict):
        players_block = {}

    players_index = _player_lookup()
    current_year = _resolve_current_year()
    league_scale = page_scale()
    rows: List[Dict[str, Any]] = []

    # Built lazily, at most once per request — only if some contract row is
    # missing team_id (the old code re-scanned every roster CSV per such row).
    roster_teams: Optional[Dict[str, str]] = None

    for pid, raw in players_block.items():
        if not isinstance(raw, dict):
            continue
        team = str(raw.get("team_id", "") or "").strip()
        if not team:
            if roster_teams is None:
                roster_teams = _roster_team_index()
            team = roster_teams.get(pid, "")
        if team_id and team != team_id:
            continue
        years_left = int(raw.get("years_left", 0) or 0)
        if expiring_only and years_left > 1:
            continue
        player = players_index.get(pid)
        first = getattr(player, "first_name", "") if player else ""
        last = getattr(player, "last_name", "") if player else ""
        position = getattr(player, "primary_position", "") if player else ""
        is_pitcher = bool(getattr(player, "is_pitcher", False)) if player else False
        # Age and overall so a salary can be read against the player it's
        # paying — sorting by either against salary is how you spot a deal
        # that's out of line. Same overall the roster/list views show.
        age = _age_of_player(player)
        overall = None
        if player is not None:
            try:
                overall = compute_overall(
                    lambda key: getattr(player, key, None),
                    is_pitcher=is_pitcher,
                    position=position or None,
                    scale=display_scale_for(player, league_scale),
                ).get("overall_display")
            except Exception:  # pragma: no cover - defensive
                overall = None
        annual_salary = int(raw.get("annual_salary", 0) or 0)
        fa_year = int(raw.get("fa_year", current_year + years_left) or 0)
        options = raw.get("options") or []
        pending_options = sum(
            1
            for opt in options
            if isinstance(opt, dict)
            and str(opt.get("decision", "pending")).lower() == "pending"
        )
        rows.append(
            {
                "player_id": pid,
                "first_name": first,
                "last_name": last,
                "primary_position": position,
                "is_pitcher": is_pitcher,
                "age": age,
                "overall": overall,
                "team_id": team,
                "annual_salary": annual_salary,
                "years_left": years_left,
                "fa_year": fa_year,
                "guaranteed": bool(raw.get("guaranteed", True)),
                "buyout_guarantee": int(raw.get("buyout_guarantee", 0) or 0),
                "arb_eligible": bool(raw.get("arb_eligible", False)),
                "service_time_days": int(raw.get("service_time_days", 0) or 0),
                "pending_options": pending_options,
                "expiring_this_year": years_left <= 1,
            }
        )

    rows.sort(
        key=lambda r: (
            -int(r.get("expiring_this_year", False)),
            int(r.get("years_left", 0)),
            -int(r.get("annual_salary", 0)),
        )
    )

    return {
        "current_year": current_year,
        "count": len(rows),
        "contracts": rows,
    }
