from __future__ import annotations

from typing import Dict, Mapping

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from services.contracts_service import (
    extend_contract,
    get_contract,
    set_contract_option_decision,
)
from services.finance_settings import load_financial_settings
from services.finance_budget_effects import training_camp_multiplier_for_team
from services.gm_finance_queue import (
    apply_recommended_arbitration_decisions,
    apply_recommended_free_agency_targets,
    build_arbitration_queue,
    build_free_agency_queue,
    list_team_queue_decisions,
)
from services.offseason_finance_flow import collect_offseason_finance_overview
from services.owner_finance_engine import (
    get_team_finance_snapshot,
    list_team_financial_transactions,
    update_team_budget_targets,
)
from services.payroll_engine import calculate_annual_payroll_totals, load_contracts
from utils.league_settings import is_owner_league, load_league_settings
from .components import Card, section_title
from .manual_viewer_dialog import DOC_FINANCE_MANUAL, ManualViewerDialog

_ARBITRATION_SERVICE_DAYS = 172
_ARBITRATION_ELIGIBILITY_DAYS = 3 * _ARBITRATION_SERVICE_DAYS

_MODULE_LABELS = {
    "owner_revenue": "Owner Revenue",
    "owner_market_model": "Owner Market Model",
    "owner_budgets": "Owner Budgets",
    "owner_expenses": "Owner Expenses",
    "gm_contracts": "GM Contracts",
    "gm_payroll_rules": "GM Payroll Rules",
    "gm_arbitration": "GM Arbitration",
    "gm_free_agency": "GM Free Agency",
    "gm_roster_cost_enforcement": "GM Roster Cost Enforcement",
    "gm_finance_ai": "GM Finance AI",
}

_OWNER_BUDGET_FIELDS = ("training", "scouting", "development", "facilities")
_OWNER_BUDGET_LABELS = {
    "training": "Training",
    "scouting": "Scouting",
    "development": "Development",
    "facilities": "Facilities",
}


