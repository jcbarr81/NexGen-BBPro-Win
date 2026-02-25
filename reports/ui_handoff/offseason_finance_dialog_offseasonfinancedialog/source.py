"""Admin dialog for offseason financial workflow controls."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.offseason_finance_flow import (
    collect_offseason_finance_overview,
    get_offseason_checklist,
    get_offseason_stage_details,
    mark_offseason_stage,
)
from services.gm_finance_queue import (
    apply_approved_queue_decisions,
    set_queue_review_status,
)
from services.finance_reporting import build_commissioner_projection_report, build_finance_alerts


def _format_gm_queue_hint(overview: dict[str, object]) -> tuple[bool, str]:
    if not bool(overview.get("requires_commissioner_finance_review", False)):
        return (
            False,
            "GM queue review is only required in multi-owner leagues.",
        )
    pending = int(overview.get("gm_queue_pending", 0) or 0)
    approved_unapplied = int(overview.get("gm_queue_approved_unapplied", 0) or 0)
    total = int(overview.get("gm_queue_total", 0) or 0)
    if pending > 0:
        return (
            True,
            f"GM queue requires commissioner review: {pending} pending decision(s).",
        )
    if approved_unapplied > 0:
        return (
            True,
            f"GM queue has {approved_unapplied} approved decision(s) that still need application.",
        )
    if total > 0:
        return True, "GM queue is clear for the current offseason checklist stage."
    return True, "No GM queue decisions are queued for this offseason."


def _gm_inline_action_state(
    overview: dict[str, object],
    *,
    selected_status: str | None = None,
) -> dict[str, object]:
    enabled, hint = _format_gm_queue_hint(overview)
    status = str(selected_status or "").strip().lower()
    approved_unapplied = int(overview.get("gm_queue_approved_unapplied", 0) or 0)
    approve_enabled = enabled and status == "pending_commissioner"
    reject_enabled = enabled and status == "pending_commissioner"
    apply_enabled = enabled and approved_unapplied > 0
    return {
        "queue_enabled": enabled,
        "queue_hint": hint,
        "approve_enabled": approve_enabled,
        "reject_enabled": reject_enabled,
        "apply_enabled": apply_enabled,
        "approve_hint": (
            "Approve selected pending GM queue decision."
            if approve_enabled
            else "Select a pending commissioner decision to approve."
        ),
        "reject_hint": (
            "Reject selected pending GM queue decision."
            if reject_enabled
            else "Select a pending commissioner decision to reject."
        ),
        "apply_hint": (
            f"Apply {approved_unapplied} approved GM decision(s)."
            if apply_enabled
            else "No approved-not-applied GM decisions are available.",
        ),
    }


def _filter_gm_queue_rows(
    rows: list[dict[str, object]],
    *,
    team_id: str = "",
    queue_type: str = "",
    status_filter: str = "",
    query: str = "",
) -> list[dict[str, object]]:
    clean_team = str(team_id or "").strip().lower()
    clean_queue = str(queue_type or "").strip().lower()
    clean_status = str(status_filter or "").strip().lower()
    clean_query = str(query or "").strip().lower()
    filtered: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_team = str(row.get("team_id") or "").strip().lower()
        row_queue = str(row.get("queue_type") or "").strip().lower()
        row_status = str(row.get("review_status") or "").strip().lower()
        row_applied = bool(row.get("applied", False))
        if clean_team and row_team != clean_team:
            continue
        if clean_queue and row_queue != clean_queue:
            continue
        if clean_status == "approved_unapplied":
            if row_status not in {"approved_local", "approved_commissioner"} or row_applied:
                continue
        elif clean_status == "approved_applied":
            if row_status not in {"approved_local", "approved_commissioner"} or (not row_applied):
                continue
        elif clean_status == "approved_any":
            if row_status not in {"approved_local", "approved_commissioner"}:
                continue
        elif clean_status and row_status != clean_status:
            continue
        if clean_query:
            haystack = " ".join(
                [
                    str(row.get("team_id") or ""),
                    str(row.get("queue_type") or ""),
                    str(row.get("item_id") or ""),
                    str(row.get("action") or ""),
                    str(row.get("review_status") or ""),
                    str(row.get("notes") or ""),
                ]
            ).lower()
            if clean_query not in haystack:
                continue
        filtered.append(row)
    return filtered


class OffseasonFinanceDialog(QDialog):
    """Review and execute offseason finance tasks for the active league."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Offseason Finance Workflow")
        self.resize(760, 460)
        self._overview: dict[str, object] = {}
        self._checklist: dict[str, object] = {}
        self._details: dict[str, object] = {}
        self._gm_queue_rows: list[dict[str, object]] = []
        self._gm_queue_visible_rows: list[dict[str, object]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        self._blockers = QLabel("")
        self._blockers.setWordWrap(True)
        self._blockers.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._blockers)

        self._alerts = QLabel("")
        self._alerts.setWordWrap(True)
        self._alerts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._alerts)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._status, stretch=1)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=2)

        self._contracts_table = self._build_table(
            ["Player", "Team", "Years Left", "Salary", "Service Days", "Arb Eligible"]
        )
        self._tabs.addTab(self._contracts_table, "Contract Expirations")

        self._arbitration_table = self._build_table(
            ["Player", "Team", "Old Salary", "New Salary", "Delta"]
        )
        self._tabs.addTab(self._arbitration_table, "Arbitration Details")

        self._budget_table = self._build_table(
            [
                "Team",
                "Previous Budget",
                "Current Budget",
                "Delta",
                "Training Δ",
                "Scouting Δ",
                "Development Δ",
                "Facilities Δ",
            ]
        )
        self._tabs.addTab(self._budget_table, "Budget Deltas")

        self._gm_queue_table = self._build_table(
            ["Team", "Queue", "Item ID", "Action", "Status", "Applied", "Updated"]
        )
        self._gm_queue_table.itemSelectionChanged.connect(self._sync_gm_queue_inline_actions)
        self._gm_team_filter = QComboBox()
        self._gm_team_filter.currentIndexChanged.connect(self._apply_gm_queue_filters)
        self._gm_queue_filter = QComboBox()
        self._gm_queue_filter.addItem("All Queues", "")
        self._gm_queue_filter.addItem("Arbitration", "arbitration")
        self._gm_queue_filter.addItem("Free Agency", "free_agency")
        self._gm_queue_filter.currentIndexChanged.connect(self._apply_gm_queue_filters)
        self._gm_status_filter = QComboBox()
        self._gm_status_filter.addItem("All Statuses", "")
        self._gm_status_filter.addItem("Pending Review", "pending_commissioner")
        self._gm_status_filter.addItem("Approved (Not Applied)", "approved_unapplied")
        self._gm_status_filter.addItem("Approved (Applied)", "approved_applied")
        self._gm_status_filter.addItem("Approved (Any)", "approved_any")
        self._gm_status_filter.addItem("Rejected", "rejected_commissioner")
        self._gm_status_filter.currentIndexChanged.connect(self._apply_gm_queue_filters)
        self._gm_search_input = QLineEdit()
        self._gm_search_input.setPlaceholderText("Search team/player/action/status...")
        self._gm_search_input.textChanged.connect(self._apply_gm_queue_filters)
        self._gm_clear_filters_button = QPushButton("Clear Filters")
        self._gm_clear_filters_button.clicked.connect(self._clear_gm_queue_filters)

        gm_tab = QWidget()
        gm_tab_layout = QVBoxLayout(gm_tab)
        gm_tab_layout.setContentsMargins(0, 0, 0, 0)
        gm_tab_layout.setSpacing(6)
        gm_filter_row = QHBoxLayout()
        gm_filter_row.addWidget(QLabel("Team"))
        gm_filter_row.addWidget(self._gm_team_filter)
        gm_filter_row.addWidget(QLabel("Queue"))
        gm_filter_row.addWidget(self._gm_queue_filter)
        gm_filter_row.addWidget(QLabel("Status"))
        gm_filter_row.addWidget(self._gm_status_filter)
        gm_filter_row.addWidget(self._gm_search_input, stretch=1)
        gm_filter_row.addWidget(self._gm_clear_filters_button)
        gm_tab_layout.addLayout(gm_filter_row)
        gm_tab_layout.addWidget(self._gm_queue_table, stretch=1)
        self._tabs.addTab(gm_tab, "GM Queue")

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh)
        button_row.addWidget(self.refresh_button)

        self.run_button = QPushButton("Run Offseason Finance")
        self.run_button.setObjectName("Primary")
        self.run_button.clicked.connect(self._run_workflow_stage)
        button_row.addWidget(self.run_button)

        self.complete_stage_button = QPushButton("Complete Next Checklist Step")
        self.complete_stage_button.clicked.connect(self._complete_next_stage)
        button_row.addWidget(self.complete_stage_button)

        self.gm_queue_button = QPushButton("Open GM Finance Queue")
        self.gm_queue_button.clicked.connect(self._open_gm_finance_queue)
        button_row.addWidget(self.gm_queue_button)

        self.gm_queue_approve_button = QPushButton("Approve Selected")
        self.gm_queue_approve_button.clicked.connect(self._approve_selected_gm_queue)
        button_row.addWidget(self.gm_queue_approve_button)

        self.gm_queue_reject_button = QPushButton("Reject Selected")
        self.gm_queue_reject_button.setObjectName("Danger")
        self.gm_queue_reject_button.clicked.connect(self._reject_selected_gm_queue)
        button_row.addWidget(self.gm_queue_reject_button)

        self.gm_queue_apply_button = QPushButton("Apply Approved")
        self.gm_queue_apply_button.clicked.connect(self._apply_approved_gm_queue)
        button_row.addWidget(self.gm_queue_apply_button)

        self.free_agency_button = QPushButton("Open Free Agency Hub")
        self.free_agency_button.clicked.connect(self._open_free_agency)
        button_row.addWidget(self.free_agency_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        button_row.addWidget(self.close_button)

        root.addLayout(button_row)
        self._refresh()

    def _refresh(self) -> None:
        overview = collect_offseason_finance_overview()
        self._overview = overview
        self._checklist = get_offseason_checklist()
        self._details = get_offseason_stage_details()
        enabled = bool(overview.get("financials_enabled", False))
        preset = str(overview.get("preset", "off"))
        phase = str(overview.get("phase", "UNKNOWN"))
        ended = int(overview.get("ended_season_year", 0) or 0)
        next_year = int(overview.get("next_season_year", 0) or 0)
        completed = bool(overview.get("workflow_completed", False))
        stages = self._checklist.get("stages")
        stage_rows: list[str] = []
        if isinstance(stages, list):
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                stage_id = str(stage.get("id") or "")
                label = str(stage.get("label") or stage_id)
                required = bool(stage.get("required", False))
                done = bool(stage.get("done", False))
                if required and done:
                    status = "Done"
                elif required and not done:
                    status = "Pending"
                else:
                    status = "Skipped"
                stage_rows.append(f"- {label}: {status}")
        next_stage = str(self._checklist.get("next_stage_id") or "")

        self._summary.setText(
            "Use this workflow during offseason/preseason to finalize yearly finance transitions. "
            "It snapshots year-end finance, applies arbitration (if enabled), and resets team "
            "finance ledgers for the new season. Then complete checklist reviews in order."
        )
        lines = [
            f"Season Phase: {phase}",
            f"Financial System Enabled: {'Yes' if enabled else 'No'} (preset: {preset})",
            f"Offseason Window: {ended} -> {next_year}",
            f"Workflow Already Completed: {'Yes' if completed else 'No'}",
            f"Snapshot Exists: {'Yes' if bool(overview.get('snapshot_exists', False)) else 'No'}",
            f"Snapshot Path: {overview.get('snapshot_path', '--')}",
            "",
            "Contract / Market Summary",
            f"- Active contracts: {int(overview.get('contracts_total', 0) or 0)}",
            f"- Expiring contracts: {int(overview.get('contracts_expiring', 0) or 0)}",
            f"- Arbitration candidates: {int(overview.get('arbitration_candidates', 0) or 0)}",
            f"- Unsigned players (free agents): {int(overview.get('unsigned_players', 0) or 0)}",
        ]
        if bool(overview.get("requires_commissioner_finance_review", False)):
            lines.extend(
                [
                    "",
                    "Multi-Owner GM Queue",
                    f"- Total queued decisions: {int(overview.get('gm_queue_total', 0) or 0)}",
                    f"- Pending commissioner review: {int(overview.get('gm_queue_pending', 0) or 0)}",
                    f"- Approved not yet applied: {int(overview.get('gm_queue_approved_unapplied', 0) or 0)}",
                    f"- Applied approved decisions: {int(overview.get('gm_queue_approved_applied', 0) or 0)}",
                    f"- Rejected decisions: {int(overview.get('gm_queue_rejected', 0) or 0)}",
                ]
            )
        lines.extend(["", "Checklist"])
        lines.extend(stage_rows or ["- No checklist stages available."])
        self._status.setText("\n".join(lines))
        self._populate_review_tabs()

        can_run = bool(overview.get("can_run_now", False))
        run_reason = ""
        run_enabled = can_run and (next_stage == "run_pipeline")
        if not can_run:
            run_reason = "Workflow can only run during OFFSEASON or PRESEASON."
        elif next_stage != "run_pipeline":
            run_reason = "Pipeline already executed for this offseason year."
        self.run_button.setEnabled(run_enabled)
        self.run_button.setToolTip(run_reason)

        stage_reason = ""
        stage_enabled = can_run and (next_stage not in {"", "run_pipeline"})
        if not can_run:
            stage_reason = "Checklist can only be updated during OFFSEASON or PRESEASON."
        elif next_stage in {"", "run_pipeline"}:
            stage_reason = (
                "Run pipeline first."
                if next_stage == "run_pipeline"
                else "All checklist stages are complete."
            )
        self.complete_stage_button.setEnabled(stage_enabled)
        if stage_enabled:
            action_label = next(
                (
                    str(stage.get("action_label"))
                    for stage in stages
                    if isinstance(stage, dict) and str(stage.get("id") or "") == next_stage
                ),
                "Complete Next Checklist Step",
            )
            self.complete_stage_button.setText(action_label)
        else:
            self.complete_stage_button.setText("Complete Next Checklist Step")
        self.complete_stage_button.setToolTip(stage_reason)

        readiness_text = self._build_readiness_text(
            can_run=can_run,
            next_stage_id=next_stage,
            run_enabled=run_enabled,
            run_reason=run_reason,
            stage_enabled=stage_enabled,
            stage_reason=stage_reason,
            stages=stages if isinstance(stages, list) else [],
        )
        self._blockers.setText(readiness_text)
        try:
            report = build_commissioner_projection_report()
            alerts = build_finance_alerts(report=report, limit=6)
            self._alerts.setText(self._format_alerts_text(alerts))
        except Exception:
            self._alerts.setText("Finance Alerts\n- Unable to load finance alerts.")
        self._sync_gm_queue_inline_actions()

    def _run_workflow_stage(self) -> None:
        result = mark_offseason_stage("run_pipeline")
        if not bool(result.get("ok", False)):
            QMessageBox.warning(self, "Offseason Finance", str(result.get("reason", "Unable to run workflow.")))
            return
        pipeline_result = result.get("pipeline_result")
        if not isinstance(pipeline_result, dict):
            pipeline_result = {}
        arbitration = result.get("arbitration")
        team_reset = result.get("team_reset")
        if not isinstance(arbitration, dict):
            arbitration = pipeline_result.get("arbitration")
        if not isinstance(team_reset, dict):
            team_reset = pipeline_result.get("team_reset")
        awards = int(arbitration.get("awards", 0) or 0) if isinstance(arbitration, dict) else 0
        salary_delta = (
            int(arbitration.get("salary_delta", 0) or 0)
            if isinstance(arbitration, dict)
            else 0
        )
        teams_reset = (
            int(team_reset.get("teams_reset", 0) or 0)
            if isinstance(team_reset, dict)
            else 0
        )

        QMessageBox.information(
            self,
            "Offseason Finance",
            (
                f"Offseason finance pipeline completed.\n\n"
                f"Snapshot: {pipeline_result.get('snapshot_path', '--')}\n"
                f"Arbitration awards: {awards}\n"
                f"Payroll delta: ${salary_delta:,}\n"
                f"Team ledgers reset: {teams_reset}"
            ),
        )
        self._refresh()

    def _complete_next_stage(self) -> None:
        next_stage = str(self._checklist.get("next_stage_id") or "")
        if not next_stage or next_stage == "run_pipeline":
            return
        result = mark_offseason_stage(next_stage)
        if not bool(result.get("ok", False)):
            QMessageBox.warning(
                self,
                "Offseason Finance",
                str(result.get("reason", "Unable to update checklist stage.")),
            )
            return
        if next_stage == "gm_finance_review":
            apply_summary = result.get("apply_summary")
            if not isinstance(apply_summary, dict):
                apply_summary = {}
            QMessageBox.information(
                self,
                "Offseason Finance",
                (
                    "GM finance queue review stage completed.\n\n"
                    f"Applied decisions: {int(apply_summary.get('applied', 0) or 0)}\n"
                    f"Skipped decisions: {int(apply_summary.get('skipped', 0) or 0)}"
                ),
            )
            self._refresh()
            return
        QMessageBox.information(
            self,
            "Offseason Finance",
            f"Checklist stage completed: {next_stage}",
        )
        self._refresh()

    def _build_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        return table

    @staticmethod
    def _fmt_currency(value: object) -> str:
        amount = 0
        try:
            amount = int(round(float(value)))
        except Exception:
            amount = 0
        sign = "-" if amount < 0 else ""
        return f"{sign}${abs(amount):,}"

    def _populate_review_tabs(self) -> None:
        contract_rows = self._details.get("contract_expirations")
        contracts = contract_rows if isinstance(contract_rows, list) else []
        self._contracts_table.setRowCount(len(contracts))
        for row_index, row in enumerate(contracts):
            if not isinstance(row, dict):
                continue
            self._contracts_table.setItem(
                row_index, 0, QTableWidgetItem(str(row.get("player_name", "")))
            )
            self._contracts_table.setItem(
                row_index, 1, QTableWidgetItem(str(row.get("team_id", "")))
            )
            self._contracts_table.setItem(
                row_index, 2, QTableWidgetItem(str(row.get("years_left", "")))
            )
            self._contracts_table.setItem(
                row_index, 3, QTableWidgetItem(self._fmt_currency(row.get("annual_salary", 0)))
            )
            self._contracts_table.setItem(
                row_index, 4, QTableWidgetItem(str(row.get("service_time_days", "")))
            )
            self._contracts_table.setItem(
                row_index,
                5,
                QTableWidgetItem("Yes" if bool(row.get("arb_eligible", False)) else "No"),
            )
        self._tabs.setTabText(0, f"Contract Expirations ({len(contracts)})")

        arbitration_rows = self._details.get("arbitration_details")
        arbitration = arbitration_rows if isinstance(arbitration_rows, list) else []
        self._arbitration_table.setRowCount(len(arbitration))
        for row_index, row in enumerate(arbitration):
            if not isinstance(row, dict):
                continue
            self._arbitration_table.setItem(
                row_index, 0, QTableWidgetItem(str(row.get("player_name", "")))
            )
            self._arbitration_table.setItem(
                row_index, 1, QTableWidgetItem(str(row.get("team_id", "")))
            )
            self._arbitration_table.setItem(
                row_index, 2, QTableWidgetItem(self._fmt_currency(row.get("old_salary", 0)))
            )
            self._arbitration_table.setItem(
                row_index, 3, QTableWidgetItem(self._fmt_currency(row.get("new_salary", 0)))
            )
            self._arbitration_table.setItem(
                row_index, 4, QTableWidgetItem(self._fmt_currency(row.get("delta", 0)))
            )
        self._tabs.setTabText(1, f"Arbitration Details ({len(arbitration)})")

        budget_rows = self._details.get("budget_deltas")
        budgets = budget_rows if isinstance(budget_rows, list) else []
        self._budget_table.setRowCount(len(budgets))
        for row_index, row in enumerate(budgets):
            if not isinstance(row, dict):
                continue
            self._budget_table.setItem(
                row_index, 0, QTableWidgetItem(str(row.get("team_id", "")))
            )
            self._budget_table.setItem(
                row_index, 1, QTableWidgetItem(self._fmt_currency(row.get("previous_total", 0)))
            )
            self._budget_table.setItem(
                row_index, 2, QTableWidgetItem(self._fmt_currency(row.get("current_total", 0)))
            )
            self._budget_table.setItem(
                row_index, 3, QTableWidgetItem(self._fmt_currency(row.get("delta", 0)))
            )
            self._budget_table.setItem(
                row_index, 4, QTableWidgetItem(self._fmt_currency(row.get("training_delta", 0)))
            )
            self._budget_table.setItem(
                row_index, 5, QTableWidgetItem(self._fmt_currency(row.get("scouting_delta", 0)))
            )
            self._budget_table.setItem(
                row_index, 6, QTableWidgetItem(self._fmt_currency(row.get("development_delta", 0)))
            )
            self._budget_table.setItem(
                row_index, 7, QTableWidgetItem(self._fmt_currency(row.get("facilities_delta", 0)))
            )
        self._tabs.setTabText(2, f"Budget Deltas ({len(budgets)})")

        gm_queue_rows = self._details.get("gm_finance_queue")
        gm_rows = gm_queue_rows if isinstance(gm_queue_rows, list) else []
        self._gm_queue_rows = [
            row for row in gm_rows if isinstance(row, dict)
        ]
        self._refresh_gm_team_filter_options()
        self._apply_gm_queue_filters()

    def _selected_gm_queue_row(self) -> dict[str, object] | None:
        row_index = self._gm_queue_table.currentRow()
        if row_index < 0 or row_index >= len(self._gm_queue_visible_rows):
            return None
        row = self._gm_queue_visible_rows[row_index]
        if not isinstance(row, dict):
            return None
        return row

    def _clear_gm_queue_filters(self) -> None:
        self._gm_team_filter.setCurrentIndex(0)
        self._gm_queue_filter.setCurrentIndex(0)
        self._gm_status_filter.setCurrentIndex(0)
        self._gm_search_input.clear()

    def _refresh_gm_team_filter_options(self) -> None:
        current_value = str(self._gm_team_filter.currentData() or "")
        teams = sorted(
            {
                str(row.get("team_id") or "").strip()
                for row in self._gm_queue_rows
                if str(row.get("team_id") or "").strip()
            }
        )
        self._gm_team_filter.blockSignals(True)
        self._gm_team_filter.clear()
        self._gm_team_filter.addItem("All Teams", "")
        selected_index = 0
        for idx, team_id in enumerate(teams, start=1):
            self._gm_team_filter.addItem(team_id, team_id)
            if team_id == current_value:
                selected_index = idx
        self._gm_team_filter.setCurrentIndex(selected_index)
        self._gm_team_filter.blockSignals(False)

    def _apply_gm_queue_filters(self) -> None:
        team_id = str(self._gm_team_filter.currentData() or "")
        queue_type = str(self._gm_queue_filter.currentData() or "")
        status_filter = str(self._gm_status_filter.currentData() or "")
        query = self._gm_search_input.text()
        visible_rows = _filter_gm_queue_rows(
            self._gm_queue_rows,
            team_id=team_id,
            queue_type=queue_type,
            status_filter=status_filter,
            query=query,
        )
        self._gm_queue_visible_rows = visible_rows
        self._gm_queue_table.setRowCount(len(visible_rows))
        for row_index, row in enumerate(visible_rows):
            self._gm_queue_table.setItem(
                row_index, 0, QTableWidgetItem(str(row.get("team_id", "")))
            )
            self._gm_queue_table.setItem(
                row_index, 1, QTableWidgetItem(str(row.get("queue_type", "")))
            )
            self._gm_queue_table.setItem(
                row_index, 2, QTableWidgetItem(str(row.get("item_id", "")))
            )
            self._gm_queue_table.setItem(
                row_index, 3, QTableWidgetItem(str(row.get("action", "")))
            )
            self._gm_queue_table.setItem(
                row_index, 4, QTableWidgetItem(str(row.get("review_status", "")))
            )
            self._gm_queue_table.setItem(
                row_index,
                5,
                QTableWidgetItem("Yes" if bool(row.get("applied", False)) else "No"),
            )
            self._gm_queue_table.setItem(
                row_index, 6, QTableWidgetItem(str(row.get("updated_at", "")))
            )
        total_count = len(self._gm_queue_rows)
        self._tabs.setTabText(3, f"GM Queue ({len(visible_rows)}/{total_count})")
        self._sync_gm_queue_inline_actions()

    def _sync_gm_queue_inline_actions(self) -> None:
        selected = self._selected_gm_queue_row()
        selected_status = (
            str(selected.get("review_status") or "").strip()
            if isinstance(selected, dict)
            else ""
        )
        state = _gm_inline_action_state(
            self._overview,
            selected_status=selected_status,
        )
        self.gm_queue_button.setEnabled(bool(state.get("queue_enabled")))
        self.gm_queue_button.setToolTip(str(state.get("queue_hint") or ""))
        self.gm_queue_approve_button.setEnabled(bool(state.get("approve_enabled")))
        self.gm_queue_approve_button.setToolTip(str(state.get("approve_hint") or ""))
        self.gm_queue_reject_button.setEnabled(bool(state.get("reject_enabled")))
        self.gm_queue_reject_button.setToolTip(str(state.get("reject_hint") or ""))
        self.gm_queue_apply_button.setEnabled(bool(state.get("apply_enabled")))
        self.gm_queue_apply_button.setToolTip(str(state.get("apply_hint") or ""))

    @staticmethod
    def _build_readiness_text(
        *,
        can_run: bool,
        next_stage_id: str,
        run_enabled: bool,
        run_reason: str,
        stage_enabled: bool,
        stage_reason: str,
        stages: list[dict],
    ) -> str:
        stage_label = "None"
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            if str(stage.get("id") or "") != next_stage_id:
                continue
            stage_label = str(stage.get("label") or next_stage_id)
            break

        lines = ["Action Readiness"]
        lines.append(f"- Next required stage: {stage_label}")

        if run_enabled:
            lines.append("- Pipeline action: Ready")
        else:
            reason = run_reason or "Pipeline already completed or not required."
            lines.append(f"- Pipeline action: Blocked ({reason})")

        if stage_enabled:
            lines.append("- Checklist action: Ready")
        else:
            if not can_run:
                reason = stage_reason or "Checklist updates are outside offseason/preseason."
            elif next_stage_id in {"", None}:
                reason = "All required offseason finance checklist steps are complete."
            elif next_stage_id == "run_pipeline":
                reason = "Run the offseason finance pipeline before stage reviews."
            else:
                reason = stage_reason or f"Complete prerequisite stage: {stage_label}."
            lines.append(f"- Checklist action: Blocked ({reason})")
        return "\n".join(lines)

    @staticmethod
    def _format_alerts_text(alerts: list[dict[str, str]]) -> str:
        if not alerts:
            return "Finance Alerts\n- No immediate cash, payroll, or deadline alerts."
        lines = ["Finance Alerts"]
        for row in alerts[:5]:
            severity = str(row.get("severity") or "info").strip().upper()
            title = str(row.get("title") or "").strip()
            message = str(row.get("message") or "").strip()
            next_step = str(row.get("next_step") or "").strip()
            lines.append(f"- [{severity}] {title}: {message} Next: {next_step}")
        return "\n".join(lines)

    def _open_free_agency(self) -> None:
        callback = getattr(self.parent(), "open_free_agency", None)
        if callable(callback):
            callback()
            return
        try:
            from ui.free_agency_window import FreeAgencyWindow

            win = FreeAgencyWindow(self)
            win.show()
        except Exception:
            QMessageBox.warning(self, "Free Agency", "Unable to open Free Agency Hub.")

    def _open_gm_finance_queue(self) -> None:
        callback = getattr(self.parent(), "open_gm_finance_queue_review", None)
        if callable(callback):
            callback()
            self._refresh()
            return
        try:
            from ui.gm_finance_queue_dialog import GmFinanceQueueDialog

            dialog = GmFinanceQueueDialog(self)
            dialog.exec()
            self._refresh()
        except Exception:
            QMessageBox.warning(self, "GM Finance Queue", "Unable to open GM Finance Queue.")

    def _approve_selected_gm_queue(self) -> None:
        row = self._selected_gm_queue_row()
        if row is None:
            QMessageBox.information(self, "GM Finance Queue", "Select a GM queue row first.")
            return
        status = str(row.get("review_status") or "").strip().lower()
        if status != "pending_commissioner":
            QMessageBox.information(
                self,
                "GM Finance Queue",
                "Only pending commissioner decisions can be approved.",
            )
            return
        updated = set_queue_review_status(
            str(row.get("team_id") or ""),
            queue_type=str(row.get("queue_type") or ""),
            item_id=str(row.get("item_id") or ""),
            review_status="approved_commissioner",
            notes="Approved from offseason workflow",
        )
        if updated is None:
            QMessageBox.warning(
                self,
                "GM Finance Queue",
                "Unable to approve selected decision.",
            )
            return
        self._refresh()

    def _reject_selected_gm_queue(self) -> None:
        row = self._selected_gm_queue_row()
        if row is None:
            QMessageBox.information(self, "GM Finance Queue", "Select a GM queue row first.")
            return
        status = str(row.get("review_status") or "").strip().lower()
        if status != "pending_commissioner":
            QMessageBox.information(
                self,
                "GM Finance Queue",
                "Only pending commissioner decisions can be rejected.",
            )
            return
        updated = set_queue_review_status(
            str(row.get("team_id") or ""),
            queue_type=str(row.get("queue_type") or ""),
            item_id=str(row.get("item_id") or ""),
            review_status="rejected_commissioner",
            notes="Rejected from offseason workflow",
        )
        if updated is None:
            QMessageBox.warning(
                self,
                "GM Finance Queue",
                "Unable to reject selected decision.",
            )
            return
        self._refresh()

    def _apply_approved_gm_queue(self) -> None:
        summary = apply_approved_queue_decisions()
        applied = int(summary.get("applied", 0) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        QMessageBox.information(
            self,
            "GM Finance Queue",
            f"Applied approved GM decisions: {applied}\nSkipped: {skipped}",
        )
        self._refresh()


__all__ = [
    "OffseasonFinanceDialog",
    "_format_gm_queue_hint",
    "_gm_inline_action_state",
    "_filter_gm_queue_rows",
]
