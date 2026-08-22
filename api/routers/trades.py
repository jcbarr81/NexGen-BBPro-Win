"""Trade list endpoint.

Reads ``data/trades_pending.csv`` via :func:`utils.trade_utils.load_trades`
and hydrates each side with player names so the React page can render
without a second trip to ``/players``. Read-only in this iteration --
proposing / accepting / rejecting trades will ride on top in a follow-up
via the existing ``utils.trade_utils.save_trade``.
"""

from __future__ import annotations

import csv
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from models.trade import Trade
from services.draft_pick_ledger import format_pick_label, transfer_pick
from services.transaction_log import record_transaction
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster
from utils.trade_utils import load_trades, save_trade

from ..security import CurrentIdentity, require_bearer, require_team_owner

router = APIRouter(prefix="/trades", tags=["trades"], dependencies=[CurrentIdentity])


def _require_admin(identity: Dict[str, Any]) -> None:
    """Commissioner/super-admin only (trade approve/veto/reverse)."""
    if str(identity.get("r", "")).lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to the commissioner.",
        )


def _require_trade_party(identity: Dict[str, Any], trade: Trade) -> None:
    """Either team in the trade (or the commissioner) — e.g. to reject."""
    if str(identity.get("r", "")).lower() == "admin":
        return
    team = str(identity.get("t") or "").strip()
    if team and team in {trade.from_team, trade.to_team}:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You're not a party to this trade.",
    )


def _player_label(player: Any | None, pid: str) -> str:
    if player is None:
        return pid
    first = getattr(player, "first_name", "") or ""
    last = getattr(player, "last_name", "") or ""
    name = f"{first} {last}".strip()
    return name or pid


def _player_summary(player: Any | None, pid: str) -> Dict[str, Any]:
    if player is None:
        return {"player_id": pid, "name": pid, "position": "", "is_pitcher": False}
    return {
        "player_id": pid,
        "name": _player_label(player, pid),
        "position": getattr(player, "primary_position", "") or "",
        "is_pitcher": bool(getattr(player, "is_pitcher", False)),
    }


@router.get("/deadline")
def trade_deadline() -> Dict[str, Any]:
    """Return the active trade deadline + how many sim days remain."""

    from utils.trade_utils import (
        current_trade_deadline,
        days_until_trade_deadline,
        is_past_trade_deadline,
        _today,
    )

    deadline = current_trade_deadline()
    today = _today()
    days_remaining = days_until_trade_deadline()
    return {
        "deadline_date": deadline.isoformat(),
        "current_sim_date": today.isoformat(),
        "days_remaining": days_remaining,
        "is_past": is_past_trade_deadline(),
    }


@router.get("")
def list_trades(
    team_id: Optional[str] = Query(default=None, description="Involving this team (give or receive)"),
    status: Optional[str] = Query(default=None, description="Filter by status (pending, accepted, rejected, ...)"),
) -> Dict[str, Any]:
    trades = load_trades()
    cpu_evals = _load_cpu_evals()

    # One players.csv hydration for all trades.
    try:
        players = {getattr(p, "player_id", ""): p for p in load_players_from_csv("data/players.csv")}
    except Exception:
        players = {}

    status_norm = status.strip().lower() if status else None

    out: List[Dict[str, Any]] = []
    for trade in trades:
        if status_norm and str(trade.status).lower() != status_norm:
            continue
        if team_id and team_id not in (trade.from_team, trade.to_team):
            continue
        out.append(
            {
                "trade_id": trade.trade_id,
                "from_team": trade.from_team,
                "to_team": trade.to_team,
                "status": trade.status,
                "initiated_by": getattr(trade, "initiated_by", "human") or "human",
                "cpu_eval": cpu_evals.get(trade.trade_id),
                "give_players": [
                    _player_summary(players.get(pid), pid) for pid in trade.give_player_ids
                ],
                "receive_players": [
                    _player_summary(players.get(pid), pid) for pid in trade.receive_player_ids
                ],
                "give_picks": list(trade.give_pick_ids or []),
                "receive_picks": list(trade.receive_pick_ids or []),
            }
        )

    # Group by status for convenient UI rendering.
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in out:
        grouped.setdefault(row["status"], []).append(row)

    return {"count": len(out), "trades": out, "grouped": grouped}


# ---------------------------------------------------------------------------
# Write actions: propose / accept / reject / withdraw


