from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
try:
    from PyQt6.QtGui import QGuiApplication
except ImportError:  # pragma: no cover - lightweight test stubs
    QGuiApplication = None  # type: ignore[assignment]
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from models.trade import Trade
from services.contracts_service import transfer_contracts
from services.draft_pick_ledger import (
    format_pick_label,
    list_team_tradable_picks,
    transfer_pick,
)
from services.payroll_policy import (
    evaluate_trade_payroll_impact,
    format_payroll_policy_message,
    record_payroll_policy_result,
)
from services.trade_settings import load_trade_settings
from services.transaction_log import record_transaction
from services.unified_data_service import get_unified_data_service
from utils.player_loader import load_players_from_csv
from utils.path_utils import get_data_dir
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
        self.setMinimumSize(760, 540)
        width, height = self._initial_window_size()
        self.resize(width, height)

        tabs = QTabWidget()
        tabs.addTab(self._wrap_scrollable_tab(self._build_new_trade_tab()), "New Trade")
        tabs.addTab(self._wrap_scrollable_tab(self._build_incoming_tab()), "Incoming")

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

    def _initial_window_size(self) -> tuple[int, int]:
        width = 920
        height = 660
        try:
            screen = (
                QGuiApplication.primaryScreen()
                if QGuiApplication is not None
                else None
            )
            if screen is not None:
                rect = screen.availableGeometry()
                max_width = max(760, int(rect.width() * 0.85))
                max_height = max(540, int(rect.height() * 0.85))
                width = min(width, max_width)
                height = min(height, max_height)
        except Exception:
            pass
        return width, height

    def _wrap_scrollable_tab(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    # --- New trade tab -------------------------------------------------
    def _build_new_trade_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        partner_row = QHBoxLayout()
        partner_row.setSpacing(8)
        partner_row.addWidget(QLabel("Trade with:"))
        self.team_dropdown = QComboBox()
        teams = [t.team_id for t in load_teams() if t.team_id != self.team_id]
        self.team_dropdown.addItems(teams)
        self.team_dropdown.currentTextChanged.connect(self._refresh_receive_list)
        self.team_dropdown.currentTextChanged.connect(
            lambda _value: self._update_offer_summary()
        )
        self.team_dropdown.currentTextChanged.connect(
            lambda _value: self._update_new_trade_policy_preview()
        )
        partner_row.addWidget(self.team_dropdown, 1)
        layout.addLayout(partner_row)

        self.picks_disabled_label = QLabel(
            "Draft pick trading is disabled by the commissioner."
        )
        self.picks_disabled_label.setWordWrap(True)
        self.picks_disabled_label.setVisible(
            not self.trade_settings.draft_pick_trading_enabled
        )
        layout.addWidget(self.picks_disabled_label)

        assets_row = QHBoxLayout()
        assets_row.setSpacing(14)

        give_panel = QWidget()
        give_layout = QVBoxLayout(give_panel)
        give_layout.setContentsMargins(0, 0, 0, 0)
        give_layout.setSpacing(8)
        give_heading = QLabel("You Send")
        give_heading.setStyleSheet("font-weight: 700;")
        give_layout.addWidget(give_heading)
        give_layout.addWidget(QLabel("Players"))
        self.give_list = QListWidget()
        self.give_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.give_list.setMinimumHeight(170)
        self.give_list.itemSelectionChanged.connect(self._update_new_trade_policy_preview)
        self.give_list.itemSelectionChanged.connect(self._update_offer_summary)
        roster = load_roster(self.team_id)
        for pid in roster.act:
            self.give_list.addItem(self._make_player_item(pid))
        give_layout.addWidget(self.give_list, 1)

        give_layout.addWidget(QLabel("Draft Picks"))
        self.give_pick_list = QListWidget()
        self.give_pick_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.give_pick_list.setEnabled(self.trade_settings.draft_pick_trading_enabled)
        self.give_pick_list.setMinimumHeight(120)
        self.give_pick_list.itemSelectionChanged.connect(self._update_offer_summary)
        give_layout.addWidget(self.give_pick_list, 1)

        receive_panel = QWidget()
        receive_layout = QVBoxLayout(receive_panel)
        receive_layout.setContentsMargins(0, 0, 0, 0)
        receive_layout.setSpacing(8)
        receive_heading = QLabel("You Receive")
        receive_heading.setStyleSheet("font-weight: 700;")
        receive_layout.addWidget(receive_heading)
        receive_layout.addWidget(QLabel("Players"))
        self.receive_list = QListWidget()
        self.receive_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.receive_list.setMinimumHeight(170)
        self.receive_list.itemSelectionChanged.connect(self._update_new_trade_policy_preview)
        self.receive_list.itemSelectionChanged.connect(self._update_offer_summary)
        receive_layout.addWidget(self.receive_list, 1)

        receive_layout.addWidget(QLabel("Draft Picks"))
        self.receive_pick_list = QListWidget()
        self.receive_pick_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.receive_pick_list.setEnabled(self.trade_settings.draft_pick_trading_enabled)
        self.receive_pick_list.setMinimumHeight(120)
        self.receive_pick_list.itemSelectionChanged.connect(self._update_offer_summary)
        receive_layout.addWidget(self.receive_pick_list, 1)

        assets_row.addWidget(give_panel, 1)
        assets_row.addWidget(receive_panel, 1)
        layout.addLayout(assets_row)

        self._refresh_receive_list(self.team_dropdown.currentText())
        self._refresh_pick_lists(self.team_dropdown.currentText())

        self.selection_summary_label = QLabel("Offer summary: no assets selected yet.")
        self.selection_summary_label.setWordWrap(True)
        layout.addWidget(self.selection_summary_label)

        self.new_trade_policy_label = QLabel(
            "Validation & payroll preview: select trade assets."
        )
        self.new_trade_policy_label.setWordWrap(True)
        layout.addWidget(self.new_trade_policy_label)
        self._update_offer_summary()
        self._update_new_trade_policy_preview()

        submit_btn = QPushButton("Submit Trade")
        submit_btn.clicked.connect(self._submit_trade)
        submit_btn.setEnabled(self.trade_settings.trades_enabled)
        layout.addWidget(submit_btn)
        layout.addStretch(1)

        return widget

    def _update_offer_summary(self) -> None:
        label = getattr(self, "selection_summary_label", None)
        if label is None:
            return
        partner = self.team_dropdown.currentText() if hasattr(self, "team_dropdown") else ""
        give_players = len(self.give_list.selectedItems()) if hasattr(self, "give_list") else 0
        give_picks = (
            len(self.give_pick_list.selectedItems())
            if hasattr(self, "give_pick_list")
            else 0
        )
        recv_players = (
            len(self.receive_list.selectedItems()) if hasattr(self, "receive_list") else 0
        )
        recv_picks = (
            len(self.receive_pick_list.selectedItems())
            if hasattr(self, "receive_pick_list")
            else 0
        )
        if not partner:
            label.setText("Offer summary: choose a trade partner.")
            return
        label.setText(
            "Offer summary: "
            f"send {give_players} player(s), {give_picks} pick(s) | "
            f"receive {recv_players} player(s), {recv_picks} pick(s) "
            f"with {partner}."
        )

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
            self._update_new_trade_policy_preview()
            return
        roster = load_roster(team_id)
        for pid in roster.act:
            self.receive_list.addItem(self._make_player_item(pid))
        self._update_new_trade_policy_preview()

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

    def _build_trade_from_current_selection(self) -> Trade | None:
        to_team = self.team_dropdown.currentText()
        if not to_team:
            return None
        give_ids = [i.data(Qt.ItemDataRole.UserRole) for i in self.give_list.selectedItems()]
        recv_ids = [i.data(Qt.ItemDataRole.UserRole) for i in self.receive_list.selectedItems()]
        give_pick_ids = [i.data(Qt.ItemDataRole.UserRole) for i in self.give_pick_list.selectedItems()]
        recv_pick_ids = [i.data(Qt.ItemDataRole.UserRole) for i in self.receive_pick_list.selectedItems()]
        return Trade(
            trade_id="preview",
            from_team=self.team_id,
            to_team=to_team,
            give_player_ids=give_ids,
            receive_player_ids=recv_ids,
            give_pick_ids=give_pick_ids,
            receive_pick_ids=recv_pick_ids,
        )

    def _update_new_trade_policy_preview(self) -> None:
        label = getattr(self, "new_trade_policy_label", None)
        if label is None:
            return
        trade = self._build_trade_from_current_selection()
        if trade is None:
            label.setText("Payroll policy preview: select a trade partner.")
            label.setStyleSheet("")
            return
        if not trade.give_player_ids and not trade.receive_player_ids:
            label.setText("Payroll policy preview: select players to evaluate payroll impact.")
            label.setStyleSheet("")
            return
        result = evaluate_trade_payroll_impact(
            trade,
            players_by_id=self.players,
        )
        if not result.violations:
            label.setText("Payroll policy preview: no payroll rule issues detected.")
            label.setStyleSheet("color: #2fa36b;")
            return
        summary = format_payroll_policy_message(result).replace("\n", " ")
        if result.allowed and result.warning:
            label.setText(f"Payroll policy preview (warning): {summary}")
            label.setStyleSheet("color: #d4a76a;")
            return
        label.setText(f"Payroll policy preview (blocked): {summary}")
        label.setStyleSheet("color: #d45b5b;")

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
        policy = evaluate_trade_payroll_impact(
            trade,
            players_by_id=self.players,
        )
        if not policy.allowed:
            record_payroll_policy_result(
                policy,
                action="owner_trade_submit",
                data_dir=get_data_dir(),
            )
            QMessageBox.warning(
                self,
                "Payroll Policy Blocked",
                format_payroll_policy_message(policy),
            )
            return
        if policy.warning:
            record_payroll_policy_result(
                policy,
                action="owner_trade_submit",
                data_dir=get_data_dir(),
            )
            proceed = QMessageBox.question(
                self,
                "Payroll Policy Warning",
                format_payroll_policy_message(policy) + "\n\nSubmit this trade anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return
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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Incoming Trade Offers")
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        self.incoming_list = QListWidget()
        self.incoming_list.setMinimumHeight(240)
        self.incoming_list.currentItemChanged.connect(
            lambda _current, _previous: self._update_incoming_policy_preview()
        )
        layout.addWidget(self.incoming_list)

        self.incoming_detail_label = QLabel("Select a trade to inspect full asset details.")
        self.incoming_detail_label.setWordWrap(True)
        layout.addWidget(self.incoming_detail_label)

        self.incoming_policy_label = QLabel("Payroll policy preview: select an incoming trade.")
        self.incoming_policy_label.setWordWrap(True)
        layout.addWidget(self.incoming_policy_label)

        btn_row = QHBoxLayout()
        accept_btn = QPushButton("Accept")
        reject_btn = QPushButton("Reject")
        accept_btn.clicked.connect(lambda: self._respond_to_trade(True))
        reject_btn.clicked.connect(lambda: self._respond_to_trade(False))
        btn_row.addWidget(accept_btn)
        btn_row.addWidget(reject_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(1)

        self._load_incoming_trades()
        return widget

    def _load_incoming_trades(self):
        self.trade_map: Dict[str, Trade] = {}
        self.incoming_list.clear()
        for t in get_pending_trades(self.team_id):
            summary = f"{t.trade_id} | {t.from_team} -> {t.to_team}"
            item = QListWidgetItem(summary)
            item.setData(Qt.ItemDataRole.UserRole, t.trade_id)
            self.incoming_list.addItem(item)
            self.trade_map[t.trade_id] = t
        self._update_incoming_policy_preview()

    def _update_incoming_policy_preview(self) -> None:
        label = getattr(self, "incoming_policy_label", None)
        if label is None:
            return
        selected = self.incoming_list.currentItem()
        if selected is None:
            self.incoming_detail_label.setText(
                "Select a trade to inspect full asset details."
            )
            label.setText("Payroll policy preview: select an incoming trade.")
            label.setStyleSheet("")
            return
        trade_id = selected.data(Qt.ItemDataRole.UserRole)
        trade = self.trade_map.get(str(trade_id or ""))
        if trade is None:
            self.incoming_detail_label.setText("Unable to load details for this trade.")
            label.setText("Payroll policy preview: unable to evaluate selected trade.")
            label.setStyleSheet("")
            return
        give_names = [
            self.players.get(pid).last_name
            for pid in trade.give_player_ids
            if pid in self.players
        ]
        recv_names = [
            self.players.get(pid).last_name
            for pid in trade.receive_player_ids
            if pid in self.players
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
        self.incoming_detail_label.setText(
            f"Offer details:\n"
            f"{trade.from_team} sends: {', '.join(give_assets) if give_assets else '--'}\n"
            f"{trade.to_team} sends: {', '.join(recv_assets) if recv_assets else '--'}"
        )
        result = evaluate_trade_payroll_impact(
            trade,
            players_by_id=self.players,
        )
        if not result.violations:
            label.setText("Payroll policy preview: no payroll rule issues detected.")
            label.setStyleSheet("color: #2fa36b;")
            return
        summary = format_payroll_policy_message(result).replace("\n", " ")
        if result.allowed and result.warning:
            label.setText(f"Payroll policy preview (warning): {summary}")
            label.setStyleSheet("color: #d4a76a;")
            return
        label.setText(f"Payroll policy preview (blocked): {summary}")
        label.setStyleSheet("color: #d45b5b;")

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

        trade_id = selected.data(Qt.ItemDataRole.UserRole)
        trade = self.trade_map.get(str(trade_id or ""))
        if trade is None:
            QMessageBox.warning(self, "Trade Missing", "Unable to load selected trade.")
            return
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
            policy = evaluate_trade_payroll_impact(
                trade,
                players_by_id=self.players,
            )
            if not policy.allowed:
                record_payroll_policy_result(
                    policy,
                    action="owner_trade_accept",
                    data_dir=get_data_dir(),
                )
                QMessageBox.warning(
                    self,
                    "Payroll Policy Blocked",
                    format_payroll_policy_message(policy),
                )
                return
            if policy.warning:
                record_payroll_policy_result(
                    policy,
                    action="owner_trade_accept",
                    data_dir=get_data_dir(),
                )
                proceed = QMessageBox.question(
                    self,
                    "Payroll Policy Warning",
                    format_payroll_policy_message(policy) + "\n\nProceed with this trade?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if proceed != QMessageBox.StandardButton.Yes:
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
            transfer_contracts(
                trade.give_player_ids,
                trade.to_team,
                players_by_id=self.players,
            )
            transfer_contracts(
                trade.receive_player_ids,
                trade.from_team,
                players_by_id=self.players,
            )
        except Exception:
            pass
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

