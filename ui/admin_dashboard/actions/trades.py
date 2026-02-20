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

from services.contracts_service import transfer_contracts
from services.draft_pick_ledger import format_pick_label, transfer_pick
from services.payroll_policy import (
    evaluate_trade_payroll_impact,
    format_payroll_policy_message,
    record_payroll_policy_result,
)
from services.trade_settings import load_trade_settings
from services.transaction_log import record_transaction
from ui.window_utils import show_on_top
from utils.news_logger import log_news_event
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.trade_utils import load_trades, save_trade

from ..context import DashboardContext


def _safe_pick_label(pick_id: str) -> str:
    try:
        return format_pick_label(pick_id)
    except Exception:
        return str(pick_id)


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

    layout = QVBoxLayout()

    trade_list = QListWidget()
    trade_map = {}

    for trade in trades:
        if trade.status not in {"pending", "owner_accepted"}:
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
        give_assets = list(give_names)
        recv_assets = list(recv_names)
        give_assets.extend(
            _safe_pick_label(pick_id)
            for pick_id in (getattr(trade, "give_pick_ids", []) or [])
        )
        recv_assets.extend(
            _safe_pick_label(pick_id)
            for pick_id in (getattr(trade, "receive_pick_ids", []) or [])
        )
        summary = (
            f"{trade.trade_id} [{trade.status}]: {trade.from_team} -> {trade.to_team} | "
            f"Give: {', '.join(give_assets)} | Get: {', '.join(recv_assets)}"
        )
        trade_list.addItem(summary)
        trade_map[summary] = trade

    payroll_preview = QLabel("Payroll policy preview: select a trade.")
    payroll_preview.setWordWrap(True)

    def update_payroll_preview() -> None:
        selected = trade_list.currentItem()
        if not selected:
            payroll_preview.setText("Payroll policy preview: select a trade.")
            payroll_preview.setStyleSheet("")
            return
        trade = trade_map.get(selected.text())
        if trade is None:
            payroll_preview.setText("Payroll policy preview: unable to evaluate selected trade.")
            payroll_preview.setStyleSheet("")
            return
        result = evaluate_trade_payroll_impact(trade, players_by_id=players)
        if not result.violations:
            payroll_preview.setText("Payroll policy preview: no payroll rule issues detected.")
            payroll_preview.setStyleSheet("color: #2fa36b;")
            return
        summary = format_payroll_policy_message(result).replace("\n", " ")
        if result.allowed and result.warning:
            payroll_preview.setText(f"Payroll policy preview (warning): {summary}")
            payroll_preview.setStyleSheet("color: #d4a76a;")
            return
        payroll_preview.setText(f"Payroll policy preview (blocked): {summary}")
        payroll_preview.setStyleSheet("color: #d45b5b;")

    trade_list.currentItemChanged.connect(lambda *_args: update_payroll_preview())

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
            settings = load_trade_settings()
            if not settings.trades_enabled:
                QMessageBox.warning(
                    dialog,
                    "Trading Disabled",
                    "Trading is currently disabled by the commissioner.",
                )
                return
            if settings.require_commissioner_approval and trade.status != "owner_accepted":
                QMessageBox.warning(
                    dialog,
                    "Owner Acceptance Required",
                    "This trade must be accepted by the receiving owner before commissioner approval.",
                )
                return
            policy = evaluate_trade_payroll_impact(
                trade,
                players_by_id=players,
            )
            if not policy.allowed:
                record_payroll_policy_result(
                    policy,
                    action="admin_trade_approve",
                    data_dir=get_data_dir(),
                )
                QMessageBox.warning(
                    dialog,
                    "Payroll Policy Blocked",
                    format_payroll_policy_message(policy),
                )
                return
            if policy.warning:
                record_payroll_policy_result(
                    policy,
                    action="admin_trade_approve",
                    data_dir=get_data_dir(),
                )
                proceed = QMessageBox.question(
                    dialog,
                    "Payroll Policy Warning",
                    format_payroll_policy_message(policy) + "\n\nApprove this trade anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return
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
            try:
                for pick_id in getattr(trade, "give_pick_ids", []) or []:
                    transfer_pick(pick_id, trade.from_team, trade.to_team)
                for pick_id in getattr(trade, "receive_pick_ids", []) or []:
                    transfer_pick(pick_id, trade.to_team, trade.from_team)
            except ValueError as exc:
                QMessageBox.warning(dialog, "Trade Failed", str(exc))
                return

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
            try:
                transfer_contracts(
                    trade.give_player_ids,
                    trade.to_team,
                    players_by_id=players,
                )
                transfer_contracts(
                    trade.receive_player_ids,
                    trade.from_team,
                    players_by_id=players,
                )
            except Exception:
                pass

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
                for pick_id in getattr(trade, "give_pick_ids", []) or []:
                    pick_label = _safe_pick_label(pick_id)
                    record_transaction(
                        action="trade_out",
                        team_id=trade.from_team,
                        player_id=pick_id,
                        player_name=pick_label,
                        from_level="PICK",
                        to_level="PICK",
                        counterparty=trade.to_team,
                        details=(
                            f"Trade {trade.trade_id} sent draft pick "
                            f"{pick_label} to {trade.to_team}"
                        ),
                    )
                    record_transaction(
                        action="trade_in",
                        team_id=trade.to_team,
                        player_id=pick_id,
                        player_name=pick_label,
                        from_level="PICK",
                        to_level="PICK",
                        counterparty=trade.from_team,
                        details=(
                            f"Trade {trade.trade_id} acquired draft pick "
                            f"{pick_label} from {trade.from_team}"
                        ),
                    )
                for pick_id in getattr(trade, "receive_pick_ids", []) or []:
                    pick_label = _safe_pick_label(pick_id)
                    record_transaction(
                        action="trade_out",
                        team_id=trade.to_team,
                        player_id=pick_id,
                        player_name=pick_label,
                        from_level="PICK",
                        to_level="PICK",
                        counterparty=trade.from_team,
                        details=(
                            f"Trade {trade.trade_id} sent draft pick "
                            f"{pick_label} to {trade.from_team}"
                        ),
                    )
                    record_transaction(
                        action="trade_in",
                        team_id=trade.from_team,
                        player_id=pick_id,
                        player_name=pick_label,
                        from_level="PICK",
                        to_level="PICK",
                        counterparty=trade.to_team,
                        details=(
                            f"Trade {trade.trade_id} acquired draft pick "
                            f"{pick_label} from {trade.to_team}"
                        ),
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
    layout.addWidget(payroll_preview)
    layout.addLayout(btn_layout)
    dialog.setLayout(layout)
    update_payroll_preview()
    show_on_top(dialog)


__all__ = ["review_pending_trades"]