class OwnerFinancePage(QWidget):
    """Owner-facing finance hub split into Owner Ops and GM/Coach Ops tabs."""

    def __init__(self, dashboard) -> None:
        super().__init__()
        self._dashboard = dashboard
        self._requires_commissioner_review = False
        self._gm_contract_rows_by_player: dict[str, Dict[str, object]] = {}
        self._gm_contracts_enabled = False
        self._gm_contract_advanced_terms_enabled = False
        self._budget_inputs: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        title = QLabel("Owner Finance")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel(
            "Use Owner Ops for franchise cashflow and GM/Coach Ops for payroll, contracts, and queues."
        )
        subtitle.setStyleSheet("color: #b8b8b8;")
        subtitle.setWordWrap(True)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        tutorial_button = QPushButton("Tutorial")
        tutorial_button.clicked.connect(self._open_tutorial)
        manual_button = QPushButton("Finance Manual")
        manual_button.clicked.connect(self._open_finance_manual)

        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        header_row.addLayout(title_block, stretch=1)
        header_row.addWidget(manual_button, alignment=Qt.AlignmentFlag.AlignRight)
        header_row.addWidget(tutorial_button, alignment=Qt.AlignmentFlag.AlignRight)
        header_row.addWidget(refresh_button, alignment=Qt.AlignmentFlag.AlignRight)
        root.addLayout(header_row)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)

        owner_ops = QWidget()
        owner_layout = QVBoxLayout(owner_ops)
        owner_layout.setContentsMargins(0, 0, 0, 0)
        owner_layout.setSpacing(12)

        self.status_card = Card()
        self.status_card.layout().addWidget(section_title("Current Status"))
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_card.layout().addWidget(self.status_label)
        owner_layout.addWidget(self.status_card)

        self.projections_card = Card()
        self.projections_card.layout().addWidget(section_title("Monthly Projection"))
        self.projections_label = QLabel("")
        self.projections_label.setWordWrap(True)
        self.projections_card.layout().addWidget(self.projections_label)
        owner_layout.addWidget(self.projections_card)

        self.budgets_card = Card()
        self.budgets_card.layout().addWidget(section_title("Budget Controls"))
        self.budgets_hint_label = QLabel("")
        self.budgets_hint_label.setWordWrap(True)
        self.budgets_card.layout().addWidget(self.budgets_hint_label)
        for key in _OWNER_BUDGET_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(QLabel(f"{_OWNER_BUDGET_LABELS[key]} Budget"))
            field = QLineEdit()
            field.setPlaceholderText("$0")
            row.addWidget(field, stretch=1)
            self._budget_inputs[key] = field
            self.budgets_card.layout().addLayout(row)
        self.save_budgets_button = QPushButton("Save Budget Targets")
        self.save_budgets_button.clicked.connect(self._save_budget_targets)
        self.budgets_card.layout().addWidget(self.save_budgets_button)
        owner_layout.addWidget(self.budgets_card)

        self.history_card = Card()
        self.history_card.layout().addWidget(section_title("Finance Transaction History"))
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(180)
        self.history_card.layout().addWidget(self.history_list)
        owner_layout.addWidget(self.history_card, stretch=1)

        gm_ops = QWidget()
        gm_layout = QVBoxLayout(gm_ops)
        gm_layout.setContentsMargins(0, 0, 0, 0)
        gm_layout.setSpacing(12)

        self.gm_modules_card = Card()
        self.gm_modules_card.layout().addWidget(section_title("Module Status"))
        self.gm_modules_label = QLabel("")
        self.gm_modules_label.setWordWrap(True)
        self.gm_modules_card.layout().addWidget(self.gm_modules_label)
        gm_layout.addWidget(self.gm_modules_card)

        self.workflow_card = Card()
        self.workflow_card.layout().addWidget(section_title("Next Finance Actions"))
        self.workflow_label = QLabel("")
        self.workflow_label.setWordWrap(True)
        self.workflow_card.layout().addWidget(self.workflow_label)
        gm_layout.addWidget(self.workflow_card)

        self.gm_contracts_card = Card()
        self.gm_contracts_card.layout().addWidget(section_title("Contracts & Payroll"))
        self.gm_summary_label = QLabel("")
        self.gm_summary_label.setWordWrap(True)
        self.gm_contracts_card.layout().addWidget(self.gm_summary_label)
        self.gm_contract_list = QListWidget()
        self.gm_contract_list.setMinimumHeight(220)
        self.gm_contract_list.itemSelectionChanged.connect(
            self._sync_contract_action_buttons
        )
        self.gm_contracts_card.layout().addWidget(self.gm_contract_list)
        contract_actions = QVBoxLayout()
        contract_row_primary = QHBoxLayout()
        contract_row_secondary = QHBoxLayout()
        self.extend_contract_button = QPushButton("Extend Contract")
        self.extend_contract_button.clicked.connect(self._extend_selected_contract)
        self.add_option_button = QPushButton("Add Option")
        self.add_option_button.clicked.connect(self._add_option_to_selected_contract)
        self.add_incentive_button = QPushButton("Add Incentive")
        self.add_incentive_button.clicked.connect(
            self._add_incentive_to_selected_contract
        )
        self.edit_guarantees_button = QPushButton("Edit Guarantees")
        self.edit_guarantees_button.clicked.connect(
            self._edit_selected_guarantees
        )
        self.exercise_option_button = QPushButton("Exercise Option")
        self.exercise_option_button.clicked.connect(
            lambda: self._set_selected_option_decision("exercised")
        )
        self.decline_option_button = QPushButton("Decline Option")
        self.decline_option_button.clicked.connect(
            lambda: self._set_selected_option_decision("declined")
        )
        self.edit_option_button = QPushButton("Edit Option")
        self.edit_option_button.clicked.connect(self._edit_selected_option)
        self.remove_option_button = QPushButton("Remove Option")
        self.remove_option_button.clicked.connect(self._remove_selected_option)
        self.edit_incentive_button = QPushButton("Edit Incentive")
        self.edit_incentive_button.clicked.connect(self._edit_selected_incentive)
        self.remove_incentive_button = QPushButton("Remove Incentive")
        self.remove_incentive_button.clicked.connect(self._remove_selected_incentive)
        contract_row_primary.addWidget(self.extend_contract_button)
        contract_row_primary.addWidget(self.add_option_button)
        contract_row_primary.addWidget(self.add_incentive_button)
        contract_row_primary.addWidget(self.edit_guarantees_button)
        contract_row_primary.addWidget(self.edit_option_button)
        contract_row_primary.addStretch(1)
        contract_row_secondary.addWidget(self.exercise_option_button)
        contract_row_secondary.addWidget(self.decline_option_button)
        contract_row_secondary.addWidget(self.remove_option_button)
        contract_row_secondary.addWidget(self.edit_incentive_button)
        contract_row_secondary.addWidget(self.remove_incentive_button)
        contract_row_secondary.addStretch(1)
        contract_actions.addLayout(contract_row_primary)
        contract_actions.addLayout(contract_row_secondary)
        self.gm_contracts_card.layout().addLayout(contract_actions)
        gm_layout.addWidget(self.gm_contracts_card, stretch=1)

        self.gm_queue_card = Card()
        self.gm_queue_card.layout().addWidget(section_title("Arbitration & Free Agency Queue"))
        self.gm_queue_label = QLabel("")
        self.gm_queue_label.setWordWrap(True)
        self.gm_queue_card.layout().addWidget(self.gm_queue_label)
        self.gm_queue_list = QListWidget()
        self.gm_queue_list.setMinimumHeight(180)
        self.gm_queue_card.layout().addWidget(self.gm_queue_list)
        gm_actions = QVBoxLayout()
        gm_actions_primary = QHBoxLayout()
        gm_actions_secondary = QHBoxLayout()
        self.open_trade_center_button = QPushButton("Open Trade Center")
        self.open_trade_center_button.clicked.connect(self._open_trade_center)
        self.open_free_agency_button = QPushButton("Open Free Agency Hub")
        self.open_free_agency_button.clicked.connect(self._open_free_agency_hub)
        self.queue_arbitration_button = QPushButton("Queue Recommended Arbitration")
        self.queue_arbitration_button.clicked.connect(
            self._queue_recommended_arbitration
        )
        self.queue_free_agency_button = QPushButton("Queue Recommended FA Targets")
        self.queue_free_agency_button.clicked.connect(self._queue_recommended_free_agency)
        gm_actions_primary.addWidget(self.open_trade_center_button)
        gm_actions_primary.addWidget(self.open_free_agency_button)
        gm_actions_primary.addStretch(1)
        gm_actions_secondary.addWidget(self.queue_arbitration_button)
        gm_actions_secondary.addWidget(self.queue_free_agency_button)
        gm_actions_secondary.addStretch(1)
        gm_actions.addLayout(gm_actions_primary)
        gm_actions.addLayout(gm_actions_secondary)
        self.gm_queue_card.layout().addLayout(gm_actions)
        gm_layout.addWidget(self.gm_queue_card, stretch=1)

        self._tabs.addTab(self._wrap_scroll(owner_ops), "Owner Ops")
        self._tabs.addTab(self._wrap_scroll(gm_ops), "GM/Coach Ops")

        self.refresh()

    @staticmethod
    def _wrap_scroll(content: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(content)
        return area

    def _open_tutorial(self) -> None:
        callback = getattr(self._dashboard, "show_finance_snapshot_tutorial", None)
        if callable(callback):
            callback(force=True)

    def _open_finance_manual(self) -> None:
        callback = getattr(self._dashboard, "open_finance_manual", None)
        if callable(callback):
            callback()
            return
        try:
            dialog = ManualViewerDialog(
                initial_doc_id=DOC_FINANCE_MANUAL,
                parent=self,
            )
            dialog.exec()
        except Exception:
            pass

    def _open_trade_center(self) -> None:
        callback = getattr(self._dashboard, "open_trade_dialog", None)
        if callable(callback):
            callback()

    def _open_free_agency_hub(self) -> None:
        callback = getattr(self._dashboard, "open_free_agency_hub", None)
        if callable(callback):
            callback()

    def _queue_recommended_arbitration(self) -> None:
        team_id = str(getattr(self._dashboard, "team_id", "") or "").strip()
        result = apply_recommended_arbitration_decisions(team_id)
        self._show_status(str(result.get("message") or "Queued arbitration decisions."))
        self.refresh()

    def _queue_recommended_free_agency(self) -> None:
        team_id = str(getattr(self._dashboard, "team_id", "") or "").strip()
        result = apply_recommended_free_agency_targets(team_id)
        self._show_status(str(result.get("message") or "Queued free-agency decisions."))
        self.refresh()

    def _show_status(self, message: str) -> None:
        status_bar = getattr(self._dashboard, "statusBar", None)
        if callable(status_bar):
            try:
                status = status_bar()
                if status is not None:
                    status.showMessage(message, 5000)
            except Exception:
                pass

    def _selected_contract_row(self) -> Dict[str, object] | None:
        item = self.gm_contract_list.currentItem()
        if item is None:
            return None
        player_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not player_id:
            return None
        row = self._gm_contract_rows_by_player.get(player_id)
        if not isinstance(row, Mapping):
            return None
        return dict(row)

    def _sync_contract_action_buttons(self) -> None:
        row = self._selected_contract_row()
        has_selection = row is not None
        enabled = self._gm_contracts_enabled and has_selection
        advanced_enabled = enabled and self._gm_contract_advanced_terms_enabled
        has_options = advanced_enabled and self._row_has_option_terms(row)
        self.extend_contract_button.setEnabled(enabled)
        self.add_option_button.setEnabled(advanced_enabled)
        self.add_incentive_button.setEnabled(advanced_enabled)
        self.edit_guarantees_button.setEnabled(advanced_enabled)
        self.edit_option_button.setEnabled(has_options)
        self.exercise_option_button.setEnabled(has_options)
        self.decline_option_button.setEnabled(has_options)
        self.remove_option_button.setEnabled(has_options)
        has_incentives = advanced_enabled and self._row_has_incentive_terms(row)
        self.edit_incentive_button.setEnabled(has_incentives)
        self.remove_incentive_button.setEnabled(has_incentives)

    @staticmethod
    def _row_has_option_terms(row: Mapping[str, object] | None) -> bool:
        if not isinstance(row, Mapping):
            return False
        try:
            return int(row.get("options_count", 0) or 0) > 0
        except Exception:
            return False

    @staticmethod
    def _row_has_incentive_terms(row: Mapping[str, object] | None) -> bool:
        if not isinstance(row, Mapping):
            return False
        try:
            return int(row.get("incentives_count", 0) or 0) > 0
        except Exception:
            return False

    @staticmethod
    def _contracts_advanced_terms_enabled(level: str) -> bool:
        clean_level = str(level or "").strip().lower()
        return clean_level in {"advanced", "mlb_like"}

    def _extend_selected_contract(self) -> None:
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        years_default = 1
        years, ok = QInputDialog.getInt(
            self,
            "Extend Contract",
            "Additional years:",
            years_default,
            1,
            10,
            1,
        )
        if not ok:
            return
        salary_default = max(
            0,
            int(contract.get("annual_salary", row.get("annual_salary", 0)) or 0),
        )
        salary, ok = QInputDialog.getInt(
            self,
            "Extend Contract",
            "New annual salary:",
            salary_default,
            0,
            250_000_000,
            100_000,
        )
        if not ok:
            return
        updated = extend_contract(
            player_id,
            additional_years=years,
            annual_salary=salary,
        )
        if updated is None:
            self._show_status("Unable to extend selected contract.")
            return
        self._show_status(
            f"Extended contract for {player_id} by {years} year(s)."
        )
        self.refresh()

    def _add_option_to_selected_contract(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to add option terms.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        option_type, ok = QInputDialog.getItem(
            self,
            "Add Contract Option",
            "Option type:",
            ["team", "player", "mutual", "vesting"],
            0,
            False,
        )
        if not ok:
            return
        salary_default = max(0, int(contract.get("annual_salary", 0) or 0))
        option_salary, ok = QInputDialog.getInt(
            self,
            "Add Contract Option",
            "Option salary:",
            salary_default,
            0,
            250_000_000,
            100_000,
        )
        if not ok:
            return
        buyout, ok = QInputDialog.getInt(
            self,
            "Add Contract Option",
            "Buyout amount (0 for none):",
            0,
            0,
            250_000_000,
            50_000,
        )
        if not ok:
            return
        options = list(contract.get("options") or [])
        options.append(
            {
                "type": str(option_type or "team").strip().lower(),
                "salary": int(option_salary),
                "buyout": int(buyout),
                "decision": "pending",
            }
        )
        updated = extend_contract(
            player_id,
            additional_years=0,
            options=options,
        )
        if updated is None:
            self._show_status("Unable to add option to selected contract.")
            return
        self._show_status(f"Added option term to {player_id}.")
        self.refresh()

    def _add_incentive_to_selected_contract(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to add incentive terms.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        label, ok = QInputDialog.getText(
            self,
            "Add Incentive",
            "Incentive label:",
            text="Performance Bonus",
        )
        if not ok:
            return
        clean_label = str(label or "").strip()
        if not clean_label:
            self._show_status("Incentive label is required.")
            return
        amount, ok = QInputDialog.getInt(
            self,
            "Add Incentive",
            "Incentive amount:",
            500_000,
            1,
            25_000_000,
            10_000,
        )
        if not ok:
            return
        probability, ok = QInputDialog.getDouble(
            self,
            "Add Incentive",
            "Expected probability (0.0 - 1.0):",
            0.3,
            0.0,
            1.0,
            2,
        )
        if not ok:
            return
        incentives = list(contract.get("incentives") or [])
        incentives.append(
            {
                "label": clean_label,
                "amount": int(amount),
                "expected_probability": float(probability),
            }
        )
        updated = extend_contract(
            player_id,
            additional_years=0,
            incentives=incentives,
        )
        if updated is None:
            self._show_status("Unable to add incentive to selected contract.")
            return
        self._show_status(f"Added incentive term to {player_id}.")
        self.refresh()

    def _edit_selected_guarantees(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status(
                "Enable GM Contracts advanced mode to edit guarantees."
            )
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        guaranteed_default = (
            "Guaranteed"
            if bool(contract.get("guaranteed", True))
            else "Not Guaranteed"
        )
        guaranteed_label, ok = QInputDialog.getItem(
            self,
            "Edit Guarantees",
            "Guarantee status:",
            ["Guaranteed", "Not Guaranteed"],
            0 if guaranteed_default == "Guaranteed" else 1,
            False,
        )
        if not ok:
            return
        current_buyout = max(
            0,
            self._safe_int(contract.get("buyout_guarantee", 0)),
        )
        buyout_guarantee, ok = QInputDialog.getInt(
            self,
            "Edit Guarantees",
            "Guaranteed buyout amount:",
            current_buyout,
            0,
            250_000_000,
            50_000,
        )
        if not ok:
            return
        updated = extend_contract(
            player_id,
            additional_years=0,
            guaranteed=(guaranteed_label == "Guaranteed"),
            buyout_guarantee=buyout_guarantee,
        )
        if updated is None:
            self._show_status("Unable to update guarantee terms.")
            return
        self._show_status(f"Updated guarantee terms for {player_id}.")
        self.refresh()

    def _select_option_index(
        self,
        options: list[object],
        *,
        title: str,
        prompt: str,
    ) -> int | None:
        if not options:
            return None
        if len(options) == 1:
            return 0
        labels: list[str] = []
        for idx, raw_option in enumerate(options):
            option = raw_option if isinstance(raw_option, Mapping) else {}
            option_type = str(option.get("type") or "team").strip()
            option_salary = self._fmt_currency(
                self._safe_int(option.get("salary", 0))
            )
            decision = str(option.get("decision") or "pending").strip().lower()
            labels.append(
                f"#{idx + 1} {option_type} @ {option_salary} ({decision})"
            )
        selected_label, ok = QInputDialog.getItem(
            self,
            title,
            prompt,
            labels,
            0,
            False,
        )
        if not ok:
            return None
        return max(0, labels.index(selected_label))

    def _select_incentive_index(
        self,
        incentives: list[object],
        *,
        title: str,
        prompt: str,
    ) -> int | None:
        if not incentives:
            return None
        if len(incentives) == 1:
            return 0
        labels: list[str] = []
        for idx, raw_incentive in enumerate(incentives):
            incentive = raw_incentive if isinstance(raw_incentive, Mapping) else {}
            label = str(incentive.get("label") or f"Incentive {idx + 1}").strip()
            amount = self._fmt_currency(self._safe_int(incentive.get("amount", 0)))
            labels.append(f"#{idx + 1} {label} ({amount})")
        selected_label, ok = QInputDialog.getItem(
            self,
            title,
            prompt,
            labels,
            0,
            False,
        )
        if not ok:
            return None
        return max(0, labels.index(selected_label))

    def _edit_selected_option(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to edit options.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        options = list(contract.get("options") or [])
        option_index = self._select_option_index(
            options,
            title="Edit Option",
            prompt="Option term:",
        )
        if option_index is None:
            self._show_status("Selected contract has no option terms.")
            return
        current_option_raw = options[option_index]
        current_option = (
            current_option_raw
            if isinstance(current_option_raw, Mapping)
            else {}
        )
        option_types = ["team", "player", "mutual", "vesting"]
        current_type = str(current_option.get("type") or "team").strip().lower()
        if current_type not in option_types:
            current_type = "team"
        option_type, ok = QInputDialog.getItem(
            self,
            "Edit Option",
            "Option type:",
            option_types,
            option_types.index(current_type),
            False,
        )
        if not ok:
            return
        option_salary, ok = QInputDialog.getInt(
            self,
            "Edit Option",
            "Option salary:",
            max(0, self._safe_int(current_option.get("salary", 0))),
            0,
            250_000_000,
            100_000,
        )
        if not ok:
            return
        buyout, ok = QInputDialog.getInt(
            self,
            "Edit Option",
            "Buyout amount:",
            max(0, self._safe_int(current_option.get("buyout", 0))),
            0,
            250_000_000,
            50_000,
        )
        if not ok:
            return
        decision_values = ["pending", "exercised", "declined"]
        current_decision = str(current_option.get("decision") or "pending").strip().lower()
        if current_decision not in decision_values:
            current_decision = "pending"
        decision, ok = QInputDialog.getItem(
            self,
            "Edit Option",
            "Decision:",
            decision_values,
            decision_values.index(current_decision),
            False,
        )
        if not ok:
            return
        options[option_index] = {
            **dict(current_option),
            "type": str(option_type).strip().lower(),
            "salary": int(option_salary),
            "buyout": int(buyout),
            "decision": str(decision).strip().lower(),
        }
        updated = extend_contract(
            player_id,
            additional_years=0,
            options=options,
        )
        if updated is None:
            self._show_status("Unable to update selected option.")
            return
        self._show_status(
            f"Updated option #{option_index + 1} for {player_id}."
        )
        self.refresh()

    def _remove_selected_option(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to remove options.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        options = list(contract.get("options") or [])
        option_index = self._select_option_index(
            options,
            title="Remove Option",
            prompt="Option term:",
        )
        if option_index is None:
            self._show_status("Selected contract has no option terms.")
            return
        options.pop(option_index)
        updated = extend_contract(
            player_id,
            additional_years=0,
            options=options,
        )
        if updated is None:
            self._show_status("Unable to remove selected option.")
            return
        self._show_status(
            f"Removed option #{option_index + 1} from {player_id}."
        )
        self.refresh()

    def _edit_selected_incentive(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to edit incentives.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        incentives = list(contract.get("incentives") or [])
        incentive_index = self._select_incentive_index(
            incentives,
            title="Edit Incentive",
            prompt="Incentive term:",
        )
        if incentive_index is None:
            self._show_status("Selected contract has no incentive terms.")
            return
        current_incentive_raw = incentives[incentive_index]
        current_incentive = (
            current_incentive_raw
            if isinstance(current_incentive_raw, Mapping)
            else {}
        )
        label, ok = QInputDialog.getText(
            self,
            "Edit Incentive",
            "Incentive label:",
            text=str(current_incentive.get("label") or "Performance Bonus"),
        )
        if not ok:
            return
        clean_label = str(label or "").strip()
        if not clean_label:
            self._show_status("Incentive label is required.")
            return
        amount, ok = QInputDialog.getInt(
            self,
            "Edit Incentive",
            "Incentive amount:",
            max(1, self._safe_int(current_incentive.get("amount", 1))),
            1,
            25_000_000,
            10_000,
        )
        if not ok:
            return
        probability, ok = QInputDialog.getDouble(
            self,
            "Edit Incentive",
            "Expected probability (0.0 - 1.0):",
            max(
                0.0,
                min(
                    1.0,
                    float(current_incentive.get("expected_probability", 0.3) or 0.3),
                ),
            ),
            0.0,
            1.0,
            2,
        )
        if not ok:
            return
        incentives[incentive_index] = {
            **dict(current_incentive),
            "label": clean_label,
            "amount": int(amount),
            "expected_probability": float(probability),
        }
        updated = extend_contract(
            player_id,
            additional_years=0,
            incentives=incentives,
        )
        if updated is None:
            self._show_status("Unable to update selected incentive.")
            return
        self._show_status(
            f"Updated incentive #{incentive_index + 1} for {player_id}."
        )
        self.refresh()

    def _remove_selected_incentive(self) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to remove incentives.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        incentives = list(contract.get("incentives") or [])
        incentive_index = self._select_incentive_index(
            incentives,
            title="Remove Incentive",
            prompt="Incentive term:",
        )
        if incentive_index is None:
            self._show_status("Selected contract has no incentive terms.")
            return
        incentives.pop(incentive_index)
        updated = extend_contract(
            player_id,
            additional_years=0,
            incentives=incentives,
        )
        if updated is None:
            self._show_status("Unable to remove selected incentive.")
            return
        self._show_status(
            f"Removed incentive #{incentive_index + 1} from {player_id}."
        )
        self.refresh()

    def _set_selected_option_decision(self, decision: str) -> None:
        if not self._gm_contract_advanced_terms_enabled:
            self._show_status("Enable GM Contracts advanced mode to manage option decisions.")
            return
        row = self._selected_contract_row()
        if row is None:
            self._show_status("Select a contract row first.")
            return
        player_id = str(row.get("player_id") or "").strip()
        contract = get_contract(player_id)
        if not isinstance(contract, Mapping):
            self._show_status("Contract not found for selected player.")
            return
        options = list(contract.get("options") or [])
        if not options:
            self._show_status("Selected contract has no option terms.")
            return
        option_index = self._select_option_index(
            options,
            title="Select Option",
            prompt="Option term:",
        )
        if option_index is None:
            self._show_status("Selected contract has no option terms.")
            return
        updated = set_contract_option_decision(
            player_id,
            decision=decision,
            option_index=option_index,
        )
        if updated is None:
            self._show_status("Unable to update option decision.")
            return
        action = "exercised" if str(decision).strip().lower() == "exercised" else "declined"
        self._show_status(f"Marked option #{option_index + 1} as {action} for {player_id}.")
        self.refresh()

    @staticmethod
    def _fmt_currency(amount: int) -> str:
        sign = "-" if amount < 0 else ""
        return f"{sign}${abs(int(amount)):,}"

    @staticmethod
    def _fmt_level(level: str) -> str:
        token = str(level or "off").strip()
        if token == "mlb_like":
            return "MLB-Like"
        return token.title()

    @staticmethod
    def _is_arbitration_candidate(years_left: int, service_time_days: int) -> bool:
        return years_left <= 1 and service_time_days >= _ARBITRATION_ELIGIBILITY_DAYS

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(round(float(value)))
        except Exception:
            return default

    @staticmethod
    def _parse_non_negative_currency(value: object) -> int | None:
        token = str(value or "").strip()
        if not token:
            return 0
        clean = token.replace("$", "").replace(",", "").strip()
        if not clean:
            return 0
        try:
            parsed = int(round(float(clean)))
        except Exception:
            return None
        return max(0, parsed)

    def _save_budget_targets(self) -> None:
        team_id = str(getattr(self._dashboard, "team_id", "") or "").strip()
        if not team_id:
            self._show_status("Unable to resolve team id for budget update.")
            return
        budgets: dict[str, int] = {}
        for key in _OWNER_BUDGET_FIELDS:
            field = self._budget_inputs.get(key)
            raw = field.text() if field is not None else ""
            parsed = self._parse_non_negative_currency(raw)
            if parsed is None:
                self._show_status(f"Invalid value for {_OWNER_BUDGET_LABELS[key]} budget.")
                return
            budgets[key] = parsed
        result = update_team_budget_targets(team_id, budgets)
        if not bool(result.get("saved")):
            self._show_status(
                str(result.get("message") or "Unable to save budget targets.")
            )
            return
        self._show_status("Budget targets saved.")
        self.refresh()

    def refresh(self) -> None:
        team_id = str(getattr(self._dashboard, "team_id", "") or "").strip()
        self._requires_commissioner_review = self._resolve_requires_commissioner_review()
        if self._requires_commissioner_review:
            self.queue_arbitration_button.setText("Queue Recommended Arbitration")
            self.queue_free_agency_button.setText("Queue Recommended FA Targets")
        else:
            self.queue_arbitration_button.setText("Apply Recommended Arbitration")
            self.queue_free_agency_button.setText("Apply Recommended FA Targets")
        settings = load_financial_settings()
        snapshot = get_team_finance_snapshot(team_id)
        annual_payroll = calculate_annual_payroll_totals().get(team_id, 0)
        contracts_payload = load_contracts()
        contract_rows = self._team_contract_rows(team_id, contracts_payload)
        active_contracts = len(contract_rows)
        expiring_contracts = sum(
            1 for row in contract_rows if int(row.get("years_left", 0)) <= 1
        )
        overview = collect_offseason_finance_overview()

        self._refresh_owner_ops(
            snapshot=snapshot,
            settings=settings,
            annual_payroll=annual_payroll,
            active_contracts=active_contracts,
            expiring_contracts=expiring_contracts,
            team_id=team_id,
        )
        self._refresh_gm_ops(
            team_id=team_id,
            requires_commissioner_review=self._requires_commissioner_review,
            settings=settings,
            annual_payroll=annual_payroll,
            contract_rows=contract_rows,
            overview=overview,
        )

    def _refresh_owner_ops(
        self,
        *,
        snapshot,
        settings,
        annual_payroll: int,
        active_contracts: int,
        expiring_contracts: int,
        team_id: str,
    ) -> None:
        self.history_list.clear()
        if snapshot is None:
            self.status_label.setText("Finance data is not available for this team yet.")
            self.projections_label.setText(
                "Run at least one simulation cycle after finance initialization."
            )
            self.budgets_hint_label.setText(
                "Budget controls will unlock after finance data is initialized."
            )
            for field in self._budget_inputs.values():
                field.setText("")
                field.setEnabled(False)
            self.save_budgets_button.setEnabled(False)
            self.history_list.addItem(
                QListWidgetItem("No finance transactions recorded.")
            )
            return

        status_lines = [
            f"Financial System Enabled: {'Yes' if snapshot.financials_enabled else 'No'}",
            f"Preset: {snapshot.preset}",
            f"Cash On Hand: {self._fmt_currency(snapshot.cash_on_hand)}",
            f"Debt: {self._fmt_currency(snapshot.debt)}",
            f"Annual Payroll Commitments: {self._fmt_currency(annual_payroll)}",
            f"Active Contracts: {active_contracts} (expiring after season: {expiring_contracts})",
            f"Total Revenue To Date: {self._fmt_currency(sum(snapshot.revenue_totals.values()))}",
            f"Total Expenses To Date: {self._fmt_currency(sum(snapshot.expense_totals.values()))}",
        ]
        self.status_label.setText("\n".join(status_lines))

        projection_lines: list[str] = []
        if not settings.enabled:
            projection_lines.append(
                "Financial system is disabled by league settings. Owner projections are inactive."
            )
        else:
            revenue_level = settings.module_level("owner_revenue")
            expenses_level = settings.module_level("owner_expenses")
            budgets_level = settings.module_level("owner_budgets")
            contracts_level = settings.module_level("gm_contracts")

            if revenue_level == "off":
                projection_lines.append(
                    "Projected Monthly Revenue: Disabled (Owner Revenue module is Off)."
                )
            else:
                projection_lines.extend(
                    [
                        f"Projected Monthly Revenue ({self._fmt_level(revenue_level)})",
                        "  "
                        + ", ".join(
                            f"{k}: {self._fmt_currency(v)}"
                            for k, v in snapshot.projected_revenue.items()
                        ),
                    ]
                )

            if expenses_level == "off":
                projection_lines.append(
                    "Projected Monthly Expenses: Disabled (Owner Expenses module is Off)."
                )
            else:
                projection_lines.extend(
                    [
                        f"Projected Monthly Expenses ({self._fmt_level(expenses_level)})",
                        "  "
                        + ", ".join(
                            f"{k}: {self._fmt_currency(v)}"
                            for k, v in snapshot.projected_expenses.items()
                        ),
                    ]
                )
                if contracts_level == "off":
                    projection_lines.append(
                        "  Payroll expense is excluded because GM Contracts is Off."
                    )

            projection_lines.append(
                f"Projected Monthly Net: {self._fmt_currency(snapshot.projected_net)}"
            )

            if budgets_level == "off":
                projection_lines.append(
                    "Recommended Budget Targets: Disabled (Owner Budgets module is Off)."
                )
                self.budgets_hint_label.setText(
                    "Budget controls are disabled by commissioner settings."
                )
                for key in _OWNER_BUDGET_FIELDS:
                    field = self._budget_inputs.get(key)
                    if field is not None:
                        field.setText(self._fmt_currency(int(snapshot.budgets.get(key, 0))))
                        field.setEnabled(False)
                self.save_budgets_button.setEnabled(False)
            else:
                projection_lines.extend(
                    [
                        f"Recommended Budget Targets ({self._fmt_level(budgets_level)})",
                        "  "
                        + ", ".join(
                            f"{k}: {self._fmt_currency(v)}"
                            for k, v in snapshot.projected_budgets.items()
                        ),
                    ]
                )
                camp_multiplier = training_camp_multiplier_for_team(team_id)
                projection_lines.append(
                    "Training Camp Development Multiplier: "
                    f"{camp_multiplier:.2f}x"
                )
                self.budgets_hint_label.setText(
                    "Edit and save owner budget targets for this team. Changes apply league-scoped and update finance effects."
                )
                for key in _OWNER_BUDGET_FIELDS:
                    field = self._budget_inputs.get(key)
                    if field is not None:
                        field.setText(str(int(snapshot.budgets.get(key, 0) or 0)))
                        field.setEnabled(True)
                self.save_budgets_button.setEnabled(True)
        if not settings.enabled:
            self.budgets_hint_label.setText(
                "Budget controls are unavailable because the financial system is disabled."
            )
            for key in _OWNER_BUDGET_FIELDS:
                field = self._budget_inputs.get(key)
                if field is not None:
                    field.setText(str(int(snapshot.budgets.get(key, 0) or 0)))
                    field.setEnabled(False)
            self.save_budgets_button.setEnabled(False)
        self.projections_label.setText("\n".join(projection_lines))

        rows = list_team_financial_transactions(team_id, limit=50)
        if not rows:
            self.history_list.addItem(QListWidgetItem("No finance transactions recorded."))
            return
        for row in rows:
            amount = int(row.get("amount", 0) or 0)
            prefix = "+" if amount > 0 else ""
            line = (
                f"{row.get('timestamp', '')} | {row.get('category', '')} | "
                f"{prefix}{self._fmt_currency(amount)}"
            )
            memo = str(row.get("memo", "") or "").strip()
            if memo:
                line = f"{line} | {memo}"
            self.history_list.addItem(QListWidgetItem(line))

    def _refresh_gm_ops(
        self,
        *,
        team_id: str,
        requires_commissioner_review: bool,
        settings,
        annual_payroll: int,
        contract_rows: list[Dict[str, object]],
        overview: Mapping[str, object],
    ) -> None:
        self.gm_contract_list.clear()
        self.gm_queue_list.clear()

        gm_modules = [
            "gm_contracts",
            "gm_payroll_rules",
            "gm_arbitration",
            "gm_free_agency",
            "gm_roster_cost_enforcement",
            "gm_finance_ai",
        ]
        module_lines = [
            f"{_MODULE_LABELS[module]}: {self._fmt_level(settings.module_level(module))}"
            for module in gm_modules
        ]
        self.gm_modules_label.setText("\n".join(module_lines))

        contracts_level = settings.module_level("gm_contracts")
        self._gm_contract_advanced_terms_enabled = self._contracts_advanced_terms_enabled(
            contracts_level
        )
        if (not settings.enabled) or contracts_level == "off":
            self._gm_contracts_enabled = False
            self._gm_contract_advanced_terms_enabled = False
            self._gm_contract_rows_by_player = {}
            self.gm_summary_label.setText(
                "GM contract/payroll features are currently disabled by league settings."
            )
            self.gm_contract_list.addItem(
                QListWidgetItem("Enable GM Contracts to see contract and payroll queues.")
            )
        else:
            self._gm_contracts_enabled = True
            self._gm_contract_rows_by_player = {
                str(row.get("player_id") or ""): row
                for row in contract_rows
                if str(row.get("player_id") or "").strip()
            }
            expiring_count = sum(
                1 for row in contract_rows if int(row.get("years_left", 0)) <= 1
            )
            options_count = sum(
                int(row.get("options_count", 0) or 0)
                for row in contract_rows
            )
            incentives_count = sum(
                int(row.get("incentives_count", 0) or 0)
                for row in contract_rows
            )
            self.gm_summary_label.setText(
                "\n".join(
                    [
                        f"Annual Payroll: {self._fmt_currency(annual_payroll)}",
                        f"Active Contracts: {len(contract_rows)}",
                        f"Expiring Contracts (<= 1 year): {expiring_count}",
                        f"Option Terms: {options_count} | Incentive Terms: {incentives_count}",
                        (
                            "Advanced Terms: Enabled"
                            if self._gm_contract_advanced_terms_enabled
                            else "Advanced Terms: Disabled (set GM Contracts to Advanced/MLB-Like)"
                        ),
                    ]
                )
            )
            if not contract_rows:
                self.gm_contract_list.addItem(QListWidgetItem("No contracts found for this team."))
            else:
                for row in contract_rows[:50]:
                    salary = self._fmt_currency(int(row.get("annual_salary", 0) or 0))
                    years_left = int(row.get("years_left", 0) or 0)
                    service_days = int(row.get("service_time_days", 0) or 0)
                    player_name = str(row.get("player_name") or row.get("player_id") or "")
                    guaranteed = bool(row.get("guaranteed", True))
                    buyout_guarantee = self._fmt_currency(
                        int(row.get("buyout_guarantee", 0) or 0)
                    )
                    options_count = int(row.get("options_count", 0) or 0)
                    incentives_count = int(row.get("incentives_count", 0) or 0)
                    pending_options = int(row.get("pending_options_count", 0) or 0)
                    guarantee_label = "Yes" if guaranteed else "No"
                    item = QListWidgetItem(
                        (
                            f"{player_name} | {salary} | Years Left: {years_left} "
                            f"| Service Days: {service_days} | Options: {options_count} "
                            f"(pending: {pending_options}) | Incentives: {incentives_count} "
                            f"| Guaranteed: {guarantee_label} | Buyout: {buyout_guarantee}"
                        )
                    )
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        str(row.get("player_id") or "").strip(),
                    )
                    self.gm_contract_list.addItem(item)

        arbitration_level = settings.module_level("gm_arbitration")
        free_agency_level = settings.module_level("gm_free_agency")
        arbitration_queue = build_arbitration_queue(team_id)
        free_agency_queue = build_free_agency_queue(team_id, limit=25)
        queued_arb_decisions = list_team_queue_decisions(
            team_id,
            queue_type="arbitration",
        )
        queued_fa_decisions = list_team_queue_decisions(
            team_id,
            queue_type="free_agency",
        )
        unsigned_players = int(overview.get("unsigned_players", 0) or 0)
        phase = str(overview.get("phase", "UNKNOWN") or "UNKNOWN")
        can_run_now = bool(overview.get("can_run_now", False))
        workflow_completed = bool(overview.get("workflow_completed", False))
        pending_arb = sum(
            1
            for row in queued_arb_decisions
            if str(row.get("review_status") or "").strip() == "pending_commissioner"
        )
        rejected_arb = sum(
            1
            for row in queued_arb_decisions
            if str(row.get("review_status") or "").strip() == "rejected_commissioner"
        )
        pending_fa = sum(
            1
            for row in queued_fa_decisions
            if str(row.get("review_status") or "").strip() == "pending_commissioner"
        )
        rejected_fa = sum(
            1
            for row in queued_fa_decisions
            if str(row.get("review_status") or "").strip() == "rejected_commissioner"
        )
        approved_arb = max(0, len(queued_arb_decisions) - pending_arb - rejected_arb)
        approved_fa = max(0, len(queued_fa_decisions) - pending_fa - rejected_fa)
        self.workflow_label.setText(
            self._build_finance_workflow_guidance(
                phase=phase,
                can_run_now=can_run_now,
                workflow_completed=workflow_completed,
                requires_commissioner_review=requires_commissioner_review,
                arbitration_level=arbitration_level,
                free_agency_level=free_agency_level,
                arbitration_candidates=len(arbitration_queue),
                unsigned_players=unsigned_players,
                pending_arb=pending_arb,
                pending_fa=pending_fa,
                approved_arb=approved_arb,
                approved_fa=approved_fa,
                settings_enabled=bool(settings.enabled),
            )
        )

        queue_lines = [
            f"Season Phase: {phase}",
            f"Offseason workflow completed: {'Yes' if workflow_completed else 'No'}",
            (
                "Mode: Multi-owner (commissioner approval required for queued finance decisions)."
                if requires_commissioner_review
                else "Mode: Single-player (recommended finance decisions are auto-approved)."
            ),
            (
                "Arbitration Queue: Disabled by commissioner settings."
                if arbitration_level == "off"
                else (
                    f"Arbitration Candidates: {len(arbitration_queue)} "
                    f"(queued: {len(queued_arb_decisions)}, pending: {pending_arb}, approved: {approved_arb}, rejected: {rejected_arb})"
                )
            ),
            (
                "Free Agency Queue: Disabled by commissioner settings."
                if free_agency_level == "off"
                else (
                    f"Unsigned Players Available: {unsigned_players} "
                    f"(queued: {len(queued_fa_decisions)}, pending: {pending_fa}, approved: {approved_fa}, rejected: {rejected_fa})"
                )
            ),
        ]
        if can_run_now:
            queue_lines.append(
                "Offseason/preseason finance actions are currently in an active phase."
            )
        self.gm_queue_label.setText("\n".join(queue_lines))

        if arbitration_level != "off" and arbitration_queue:
            self.gm_queue_list.addItem(
                QListWidgetItem("Top arbitration candidates for this team:")
            )
            for row in arbitration_queue[:10]:
                player_name = str(row.get("player_name") or row.get("player_id") or "")
                salary = self._fmt_currency(int(row.get("current_salary", 0) or 0))
                action = str(row.get("recommended_action") or "").strip() or "hold"
                queued_action = str(row.get("queued_action") or "").strip()
                queued_status = str(row.get("queued_status") or "").strip()
                queued_suffix = f" | queued: {queued_action}" if queued_action else ""
                if queued_status:
                    queued_suffix = f"{queued_suffix} ({queued_status})"
                self.gm_queue_list.addItem(
                    QListWidgetItem(
                        f"- {player_name} | Current Salary: {salary} | rec: {action}{queued_suffix}"
                    )
                )

        if free_agency_level != "off":
            self.gm_queue_list.addItem(
                QListWidgetItem(
                    f"Free-agency market currently has {unsigned_players} unsigned players."
                )
            )
            if free_agency_queue:
                self.gm_queue_list.addItem(
                    QListWidgetItem("Top free-agency targets:")
                )
                for row in free_agency_queue[:10]:
                    player_name = str(row.get("player_name") or row.get("player_id") or "")
                    expected = self._fmt_currency(int(row.get("expected_salary", 0) or 0))
                    action = str(row.get("recommended_action") or "").strip() or "monitor"
                    queued_action = str(row.get("queued_action") or "").strip()
                    queued_status = str(row.get("queued_status") or "").strip()
                    queued_suffix = f" | queued: {queued_action}" if queued_action else ""
                    if queued_status:
                        queued_suffix = f"{queued_suffix} ({queued_status})"
                    self.gm_queue_list.addItem(
                        QListWidgetItem(
                            f"- {player_name} | ask: {expected} | rec: {action}{queued_suffix}"
                        )
                    )
        elif arbitration_level == "off":
            self.gm_queue_list.addItem(
                QListWidgetItem("Enable GM Arbitration and/or GM Free Agency to unlock queue workflows.")
            )

        self.open_free_agency_button.setEnabled(
            bool(settings.enabled) and free_agency_level != "off"
        )
        self.queue_arbitration_button.setEnabled(
            bool(settings.enabled) and arbitration_level != "off"
        )
        self.queue_free_agency_button.setEnabled(
            bool(settings.enabled) and free_agency_level != "off"
        )
        self._sync_contract_action_buttons()

    @staticmethod
    def _build_finance_workflow_guidance(
        *,
        phase: str,
        can_run_now: bool,
        workflow_completed: bool,
        requires_commissioner_review: bool,
        arbitration_level: str,
        free_agency_level: str,
        arbitration_candidates: int,
        unsigned_players: int,
        pending_arb: int,
        pending_fa: int,
        approved_arb: int,
        approved_fa: int,
        settings_enabled: bool,
    ) -> str:
        if not settings_enabled:
            return (
                "Financial system is disabled.\n"
                "- Next step: Ask commissioner to enable Financial System Settings if this league should use finance workflows."
            )

        lines = [f"Current phase: {phase}"]
        if can_run_now:
            lines.append(
                "- Offseason/preseason window is active: complete finance queue actions before preseason simulation."
            )
        else:
            lines.append(
                "- Regular-season window: monitor payroll/contracts and queue moves for offseason planning."
            )

        if arbitration_level != "off":
            lines.append(
                f"- Arbitration: {arbitration_candidates} candidate(s), pending {pending_arb}, approved {approved_arb}."
            )
        else:
            lines.append("- Arbitration module is off for this league.")

        if free_agency_level != "off":
            lines.append(
                f"- Free agency: {unsigned_players} unsigned player(s), pending {pending_fa}, approved {approved_fa}."
            )
        else:
            lines.append("- Free-agency module is off for this league.")

        if requires_commissioner_review:
            lines.append(
                "- Multi-owner mode: commissioner must review pending finance decisions before they apply."
            )
        else:
            lines.append(
                "- Single-player mode: queued recommended decisions are locally approved/applied."
            )

        if workflow_completed:
            lines.append("- Offseason workflow status: completed for current cycle.")
        elif can_run_now:
            lines.append(
                "- Offseason workflow status: in progress; use commissioner checklist until finalized."
            )
        return "\n".join(lines)

    def _team_contract_rows(
        self,
        team_id: str,
        contracts_payload: Mapping[str, object],
    ) -> list[Dict[str, object]]:
        players = contracts_payload.get("players")
        if not isinstance(players, Mapping):
            return []
        rows: list[Dict[str, object]] = []
        for player_id, raw_contract in players.items():
            if not isinstance(raw_contract, Mapping):
                continue
            contract_team = str(raw_contract.get("team_id") or "").strip()
            if contract_team != team_id:
                continue
            clean_player_id = str(player_id).strip()
            options_raw = raw_contract.get("options")
            options = options_raw if isinstance(options_raw, list) else []
            incentives_raw = raw_contract.get("incentives")
            incentives = incentives_raw if isinstance(incentives_raw, list) else []
            pending_options = 0
            for option in options:
                if not isinstance(option, Mapping):
                    continue
                status = str(option.get("decision") or "pending").strip().lower()
                if status not in {"declined", "decline", "exercised", "exercise"}:
                    pending_options += 1
            rows.append(
                {
                    "player_id": clean_player_id,
                    "player_name": self._resolve_player_name(clean_player_id),
                    "annual_salary": self._safe_int(raw_contract.get("annual_salary", 0)),
                    "years_left": max(
                        0,
                        self._safe_int(raw_contract.get("years_left", 0)),
                    ),
                    "service_time_days": max(
                        0,
                        self._safe_int(raw_contract.get("service_time_days", 0)),
                    ),
                    "guaranteed": bool(raw_contract.get("guaranteed", True)),
                    "buyout_guarantee": max(
                        0,
                        self._safe_int(raw_contract.get("buyout_guarantee", 0)),
                    ),
                    "options_count": len(options),
                    "pending_options_count": pending_options,
                    "incentives_count": len(incentives),
                }
            )
        rows.sort(
            key=lambda row: (
                -int(row.get("annual_salary", 0) or 0),
                str(row.get("player_name") or row.get("player_id") or ""),
            )
        )
        return rows

    def _resolve_player_name(self, player_id: str) -> str:
        players = getattr(self._dashboard, "players", {})
        if not isinstance(players, Mapping):
            return player_id
        player = players.get(player_id)
        if player is None:
            return player_id
        first_name = str(getattr(player, "first_name", "") or "").strip()
        last_name = str(getattr(player, "last_name", "") or "").strip()
        return f"{first_name} {last_name}".strip() or player_id

    @staticmethod
    def _resolve_requires_commissioner_review() -> bool:
        try:
            settings = load_league_settings()
            return bool(is_owner_league(settings))
        except Exception:
            return False