def _find_trade(trade_id: str) -> Trade:
    for trade in load_trades():
        if trade.trade_id == trade_id:
            return trade
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Trade {trade_id} not found.",
    )


def _commit_trade(trade: Trade) -> None:
    """Apply a trade's roster + pick swap, log transactions, announce.

    Thin HTTP wrapper (S2-10): the executable logic now lives in
    ``services.trade_execution.commit_trade`` (FastAPI-free so the CPU-CPU lane
    can reuse it). A pick-ownership failure surfaces there as ``ValueError`` and
    is re-raised as an HTTP 400 to preserve the previous behavior.
    """

    from services.trade_execution import announce_trade, commit_trade

    try:
        commit_trade(trade)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    announce_trade(trade)


_CPU_EVAL_FILENAME = "trade_cpu_evals.json"


def _cpu_eval_path():
    from utils.path_utils import get_data_dir

    return get_data_dir() / _CPU_EVAL_FILENAME


def _load_cpu_evals() -> Dict[str, Dict[str, Any]]:
    import json

    path = _cpu_eval_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): v for k, v in payload.items() if isinstance(v, dict)}


def _persist_cpu_eval(trade_id: str, evaluation: Dict[str, Any]) -> None:
    import json

    history = _load_cpu_evals()
    history[str(trade_id)] = evaluation
    path = _cpu_eval_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass


