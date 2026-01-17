"""Dialog for displaying a player profile with themed styling."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
import json
import sys
import csv
import math
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.injury_manager import disabled_list_days_remaining, disabled_list_label
from services.training_history import load_player_training_history
from services.injury_history import load_player_injury_history
from services.record_book import player_record_entries
from services.special_events import load_player_special_events
from services.transaction_log import load_transactions
from playbalance.season_context import SeasonContext

try:
    from PyQt6.QtCore import Qt, QPointF, QRectF
except ImportError:  # pragma: no cover - test stubs
    Qt = SimpleNamespace(
        AspectRatioMode=SimpleNamespace(KeepAspectRatio=None),
        TransformationMode=SimpleNamespace(SmoothTransformation=None),
        AlignmentFlag=SimpleNamespace(
            AlignCenter=None,
            AlignHCenter=None,
            AlignVCenter=None,
            AlignLeft=None,
            AlignRight=None,
            AlignTop=None,
        ),
        ItemDataRole=SimpleNamespace(
            DisplayRole=None,
            EditRole=None,
            UserRole=None,
        ),
    )
    QPointF = SimpleNamespace

try:
    from PyQt6.QtGui import QPixmap, QPainter, QPen, QBrush, QColor, QPolygonF
except ImportError:  # pragma: no cover - test stubs
    class QPixmap:  # type: ignore[too-many-ancestors]
        def __init__(self, *args, **kwargs) -> None:
            self._is_null = True

        def isNull(self) -> bool:
            return self._is_null

        def scaled(self, *args, **kwargs) -> 'QPixmap':
            return self

        def scaledToWidth(self, *args, **kwargs) -> 'QPixmap':
            return self

        def fill(self, *args, **kwargs) -> None:
            self._is_null = False

    class _GraphicDummy:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):  # noqa: D401 - simple no-op forwarder
            def _noop(*_args, **_kwargs) -> None:
                return None

            return _noop

    QColor = QPainter = QPen = QBrush = QPolygonF = _GraphicDummy

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QLabel,
        QVBoxLayout,
        QHBoxLayout,
        QFrame,
        QGridLayout,
        QTabWidget,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QWidget,
        QPushButton,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QSizePolicy,
        QAbstractItemView,
    )
except ImportError:  # pragma: no cover - test stubs
    class _QtDummy:
        Shape = SimpleNamespace(StyledPanel=None)
        EditTrigger = SimpleNamespace(NoEditTriggers=None)
        SelectionBehavior = SimpleNamespace(SelectRows=None)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):  # noqa: D401 - simple dummy forwarder
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

        def layout(self):
            return self

        def setLayout(self, *args, **kwargs) -> None:
            pass

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

        def setFixedSize(self, *args, **kwargs) -> None:
            pass

        def setWordWrap(self, *args, **kwargs) -> None:
            pass

        def setText(self, *args, **kwargs) -> None:
            pass

        def setPixmap(self, *args, **kwargs) -> None:
            pass

        def setMinimumSize(self, *args, **kwargs) -> None:
            pass

        def setMinimumWidth(self, *args, **kwargs) -> None:
            pass

        def setMargin(self, *args, **kwargs) -> None:
            pass

        def setProperty(self, *args, **kwargs) -> None:
            pass

    def setData(self, *args, **kwargs) -> None:
        pass

        def setTextAlignment(self, *args, **kwargs) -> None:
            pass

        def setEditTriggers(self, *args, **kwargs) -> None:
            pass

        def setSelectionBehavior(self, *args, **kwargs) -> None:
            pass

        def setAlternatingRowColors(self, *args, **kwargs) -> None:
            pass

        def setHorizontalHeaderLabels(self, *args, **kwargs) -> None:
            pass

        def setSortingEnabled(self, *args, **kwargs) -> None:
            pass

        def setItem(self, *args, **kwargs) -> None:
            pass

        def horizontalHeader(self):
            return self

        def verticalHeader(self):
            return self

        def setSectionResizeMode(self, *args, **kwargs) -> None:
            pass

    (
        QDialog,
        QLabel,
        QVBoxLayout,
        QHBoxLayout,
        QFrame,
        QGridLayout,
        QTabWidget,
        QScrollArea,
        QTableWidget,
        QWidget,
        QAbstractItemView,
    ) = (_QtDummy,) * 11

    class QTableWidgetItem(_QtDummy):
        pass

    class QHeaderView:  # type: ignore[too-many-ancestors]
        class ResizeMode:
            Stretch = None

from models.base_player import BasePlayer
from utils.stats_persistence import load_stats
from utils.path_utils import get_base_dir
from utils.player_loader import load_players_from_csv
from utils.rating_display import rating_display_text, rating_display_value
from .star_rating import star_label, star_pixmap, star_text
from .components import Card, section_title


def _looks_like_qt_stub(cls: Any) -> bool:
    """Return True when the supplied class is a light-weight stub."""

    name = getattr(cls, "__name__", "") or ""
    module = getattr(cls, "__module__", "") or ""
    name_lower = name.lower()
    if "dummy" in name_lower or name_lower.startswith("fake"):
        return True
    return module.startswith("tests.") or module.startswith("tests_")


HEADLESS_QT = (
    _looks_like_qt_stub(QDialog)
    or _looks_like_qt_stub(QTableWidget)
    or _looks_like_qt_stub(QTabWidget)
    or not hasattr(QFrame, "Shape")
)


def _safe_call(target: Any, method: str, *args, **kwargs) -> None:
    """Invoke ``method`` on ``target`` when available and callable."""

    func = getattr(target, method, None)
    if callable(func):
        func(*args, **kwargs)


def _safe_set_margins(layout: Any, *values: int) -> None:
    _safe_call(layout, "setContentsMargins", *values)


def _safe_set_spacing(layout: Any, value: int) -> None:
    _safe_call(layout, "setSpacing", value)


def _year_from_token(token: Any) -> int | None:
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        return None
    try:
        tail = text.rsplit("-", 1)[-1]
        return int(tail)
    except (ValueError, TypeError):
        pass
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 4:
        try:
            return int(digits[-4:])
        except ValueError:
            return None
    if digits:
        try:
            return int(digits)
        except ValueError:
            return None
    return None


def _year_from_entry(entry: Dict[str, Any]) -> tuple[int | None, str]:
    date_token = str(entry.get("date") or "").strip()
    year_val = _year_from_token(entry.get("year") or entry.get("season_id"))
    if year_val is None and date_token:
        try:
            year_val = int(date_token.split("-", 1)[0])
        except (ValueError, TypeError):
            year_val = None
    return year_val, date_token


def _aggregate_history_rows(
    dialog: "PlayerProfileDialog",
    entries: Iterable[Dict[str, Any]],
    *,
    is_pitcher: bool,
) -> List[Tuple[str, Dict[str, Any]]]:
    aggregated: dict[str, tuple[int, str, Dict[str, Any]]] = {}
    unknown_counter = 0
    player_id = getattr(dialog.player, "player_id", "")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        players_block = entry.get("players", {})
        if not isinstance(players_block, dict):
            continue
        player_data = players_block.get(player_id)
        if not player_data:
            continue
        snapshot = player_data.get("stats", player_data)
        data = dialog._stats_to_dict(snapshot, is_pitcher)
        if not data:
            continue
        year_val, date_token = _year_from_entry(entry)
        if year_val is None:
            unknown_counter += 1
            label = f"Year {unknown_counter}"
            order_key = -unknown_counter
        else:
            label = f"{year_val:04d}"
            order_key = year_val
        stored = aggregated.get(label)
        if stored is None or (date_token and date_token > stored[1]):
            aggregated[label] = (order_key, date_token, data)

    ordered = sorted(
        aggregated.items(),
        key=lambda item: (item[1][0], item[1][1]),
        reverse=True,
    )
    return [(label, payload[2]) for label, payload in ordered]


def _safe_set_hspacing(layout: Any, value: int) -> None:
    _safe_call(layout, "setHorizontalSpacing", value)


def _safe_set_vspacing(layout: Any, value: int) -> None:
    _safe_call(layout, "setVerticalSpacing", value)


def _alignment(*names: str) -> Any | None:
    flags = getattr(Qt, "AlignmentFlag", None)
    if not flags:
        return None
    combo = None
    for name in names:
        flag = getattr(flags, name, None)
        if flag is None:
            return None
        combo = flag if combo is None else combo | flag
    return combo


def _set_alignment(widget: Any, *names: str) -> None:
    align = _alignment(*names)
    if align is None:
        return
    try:
        widget.setAlignment(align)
    except Exception:
        pass


def _set_text_alignment(item: Any, *names: str) -> None:
    align = _alignment(*names)
    if align is None:
        return
    try:
        item.setTextAlignment(align)
    except Exception:
        pass


def _layout_add_widget(layout: Any, *args: Any, **kwargs: Any) -> None:
    method = getattr(layout, "addWidget", None)
    if not callable(method):
        return
    try:
        method(*args, **kwargs)
    except TypeError:
        try:
            method(*args)
        except TypeError:
            pass


def _layout_add_stretch(layout: Any, *args: Any) -> None:
    method = getattr(layout, "addStretch", None)
    if callable(method):
        try:
            method(*args)
        except TypeError:
            method()


_BATTING_STATS: List[str] = [
    "age",
    "team",
    "g",
    "ab",
    "r",
    "h",
    "2b",
    "3b",
    "hr",
    "rbi",
    "bb",
    "ibb",
    "k",
    "sb",
    "cs",
    "sh",
    "hbp",
    "gidp",
    "avg",
    "obp",
    "slg",
    "ops",
]

_PITCHING_STATS: List[str] = [
    "age",
    "team",
    "g",
    "gs",
    "w",
    "l",
    "pct",
    "era",
    "ip",
    "r",
    "er",
    "h",
    "hr",
    "bb",
    "k",
    "oba",
    "hbp",
    "wp",
    "cg",
    "sho",
    "sv",
    "bs",
    "dera",
]

_STAT_LABELS: Dict[str, str] = {
    "age": "Age",
    "team": "Team",
    "g": "G",
    "ab": "AB",
    "r": "R",
    "h": "H",
    "2b": "2B",
    "3b": "3B",
    "hr": "HR",
    "rbi": "RBI",
    "bb": "BB",
    "ibb": "IBB",
    "k": "K",
    "sb": "SB",
    "cs": "CS",
    "sh": "SH",
    "hbp": "HBP",
    "gidp": "GDP",
    "avg": "AVG",
    "obp": "OBP",
    "slg": "SLG",
    "ops": "OPS",
    "gs": "GS",
    "w": "W",
    "l": "L",
    "pct": "Pct.",
    "era": "ERA",
    "ip": "IP",
    "r": "R",
    "er": "ER",
    "h": "H",
    "hr": "HR",
    "bb": "BB",
    "oba": "OBA",
    "wp": "WP",
    "cg": "CG",
    "sho": "SHO",
    "sv": "SV",
    "bs": "BS",
    "dera": "dERA",
    "k9": "K/9",
    "bb9": "BB/9",
}

_STAT_ALIASES: Dict[str, Tuple[str, ...]] = {
    "2b": ("b2",),
    "3b": ("b3",),
    "k": ("so",),
    "gidp": ("gdp", "dp"),
    "pct": ("win_pct",),
    "dera": ("fip",),
}

_LEFT_ALIGN_STATS: set[str] = {"team"}
_SUMMARY_KEYS: Dict[bool, List[str]] = {
    False: ["g", "ab", "h", "hr", "rbi", "avg"],
    True: ["g", "gs", "ip", "era", "k", "sv"],
}

_STAT_ROUNDING: Dict[str, int] = {
    "avg": 3,
    "obp": 3,
    "slg": 3,
    "ops": 3,
    "pct": 3,
    "oba": 3,
    "ip": 2,
    "era": 2,
    "whip": 2,
    "fip": 2,
    "dera": 2,
}

_PITCHER_RATING_LABELS: Dict[str, str] = {
    "endurance": "EN",
    "control": "CO",
    "movement": "MO",
    "hold_runner": "HR",
}

_HITTER_RATING_HISTORY: List[Tuple[str, str]] = [
    ("overall", "OVR"),
    ("ch", "CH"),
    ("ph", "PH"),
    ("sp", "SP"),
    ("pl", "PL"),
    ("vl", "VL"),
    ("sc", "SC"),
    ("fa", "FA"),
    ("arm", "AS"),
    ("gf", "GF"),
]

_PITCHER_RATING_HISTORY: List[Tuple[str, str]] = [
    ("overall", "OVR"),
    ("endurance", "EN"),
    ("control", "CO"),
    ("movement", "MO"),
    ("hold_runner", "HR"),
    ("arm", "AS"),
    ("fa", "FA"),
    ("fb", "FB"),
    ("cu", "CU"),
    ("cb", "CB"),
    ("sl", "SL"),
    ("si", "SI"),
    ("scb", "SCB"),
    ("kn", "KN"),
]

_HITTER_OVERALL_KEYS: Tuple[str, ...] = (
    "ch",
    "ph",
    "sp",
    "pl",
    "vl",
    "sc",
    "fa",
    "arm",
    "gf",
)
_PITCHER_OVERALL_KEYS: Tuple[str, ...] = (
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "arm",
    "fa",
    "fb",
    "cu",
    "cb",
    "sl",
    "si",
    "scb",
    "kn",
)

_LEADER_CATEGORIES: Dict[bool, List[Tuple[str, str, bool]]] = {
    False: [
        ("avg", "AVG", True),
        ("hr", "HR", True),
        ("rbi", "RBI", True),
        ("sb", "SB", True),
        ("obp", "OBP", True),
        ("ops", "OPS", True),
    ],
    True: [
        ("era", "ERA", False),
        ("whip", "WHIP", False),
        ("w", "W", True),
        ("so", "SO", True),
        ("sv", "SV", True),
    ],
}


class PlayerProfileDialog(QDialog):
    """Display player information, ratings and stats using themed cards."""

    _FIELD_DIAGRAM_CACHE: QPixmap | None = None

    def __init__(self, player: BasePlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player = player
        # Ensure the view reflects the latest persisted season stats in case
        # the passed ``player`` instance is stale in memory while simulations
        # are running in another window.
        try:
            from utils.stats_persistence import load_stats as _load_season
            data = _load_season()
            cur = data.get("players", {}).get(player.player_id)
            if isinstance(cur, dict) and cur:
                self.player.season_stats = cur
        except Exception:
            pass
        try:
            self._stats_snapshot = load_stats()
        except Exception:
            self._stats_snapshot = {}
        self._history_override = list(self._stats_snapshot.get("history", []) or [])
        if callable(getattr(self, "setWindowTitle", None)):
            self.setWindowTitle(f"{player.first_name} {player.last_name}")

        self._is_pitcher = getattr(player, "is_pitcher", False)
        self._comparison_player: Optional[Any] = None
        self._player_pool: Optional[Dict[str, Any]] = None
        self._compare_button: Optional[QPushButton] = None
        self._clear_compare_button: Optional[QPushButton] = None
        self._spray_chart_widget: Optional['SprayChartWidget'] = None
        self._rolling_stats_widget: Optional['RollingStatsWidget'] = None
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._comparison_labels: Dict[str, Tuple[Any, Any]] = {}
        self._comparison_name_label: Optional[QLabel] = None

        root = QVBoxLayout()
        if callable(getattr(root, "setContentsMargins", None)):
            _safe_set_margins(root, 24, 24, 24, 24)
        if callable(getattr(root, "setSpacing", None)):
            _safe_set_spacing(root, 18)

        if HEADLESS_QT:
            stats_history = self._collect_stats_history()
            if stats_history:
                columns = _PITCHING_STATS if self._is_pitcher else _BATTING_STATS
                self._create_stats_table(stats_history, columns)
            return

        header = self._build_header_section()
        _layout_add_widget(root, header)

        self._comparison_panel = self._build_comparison_panel()
        _layout_add_widget(root, self._comparison_panel)
        self._comparison_panel.hide()

        tabs = QTabWidget()
        _safe_call(tabs, "setObjectName", "ProfileTabs")

        overview = self._build_overview_section()
        insights = self._build_insights_section()
        injuries = self._build_injury_history_section()
        overview_tab = self._build_tab_container(
            (overview, insights, injuries),
            empty_message="No additional profile details available.",
        )
        tabs.addTab(overview_tab, "Overview")

        stats_history = self._collect_stats_history()
        stats_tab = self._build_tab_container((self._build_stats_section(stats_history),))
        tabs.addTab(stats_tab, "Stats")

        ledger = self._build_career_ledger_section()
        ledger_tab = self._build_tab_container(
            (ledger,),
            empty_message="Career ledger unavailable.",
        )
        tabs.addTab(ledger_tab, "Career")

        _layout_add_widget(root, tabs)
        _layout_add_stretch(root)
        close_row = QWidget()
        close_layout = QHBoxLayout(close_row)
        _safe_set_margins(close_layout, 0, 0, 0, 0)
        _safe_set_spacing(close_layout, 0)
        _layout_add_stretch(close_layout)
        close_button = QPushButton("Close")
        try:
            close_button.clicked.connect(self.close)
        except Exception:
            pass
        _layout_add_widget(close_layout, close_button)
        _layout_add_widget(root, close_row)
        self.setLayout(root)
        self._update_comparison_panel()
            # Size policy: keep a comfortable default so the dialog fits smaller
            # screens; tabs and scrolling handle overflow content.
        # Size policy: robust against test stubs without real Qt widgets
        try:
            self.adjustSize()
            hint = self.sizeHint()
            # width/height may be callables on real QSize; guard for stubs
            w_attr = getattr(hint, "width", 0)
            h_attr = getattr(hint, "height", 0)
            w = int(w_attr() if callable(w_attr) else w_attr or 0)
            h = int(h_attr() if callable(h_attr) else h_attr or 0)
            min_w = max(min(w, 980), 900)
            min_h = max(min(h, 640), 560)
            self.setMinimumSize(min_w, min_h)
            self.resize(min_w, min_h)
        except Exception:
            # Fallback in headless test stubs
            pass
        try:
            if hasattr(Qt, "WindowState") and hasattr(self, "setWindowState"):
                self.setWindowState(Qt.WindowState.WindowMaximized)
            else:
                _safe_call(self, "showMaximized")
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _build_header_section(self) -> QFrame:
        builder = self._build_pitcher_header if self._is_pitcher else self._build_hitter_header
        widget = builder()
        if widget is None:
            widget = self._build_generic_header()
        return widget

    def _build_avatar_panel(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 6)

        avatar_label = QLabel()
        pix = self._load_avatar_pixmap()
        if not pix.isNull():
            _safe_call(avatar_label, "setPixmap", pix)
        _safe_call(avatar_label, "setFixedSize", 128, 128)
        try:
            _set_alignment(avatar_label, "AlignCenter")
        except Exception:
            pass
        align = _alignment("AlignHCenter", "AlignTop")
        if align is not None:
            _layout_add_widget(layout, avatar_label, alignment=align)
        else:
            _layout_add_widget(layout, avatar_label)
        _layout_add_stretch(layout)
        return wrapper

    def _build_hitter_header(self) -> QFrame | None:
        frame = QFrame()
        _safe_call(frame, "setObjectName", "ProfileHeader")
        outer = QVBoxLayout(frame)
        _safe_set_margins(outer, 18, 18, 18, 18)
        _safe_set_spacing(outer, 12)

        header_row = QHBoxLayout()
        _safe_set_spacing(header_row, 18)

        _layout_add_widget(header_row, self._build_avatar_panel(), 0)
        _layout_add_widget(header_row, self._build_hitter_identity_block(), 2)
        _layout_add_widget(header_row, self._build_overall_block(), 1)
        _layout_add_widget(header_row, self._build_fielding_block(), 1)

        outer.addLayout(header_row)
        _layout_add_widget(outer, self._build_scouting_summary_box())
        _layout_add_widget(outer, self._build_header_actions())
        return frame

    def _build_hitter_identity_block(self) -> QWidget:
        panel = QWidget()
        layout = QGridLayout(panel)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_hspacing(layout, 8)
        _safe_set_vspacing(layout, 4)

        name = QLabel(f"{self.player.first_name} {self.player.last_name}")
        _safe_call(name, "setObjectName", "PlayerName")
        _safe_call(name, "setProperty", "profile", "name")
        _layout_add_widget(layout, name, 0, 0, 1, 2)

        age = self._calculate_age(self.player.birthdate)
        _layout_add_widget(layout, QLabel(f"Age: {age}"), 1, 0)
        _layout_add_widget(layout, QLabel(f"Bats: {getattr(self.player, 'bats', '?')}"), 1, 1)
        _layout_add_widget(layout, QLabel(f"Height: {self._format_height(getattr(self.player, 'height', None))}"), 2, 0)
        _layout_add_widget(layout, QLabel(f"Weight: {getattr(self.player, 'weight', '?')}"), 2, 1)

        positions = [self.player.primary_position, *getattr(self.player, 'other_positions', [])]
        positions = [p for p in positions if p]
        pos_label = ', '.join(positions) if positions else '?'
        _layout_add_widget(layout, QLabel(f"Positions: {pos_label}"), 3, 0, 1, 2)

        gf_display = rating_display_text(
            getattr(self.player, "gf", "?"),
            key="GF",
            position=getattr(self.player, "primary_position", None),
            is_pitcher=False,
        )
        _layout_add_widget(
            layout, QLabel(f"Groundball/Flyball: {gf_display}"), 4, 0, 1, 2
        )
        return panel

    def _build_overall_block(self, *, title: str = "Overall", overall: int | None = None) -> QWidget:
        wrapper = QFrame()
        _safe_call(wrapper, "setObjectName", "OverallBlock")
        wrapper.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(wrapper)
        _safe_set_margins(layout, 12, 12, 12, 12)
        _safe_set_spacing(layout, 6)

        header = QLabel(title)
        _set_alignment(header, "AlignCenter")
        _layout_add_widget(layout, header)

        overall_val = overall if overall is not None else getattr(self.player, 'overall', None)
        if not isinstance(overall_val, (int, float)):
            overall_val = self._estimate_overall_rating()
        display_val = self._overall_display_value(overall_val, self.player)
        star_source = display_val if display_val is not None else overall_val

        overall_label = star_label(
            star_source,
            min_rating=35.0,
            max_rating=99.0,
            size=18,
        )
        _safe_call(overall_label, "setObjectName", "OverallValue")
        _set_alignment(overall_label, "AlignCenter")
        _layout_add_widget(layout, overall_label)

        return wrapper

    def _format_overall_stars(self, value: Any) -> str:
        display_val = self._overall_display_value(value, self.player)
        star_source = display_val if display_val is not None else value
        fallback = star_text(star_source, min_rating=35.0, max_rating=99.0)
        return fallback if fallback is not None else str(value)

    def _apply_overall_star_label(self, label: QLabel, player: Any) -> None:
        value = getattr(player, "overall", None) if player is not None else None
        if not isinstance(value, (int, float)):
            value = (
                self._estimate_overall_rating()
                if player is self.player
                else getattr(player, "overall", None)
            )
        display_val = self._overall_display_value(value, player)
        star_source = display_val if display_val is not None else value
        pix = star_pixmap(
            star_source,
            min_rating=35.0,
            max_rating=99.0,
            size=14,
        )
        if pix is not None:
            label.setPixmap(pix)
            label.setText("")
            _set_alignment(label, "AlignCenter")
            return
        label.setPixmap(QPixmap())
        label.setText(self._format_overall_stars(value))

    def _overall_display_value(self, value: Any, player: Any) -> Optional[float]:
        if not isinstance(value, (int, float)):
            return None
        if player is self.player:
            is_pitcher = self._is_pitcher
        else:
            is_pitcher = bool(
                getattr(player, "is_pitcher", False)
                or str(getattr(player, "primary_position", "")).upper() == "P"
            )
        display_val = rating_display_value(
            value,
            key="OVR",
            position=getattr(player, "primary_position", None),
            is_pitcher=is_pitcher,
            mode="scale_99",
        )
        try:
            return float(display_val)
        except (TypeError, ValueError):
            return None

    def _build_fielding_block(self) -> QWidget:
        wrapper = QFrame()
        _safe_call(wrapper, "setObjectName", "FieldingBlock")
        wrapper.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(wrapper)
        _safe_set_margins(layout, 12, 12, 12, 12)
        _safe_set_spacing(layout, 6)

        title = QLabel("Defense")
        _set_alignment(title, "AlignCenter")
        _layout_add_widget(layout, title)

        diagram = QLabel()
        _set_alignment(diagram, "AlignCenter")
        _safe_call(diagram, "setObjectName", "FieldDiagram")
        pix = self._load_field_diagram_pixmap()
        if pix is not None:
            scaled = pix.scaled(
                160,
                130,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            diagram.setPixmap(scaled)
        else:
            diagram.setText("Field Chart")
            diagram.setMinimumSize(160, 130)
        _layout_add_widget(layout, diagram)

        metrics = QWidget()
        grid = QGridLayout(metrics)
        _safe_set_margins(grid, 0, 0, 0, 0)
        _safe_set_hspacing(grid, 12)
        _safe_set_vspacing(grid, 4)

        metric_pairs = [
            (
                "Fielding",
                rating_display_text(
                    getattr(self.player, "fa", "?"),
                    key="FA",
                    position=getattr(self.player, "primary_position", None),
                    is_pitcher=False,
                ),
            ),
            (
                "Arm",
                rating_display_text(
                    getattr(self.player, "arm", "?"),
                    key="AS",
                    position=getattr(self.player, "primary_position", None),
                    is_pitcher=False,
                ),
            ),
            (
                "Speed",
                rating_display_text(
                    getattr(self.player, "sp", "?"),
                    key="SP",
                    position=getattr(self.player, "primary_position", None),
                    is_pitcher=False,
                ),
            ),
        ]
        for row, (label, value) in enumerate(metric_pairs):
            _layout_add_widget(grid, QLabel(label), row, 0)
            _layout_add_widget(grid, QLabel(str(value)), row, 1)

        _layout_add_widget(layout, metrics)
        return wrapper

    def _build_scouting_summary_box(self) -> QWidget:
        box = QFrame()
        _safe_call(box, "setObjectName", "ScoutingBox")
        box.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(box)
        _safe_set_margins(layout, 12, 12, 12, 12)
        _safe_set_spacing(layout, 6)

        summary = getattr(self.player, 'summary', '') or "No scouting report available."
        label = QLabel(summary)
        label.setWordWrap(True)
        _layout_add_widget(layout, label)
        status_label = self._build_injury_status_label()
        if status_label is not None:
            _layout_add_widget(layout, status_label)
        return box

    def _build_injury_status_label(self) -> QLabel | None:
        injured = bool(getattr(self.player, 'injured', False))
        list_name = getattr(self.player, 'injury_list', None)
        return_date = getattr(self.player, 'return_date', None) or ""
        ready_flag = getattr(self.player, 'ready', True)
        info: List[str] = []

        if list_name:
            list_label = disabled_list_label(list_name)
            days = disabled_list_days_remaining(self.player)
            if days is None:
                detail = "status pending"
            elif days <= 0:
                detail = "eligible to return now"
            else:
                detail = f"{days} day(s) remaining"
            info.append(f"{list_label}: {detail}")
            desc = getattr(self.player, 'injury_description', None)
            if desc:
                info.append(f"Injury: {desc}")
        elif injured:
            desc = getattr(self.player, 'injury_description', None) or "Injured"
            info.append(f"Injury: {desc}")

        if return_date:
            info.append(f"ETA: {return_date}")

        if list_name and ready_flag:
            info.append("Ready for activation")
        elif not injured and not ready_flag:
            info.append("Not yet game-ready")

        if not info:
            return None

        text = "Health Monitor:\n" + "\n".join(info)
        label = QLabel(text)
        label.setWordWrap(True)
        _safe_call(label, "setProperty", "profile", "injury-status")
        return label

    def _build_pitcher_header(self) -> QFrame | None:
        frame = QFrame()
        _safe_call(frame, "setObjectName", "ProfileHeader")

        outer = QVBoxLayout(frame)
        _safe_set_margins(outer, 18, 18, 18, 18)
        _safe_set_spacing(outer, 12)

        header_row = QHBoxLayout()
        _safe_set_spacing(header_row, 18)

        _layout_add_widget(header_row, self._build_avatar_panel(), 0)
        _layout_add_widget(header_row, self._build_pitcher_identity_block(), 2)
        _layout_add_widget(header_row, self._build_overall_block(), 1)
        _layout_add_widget(header_row, self._build_pitcher_arsenal_block(), 1)

        outer.addLayout(header_row)
        _layout_add_widget(outer, self._build_pitcher_summary_box())
        _layout_add_widget(outer, self._build_header_actions())
        return frame

    def _build_pitcher_identity_block(self) -> QWidget:
        panel = QWidget()
        layout = QGridLayout(panel)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_hspacing(layout, 8)
        _safe_set_vspacing(layout, 4)

        name = QLabel(f"{self.player.first_name} {self.player.last_name}")
        _safe_call(name, "setObjectName", "PlayerName")
        _safe_call(name, "setProperty", "profile", "name")
        _layout_add_widget(layout, name, 0, 0, 1, 2)

        age = self._calculate_age(self.player.birthdate)
        role = getattr(self.player, 'role', '') or 'Pitcher'
        _layout_add_widget(layout, QLabel(f"Age: {age}"), 1, 0)
        _layout_add_widget(layout, QLabel(f"Role: {role}"), 1, 1)

        bats = getattr(self.player, "bats", "?")
        gf_display = rating_display_text(
            getattr(self.player, "gf", "?"), key="GF", is_pitcher=True
        )
        _layout_add_widget(layout, QLabel(f"Bats: {bats}"), 2, 0)
        _layout_add_widget(layout, QLabel(f"GF: {gf_display}"), 2, 1)

        control_display = rating_display_text(
            getattr(self.player, "control", "?"), key="CO", is_pitcher=True
        )
        movement_display = rating_display_text(
            getattr(self.player, "movement", "?"), key="MO", is_pitcher=True
        )
        _layout_add_widget(layout, QLabel(f"Control: {control_display}"), 3, 0)
        _layout_add_widget(layout, QLabel(f"Movement: {movement_display}"), 3, 1)

        endurance_display = rating_display_text(
            getattr(self.player, "endurance", "?"), key="EN", is_pitcher=True
        )
        hold_display = rating_display_text(
            getattr(self.player, "hold_runner", "?"),
            key="hold_runner",
            is_pitcher=True,
        )
        _layout_add_widget(layout, QLabel(f"Endurance: {endurance_display}"), 4, 0)
        _layout_add_widget(layout, QLabel(f"Hold Runner: {hold_display}"), 4, 1)
        return panel

    def _build_pitcher_arsenal_block(self) -> QWidget:
        wrapper = QFrame()
        _safe_call(wrapper, "setObjectName", "ArsenalBlock")
        wrapper.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QGridLayout(wrapper)
        _safe_set_margins(layout, 12, 12, 12, 12)
        _safe_set_hspacing(layout, 12)
        _safe_set_vspacing(layout, 6)

        title = QLabel("Pitch Arsenal")
        _set_alignment(title, "AlignCenter")
        _layout_add_widget(layout, title, 0, 0, 1, 2)

        pitch_labels = {
            'fb': 'Fastball',
            'si': 'Sinker',
            'sl': 'Slider',
            'cu': 'Changeup',
            'cb': 'Curveball',
            'scb': 'Screwball',
            'kn': 'Knuckle',
        }
        values = []
        for key, label in pitch_labels.items():
            value = getattr(self.player, key, None)
            if isinstance(value, (int, float)) and value > 0:
                values.append((label, int(value), key))
        if not values:
            _layout_add_widget(layout, QLabel("No pitch data"), 1, 0, 1, 2)
            return wrapper

        max_value = max(v for _, v, _ in values)
        for idx, (label, value, key) in enumerate(values, start=1):
            row = idx
            _layout_add_widget(layout, QLabel(label), row, 0)
            value_label = QLabel(
                rating_display_text(value, key=key, is_pitcher=True)
            )
            if value == max_value:
                _safe_call(value_label, "setProperty", "highlight", True)
            _layout_add_widget(layout, value_label, row, 1)

        return wrapper

    def _build_pitcher_summary_box(self) -> QWidget:
        box = self._build_scouting_summary_box()
        layout = box.layout()
        if layout is not None:
            fatigue = getattr(self.player, 'fatigue', '').replace('_', ' ').title()
            fatigue_text = fatigue or 'Fresh'
            _layout_add_widget(layout, QLabel(f"Fatigue: {fatigue_text}"))
        return box

    def _build_generic_header(self) -> QFrame:
        frame = QFrame()
        _safe_call(frame, "setObjectName", "ProfileHeader")
        outer = QVBoxLayout(frame)
        _safe_set_margins(outer, 18, 18, 18, 18)
        _safe_set_spacing(outer, 12)
        _layout_add_widget(outer, section_title("Player Profile"))

        body = QWidget()
        body_layout = QHBoxLayout(body)
        _safe_set_margins(body_layout, 0, 0, 0, 0)
        _safe_set_spacing(body_layout, 18)

        _layout_add_widget(body_layout, self._build_avatar_panel(), 0)
        _layout_add_widget(body_layout, self._build_identity_panel(), 1)
        _layout_add_widget(body_layout, self._build_role_panel(), 1)

        _layout_add_widget(outer, body)
        _layout_add_widget(outer, self._build_header_actions())
        return frame

    def _build_header_actions(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 8)
        _layout_add_stretch(layout)

        compare_btn = QPushButton("Compare...")
        _safe_call(compare_btn, "setObjectName", "SecondaryButton")
        compare_btn.clicked.connect(self._prompt_comparison_player)
        _layout_add_widget(layout, compare_btn)

        clear_btn = QPushButton("Clear Compare")
        _safe_call(clear_btn, "setObjectName", "SecondaryButton")
        clear_btn.clicked.connect(self._clear_comparison)
        clear_btn.hide()
        _layout_add_widget(layout, clear_btn)

        self._compare_button = compare_btn
        self._clear_compare_button = clear_btn
        return bar


    def _load_avatar_pixmap(self) -> QPixmap:
        pix = QPixmap(f"images/avatars/{self.player.player_id}.png")
        if pix.isNull():
            pix = QPixmap("images/avatars/default.png")
        if pix.isNull():
            placeholder = QPixmap(128, 128)
            try:
                color = getattr(getattr(Qt, "GlobalColor", None), "darkGray", None)
            except Exception:
                color = None
            try:
                placeholder.fill(color if color is not None else 0)
            except Exception:
                pass
            return placeholder
        return pix.scaled(
            128,
            128,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _load_field_diagram_pixmap(self) -> QPixmap | None:
        if PlayerProfileDialog._FIELD_DIAGRAM_CACHE is None:
            path = get_base_dir() / "assets" / "field_diagram.png"
            if path.exists():
                PlayerProfileDialog._FIELD_DIAGRAM_CACHE = QPixmap(str(path))
        return PlayerProfileDialog._FIELD_DIAGRAM_CACHE

    def _get_stats_cache(self) -> Dict[str, Any]:
        if self._stats_cache is None:
            try:
                self._stats_cache = load_stats().get("players", {})
            except Exception:
                self._stats_cache = {}
        return self._stats_cache

    def _attach_player_stats(self, player: Any) -> None:
        if getattr(player, "season_stats", None):
            return
        try:
            stats = self._get_stats_cache().get(getattr(player, "player_id", None))
            if stats:
                player.season_stats = stats
        except Exception:
            pass

    def _player_stats(self, player: Any) -> Dict[str, Any]:
        stats = getattr(player, "season_stats", None)
        if isinstance(stats, dict):
            return stats
        return {}

    def _player_display_name(self, player: Any) -> str:
        first = str(getattr(player, "first_name", "").strip())
        last = str(getattr(player, "last_name", "").strip())
        pid = str(getattr(player, "player_id", "--"))
        full = " ".join(part for part in (first, last) if part)
        return f"{full} [{pid}]" if full else pid

    def _load_player_pool(self) -> Dict[str, Any]:
        if self._player_pool is None:
            try:
                players = load_players_from_csv("data/players.csv")
            except Exception:
                players = []
            self._player_pool = {p.player_id: p for p in players if getattr(p, "player_id", None)}
        return self._player_pool

    def _build_comparison_panel(self) -> Card:
        card = Card()
        layout = card.layout()
        _layout_add_widget(layout, section_title("Comparison"))

        grid = QGridLayout()
        _safe_set_margins(grid, 0, 0, 0, 0)
        _safe_set_hspacing(grid, 12)
        _safe_set_vspacing(grid, 6)

        header_label = QLabel("Metric")
        header_label.setStyleSheet("font-weight:600;")
        _layout_add_widget(grid, header_label, 0, 0)
        primary_name = QLabel(self._player_display_name(self.player))
        primary_name.setStyleSheet("font-weight:600;")
        self._comparison_name_label = QLabel("--")
        self._comparison_name_label.setStyleSheet("font-weight:600;")
        _layout_add_widget(grid, primary_name, 0, 1)
        _layout_add_widget(grid, self._comparison_name_label, 0, 2)

        for idx, (metric_id, label) in enumerate(self._comparison_metric_definitions(), start=1):
            title = QLabel(label)
            _layout_add_widget(grid, title, idx, 0)
            primary_label = QLabel("--")
            compare_label = QLabel("--")
            _layout_add_widget(grid, primary_label, idx, 1)
            _layout_add_widget(grid, compare_label, idx, 2)
            self._comparison_labels[metric_id] = (primary_label, compare_label)

        layout.addLayout(grid)
        _layout_add_stretch(layout)
        return card


    def _comparison_metric_definitions(self) -> List[tuple[str, str]]:
        if self._is_pitcher:
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

    def _metric_value(self, player: Any, metric_id: str) -> str:
        if player is None:
            return "--"
        stats = self._player_stats(player)
        def safe(key: str) -> float:
            value = stats.get(key, 0)
            try:
                return float(value or 0)
            except Exception:
                return 0.0

        if metric_id == "overall":
            value = getattr(player, "overall", None)
            if not isinstance(value, (int, float)):
                value = self._estimate_overall_rating() if player is self.player else getattr(player, "overall", "--")
            return self._format_overall_stars(value)
        if metric_id == "avg":
            ab = safe("ab")
            hits = safe("h")
            return f"{hits / ab:.3f}" if ab else "--"
        if metric_id == "ops":
            obp = self._calculate_obp(stats)
            slg = self._calculate_slg(stats)
            total = obp + slg
            return f"{total:.3f}" if total else "--"
        if metric_id == "hr":
            hr = stats.get("hr")
            return str(int(hr)) if isinstance(hr, (int, float)) else "--"
        if metric_id == "rbi":
            rbi = stats.get("rbi")
            return str(int(rbi)) if isinstance(rbi, (int, float)) else "--"
        if metric_id == "speed":
            value = getattr(player, "sp", getattr(player, "speed", "--"))
            return rating_display_text(
                value,
                key="SP",
                position=getattr(player, "primary_position", None),
                is_pitcher=False,
            )
        if metric_id == "power":
            value = getattr(player, "ph", getattr(player, "power", "--"))
            return rating_display_text(
                value,
                key="PH",
                position=getattr(player, "primary_position", None),
                is_pitcher=False,
            )
        if metric_id == "contact":
            value = getattr(player, "ch", getattr(player, "contact", "--"))
            return rating_display_text(
                value,
                key="CH",
                position=getattr(player, "primary_position", None),
                is_pitcher=False,
            )
        if metric_id == "defense":
            value = getattr(player, "fa", getattr(player, "defense", "--"))
            return rating_display_text(
                value,
                key="FA",
                position=getattr(player, "primary_position", None),
                is_pitcher=False,
            )
        if metric_id == "era":
            outs = safe("outs")
            ip = outs / 3 if outs else 0
            er = safe("er")
            return f"{(er * 9) / ip:.2f}" if ip else "--"
        if metric_id == "whip":
            outs = safe("outs")
            ip = outs / 3 if outs else 0
            if not ip:
                return "--"
            bb = safe("bb")
            hits = safe("h")
            return f"{(bb + hits) / ip:.2f}"
        if metric_id == "k9":
            outs = safe("outs")
            ip = outs / 3 if outs else 0
            if not ip:
                return "--"
            so = safe("so")
            return f"{(so * 9) / ip:.2f}"
        if metric_id == "bb9":
            outs = safe("outs")
            ip = outs / 3 if outs else 0
            if not ip:
                return "--"
            walk = safe("bb")
            return f"{(walk * 9) / ip:.2f}"
        if metric_id == "control":
            return rating_display_text(
                getattr(player, "control", "--"), key="CO", is_pitcher=True
            )
        if metric_id == "movement":
            return rating_display_text(
                getattr(player, "movement", "--"), key="MO", is_pitcher=True
            )
        if metric_id == "endurance":
            return rating_display_text(
                getattr(player, "endurance", "--"), key="EN", is_pitcher=True
            )
        return str(getattr(player, metric_id, "--"))

    def _build_insights_section(self) -> Card | None:
        history = load_player_training_history(getattr(self.player, "player_id", ""), limit=3)
        if not history:
            return None

        card = Card()
        layout = card.layout()
        if layout is None:
            return None

        _layout_add_widget(layout, section_title("Recent Training Focus"))

        for idx, entry in enumerate(history):
            header = QLabel(self._format_training_header(entry))
            _safe_call(header, "setWordWrap", True)
            _safe_call(header, "setProperty", "profile", "training-header")
            _layout_add_widget(layout, header)

            note = str(entry.get("note") or "").strip()
            if note:
                note_label = QLabel(note)
                _safe_call(note_label, "setWordWrap", True)
                _safe_call(note_label, "setProperty", "profile", "training-note")
                _layout_add_widget(layout, note_label)

            if idx < len(history) - 1:
                _safe_call(layout, "addSpacing", 8)

        return card

    def _build_injury_history_section(self) -> Card | None:
        history = load_player_injury_history(getattr(self.player, "player_id", ""), limit=10)
        if not history:
            return None

        card = Card()
        layout = card.layout()
        if layout is None:
            return None

        _layout_add_widget(layout, section_title("Injury History"))
        for idx, entry in enumerate(history):
            date = str(entry.get("date") or "").strip()
            if "T" in date:
                date = date.split("T", 1)[0]
            description = str(entry.get("description") or "Injury").strip()
            if date:
                text = f"{date} - {description}"
            else:
                season = str(entry.get("season_id") or "").strip()
                text = f"{season} - {description}" if season else description
            label = QLabel(text)
            _safe_call(label, "setWordWrap", True)
            _layout_add_widget(layout, label)
            if idx < len(history) - 1:
                _safe_call(layout, "addSpacing", 6)

        return card

    def _format_training_header(self, entry: Dict[str, object]) -> str:
        season = str(entry.get("season_id") or "").strip() or "Season"
        focus = str(entry.get("focus") or "").strip() or "Training Focus"
        run_at = str(entry.get("run_at") or "").strip()
        if "T" in run_at:
            run_at = run_at.split("T", 1)[0]
        changes = entry.get("changes") or {}
        change_bits: List[str] = []
        if isinstance(changes, dict):
            for attr, value in changes.items():
                if isinstance(attr, str) and isinstance(value, (int, float)) and value:
                    sign = "+" if value >= 0 else ""
                    change_bits.append(f"{attr.upper()} {sign}{int(value)}")
        seasonal = f"{season} • {focus}"
        if change_bits:
            seasonal += f" ({', '.join(change_bits)})"
        if run_at:
            return f"{run_at}: {seasonal}"
        return seasonal

    def _compute_spray_points(self) -> List[Dict[str, float]]:
        stats = self._player_stats(self.player)
        singles = int(stats.get("b1", 0) or 0)
        doubles = int(stats.get("b2", 0) or 0)
        triples = int(stats.get("b3", 0) or 0)
        homers = int(stats.get("hr", 0) or 0)
        total = singles + doubles + triples + homers
        if total <= 0:
            return []

        handed = str(getattr(self.player, "bats", "R")).upper() or "R"
        if handed.startswith("L"):
            side = 1.0
        elif handed.startswith("S"):
            side = 0.0
        else:
            side = -1.0

        points: List[Dict[str, float]] = []

        def add_points(count: int, base_x: float, depth: float, spread: float, kind: str) -> None:
            for idx in range(int(count)):
                seed = hash((self.player.player_id, kind, idx))
                offset = ((seed % 1000) / 999.0) - 0.5
                if side == 0.0:
                    x = base_x + offset * spread
                    if idx % 2 == 0:
                        x *= -1
                else:
                    x = (base_x * side) + offset * spread
                x = max(-0.95, min(0.95, x))
                depth_variation = ((seed // 1000) % 200) / 1000.0 - 0.1
                y = max(0.1, min(1.0, depth + depth_variation))
                points.append({"x": x, "y": y, "kind": kind})

        add_points(singles, 0.45, 0.35, 0.25, "1B")
        add_points(doubles, 0.25, 0.60, 0.20, "2B")
        add_points(triples, 0.05, 0.80, 0.20, "3B")
        add_points(homers, 0.00, 1.00, 0.15, "HR")
        return points

    def _compute_rolling_stats(self) -> Dict[str, Any]:
        history_dir = get_base_dir() / "data" / "season_history"
        if not history_dir.exists():
            return {"dates": [], "series": {}}

        snapshots = sorted(history_dir.glob("*.json"))
        dates: List[str] = []
        series: Dict[str, List[float]] = {}
        if self._is_pitcher:
            metric_specs = [("ERA", "era"), ("WHIP", "whip")]
        else:
            metric_specs = [("AVG", "avg"), ("OPS", "ops")]
        for label, _ in metric_specs:
            series[label] = []

        for path in snapshots[-12:]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            stats = payload.get("players", {}).get(self.player.player_id)
            if not stats:
                continue
            dates.append(path.stem)
            temp_stats = stats
            for label, metric_id in metric_specs:
                if metric_id == "avg":
                    ab = float(temp_stats.get("ab", 0) or 0)
                    hits = float(temp_stats.get("h", 0) or 0)
                    value = hits / ab if ab else 0.0
                elif metric_id == "ops":
                    value = self._calculate_obp(temp_stats) + self._calculate_slg(temp_stats)
                elif metric_id == "era":
                    outs = float(temp_stats.get("outs", 0) or 0)
                    ip = outs / 3 if outs else 0.0
                    er = float(temp_stats.get("er", 0) or 0)
                    value = (er * 9) / ip if ip else 0.0
                elif metric_id == "whip":
                    outs = float(temp_stats.get("outs", 0) or 0)
                    ip = outs / 3 if outs else 0.0
                    walks = float(temp_stats.get("bb", 0) or 0)
                    hits_allowed = float(temp_stats.get("h", 0) or 0)
                    value = (walks + hits_allowed) / ip if ip else 0.0
                else:
                    value = 0.0
                series[label].append(round(value, 3))

        return {"dates": dates, "series": series}


    def _prompt_comparison_player(self) -> None:
        pool = self._load_player_pool().copy()
        selector = ComparisonSelectorDialog(pool, self.player.player_id, self)
        if selector.exec():
            chosen = selector.selected_player
            if chosen is None:
                return
            self._attach_player_stats(chosen)
            self._comparison_player = chosen
            self._update_comparison_panel()

    def _clear_comparison(self) -> None:
        self._comparison_player = None
        self._update_comparison_panel()

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
            if metric_id == "overall":
                self._apply_overall_star_label(primary_label, self.player)
                if has_compare:
                    self._apply_overall_star_label(
                        compare_label, self._comparison_player
                    )
                else:
                    compare_label.setPixmap(QPixmap())
                    compare_label.setText("--")
                continue
            primary_label.setText(self._metric_value(self.player, metric_id))
            compare_label.setText(
                self._metric_value(self._comparison_player, metric_id)
                if has_compare
                else "--"
            )
        if self._comparison_panel is not None:
            if has_compare:
                self._comparison_panel.show()
                if self._clear_compare_button is not None:
                    self._clear_compare_button.show()
            else:
                self._comparison_panel.hide()
                if self._clear_compare_button is not None:
                    self._clear_compare_button.hide()

    def _calculate_obp(self, stats: Dict[str, Any]) -> float:
        h = float(stats.get("h", 0) or 0)
        bb = float(stats.get("bb", 0) or 0)
        hbp = float(stats.get("hbp", 0) or 0)
        ab = float(stats.get("ab", 0) or 0)
        sf = float(stats.get("sf", 0) or 0)
        denom = ab + bb + hbp + sf
        if denom <= 0:
            return 0.0
        return (h + bb + hbp) / denom

    def _calculate_slg(self, stats: Dict[str, Any]) -> float:
        ab = float(stats.get("ab", 0) or 0)
        if ab <= 0:
            return 0.0
        singles = float(stats.get("b1", 0) or 0)
        doubles = float(stats.get("b2", 0) or 0)
        triples = float(stats.get("b3", 0) or 0)
        homers = float(stats.get("hr", 0) or 0)
        total_bases = singles + (2 * doubles) + (3 * triples) + (4 * homers)
        return total_bases / ab


    def _build_identity_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 4)

        name = QLabel(f"{self.player.first_name} {self.player.last_name}")
        _safe_call(name, "setObjectName", "PlayerName")
        _layout_add_widget(layout, name)

        age = self._calculate_age(self.player.birthdate)
        info_lines = [
            f"Age: {age}",
            f"Height: {self._format_height(getattr(self.player, 'height', None))}",
            f"Weight: {getattr(self.player, 'weight', '?')}",
            f"Bats: {getattr(self.player, 'bats', '?')}",
        ]
        positions = [self.player.primary_position, *getattr(self.player, 'other_positions', [])]
        positions = [p for p in positions if p]
        if positions:
            info_lines.append("Positions: " + ", ".join(positions))
        for line in info_lines:
            _layout_add_widget(layout, QLabel(line))

        _layout_add_stretch(layout)
        return panel

    def _build_role_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 4)

        if self._is_pitcher:
            role = getattr(self.player, 'role', '') or 'Pitcher'
            _layout_add_widget(layout, QLabel(f"Role: {role}"))
            gf_display = rating_display_text(
                getattr(self.player, "gf", "?"), key="GF", is_pitcher=True
            )
            _layout_add_widget(layout, QLabel(f"GF: {gf_display}"))
        else:
            _layout_add_widget(layout, QLabel(f"Primary: {self.player.primary_position}"))
            others = [p for p in getattr(self.player, 'other_positions', []) if p]
            if others:
                _layout_add_widget(layout, QLabel("Other: " + ", ".join(others)))
            gf_display = rating_display_text(
                getattr(self.player, "gf", "?"),
                key="GF",
                position=getattr(self.player, "primary_position", None),
                is_pitcher=False,
            )
            _layout_add_widget(layout, QLabel(f"GF: {gf_display}"))

        _layout_add_stretch(layout)
        return panel

    def _build_overview_section(self) -> QWidget | None:
        ratings = self._collect_ratings()
        if not ratings:
            return None

        card = Card()
        layout = card.layout()
        _layout_add_widget(layout, section_title("Ratings"))

        grid = QGridLayout()
        _safe_set_margins(grid, 0, 0, 0, 0)
        _safe_set_hspacing(grid, 18)
        _safe_set_vspacing(grid, 8)

        for col, (label, key, value) in enumerate(ratings):
            header = QLabel(label)
            _set_alignment(header, "AlignCenter")
            position = None
            if not self._is_pitcher:
                position = getattr(self.player, "primary_position", None)
            value_label = QLabel(
                rating_display_text(
                    value,
                    key=key,
                    position=position,
                    is_pitcher=self._is_pitcher,
                )
            )
            _set_alignment(value_label, "AlignCenter")
            _layout_add_widget(grid, header, 0, col)
            _layout_add_widget(grid, value_label, 1, col)

        grid_widget = QWidget()
        grid_widget.setLayout(grid)
        _layout_add_widget(layout, grid_widget)
        return card

    def _create_stats_table(self, rows: List[Tuple[str, Dict[str, Any]]], columns: List[str]) -> QTableWidget:
        table = QTableWidget(len(rows), len(columns) + 1)
        _safe_call(table, "setObjectName", "StatsTable")
        try:
            font = table.font()
            if hasattr(font, "setPointSize"):
                point = font.pointSize()
                if point > 0:
                    font.setPointSize(max(10, point - 1))
                    table.setFont(font)
            header_font = table.horizontalHeader().font() if hasattr(table.horizontalHeader(), "font") else None
            if header_font and hasattr(header_font, "setPointSize"):
                point = header_font.pointSize()
                if point > 0:
                    header_font.setPointSize(max(10, point - 1))
                    table.horizontalHeader().setFont(header_font)
        except Exception:
            pass
        headers = ["Year"] + [c.upper() for c in columns]
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        try:
            table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            table.setSizeAdjustPolicy(QAbstractItemView.SizeAdjustPolicy.AdjustToContents)
        except Exception:
            pass

        header = table.horizontalHeader()
        try:
            header.setStretchLastSection(False)
            for idx in range(len(headers)):
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        except Exception:
            pass

        for row_idx, (year, data) in enumerate(rows):
            label_text = str(year)
            if isinstance(year, str) and year.strip().lower() in {"season", "current"}:
                try:
                    label_text = f"{self._current_season_year():04d}"
                except Exception:
                    label_text = year
            label_lower = label_text.lower()
            if "career" in label_lower:
                row_role = "career"
            elif "current" in label_lower:
                row_role = "current"
            else:
                row_role = "history"

            year_item = self._stat_item(label_text, align_left=True)
            year_item.setData(Qt.ItemDataRole.UserRole, row_role)
            table.setItem(row_idx, 0, year_item)

            for col_idx, key in enumerate(columns, start=1):
                value = data.get(key, "")
                item = self._stat_item(value)
                item.setData(Qt.ItemDataRole.UserRole, row_role)
                table.setItem(row_idx, col_idx, item)
        table.setSortingEnabled(True)
        try:
            table.resizeColumnsToContents()
            total_width = table.verticalHeader().width()
            for idx in range(len(headers)):
                total_width += table.columnWidth(idx)
            total_width += (table.frameWidth() * 2) + 24
            table.setMinimumWidth(min(total_width, 900))
            if hasattr(table.horizontalHeader(), "setStretchLastSection"):
                table.horizontalHeader().setStretchLastSection(False)
        except Exception:
            pass
        return table

    def _create_stats_summary(self, rows: List[Tuple[str, Dict[str, Any]]], columns: List[str]) -> QWidget | None:
        target = None
        for label, data in rows:
            if label.lower() == "career" and data:
                target = data
                break
        if target is None and rows:
            target = rows[-1][1]
        if not target:
            return None

        panel = QWidget()
        grid = QGridLayout(panel)
        _safe_set_margins(grid, 12, 12, 12, 12)
        _safe_set_hspacing(grid, 18)
        _safe_set_vspacing(grid, 8)

        display_columns = columns[:6]
        for idx, key in enumerate(display_columns):
            label = QLabel(key.upper())
            _set_alignment(label, "AlignLeft", "AlignVCenter")
            value = QLabel(self._format_stat(target.get(key, "")))
            _set_alignment(value, "AlignRight", "AlignVCenter")
            _layout_add_widget(grid, label, idx, 0)
            _layout_add_widget(grid, value, idx, 1)
        return panel

    def _build_stat_key_footer(self) -> QWidget:
        footer = QWidget()
        _safe_call(footer, "setObjectName", "StatFooter")
        layout = QHBoxLayout(footer)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 8)

        _layout_add_widget(layout, QLabel("Stat Key:"))
        chips = [
            ("Current Season", "current"),
            ("Career Totals", "career"),
            ("History", "history"),
        ]
        for text, variant in chips:
            chip = QLabel(text)
            _safe_call(chip, "setObjectName", "StatChip")
            _safe_call(chip, "setProperty", "variant", variant)
            _set_alignment(chip, "AlignCenter")
            chip.setMinimumWidth(90)
            chip.setMargin(4)
            _layout_add_widget(layout, chip)
        leader_chip = QLabel("* League Leader")
        _safe_call(leader_chip, "setObjectName", "StatChip")
        _safe_call(leader_chip, "setProperty", "variant", "leader")
        _set_alignment(leader_chip, "AlignCenter")
        leader_chip.setMinimumWidth(110)
        leader_chip.setMargin(4)
        _layout_add_widget(layout, leader_chip)
        _layout_add_stretch(layout)
        return footer

    def _estimate_overall_rating(self) -> int:
        if self._is_pitcher:
            keys = [
                "endurance",
                "control",
                "movement",
                "hold_runner",
                "arm",
                "fa",
                "fb",
                "cu",
                "cb",
                "sl",
                "si",
                "scb",
                "kn",
            ]
        else:
            keys = [
                "ch",
                "ph",
                "sp",
                "pl",
                "vl",
                "sc",
                "fa",
                "arm",
                "gf",
            ]
        values = [getattr(self.player, key, 0) for key in keys]
        numeric = [v for v in values if isinstance(v, (int, float))]
        if not numeric:
            return 0
        return max(0, min(99, int(round(sum(numeric) / len(numeric)))))

    def _estimate_peak_rating(self) -> int:
        potential = getattr(self.player, 'potential', {}) or {}
        if not potential:
            return self._estimate_overall_rating()
        if self._is_pitcher:
            keys = [
                "control",
                "movement",
                "endurance",
                "hold_runner",
                "arm",
                "fa",
                "fb",
                "cu",
                "cb",
                "sl",
                "si",
                "scb",
                "kn",
            ]
        else:
            keys = [
                "ch",
                "ph",
                "sp",
                "pl",
                "vl",
                "sc",
                "fa",
                "arm",
                "gf",
            ]
        values = [potential.get(key, getattr(self.player, key, 0)) for key in keys]
        numeric = [v for v in values if isinstance(v, (int, float))]
        if not numeric:
            return self._estimate_overall_rating()
        return max(0, min(99, int(round(sum(numeric) / len(numeric)))))

    def _build_stats_section(self, rows: List[Tuple[str, Dict[str, Any]]]) -> Card:
        card = Card()
        layout = card.layout()
        _layout_add_widget(layout, section_title("Stats"))
        try:
            year_label = QLabel(f"{self._current_season_year():04d}")
            _safe_call(year_label, "setObjectName", "SeasonYearLabel")
            _layout_add_widget(layout, year_label)
        except Exception:
            pass

        if not rows:
            _layout_add_widget(layout, QLabel("No stats available"))
            return card

        columns = _PITCHING_STATS if self._is_pitcher else _BATTING_STATS

        tabs = QTabWidget()
        _safe_call(tabs, "setObjectName", "StatsTabs")
        primary_label = "Pitching" if self._is_pitcher else "Batting"
        tabs.addTab(self._create_stats_table(rows, columns), primary_label)

        summary = self._create_stats_summary(rows, columns)
        if summary is not None:
            tabs.addTab(summary, "Summary")

        _layout_add_widget(layout, tabs)
        _layout_add_widget(layout, self._build_stat_key_footer())
        return card

    def _build_career_ledger_section(self) -> Card | None:
        card = Card()
        layout = card.layout()
        if layout is None:
            return None
        _layout_add_widget(layout, section_title("Career Ledger"))
        tabs = QTabWidget()
        _safe_call(tabs, "setObjectName", "CareerLedgerTabs")
        tabs.addTab(self._build_ratings_history_tab(), "Ratings")
        tabs.addTab(self._build_awards_tab(), "Awards")
        tabs.addTab(self._build_records_events_tab(), "Records & Events")
        tabs.addTab(self._build_transactions_tab(), "Transactions")
        tabs.addTab(self._build_transactions_tab(trade_only=True), "Trades")
        _layout_add_widget(layout, tabs)
        return card

    def _build_ratings_history_tab(self) -> QWidget:
        rows = self._collect_ratings_history()
        if not rows:
            return self._build_empty_tab("Ratings history unavailable.")

        fields = _PITCHER_RATING_HISTORY if self._is_pitcher else _HITTER_RATING_HISTORY
        table = QTableWidget(len(rows), len(fields) + 1)
        table.setHorizontalHeaderLabels(["Year"] + [label for _, label in fields])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        try:
            header.setStretchLastSection(False)
            for idx in range(len(fields) + 1):
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        except Exception:
            pass

        for row_idx, (label, data) in enumerate(rows):
            year_item = QTableWidgetItem(str(label))
            _set_text_alignment(year_item, "AlignLeft", "AlignVCenter")
            table.setItem(row_idx, 0, year_item)
            for col_idx, (key, _label) in enumerate(fields, start=1):
                raw = data.get(key)
                text = "--"
                if raw is not None and raw != "":
                    try:
                        text = str(int(float(raw)))
                    except (TypeError, ValueError):
                        text = str(raw)
                item = QTableWidgetItem(text)
                _set_text_alignment(item, "AlignRight", "AlignVCenter")
                table.setItem(row_idx, col_idx, item)

        try:
            table.resizeColumnsToContents()
        except Exception:
            pass

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        _safe_set_margins(wrapper_layout, 0, 0, 0, 0)
        _safe_set_spacing(wrapper_layout, 6)
        _layout_add_widget(wrapper_layout, table)
        if len(rows) <= 1:
            note = QLabel(
                "Historical rating snapshots will appear after season rollover."
            )
            _safe_call(note, "setWordWrap", True)
            _layout_add_widget(wrapper_layout, note)
        _layout_add_stretch(wrapper_layout)
        return wrapper

    def _build_awards_tab(self) -> QWidget:
        entries = self._collect_awards_history()
        if not entries:
            return self._build_empty_tab("No awards recorded.")

        table = QTableWidget(len(entries), 3)
        table.setHorizontalHeaderLabels(["Year", "Award", "Detail"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        try:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass

        for row_idx, entry in enumerate(entries):
            table.setItem(row_idx, 0, QTableWidgetItem(str(entry.get("year", "--"))))
            table.setItem(row_idx, 1, QTableWidgetItem(str(entry.get("award", "--"))))
            table.setItem(row_idx, 2, QTableWidgetItem(str(entry.get("detail", "--"))))

        try:
            table.resizeColumnsToContents()
        except Exception:
            pass
        return table

    def _build_records_events_tab(self) -> QWidget:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        records: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []
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
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 10)

        record_label = QLabel("Records")
        _layout_add_widget(layout, record_label)

        if records:
            records.sort(
                key=lambda item: (item.get("scope") != "career", str(item.get("label") or "")),
            )
            table = QTableWidget(len(records), 3)
            table.setHorizontalHeaderLabels(["Record", "Value", "Season"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setAlternatingRowColors(True)
            header = table.horizontalHeader()
            try:
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            except Exception:
                pass

            for row_idx, entry in enumerate(records):
                holder = entry.get("holder", {}) if isinstance(entry, dict) else {}
                value_text = entry.get("value_text") or entry.get("value") or "--"
                season_label = holder.get("season_label") if isinstance(holder, dict) else None
                if not season_label:
                    season_label = "Career" if entry.get("scope") == "career" else "-"
                table.setItem(row_idx, 0, QTableWidgetItem(str(entry.get("label") or "--")))
                table.setItem(row_idx, 1, QTableWidgetItem(str(value_text)))
                table.setItem(row_idx, 2, QTableWidgetItem(str(season_label)))
            try:
                table.resizeColumnsToContents()
            except Exception:
                pass
            _layout_add_widget(layout, table)
        else:
            _layout_add_widget(layout, QLabel("No record book entries yet."))

        events_label = QLabel("Special Events")
        _layout_add_widget(layout, events_label)

        if events:
            table = QTableWidget(len(events), 4)
            table.setHorizontalHeaderLabels(["Season", "Date", "Event", "Detail"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setAlternatingRowColors(True)
            header = table.horizontalHeader()
            try:
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
                header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            except Exception:
                pass

            for row_idx, entry in enumerate(events):
                season_id = entry.get("season_id") or ""
                league_year = entry.get("league_year")
                season_label = ""
                if league_year:
                    season_label = f"{int(league_year):04d}" if str(league_year).isdigit() else str(league_year)
                if not season_label and season_id:
                    season_label = self._format_season_label(str(season_id))
                date_val = str(entry.get("date") or "--")
                event_label = str(entry.get("label") or entry.get("type") or "--")
                detail = str(entry.get("detail") or "").strip()
                if not detail:
                    team_id = str(entry.get("team_id") or "").strip()
                    opp_id = str(entry.get("opponent_id") or "").strip()
                    if team_id and opp_id:
                        detail = f"{team_id} vs {opp_id}"
                    elif team_id:
                        detail = team_id
                table.setItem(row_idx, 0, QTableWidgetItem(season_label or "--"))
                table.setItem(row_idx, 1, QTableWidgetItem(date_val))
                table.setItem(row_idx, 2, QTableWidgetItem(event_label))
                table.setItem(row_idx, 3, QTableWidgetItem(detail or "--"))
            try:
                table.resizeColumnsToContents()
            except Exception:
                pass
            _layout_add_widget(layout, table)
        else:
            _layout_add_widget(layout, QLabel("No special events recorded yet."))

        _layout_add_stretch(layout)
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
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
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

        for row_idx, entry in enumerate(entries):
            date_val = str(entry.get("season_date") or entry.get("timestamp") or "").strip()
            if " " in date_val:
                date_val = date_val.split(" ", 1)[0]
            action = str(entry.get("action") or "").replace("_", " ").title()
            table.setItem(row_idx, 0, QTableWidgetItem(date_val or "--"))
            table.setItem(row_idx, 1, QTableWidgetItem(str(entry.get("team_id") or "--")))
            table.setItem(row_idx, 2, QTableWidgetItem(action or "--"))
            table.setItem(row_idx, 3, QTableWidgetItem(str(entry.get("from_level") or "")))
            table.setItem(row_idx, 4, QTableWidgetItem(str(entry.get("to_level") or "")))
            table.setItem(row_idx, 5, QTableWidgetItem(str(entry.get("counterparty") or "")))
            table.setItem(row_idx, 6, QTableWidgetItem(str(entry.get("details") or "")))

        try:
            table.resizeColumnsToContents()
        except Exception:
            pass
        return table

    def _build_tab_container(
        self,
        widgets: Iterable[QWidget | None],
        *,
        empty_message: str | None = None,
    ) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        _safe_set_margins(layout, 0, 0, 0, 0)
        _safe_set_spacing(layout, 12)
        added = False
        for widget in widgets:
            if widget is None:
                continue
            _layout_add_widget(layout, widget)
            added = True
        if not added and empty_message:
            label = QLabel(empty_message)
            _safe_call(label, "setWordWrap", True)
            _layout_add_widget(layout, label)
        _layout_add_stretch(layout)

        scroll = QScrollArea()
        _safe_call(scroll, "setWidgetResizable", True)
        _safe_call(scroll, "setWidget", container)
        return scroll

    def _build_empty_tab(self, message: str) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        _safe_set_margins(layout, 12, 12, 12, 12)
        _safe_set_spacing(layout, 8)
        label = QLabel(message)
        _safe_call(label, "setWordWrap", True)
        _layout_add_widget(layout, label)
        _layout_add_stretch(layout)
        return wrapper

    def _collect_ratings_history(self) -> List[Tuple[str, Dict[str, Any]]]:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return []
        entries: List[Tuple[str, Dict[str, Any]]] = []
        seen_years: set[int] = set()

        try:
            ctx = SeasonContext.load()
            seasons = list(ctx.seasons)
        except Exception:
            seasons = []

        for season in seasons:
            if not isinstance(season, dict):
                continue
            season_id = str(season.get("season_id", "") or "").strip()
            if not season_id:
                continue
            league_year = season.get("league_year")
            try:
                year_val = (
                    int(league_year)
                    if league_year is not None
                    else PlayerProfileDialog._season_year_from_id(season_id)
                )
            except Exception:
                year_val = PlayerProfileDialog._season_year_from_id(season_id)
            artifacts = season.get("artifacts") or {}
            path = None
            if isinstance(artifacts, dict):
                path = _resolve_artifact_path(artifacts.get("players"))
            if path is None:
                path = get_base_dir() / "data" / "careers" / season_id / "players.csv"
            row = _load_player_row_from_csv(path, player_id)
            if row:
                ratings = _ratings_from_row(row, is_pitcher=self._is_pitcher)
                if ratings:
                    label = f"{year_val:04d}" if year_val > 0 else season_id
                    entries.append((label, ratings))
                    if year_val > 0:
                        seen_years.add(year_val)

        current_year = self._current_season_year()
        current_ratings = _ratings_from_player(self.player, is_pitcher=self._is_pitcher)
        if current_ratings:
            label = f"{current_year:04d}" if current_year else "Current"
            if current_year and current_year in seen_years:
                entries = [
                    entry
                    for entry in entries
                    if _extract_year_from_label(entry[0]) != current_year
                ]
            entries.append((label, current_ratings))

        entries.sort(
            key=lambda item: (_extract_year_from_label(item[0]) or -1),
            reverse=True,
        )
        return entries

    def _collect_awards_history(self) -> List[Dict[str, str]]:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return []
        entries: List[Dict[str, str]] = []
        try:
            ctx = SeasonContext.load()
            seasons = list(ctx.seasons)
        except Exception:
            seasons = []
        full_name = f"{self.player.first_name} {self.player.last_name}".strip()

        for season in seasons:
            if not isinstance(season, dict):
                continue
            season_id = str(season.get("season_id", "") or "").strip()
            if not season_id:
                continue
            league_year = season.get("league_year")
            try:
                year_val = int(league_year) if league_year is not None else self._season_year_from_id(season_id)
            except Exception:
                year_val = self._season_year_from_id(season_id)
            artifacts = season.get("artifacts") or {}
            path = None
            if isinstance(artifacts, dict):
                path = _resolve_artifact_path(artifacts.get("awards"))
            if path is None:
                path = get_base_dir() / "data" / "careers" / season_id / "awards.json"
            if path is None or not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            awards = payload.get("awards", {}) if isinstance(payload, dict) else {}
            if not isinstance(awards, dict):
                continue
            for award_name, info in awards.items():
                if not isinstance(info, dict):
                    continue
                award_pid = str(info.get("player_id") or "").strip()
                award_name_raw = str(award_name or "").strip()
                award_name_clean = award_name_raw.replace("_", " ").title()
                if award_pid and award_pid != player_id:
                    continue
                if not award_pid and full_name:
                    award_player_name = str(info.get("player_name") or "").strip()
                    if award_player_name and award_player_name != full_name:
                        continue
                detail = str(info.get("metric") or "").strip()
                entries.append(
                    {
                        "year": f"{year_val:04d}" if year_val > 0 else season_id,
                        "award": award_name_clean or award_name_raw,
                        "detail": detail or "-",
                    }
                )

        entries.sort(key=lambda entry: str(entry.get("year", "")), reverse=True)
        return entries

    def _collect_transactions(self, *, trade_only: bool = False) -> List[Dict[str, str]]:
        player_id = str(getattr(self.player, "player_id", "") or "").strip()
        if not player_id:
            return []
        try:
            rows = load_transactions(limit=None)
        except Exception:
            rows = []
        filtered = [row for row in rows if row.get("player_id") == player_id]
        if trade_only:
            filtered = [
                row
                for row in filtered
                if str(row.get("action", "")).lower().startswith("trade")
            ]
        filtered.sort(
            key=lambda row: row.get("season_date") or row.get("timestamp") or "",
            reverse=True,
        )
        return filtered

    # ------------------------------------------------------------------
    def _collect_ratings(self) -> List[Tuple[str, str, Any]]:
        excluded = {
            "player_id",
            "first_name",
            "last_name",
            "birthdate",
            "height",
            "weight",
            "bats",
            "primary_position",
            "other_positions",
            "gf",
            "injured",
            "injury_description",
            "return_date",
            "ready",
            "is_pitcher",
        }
        values: Dict[str, Any] = {}
        for key, val in vars(self.player).items():
            if key in excluded or key.startswith("pot_"):
                continue
            if isinstance(val, (int, float)):
                values[key] = val

        if self._is_pitcher:
            ordered: List[Tuple[str, str, Any]] = []
            pitcher_sequence = [
                ("arm", "AS"),
                ("endurance", "EN"),
                ("control", "CO"),
                ("fb", "FB"),
                ("sl", "SL"),
                ("cu", "CU"),
                ("cb", "CB"),
                ("si", "SI"),
                ("scb", "SCB"),
                ("kn", "KN"),
                ("movement", "MO"),
                ("fa", "FA"),
            ]
            for key, label in pitcher_sequence:
                if key in values:
                    ordered.append((label, key, values.pop(key)))
            for key in sorted(values):
                ordered.append((self._format_rating_label(key), key, values[key]))
            return ordered

        ordered: List[Tuple[str, str, Any]] = []
        hitter_sequence = [
            ("ch", "CH"),
            ("ph", "PH"),
            ("sp", "SP"),
            ("fa", "FA"),
            ("arm", "AS"),
        ]
        for key, label in hitter_sequence:
            if key in values:
                ordered.append((label, key, values.pop(key)))
        for key in sorted(values):
            ordered.append((self._format_rating_label(key), key, values[key]))
        return ordered

    def _format_rating_label(self, key: str) -> str:
        if "_" in key:
            return key.replace("_", " ").title()
        if len(key) <= 3:
            return key.upper()
        return key.title()

    def _collect_stats_history(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Return rows for the stats table.

        Includes current season and career rows when available. If no season/
        career stats exist, falls back to recent historical snapshots loaded
        from persistence, labelling undated snapshots as "Year N".
        """
        is_pitcher = getattr(self.player, "is_pitcher", False)
        rows: List[Tuple[str, Dict[str, Any]]] = []

        current_year = self._current_season_year()
        season = self._stats_to_dict(getattr(self.player, "season_stats", {}), is_pitcher)
        # Clamp displayed games to the number already played by teams this
        # season to avoid showing stale totals when starting a new season.
        if season:
            try:
                from utils.stats_persistence import load_stats as _load_season
                all_stats = _load_season()
                team_stats = all_stats.get("teams", {}) or {}
                games_list = [int(v.get("g", v.get("games", 0)) or 0) for v in team_stats.values()]
                if games_list:
                    max_team_g = max(games_list)
                    g_val = int(season.get("g", 0) or 0)
                    if max_team_g:
                        season["g"] = min(g_val, max_team_g)
            except Exception:
                pass
            rows.append((f"{current_year:04d}", season))

        history_map = getattr(self.player, "career_history", {}) or {}
        if isinstance(history_map, dict):
            history_rows: list[tuple[Tuple[int, str], str, Dict[str, Any]]] = []
            for season_id, raw_stats in history_map.items():
                data = self._stats_to_dict(raw_stats, is_pitcher)
                if not data:
                    continue
                label = self._format_season_label(str(season_id))
                history_rows.append((self._season_sort_key(season_id), label, data))
            if history_rows:
                history_rows.sort(key=lambda item: item[0], reverse=True)
                rows.extend((label, data) for _, label, data in history_rows)

        career = self._stats_to_dict(getattr(self.player, "career_stats", {}), is_pitcher)
        if career:
            rows.append(("Career", career))
        if rows:
            return rows

        history_entries = list(self._history_override or [])
        aggregated = _aggregate_history_rows(self, history_entries, is_pitcher=is_pitcher)
        if aggregated:
            return aggregated

        fallback_entries: list[Dict[str, Any]] = []
        loader = getattr(self, "_load_history", None)
        iterable_history: Iterable[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
        if callable(loader):
            try:
                candidate = loader()
                if isinstance(candidate, Iterable):
                    iterable_history = candidate
            except Exception:
                iterable_history = []
        for entry_label, _ratings, stats in iterable_history:
            fallback_entries.append(
                {
                    "players": {self.player.player_id: stats},
                    "year": entry_label,
                }
            )
        return _aggregate_history_rows(self, fallback_entries, is_pitcher=is_pitcher)

    def _load_history(self) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
        loader = getattr(sys.modules[__name__], "load_stats")
        data = loader()
        history: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
        rating_fields = getattr(type(self.player), "_rating_fields", set())
        entries = data.get("history", [])[-5:]
        used_years: set[str] = set()
        snap_idx = 0
        for entry in entries:
            player_data = entry.get("players", {}).get(self.player.player_id)
            if not player_data:
                continue
            if "ratings" in player_data or "stats" in player_data:
                ratings = player_data.get("ratings", {})
                stats = player_data.get("stats", {})
            else:
                ratings = {
                    k: v
                    for k, v in player_data.items()
                    if k in rating_fields and not k.startswith("pot_")
                }
                stats = {
                    k: v
                    for k, v in player_data.items()
                    if k not in rating_fields and not k.startswith("pot_")
                }
            year = entry.get("year")
            if year is None:
                snap_idx += 1
                year_label = f"Year {snap_idx}"
            else:
                year_label = str(year)
            if year_label in used_years:
                continue
            used_years.add(year_label)
            history.append((year_label, ratings, stats))
        return history

    def _current_season_year(self) -> int:
        """Return the current season year based on schedule/progress.

        Prefer the year of the date at the current simulation index from
        ``season_progress.json``. If unavailable, use the first scheduled
        game's year rather than the maximum to avoid multi-year schedules
        (e.g., repeated cycles) pushing the label into the future. Falls back
        to the calendar year on error.
        """
        try:
            data_dir = Path(__file__).resolve().parents[1] / "data"
            sched = data_dir / "schedule.csv"
            prog = data_dir / "season_progress.json"
            if not sched.exists():
                return datetime.now().year
            rows: list[dict] = []
            with sched.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            if not rows:
                return datetime.now().year
            # Try to read the current sim index
            idx = 0
            if prog.exists():
                try:
                    import json as _json
                    data = _json.loads(prog.read_text(encoding="utf-8"))
                    raw_idx = int(data.get("sim_index", 0) or 0)
                    idx = max(0, min(raw_idx, len(rows) - 1))
                except Exception:
                    idx = 0
            cur_date = str(rows[idx].get("date") or "").strip()
            if cur_date:
                try:
                    return int(cur_date.split("-")[0])
                except Exception:
                    pass
            # Fallback: use the first scheduled game's year
            first_date = str(rows[0].get("date") or "").strip()
            if first_date:
                try:
                    return int(first_date.split("-")[0])
                except Exception:
                    pass
            return datetime.now().year
        except Exception:
            return datetime.now().year

    @staticmethod
    def _season_year_from_id(season_id: str) -> int:
        try:
            token = str(season_id).rsplit("-", 1)[-1]
            return int(token)
        except Exception:
            return -1

    def _season_sort_key(self, season_id: str) -> tuple[int, str]:
        return (self._season_year_from_id(season_id), str(season_id))

    def _format_season_label(self, season_id: str) -> str:
        parts = str(season_id).rsplit("-", 1)
        if len(parts) == 2:
            league_token, year_token = parts
            try:
                year_int = int(year_token)
                label = f"{year_int:04d}"
            except ValueError:
                return str(season_id)
            league_token = league_token.strip().upper()
            if league_token and league_token not in {"LEAGUE"}:
                return f"{label} ({league_token})"
            return label
        return str(season_id)

    def _stats_to_dict(self, stats: Any, is_pitcher: bool) -> Dict[str, Any]:
        if isinstance(stats, dict):
            data = dict(stats)
        elif is_dataclass(stats):
            data = asdict(stats)
        else:
            return {}

        if is_pitcher:
            data = self._normalize_pitching_stats(data)
            _round_stat_values(data)
            return data

        if "b2" in data and "2b" not in data:
            data["2b"] = data.get("b2", 0)
        if "b3" in data and "3b" not in data:
            data["3b"] = data.get("b3", 0)
        _round_stat_values(data)
        return data

    def _normalize_pitching_stats(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(data)
        outs = result.get("outs")
        if outs is not None and "ip" not in result:
            result["ip"] = outs / 3
        ip = result.get("ip", 0)
        if ip:
            er = result.get("er", 0)
            result.setdefault("era", (er * 9) / ip if ip else 0.0)
            walks_hits = result.get("bb", 0) + result.get("h", 0)
            result.setdefault("whip", walks_hits / ip if ip else 0.0)
        result.setdefault("w", result.get("wins", result.get("w", 0)))
        result.setdefault("l", result.get("losses", result.get("l", 0)))
        _round_stat_values(result)
        return result

    def _stat_item(self, value: Any, *, align_left: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem()
        names = ["AlignLeft" if align_left else "AlignRight", "AlignVCenter"]
        _set_text_alignment(item, *names)
        if isinstance(value, (int, float)):
            item.setData(Qt.ItemDataRole.DisplayRole, self._format_stat(value))
            item.setData(Qt.ItemDataRole.EditRole, float(value))
            return item
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            item.setData(Qt.ItemDataRole.DisplayRole, str(value))
        else:
            item.setData(Qt.ItemDataRole.DisplayRole, self._format_stat(numeric))
            item.setData(Qt.ItemDataRole.EditRole, numeric)
        return item

    def _format_stat(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    def _format_height(self, height: Any) -> str:
        try:
            total_inches = int(height)
        except (TypeError, ValueError):
            return "?"
        feet, inches = divmod(total_inches, 12)
        return f"{feet}'{inches}\""

    def _calculate_age(self, birthdate_str: str):
        try:
            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
            today = datetime.today().date()
            return today.year - birthdate.year - (
                (today.month, today.day) < (birthdate.month, birthdate.day)
            )
        except Exception:
            return "?"

class SprayChartWidget(QWidget):
    """Draw a simple spray chart using normalized hit locations."""

    def __init__(self) -> None:
        super().__init__()
        self._points: List[Dict[str, float]] = []
        self.setMinimumHeight(220)

    def set_points(self, points: List[Dict[str, float]] | None) -> None:
        self._points = points or []
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        except Exception:
            pass
        rect = self.rect().adjusted(20, 20, -20, -20)
        home_x = rect.left() + rect.width() / 2
        home_y = rect.bottom()

        painter.setPen(QPen(QColor("#adb5bd"), 2))
        painter.drawLine(int(home_x), int(home_y), rect.left(), rect.top())
        painter.drawLine(int(home_x), int(home_y), rect.right(), rect.top())

        arc_rect = QRectF(rect.left(), rect.top() - rect.height(), rect.width(), rect.height() * 2)
        painter.drawArc(arc_rect, 0, 180 * 16)

        color_map = {
            "1B": QColor("#51cf66"),
            "2B": QColor("#339af0"),
            "3B": QColor("#fcc419"),
            "HR": QColor("#fa5252"),
        }

        radius_x = rect.width() / 2
        radius_y = rect.height()
        for point in self._points:
            x_norm = float(point.get("x", 0))
            y_norm = float(point.get("y", 0))
            kind = str(point.get("kind", "1B"))
            color = color_map.get(kind, QColor("#868e96"))
            x = home_x + x_norm * radius_x
            y = home_y - y_norm * radius_y
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color))
            painter.drawEllipse(QPointF(x, y), 5, 5)

        if not self._points:
            painter.setPen(QPen(QColor("#868e96")))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No batted ball data available.",
            )
        painter.end()


class RollingStatsWidget(QWidget):
    """Line chart displaying rolling metrics such as AVG/OPS or ERA/WHIP."""

    palette = [
        QColor("#228be6"),
        QColor("#f76707"),
        QColor("#12b886"),
        QColor("#fa5252"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._dates: List[str] = []
        self._series: Dict[str, List[float]] = {}
        self.setMinimumHeight(220)

    def update_series(self, data: Dict[str, Any]) -> None:
        self._dates = list(data.get("dates", []))
        raw_series = data.get("series", {}) or {}
        self._series = {label: list(values) for label, values in raw_series.items()}
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        except Exception:
            pass
        rect = self.rect().adjusted(20, 20, -20, -40)

        values: List[float] = []
        for series in self._series.values():
            values.extend(float(v) for v in series)
        values = [v for v in values if v or v == 0.0]

        if not self._dates or not values:
            painter.setPen(QPen(QColor("#868e96")))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No rolling data available.",
            )
            painter.end()
            return

        min_val = min(values)
        max_val = max(values)
        if abs(max_val - min_val) < 0.001:
            max_val += 0.5
            min_val -= 0.5

        painter.setPen(QPen(QColor("#adb5bd")))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.topLeft())

        step = rect.width() / max(1, len(self._dates) - 1)

        def map_y(value: float) -> float:
            if max_val == min_val:
                return rect.bottom()
            ratio = (value - min_val) / (max_val - min_val)
            return rect.bottom() - ratio * rect.height()

        for idx, (label, series) in enumerate(self._series.items()):
            if not series:
                continue
            points = [
                QPointF(rect.left() + index * step, map_y(float(value)))
                for index, value in enumerate(series)
            ]
            pen = QPen(self.palette[idx % len(self.palette)], 2)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(self.palette[idx % len(self.palette)]))
            painter.drawText(
                rect.left() + 8 + idx * 90,
                rect.top() - 8,
                f"{label}",
            )

        painter.setPen(QPen(QColor("#495057")))
        painter.drawText(
            rect.left(),
            rect.bottom() + 18,
            self._dates[0],
        )
        if len(self._dates) > 1:
            painter.drawText(
                rect.right() - 60,
                rect.bottom() + 18,
                self._dates[-1],
            )
        painter.end()


