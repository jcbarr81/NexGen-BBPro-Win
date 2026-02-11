"""Trade-related admin dashboard actions."""
from __future__ import annotations

import csv
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.transaction_log import record_transaction
from ui.window_utils import show_on_top
from utils.news_logger import log_news_event
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.team_loader import load_teams
from utils.trade_utils import load_trades, save_trade

from ..context import DashboardContext


def review_pending_trades(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Open a dialog allowing admins to approve or reject trades."""

    dialog = QDialog(parent)
    dialog.setWindowTitle("Review Pending Trades")
    dialog.setMinimumSize(600, 400)

    trades = load_trades()
    players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
    teams = {t.team_id: t for t in load_teams("data/teams.csv")}

    layout = QVBoxLayout()

    trade_list = QListWidget()
    trade_map = {}

    for trade in trades:
        if trade.status != "pending":
            continue
        give_names = [
            f"{pid} ({players[pid].first_name} {players[pid].last_name})"
            for pid in trade.give_player_ids
            if pid in players
        ]
        recv_names = [
            f"{pid} ({players[pid].first_name} {players[pid].last_name})"
            for pid in trade.receive_player_ids
            if pid in players
        ]
        summary = (
            f"{trade.trade_id}: {trade.from_team} -> {trade.to_team} | "
            f"Give: {', '.join(give_names)} | Get: {', '.join(recv_names)}"
        )
        trade_list.addItem(summary)
        trade_map[summary] = trade

    def process_trade(accept: bool = True) -> None:
        selected = trade_list.currentItem()
        if not selected:
            return
        summary = selected.text()
        trade = trade_map[summary]

        outgoing_from: list[tuple[str, str]] = []
        incoming_to: list[tuple[str, str]] = []
        outgoing_to: list[tuple[str, str]] = []
        incoming_from: list[tuple[str, str]] = []

        if accept:
            from_roster = load_roster(trade.from_team)
            to_roster = load_roster(trade.to_team)

            for pid in trade.give_player_ids:
                for level in ("act", "aaa", "low"):
                    roster_list = getattr(from_roster, level)
                    if pid in roster_list:
                        roster_list.remove(pid)
                        getattr(to_roster, level).append(pid)
                        outgoing_from.append((pid, level))
                        incoming_to.append((pid, level))
                        break

            for pid in trade.receive_player_ids:
                for level in ("act", "aaa", "low"):
                    roster_list = getattr(to_roster, level)
                    if pid in roster_list:
                        roster_list.remove(pid)
                        getattr(from_roster, level).append(pid)
                        outgoing_to.append((pid, level))
                        incoming_from.append((pid, level))
                        break

            def save_roster(roster) -> None:
                path = get_data_dir() / "rosters" / f"{roster.team_id}.csv"
                with path.open("w", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=["player_id", "level"])
                    writer.writeheader()
                    for level in ("act", "aaa", "low"):
                        for player_id in getattr(roster, level):
                            writer.writerow({"player_id": player_id, "level": level.upper()})

            save_roster(from_roster)
            save_roster(to_roster)

        trade.status = "accepted" if accept else "rejected"
        save_trade(trade)

        if accept:
            try:
                for pid, level in outgoing_from:
                    record_transaction(
                        action="trade_out",
                        team_id=trade.from_team,
                        player_id=pid,
                        from_level=level.upper(),
                        to_level=level.upper(),
                        counterparty=trade.to_team,
                        details=f"Trade {trade.trade_id} sent to {trade.to_team}",
                    )
                    record_transaction(
                        action="trade_in",
                        team_id=trade.to_team,
                        player_id=pid,
                        from_level=level.upper(),
                        to_level=level.upper(),
                        counterparty=trade.from_team,
                        details=f"Trade {trade.trade_id} acquired from {trade.from_team}",
                    )
                for pid, level in outgoing_to:
                    record_transaction(
                        action="trade_out",
                        team_id=trade.to_team,
                        player_id=pid,
                        from_level=level.upper(),
                        to_level=level.upper(),
                        counterparty=trade.from_team,
                        details=f"Trade {trade.trade_id} sent to {trade.from_team}",
                    )
                    record_transaction(
                        action="trade_in",
                        team_id=trade.from_team,
                        player_id=pid,
                        from_level=level.upper(),
                        to_level=level.upper(),
                        counterparty=trade.to_team,
                        details=f"Trade {trade.trade_id} acquired from {trade.to_team}",
                    )
            except Exception:
                pass

        log_news_event(f"TRADE {'ACCEPTED' if accept else 'REJECTED'}: {summary}")
        QMessageBox.information(
            dialog,
            "Trade Processed",
            f"{summary} marked as {trade.status.upper()}.",
        )
        trade_list.takeItem(trade_list.currentRow())

    btn_layout = QHBoxLayout()
    accept_btn = QPushButton("Accept Trade")
    reject_btn = QPushButton("Reject Trade")
    accept_btn.clicked.connect(lambda: process_trade(True))
    reject_btn.clicked.connect(lambda: process_trade(False))
    btn_layout.addWidget(accept_btn)
    btn_layout.addWidget(reject_btn)

    layout.addWidget(trade_list)
    layout.addLayout(btn_layout)
    dialog.setLayout(layout)
    show_on_top(dialog)


__all__ = ["review_pending_trades"]
