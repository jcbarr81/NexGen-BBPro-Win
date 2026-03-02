from __future__ import annotations

from typing import Callable, Dict, List, Optional

try:
    from PyQt6.QtCore import Qt, QTimer
except ImportError:  # pragma: no cover - fallback for lightweight test stubs
    from PyQt6.QtCore import Qt

    class QTimer:  # type: ignore[too-many-ancestors]
        @staticmethod
        def singleShot(_msec, callback) -> None:
            if callback is not None:
                callback()
try:
    from PyQt6.QtGui import QGuiApplication
except ImportError:  # pragma: no cover - lightweight test stubs
    QGuiApplication = None  # type: ignore[assignment]
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
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
from services.decision_explanations import (
    append_decision_log,
    explanation,
    reason,
    summarize_decision_explanation,
    should_persist_decision_logs,
)
from services.trade_settings import load_trade_settings
from services.transaction_log import record_transaction
from services.unified_data_service import get_unified_data_service
from utils.player_loader import load_players_from_csv
from utils.path_utils import get_data_dir
from utils.roster_loader import load_roster, save_roster
from utils.team_loader import load_teams
from utils.trade_utils import get_pending_trades, save_trade
from .design_tokens import apply_status

import uuid


def _safe_pick_label(pick_id: str) -> str:
    try:
        return format_pick_label(pick_id)
    except Exception:
        return str(pick_id)


