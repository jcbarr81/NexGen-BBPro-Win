"""Player Profile V2 dialog."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Optional

try:
    from PyQt6.QtCore import Qt
except ImportError:  # pragma: no cover - local fallback for headless tests
    Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(
            AlignCenter=None,
            AlignHCenter=None,
            AlignVCenter=None,
            AlignLeft=None,
            AlignRight=None,
            AlignTop=None,
        ),
        AspectRatioMode=SimpleNamespace(KeepAspectRatio=None),
        TransformationMode=SimpleNamespace(SmoothTransformation=None),
        ItemDataRole=SimpleNamespace(DisplayRole=None, EditRole=None),
    )

try:
    from PyQt6.QtGui import QColor, QFont, QPixmap
except ImportError:  # pragma: no cover - local fallback for headless tests
    class QPixmap:  # type: ignore[too-many-ancestors]
        def __init__(self, *args, **kwargs) -> None:
            self._is_null = True

        def isNull(self) -> bool:
            return self._is_null

        def scaled(self, *args, **kwargs) -> "QPixmap":
            return self

    class _GuiDummy:
        def __init__(self, *args, **kwargs) -> None:
            pass

    QColor = QFont = _GuiDummy

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
        QHeaderView,
    )
except ImportError:  # pragma: no cover - local fallback for headless tests
    class _QtDummy:
        Shape = SimpleNamespace(StyledPanel=None, NoFrame=None)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, _name):
            def _dummy(*_args, **_kwargs):
                return self

            return _dummy

        def addWidget(self, *args, **kwargs) -> None:
            pass

        def addLayout(self, *args, **kwargs) -> None:
            pass

        def addTab(self, *args, **kwargs) -> None:
            pass

        def addStretch(self, *args, **kwargs) -> None:
            pass

        def addSpacing(self, *args, **kwargs) -> None:
            pass

        def setLayout(self, *args, **kwargs) -> None:
            pass

        def layout(self):
            return self

        def setContentsMargins(self, *args, **kwargs) -> None:
            pass

        def setSpacing(self, *args, **kwargs) -> None:
            pass

        def setObjectName(self, *args, **kwargs) -> None:
            pass

        def setFrameShape(self, *args, **kwargs) -> None:
            pass

        def setAlignment(self, *args, **kwargs) -> None:
            pass

        def setWordWrap(self, *args, **kwargs) -> None:
            pass

        def setText(self, *args, **kwargs) -> None:
            pass

        def setPixmap(self, *args, **kwargs) -> None:
            pass

        def setMinimumSize(self, *args, **kwargs) -> None:
            pass

        def setStyleSheet(self, *args, **kwargs) -> None:
            pass

        def setData(self, *args, **kwargs) -> None:
            pass

        def setHorizontalHeaderLabels(self, *args, **kwargs) -> None:
            pass

        def setItem(self, *args, **kwargs) -> None:
            pass

        def horizontalHeader(self):
            return self

        def verticalHeader(self):
            return self

        def setSectionResizeMode(self, *args, **kwargs) -> None:
            pass

    QDialog = QLabel = QVBoxLayout = QHBoxLayout = QFrame = QGridLayout = QTabWidget = QScrollArea = QWidget = QPushButton = QTableWidget = QHeaderView = _QtDummy

    class QTableWidgetItem(_QtDummy):
        pass

from playbalance.season_context import SeasonContext
from services.finance_budget_effects import scouting_display_value
from services.record_book import player_record_entries
from services.special_events import load_player_special_events
from services.transaction_log import load_transactions
from utils.path_utils import get_base_dir
from utils.player_loader import load_players_from_csv
from utils.rating_display import rating_display_value
from utils.stats_persistence import load_stats
from .player_profile_v2_viewmodel import (
    PlayerProfileViewModel,
    ProfileNote,
    TrainingFocusSummary,
    _current_season_year,
    _estimate_overall_rating,
    _format_season_label,
    _resolve_team_id,
    build_player_profile_view_model,
)
from .star_rating import star_label, star_text


def _looks_like_qt_stub(cls: Any) -> bool:
    name = getattr(cls, "__name__", "") or ""
    module = getattr(cls, "__module__", "") or ""
    lowered = name.lower()
    return "dummy" in lowered or lowered.startswith("fake") or module.startswith("tests")


HEADLESS_QT = _looks_like_qt_stub(QDialog) or _looks_like_qt_stub(QTableWidget)

C_BG = "#11151b"
C_PANEL = "#171d27"
C_PANEL_ALT = "#0f141b"
C_BORDER = "#283447"
C_TEXT = "#edf1f7"
C_TEXT_DIM = "#91a0b8"
C_TEXT_MUTED = "#6b778c"
C_ACCENT = "#cc2336"
C_ACCENT_ALT = "#235e99"
C_GOOD = "#4cc38a"
C_WARN = "#d7aa3a"


class PlayerProfileDialogV2(QDialog):
    """Modern player profile dialog with explicit legacy fallback."""

    def __init__(self, player: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player = player
        self.vm = build_player_profile_view_model(player)
        self._player_pool: Optional[dict[str, Any]] = None
        self._stats_cache: Optional[dict[str, Any]] = None
        self._comparison_player: Any | None = None
        self._comparison_panel: Optional[QWidget] = None
        self._comparison_name_label: Optional[QLabel] = None
        self._comparison_labels: dict[str, tuple[QLabel, QLabel]] = {}
        self._training_source_label: Optional[QLabel] = None
        self._training_hitters_label: Optional[QLabel] = None
        self._training_pitchers_label: Optional[QLabel] = None
        self._clear_compare_button: Optional[QPushButton] = None
        self.setWindowTitle(self.vm.full_name)
        if HEADLESS_QT:
            self._create_stats_table(self.vm.stats_rows, self.vm.stats_columns)
            return
        self.setMinimumSize(920, 680)
        self._apply_style()
        self._build_ui()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {C_BG};
                color: {C_TEXT};
            }}
            QFrame#HeroCard, QFrame#PanelCard {{
                background: {C_PANEL};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
            }}
            QFrame#PanelCardAlt {{
                background: {C_PANEL_ALT};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
            }}
            QLabel#ProfileTitle {{
                color: {C_TEXT};
                font-size: 26px;
                font-weight: 800;
            }}
            QLabel#SectionTitle {{
                color: {C_TEXT_DIM};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
                text-transform: uppercase;
            }}
            QLabel#MetricLabel {{
                color: {C_TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#MetricValue {{
                color: {C_TEXT};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#Badge {{
                background: {C_ACCENT};
                color: white;
                border-radius: 9px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#AvatarFallback {{
                background: {C_ACCENT_ALT};
                border: 2px solid {C_BORDER};
                border-radius: 42px;
                color: {C_TEXT};
                font-size: 24px;
                font-weight: 800;
            }}
            QLabel#OverallValue {{
                color: {C_ACCENT};
                font-size: 44px;
                font-weight: 800;
            }}
            QLabel#StatusLabel {{
                background: rgba(204, 35, 54, 0.12);
                border: 1px solid rgba(204, 35, 54, 0.28);
                border-radius: 10px;
                color: {C_TEXT};
                padding: 4px 10px;
            }}
            QTabWidget::pane {{
                border: none;
                background: {C_BG};
            }}
            QTabBar::tab {{
                background: {C_PANEL_ALT};
                color: {C_TEXT_DIM};
                padding: 10px 18px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {C_TEXT};
                border-bottom: 2px solid {C_ACCENT};
            }}
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                color: {C_TEXT};
                padding: 6px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.10);
            }}
            QTableWidget {{
                background: {C_PANEL};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                gridline-color: {C_BORDER};
                color: {C_TEXT};
                selection-background-color: {C_ACCENT_ALT};
            }}
            QHeaderView::section {{
                background: {C_PANEL_ALT};
                color: {C_TEXT_DIM};
                border: none;
                border-bottom: 1px solid {C_BORDER};
                padding: 6px;
                font-weight: 700;
            }}
            """
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        root.addWidget(self._build_top_bar())
        root.addWidget(self._build_header())
        root.addWidget(self._build_action_row())

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_stats_tab(), "Stats")
        tabs.addTab(self._build_career_tab(), "Career")
        root.addWidget(tabs, 1)

        root.addWidget(self._build_footer())

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label("PLAYER PROFILE", object_name="SectionTitle"))
        layout.addStretch()
        layout.addWidget(self._label("V2 rollout active", color=C_TEXT_MUTED))
        return bar

    def _build_header(self) -> QWidget:
        card = self._panel("HeroCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        layout.addWidget(self._build_avatar(), 0, self._align("AlignTop"))
        layout.addWidget(self._build_identity_block(), 2)
        layout.addWidget(self._build_overall_block(), 1)
        layout.addWidget(self._build_defense_block(), 1)
        return card

    def _build_avatar(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        avatar = QLabel()
        avatar.setFixedSize(84, 84)
        avatar.setAlignment(self._align("AlignCenter"))
        pix = self._load_avatar_pixmap()
        if pix is not None and not pix.isNull():
            avatar.setPixmap(pix)
        else:
            avatar.setObjectName("AvatarFallback")
            avatar.setText(self.vm.initials)
        layout.addWidget(avatar)
        return wrapper

    def _build_identity_block(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = self._label(self.vm.full_name, object_name="ProfileTitle")
        layout.addWidget(title)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)
        badge_row.addWidget(self._label(self.vm.positions_text or "?", object_name="Badge"))
        badge_row.addWidget(self._label(self.vm.team_id or "--", color=C_TEXT_DIM))
        if self.vm.role_text:
            badge_row.addWidget(self._label(self.vm.role_text, color=C_TEXT_MUTED))
        badge_row.addStretch()
        layout.addLayout(badge_row)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        for index, (label_text, value_text) in enumerate(self.vm.header_metrics):
            row = index // 3
            col = index % 3
            grid.addWidget(self._metric_widget(label_text, value_text), row, col)
        layout.addLayout(grid)

        layout.addWidget(self._build_summary_card())
        return wrapper

    def _build_summary_card(self) -> QWidget:
        card = self._panel("PanelCardAlt")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(self._label("Scouting Summary", object_name="SectionTitle"))
        summary = self._label(self.vm.scouting_summary)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        layout.addWidget(
            self._label(
                f"Confidence: {self.vm.scouting_confidence_text}",
                color=C_TEXT_DIM,
            )
        )
        layout.addWidget(self._label(self.vm.health_status, object_name="StatusLabel"))
        return card

    def _build_overall_block(self) -> QWidget:
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._label("Overall", object_name="SectionTitle"))
        overall_text = "--"
        if self.vm.overall_display is not None:
            overall_text = str(int(round(float(self.vm.overall_display))))
        overall = self._label(overall_text, object_name="OverallValue")
        layout.addWidget(overall)
        layout.addWidget(star_label(self.vm.overall_display or 35, min_rating=35.0, max_rating=99.0, size=14))
        layout.addWidget(self._label(f"Stars: {self.vm.overall_stars_text}", color=C_TEXT_DIM))
        layout.addStretch()
        return card

    def _build_defense_block(self) -> QWidget:
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._label("Defense Snapshot", object_name="SectionTitle"))
        for label_text, value_text in self.vm.defense_ratings:
            layout.addWidget(self._stat_line(label_text, value_text))
        layout.addStretch()
        return card

    def _build_overview_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_ratings_card())

        overall_card = self._build_detail_card("Overall Breakdown", self.vm.overall_details)
        if overall_card is not None:
            layout.addWidget(overall_card)

        contract_card = self._build_detail_card("Contract Snapshot", self.vm.contract_details)
        if contract_card is not None:
            layout.addWidget(contract_card)

        training_card = self._build_training_focus_card(self.vm.training_focus)
        if training_card is not None:
            layout.addWidget(training_card)

        comparison_card = self._build_comparison_card()
        if comparison_card is not None:
            layout.addWidget(comparison_card)

        recent_training = self._build_notes_card("Recent Training Focus", self.vm.recent_training_entries)
        if recent_training is not None:
            layout.addWidget(recent_training)

        injury_card = self._build_notes_card("Injury History", self.vm.injury_history)
        if injury_card is not None:
            layout.addWidget(injury_card)

        layout.addStretch()
        scroll.setWidget(body)
        return scroll

    def _build_ratings_card(self) -> QWidget:
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self._label("Ratings", object_name="SectionTitle"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        columns = 3
        for index, (label_text, value_text) in enumerate(self.vm.overview_ratings):
            row = index // columns
            col = index % columns
            grid.addWidget(self._stat_line(label_text, value_text), row, col)
        layout.addLayout(grid)
        return card

    def _build_training_focus_card(self, summary: Optional[TrainingFocusSummary]) -> Optional[QWidget]:
        if summary is None:
            return None
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._label("Training Focus", object_name="SectionTitle"))
        self._training_source_label = self._label(
            f"Source: {summary.source_text}",
            color=C_TEXT_DIM,
        )
        self._training_hitters_label = self._label(f"Hitters: {summary.hitters_text}")
        self._training_pitchers_label = self._label(f"Pitchers: {summary.pitchers_text}")
        layout.addWidget(self._training_source_label)
        layout.addWidget(self._training_hitters_label)
        layout.addWidget(self._training_pitchers_label)
        return card

    def _build_notes_card(self, title: str, notes: Iterable[ProfileNote]) -> Optional[QWidget]:
        note_list = list(notes)
        if not note_list:
            return None
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._label(title, object_name="SectionTitle"))
        for note in note_list:
            entry = QWidget()
            entry_layout = QVBoxLayout(entry)
            entry_layout.setContentsMargins(0, 0, 0, 0)
            entry_layout.setSpacing(2)
            title_label = self._label(note.title)
            title_label.setWordWrap(True)
            entry_layout.addWidget(title_label)
            if note.detail:
                detail_label = self._label(note.detail, color=C_TEXT_DIM)
                detail_label.setWordWrap(True)
                entry_layout.addWidget(detail_label)
            layout.addWidget(entry)
        return card

    def _build_detail_card(
        self,
        title: str,
        details: Iterable[tuple[str, str]],
    ) -> Optional[QWidget]:
        detail_rows = list(details)
        if not detail_rows:
            return None
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._label(title, object_name="SectionTitle"))
        for label_text, value_text in detail_rows:
            layout.addWidget(self._stat_line(label_text, value_text))
        return card

    def _build_stats_tab(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        summary = self._build_detail_card("Stat Snapshots", self._stats_summary_rows())
        if summary is not None:
            layout.addWidget(summary)
        table = self._create_stats_table(self.vm.stats_rows, self.vm.stats_columns)
        if isinstance(table, QWidget):
            layout.addWidget(table)
        else:
            fallback = self._label("Stats unavailable.")
            fallback.setAlignment(self._align("AlignCenter"))
            layout.addWidget(fallback)
        return wrapper

    def _build_career_tab(self) -> QWidget:
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        layout.addWidget(self._label("Career Ledger", object_name="SectionTitle"))
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_ratings_history_tab(), "Ratings")
        tabs.addTab(self._build_awards_tab(), "Awards")
        tabs.addTab(self._build_records_events_tab(), "Records & Events")
        tabs.addTab(self._build_transactions_tab(), "Transactions")
        tabs.addTab(self._build_transactions_tab(trade_only=True), "Trades")
        layout.addWidget(tabs)
        return card

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        return footer

    def _create_stats_table(
        self,
        rows: Iterable[tuple[str, dict[str, Any]]],
        columns: Iterable[str],
    ) -> QWidget:
        rows_list = list(rows)
        columns_list = list(columns)
        if not rows_list or not columns_list:
            label = self._label("No stat history available.", color=C_TEXT_DIM)
            label.setAlignment(self._align("AlignCenter"))
            return label

        table = QTableWidget(len(rows_list), len(columns_list) + 1)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setHorizontalHeaderLabels(["Season", *[str(col).upper() for col in columns_list]])
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        try:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass

        for row_index, (row_label, stats) in enumerate(rows_list):
            table.setItem(row_index, 0, self._table_item(row_label, align_left=True))
            for col_index, key in enumerate(columns_list, start=1):
                value = stats.get(key, "")
                table.setItem(row_index, col_index, self._table_item(_format_stat(value, key=key)))
        return table

    def _table_item(self, value: Any, *, align_left: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(str(value))
        try:
            if align_left:
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            pass
        return item

    def _panel(self, object_name: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName(object_name)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        return panel

    def _label(
        self,
        text: str,
        *,
        color: Optional[str] = None,
        object_name: str = "",
    ) -> QLabel:
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        elif color:
            set_style = getattr(label, "setStyleSheet", None)
            if callable(set_style):
                set_style(f"color: {color};")
        return label

    def _metric_widget(self, label_text: str, value_text: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._label(label_text, object_name="MetricLabel"))
        layout.addWidget(self._label(value_text, object_name="MetricValue"))
        return widget

    def _stat_line(self, label_text: str, value_text: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._label(label_text, color=C_TEXT_DIM))
        layout.addStretch()
        layout.addWidget(self._label(value_text, color=C_TEXT))
        return widget

    def _load_avatar_pixmap(self) -> Optional[QPixmap]:
        avatar_path = getattr(self.player, "avatar_path", None)
        if avatar_path:
            pix = QPixmap(str(avatar_path))
            if not pix.isNull():
                return pix.scaled(
                    84,
                    84,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        avatar_dir = Path(get_base_dir()) / "images" / "avatars"
        paths = []
        if player_id:
            paths.append(avatar_dir / f"{player_id}.png")
        paths.append(avatar_dir / "default.png")
        pix = QPixmap()
        for path in paths:
            pix = QPixmap(str(path))
            if not pix.isNull():
                break
        if pix.isNull():
            return None
        return pix.scaled(
            84,
            84,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _align(*names: str):
        value = None
        for name in names:
            attr = getattr(Qt.AlignmentFlag, name, None)
            if attr is None:
                continue
            value = attr if value is None else value | attr
        return value

    def _build_action_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addStretch()

        training_btn = QPushButton("Training Focus...")
        training_btn.clicked.connect(self._open_training_focus_dialog)
        layout.addWidget(training_btn)

        compare_btn = QPushButton("Compare...")
        compare_btn.clicked.connect(self._prompt_comparison_player)
        layout.addWidget(compare_btn)

        legacy_btn = QPushButton("Legacy View...")
        legacy_btn.clicked.connect(self._open_legacy_dialog)
        layout.addWidget(legacy_btn)

        clear_btn = QPushButton("Clear Compare")
        clear_btn.clicked.connect(self._clear_comparison)
        layout.addWidget(clear_btn)
        self._clear_compare_button = clear_btn
        self._refresh_compare_actions()
        return row

    def _build_comparison_card(self) -> Optional[QWidget]:
        card = self._panel("PanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._label("Comparison", object_name="SectionTitle"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.addWidget(self._label("Metric", color=C_TEXT_DIM), 0, 0)
        grid.addWidget(self._label(self._player_display_name(self.player)), 0, 1)
        self._comparison_name_label = self._label("--")
        grid.addWidget(self._comparison_name_label, 0, 2)

        for row_index, (metric_id, label_text) in enumerate(
            self._comparison_metric_definitions(),
            start=1,
        ):
            grid.addWidget(self._label(label_text, color=C_TEXT_DIM), row_index, 0)
            primary_label = self._label("--")
            compare_label = self._label("--")
            grid.addWidget(primary_label, row_index, 1)
            grid.addWidget(compare_label, row_index, 2)
            self._comparison_labels[metric_id] = (primary_label, compare_label)

        layout.addLayout(grid)
        self._comparison_panel = card
        self._update_comparison_panel()
        return card

    def _refresh_compare_actions(self) -> None:
        if self._clear_compare_button is None:
            return
        has_compare = self._comparison_player is not None
        try:
            self._clear_compare_button.setVisible(has_compare)
        except Exception:
            pass

    def _prompt_comparison_player(self) -> None:
        try:
            from .player_profile_dialog import ComparisonSelectorDialog
        except Exception:
            return
        try:
            pool = self._load_player_pool().copy()
            selector = ComparisonSelectorDialog(
                pool,
                self.player.player_id,
                self,
            )
        except Exception:
            return
        try:
            accepted = bool(selector.exec())
        except Exception:
            accepted = False
        if not accepted:
            return
        chosen = getattr(selector, "selected_player", None)
        if chosen is None:
            return
        self._attach_player_stats(chosen)
        self._comparison_player = chosen
        self._update_comparison_panel()
        self._refresh_compare_actions()

    def _clear_comparison(self) -> None:
        self._comparison_player = None
        self._update_comparison_panel()
        self._refresh_compare_actions()

    def _open_legacy_dialog(self) -> None:
        try:
            from .player_profile_launcher import open_player_profile_dialog
        except Exception:
            return
        try:
            open_player_profile_dialog(self.player, self, variant="legacy")
        except Exception:
            return

    def _load_player_pool(self) -> dict[str, Any]:
        if self._player_pool is None:
            try:
                players = load_players_from_csv("data/players.csv")
            except Exception:
                players = []
            self._player_pool = {
                str(getattr(player, "player_id", "") or ""): player
                for player in players
                if getattr(player, "player_id", None)
            }
        return self._player_pool

    def _get_stats_cache(self) -> dict[str, Any]:
        if self._stats_cache is None:
            try:
                payload = load_stats()
            except Exception:
                payload = {}
            players = payload.get("players", {}) if isinstance(payload, Mapping) else {}
            self._stats_cache = dict(players) if isinstance(players, Mapping) else {}
        return self._stats_cache

    def _attach_player_stats(self, player: Any) -> None:
        if getattr(player, "season_stats", None):
            return
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            return
        stats = self._get_stats_cache().get(player_id)
        if isinstance(stats, dict) and stats:
            try:
                player.season_stats = stats
            except Exception:
                return

    def _player_stats(self, player: Any) -> dict[str, Any]:
        stats = getattr(player, "season_stats", None)
        return dict(stats) if isinstance(stats, Mapping) else {}

    def _player_display_name(self, player: Any) -> str:
        first_name = str(getattr(player, "first_name", "") or "").strip()
        last_name = str(getattr(player, "last_name", "") or "").strip()
        player_id = str(getattr(player, "player_id", "--") or "--")
        full_name = " ".join(part for part in (first_name, last_name) if part)
        return f"{full_name} [{player_id}]" if full_name else player_id

    def _comparison_metric_definitions(self) -> list[tuple[str, str]]:
        if self.vm.is_pitcher:
            return [
                ("overall", "Overall"),
                ("era", "ERA"),
                ("whip", "WHIP"),
                ("k9", "K/9"),
                ("bb9", "BB/9"),
                ("velocity", "Velocity"),
                ("control", "Control"),
                ("movement", "Movement"),
                ("endurance", "Endurance"),
            ]
        return [
            ("overall", "Overall"),
            ("avg", "AVG"),
            ("ops", "OPS"),
            ("hr", "HR"),
            ("rbi", "RBI"),
            ("speed", "Speed"),
            ("power", "Power"),
            ("contact", "Contact"),
            ("defense", "Defense"),
        ]

    def _update_comparison_panel(self) -> None:
        has_compare = self._comparison_player is not None
        if self._comparison_name_label is not None:
            name = self._player_display_name(self._comparison_player) if has_compare else "--"
            self._comparison_name_label.setText(name)
        for metric_id, _ in self._comparison_metric_definitions():
            labels = self._comparison_labels.get(metric_id)
            if not labels:
                continue
            primary_label, compare_label = labels
            primary_label.setText(self._comparison_metric_value(self.player, metric_id))
            compare_label.setText(
                self._comparison_metric_value(self._comparison_player, metric_id)
                if has_compare
                else "--"
            )

    def _comparison_metric_value(self, player: Any, metric_id: str) -> str:
        if player is None:
            return "--"
        stats = self._player_stats(player)

        def safe(key: str) -> float:
            value = stats.get(key, 0)
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        if metric_id == "overall":
            return star_text(self._overall_display_value(player), min_rating=35.0, max_rating=99.0) or "--"
        if metric_id == "avg":
            at_bats = safe("ab")
            hits = safe("h")
            return f"{hits / at_bats:.3f}" if at_bats else "--"
        if metric_id == "ops":
            total = self._obp(stats) + self._slg(stats)
            return f"{total:.3f}" if total else "--"
        if metric_id == "hr":
            homers = stats.get("hr")
            return str(int(homers)) if isinstance(homers, (int, float)) else "--"
        if metric_id == "rbi":
            runs_batted_in = stats.get("rbi")
            return str(int(runs_batted_in)) if isinstance(runs_batted_in, (int, float)) else "--"
        if metric_id == "speed":
            return self._scouting_rating_text(getattr(player, "sp", None), key="SP", player=player)
        if metric_id == "power":
            return self._scouting_rating_text(getattr(player, "ph", None), key="PH", player=player)
        if metric_id == "contact":
            return self._scouting_rating_text(getattr(player, "ch", None), key="CH", player=player)
        if metric_id == "defense":
            return self._scouting_rating_text(getattr(player, "fa", None), key="FA", player=player)
        if metric_id == "era":
            innings = self._innings_pitched(stats)
            return f"{(safe('er') * 9.0) / innings:.2f}" if innings else "--"
        if metric_id == "whip":
            innings = self._innings_pitched(stats)
            return f"{(safe('bb') + safe('h')) / innings:.2f}" if innings else "--"
        if metric_id == "k9":
            innings = self._innings_pitched(stats)
            strikeouts = safe("k") or safe("so")
            return f"{(strikeouts * 9.0) / innings:.2f}" if innings else "--"
        if metric_id == "bb9":
            innings = self._innings_pitched(stats)
            return f"{(safe('bb') * 9.0) / innings:.2f}" if innings else "--"
        if metric_id == "control":
            return self._scouting_rating_text(getattr(player, "control", None), key="CO", player=player)
        if metric_id == "movement":
            return self._scouting_rating_text(getattr(player, "movement", None), key="MO", player=player)
        if metric_id == "endurance":
            return self._scouting_rating_text(getattr(player, "endurance", None), key="EN", player=player)
        return str(getattr(player, metric_id, "--"))

    def _build_ratings_history_tab(self) -> QWidget:
        rows = self._collect_ratings_history()
        if not rows:
            return self._build_empty_tab("Ratings history unavailable.")

        fields = self._rating_history_fields()
        table = QTableWidget(len(rows), len(fields) + 1)
        table.setHorizontalHeaderLabels(["Year"] + [label for _, label in fields])
        table.verticalHeader().setVisible(False)
        try:
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        except Exception:
            pass
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        try:
            for idx in range(len(fields) + 1):
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        except Exception:
            pass

        for row_index, (label_text, data) in enumerate(rows):
            table.setItem(row_index, 0, self._table_item(label_text, align_left=True))
            for col_index, (key, rating_label) in enumerate(fields, start=1):
                text = self._scouting_rating_text(data.get(key), key=rating_label, player=self.player)
                table.setItem(row_index, col_index, self._table_item(text))

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(table)
        if len(rows) <= 1:
            note = self._label(
                "Historical rating snapshots will appear after season rollover.",
                color=C_TEXT_DIM,
            )
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addStretch()
        return wrapper

    def _build_awards_tab(self) -> QWidget:
        entries = self._collect_awards_history()
        if not entries:
            return self._build_empty_tab("No awards recorded.")

        table = QTableWidget(len(entries), 3)
        table.setHorizontalHeaderLabels(["Year", "Award", "Detail"])
        table.verticalHeader().setVisible(False)
        try:
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        except Exception:
            pass
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        try:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass
        for row_index, entry in enumerate(entries):
            table.setItem(row_index, 0, self._table_item(entry.get("year", "--"), align_left=True))
            table.setItem(row_index, 1, self._table_item(entry.get("award", "--"), align_left=True))
            table.setItem(row_index, 2, self._table_item(entry.get("detail", "--"), align_left=True))
        return table

    def _build_records_events_tab(self) -> QWidget:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        records: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        if player_id:
            try:
                records = player_record_entries(player_id)
            except Exception:
                records = []
            try:
                events = load_player_special_events(player_id, limit=25)
            except Exception:
                events = []

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._label("Records", color=C_TEXT_DIM))

        if records:
            records.sort(key=lambda item: (item.get("scope") != "career", str(item.get("label") or "")))
            record_table = QTableWidget(len(records), 3)
            record_table.setHorizontalHeaderLabels(["Record", "Value", "Season"])
            record_table.verticalHeader().setVisible(False)
            try:
                record_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                record_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            except Exception:
                pass
            record_table.setAlternatingRowColors(True)
            header = record_table.horizontalHeader()
            try:
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            except Exception:
                pass
            for row_index, entry in enumerate(records):
                holder = entry.get("holder", {}) if isinstance(entry, Mapping) else {}
                season_label = holder.get("season_label") if isinstance(holder, Mapping) else None
                if not season_label:
                    season_label = "Career" if entry.get("scope") == "career" else "-"
                value_text = entry.get("value_text") or entry.get("value") or "--"
                record_table.setItem(row_index, 0, self._table_item(entry.get("label") or "--", align_left=True))
                record_table.setItem(row_index, 1, self._table_item(value_text))
                record_table.setItem(row_index, 2, self._table_item(season_label, align_left=True))
            layout.addWidget(record_table)
        else:
            layout.addWidget(self._label("No record book entries yet.", color=C_TEXT_DIM))

        layout.addWidget(self._label("Special Events", color=C_TEXT_DIM))
        if events:
            event_table = QTableWidget(len(events), 4)
            event_table.setHorizontalHeaderLabels(["Season", "Date", "Event", "Detail"])
            event_table.verticalHeader().setVisible(False)
            try:
                event_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                event_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            except Exception:
                pass
            event_table.setAlternatingRowColors(True)
            header = event_table.horizontalHeader()
            try:
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
                header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            except Exception:
                pass
            for row_index, entry in enumerate(events):
                season_id = str(entry.get("season_id") or "").strip()
                league_year = entry.get("league_year")
                if league_year not in (None, ""):
                    season_label = f"{int(league_year):04d}" if str(league_year).isdigit() else str(league_year)
                else:
                    season_label = _format_season_label(season_id) if season_id else "--"
                detail = str(entry.get("detail") or "").strip()
                if not detail:
                    team_id = str(entry.get("team_id") or "").strip()
                    opponent_id = str(entry.get("opponent_id") or "").strip()
                    if team_id and opponent_id:
                        detail = f"{team_id} vs {opponent_id}"
                    elif team_id:
                        detail = team_id
                event_table.setItem(row_index, 0, self._table_item(season_label, align_left=True))
                event_table.setItem(row_index, 1, self._table_item(entry.get("date") or "--", align_left=True))
                event_table.setItem(row_index, 2, self._table_item(entry.get("label") or entry.get("type") or "--", align_left=True))
                event_table.setItem(row_index, 3, self._table_item(detail or "--", align_left=True))
            layout.addWidget(event_table)
        else:
            layout.addWidget(self._label("No special events recorded yet.", color=C_TEXT_DIM))
        layout.addStretch()
        return wrapper

    def _build_transactions_tab(self, *, trade_only: bool = False) -> QWidget:
        entries = self._collect_transactions(trade_only=trade_only)
        if not entries:
            message = "No trade history recorded." if trade_only else "No transactions recorded."
            return self._build_empty_tab(message)

        table = QTableWidget(len(entries), 7)
        table.setHorizontalHeaderLabels(
            ["Date", "Team", "Action", "From", "To", "Counterparty", "Details"]
        )
        table.verticalHeader().setVisible(False)
        try:
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        except Exception:
            pass
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        try:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass
        for row_index, entry in enumerate(entries):
            date_value = str(entry.get("season_date") or entry.get("timestamp") or "").strip()
            if " " in date_value:
                date_value = date_value.split(" ", 1)[0]
            action = str(entry.get("action") or "").replace("_", " ").title()
            table.setItem(row_index, 0, self._table_item(date_value or "--", align_left=True))
            table.setItem(row_index, 1, self._table_item(entry.get("team_id") or "--", align_left=True))
            table.setItem(row_index, 2, self._table_item(action or "--", align_left=True))
            table.setItem(row_index, 3, self._table_item(entry.get("from_level") or "", align_left=True))
            table.setItem(row_index, 4, self._table_item(entry.get("to_level") or "", align_left=True))
            table.setItem(row_index, 5, self._table_item(entry.get("counterparty") or "", align_left=True))
            table.setItem(row_index, 6, self._table_item(entry.get("details") or "", align_left=True))
        return table

    def _build_empty_tab(self, message: str) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        label = self._label(message, color=C_TEXT_DIM)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()
        return wrapper

    def _collect_ratings_history(self) -> list[tuple[str, dict[str, Any]]]:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return []
        helpers = _legacy_profile_helpers()
        if helpers is None:
            return []

        entries: list[tuple[str, dict[str, Any]]] = []
        seen_years: set[int] = set()
        try:
            seasons = list(SeasonContext.load().seasons)
        except Exception:
            seasons = []

        for season in seasons:
            if not isinstance(season, Mapping):
                continue
            season_id = str(season.get("season_id", "") or "").strip()
            if not season_id:
                continue
            year_value = _coerce_year(season.get("league_year")) or _season_year_from_id(season_id)
            path = None
            artifacts = season.get("artifacts") or {}
            if isinstance(artifacts, Mapping):
                try:
                    path = helpers._resolve_artifact_path(artifacts.get("players"))
                except Exception:
                    path = None
            if path is None:
                path = get_base_dir() / "data" / "careers" / season_id / "players.csv"
            row = helpers._load_player_row_from_csv(path, player_id)
            if not row:
                continue
            ratings = helpers._ratings_from_row(row, is_pitcher=self.vm.is_pitcher)
            if not ratings:
                continue
            label_text = f"{year_value:04d}" if year_value > 0 else season_id
            entries.append((label_text, ratings))
            if year_value > 0:
                seen_years.add(year_value)

        current_year = _current_season_year()
        current_ratings = helpers._ratings_from_player(self.player, is_pitcher=self.vm.is_pitcher)
        if current_ratings:
            label_text = f"{current_year:04d}" if current_year else "Current"
            if current_year and current_year in seen_years:
                entries = [
                    entry
                    for entry in entries
                    if helpers._extract_year_from_label(entry[0]) != current_year
                ]
            entries.append((label_text, current_ratings))

        entries.sort(
            key=lambda item: helpers._extract_year_from_label(item[0]) or -1,
            reverse=False,
        )
        return entries

    def _collect_awards_history(self) -> list[dict[str, str]]:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return []
        helpers = _legacy_profile_helpers()
        if helpers is None:
            return []

        entries: list[dict[str, str]] = []
        full_name = self.vm.full_name.strip()
        try:
            seasons = list(SeasonContext.load().seasons)
        except Exception:
            seasons = []

        for season in seasons:
            if not isinstance(season, Mapping):
                continue
            season_id = str(season.get("season_id", "") or "").strip()
            if not season_id:
                continue
            year_value = _coerce_year(season.get("league_year")) or _season_year_from_id(season_id)
            path = None
            artifacts = season.get("artifacts") or {}
            if isinstance(artifacts, Mapping):
                try:
                    path = helpers._resolve_artifact_path(artifacts.get("awards"))
                except Exception:
                    path = None
            if path is None:
                path = get_base_dir() / "data" / "careers" / season_id / "awards.json"
            if path is None or not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            awards = payload.get("awards", {}) if isinstance(payload, Mapping) else {}
            if not isinstance(awards, Mapping):
                continue
            for award_name, info in awards.items():
                if not isinstance(info, Mapping):
                    continue
                award_player_id = str(info.get("player_id") or "").strip()
                if award_player_id and award_player_id != player_id:
                    continue
                if not award_player_id and full_name:
                    award_player_name = str(info.get("player_name") or "").strip()
                    if award_player_name and award_player_name != full_name:
                        continue
                award_name_raw = str(award_name or "").strip()
                entries.append(
                    {
                        "year": f"{year_value:04d}" if year_value > 0 else season_id,
                        "award": award_name_raw.replace("_", " ").title() or award_name_raw,
                        "detail": str(info.get("metric") or "").strip() or "-",
                    }
                )
        entries.sort(key=lambda entry: str(entry.get("year", "")), reverse=True)
        return entries

    def _collect_transactions(self, *, trade_only: bool = False) -> list[dict[str, str]]:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return []
        try:
            rows = load_transactions(limit=None)
        except Exception:
            rows = []
        filtered = [dict(row) for row in rows if row.get("player_id") == player_id]
        if trade_only:
            filtered = [
                row for row in filtered if str(row.get("action", "")).lower().startswith("trade")
            ]
        filtered.sort(
            key=lambda row: row.get("season_date") or row.get("timestamp") or "",
            reverse=True,
        )
        return filtered

    def _rating_history_fields(self) -> list[tuple[str, str]]:
        helpers = _legacy_profile_helpers()
        if helpers is None:
            return [("overall", "OVR")]
        return list(
            helpers._PITCHER_RATING_HISTORY if self.vm.is_pitcher else helpers._HITTER_RATING_HISTORY
        )

    def _overall_display_value(self, player: Any) -> Optional[float]:
        value = getattr(player, "overall", None)
        if not isinstance(value, (int, float)):
            value = _estimate_overall_rating(player, is_pitcher=_player_is_pitcher(player))
        if not isinstance(value, (int, float)):
            return None
        display_value = rating_display_value(
            value,
            key="OVR",
            position=getattr(player, "primary_position", None),
            is_pitcher=_player_is_pitcher(player),
            mode="scale_99",
        )
        try:
            numeric_display = float(display_value)
        except (TypeError, ValueError):
            return None
        adjusted = scouting_display_value(
            numeric_display,
            player_id=str(getattr(player, "player_id", "") or ""),
            metric_key="OVR",
            team_id=_resolve_team_id(player) or None,
            minimum=35,
            maximum=99,
        )
        try:
            return float(adjusted)
        except (TypeError, ValueError):
            return numeric_display

    def _scouting_rating_text(self, value: Any, *, key: str, player: Any) -> str:
        if value in ("", None):
            return "--"
        display_value = rating_display_value(
            value,
            key=key,
            position=getattr(player, "primary_position", None),
            is_pitcher=_player_is_pitcher(player),
            mode="scale_99",
        )
        adjusted = scouting_display_value(
            display_value,
            player_id=str(getattr(player, "player_id", "") or ""),
            metric_key=key,
            team_id=_resolve_team_id(player) or None,
            minimum=35,
            maximum=99,
        )
        try:
            return str(int(round(float(adjusted))))
        except (TypeError, ValueError):
            return str(adjusted)

    def _stats_summary_rows(self) -> tuple[tuple[str, str], ...]:
        rows = list(self.vm.stats_rows)
        if not rows:
            return ()
        season_label = rows[0][0]
        season_stats = rows[0][1] if rows else {}
        career_stats = rows[-1][1] if rows and str(rows[-1][0]).lower() == "career" else {}
        if self.vm.is_pitcher:
            return (
                ("Latest Season", season_label),
                ("ERA", _format_stat(season_stats.get("era"), key="era") or "--"),
                ("WHIP", _format_stat(self._whip(season_stats), key="whip") or "--"),
                ("Career ERA", _format_stat(career_stats.get("era"), key="era") or "--"),
            )
        return (
            ("Latest Season", season_label),
            ("AVG", _format_stat(season_stats.get("avg"), key="avg") or "--"),
            ("OPS", _format_stat(season_stats.get("ops"), key="ops") or "--"),
            ("Career OPS", _format_stat(career_stats.get("ops"), key="ops") or "--"),
        )

    def _innings_pitched(self, stats: Mapping[str, Any]) -> float:
        try:
            innings = float(stats.get("ip", 0) or 0)
        except (TypeError, ValueError):
            innings = 0.0
        if innings > 0:
            return innings
        try:
            outs = float(stats.get("outs", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return outs / 3.0 if outs > 0 else 0.0

    def _obp(self, stats: Mapping[str, Any]) -> float:
        hits = _safe_float(stats.get("h"))
        walks = _safe_float(stats.get("bb"))
        hit_by_pitch = _safe_float(stats.get("hbp"))
        at_bats = _safe_float(stats.get("ab"))
        sacrifice_flies = _safe_float(stats.get("sf"))
        denominator = at_bats + walks + hit_by_pitch + sacrifice_flies
        if denominator <= 0:
            return 0.0
        return (hits + walks + hit_by_pitch) / denominator

    def _slg(self, stats: Mapping[str, Any]) -> float:
        at_bats = _safe_float(stats.get("ab"))
        if at_bats <= 0:
            return 0.0
        hits = _safe_float(stats.get("h"))
        doubles = _safe_float(stats.get("2b", stats.get("b2")))
        triples = _safe_float(stats.get("3b", stats.get("b3")))
        homers = _safe_float(stats.get("hr"))
        singles = hits - doubles - triples - homers
        total_bases = singles + (2.0 * doubles) + (3.0 * triples) + (4.0 * homers)
        return total_bases / at_bats

    def _whip(self, stats: Mapping[str, Any]) -> Optional[float]:
        innings = self._innings_pitched(stats)
        if innings <= 0:
            return None
        return (_safe_float(stats.get("bb")) + _safe_float(stats.get("h"))) / innings

    def _open_training_focus_dialog(self) -> None:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return
        try:
            from ui.training_focus_dialog import TrainingFocusDialog
        except Exception:
            return

        player_name = self.vm.full_name or player_id
        try:
            dialog = TrainingFocusDialog(
                parent=self,
                mode="player",
                player_id=player_id,
                player_name=player_name,
                team_id=self.vm.team_id or None,
            )
        except Exception:
            return
        try:
            accepted = bool(dialog.exec())
        except Exception:
            accepted = False
        if not accepted:
            return

        self.vm = build_player_profile_view_model(self.player)
        if self._training_source_label is not None and self.vm.training_focus is not None:
            self._training_source_label.setText(
                f"Source: {self.vm.training_focus.source_text}"
            )
        if self._training_hitters_label is not None and self.vm.training_focus is not None:
            self._training_hitters_label.setText(
                f"Hitters: {self.vm.training_focus.hitters_text}"
            )
        if self._training_pitchers_label is not None and self.vm.training_focus is not None:
            self._training_pitchers_label.setText(
                f"Pitchers: {self.vm.training_focus.pitchers_text}"
            )


def _format_stat(value: Any, *, key: Optional[str] = None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        if key == "ip":
            return f"{value:.2f}"
        if key in {"avg", "obp", "slg", "ops", "pct", "oba"}:
            return f"{value:.3f}".replace("-0.", "-.")
        if key in {"era", "dera", "whip"}:
            return f"{value:.2f}"
        if value.is_integer():
            return str(int(value))
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return str(value)


def _safe_float(value: Any) -> float:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return numeric


def _player_is_pitcher(player: Any) -> bool:
    return bool(
        getattr(player, "is_pitcher", False)
        or str(getattr(player, "primary_position", "") or "").upper() == "P"
    )


def _coerce_year(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _season_year_from_id(season_id: str) -> int:
    try:
        parts = str(season_id).rsplit("-", 1)
        return int(parts[-1])
    except (TypeError, ValueError):
        return 0


def _legacy_profile_helpers():
    try:
        from . import player_profile_dialog as legacy_profile
    except Exception:
        return None
    return legacy_profile


__all__ = ["PlayerProfileDialogV2"]