class ComparisonSelectorDialog(QDialog):
    """Simple selector to choose a comparison player from the league."""

    def __init__(self, pool: Dict[str, Any], exclude_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Comparison Player")
        self._players = [
            player for pid, player in pool.items() if pid and pid != exclude_id
        ]
        self._players.sort(
            key=lambda p: (
                str(getattr(p, "last_name", "")).lower(),
                str(getattr(p, "first_name", "")).lower(),
            )
        )
        self._selected: Any | None = None

        layout = QVBoxLayout(self)
        _layout_add_widget(layout, QLabel("Search by name or player ID"))

        self.search_edit = QLineEdit()
        _layout_add_widget(layout, self.search_edit)

        self.list_widget = QListWidget()
        _layout_add_widget(layout, self.list_widget)

        button_row = QHBoxLayout()
        _layout_add_stretch(button_row)
        self.compare_button = QPushButton("Compare")
        self.cancel_button = QPushButton("Cancel")
        _layout_add_widget(button_row, self.compare_button)
        _layout_add_widget(button_row, self.cancel_button)
        layout.addLayout(button_row)

        self.search_edit.textChanged.connect(self._apply_filter)
        self.compare_button.clicked.connect(self._accept_selection)
        self.cancel_button.clicked.connect(self.reject)
        self.list_widget.itemDoubleClicked.connect(lambda *_: self._accept_selection())

        self._apply_filter("")

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        self.list_widget.clear()
        for player in self._players:
            label = self._display_label(player)
            if query and query not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, player)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _display_label(self, player: Any) -> str:
        name = " ".join(
            part
            for part in (
                str(getattr(player, "first_name", "")).strip(),
                str(getattr(player, "last_name", "")).strip(),
            )
            if part
        )
        pid = getattr(player, "player_id", "--")
        pos = getattr(player, "primary_position", "?")
        return f"{name or pid} ({pos}) [{pid}]"

    def _accept_selection(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        player = item.data(Qt.ItemDataRole.UserRole)
        if player is None:
            return
        self._selected = player
        self.accept()

    @property
    def selected_player(self) -> Any | None:
        return self._selected

# ---------------------------------------------------------------------------
# Enhanced stat helpers
# ---------------------------------------------------------------------------

_PLAYER_TEAM_CACHE: Dict[str, str] | None = None
_PLAYER_TYPE_CACHE: Dict[str, bool] | None = None
_SEASON_STATS_CACHE: Dict[int, Dict[str, Any]] = {}
_ORIGINAL_METHODS: Dict[str, Any] = {}


def _original(name: str) -> Any:
    func = _ORIGINAL_METHODS.get(name)
    if func is None:
        func = getattr(PlayerProfileDialog, name)
        _ORIGINAL_METHODS[name] = func
    return func


def _lookup_player_team(player_id: str) -> Optional[str]:
    global _PLAYER_TEAM_CACHE
    if _PLAYER_TEAM_CACHE is None:
        mapping: Dict[str, str] = {}
        roster_dir = get_base_dir() / "data" / "rosters"
        if roster_dir.exists():
            for path in sorted(roster_dir.glob("*.csv")):
                stem = path.stem
                if not stem or "_" in stem:
                    continue
                team_id = stem.upper()
                try:
                    with path.open("r", encoding="utf-8", newline="") as fh:
                        reader = csv.reader(fh)
                        for row in reader:
                            if not row:
                                continue
                            pid = str(row[0]).strip()
                            if pid and pid not in mapping:
                                mapping[pid] = team_id
                except OSError:
                    continue
        _PLAYER_TEAM_CACHE = mapping
    return _PLAYER_TEAM_CACHE.get(player_id)


def _resolve_artifact_path(value: object) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(str(value))
    if not candidate.is_absolute():
        candidate = get_base_dir() / candidate
    return candidate


def _coerce_int(value: Any) -> Optional[int]:
    if value in ("", None):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _rating_fields(is_pitcher: bool) -> List[Tuple[str, str]]:
    return _PITCHER_RATING_HISTORY if is_pitcher else _HITTER_RATING_HISTORY


def _overall_from_ratings(values: Dict[str, Any], is_pitcher: bool) -> Optional[int]:
    keys = _PITCHER_OVERALL_KEYS if is_pitcher else _HITTER_OVERALL_KEYS
    numeric: List[float] = []
    for key in keys:
        raw = values.get(key)
        try:
            numeric.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return None
    return max(0, min(99, int(round(sum(numeric) / len(numeric)))))


def _ratings_from_row(row: Dict[str, Any], *, is_pitcher: bool) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for key, _label in _rating_fields(is_pitcher):
        if key == "overall":
            continue
        raw = row.get(key)
        val = _coerce_int(raw)
        if val is not None:
            values[key] = val
    overall = _overall_from_ratings(values, is_pitcher)
    if overall is None:
        overall = _coerce_int(row.get("overall"))
    if overall is not None:
        values["overall"] = overall
    return values


def _ratings_from_player(player: Any, *, is_pitcher: bool) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for key, _label in _rating_fields(is_pitcher):
        if key == "overall":
            continue
        raw = getattr(player, key, None)
        val = _coerce_int(raw)
        if val is not None:
            values[key] = val
    overall = _overall_from_ratings(values, is_pitcher)
    if overall is None:
        overall = _coerce_int(getattr(player, "overall", None))
    if overall is not None:
        values["overall"] = overall
    return values


def _load_player_row_from_csv(path: Optional[Path], player_id: str) -> Optional[Dict[str, Any]]:
    if path is None or not player_id:
        return None
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if str(row.get("player_id", "")).strip() == player_id:
                    return row
    except Exception:
        return None
    return None


def _player_type_map() -> Dict[str, bool]:
    global _PLAYER_TYPE_CACHE
    if _PLAYER_TYPE_CACHE is None:
        try:
            players = load_players_from_csv("data/players.csv")
        except Exception:
            players = []
        mapping: Dict[str, bool] = {}
        for player in players:
            is_pitcher = bool(
                getattr(player, "is_pitcher", False)
                or str(getattr(player, "primary_position", "")).upper() == "P"
            )
            mapping[getattr(player, "player_id", "")] = is_pitcher
        _PLAYER_TYPE_CACHE = mapping
    return _PLAYER_TYPE_CACHE


def _is_pitcher_stats(stats: Dict[str, Any]) -> Optional[bool]:
    if not stats:
        return None
    for key in ("ip", "outs", "era", "sv", "bs", "gs", "w", "l"):
        if key in stats:
            return True
    return None


def _season_stats_payload_for_year(year: int, *, current_year: Optional[int] = None) -> Dict[str, Any]:
    if year in _SEASON_STATS_CACHE:
        return _SEASON_STATS_CACHE[year]

    payload: Dict[str, Any] = {}
    if current_year is not None and year == current_year:
        try:
            payload = load_stats()
        except Exception:
            payload = {}
        _SEASON_STATS_CACHE[year] = payload
        return payload

    target_path: Optional[Path] = None
    try:
        ctx = SeasonContext.load()
        for season in list(ctx.seasons):
            if not isinstance(season, dict):
                continue
            season_id = str(season.get("season_id", "") or "").strip()
            league_year = season.get("league_year")
            if not season_id:
                continue
            try:
                year_val = int(league_year) if league_year is not None else self._season_year_from_id(season_id)
            except Exception:
                year_val = self._season_year_from_id(season_id)
            if year_val != year:
                continue
            artifacts = season.get("artifacts") or {}
            if isinstance(artifacts, dict):
                target_path = _resolve_artifact_path(artifacts.get("stats"))
            if target_path is None:
                target_path = get_base_dir() / "data" / "careers" / season_id / "stats.json"
            break
    except Exception:
        target_path = None

    if target_path is None:
        careers_dir = get_base_dir() / "data" / "careers"
        if careers_dir.exists():
            for candidate in careers_dir.glob(f"*-{year}/stats.json"):
                target_path = candidate
                break

    if target_path and target_path.exists():
        try:
            payload = json.loads(target_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}

    _SEASON_STATS_CACHE[year] = payload
    return payload


def _leader_value(stats: Dict[str, Any], key: str) -> Optional[float]:
    if not stats:
        return None

    def _float(raw: Any) -> Optional[float]:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    if key == "avg":
        ab = _float(stats.get("ab"))
        hits = _float(stats.get("h"))
        if not ab:
            return None
        return hits / ab if hits is not None else None
    if key == "obp":
        ab = _float(stats.get("ab")) or 0.0
        hits = _float(stats.get("h")) or 0.0
        bb = _float(stats.get("bb")) or 0.0
        hbp = _float(stats.get("hbp")) or 0.0
        sf = _float(stats.get("sf")) or 0.0
        denom = ab + bb + hbp + sf
        if denom <= 0:
            return None
        return (hits + bb + hbp) / denom
    if key == "ops":
        ab = _float(stats.get("ab")) or 0.0
        if ab <= 0:
            return None
        hits = _float(stats.get("h")) or 0.0
        doubles = _float(stats.get("b2", stats.get("2b"))) or 0.0
        triples = _float(stats.get("b3", stats.get("3b"))) or 0.0
        homers = _float(stats.get("hr")) or 0.0
        singles = max(hits - doubles - triples - homers, 0.0)
        total_bases = singles + (2 * doubles) + (3 * triples) + (4 * homers)
        slg = total_bases / ab if ab else None
        obp = _leader_value(stats, "obp")
        if slg is None or obp is None:
            return None
        return obp + slg
    if key == "era":
        outs = _float(stats.get("outs"))
        ip = _float(stats.get("ip"))
        if ip is None:
            ip = outs / 3 if outs else None
        if not ip:
            return None
        er = _float(stats.get("er")) or 0.0
        return (er * 9.0) / ip
    if key == "whip":
        outs = _float(stats.get("outs"))
        ip = _float(stats.get("ip"))
        if ip is None:
            ip = outs / 3 if outs else None
        if not ip:
            return None
        hits = _float(stats.get("h")) or 0.0
        walks = _float(stats.get("bb")) or 0.0
        return (hits + walks) / ip
    if key == "so":
        value = _float(stats.get("so"))
        if value is None:
            value = _float(stats.get("k"))
        return value
    if key == "w":
        value = _float(stats.get("w"))
        if value is None:
            value = _float(stats.get("wins"))
        return value
    return _float(stats.get(key))


def _leader_labels_for_year(
    dialog: "PlayerProfileDialog",
    year: int,
    player_stats: Optional[Dict[str, Any]] = None,
) -> List[str]:
    cache = getattr(dialog, "_leader_cache", None)
    if cache is None:
        cache = {}
        setattr(dialog, "_leader_cache", cache)
    if year in cache:
        return cache[year]

    labels: List[str] = []
    current_year = _current_season_year_value(dialog)
    payload = _season_stats_payload_for_year(year, current_year=current_year)
    stats_map = payload.get("players", {}) if isinstance(payload, dict) else {}
    if not isinstance(stats_map, dict) or not stats_map:
        cache[year] = labels
        return labels
    player_id = getattr(dialog.player, "player_id", "")
    if player_stats is None:
        player_stats = stats_map.get(player_id, {})
    if not isinstance(player_stats, dict) or not player_stats:
        cache[year] = labels
        return labels

    type_map = _player_type_map()
    categories = _LEADER_CATEGORIES[bool(dialog._is_pitcher)]
    for key, label, descending in categories:
        best: Optional[float] = None
        for pid, stats in stats_map.items():
            if not isinstance(stats, dict):
                continue
            is_pitcher = type_map.get(pid)
            if is_pitcher is None:
                is_pitcher = _is_pitcher_stats(stats)
            if is_pitcher is None:
                continue
            if bool(is_pitcher) != bool(dialog._is_pitcher):
                continue
            val = _leader_value(stats, key)
            if val is None:
                continue
            if best is None:
                best = val
            else:
                if descending and val > best:
                    best = val
                elif not descending and val < best:
                    best = val
        if best is None:
            continue
        player_val = _leader_value(player_stats, key)
        if player_val is None:
            continue
        if abs(player_val - best) <= 1e-6:
            labels.append(label)

    cache[year] = labels
    return labels


def _extract_year_from_label(label: Any) -> Optional[int]:
    if isinstance(label, (int, float)):
        year_val = int(label)
        return year_val if 1900 <= year_val <= 3000 else None
    try:
        text = str(label)
    except Exception:
        return None
    normalized = (
        text.replace("(", " ")
        .replace(")", " ")
        .replace("/", " ")
        .replace("-", " ")
    )
    for token in normalized.split():
        if len(token) == 4 and token.isdigit():
            year_val = int(token)
            if 1900 <= year_val <= 3000:
                return year_val
    return None


def _age_for_year(dialog: PlayerProfileDialog, year: Optional[int]) -> Optional[int]:
    if year is None:
        return None
    try:
        birthdate = datetime.strptime(dialog.player.birthdate, "%Y-%m-%d").date()
    except Exception:
        return None
    try:
        pivot = datetime(year, 7, 1).date()
    except Exception:
        return None
    age = pivot.year - birthdate.year - (
        (pivot.month, pivot.day) < (birthdate.month, birthdate.day)
    )
    return age if age >= 0 else None


def _compute_ops(stats: Dict[str, Any]) -> Optional[float]:
    try:
        obp = float(stats.get("obp"))
        slg = float(stats.get("slg"))
    except (TypeError, ValueError):
        return None
    return obp + slg


def _compute_win_pct(stats: Dict[str, Any]) -> Optional[float]:
    wins = stats.get("w", stats.get("wins"))
    losses = stats.get("l", stats.get("losses"))
    try:
        wins_val = float(wins)
        losses_val = float(losses)
    except (TypeError, ValueError):
        return None
    total = wins_val + losses_val
    if total <= 0:
        return None
    return wins_val / total


def _compute_oba(stats: Dict[str, Any]) -> Optional[float]:
    hits = stats.get("h")
    batters_faced = stats.get("bf")
    try:
        hits_val = float(hits)
        bf_val = float(batters_faced)
    except (TypeError, ValueError):
        return None
    walks = stats.get("bb", 0)
    hbp = stats.get("hbp", 0)
    sf = stats.get("sf", 0)
    sh = stats.get("sh", 0)
    ci = stats.get("ci", 0)
    try:
        adjustments = sum(float(v or 0) for v in (walks, hbp, sf, sh, ci))
    except (TypeError, ValueError):
        adjustments = 0.0
    at_bats_against = bf_val - adjustments
    if at_bats_against <= 0:
        return None
    return hits_val / at_bats_against


def _current_season_year_value(dialog: PlayerProfileDialog) -> Optional[int]:
    try:
        data_dir = Path(__file__).resolve().parents[1] / "data"
        sched = data_dir / "schedule.csv"
        prog = data_dir / "season_progress.json"
        if not sched.exists():
            return None
        with sched.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            return None
        idx = 0
        if prog.exists():
            try:
                import json as _json

                data = _json.loads(prog.read_text(encoding="utf-8"))
                raw_idx = int(data.get("sim_index", 0) or 0)
                idx = max(0, min(raw_idx, len(rows) - 1))
            except Exception:
                idx = 0
        cur_date = str(rows[idx].get("date") or "").strip()
        if cur_date:
            try:
                return int(cur_date.split("-")[0])
            except Exception:
                pass
        first_date = str(rows[0].get("date") or "").strip()
        if first_date:
            try:
                return int(first_date.split("-")[0])
            except Exception:
                pass
    except Exception:
        return None
    return None


def _prepare_stat_row(
    dialog: PlayerProfileDialog,
    label: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    prepared = dict(data)
    player_id = getattr(dialog.player, "player_id", "")
    if not prepared.get("team"):
        team_id = _lookup_player_team(player_id)
        if team_id:
            prepared["team"] = team_id

    year_hint = _extract_year_from_label(label)
    if year_hint is None and str(label).strip().lower() in {"season", "current"}:
        year_hint = _current_season_year_value(dialog)
    age = _age_for_year(dialog, year_hint)
    if age is not None:
        prepared["age"] = age

    if "k" not in prepared and "so" in prepared:
        prepared["k"] = prepared["so"]
    if "gidp" not in prepared:
        for alias in _STAT_ALIASES.get("gidp", ()):  # type: ignore[arg-type]
            if alias in prepared:
                prepared["gidp"] = prepared[alias]
                break

    if "ops" not in prepared:
        ops = _compute_ops(prepared)
        if ops is not None:
            prepared["ops"] = ops

    if dialog._is_pitcher:
        if "pct" not in prepared:
            pct = _compute_win_pct(prepared)
            if pct is not None:
                prepared["pct"] = pct
        if "oba" not in prepared:
            oba = _compute_oba(prepared)
            if oba is not None:
                prepared["oba"] = oba
        if "dera" not in prepared and "fip" in prepared:
            prepared["dera"] = prepared["fip"]
        _round_stat_values(prepared)

    label_lower = str(label).strip().lower()
    label_lower = str(label).strip().lower()
    if "career" in label_lower:
        prepared.pop("team", None)
        prepared.pop("age", None)
    return prepared


def _resolve_stat_value(data: Dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]
    for alias in _STAT_ALIASES.get(key, ()):  # type: ignore[arg-type]
        if alias in data:
            return data[alias]
    return ""


def _round_stat_values(data: Dict[str, Any]) -> None:
    for key, decimals in _STAT_ROUNDING.items():
        value = data.get(key)
        if isinstance(value, (int, float)):
            data[key] = round(float(value), decimals)


def _stat_item(self: PlayerProfileDialog, value: Any, *, align_left: bool = False, key: Optional[str] = None) -> "QTableWidgetItem":
    item = QTableWidgetItem()
    names = ["AlignLeft" if align_left else "AlignRight", "AlignVCenter"]
    _set_text_alignment(item, *names)
    if isinstance(value, (int, float)):
        text, numeric = _format_stat(value, key=key)
        item.setData(Qt.ItemDataRole.DisplayRole, text)
        item.setData(Qt.ItemDataRole.EditRole, numeric if numeric is not None else value)
        return item
    text, numeric = _format_stat(value, key=key)
    item.setData(Qt.ItemDataRole.DisplayRole, text)
    if numeric is not None:
        item.setData(Qt.ItemDataRole.EditRole, numeric)
    return item


def _format_stat(value: Any, *, key: Optional[str] = None) -> tuple[str, Optional[float]]:
    if value is None:
        return "", None
    if isinstance(value, float):
        if not math.isfinite(value):
            return "-", None
        if key == "ip":
            text = f"{value:.2f}"
            return text, float(value)
        if key in {"avg", "obp", "slg", "ops", "pct", "oba"}:
            text = f"{value:.3f}"
            text = text.replace("-0.", "-.")
            return text, float(value)
        if key in {"era", "whip", "fip", "dera"}:
            return f"{value:.2f}", float(value)
        if value.is_integer():
            return str(int(value)), float(value)
        formatted = f"{value:.3f}".rstrip("0").rstrip(".")
        text = formatted if formatted else f"{value:.3f}"
        return text, float(value)
    if isinstance(value, (int, float)):
        return str(value), float(value)
    return str(value), None


def _row_role(label: Any) -> str:
    text = str(label).strip().lower()
    if "career" in text:
        return "career"
    if "current" in text:
        return "current"
    return "history"


def _create_stats_table(self: PlayerProfileDialog, rows: List[Tuple[str, Dict[str, Any]]], columns: List[str]) -> "QTableWidget":
    table = QTableWidget(len(rows), len(columns) + 1)
    _safe_call(table, "setObjectName", "StatsTable")
    try:
        font = table.font()
        if hasattr(font, "setPointSize"):
            point = font.pointSize()
            if point > 0:
                font.setPointSize(max(10, point - 1))
                table.setFont(font)
        header_widget = table.horizontalHeader()
        if header_widget is not None and hasattr(header_widget, "font"):
            header_font = header_widget.font()
            if hasattr(header_font, "setPointSize"):
                point = header_font.pointSize()
                if point > 0:
                    header_font.setPointSize(max(10, point - 1))
                    header_widget.setFont(header_font)
    except Exception:
        pass

    headers = ["Year"] + [_STAT_LABELS.get(col, col.upper()) for col in columns]
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    try:
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setSizeAdjustPolicy(QAbstractItemView.SizeAdjustPolicy.AdjustToContents)
    except Exception:
        pass

    header = table.horizontalHeader()
    try:
        header.setStretchLastSection(False)
        for idx in range(len(headers)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
    except Exception:
        pass

    current_year = _current_season_year_value(self)
    normalized_year = f"{current_year:04d}" if isinstance(current_year, int) else None

    for row_idx, (label, data) in enumerate(rows):
        raw_label = str(label)
        label_lower = raw_label.strip().lower()
        if normalized_year and label_lower in {"season", "current"}:
            display_label = normalized_year
        else:
            display_label = raw_label
        row_role = _row_role(raw_label)

        leader_labels: List[str] = []
        year_hint = _extract_year_from_label(display_label)
        if year_hint is not None and row_role != "career" and isinstance(data, dict):
            leader_labels = _leader_labels_for_year(self, year_hint, data)
            if leader_labels:
                display_label = f"{display_label}*"

        year_item = _stat_item(self, display_label, align_left=True)
        if leader_labels:
            year_item.setToolTip(
                "League leader: " + ", ".join(sorted(set(leader_labels)))
            )
        year_item.setData(Qt.ItemDataRole.UserRole, row_role)
        table.setItem(row_idx, 0, year_item)

        for col_idx, key in enumerate(columns, start=1):
            value = _resolve_stat_value(data, key)
            item = _stat_item(self, value, align_left=key in _LEFT_ALIGN_STATS, key=key)
            item.setData(Qt.ItemDataRole.UserRole, row_role)
            table.setItem(row_idx, col_idx, item)

    table.setSortingEnabled(True)
    try:
        table.resizeColumnsToContents()
        total_width = table.verticalHeader().width() + (table.frameWidth() * 2) + 24
        for idx in range(len(headers)):
            total_width += table.columnWidth(idx)
        table.setMinimumWidth(min(total_width, 900))
        if hasattr(table.horizontalHeader(), "setStretchLastSection"):
            table.horizontalHeader().setStretchLastSection(False)
    except Exception:
        pass
    return table


def _create_stats_summary(
    self: PlayerProfileDialog,
    rows: List[Tuple[str, Dict[str, Any]]],
    columns: List[str],
    summary_keys: Optional[List[str]] = None,
) -> Optional["QWidget"]:
    target = None
    for label, data in rows:
        if label.lower() == "career" and data:
            target = data
            break
    if target is None and rows:
        target = rows[-1][1]
    if not target:
        return None

    panel = QWidget()
    grid = QGridLayout(panel)
    _safe_set_margins(grid, 12, 12, 12, 12)
    _safe_set_hspacing(grid, 18)
    _safe_set_vspacing(grid, 8)

    key_sequence = summary_keys or columns[:6]
    for idx, key in enumerate(key_sequence):
        label_widget = QLabel(_STAT_LABELS.get(key, key.upper()))
        _set_alignment(label_widget, "AlignLeft", "AlignVCenter")
        raw_value = _resolve_stat_value(target, key)
        display, _numeric = _format_stat(raw_value, key=key)
        value_widget = QLabel(display)
        _set_alignment(value_widget, "AlignRight", "AlignVCenter")
        _layout_add_widget(grid, label_widget, idx, 0)
        _layout_add_widget(grid, value_widget, idx, 1)
    return panel


def _build_stats_section(self: PlayerProfileDialog, rows: List[Tuple[str, Dict[str, Any]]]) -> "Card":
    card = Card()
    layout = card.layout()
    _layout_add_widget(layout, section_title("Stats"))
    current_year = _current_season_year_value(self)
    if current_year is not None:
        try:
            year_label = QLabel(f"{current_year:04d}")
            _safe_call(year_label, "setObjectName", "SeasonYearLabel")
            _layout_add_widget(layout, year_label)
        except Exception:
            pass

    if not rows:
        _layout_add_widget(layout, QLabel("No stats available"))
        return card

    columns = _PITCHING_STATS if self._is_pitcher else _BATTING_STATS
    summary_keys = _SUMMARY_KEYS[self._is_pitcher]

    tabs = QTabWidget()
    _safe_call(tabs, "setObjectName", "StatsTabs")
    primary_label = "Pitching" if self._is_pitcher else "Batting"
    tabs.addTab(_create_stats_table(self, rows, columns), primary_label)

    summary = _create_stats_summary(self, rows, columns, summary_keys)
    if summary is not None:
        tabs.addTab(summary, "Summary")

    spray_points = self._compute_spray_points()
    if spray_points:
        self._spray_chart_widget = SprayChartWidget()
        self._spray_chart_widget.set_points(spray_points)
        tabs.addTab(self._spray_chart_widget, "Spray Chart")

    rolling = self._compute_rolling_stats()
    if rolling.get("dates"):
        self._rolling_stats_widget = RollingStatsWidget()
        self._rolling_stats_widget.update_series(rolling)
        tabs.addTab(self._rolling_stats_widget, "Rolling Stats")

    _layout_add_widget(layout, tabs)
    try:
        footer = _original("_build_stat_key_footer")(self)
    except AttributeError:
        footer = None
    if footer is None:
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        _safe_set_margins(footer_layout, 0, 0, 0, 0)
        _safe_set_spacing(footer_layout, 8)
        _layout_add_widget(footer_layout, QLabel("Stat Key:"))
        for text, variant in (
            ("Current Season", "current"),
            ("Career Totals", "career"),
            ("History", "history"),
        ):
            chip = QLabel(text)
            _safe_call(chip, "setObjectName", "StatChip")
            _safe_call(chip, "setProperty", "variant", variant)
            _set_alignment(chip, "AlignCenter")
            chip.setMinimumWidth(90)
            chip.setMargin(4)
            _layout_add_widget(footer_layout, chip)
        leader_chip = QLabel("* League Leader")
        _safe_call(leader_chip, "setObjectName", "StatChip")
        _safe_call(leader_chip, "setProperty", "variant", "leader")
        _set_alignment(leader_chip, "AlignCenter")
        leader_chip.setMinimumWidth(110)
        leader_chip.setMargin(4)
        _layout_add_widget(footer_layout, leader_chip)
        _layout_add_stretch(footer_layout)
    _layout_add_widget(layout, footer)
    return card


def _stats_to_dict(self: PlayerProfileDialog, stats: Any, is_pitcher: bool) -> Dict[str, Any]:
    data = _original("_stats_to_dict")(self, stats, is_pitcher)
    if not isinstance(data, dict):
        return {}
    # Ensure double aliases present even if original mapping misses them.
    if "b2" in data and "2b" not in data:
        data["2b"] = data.get("b2", 0)
    if "b3" in data and "3b" not in data:
        data["3b"] = data.get("b3", 0)
    _round_stat_values(data)
    return data


def _normalize_pitching_stats(self: PlayerProfileDialog, data: Dict[str, Any]) -> Dict[str, Any]:
    result = _original("_normalize_pitching_stats")(self, data)
    if "pct" not in result:
        pct = _compute_win_pct(result)
        if pct is not None:
            result["pct"] = pct
    if "oba" not in result:
        oba = _compute_oba(result)
        if oba is not None:
            result["oba"] = oba
    if "dera" not in result and "fip" in result:
        result["dera"] = result["fip"]
    _round_stat_values(result)
    return result


def _collect_stats_history(self: PlayerProfileDialog) -> List[Tuple[str, Dict[str, Any]]]:
    base_rows = _original("_collect_stats_history")(self)
    enriched: List[Tuple[str, Dict[str, Any]]] = []
    for label, data in base_rows:
        if isinstance(data, dict):
            enriched.append((label, _prepare_stat_row(self, label, data)))
        else:
            enriched.append((label, data))
    return enriched


if not hasattr(PlayerProfileDialog, '_create_stats_table'):
    def _fallback_create_stats_table(self, rows, columns):  # pragma: no cover - stub
        return None

    PlayerProfileDialog._create_stats_table = _fallback_create_stats_table  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_build_insights_section'):
    def _fallback_build_insights(self):  # pragma: no cover - stub
        return None

    PlayerProfileDialog._build_insights_section = _fallback_build_insights  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_compute_spray_points'):
    def _fallback_spray_points(self):  # pragma: no cover - stub
        return []

    PlayerProfileDialog._compute_spray_points = _fallback_spray_points  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_compute_rolling_stats'):
    def _fallback_rolling_stats(self):  # pragma: no cover - stub
        return {'dates': [], 'series': {}}

    PlayerProfileDialog._compute_rolling_stats = _fallback_rolling_stats  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_calculate_age'):
    def _fallback_calculate_age(self, birthdate_str: str):  # pragma: no cover - stub
        try:
            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
            today = datetime.today().date()
            return today.year - birthdate.year - (
                (today.month, today.day) < (birthdate.month, birthdate.day)
            )
        except Exception:
            return "?"

    PlayerProfileDialog._calculate_age = _fallback_calculate_age  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_format_height'):
    def _fallback_format_height(self, height: Any) -> str:  # pragma: no cover - stub
        try:
            total_inches = int(height)
        except (TypeError, ValueError):
            return "?"
        feet, inches = divmod(total_inches, 12)
        return f"{feet}'{inches}\""

    PlayerProfileDialog._format_height = _fallback_format_height  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_estimate_overall_rating'):
    def _fallback_estimate_overall_rating(self) -> int:  # pragma: no cover - stub
        try:
            values = []
            if getattr(self, "_is_pitcher", False):
                keys = [
                    "endurance",
                    "control",
                    "movement",
                    "hold_runner",
                    "arm",
                    "fa", "fb", "cu", "cb", "sl", "si", "scb", "kn",
                ]
            else:
                keys = [
                    "ch",
                    "ph",
                    "sp",
                    "pl",
                    "vl",
                    "sc",
                    "fa",
                    "arm",
                    "gf",
                ]
            for key in keys:
                val = getattr(self.player, key, None)
                if isinstance(val, (int, float)):
                    values.append(val)
            if not values:
                return 0
            return max(0, min(99, int(round(sum(values) / len(values)))))
        except Exception:
            return 0

    PlayerProfileDialog._estimate_overall_rating = _fallback_estimate_overall_rating  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_estimate_peak_rating'):
    def _fallback_estimate_peak_rating(self) -> int:  # pragma: no cover - stub
        potential = getattr(self.player, "potential", {}) or {}
        overall = potential.get("overall")
        if isinstance(overall, (int, float)):
            return int(round(overall))
        return self._estimate_overall_rating()

    PlayerProfileDialog._estimate_peak_rating = _fallback_estimate_peak_rating  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_format_rating_label'):
    def _fallback_format_rating_label(self, label: str, value: Any) -> str:  # pragma: no cover - stub
        return f"{label}: {value}"

    PlayerProfileDialog._format_rating_label = _fallback_format_rating_label  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_load_field_diagram_pixmap'):
    def _fallback_load_field_diagram_pixmap(self):  # pragma: no cover - stub
        return None

    PlayerProfileDialog._load_field_diagram_pixmap = _fallback_load_field_diagram_pixmap  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_load_avatar_pixmap'):
    def _fallback_load_avatar_pixmap(self):  # pragma: no cover - stub
        try:
            path = getattr(self.player, "avatar_path", None)
            if path:
                pix = QPixmap(str(path))
                if not pix.isNull():
                    return pix
        except Exception:
            pass
        return QPixmap()

    PlayerProfileDialog._load_avatar_pixmap = _fallback_load_avatar_pixmap  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_stats_to_dict'):
    def _fallback_stats_to_dict(self, stats: Any, is_pitcher: bool) -> Dict[str, Any]:  # pragma: no cover - stub
        if isinstance(stats, dict):
            data = dict(stats)
        elif is_dataclass(stats):
            data = asdict(stats)
        else:
            return {}
        if is_pitcher:
            data = self._normalize_pitching_stats(data)
            _round_stat_values(data)
            return data
        _round_stat_values(data)
        return data

    PlayerProfileDialog._stats_to_dict = _fallback_stats_to_dict  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_normalize_pitching_stats'):
    def _fallback_normalize_pitching_stats(self, data: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - stub
        result = dict(data)
        outs = result.get("outs")
        if outs is not None and "ip" not in result:
            result["ip"] = outs / 3
        ip = result.get("ip", 0)
        if ip:
            er = result.get("er", 0)
            result.setdefault("era", (er * 9) / ip if ip else 0.0)
            walks_hits = result.get("bb", 0) + result.get("h", 0)
            result.setdefault("whip", walks_hits / ip if ip else 0.0)
        _round_stat_values(result)
        return result

    PlayerProfileDialog._normalize_pitching_stats = _fallback_normalize_pitching_stats  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_format_stat'):
    def _fallback_format_stat(self, value: Any) -> str:  # pragma: no cover - stub
        try:
            return f"{float(value):.3f}"
        except Exception:
            return str(value)

    PlayerProfileDialog._format_stat = _fallback_format_stat  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_build_stats_section'):
    def _fallback_build_stats_section(self, stats_history):  # pragma: no cover - stub
        label = QLabel("Statistics unavailable.")
        _set_alignment(label, "AlignCenter")
        return label

    PlayerProfileDialog._build_stats_section = _fallback_build_stats_section  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_build_overview_section'):
    def _fallback_build_overview_section(self):  # pragma: no cover - stub
        return None

    PlayerProfileDialog._build_overview_section = _fallback_build_overview_section  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_build_comparison_panel'):
    def _fallback_build_comparison_panel(self):  # pragma: no cover - stub
        panel = QFrame()
        panel.setLayout(QVBoxLayout())
        panel.setVisible(False)
        return panel

    PlayerProfileDialog._build_comparison_panel = _fallback_build_comparison_panel  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_update_comparison_panel'):
    def _fallback_update_comparison_panel(self):  # pragma: no cover - stub
        pass

    PlayerProfileDialog._update_comparison_panel = _fallback_update_comparison_panel  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_prompt_comparison_player'):
    def _fallback_prompt_comparison_player(self):  # pragma: no cover - stub
        return None

    PlayerProfileDialog._prompt_comparison_player = _fallback_prompt_comparison_player  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_load_player_pool'):
    def _fallback_load_player_pool(self):  # pragma: no cover - stub
        return {}

    PlayerProfileDialog._load_player_pool = _fallback_load_player_pool  # type: ignore[attr-defined]

if not hasattr(PlayerProfileDialog, '_attach_player_stats'):
    def _fallback_attach_player_stats(self, player):  # pragma: no cover - stub
        return getattr(player, "season_stats", {})

    PlayerProfileDialog._attach_player_stats = _fallback_attach_player_stats  # type: ignore[attr-defined]


if not hasattr(PlayerProfileDialog, '_collect_stats_history'):
    def _fallback_collect_stats_history(self):  # pragma: no cover - stub
        rows: List[Tuple[str, Dict[str, Any]]] = []
        is_pitcher = getattr(self.player, "is_pitcher", False)
        season = self._stats_to_dict(getattr(self.player, "season_stats", {}), is_pitcher)
        if season:
            try:
                year_label = f"{self._current_season_year():04d}"
            except Exception:
                year_label = "Season"
            rows.append((year_label, season))
        if rows:
            return rows

        history_entries = getattr(self, "_history_override", []) or []
        aggregated = _aggregate_history_rows(self, history_entries, is_pitcher=is_pitcher)
        if aggregated:
            return aggregated

        fallback_entries: list[Dict[str, Any]] = []
        loader = getattr(self, "_load_history", None)
        iterable_history: Iterable[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
        if callable(loader):
            try:
                candidate = loader()
                if isinstance(candidate, Iterable):
                    iterable_history = candidate
            except Exception:
                iterable_history = []
        for entry_label, _ratings, stats in iterable_history:
            fallback_entries.append(
                {
                    "players": {self.player.player_id: stats},
                    "year": entry_label,
                }
            )
        aggregated = _aggregate_history_rows(self, fallback_entries, is_pitcher=is_pitcher)
        if aggregated:
            return aggregated

        career = self._stats_to_dict(getattr(self.player, "career_stats", {}), is_pitcher)
        if career:
            rows.append(("Career", career))
        return rows

    PlayerProfileDialog._collect_stats_history = _fallback_collect_stats_history  # type: ignore[attr-defined]


# Prime original-method cache before overriding behaviour.
for _method_name in (
    "_collect_stats_history",
    "_create_stats_table",
    "_create_stats_summary",
    "_build_stats_section",
    "_stats_to_dict",
    "_normalize_pitching_stats",
    "_stat_item",
    "_format_stat",
    "_current_season_year",
    "_build_stat_key_footer",
):
    try:
        _original(_method_name)
    except AttributeError:
        pass

# Override with enriched implementations (fallbacks above retain test support).
PlayerProfileDialog._create_stats_table = _create_stats_table  # type: ignore[attr-defined]
PlayerProfileDialog._create_stats_summary = _create_stats_summary  # type: ignore[attr-defined]
PlayerProfileDialog._build_stats_section = _build_stats_section  # type: ignore[attr-defined]
PlayerProfileDialog._collect_stats_history = _collect_stats_history  # type: ignore[attr-defined]
PlayerProfileDialog._stats_to_dict = _stats_to_dict  # type: ignore[attr-defined]
PlayerProfileDialog._normalize_pitching_stats = _normalize_pitching_stats  # type: ignore[attr-defined]
PlayerProfileDialog._stat_item = _stat_item  # type: ignore[attr-defined]
PlayerProfileDialog._format_stat = _format_stat  # type: ignore[attr-defined]
