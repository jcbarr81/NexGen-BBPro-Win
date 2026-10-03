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
from utils.roster_loader import claim_players, load_roster, save_roster

__all__ = ["commit_trade", "announce_trade"]


def _roster_dir(data_dir) -> str | Path:
    if data_dir is None:
        return "data/rosters"
    return Path(data_dir) / "rosters"


_LEVELS = ("act", "aaa", "low", "dl", "ir")


def _take(roster, pid: str) -> str | None:
    """Remove ``pid`` from every level of ``roster``; return the level he left.

    A traded player can be on any level -- the trade screen offers AAA, Low-A
    and injured players too. Removing him only from ACT left a minor leaguer
    on BOTH teams: a draft pick then reverted to his old team on the next
    roster reload (the placeholder pool keeps the first owner), and anyone
    else stayed listed by two clubs.
    """

    left = None
    for level in _LEVELS:
        group = getattr(roster, level, None)
        if group and pid in group:
            group[:] = [other for other in group if other != pid]
            left = left or level
    tiers = getattr(roster, "dl_tiers", None)
    if tiers:
        tiers.pop(pid, None)
    return left


def _move(pid: str, source, dest) -> str:
    """Move ``pid`` from ``source`` to ``dest``'s active roster.

    Arrivals land on ACT, as ``validate_trade`` assumes when it checks the
    post-trade roster; the new owner places him from there. Returns the level
    he came from, for the transaction log.
    """

    left = _take(source, pid)
    _take(dest, pid)
    dest.act.append(pid)
    return (left or "act").upper()


def commit_trade(trade: Trade, *, data_dir=None) -> None:
    """Apply a trade's roster + pick swap and log the transactions.

    Former ``api/routers/trades.py::_commit_trade`` with ``HTTPException``
    replaced by ``ValueError``. Traded players leave whatever level they were
    on and arrive on ACT. Raises ``ValueError`` on pick-ownership failure.
    """

    roster_dir = _roster_dir(data_dir)

    # Transfer draft picks first (raises ValueError on bad ownership). The
    # rosters below are the roster cache's own objects: editing them before a
    # failure here would leave a half-applied trade for the next save to write.
    for pick_id in trade.give_pick_ids or []:
        transfer_pick(pick_id, trade.from_team, trade.to_team)
    for pick_id in trade.receive_pick_ids or []:
        transfer_pick(pick_id, trade.to_team, trade.from_team)

    from_roster = load_roster(trade.from_team, roster_dir=roster_dir)
    to_roster = load_roster(trade.to_team, roster_dir=roster_dir)

    came_from: dict[str, str] = {}
    for pid in trade.give_player_ids:
        came_from[pid] = _move(pid, from_roster, to_roster)
    for pid in trade.receive_player_ids:
        came_from[pid] = _move(pid, to_roster, from_roster)

    save_roster(trade.from_team, from_roster, roster_dir=roster_dir)
    save_roster(trade.to_team, to_roster, roster_dir=roster_dir)
    claim_players(trade.to_team, trade.give_player_ids)
    claim_players(trade.from_team, trade.receive_player_ids)

    # Best-effort transaction log entries.
    for pid in trade.give_player_ids:
        try:
            record_transaction(
                action="trade_out",
                team_id=trade.from_team,
                player_id=pid,
                from_level=came_from.get(pid, "ACT"),
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
                from_level=came_from.get(pid, "ACT"),
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
