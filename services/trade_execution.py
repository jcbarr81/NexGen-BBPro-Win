"""UI-independent trade commit shared by the trades router and CPU-CPU lane.

Extracted verbatim (S2-10) from ``api/routers/trades.py::_commit_trade`` so the
CPU→CPU auto-resolve lane can execute deals without importing FastAPI. The two
``HTTPException`` raises become ``ValueError`` (message preserved); the router
keeps a thin wrapper that re-raises them as ``HTTPException(400)``.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path

from models.trade import Trade
from services.draft_pick_ledger import (
    format_pick_label,
    get_pick_owner,
    parse_pick_id,
    transfer_pick,
)
from services.transaction_log import record_transaction
from utils.roster_loader import check_rosters, claim_players, load_roster, save_rosters

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


def _check_pick_owner(pick_id: str, owner: str) -> None:
    """ValueError unless ``owner`` holds ``pick_id`` now (moves nothing)."""

    year, round_no, original_team = parse_pick_id(pick_id)
    current = str(get_pick_owner(year, round_no, original_team) or original_team)
    if current != str(owner or "").strip():
        raise ValueError(
            f"{format_pick_label(pick_id)} is owned by {current}, not {owner}."
        )


def _transfer_contracts(trade: Trade, data_dir) -> None:
    """Move each traded player's contract to his new club (8.1.1).

    Payroll is summed by the contract's ``team_id``, so a contract left with
    the old club kept charging it for the player. Only existing contracts
    move; a player without one (a minor leaguer, a league without finance)
    gets none. Never fails the trade, which has already been saved.
    """

    from services.contracts_service import transfer_contracts

    for ids, receiver in (
        (trade.give_player_ids, trade.to_team),
        (trade.receive_player_ids, trade.from_team),
    ):
        if not ids:
            continue
        try:
            transfer_contracts(
                list(ids),
                receiver,
                create_if_missing=False,
                data_dir=data_dir,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "trade %s: could not move contracts to %s",
                getattr(trade, "trade_id", "?"),
                receiver,
            )


def commit_trade(trade: Trade, *, data_dir=None) -> None:
    """Apply a trade's roster + pick swap and log the transactions.

    Former ``api/routers/trades.py::_commit_trade`` with ``HTTPException``
    replaced by ``ValueError``. Traded players leave whatever level they were
    on and arrive on ACT. Raises ``ValueError`` on pick-ownership failure.
    """

    roster_dir = _roster_dir(data_dir)

    # All or nothing (8.1.1): build both clubs' rosters after the trade on
    # COPIES (load_roster hands out the cache's own objects), check them --
    # no player may end up on a second club -- and check every pick's owner,
    # all before anything moves. A refused trade used to keep its picks
    # moved: they were transferred before the rosters were checked.
    from_roster = copy.deepcopy(load_roster(trade.from_team, roster_dir=roster_dir))
    to_roster = copy.deepcopy(load_roster(trade.to_team, roster_dir=roster_dir))

    came_from: dict[str, str] = {}
    for pid in trade.give_player_ids:
        came_from[pid] = _move(pid, from_roster, to_roster)
    for pid in trade.receive_player_ids:
        came_from[pid] = _move(pid, to_roster, from_roster)

    pairs = [(trade.from_team, from_roster), (trade.to_team, to_roster)]
    check_rosters(pairs, roster_dir=roster_dir)  # DoubleRosterError (ValueError)
    pick_moves = [
        (pick_id, trade.from_team, trade.to_team) for pick_id in trade.give_pick_ids or []
    ] + [
        (pick_id, trade.to_team, trade.from_team) for pick_id in trade.receive_pick_ids or []
    ]
    for pick_id, owner, _ in pick_moves:
        _check_pick_owner(pick_id, owner)

    moved: list[tuple[str, str, str]] = []
    try:
        for pick_id, owner, receiver in pick_moves:
            transfer_pick(pick_id, owner, receiver)
            moved.append((pick_id, owner, receiver))
        # One checked write for both clubs: each one's new player is still on
        # the other's file until the pair lands (a lone save would be refused
        # as a second club for him).
        save_rosters(pairs, roster_dir=roster_dir)
    except Exception:
        for pick_id, owner, receiver in reversed(moved):
            try:
                transfer_pick(pick_id, receiver, owner)
            except Exception:  # pragma: no cover - best effort
                pass
        raise
    claim_players(trade.to_team, trade.give_player_ids)
    claim_players(trade.from_team, trade.receive_player_ids)
    _transfer_contracts(trade, data_dir)
    # Both directions: every traded player's picture goes to his new club's
    # colors (queued; never fails the trade).
    from services.avatar_recolor import enqueue as _queue_pictures

    _queue_pictures(
        list(trade.give_player_ids or []) + list(trade.receive_player_ids or []),
        f"trade {getattr(trade, 'trade_id', '')}".strip(),
        data_dir=data_dir,
    )

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
