from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import (
        QDialog,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - fallback for lightweight test stubs
    class _QtDummy:
        def __init__(self, *_, **__):
            pass

        def __getattr__(self, _name):
            return self

        def addWidget(self, *_):
            pass

        def addLayout(self, *_):
            pass

        def addStretch(self, *_):
            pass

        def setLayout(self, *_):
            pass

        def setWidget(self, *_):
            pass

        def setWidgetResizable(self, *_):
            pass

        def setText(self, *_):
            pass

    class QDialog(_QtDummy):
        pass

    class QGroupBox(_QtDummy):
        pass

    class QHBoxLayout(_QtDummy):
        pass

    class QLabel(_QtDummy):
        pass

    class QPushButton(_QtDummy):
        pass

    class QScrollArea(_QtDummy):
        pass

    class QVBoxLayout(_QtDummy):
        pass

    class QWidget(_QtDummy):
        pass

    class QTimer:
        @staticmethod
        def singleShot(_msec, callback):
            if callback is not None:
                callback()

from services.league_command_center import build_league_command_center_snapshot
from services.unified_data_service import get_unified_data_service
from utils.path_utils import get_data_dir


class LeagueCommandCenterWindow(QDialog):
    """Read-only shell for league command center cards."""

    _REFRESH_TOPICS = (
        "players.updated",
        "players.invalidated",
        "rosters.updated",
        "rosters.invalidated",
        "transactions.updated",
        "transactions.invalidated",
        "standings.updated",
        "standings.invalidated",
        "change_requests.updated",
        "change_requests.invalidated",
    )
    _ACTION_HANDLER_CANDIDATES: dict[str, tuple[str, ...]] = {
        "Open Injury Center": ("open_team_injury_center", "open_injury_center"),
        "Review Pending Trades": ("open_trade_review", "open_trade_dialog"),
        "Review Change Requests": (
            "open_change_requests_window",
            "open_change_request_export_dialog",
        ),
        "Review GM Finance Queue": ("open_gm_finance_queue_review",),
        "Open Team Roster": ("open_roster_page", "open_team_dashboard"),
        "Run Auto-Reassign": ("open_reassign_players_dialog", "auto_reassign_rosters"),
        "Open Season Progress": ("open_season_progress_window", "open_season_progress"),
        "Open Draft Console": ("open_draft_console",),
        "Open Finance Hub": ("open_finance_hub", "open_finance_snapshot"),
        "Open Finance Settings": ("open_financial_settings", "open_finance_hub"),
        "Open Offseason Finance Workflow": (
            "open_offseason_finance_workflow",
            "open_finance_hub",
        ),
    }

    def __init__(
        self,
        parent=None,
        *,
        data_dir: Path | str | None = None,
        league_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
        self._league_id = str(league_id or "").strip() or None
        self._service = get_unified_data_service()
        self._action_target = parent
        self._event_unsubscribes: list[callable] = []
        self._snapshot_payload: dict[str, Any] = {}
        self._card_states: list[dict[str, Any]] = []

        self.setWindowTitle("League Command Center")
        self._safe_ui_call(self, "setMinimumSize", 980, 720)
        self._safe_ui_call(self, "setGeometry", 100, 100, 1120, 800)

        root = QVBoxLayout(self)
        self._safe_ui_call(root, "setContentsMargins", 12, 12, 12, 12)
        self._safe_ui_call(root, "setSpacing", 10)

        status_group = QGroupBox("Overview")
        status_layout = QVBoxLayout()
        self.overview_label = QLabel("Loading command center snapshot...")
        self._safe_ui_call(self.overview_label, "setObjectName", "StatusLabel")
        self._safe_ui_call(self.overview_label, "setWordWrap", True)
        status_layout.addWidget(self.overview_label)
        self.generated_label = QLabel("Generated: --")
        self._safe_ui_call(self.generated_label, "setWordWrap", True)
        status_layout.addWidget(self.generated_label)
        status_group.setLayout(status_layout)
        root.addWidget(status_group)

        action_group = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        self._safe_ui_call(action_layout, "setSpacing", 8)
        self.refresh_button = QPushButton("Refresh")
        self._safe_ui_call(self.refresh_button, "setObjectName", "Primary")
        self.refresh_button.clicked.connect(self._refresh_snapshot)
        action_layout.addWidget(self.refresh_button)
        self.last_updated_label = QLabel("Last updated: --")
        action_layout.addWidget(self.last_updated_label)
        action_layout.addStretch(1)
        action_group.setLayout(action_layout)
        root.addWidget(action_group)

        self.cards_scroll = QScrollArea()
        self._safe_ui_call(self.cards_scroll, "setWidgetResizable", True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self._safe_ui_call(self.cards_layout, "setContentsMargins", 0, 0, 0, 0)
        self._safe_ui_call(self.cards_layout, "setSpacing", 8)
        self._safe_ui_call(self.cards_scroll, "setWidget", self.cards_container)
        root.addWidget(self.cards_scroll)

        self._register_event_listeners()
        self._refresh_snapshot()

    def _register_event_listeners(self) -> None:
        bus = getattr(self._service, "events", None)
        if bus is None:
            return

        def _schedule_refresh(_payload=None) -> None:
            self._queue_refresh()

        for topic in self._REFRESH_TOPICS:
            try:
                self._event_unsubscribes.append(bus.subscribe(topic, _schedule_refresh))
            except Exception:
                pass

    def _queue_refresh(self) -> None:
        single_shot = getattr(QTimer, "singleShot", None)
        if callable(single_shot):
            single_shot(0, self._refresh_snapshot)
            return
        self._refresh_snapshot()

    def _refresh_snapshot(self) -> None:
        try:
            payload = build_league_command_center_snapshot(
                data_dir=self._data_dir,
                league_id=self._league_id,
            )
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        self._snapshot_payload = payload
        self._render_overview(payload)
        self._render_cards(payload.get("cards", []))

    def _render_overview(self, payload: Mapping[str, Any]) -> None:
        league_id = str(payload.get("league_id") or "league")
        phase = str(payload.get("phase") or "UNKNOWN")
        sim_date = str(payload.get("sim_date") or "--")
        overview = payload.get("overview") if isinstance(payload.get("overview"), Mapping) else {}
        critical = int(overview.get("critical_cards", 0) or 0)
        warning = int(overview.get("warning_cards", 0) or 0)
        total = int(overview.get("total_attention_items", 0) or 0)
        self.overview_label.setText(
            f"League {league_id} | Phase: {phase} | Sim Date: {sim_date} | "
            f"Attention Items: {total} ({critical} critical, {warning} warning)."
        )
        generated = str(payload.get("generated_at_utc") or "--")
        self.generated_label.setText(f"Generated: {generated}")
        self.last_updated_label.setText(
            f"Last updated: {datetime.now().strftime('%H:%M:%S')}"
        )

    def _render_cards(self, cards_payload: Any) -> None:
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self._safe_ui_call(self.cards_layout, "setContentsMargins", 0, 0, 0, 0)
        self._safe_ui_call(self.cards_layout, "setSpacing", 8)
        self._safe_ui_call(self.cards_scroll, "setWidget", self.cards_container)
        self._card_states = []

        cards = cards_payload if isinstance(cards_payload, list) else []
        if not cards:
            self.cards_layout.addWidget(QLabel("No command center cards available."))
            self.cards_layout.addStretch(1)
            return

        for card in cards:
            if not isinstance(card, Mapping):
                continue
            self._card_states.append(
                {
                    "card_id": str(card.get("card_id") or ""),
                    "severity": str(card.get("severity") or ""),
                    "count": int(card.get("count", 0) or 0),
                }
            )
            self.cards_layout.addWidget(self._build_card_widget(card))
        self.cards_layout.addStretch(1)

    def _build_card_widget(self, card: Mapping[str, Any]) -> QWidget:
        title = str(card.get("title") or card.get("card_id") or "Card")
        group = QGroupBox(title)
        layout = QVBoxLayout()
        card_id = str(card.get("card_id") or "")
        summary = str(card.get("summary") or "")
        count = int(card.get("count", 0) or 0)
        severity = str(card.get("severity") or "info").lower()
        tone = QLabel(f"Severity: {severity.upper()} | Count: {count}")
        self._safe_ui_call(tone, "setWordWrap", True)
        self._safe_ui_call(tone, "setStyleSheet", self._severity_style(severity))
        layout.addWidget(tone)
        summary_label = QLabel(summary)
        self._safe_ui_call(summary_label, "setWordWrap", True)
        layout.addWidget(summary_label)

        item_lines = self._format_items(card.get("items"), card_id=card_id)
        items_label = QLabel(item_lines)
        self._safe_ui_call(items_label, "setWordWrap", True)
        layout.addWidget(items_label)

        actions = card.get("actions") if isinstance(card.get("actions"), list) else []
        if isinstance(actions, list) and actions:
            actions_group = QGroupBox("Suggested Actions")
            actions_layout = QHBoxLayout()
            self._safe_ui_call(actions_layout, "setSpacing", 6)
            for action_label in actions:
                label = str(action_label or "").strip()
                if not label:
                    continue
                button = QPushButton(label)
                handler = self._resolve_action_handler(label)
                if callable(handler):
                    try:
                        button.clicked.connect(handler)
                    except Exception:
                        pass
                else:
                    self._safe_ui_call(button, "setEnabled", False)
                actions_layout.addWidget(button)
            actions_layout.addStretch(1)
            actions_group.setLayout(actions_layout)
            layout.addWidget(actions_group)
        group.setLayout(layout)
        return group

    @classmethod
    def _format_items(
        cls,
        payload: Any,
        *,
        card_id: str = "",
        max_items: int | None = None,
    ) -> str:
        rows = payload if isinstance(payload, list) else []
        if not rows:
            return "Details: --"
        if max_items is None:
            if card_id in {
                "injuries",
                "pending_approvals",
                "roster_conflicts",
                "deadlines",
                "finance_risks",
            }:
                max_items = 8
            else:
                max_items = 5
        lines = []
        for row in rows[:max_items]:
            if isinstance(row, Mapping):
                lines.append(f"- {cls._format_item_row(row)}")
        if not lines:
            return "Details: --"
        hidden = len(rows) - len(lines)
        if hidden > 0:
            lines.append(f"- +{hidden} more item(s)")
        return "Details:\n" + "\n".join(lines)

    @staticmethod
    def _format_item_row(row: Mapping[str, Any]) -> str:
        if "label" in row and "status" in row and (
            "date" in row or "next_stage" in row or "days_remaining" in row
        ):
            label = str(row.get("label") or "").strip() or "Item"
            status = str(row.get("status") or "unknown").strip().replace("_", " ")
            parts = [f"{label}: {status}"]

            date_value = str(row.get("date") or "").strip()
            if date_value:
                parts.append(f"date {date_value}")

            days_remaining = row.get("days_remaining")
            if days_remaining is not None:
                day_count = LeagueCommandCenterWindow._safe_int(days_remaining)
                if day_count == 0:
                    parts.append("today")
                elif day_count > 0:
                    parts.append(f"{day_count}d remaining")
                else:
                    parts.append(f"{abs(day_count)}d past")

            next_stage = str(row.get("next_stage") or "").strip()
            if next_stage:
                parts.append(f"next: {next_stage}")

            return " | ".join(parts)

        if "label" in row and "count" in row:
            return f"{row.get('label')}: {row.get('count')}"
        if "team_id" in row and "injury_count" in row:
            return f"{row.get('team_id')}: {row.get('injury_count')} injuries"
        if "team_id" in row and "missing_positions" in row:
            missing = row.get("missing_positions") or []
            if isinstance(missing, list):
                joined = ", ".join(str(token) for token in missing)
            else:
                joined = str(missing)
            return f"{row.get('team_id')}: missing {joined or '--'}"
        if "title" in row and "severity" in row and (
            "message" in row or "next_step" in row
        ):
            title = str(row.get("title") or "").strip() or "Finance Alert"
            severity = str(row.get("severity") or "info").upper()
            message = str(row.get("message") or "").strip()
            next_step = str(row.get("next_step") or "").strip()
            segments = [f"[{severity}] {title}"]
            if message:
                segments.append(message)
            if next_step:
                segments.append(f"Next: {next_step}")
            return " | ".join(segments)
        if "title" in row and "severity" in row:
            return f"[{str(row.get('severity')).upper()}] {row.get('title')}"
        compact = []
        for key, value in row.items():
            compact.append(f"{key}={value}")
            if len(compact) >= 4:
                break
        return ", ".join(compact) if compact else "--"

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(round(float(value)))
        except Exception:
            return 0

    @staticmethod
    def _severity_style(severity: str) -> str:
        if severity == "critical":
            return "color: #c92a2a; font-weight: 700;"
        if severity == "warning":
            return "color: #b36b18; font-weight: 700;"
        if severity == "success":
            return "color: #2f9e44; font-weight: 700;"
        return "color: #6c757d; font-weight: 600;"

    def _resolve_action_handler(self, action_label: str):
        label = str(action_label or "").strip()
        if not label:
            return None
        candidates = self._ACTION_HANDLER_CANDIDATES.get(label, ())
        targets = [self._action_target, self]
        for target in targets:
            if target is None:
                continue
            for method_name in candidates:
                handler = getattr(target, method_name, None)
                if callable(handler):
                    return handler
        return None

    def closeEvent(self, event):  # pragma: no cover - GUI wiring
        for unsubscribe in getattr(self, "_event_unsubscribes", []):
            try:
                unsubscribe()
            except Exception:
                pass
        self._event_unsubscribes = []
        try:
            super().closeEvent(event)
        except Exception:
            pass

    @staticmethod
    def _safe_ui_call(target, method: str, *args) -> None:
        fn = getattr(target, method, None)
        if callable(fn):
            try:
                fn(*args)
            except Exception:
                return


__all__ = ["LeagueCommandCenterWindow"]
