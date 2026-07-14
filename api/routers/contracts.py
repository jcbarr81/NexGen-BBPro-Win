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

from services.contract_negotiator import (
    ExtensionEvaluation,
    REJECTION_COOLDOWN_DAYS,
    check_extension_eligibility,
    evaluate_extension_offer,
    fair_market_salary,
    fair_market_years,
)
from services.contracts_service import (
    extend_contract,
    load_contracts_payload,
)
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.sim_date import get_current_sim_date

from ..security import CurrentIdentity, require_bearer

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
    """Best-effort ``player_id -> team_id`` map built from ONE pass over the
    roster CSVs.

    Mirrors the old per-player ``_team_for`` scan exactly: every roster level
    counts (any row whose first cell is the player id, regardless of
    ACT/AAA/LOW/DL/IR), and the first roster file in glob order that contains
    the player wins. Building the dict once turns the league tracker's
    contracts x rosters file-open storm into a single roster sweep.
    """

    rosters_dir = get_data_dir() / "rosters"
    if not rosters_dir.exists():
        return {}
    import csv

    index: Dict[str, str] = {}
    for roster_file in rosters_dir.glob("*.csv"):
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) < 1:
                        continue
                    pid = (row[0] or "").strip()
                    if pid:
                        # First file containing the player wins (glob order),
                        # matching the early-return of the per-player scan.
                        index.setdefault(pid, roster_file.stem)
        except OSError:
            continue
    return index


def _team_for(player_id: str, players: Dict[str, Any]) -> str:
    """Best-effort lookup of which team currently rosters a player.

    Kept for signature compatibility; prefer :func:`_roster_team_index` when
    resolving many players in one request.
    """

    return _roster_team_index().get(player_id, "")


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

    path = _extension_history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass


def _record_extension_outcome(player_id: str, decision: str) -> None:
    """Persist the latest extension outcome so the cooldown rule has data."""

    history = _load_extension_history()
    entry = history.get(player_id) or {}
    sim_date = get_current_sim_date() or ""
    entry["last_decision"] = decision
    entry["last_offer_at"] = sim_date
    if decision == "rejected":
        entry["last_rejected_at"] = sim_date
    history[player_id] = entry
    _save_extension_history(history)


def _last_rejected_iso(player_id: str) -> Optional[str]:
    history = _load_extension_history()
    entry = history.get(player_id) or {}
    raw = entry.get("last_rejected_at")
    return str(raw) if raw else None


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
) -> Dict[str, Any]:
    """Preview how a player would respond to an extension offer.

    Returns the same shape as the extend endpoint's evaluation block:
    ``{decision, fair_market_salary, fair_market_years, counter_*, reason}``.
    Does NOT mutate the contract — used by the Extend dialog to show a
    fair-value hint and let the owner explore offers before submitting.
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

    # House-rule eligibility check first — short-circuit the simulation
    # of an offer for players who can't legally receive one right now.
    eligibility = check_extension_eligibility(
        service_time_days=service_days,
        current_years_left=current_years,
        current_phase=_current_league_phase(),
        last_rejected_iso=_last_rejected_iso(pid),
        sim_date_iso=get_current_sim_date(),
    )

    try:
        offered_years = max(1, int(payload.get("years", 1) or 1))
    except (TypeError, ValueError):
        offered_years = 1
    salary_raw = payload.get("annual_salary")
    if salary_raw in (None, ""):
        offered_salary = current_salary or fair_market_salary(
            player, service_time_days=service_days
        )
    else:
        try:
            offered_salary = int(salary_raw)
        except (TypeError, ValueError):
            offered_salary = current_salary

    evaluation = evaluate_extension_offer(
        player,
        offered_years=offered_years,
        offered_annual_salary=offered_salary,
        service_time_days=service_days,
        current_annual_salary=current_salary,
        current_years_left=current_years,
    )
    return {
        "player_id": pid,
        "current_annual_salary": current_salary,
        "current_years_left": current_years,
        "service_time_days": service_days,
        "eligibility": eligibility.to_dict(),
        **evaluation.to_dict(),
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
      - "countered" → 409 with the player's counter-offer; owner can
        re-submit with the counter terms or with ``force=true``
      - "rejected" → 409 with reason; owner is locked out of further
        offers for this player until they cool down (handled client-side)
    """

    pid = str(player_id or "").strip()
    if not pid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required.",
        )

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
    evaluation: Optional[ExtensionEvaluation] = None
    if not force or role != "admin":
        player = _resolve_player(pid)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Player {pid} not found.",
            )
        service_days, current_salary, current_years = _service_for(pid)

        # House-rule eligibility check first. Phase gating, FA-year
        # lockout, years-remaining cap, and rejection cooldown all live
        # here — admins with force=true can still bypass.
        eligibility = check_extension_eligibility(
            service_time_days=service_days,
            current_years_left=current_years,
            current_phase=_current_league_phase(),
            last_rejected_iso=_last_rejected_iso(pid),
            sim_date_iso=get_current_sim_date(),
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

        # If salary not specified, use current salary as the offer.
        offer_salary = salary if salary is not None else current_salary
        if offer_salary <= 0:
            offer_salary = fair_market_salary(
                player, service_time_days=service_days
            )
        evaluation = evaluate_extension_offer(
            player,
            offered_years=years,
            offered_annual_salary=offer_salary,
            service_time_days=service_days,
            current_annual_salary=current_salary,
            current_years_left=current_years,
        )
        if evaluation.decision != "accepted":
            # Record the rejection so the cooldown timer starts. We
            # only persist for actual rejections — a counter-offer
            # leaves the door open for the owner to come right back.
            if evaluation.decision == "rejected":
                _record_extension_outcome(pid, "rejected")
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
