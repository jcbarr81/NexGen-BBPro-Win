"""Admin home page widget for the modular dashboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ...components import Card, build_metric_row, section_title
from .base import DashboardPage


def _build_overview_values(metrics: dict[str, object] | None) -> dict[str, str]:
    return {
        "Pending Trades": (str(metrics.get("pending_trades")) if metrics else "--"),
        "Pending GM Queue": (
            str(metrics.get("gm_queue_pending"))
            if metrics
            else "--"
        ),
        "Teams": (str(metrics.get("teams")) if metrics else "--"),
        "Players": (str(metrics.get("players")) if metrics else "--"),
        "Season Phase": (str(metrics.get("season_phase")) if metrics else "--"),
    }


def _format_gm_queue_status(metrics: dict[str, object] | None) -> str:
    if not metrics:
        return "GM Finance Queue: --"
    if not bool(metrics.get("gm_queue_required", False)):
        return "GM Finance Queue: Single-player mode (auto-applies recommended owner actions)."
    pending = int(metrics.get("gm_queue_pending", 0) or 0)
    unapplied = int(metrics.get("gm_queue_approved_unapplied", 0) or 0)
    return (
        "GM Finance Queue: "
        f"pending review {pending}, approved-not-applied {unapplied}."
    )


class AdminHomePage(DashboardPage):
    """Landing view with league overview and priority actions."""

    def __init__(self, dashboard, parent=None):
        super().__init__(parent)
        self._dashboard = dashboard

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        # Overview metrics ------------------------------------------------
        self.metrics_card = Card()
        self.metrics_card.layout().addWidget(section_title("League Overview"))

        self._metric_values = {
            "Pending Trades": "--",
            "Pending GM Queue": "--",
            "Teams": "--",
            "Players": "--",
            "Season Phase": "--",
        }
        self.metrics_row = build_metric_row(list(self._metric_values.items()), columns=5)
        self.metrics_card.layout().addWidget(self.metrics_row)
        self.metrics_card.layout().addStretch()
        layout.addWidget(self.metrics_card)

        # Key dates/status ------------------------------------------------
        status_card = Card()
        status_card.layout().addWidget(section_title("Calendar & Status"))
        self.next_event_label = QLabel("Draft Day: --")
        self.next_event_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        status_card.layout().addWidget(self.next_event_label)
        status_card.layout().addStretch()
        layout.addWidget(status_card)

        # Shortcuts -------------------------------------------------------
        actions = Card()
        actions.layout().addWidget(section_title("Priority Queues"))

        review_btn = QPushButton("Review Trades", objectName="Primary")
        review_btn.setToolTip("Open pending trade approvals")
        review_btn.clicked.connect(self._dashboard.open_trade_review)
        actions.layout().addWidget(review_btn)

        change_requests_btn = QPushButton("Review Change Requests", objectName="Primary")
        change_requests_btn.setToolTip("Open owner-submitted change requests")
        change_requests_btn.clicked.connect(self._dashboard.open_change_requests_window)
        actions.layout().addWidget(change_requests_btn)

        gm_queue_btn = QPushButton("Review GM Finance Queue", objectName="Primary")
        gm_queue_btn.setToolTip("Open commissioner review for owner GM finance decisions")
        gm_queue_btn.clicked.connect(self._dashboard.open_gm_finance_queue_review)
        actions.layout().addWidget(gm_queue_btn)

        self.gm_queue_status_label = QLabel("GM Finance Queue: --")
        self.gm_queue_status_label.setWordWrap(True)
        self.gm_queue_status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        actions.layout().addWidget(self.gm_queue_status_label)

        season_btn = QPushButton("Open Season Hub", objectName="Primary")
        season_btn.setToolTip("Go to season simulation and schedule controls")
        season_btn.clicked.connect(lambda: self._dashboard._go("season"))
        actions.layout().addWidget(season_btn)

        draft_btn = QPushButton("Open Draft Hub", objectName="Primary")
        draft_btn.setToolTip("Go to draft controls and draft settings")
        draft_btn.clicked.connect(lambda: self._dashboard._go("draft"))
        actions.layout().addWidget(draft_btn)

        actions.layout().addStretch()
        layout.addWidget(actions)

        layout.addStretch()

    def on_attached(self) -> None:
        """Refresh overview metrics once the shared context is available."""
        self.refresh()

    def refresh(self) -> None:
        """Refresh metrics and key dates from the dashboard helper."""
        try:
            metrics = self._dashboard.get_admin_metrics()
        except Exception:
            metrics = None

        values = _build_overview_values(metrics)
        self.metrics_card.layout().removeWidget(self.metrics_row)
        self.metrics_row.setParent(None)
        self.metrics_row = build_metric_row(list(values.items()), columns=5)
        self.metrics_card.layout().insertWidget(1, self.metrics_row)
        self.gm_queue_status_label.setText(_format_gm_queue_status(metrics))

        if metrics:
            draft_day = metrics.get("draft_day") or "--"
            draft_status = metrics.get("draft_status") or "--"
            self.next_event_label.setText(f"Draft Day: {draft_day} | Status: {draft_status}")
        else:
            self.next_event_label.setText("Draft Day: --")


__all__ = [
    "AdminHomePage",
    "_build_overview_values",
    "_format_gm_queue_status",
]