def _trade_payload_to_dict(payload: Dict[str, Any]) -> Trade:
    from_team = str(payload.get("from_team", "")).strip()
    to_team = str(payload.get("to_team", "")).strip()
    if not from_team or not to_team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_team and to_team are required.",
        )
    if from_team == to_team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_team and to_team must differ.",
        )

    def _ids(key: str) -> List[str]:
        raw = payload.get(key) or []
        if not isinstance(raw, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a list.",
            )
        return [str(x).strip() for x in raw if str(x).strip()]

    return Trade(
        trade_id=uuid.uuid4().hex[:8],
        from_team=from_team,
        to_team=to_team,
        give_player_ids=_ids("give_player_ids"),
        receive_player_ids=_ids("receive_player_ids"),
        give_pick_ids=_ids("give_pick_ids"),
        receive_pick_ids=_ids("receive_pick_ids"),
        initiated_by="human",
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def propose_trade(
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    trade = _trade_payload_to_dict(payload)
    # You can only propose a trade FROM a team you own (or as the commissioner).
    require_team_owner(identity, trade.from_team)

    # Run the shared validator before persisting. We wire in the current
    # commissioner trade settings so draft-pick toggles + year caps fire.
    from services.roster_validation import validate_trade

    from .validation import load_players_map, load_team_levels

    try:
        from services.commissioner_settings import load_trade_settings  # type: ignore

        trade_settings = load_trade_settings()
    except Exception:
        trade_settings = {}
    settings = {
        "draft_pick_trading_enabled": bool(
            getattr(trade_settings, "draft_pick_trading_enabled", True)
            if not isinstance(trade_settings, dict)
            else trade_settings.get("draft_pick_trading_enabled", True)
        ),
        "max_pick_trade_years": (
            getattr(trade_settings, "max_pick_trade_years", None)
            if not isinstance(trade_settings, dict)
            else trade_settings.get("max_pick_trade_years")
        ),
    }
    players_map = load_players_map()
    from_levels = load_team_levels(trade.from_team)
    to_levels = load_team_levels(trade.to_team)
    # Trade dataclass uses ``give_player_ids`` / ``give_pick_ids`` —
    # earlier code referenced ``give_players`` / ``give_picks`` which
    # don't exist on the model and crashed on every propose call.
    result = validate_trade(
        give_player_ids=list(trade.give_player_ids),
        receive_player_ids=list(trade.receive_player_ids),
        give_pick_ids=list(trade.give_pick_ids),
        receive_pick_ids=list(trade.receive_pick_ids),
        from_team_levels=from_levels,
        to_team_levels=to_levels,
        players=players_map,
        settings=settings,
    )
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Trade fails validation.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    try:
        save_trade(trade)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # If the receiving team is CPU-controlled, run an immediate
    # evaluation so the proposal doesn't sit in "pending" forever
    # waiting for a CPU response that was never coming. The evaluator
    # decides accept / reject / counter; we apply the verdict and
    # surface the reasoning back to the owner.
    cpu_response: Dict[str, Any] | None = None
    counter_trade_id: str | None = None
    try:
        from services.cpu_trade_evaluator import (
            evaluate_cpu_trade_offer,
            is_cpu_owned_team,
        )

        if is_cpu_owned_team(trade.to_team):
            evaluation = evaluate_cpu_trade_offer(trade)
            if evaluation is not None:
                cpu_response = {
                    "team_id": evaluation.team_id,
                    "action": evaluation.action,
                    "total_score": float(evaluation.total_score),
                    "threshold": float(evaluation.threshold),
                    "value_delta": float(evaluation.value_delta),
                    "fit_delta": float(evaluation.fit_delta),
                    "timeline_delta": float(evaluation.timeline_delta),
                    "strategy_profile": evaluation.strategy_profile,
                    "competitive_window": evaluation.competitive_window,
                    "reasons": [
                        getattr(r, "summary", str(r))
                        for r in (evaluation.reasons or [])
                    ],
                }
                _persist_cpu_eval(trade.trade_id, cpu_response)

                if evaluation.action == "accept":
                    trade.status = "accepted"
                    try:
                        _commit_trade(trade)
                        save_trade(trade)
                    except HTTPException:
                        raise
                    except Exception:
                        # Roll back to pending if the commit fails so a
                        # bad accept doesn't leave a half-applied trade.
                        trade.status = "pending"
                        save_trade(trade)
                elif evaluation.action == "reject":
                    trade.status = "rejected"
                    save_trade(trade)
                elif evaluation.action == "counter" and evaluation.counter_offer:
                    # The original proposal is dead; the CPU's counter
                    # is filed as a new pending trade in the opposite
                    # direction so the owner sees it in their inbox.
                    trade.status = "rejected"
                    save_trade(trade)
                    counter = Trade(
                        trade_id=uuid.uuid4().hex[:8],
                        from_team=trade.to_team,
                        to_team=trade.from_team,
                        give_player_ids=list(
                            evaluation.counter_offer.get("incoming_player_ids", [])
                            or []
                        ),
                        receive_player_ids=list(
                            evaluation.counter_offer.get("outgoing_player_ids", [])
                            or []
                        ),
                        give_pick_ids=list(
                            evaluation.counter_offer.get("incoming_pick_ids", [])
                            or []
                        ),
                        receive_pick_ids=list(
                            evaluation.counter_offer.get("outgoing_pick_ids", [])
                            or []
                        ),
                        initiated_by="cpu",
                    )
                    try:
                        save_trade(counter)
                        counter_trade_id = counter.trade_id
                    except Exception:
                        counter_trade_id = None
    except HTTPException:
        raise
    except Exception:
        # Evaluation is best-effort. If it throws, leave the trade
        # pending and the owner can still wait it out manually.
        cpu_response = None

    return {
        "trade_id": trade.trade_id,
        "from_team": trade.from_team,
        "to_team": trade.to_team,
        "status": trade.status,
        "cpu_response": cpu_response,
        "counter_trade_id": counter_trade_id,
    }


@router.post("/{trade_id}/accept")
def accept_trade(
    trade_id: str,
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    trade = _find_trade(trade_id)
    # Only the RECEIVING team's owner (to_team) — or the commissioner — may
    # accept. Both owners agreeing is enough to commit (no separate commissioner
    # approval); the commissioner can reverse a committed trade afterward.
    require_team_owner(identity, trade.to_team)
    if str(trade.status).lower() in {"accepted", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trade {trade_id} is already {trade.status}.",
        )
    trade.status = "accepted"
    _commit_trade(trade)
    try:
        save_trade(trade)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"trade_id": trade.trade_id, "status": trade.status}


@router.post("/{trade_id}/admin-approve")
def admin_approve_trade(
    trade_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Commissioner override: force-accept a pending trade.

    Bypasses the per-owner acceptance step. Still runs payroll policy +
    shared validator; if ``force=true`` is passed, those are reduced to
    warnings. Commissioner-only.
    """

    _require_admin(identity)
    force = bool(payload.get("force", False))
    trade = _find_trade(trade_id)
    if str(trade.status).lower() in {"accepted", "rejected", "vetoed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trade {trade_id} is already {trade.status}.",
        )

    # Re-run shared validator; admin force path collapses errors to warnings.
    from services.roster_validation import validate_trade

    from .validation import load_players_map, load_team_levels

    players_map = load_players_map()
    from_levels = load_team_levels(trade.from_team)
    to_levels = load_team_levels(trade.to_team)
    result = validate_trade(
        give_player_ids=list(trade.give_player_ids),
        receive_player_ids=list(trade.receive_player_ids),
        give_pick_ids=list(trade.give_pick_ids),
        receive_pick_ids=list(trade.receive_pick_ids),
        from_team_levels=from_levels,
        to_team_levels=to_levels,
        players=players_map,
    )
    if not result.ok and not force:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Trade would violate rules. Pass force=true to override.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    trade.status = "accepted"
    _commit_trade(trade)
    try:
        save_trade(trade)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {
        "trade_id": trade.trade_id,
        "status": trade.status,
        "forced": force,
        "warnings": result.warnings,
    }


@router.post("/{trade_id}/veto")
def admin_veto_trade(
    trade_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Commissioner veto: reject a pending trade with an admin note."""

    _require_admin(identity)
    trade = _find_trade(trade_id)
    if str(trade.status).lower() in {"accepted", "rejected", "vetoed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trade {trade_id} is already {trade.status}.",
        )
    note = str(payload.get("note", "")).strip()
    trade.status = "vetoed"
    if hasattr(trade, "admin_note"):
        trade.admin_note = note  # type: ignore[attr-defined]
    try:
        save_trade(trade)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"trade_id": trade.trade_id, "status": trade.status, "note": note}


@router.post("/{trade_id}/counter")
def counter_trade(
    trade_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Owner counters a CPU offer.

    Rejects the original CPU-initiated trade and files a new
    owner-initiated trade in the opposite direction with the modified
    terms. That counter then runs through the same CPU evaluation as
    any direct propose, so the CPU may accept, reject, or counter
    again — same logic as a fresh proposal.

    Body:
      give_player_ids / receive_player_ids / give_pick_ids / receive_pick_ids
        — the owner's revised terms, expressed from the OWNER's
        perspective (give = what you part with, receive = what you get).
    """

    original = _find_trade(trade_id)
    # The countering owner must own the team the CPU made the offer TO.
    require_team_owner(identity, original.to_team)
    if str(original.status).lower() in {"accepted", "rejected", "vetoed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trade {trade_id} is already {original.status}.",
        )
    if (original.initiated_by or "human") != "cpu":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only CPU-initiated offers can be countered. To revise "
                "your own pending proposal, withdraw it and submit a "
                "new one."
            ),
        )

    # Owner-perspective: give = what owner_team parts with → counter
    # trade has from_team=owner_team, to_team=cpu_team (the original's
    # from_team was the CPU). The owner's "give" players go from the
    # owner's roster to the CPU's roster.
    owner_team = original.to_team
    cpu_team = original.from_team

    def _ids(key: str) -> List[str]:
        raw = payload.get(key) or []
        if not isinstance(raw, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be a list.",
            )
        return [str(x).strip() for x in raw if str(x).strip()]

    counter = Trade(
        trade_id=uuid.uuid4().hex[:8],
        from_team=owner_team,
        to_team=cpu_team,
        give_player_ids=_ids("give_player_ids"),
        receive_player_ids=_ids("receive_player_ids"),
        give_pick_ids=_ids("give_pick_ids"),
        receive_pick_ids=_ids("receive_pick_ids"),
        initiated_by="human",
    )

    # Reject the original first so the inbox doesn't have stale offers
    # competing with the live counter.
    original.status = "rejected"
    try:
        save_trade(original)
    except RuntimeError:
        pass

    # Reuse the propose pipeline's validation + auto-eval by feeding
    # the counter through the same module-level helpers. The propose
    # endpoint itself is HTTP-tied, so we inline the equivalent flow.
    from services.roster_validation import validate_trade

    from .validation import load_players_map, load_team_levels

    players_map = load_players_map()
    from_levels = load_team_levels(counter.from_team)
    to_levels = load_team_levels(counter.to_team)
    result = validate_trade(
        give_player_ids=list(counter.give_player_ids),
        receive_player_ids=list(counter.receive_player_ids),
        give_pick_ids=list(counter.give_pick_ids),
        receive_pick_ids=list(counter.receive_pick_ids),
        from_team_levels=from_levels,
        to_team_levels=to_levels,
        players=players_map,
    )
    if not result.ok:
        # Roll back the rejection so the owner can keep the original
        # CPU offer alive while they fix their counter.
        original.status = "pending"
        try:
            save_trade(original)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Counter proposal fails validation.",
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    try:
        save_trade(counter)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    cpu_response: Dict[str, Any] | None = None
    counter_back_id: str | None = None
    try:
        from services.cpu_trade_evaluator import (
            evaluate_cpu_trade_offer,
            is_cpu_owned_team,
        )

        if is_cpu_owned_team(counter.to_team):
            evaluation = evaluate_cpu_trade_offer(counter)
            if evaluation is not None:
                cpu_response = {
                    "team_id": evaluation.team_id,
                    "action": evaluation.action,
                    "total_score": float(evaluation.total_score),
                    "threshold": float(evaluation.threshold),
                    "value_delta": float(evaluation.value_delta),
                    "fit_delta": float(evaluation.fit_delta),
                    "timeline_delta": float(evaluation.timeline_delta),
                    "strategy_profile": evaluation.strategy_profile,
                    "competitive_window": evaluation.competitive_window,
                    "reasons": [
                        getattr(r, "summary", str(r))
                        for r in (evaluation.reasons or [])
                    ],
                }
                _persist_cpu_eval(counter.trade_id, cpu_response)
                if evaluation.action == "accept":
                    counter.status = "accepted"
                    try:
                        _commit_trade(counter)
                        save_trade(counter)
                    except Exception:
                        counter.status = "pending"
                        save_trade(counter)
                elif evaluation.action == "reject":
                    counter.status = "rejected"
                    save_trade(counter)
                elif evaluation.action == "counter" and evaluation.counter_offer:
                    counter.status = "rejected"
                    save_trade(counter)
                    second_counter = Trade(
                        trade_id=uuid.uuid4().hex[:8],
                        from_team=counter.to_team,
                        to_team=counter.from_team,
                        give_player_ids=list(
                            evaluation.counter_offer.get("incoming_player_ids", [])
                            or []
                        ),
                        receive_player_ids=list(
                            evaluation.counter_offer.get("outgoing_player_ids", [])
                            or []
                        ),
                        give_pick_ids=list(
                            evaluation.counter_offer.get("incoming_pick_ids", [])
                            or []
                        ),
                        receive_pick_ids=list(
                            evaluation.counter_offer.get("outgoing_pick_ids", [])
                            or []
                        ),
                        initiated_by="cpu",
                    )
                    try:
                        save_trade(second_counter)
                        counter_back_id = second_counter.trade_id
                    except Exception:
                        counter_back_id = None
    except Exception:
        cpu_response = None

    return {
        "original_trade_id": original.trade_id,
        "original_status": original.status,
        "counter_trade_id": counter.trade_id,
        "counter_status": counter.status,
        "cpu_response": cpu_response,
        "counter_back_id": counter_back_id,
    }


@router.post("/{trade_id}/reject")
def reject_trade(
    trade_id: str,
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    trade = _find_trade(trade_id)
    # Either party to the trade (or the commissioner) may decline it.
    _require_trade_party(identity, trade)
    if str(trade.status).lower() == "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reject an already-accepted trade.",
        )
    trade.status = "rejected"
    try:
        save_trade(trade)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"trade_id": trade.trade_id, "status": trade.status}


@router.delete("/{trade_id}")
def withdraw_trade(
    trade_id: str,
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Withdraw a pending trade by writing the file without it."""

    trades = load_trades()
    target = next((t for t in trades if t.trade_id == trade_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trade {trade_id} not found.",
        )
    # Only the initiating team's owner (from_team) — or the commissioner — may
    # withdraw a pending proposal.
    require_team_owner(identity, target.from_team)
    keep = [t for t in trades if t.trade_id != trade_id]
    path = get_data_dir() / "trades_pending.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "trade_id",
                "from_team",
                "to_team",
                "give_player_ids",
                "receive_player_ids",
                "status",
                "give_pick_ids",
                "receive_pick_ids",
            ],
        )
        writer.writeheader()
        for t in keep:
            writer.writerow(
                {
                    "trade_id": t.trade_id,
                    "from_team": t.from_team,
                    "to_team": t.to_team,
                    "give_player_ids": "|".join(t.give_player_ids),
                    "receive_player_ids": "|".join(t.receive_player_ids),
                    "status": t.status,
                    "give_pick_ids": ",".join(t.give_pick_ids or []),
                    "receive_pick_ids": ",".join(t.receive_pick_ids or []),
                }
            )
    return {"trade_id": trade_id, "withdrawn": True}