class TradeDialog(QDialog):
    """Dialog allowing an owner to propose and respond to trades."""
    _TRADE_REASON_PLACEHOLDER = (
        "Decision reasons will appear here after you accept or reject an incoming trade."
    )

    def __init__(self, team_id: str, parent=None):
        super().__init__(parent)
        self.team_id = team_id
        self.trade_settings = load_trade_settings()
        self.players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
        self._service = get_unified_data_service()
        self._event_unsubscribes: List[Callable[[], None]] = []
        self._pending_refresh = False
        self._pending_toast_reason: Optional[str] = None
        self._last_trade_decision_explanation: dict[str, object] = {}

        self.setWindowTitle("Trade Center")
        self.setMinimumSize(760, 540)
        width, height = self._initial_window_size()
        self.resize(width, height)

        tabs = QTabWidget()
        tabs.addTab(self._wrap_scrollable_tab(self._build_new_trade_tab()), "New Trade")
        tabs.addTab(self._wrap_scrollable_tab(self._build_incoming_tab()), "Incoming")

        layout = QVBoxLayout()
        status_group = QGroupBox("Trade Center Status")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(4)
        self.trade_status_label = QLabel()
        self.trade_status_label.setObjectName("StatusLabel")
        self.trade_status_label.setWordWrap(True)
        status_layout.addWidget(self.trade_status_label)
        status_hint = QLabel(
            "Review payroll policy previews before submitting or accepting offers."
        )
        status_hint.setWordWrap(True)
        status_layout.addWidget(status_hint)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
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
        self._update_trade_status()

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

        setup_group = QGroupBox("Trade Setup")
        setup_layout = QVBoxLayout()
        setup_layout.setContentsMargins(10, 8, 10, 8)
        setup_layout.setSpacing(6)
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
        setup_layout.addLayout(partner_row)

        self.picks_disabled_label = QLabel(
            "Draft pick trading is disabled by the commissioner."
        )
        self.picks_disabled_label.setWordWrap(True)
        self.picks_disabled_label.setVisible(
            not self.trade_settings.draft_pick_trading_enabled
        )
        setup_layout.addWidget(self.picks_disabled_label)
        setup_group.setLayout(setup_layout)
        layout.addWidget(setup_group)

        assets_group = QGroupBox("Trade Assets")
        assets_row = QHBoxLayout()
        assets_row.setContentsMargins(10, 8, 10, 8)
        assets_row.setSpacing(14)

        give_panel = QGroupBox("You Send")
        give_layout = QVBoxLayout()
        give_layout.setContentsMargins(10, 8, 10, 8)
        give_layout.setSpacing(8)
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
        give_panel.setLayout(give_layout)

        receive_panel = QGroupBox("You Receive")
        receive_layout = QVBoxLayout()
        receive_layout.setContentsMargins(10, 8, 10, 8)
        receive_layout.setSpacing(8)
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
        receive_panel.setLayout(receive_layout)

        assets_row.addWidget(give_panel, 1)
        assets_row.addWidget(receive_panel, 1)
        assets_group.setLayout(assets_row)
        layout.addWidget(assets_group, 1)

        self._refresh_receive_list(self.team_dropdown.currentText())
        self._refresh_pick_lists(self.team_dropdown.currentText())

        review_group = QGroupBox("Offer Review")
        review_layout = QVBoxLayout()
        review_layout.setContentsMargins(10, 8, 10, 8)
        review_layout.setSpacing(4)
        self.selection_summary_label = QLabel("Offer summary: no assets selected yet.")
        self.selection_summary_label.setWordWrap(True)
        review_layout.addWidget(self.selection_summary_label)

        self.new_trade_policy_label = QLabel(
            "Validation & payroll preview: select trade assets."
        )
        self.new_trade_policy_label.setWordWrap(True)
        review_layout.addWidget(self.new_trade_policy_label)
        review_group.setLayout(review_layout)
        layout.addWidget(review_group)
        self._update_offer_summary()
        self._update_new_trade_policy_preview()

        action_group = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(8)
        self.submit_button = QPushButton("Submit Trade")
        self.submit_button.setObjectName("Primary")
        self.submit_button.clicked.connect(self._submit_trade)
        self.submit_button.setEnabled(self.trade_settings.trades_enabled)
        action_layout.addWidget(self.submit_button)
        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self._clear_new_trade_selection)
        action_layout.addWidget(clear_btn)
        action_layout.addStretch(1)
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)
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
            apply_status(label, "")
            return
        if not trade.give_player_ids and not trade.receive_player_ids:
            label.setText("Payroll policy preview: select players to evaluate payroll impact.")
            apply_status(label, "")
            return
        result = evaluate_trade_payroll_impact(
            trade,
            players_by_id=self.players,
        )
        if not result.violations:
            label.setText("Payroll policy preview: no payroll rule issues detected.")
            apply_status(label, "success")
            return
        summary = format_payroll_policy_message(result).replace("\n", " ")
        if result.allowed and result.warning:
            label.setText(f"Payroll policy preview (warning): {summary}")
            apply_status(label, "warning")
            return
        label.setText(f"Payroll policy preview (blocked): {summary}")
        apply_status(label, "danger")

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
        self._clear_new_trade_selection()

    def _clear_new_trade_selection(self) -> None:
        self.give_list.clearSelection()
        self.receive_list.clearSelection()
        self.give_pick_list.clearSelection()
        self.receive_pick_list.clearSelection()
        self._update_offer_summary()
        self._update_new_trade_policy_preview()

    # --- Incoming trades tab -------------------------------------------
    def _build_incoming_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        overview_group = QGroupBox("Incoming Offers Overview")
        overview_layout = QHBoxLayout()
        overview_layout.setContentsMargins(10, 8, 10, 8)
        overview_layout.setSpacing(8)
        self.incoming_count_label = QLabel("Incoming offers: 0")
        self.incoming_count_label.setObjectName("StatusLabel")
        overview_layout.addWidget(self.incoming_count_label)
        overview_layout.addStretch(1)
        refresh_btn = QPushButton("Refresh Offers")
        refresh_btn.clicked.connect(self._refresh_sources)
        overview_layout.addWidget(refresh_btn)
        overview_group.setLayout(overview_layout)
        layout.addWidget(overview_group)

        queue_group = QGroupBox("Incoming Trade Queue")
        queue_layout = QVBoxLayout()
        queue_layout.setContentsMargins(10, 8, 10, 8)
        queue_layout.setSpacing(6)
        self.incoming_list = QListWidget()
        self.incoming_list.setMinimumHeight(240)
        self.incoming_list.currentItemChanged.connect(self._on_incoming_selection_changed)
        queue_layout.addWidget(self.incoming_list)
        queue_group.setLayout(queue_layout)
        layout.addWidget(queue_group, 1)

        review_group = QGroupBox("Offer Review")
        review_layout = QVBoxLayout()
        review_layout.setContentsMargins(10, 8, 10, 8)
        review_layout.setSpacing(4)
        self.incoming_detail_label = QLabel("Select a trade to inspect full asset details.")
        self.incoming_detail_label.setWordWrap(True)
        review_layout.addWidget(self.incoming_detail_label)

        self.incoming_policy_label = QLabel("Payroll policy preview: select an incoming trade.")
        self.incoming_policy_label.setWordWrap(True)
        review_layout.addWidget(self.incoming_policy_label)

        self.incoming_decision_label = QLabel(self._TRADE_REASON_PLACEHOLDER)
        self.incoming_decision_label.setWordWrap(True)
        review_layout.addWidget(self.incoming_decision_label)
        review_group.setLayout(review_layout)
        layout.addWidget(review_group)

        action_group = QGroupBox("Actions")
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(10, 8, 10, 8)
        btn_row.setSpacing(8)
        self.accept_button = QPushButton("Accept")
        self.accept_button.setObjectName("Primary")
        self.reject_button = QPushButton("Reject")
        self.accept_button.clicked.connect(lambda: self._respond_to_trade(True))
        self.reject_button.clicked.connect(lambda: self._respond_to_trade(False))
        btn_row.addWidget(self.accept_button)
        btn_row.addWidget(self.reject_button)
        btn_row.addStretch(1)
        action_group.setLayout(btn_row)
        layout.addWidget(action_group)
        layout.addStretch(1)

        self._load_incoming_trades()
        self._update_trade_decision_reason_label()
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
        if self.incoming_list.count() > 0:
            self.incoming_list.setCurrentRow(0)
        self._update_incoming_offer_count()
        self._update_trade_status()
        self._update_incoming_action_state()
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
            apply_status(label, "")
            return
        trade_id = selected.data(Qt.ItemDataRole.UserRole)
        trade = self.trade_map.get(str(trade_id or ""))
        if trade is None:
            self.incoming_detail_label.setText("Unable to load details for this trade.")
            label.setText("Payroll policy preview: unable to evaluate selected trade.")
            apply_status(label, "")
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
            apply_status(label, "success")
            return
        summary = format_payroll_policy_message(result).replace("\n", " ")
        if result.allowed and result.warning:
            label.setText(f"Payroll policy preview (warning): {summary}")
            apply_status(label, "warning")
            return
        label.setText(f"Payroll policy preview (blocked): {summary}")
        apply_status(label, "danger")

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

        requested_action = "accept" if accept else "reject"
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
                self._record_trade_decision(
                    trade,
                    outcome="owner_accepted",
                    requested_action=requested_action,
                    reasons=[
                        reason(
                            "commissioner_gate",
                            "League requires commissioner approval before execution.",
                        ),
                    ],
                )
                self._load_incoming_trades()
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
                self._record_trade_decision(
                    trade,
                    outcome="blocked",
                    requested_action=requested_action,
                    reasons=[
                        reason(
                            "payroll_policy_blocked",
                            "Payroll policy blocked this trade acceptance.",
                            details={"violations": list(getattr(policy, "violations", []) or [])},
                        ),
                    ],
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
                    self._record_trade_decision(
                        trade,
                        outcome="cancelled",
                        requested_action=requested_action,
                        reasons=[
                            reason(
                                "user_cancelled_after_warning",
                                "Owner cancelled after reviewing payroll warning.",
                                details={
                                    "violations": list(getattr(policy, "violations", []) or []),
                                },
                            ),
                        ],
                    )
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
        self._record_trade_decision(
            trade,
            outcome=trade.status,
            requested_action=requested_action,
            reasons=[
                reason(
                    "owner_response",
                    "Owner explicitly responded to incoming trade offer.",
                ),
            ],
        )
        QMessageBox.information(self, "Trade Updated", f"Trade {trade.trade_id} {trade.status}.")
        self._load_incoming_trades()

    def _record_trade_decision(
        self,
        trade: Trade,
        *,
        outcome: str,
        requested_action: str,
        reasons: list | None = None,
    ) -> None:
        payload = explanation(
            "trade_response",
            outcome,
            actor="owner",
            team_id=self.team_id,
            subject_id=trade.trade_id,
            context={
                "requested_action": requested_action,
                "trade_status": str(getattr(trade, "status", "")),
                "from_team": trade.from_team,
                "to_team": trade.to_team,
                "give_players_count": len(getattr(trade, "give_player_ids", []) or []),
                "receive_players_count": len(getattr(trade, "receive_player_ids", []) or []),
                "give_picks_count": len(getattr(trade, "give_pick_ids", []) or []),
                "receive_picks_count": len(getattr(trade, "receive_pick_ids", []) or []),
            },
            reasons=list(reasons or []),
        )
        self._last_trade_decision_explanation = payload.to_dict()
        self._update_trade_decision_reason_label(self._last_trade_decision_explanation)
        if should_persist_decision_logs():
            append_decision_log(payload)

    def _update_trade_decision_reason_label(self, payload: dict | None = None) -> None:
        label = getattr(self, "incoming_decision_label", None)
        if label is None:
            return
        current_payload = payload
        if current_payload is None:
            raw = getattr(self, "_last_trade_decision_explanation", None)
            current_payload = raw if isinstance(raw, dict) else None
        if not isinstance(current_payload, dict):
            label.setText(self._TRADE_REASON_PLACEHOLDER)
            return
        if str(current_payload.get("decision_type") or "").strip() != "trade_response":
            label.setText(self._TRADE_REASON_PLACEHOLDER)
            return
        summary = summarize_decision_explanation(
            current_payload,
            fallback="Latest trade decision did not include detailed reasons.",
            max_reasons=3,
        )
        label.setText(f"Latest Decision Reasons:\n{summary}")

    def _update_trade_status(self) -> None:
        label = getattr(self, "trade_status_label", None)
        if label is None:
            return
        trades_state = "enabled" if self.trade_settings.trades_enabled else "disabled"
        picks_state = (
            "enabled"
            if self.trade_settings.draft_pick_trading_enabled
            else "disabled"
        )
        incoming_count = len(getattr(self, "trade_map", {}) or {})
        label.setText(
            f"Trading is {trades_state}. Draft pick trading is {picks_state}. "
            f"Incoming offers: {incoming_count}."
        )
        if not self.trade_settings.trades_enabled:
            apply_status(label, "warning")
            return
        if incoming_count > 0:
            apply_status(label, "success")
            return
        apply_status(label, "muted")

    def _update_incoming_offer_count(self) -> None:
        label = getattr(self, "incoming_count_label", None)
        if label is None:
            return
        count = len(getattr(self, "trade_map", {}) or {})
        label.setText(f"Incoming offers: {count}")
        if count > 0:
            apply_status(label, "success")
            return
        apply_status(label, "muted")

    def _on_incoming_selection_changed(self, _current=None, _previous=None) -> None:
        self._update_incoming_policy_preview()
        self._update_incoming_action_state()

    def _update_incoming_action_state(self) -> None:
        selected_item = self.incoming_list.currentItem() if hasattr(self, "incoming_list") else None
        enabled = selected_item is not None
        if hasattr(self, "accept_button"):
            self.accept_button.setEnabled(enabled)
        if hasattr(self, "reject_button"):
            self.reject_button.setEnabled(enabled)

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
