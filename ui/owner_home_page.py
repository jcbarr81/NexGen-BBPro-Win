from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional
from types import SimpleNamespace

try:
    from PyQt6.QtCore import Qt
except ImportError:  # pragma: no cover - test stubs
    Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(
            AlignCenter=0x0004,
            AlignHCenter=0x0004,
            AlignVCenter=0x0080,
            AlignLeft=0x0001,
            AlignRight=0x0002,
            AlignTop=0x0020,
            AlignBottom=0x0040,
        ),
        ToolButtonStyle=SimpleNamespace(ToolButtonTextBesideIcon=None),
        ScrollBarPolicy=SimpleNamespace(
            ScrollBarAlwaysOff=0,
            ScrollBarAsNeeded=1,
        ),
    )

try:
    from PyQt6.QtGui import QColor
except ImportError:  # pragma: no cover - test stubs
    class _GraphicDummy:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):
            def _noop(*_args, **_kwargs):
                return None

            return _noop

    QColor = _GraphicDummy
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QBoxLayout,
)

from .components import Card, section_title, build_metric_row
from .stat_helpers import format_ip


class OwnerHomePage(QWidget):
    """Landing page for the Owner Dashboard with quick metrics and actions.

    This page relies on the dashboard to provide metric data and to open
    dialogs for common actions. It keeps styling consistent using the
    shared Card and section title components and the current theme.
    """

    _BATTING_KEY_MAP = {
        "AVG Leader": "avg",
        "HR Leader": "hr",
        "RBI Leader": "rbi",
    }
    _PITCHING_KEY_MAP = {
        "Wins Leader": "wins",
        "SO Leader": "so",
        "Saves Leader": "saves",
    }

    def __init__(self, dashboard):
        super().__init__()
        self._dashboard = dashboard
        self._layout_mode: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        scroll_body = QWidget()
        scroll_layout = QVBoxLayout(scroll_body)
        scroll_layout.setContentsMargins(24, 24, 24, 24)
        scroll_layout.setSpacing(24)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._content = QWidget()
        self._content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._content.setMaximumWidth(1320)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(24)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(24)
        self._grid.setVerticalSpacing(24)
        content_layout.addLayout(self._grid)
        scroll_layout.addWidget(self._content, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._scroll.setWidget(scroll_body)
        root.addWidget(self._scroll)

        # Metrics card ----------------------------------------------------
        self.metrics_card = Card()
        self.metrics_card.setMinimumHeight(180)
        self.metrics_card.layout().addWidget(section_title("Team Snapshot"))
        self._metric_values = {
            "Record": "--",
            "Run Diff": "--",
            "Next Game": "--",
            "Next Date": "--",
            "Streak": "--",
            "Last 10": "--",
            "Injuries": "0",
            "Prob SP": "--",
        }
        self.metrics_row = build_metric_row(
            [(k, v) for k, v in self._metric_values.items()], columns=4
        )
        self.metrics_card.layout().addWidget(self.metrics_row)

        self._leader_meta: dict[str, dict[str, dict[str, object]]] = {
            "batting": {},
            "pitching": {},
        }

        self._batting_leaders = self._format_batting_leaders(None)
        self.batting_row = build_metric_row(
            self._batting_leaders,
            columns=3,
            variant="leader",
        )
        self.metrics_card.layout().addWidget(self.batting_row)

        self._pitching_leaders = self._format_pitching_leaders(None)
        self.pitching_row = build_metric_row(
            self._pitching_leaders,
            columns=3,
            variant="leader",
        )
        self.metrics_card.layout().addWidget(self.pitching_row)

        # Readiness & matchup card ---------------------------------
        self.readiness_card = Card()
        self.readiness_card.setMinimumHeight(180)
        self.readiness_card.layout().addWidget(section_title("Readiness & Matchup"))
        readiness_row = QHBoxLayout()
        readiness_row.setSpacing(16)
        self.bullpen_widget = BullpenReadinessWidget()
        self.matchup_widget = MatchupScoutWidget()
        self.bullpen_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.matchup_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        readiness_row.addWidget(self.bullpen_widget, 1)
        readiness_row.addWidget(self.matchup_widget, 1)
        self.readiness_card.layout().addLayout(readiness_row)

        # Quick actions card ---------------------------------------------
        self.quick_actions_card = Card()
        self.quick_actions_card.setMinimumHeight(180)
        self.quick_actions_card.layout().addWidget(section_title("Quick Actions"))
        self.draft_notice = QWidget()
        draft_layout = QHBoxLayout(self.draft_notice)
        draft_layout.setContentsMargins(12, 10, 12, 10)
        draft_layout.setSpacing(12)
        self.draft_notice_label = QLabel("Draft is ready.")
        self.draft_notice_label.setWordWrap(True)
        self.draft_notice_label.setStyleSheet(
            "font-weight: 700; color: #c3521f;"
        )
        self.draft_notice_button = QPushButton(
            "Open Draft Console", objectName="Primary"
        )
        self.draft_notice_button.clicked.connect(
            self._dashboard.open_draft_console
        )
        draft_layout.addWidget(self.draft_notice_label, 1)
        draft_layout.addWidget(
            self.draft_notice_button, alignment=Qt.AlignmentFlag.AlignRight
        )
        self.draft_notice.setStyleSheet(
            "background-color: rgba(195, 82, 31, 0.12); "
            "border: 1px solid #c3521f; border-radius: 10px;"
        )
        self.draft_notice.setVisible(False)
        self.quick_actions_card.layout().addWidget(self.draft_notice)
        self.quick_buttons: list[QPushButton] = []

        button_groups = [
            (
                "Roster Setup",
                [
                    ("Lineups", self._dashboard.open_lineup_editor),
                    ("Depth Chart", self._dashboard.open_depth_chart_dialog),
                    ("Training Focus", self._dashboard.open_training_focus_dialog),
                    ("Pitching Staff", self._dashboard.open_pitching_editor),
                    ("Reassign Players", self._dashboard.open_reassign_players_dialog),
                ],
            ),
            (
                "Club Operations",
                [
                    ("Recent Transactions", self._dashboard.open_transactions_page),
                    ("Team Settings", self._dashboard.open_team_settings_dialog),
                    ("Full Roster", self._dashboard.open_player_browser_dialog),
                    ("Team Injuries", self._dashboard.open_team_injury_center),
                ],
            ),
            (
                "League Intel",
                [
                    ("Team Stats", lambda: self._dashboard.open_team_stats_window("team")),
                    ("League Leaders", self._dashboard.open_league_leaders_window),
                    ("League Standings", self._dashboard.open_standings_window),
                    ("Team Schedule", self._dashboard.open_team_schedule_window),
                    ("Draft Console", self._dashboard.open_draft_console),
                    ("Playoffs Viewer", self._dashboard.open_playoffs_window),
                ],
            ),
        ]

        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(6, 12, 6, 12)
        actions_layout.setSpacing(24)
        self.quick_actions_layout = actions_layout
        self.quick_action_columns: list[QVBoxLayout] = []

        for title, items in button_groups:
            column = QVBoxLayout()
            column.setSpacing(12)
            label = QLabel(title)
            label.setObjectName("QuickActionsGroupTitle")
            label.setStyleSheet("font-weight:600; color:#d4a76a; margin-bottom:4px;")
            column.addWidget(label)
            for text, callback in items:
                btn = self._make_action_button(text, callback, compact=True)
                column.addWidget(btn)
                self.quick_buttons.append(btn)
            column.addStretch()
            actions_layout.addLayout(column)
            self.quick_action_columns.append(column)

        actions_layout.addStretch()
        self.quick_actions_card.layout().addLayout(actions_layout)

        # Performance & standings card ----------------------------------
        self.performance_card = Card()
        self.performance_card.setMinimumHeight(320)
        self.performance_card.layout().addWidget(
            section_title("Hot/Cold & Division Standings")
        )

        performance_row = QHBoxLayout()
        performance_row.setSpacing(24)

        performers_col = QVBoxLayout()
        performers_col.setSpacing(8)
        self.performers_title = QLabel("Hot/Cold Performers")
        self.performers_title.setStyleSheet("font-weight:600; color:#495057;")
        performers_col.addWidget(self.performers_title)
        self.performers_widget = HotColdWidget()
        performers_col.addWidget(self.performers_widget)

        standings_col = QVBoxLayout()
        standings_col.setSpacing(8)
        self.division_title = QLabel("Division Standings")
        self.division_title.setStyleSheet("font-weight:600; color:#495057;")
        standings_col.addWidget(self.division_title)
        self.division_widget = DivisionStandingsWidget()
        standings_col.addWidget(self.division_widget)

        performance_row.addLayout(performers_col, 1)
        performance_row.addLayout(standings_col, 1)
        self.performance_card.layout().addLayout(performance_row)

        # Recent News card ----------------------------------------------
        self.news_card = Card()
        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_row.addWidget(section_title("Recent News"))
        header_row.addStretch()
        self.news_toggle = QToolButton()
        self.news_toggle.setText("View all")
        self.news_toggle.setCheckable(True)
        self.news_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.news_toggle.clicked.connect(self._toggle_news)
        header_row.addWidget(self.news_toggle)
        self.news_card.layout().addLayout(header_row)

        self.news_preview = QLabel("No recent items.")
        self.news_preview.setWordWrap(True)
        self.news_preview.setObjectName("NewsPreview")
        self.news_card.layout().addWidget(self.news_preview)

        self.news_full = QLabel("No recent items.")
        self.news_full.setWordWrap(True)
        self.news_full.setObjectName("NewsFull")
        self.news_full.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.news_full_area = QScrollArea()
        self.news_full_area.setWidgetResizable(True)
        self.news_full_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.news_full_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.news_full_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.news_full_area.setMaximumHeight(240)
        self.news_full_area.setVisible(False)
        self.news_full_area.setWidget(self.news_full)
        self.news_card.layout().addWidget(self.news_full_area)

        self._news_lines: list[str] = []

        self._cards = [
            self.metrics_card,
            self.readiness_card,
            self.quick_actions_card,
            self.performance_card,
            self.news_card,
        ]
        self._layout_mode = None
        self._update_layout_mode()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Refresh metrics from the dashboard helpers."""
        try:
            m = self._dashboard.get_quick_metrics()
        except Exception:
            m = None

        injuries_raw = m.get("injuries") if m else 0
        try:
            injuries_count = int(injuries_raw)
        except (TypeError, ValueError):
            injuries_count = 0
        injury_entry: dict[str, object] = {
            "text": str(injuries_count),
            "highlight": injuries_count > 0,
            "tooltip": "Open Team Injury Center",
        }
        open_injuries = getattr(self._dashboard, "open_team_injury_center", None)
        if callable(open_injuries):
            injury_entry["on_click"] = open_injuries

        # Update our metric values
        new_values = {
            "Record": m.get("record", "--") if m else "--",
            "Run Diff": m.get("run_diff", "--") if m else "--",
            "Next Game": m.get("next_opponent", "--") if m else "--",
            "Next Date": m.get("next_date", "--") if m else "--",
            "Streak": m.get("streak", "--") if m else "--",
            "Last 10": m.get("last10", "--") if m else "--",
            "Injuries": injury_entry,
            "Prob SP": m.get("prob_sp", "--") if m else "--",
        }

        # Rebuild metric row content in-place
        # Remove existing metric row widget and replace
        self.metrics_card.layout().removeWidget(self.metrics_row)
        self.metrics_row.setParent(None)
        self._metric_values = new_values
        self.metrics_row = build_metric_row(
            [(k, v) for k, v in self._metric_values.items()], columns=4
        )
        self.metrics_card.layout().insertWidget(1, self.metrics_row)

        meta_candidate = m.get("leader_meta") if m else None
        batting_meta = (
            meta_candidate.get("batting") if isinstance(meta_candidate, Mapping) else {}
        )
        pitching_meta = (
            meta_candidate.get("pitching") if isinstance(meta_candidate, Mapping) else {}
        )
        self._leader_meta = {
            "batting": batting_meta if isinstance(batting_meta, Mapping) else {},
            "pitching": pitching_meta if isinstance(pitching_meta, Mapping) else {},
        }

        batting_entries = self._format_batting_leaders(
            m.get("batting_leaders") if m else None,
            self._leader_meta.get("batting"),
        )
        self._set_batting_leader_row(batting_entries)

        pitching_entries = self._format_pitching_leaders(
            m.get("pitching_leaders") if m else None,
            self._leader_meta.get("pitching"),
        )
        self._set_pitching_leader_row(pitching_entries)

        bullpen_data = m.get("bullpen", {}) if m else {}
        self.bullpen_widget.update_data(bullpen_data)
        matchup_data = m.get("matchup", {}) if m else {}
        self.matchup_widget.update_matchup(matchup_data)
        performer_data = m.get("performers", {}) if m else {}
        self.performers_widget.update_performers(performer_data)
        division_data = m.get("division_standings", {}) if m else {}
        self.division_widget.update_standings(division_data)
        window = performer_data.get("window")
        if window:
            self.performers_title.setText(
                f"Hot/Cold Performers (Last {window} Days)"
            )
        else:
            self.performers_title.setText("Hot/Cold Performers")
        division_name = division_data.get("division")
        if division_name and division_name != "--":
            self.division_title.setText(f"Division Standings - {division_name}")
        else:
            self.division_title.setText("Division Standings")

        # Update recent news
        try:
            from utils.news_logger import NEWS_FILE, sanitize_news_text
            from pathlib import Path

            p = Path(NEWS_FILE)
            if p.exists():
                lines = [
                    sanitize_news_text(line)
                    for line in p.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                # Keep a reasonable window of recent items, newest at the end
                self._news_lines = lines[-40:]
            else:
                self._news_lines = []
        except Exception:
            self._news_lines = []

        self._update_news_display()
        self._update_draft_notice()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_layout_mode()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._update_layout_mode()

    def _make_action_button(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        compact: bool = False,
    ) -> QPushButton:
        btn = QPushButton(label, objectName="Primary")
        if hasattr(btn, "setWordWrap"):
            btn.setWordWrap(True)

        if compact:
            btn.setMinimumHeight(48)
            btn.setMaximumHeight(48)
            btn.setMinimumWidth(200)
            btn.setMaximumWidth(220)
            btn.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
        else:
            btn.setMinimumHeight(64)
            hint_width = btn.sizeHint().width()
            metrics = btn.fontMetrics() if hasattr(btn, "fontMetrics") else None
            if metrics is not None:
                horizontal_advance = getattr(metrics, "horizontalAdvance", None)
                if callable(horizontal_advance):
                    text_width = horizontal_advance(label)
                else:
                    text_width = metrics.boundingRect(label).width()
            else:
                text_width = len(label) * 9
            padding = 32  # matches 16px horizontal padding in the theme
            preferred_width = max(160, hint_width, text_width + padding)
            btn.setMinimumWidth(preferred_width)
            btn.setMaximumWidth(preferred_width)
            btn.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Expanding,
            )
        btn.clicked.connect(callback)
        return btn

    def _default_batting_leaders(self) -> list[tuple[str, str]]:
        return [
            ("AVG Leader", "--"),
            ("HR Leader", "--"),
            ("RBI Leader", "--"),
        ]

    def _default_pitching_leaders(self) -> list[tuple[str, str]]:
        return [
            ("Wins Leader", "--"),
            ("SO Leader", "--"),
            ("Saves Leader", "--"),
        ]

    def _format_batting_leaders(
        self,
        leaders: Mapping[str, str] | None,
        meta: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> list[tuple[str, Any]]:
        formatted = dict(self._default_batting_leaders())
        if leaders:
            formatted["AVG Leader"] = leaders.get("avg") or formatted["AVG Leader"]
            formatted["HR Leader"] = leaders.get("hr") or formatted["HR Leader"]
            formatted["RBI Leader"] = leaders.get("rbi") or formatted["RBI Leader"]
        meta_map = meta if isinstance(meta, Mapping) else {}
        entries: list[tuple[str, Any]] = []
        for title, label in formatted.items():
            key = self._BATTING_KEY_MAP.get(title)
            info = meta_map.get(key) if isinstance(meta_map, Mapping) else None
            entries.append((title, self._player_metric_value(label, info)))
        return entries

    def _format_pitching_leaders(
        self,
        leaders: Mapping[str, str] | None,
        meta: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> list[tuple[str, Any]]:
        formatted = dict(self._default_pitching_leaders())
        if leaders:
            formatted["Wins Leader"] = leaders.get("wins") or formatted["Wins Leader"]
            formatted["SO Leader"] = leaders.get("so") or formatted["SO Leader"]
            formatted["Saves Leader"] = leaders.get("saves") or formatted["Saves Leader"]
        meta_map = meta if isinstance(meta, Mapping) else {}
        entries: list[tuple[str, Any]] = []
        for title, label in formatted.items():
            key = self._PITCHING_KEY_MAP.get(title)
            info = meta_map.get(key) if isinstance(meta_map, Mapping) else None
            entries.append((title, self._player_metric_value(label, info)))
        return entries

    def _player_metric_value(
        self,
        text: str,
        info: Mapping[str, Any] | None,
    ) -> Any:
        if not info or not isinstance(info, Mapping):
            return text
        player_id_raw = info.get("player_id")
        if not player_id_raw:
            return text
        player_id = str(player_id_raw)
        name = str(info.get("name") or text.split(" ", 1)[0])

        def _handler(pid: str = player_id) -> None:
            self._open_player_profile(pid)

        return {
            "text": text,
            "on_click": _handler,
            "tooltip": f"View {name}'s profile",
        }

    def _set_batting_leader_row(self, entries: list[tuple[str, Any]]) -> None:
        self.metrics_card.layout().removeWidget(self.batting_row)
        self.batting_row.setParent(None)
        self._batting_leaders = entries
        self.batting_row = build_metric_row(
            self._batting_leaders,
            columns=3,
            variant="leader",
        )
        self.metrics_card.layout().insertWidget(2, self.batting_row)

    def _set_pitching_leader_row(self, entries: list[tuple[str, Any]]) -> None:
        self.metrics_card.layout().removeWidget(self.pitching_row)
        self.pitching_row.setParent(None)
        self._pitching_leaders = entries
        self.pitching_row = build_metric_row(
            self._pitching_leaders,
            columns=3,
            variant="leader",
        )
        self.metrics_card.layout().insertWidget(3, self.pitching_row)

    def _open_player_profile(self, player_id: str) -> None:
        opener = getattr(self._dashboard, "open_player_profile", None)
        if callable(opener):
            try:
                opener(player_id)
            except Exception:
                pass

    def _toggle_news(self, checked: bool) -> None:
        if not self.news_toggle.isEnabled():
            self.news_toggle.setChecked(False)
            return
        self.news_full_area.setVisible(checked)
        if checked:
            try:
                self.news_full_area.verticalScrollBar().setValue(0)
            except AttributeError:
                pass
        self.news_toggle.setText("Hide full feed" if checked else "View all")

    def _update_news_display(self) -> None:
        if not self._news_lines:
            self.news_preview.setText("No recent items.")
            self.news_full.setText("No recent items.")
            self.news_toggle.setEnabled(False)
            self.news_toggle.setChecked(False)
            self.news_toggle.setText("View all")
            self.news_full_area.setVisible(False)
            return

        preview_lines = list(reversed(self._news_lines[-3:]))
        self.news_preview.setText("\n".join(preview_lines))
        self.news_full.setText("\n".join(reversed(self._news_lines)))

        has_extra = len(self._news_lines) > 3
        self.news_toggle.setEnabled(has_extra)
        if not has_extra:
            self.news_toggle.setChecked(False)
            self.news_toggle.setText("View all")
            self.news_full_area.setVisible(False)
        else:
            self.news_full_area.setVisible(self.news_toggle.isChecked())
            self.news_toggle.setText(
                "Hide full feed" if self.news_toggle.isChecked() else "View all"
            )

    def _update_draft_notice(self) -> None:
        notice = {}
        getter = getattr(self._dashboard, "get_draft_notice", None)
        if callable(getter):
            notice = getter() or {}
        visible = bool(notice.get("visible"))
        self.draft_notice.setVisible(visible)
        if not visible:
            return
        message = notice.get("message") or "Draft is ready."
        self.draft_notice_label.setText(str(message))

    def _arrange_quick_actions(self, columns: int) -> None:
        narrow = columns == 1
        try:
            direction = (
                QBoxLayout.Direction.TopToBottom
                if narrow
                else QBoxLayout.Direction.LeftToRight
            )
            self.quick_actions_layout.setDirection(direction)
        except Exception:
            pass

        for btn in self.quick_buttons:
            if narrow:
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
                btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Fixed,
                )
            else:
                btn.setMinimumWidth(200)
                btn.setMaximumWidth(220)
                btn.setSizePolicy(
                    QSizePolicy.Policy.Fixed,
                    QSizePolicy.Policy.Fixed,
                )

    def _apply_layout_mode(self, mode: str) -> None:
        if self._layout_mode == mode:
            return
        self._layout_mode = mode
        for card in self._cards:
            self._grid.removeWidget(card)

        if mode == "wide":
            self._arrange_quick_actions(columns=3)
            self._place_card(self.metrics_card, 0, 0)
            self._place_card(self.quick_actions_card, 0, 1)
            self._place_card(self.readiness_card, 1, 0)
            self._place_card(self.news_card, 1, 1)
            self._place_card(self.performance_card, 2, 0, 1, 2)
            self._grid.setColumnStretch(0, 3)
            self._grid.setColumnStretch(1, 2)
            self._grid.setColumnStretch(2, 0)
            self._grid.setRowStretch(0, 0)
            self._grid.setRowStretch(1, 0)
            self._grid.setRowStretch(2, 1)
        elif mode == "medium":
            self._arrange_quick_actions(columns=2)
            self._place_card(self.metrics_card, 0, 0)
            self._place_card(self.quick_actions_card, 0, 1)
            self._place_card(self.readiness_card, 1, 0)
            self._place_card(self.news_card, 1, 1)
            self._place_card(self.performance_card, 2, 0, 1, 2)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
            self._grid.setColumnStretch(2, 0)
            self._grid.setRowStretch(0, 0)
            self._grid.setRowStretch(1, 0)
            self._grid.setRowStretch(2, 1)
        else:
            self._arrange_quick_actions(columns=1)
            for row, card in enumerate(self._cards):
                self._place_card(card, row, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
            self._grid.setColumnStretch(2, 0)
            for idx in range(len(self._cards)):
                self._grid.setRowStretch(idx, 0)
            self._grid.setRowStretch(len(self._cards) - 1, 1)

    def _update_layout_mode(self) -> None:
        available = None
        try:
            viewport = self._scroll.viewport()
            if viewport is not None:
                available = viewport.width()
        except Exception:
            available = None
        if not available:
            try:
                available = self.width()
            except Exception:
                available = 0
        content_width = max(0, int(available) - 48)
        if content_width >= 1200:
            mode = "wide"
        elif content_width >= 960:
            mode = "medium"
        else:
            mode = "narrow"
        self._apply_layout_mode(mode)

    def _place_card(
        self,
        card: QWidget,
        row: int,
        column: int,
        row_span: int = 1,
        column_span: int = 1,
    ) -> None:
        """Insert a card into the grid with consistent alignment."""

        self._grid.addWidget(card, row, column, row_span, column_span)
        self._grid.setAlignment(card, Qt.AlignmentFlag.AlignTop)


class BullpenReadinessWidget(QWidget):
    """Compact summary of bullpen availability."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.summary_label = QLabel("Bullpen metrics unavailable.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-weight:600;")
        layout.addWidget(self.summary_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._badges: Dict[str, QLabel] = {}
        palette = {
            "ready": ("Ready", QColor(47, 158, 68)),
            "limited": ("Limited", QColor(245, 159, 0)),
            "rest": ("Rest", QColor(224, 49, 49)),
        }
        for key, (label, color) in palette.items():
            badge = QLabel(f"{label}: 0")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                "border-radius: 6px; padding: 4px 8px; "
                f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, 36); "
                f"color: rgb({color.red()}, {color.green()}, {color.blue()}); font-weight: 600;"
            )
            badge.setMinimumWidth(72)
            row.addWidget(badge)
            self._badges[key] = badge
        layout.addLayout(row)
        self._detail: List[Dict[str, Any]] = []

    def update_data(self, data: Dict[str, Any] | None) -> None:
        if not data:
            self.summary_label.setText("Bullpen metrics unavailable.")
            for key, badge in self._badges.items():
                label = "Ready" if key == "ready" else key.capitalize()
                badge.setText(f"{label}: 0")
            self.setToolTip("Bullpen readiness details unavailable.")
            return

        summary = data.get("headline") or "Bullpen outlook pending."
        self.summary_label.setText(summary)
        for key, badge in self._badges.items():
            label = "Ready" if key == "ready" else key.capitalize()
            value = int(data.get(key, 0) or 0)
            badge.setText(f"{label}: {value}")

        detail_lines: List[str] = []
        for item in data.get("detail", []) or []:
            name = item.get("name") or item.get("player_id") or "Unknown"
            status = item.get("status", "--")
            last_pitches = item.get("last_pitches", 0)
            last_used = item.get("last_used") or "--"
            detail_lines.append(
                f"{name}: {status} (last used {last_used}, {last_pitches} pitches)"
            )
        if detail_lines:
            self.setToolTip("\n".join(detail_lines))
        else:
            self.setToolTip("No bullpen usage recorded yet.")


