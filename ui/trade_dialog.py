from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models.trade import Trade
from services.draft_pick_ledger import (
    format_pick_label,
    list_team_tradable_picks,
    transfer_pick,
)
from services.trade_settings import load_trade_settings
from services.transaction_log import record_transaction
from services.unified_data_service import get_unified_data_service
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster
from utils.team_loader import load_teams
from utils.trade_utils import get_pending_trades, save_trade

import uuid


def _safe_pick_label(pick_id: str) -> str:
    try:
        return format_pick_label(pick_id)
    except Exception:
        return str(pick_id)


class TradeDialog(QDialog):
    """Dialog allowing an owner to propose and respond to trades."""

    def __init__(self, team_id: str, parent=None):
        super().__init__(parent)
        self.team_id = team_id
        self.trade_settings = load_trade_settings()
        self.players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        self._service = get_unified_data_service()
        self._event_unsubscribes: List[Callable[[], None]] = []
        self._pending_refresh = False
        self._pending_toast_reason: Optional[str] = None

        self.setWindowTitle("Trade Center")
        self.resize(600, 400)

        tabs = QTabWidget()
        tabs.addTab(self._build_new_trade_tab(), "New Trade")
        tabs.addTab(self._build_incoming_tab(), "Incoming")

        layout = QVBoxLayout()
        if not self.trade_settings.trades_enabled:
            banner = QLabel(
                "Trading is currently disabled by the commissioner. "
                "You can still review pending offers."
            )
            banner.setWordWrap(True)
            layout.addWidget(banner)
        layout.addWidget(tabs)
        self.setLayout(layout)
        self._register_event_listeners()

    # --- New trade tab -------------------------------------------------
    def _build_new_trade_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Trade with:"))
        self.team_dropdown = QComboBox()
        teams = [t.team_id for t in load_teams() if t.team_id != self.team_id]
        self.team_dropdown.addItems(teams)
        self.team_dropdown.currentTextChanged.connect(self._refresh_receive_list)
        layout.addWidget(self.team_dropdown)

        layout.addWidget(QLabel("Players to Give"))
        self.give_list = QListWidget()
        self.give_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        roster = load_roster(self.team_id)
        for pid in roster.act:
            self.give_list.addItem(self._make_player_item(pid))
        layout.addWidget(self.give_list)

        layout.addWidget(QLabel("Players to Receive"))
        self.receive_list = QListWidget()
        self.receive_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.receive_list)
        self._refresh_receive_list(self.team_dropdown.currentText())

        self.picks_disabled_label = QLabel(
            "Draft pick trading is disabled by the commissioner."
        )
        self.picks_disabled_label.setWordWrap(True)
        self.picks_disabled_label.setVisible(
            not self.trade_settings.draft_pick_trading_enabled
        )
        layout.addWidget(self.picks_disabled_label)

        layout.addWidget(QLabel("Draft Picks to Give"))
        self.give_pick_list = QListWidget()
        self.give_pick_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.give_pick_list.setEnabled(self.trade_settings.draft_pick_trading_enabled)
        layout.addWidget(self.give_pick_list)

        layout.addWidget(QLabel("Draft Picks to Receive"))
        self.receive_pick_list = QListWidget()
        self.receive_pick_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.receive_pick_list.setEnabled(self.trade_settings.draft_pick_trading_enabled)
        layout.addWidget(self.receive_pick_list)
        self._refresh_pick_lists(self.team_dropdown.currentText())

        submit_btn = QPushButton("Submit Trade")
        submit_btn.clicked.connect(self._submit_trade)
        submit_btn.setEnabled(self.trade_settings.trades_enabled)
        layout.addWidget(submit_btn)

        return widget

    def _register_event_listeners(self) -> None:
        bus = getattr(self._service, "events", None)
        if bus is None:
            return

        def _on_roster(_payload: Optional[dict] = None) -> None:
            self._queue_refresh("Roster changes detected; trade center refreshed.")

        def _on_players(_payload: Optional[dict] = None) -> None:
            self._queue_refresh("Player data updated; trade center refreshed.")

        for topic, handler in (
            ("rosters.updated", _on_roster),
            ("rosters.invalidated", _on_roster),
            ("players.updated", _on_players),
            ("players.invalidated", _on_players),
        ):
            try:
                self._event_unsubscribes.append(bus.subscribe(topic, handler))
            except Exception:
                pass

    def _queue_refresh(self, reason: str) -> None:
        def _execute() -> None:
            if not self._is_visible():
                self._pending_refresh = True
                self._pending_toast_reason = reason
                return
            self._pending_refresh = False
            self._pending_toast_reason = None
            self._refresh_sources()
            self._maybe_toast("info", reason)

        QTimer.singleShot(0, _execute)

    def _refresh_sources(self) -> None:
        self.players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        give_selected = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.give_list.selectedItems()
        }
        receive_selected = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.receive_list.selectedItems()
        }
        give_pick_selected = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.give_pick_list.selectedItems()
        }
        receive_pick_selected = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.receive_pick_list.selectedItems()
        }
        current_team = self.team_dropdown.currentText()
        team_ids = [t.team_id for t in load_teams() if t.team_id != self.team_id]
        try:
            self.team_dropdown.blockSignals(True)
        except Exception:
            pass
        try:
            self.team_dropdown.clear()
            self.team_dropdown.addItems(team_ids)
        except Exception:
            pass
        if current_team not in team_ids and team_ids:
            current_team = team_ids[0]
        if team_ids:
            try:
                idx = self.team_dropdown.findText(current_team)  # type: ignore[attr-defined]
            except Exception:
                idx = team_ids.index(current_team) if current_team in team_ids else 0
            try:
                self.team_dropdown.setCurrentIndex(max(idx, 0))
            except Exception:
                pass
        try:
            self.team_dropdown.blockSignals(False)
        except Exception:
            pass

        roster = load_roster(self.team_id)
        self.give_list.clear()
        for pid in roster.act:
            self.give_list.addItem(self._make_player_item(pid))
        for i in range(self.give_list.count()):
            item = self.give_list.item(i)
            try:
                pid = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                pid = None
            if pid in give_selected:
                try:
                    item.setSelected(True)
                except Exception:
                    pass

        self._refresh_receive_list(current_team)
        for i in range(self.receive_list.count()):
            item = self.receive_list.item(i)
            try:
                pid = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                pid = None
            if pid in receive_selected:
                try:
                    item.setSelected(True)
                except Exception:
                    pass

        self._refresh_pick_lists(current_team)
        for i in range(self.give_pick_list.count()):
            item = self.give_pick_list.item(i)
            try:
                pick_id = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                pick_id = None
            if pick_id in give_pick_selected:
                try:
                    item.setSelected(True)
                except Exception:
                    pass
        for i in range(self.receive_pick_list.count()):
            item = self.receive_pick_list.item(i)
            try:
                pick_id = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                pick_id = None
            if pick_id in receive_pick_selected:
                try:
                    item.setSelected(True)
                except Exception:
                    pass

        self._load_incoming_trades()

    def _maybe_toast(self, kind: str, message: str) -> None:
        callback = self._toast_callback()
        if callable(callback):
            try:
                callback(kind, message)
            except Exception:
                pass

    def _toast_callback(self) -> Optional[Callable[[str, str], None]]:
        parent = self.parent()
        if parent is None:
            return None
        for attr in ("_show_toast", "show_toast"):
            candidate = getattr(parent, attr, None)
            if callable(candidate):
                return candidate
        return None

    def _is_visible(self) -> bool:
        try:
            return bool(self.isVisible())
        except Exception:
            return True

    def showEvent(self, event):  # pragma: no cover - UI callback
        try:
            super().showEvent(event)
        except Exception:
            pass
        if self._pending_refresh:
            self._pending_refresh = False
            self._refresh_sources()
            if self._pending_toast_reason:
                self._maybe_toast("info", self._pending_toast_reason)
                self._pending_toast_reason = None

    def closeEvent(self, event):  # pragma: no cover - UI callback
        for unsubscribe in self._event_unsubscribes:
            try:
                unsubscribe()
            except Exception:
                pass
        self._event_unsubscribes.clear()
        try:
            super().closeEvent(event)
        except Exception:
            pass

    def _make_player_item(self, pid: str) -> QListWidgetItem:
        p = self.players.get(pid)
        label = f"{p.first_name} {p.last_name} ({pid})" if p else pid
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, pid)
        return item

    def _refresh_receive_list(self, team_id: str):
        self.receive_list.clear()
        if not team_id:
            return
        roster = load_roster(team_id)
        for pid in roster.act:
            self.receive_list.addItem(self._make_player_item(pid))

    def _refresh_pick_lists(self, team_id: str) -> None:
        self.give_pick_list.clear()
        self.receive_pick_list.clear()
        if not self.trade_settings.draft_pick_trading_enabled:
            return

        for pick in list_team_tradable_picks(self.team_id):
            item = QListWidgetItem(format_pick_label(pick.pick_id))
            item.setData(Qt.ItemDataRole.UserRole, pick.pick_id)
            self.give_pick_list.addItem(item)

        if not team_id:
            return
        for pick in list_team_tradable_picks(team_id):
            item = QListWidgetItem(format_pick_label(pick.pick_id))
            item.setData(Qt.ItemDataRole.UserRole, pick.pick_id)
            self.receive_pick_list.addItem(item)

    def _submit_trade(self):
        if not self.trade_settings.trades_enabled:
            QMessageBox.warning(
                self,
                "Trading Disabled",
                "Trading is currently disabled by the commissioner.",
            )
            return
        to_team = self.team_dropdown.currentText()
        give_items = self.give_list.selectedItems()
        recv_items = self.receive_list.selectedItems()
        give_pick_items = self.give_pick_list.selectedItems()
        recv_pick_items = self.receive_pick_list.selectedItems()

        give_ids = [i.data(Qt.ItemDataRole.UserRole) for i in give_items]
        recv_ids = [i.data(Qt.ItemDataRole.UserRole) for i in recv_items]
        give_pick_ids = [i.data(Qt.ItemDataRole.UserRole) for i in give_pick_items]
        recv_pick_ids = [i.data(Qt.ItemDataRole.UserRole) for i in recv_pick_items]

        if not to_team:
            QMessageBox.warning(self, "Incomplete", "Select a trade partner.")
            return
        if (not give_ids and not give_pick_ids) or (not recv_ids and not recv_pick_ids):
            QMessageBox.warning(
                self,
                "Incomplete",
                "Each side must include at least one player or draft pick.",
            )
            return
        trade = Trade(
            trade_id=uuid.uuid4().hex[:8],
            from_team=self.team_id,
            to_team=to_team,
            give_player_ids=give_ids,
            receive_player_ids=recv_ids,
            give_pick_ids=give_pick_ids,
            receive_pick_ids=recv_pick_ids,
        )
        try:
            save_trade(trade)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Trade Not Allowed", str(exc))
            return
        QMessageBox.information(self, "Trade Sent", f"Trade proposal sent to {to_team}.")
        self.give_list.clearSelection()
        self.receive_list.clearSelection()
        self.give_pick_list.clearSelection()
        self.receive_pick_list.clearSelection()

    # --- Incoming trades tab -------------------------------------------
    def _build_incoming_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.incoming_list = QListWidget()
        layout.addWidget(self.incoming_list)

        btn_row = QHBoxLayout()
        accept_btn = QPushButton("Accept")
        reject_btn = QPushButton("Reject")
        accept_btn.clicked.connect(lambda: self._respond_to_trade(True))
        reject_btn.clicked.connect(lambda: self._respond_to_trade(False))
        btn_row.addWidget(accept_btn)
        btn_row.addWidget(reject_btn)
        layout.addLayout(btn_row)

        self._load_incoming_trades()
        return widget

    def _load_incoming_trades(self):
        self.trade_map: Dict[str, Trade] = {}
        self.incoming_list.clear()
        for t in get_pending_trades(self.team_id):
            give_names = [self.players.get(pid).last_name for pid in t.give_player_ids if pid in self.players]
            recv_names = [self.players.get(pid).last_name for pid in t.receive_player_ids if pid in self.players]
            give_assets = list(give_names)
            recv_assets = list(recv_names)
            give_assets.extend(
                _safe_pick_label(pick_id)
                for pick_id in (getattr(t, "give_pick_ids", []) or [])
            )
            recv_assets.extend(
                _safe_pick_label(pick_id)
                for pick_id in (getattr(t, "receive_pick_ids", []) or [])
            )
            summary = (
                f"{t.trade_id}: {t.from_team} -> {t.to_team} | "
                f"Give: {', '.join(give_assets)} | Get: {', '.join(recv_assets)}"
            )
            self.incoming_list.addItem(summary)
            self.trade_map[summary] = t

    def _respond_to_trade(self, accept: bool):
        selected = self.incoming_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Select a trade to respond to.")
            return
        settings = load_trade_settings()
        if accept and not settings.trades_enabled:
            QMessageBox.warning(
                self,
                "Trading Disabled",
                "Trading is currently disabled by the commissioner.",
            )
            return

        trade = self.trade_map[selected.text()]
        if accept:
            if settings.require_commissioner_approval:
                trade.status = "owner_accepted"
                try:
                    save_trade(trade)
                except RuntimeError as exc:
                    QMessageBox.warning(self, "Trade Failed", str(exc))
                    return
                QMessageBox.information(
                    self,
                    "Awaiting Commissioner Approval",
                    (
                        f"Trade {trade.trade_id} accepted by owner and queued "
                        "for commissioner approval."
                    ),
                )
                self.incoming_list.takeItem(self.incoming_list.currentRow())
                return
            trade.status = "accepted"
            try:
                self._process_trade(trade)
            except RuntimeError as exc:
                QMessageBox.warning(self, "Trade Failed", str(exc))
                return
        else:
            trade.status = "rejected"
        try:
            save_trade(trade)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Trade Failed", str(exc))
            return
        QMessageBox.information(self, "Trade Updated", f"Trade {trade.trade_id} {trade.status}.")
        self.incoming_list.takeItem(self.incoming_list.currentRow())

    def _process_trade(self, trade: Trade):
        from_roster = load_roster(trade.from_team)
        to_roster = load_roster(trade.to_team)
        for pid in trade.give_player_ids:
            for roster in (from_roster, to_roster):
                if pid in roster.act:
                    roster.act.remove(pid)
            to_roster.act.append(pid)
        for pid in trade.receive_player_ids:
            for roster in (from_roster, to_roster):
                if pid in roster.act:
                    roster.act.remove(pid)
            from_roster.act.append(pid)

        try:
            for pick_id in getattr(trade, "give_pick_ids", []) or []:
                transfer_pick(pick_id, trade.from_team, trade.to_team)
            for pick_id in getattr(trade, "receive_pick_ids", []) or []:
                transfer_pick(pick_id, trade.to_team, trade.from_team)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        save_roster(trade.from_team, from_roster)
        save_roster(trade.to_team, to_roster)
        try:
            for pid in trade.give_player_ids:
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
            for pid in trade.receive_player_ids:
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

