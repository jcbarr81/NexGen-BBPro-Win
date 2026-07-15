"""UI-independent trade commit shared by the trades router and CPU-CPU lane.

Extracted verbatim (S2-10) from ``api/routers/trades.py::_commit_trade`` so the
CPU→CPU auto-resolve lane can execute deals without importing FastAPI. The two
``HTTPException`` raises become ``ValueError`` (message preserved); the router
keeps a thin wrapper that re-raises them as ``HTTPException(400)``.
"""
from __future__ import annotations

from pathlib import Path

from models.trade import Trade
from services.draft_pick_ledger import format_pick_label, transfer_pick
from services.transaction_log import record_transaction
from utils.roster_loader import load_roster, save_roster

__all__ = ["commit_trade", "announce_trade"]


def _roster_dir(data_dir) -> str | Path:
    if data_dir is None:
        return "data/rosters"
    return Path(data_dir) / "rosters"


def commit_trade(trade: Trade, *, data_dir=None) -> None:
    """Apply a trade's roster + pick swap and log the transactions.

    Verbatim logic of the former ``api/routers/trades.py::_commit_trade`` with
    ``HTTPException`` replaced by ``ValueError``. Roster moves are ACT<->ACT.
    Raises ``ValueError`` on pick-ownership failure.
    """

    roster_dir = _roster_dir(data_dir)
    from_roster = load_roster(trade.from_team, roster_dir=roster_dir)
    to_roster = load_roster(trade.to_team, roster_dir=roster_dir)

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
        transfer_pick(pick_id, trade.from_team, trade.to_team)
    for pick_id in trade.receive_pick_ids or []:
        transfer_pick(pick_id, trade.to_team, trade.from_team)

    save_roster(trade.from_team, from_roster, roster_dir=roster_dir)
    save_roster(trade.to_team, to_roster, roster_dir=roster_dir)

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


def _names(ids, players_by_id) -> str:
    labels = []
    for pid in ids or []:
        player = (players_by_id or {}).get(pid)
        first = str(getattr(player, "first_name", "") or "")
        last = str(getattr(player, "last_name", "") or "")
        name = f"{first} {last}".strip()
        labels.append(name or str(pid))
    return ", ".join(labels) if labels else "nothing"


def announce_trade(trade: Trade, *, players_by_id=None, data_dir=None) -> None:
    """Emit a news-feed line so users SEE the deal. Best-effort."""

    try:
        from utils.news_logger import log_news_event

        give_names = _names(trade.give_player_ids, players_by_id)
        recv_names = _names(trade.receive_player_ids, players_by_id)
        message = (
            f"TRADE: {trade.from_team} send {give_names} to "
            f"{trade.to_team} for {recv_names}."
        )
        if (getattr(trade, "give_pick_ids", None) or getattr(trade, "receive_pick_ids", None)):
            message += " Picks included."
        file_path = (Path(data_dir) / "news_feed.txt") if data_dir else None
        log_news_event(
            message,
            category="trade",
            team_id=trade.from_team,
            file_path=file_path,
        )
    except Exception:
        pass