class MatchupScoutWidget(QWidget):
    """Upcoming opponent snapshot."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.header = QLabel("No upcoming opponent detected.")
        self.header.setStyleSheet("font-weight:600;")
        layout.addWidget(self.header)

        self.subheader = QLabel("--")
        self.subheader.setStyleSheet("color: #495057;")
        layout.addWidget(self.subheader)

        self.detail = QLabel("--")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

    def update_matchup(self, data: Dict[str, Any] | None) -> None:
        if not data:
            self.header.setText("No upcoming opponent detected.")
            self.subheader.setText("--")
            self.detail.setText("Schedule context unavailable.")
            return

        opponent = data.get("opponent", "--")
        date_token = data.get("date", "--")
        venue = data.get("venue", "--")
        self.header.setText(f"{opponent} | {date_token} | {venue}")

        record = data.get("record", "--")
        run_diff = data.get("run_diff", "--")
        streak = data.get("streak", "--")
        self.subheader.setText(f"Record {record} | RD {run_diff} | Streak {streak}")

        note = data.get("note", "Opponent analytics unavailable.")
        team_prob = data.get("team_probable", "--")
        opp_prob = data.get("opponent_probable", "--")
        self.detail.setText(f"{note}\nProbable: {team_prob} vs {opp_prob}")


class HotColdWidget(QWidget):
    """Compact hot/cold performer summaries."""

    def __init__(self) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(8)

        hot_label = QLabel("Hot")
        hot_label.setStyleSheet("font-weight:600;")
        cold_label = QLabel("Cold")
        cold_label.setStyleSheet("font-weight:600;")
        layout.addWidget(hot_label, 0, 0)
        layout.addWidget(cold_label, 0, 1)

        self.hot_hitters = QLabel("Hitters: --")
        self.cold_hitters = QLabel("Hitters: --")
        self.hot_pitchers = QLabel("Pitchers: --")
        self.cold_pitchers = QLabel("Pitchers: --")
        for label in (
            self.hot_hitters,
            self.cold_hitters,
            self.hot_pitchers,
            self.cold_pitchers,
        ):
            label.setWordWrap(True)

        layout.addWidget(self.hot_hitters, 1, 0)
        layout.addWidget(self.cold_hitters, 1, 1)
        layout.addWidget(self.hot_pitchers, 2, 0)
        layout.addWidget(self.cold_pitchers, 2, 1)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

    def update_performers(self, data: Dict[str, Any] | None) -> None:
        if not data:
            self._set_empty()
            return

        hitters = data.get("hitters", {})
        if not isinstance(hitters, Mapping):
            hitters = {}
        pitchers = data.get("pitchers", {})
        if not isinstance(pitchers, Mapping):
            pitchers = {}

        hot_hitters = hitters.get("hot") or []
        cold_hitters = hitters.get("cold") or []
        hot_pitchers = pitchers.get("hot") or []
        cold_pitchers = pitchers.get("cold") or []

        self.hot_hitters.setText(self._format_hitters(hot_hitters))
        self.cold_hitters.setText(self._format_hitters(cold_hitters))
        self.hot_pitchers.setText(self._format_pitchers(hot_pitchers))
        self.cold_pitchers.setText(self._format_pitchers(cold_pitchers))

        tooltip_lines = []
        note = data.get("note")
        if note:
            tooltip_lines.append(str(note))
        range_info = data.get("range", {})
        if isinstance(range_info, Mapping):
            start = range_info.get("start")
            end = range_info.get("end")
            if start and end:
                tooltip_lines.append(f"Sample window: {start} to {end}")
        self.setToolTip("\n".join(tooltip_lines))

    def _set_empty(self) -> None:
        self.hot_hitters.setText("Hitters: --")
        self.cold_hitters.setText("Hitters: --")
        self.hot_pitchers.setText("Pitchers: --")
        self.cold_pitchers.setText("Pitchers: --")
        self.setToolTip("")

    @staticmethod
    def _format_rate(value: Any, *, decimals: int, strip_zero: bool = True) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "--"
        if numeric != numeric:  # NaN guard
            return "--"
        text = f"{numeric:.{decimals}f}"
        if strip_zero and 0 < numeric < 1:
            text = text.lstrip("0")
        return text

    def _format_hitters(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return "Hitters: --"
        lines = []
        for entry in entries:
            name = entry.get("name") or "--"
            avg = self._format_rate(entry.get("avg"), decimals=3, strip_zero=True)
            ops = self._format_rate(entry.get("ops"), decimals=3, strip_zero=True)
            hr = entry.get("hr")
            line = f"{name} {avg} OPS {ops}"
            if isinstance(hr, (int, float)) and int(hr) > 0:
                line = f"{line}, {int(hr)} HR"
            lines.append(line)
        return "Hitters:\n" + "\n".join(lines)

    def _format_pitchers(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return "Pitchers: --"
        lines = []
        for entry in entries:
            name = entry.get("name") or "--"
            era = self._format_rate(entry.get("era"), decimals=2, strip_zero=False)
            ip = entry.get("ip")
            ip_label = format_ip(ip) if ip is not None else "--"
            lines.append(f"{name} {era} ERA, {ip_label} IP")
        return "Pitchers:\n" + "\n".join(lines)


class DivisionStandingsWidget(QWidget):
    """Compact table for the current division standings."""

    def __init__(self) -> None:
        super().__init__()
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(12)
        self._layout.setVerticalSpacing(6)

    def update_standings(self, data: Dict[str, Any] | None) -> None:
        layout = self._layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        teams = []
        if data and isinstance(data.get("teams"), list):
            teams = data.get("teams") or []
        if not teams:
            layout.addWidget(QLabel("Standings unavailable."), 0, 0)
            return

        headers = [
            ("Team", Qt.AlignmentFlag.AlignLeft),
            ("W-L", Qt.AlignmentFlag.AlignRight),
            ("GB", Qt.AlignmentFlag.AlignRight),
            ("Stk", Qt.AlignmentFlag.AlignRight),
        ]
        for col, (label, align) in enumerate(headers):
            header = QLabel(label)
            header.setAlignment(align)
            header.setStyleSheet("font-weight:600; color:#495057;")
            layout.addWidget(header, 0, col)

        for row_idx, entry in enumerate(teams, start=1):
            label = entry.get("label") or entry.get("team_id") or "--"
            wins = entry.get("wins", 0)
            losses = entry.get("losses", 0)
            record = f"{wins}-{losses}"
            gb = entry.get("gb", "--")
            streak = entry.get("streak", "--")

            name_label = QLabel(str(label))
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            record_label = QLabel(str(record))
            record_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            gb_label = QLabel(str(gb))
            gb_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            streak_label = QLabel(str(streak))
            streak_label.setAlignment(Qt.AlignmentFlag.AlignRight)

            if entry.get("name"):
                name_label.setToolTip(str(entry.get("name")))
            if entry.get("is_current"):
                name_label.setStyleSheet("font-weight:700;")
                record_label.setStyleSheet("font-weight:700;")
                gb_label.setStyleSheet("font-weight:700;")
                streak_label.setStyleSheet("font-weight:700;")

            layout.addWidget(name_label, row_idx, 0)
            layout.addWidget(record_label, row_idx, 1)
            layout.addWidget(gb_label, row_idx, 2)
            layout.addWidget(streak_label, row_idx, 3)
