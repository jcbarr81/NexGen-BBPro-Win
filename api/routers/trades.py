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

from fastapi import APIRouter, Body, HTTPException, Query, status

from models.trade import Trade
from services.draft_pick_ledger import format_pick_label, transfer_pick
from services.transaction_log import record_transaction
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster
from utils.trade_utils import load_trades, save_trade

from ..security import CurrentIdentity

router = APIRouter(prefix="/trades", tags=["trades"], dependencies=[CurrentIdentity])


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


@router.get("")
def list_trades(
    team_id: Optional[str] = Query(default=None, description="Involving this team (give or receive)"),
    status: Optional[str] = Query(default=None, description="Filter by status (pending, accepted, rejected, ...)"),
) -> Dict[str, Any]:
    trades = load_trades()

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
    """Apply a trade's roster + pick swap and log the transactions.

    Mirrors the core of ``ui/trade_dialog._process_trade`` but skips the
    optional contract-transfer + auto-reassign steps (those are best-effort
    and depend on UI-resident state). Engine-required state (rosters, picks,
    transaction log) is fully consistent on success.
    """

    from_roster = load_roster(trade.from_team)
    to_roster = load_roster(trade.to_team)

    # Move "give" players from from_team's act roster onto to_team's act roster.
    for pid in trade.give_player_ids:
        if pid in from_roster.act:
            from_roster.act.remove(pid)
        if pid in to_roster.act:
            to_roster.act.remove(pid)
        to_roster.act.append(pid)

    # Move "receive" players the other direction.
    for pid in trade.receive_player_ids:
        if pid in to_roster.act:
            to_roster.act.remove(pid)
        if pid in from_roster.act:
            from_roster.act.remove(pid)
        from_roster.act.append(pid)

    # Transfer draft picks (raises ValueError on bad ownership).
    for pick_id in trade.give_pick_ids or []:
        try:
            transfer_pick(pick_id, trade.from_team, trade.to_team)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
    for pick_id in trade.receive_pick_ids or []:
        try:
            transfer_pick(pick_id, trade.to_team, trade.from_team)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    save_roster(trade.from_team, from_roster)
    save_roster(trade.to_team, to_roster)

    # Best-effort transaction log entries.
    for pid in trade.give_player_ids:
        try:
            record_transaction(
                action="trade_out",
                team_id=trade.from_team,
                player_id=pid,
                from_level="ACT",
                to_level="ACT",
                counterparty=trade.to_team,
                details=f"Trade {trade.trade_id} sent to {trade.to_team}",
            )
            record_transaction(
                action="trade_in",
                team_id=trade.to_team,
                player_id=pid,
                from_level="ACT",
                to_level="ACT",
                counterparty=trade.from_team,
                details=f"Trade {trade.trade_id} acquired from {trade.from_team}",
            )
        except Exception:
            pass
    for pid in trade.receive_player_ids:
        try:
            record_transaction(
                action="trade_out",
                team_id=trade.to_team,
                player_id=pid,
                from_level="ACT",
                to_level="ACT",
                counterparty=trade.from_team,
                details=f"Trade {trade.trade_id} sent to {trade.from_team}",
            )
            record_transaction(
                action="trade_in",
                team_id=trade.from_team,
                player_id=pid,
                from_level="ACT",
                to_level="ACT",
                counterparty=trade.to_team,
                details=f"Trade {trade.trade_id} acquired from {trade.to_team}",
            )
        except Exception:
            pass
    for pick_id in trade.give_pick_ids or []:
        try:
            record_transaction(
                action="trade_out",
                team_id=trade.from_team,
                player_id=pick_id,
                player_name=format_pick_label(pick_id),
                from_level="PICK",
                to_level="PICK",
                counterparty=trade.to_team,
                details=f"Trade {trade.trade_id} sent pick to {trade.to_team}",
            )
        except Exception:
            pass
    for pick_id in trade.receive_pick_ids or []:
        try:
            record_transaction(
                action="trade_in",
                team_id=trade.from_team,
                player_id=pick_id,
                player_name=format_pick_label(pick_id),
                from_level="PICK",
                to_level="PICK",
                counterparty=trade.to_team,
                details=f"Trade {trade.trade_id} acquired pick from {trade.to_team}",
            )
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
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def propose_trade(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    trade = _trade_payload_to_dict(payload)
    try:
        save_trade(trade)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {
        "trade_id": trade.trade_id,
        "from_team": trade.from_team,
        "to_team": trade.to_team,
        "status": trade.status,
    }


@router.post("/{trade_id}/accept")
def accept_trade(trade_id: str) -> Dict[str, Any]:
    trade = _find_trade(trade_id)
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


@router.post("/{trade_id}/reject")
def reject_trade(trade_id: str) -> Dict[str, Any]:
    trade = _find_trade(trade_id)
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
def withdraw_trade(trade_id: str) -> Dict[str, Any]:
    """Withdraw a pending trade by writing the file without it."""

    trades = load_trades()
    if not any(t.trade_id == trade_id for t in trades):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trade {trade_id} not found.",
        )
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
