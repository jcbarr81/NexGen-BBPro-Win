from __future__ import annotations

from typing import Any, Dict, Iterable, List

import csv
import json
from pathlib import Path
from types import SimpleNamespace

PYQT_AVAILABLE = True

try:
    from PyQt6.QtCore import Qt
except ImportError:  # pragma: no cover - test stubs
    PYQT_AVAILABLE = False
    Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(
            AlignCenter=None,
            AlignLeft=None,
            AlignRight=None,
            AlignVCenter=None,
        ),
        ItemDataRole=SimpleNamespace(DisplayRole=None, EditRole=None, UserRole=None),
        ItemFlag=SimpleNamespace(ItemIsEditable=None),
        SortOrder=SimpleNamespace(AscendingOrder=None, DescendingOrder=None),
    )

try:
    from PyQt6.QtWidgets import (
        QComboBox,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QStatusBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
        QHeaderView,
    )
except ImportError:  # pragma: no cover - test stubs
    PYQT_AVAILABLE = False
    class _QtDummy:
        EditTrigger = SimpleNamespace(NoEditTriggers=None)
        SelectionBehavior = SimpleNamespace(SelectRows=None)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):
            def _dummy(*_args, **_kwargs):
                return self

            return _dummy

    for _name in [
        "QComboBox",
        "QDialog",
        "QFrame",
        "QHBoxLayout",
        "QLabel",
        "QLineEdit",
        "QPushButton",
        "QStatusBar",
        "QTabWidget",
        "QTableWidget",
        "QTableWidgetItem",
        "QVBoxLayout",
        "QWidget",
    ]:
        globals()[_name] = _QtDummy

    class QHeaderView:  # type: ignore[too-many-ancestors]
        class ResizeMode:
            Stretch = None
            ResizeToContents = None

from models.team import Team
from models.roster import Roster
from models.base_player import BasePlayer
from utils.roster_loader import load_roster
from utils.player_loader import load_players_from_csv
from utils.path_utils import get_base_dir
from utils.stats_persistence import load_stats as _load_season_stats
try:
    # Best-effort import; not critical for headless tests
    from utils.stats_persistence import merge_daily_history as _merge_daily_history  # type: ignore
except Exception:  # pragma: no cover - optional import
    _merge_daily_history = None  # type: ignore
from .stat_helpers import (
    format_number,
    format_ip,
    batting_summary,
    pitching_summary,
)

DATA_DIR = get_base_dir() / "data"
PLAYERS_FILE = DATA_DIR / "players.csv"
# Stats file path is resolved by utils.stats_persistence; keep constant for reference only
STATS_FILE = DATA_DIR / "season_stats.json"

RETRO_GREEN = "#0f3b19"
RETRO_GREEN_DARK = "#0b2a12"
RETRO_GREEN_TABLE = "#164a22"
RETRO_BEIGE = "#d2ba8f"
RETRO_YELLOW = "#ffd34d"
RETRO_TEXT = "#ffffff"
RETRO_BORDER = "#3a5f3a"


def _set_style(widget: Any, style: str) -> None:
    if not hasattr(widget, "setStyleSheet"):
        return
    if not PYQT_AVAILABLE:
        return
    try:
        widget.setStyleSheet(style)
    except Exception:
        pass

def _call_if_exists(obj: Any, method: str, *args, **kwargs) -> None:
    func = getattr(obj, method, None)
    if callable(func):
        try:
            func(*args, **kwargs)
        except Exception:
            pass

def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _alignment(*names: str) -> Any:
    enum = getattr(Qt, "AlignmentFlag", None)
    if enum is None:
        return None
    value = 0
    for name in names:
        flag = getattr(enum, name, None)
        if flag is None:
            return None
        value |= flag
    return value


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None

def _has_stat_value(value: Any) -> bool:
    numeric = _coerce_float(value)
    if numeric is not None:
        return abs(numeric) > 1e-9
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _normalize_player_stats(data: Dict[str, Any] | None) -> Dict[str, Any]:
    stats = dict(data or {})
    if "b2" in stats and "2b" not in stats:
        stats["2b"] = stats.get("b2", 0)
    if "b3" in stats and "3b" not in stats:
        stats["3b"] = stats.get("b3", 0)
    stats.setdefault("w", stats.get("wins", stats.get("w", 0)))
    stats.setdefault("l", stats.get("losses", stats.get("l", 0)))
    return stats


def _normalize_team_stats(data: Dict[str, Any] | None) -> Dict[str, Any]:
    stats = dict(data or {})
    stats.setdefault("w", stats.get("wins", stats.get("w", 0)))
    stats.setdefault("l", stats.get("losses", stats.get("l", 0)))
    stats.setdefault("g", stats.get("g", stats.get("games", 0)))
    stats.setdefault("r", stats.get("r", 0))
    stats.setdefault("ra", stats.get("ra", 0))
    return stats


def _games_from_history() -> dict[str, int]:
    # Load via stats_persistence to ensure identical resolution as the simulator
    try:
        # Ensure canonical history is up to date with daily shards
        if _merge_daily_history is not None:
            try:
                _merge_daily_history()
            except Exception:
                pass
        data = _load_season_stats()
    except Exception:
        return {}
    history = data.get("history", [])
    last_pa: dict[str, int] = {}
    games: dict[str, int] = {}
    for snap in history:
        players = snap.get("players", {}) or {}
        for pid, stats in players.items():
            try:
                pa = int(stats.get("pa", 0) or 0)
            except Exception:
                pa = 0
            prev = last_pa.get(pid)
            if prev is None:
                if pa > 0:
                    games[pid] = games.get(pid, 0) + 1
            else:
                if pa > prev:
                    games[pid] = games.get(pid, 0) + 1
            last_pa[pid] = pa
    return games


def _load_players_lookup() -> tuple[Dict[str, SimpleNamespace], Dict[str, Dict[str, Any]]]:
    # Use centralized loader so GUI and simulator read the same file
    try:
        stats = _load_season_stats()
    except Exception:
        stats = {"players": {}, "teams": {}}
    player_stats: Dict[str, Dict[str, Any]] = stats.get("players", {})
    team_stats: Dict[str, Dict[str, Any]] = stats.get("teams", {})
    lookup: Dict[str, SimpleNamespace] = {}
    try:
        with PLAYERS_FILE.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pid = row["player_id"]
                stats_block = _normalize_player_stats(player_stats.get(pid))
                is_pitcher = str(row.get("is_pitcher", "")).strip().lower() in {"1", "true", "yes"}
                lookup[pid] = SimpleNamespace(
                    player_id=pid,
                    first_name=row.get("first_name", ""),
                    last_name=row.get("last_name", ""),
                    is_pitcher=is_pitcher,
                    season_stats=stats_block,
                )
    except OSError:
        lookup = {}
    return lookup, team_stats


_BATTING_COLS: List[str] = [
    "g",
    "ab",
    "r",
    "h",
    "2b",
    "3b",
    "hr",
    "rbi",
    "bb",
    "so",
    "sb",
    "avg",
    "obp",
    "slg",
]

_PITCHING_COLS: List[str] = [
    "w",
    "l",
    "era",
    "g",
    "gs",
    "sv",
    "ip",
    "h",
    "er",
    "bb",
    "so",
    "whip",
]

_TEAM_COLUMNS: List[str] = ["g", "w", "l", "r", "ra", "opp_pa", "opp_hr"]


class RetroStatusFooter(QStatusBar):
    """Footer mirroring the retro palette used by roster dialogs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _call_if_exists(self, "setSizeGripEnabled", False)
        _set_style(self, 
            f"background:{RETRO_GREEN}; color:{RETRO_TEXT}; border-top: 1px solid {RETRO_BORDER};"
        )
        container = QWidget(self)
        layout = QHBoxLayout(container)
        _call_if_exists(layout, "setContentsMargins", 6, 0, 6, 0)
        _call_if_exists(layout, "setSpacing", 6)
        left = QLabel("NexGen-BBpro")
        _set_style(left, f"color:{RETRO_YELLOW}; font-weight:600;")
        right = QLabel("Team Statistics")
        _set_style(right, f"color:{RETRO_TEXT}; font-weight:500;")
        align_flags = _alignment("AlignRight", "AlignVCenter")
        if align_flags is not None:
            _call_if_exists(right, "setAlignment", align_flags)
        spacer = QWidget()
        _call_if_exists(spacer, "setObjectName", "FooterSpacer")
        _call_if_exists(spacer, "setMinimumWidth", 10)
        layout.addWidget(left)
        layout.addWidget(spacer, 1)
        layout.addWidget(right)
        _call_if_exists(self, "addPermanentWidget", container, 1)


class TeamStatsWindow(QDialog):
    def __init__(
        self,
        team: Team,
        players: Dict[str, BasePlayer],
        roster: Roster,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        _call_if_exists(self, "setObjectName", "TeamStatsWindow")
        self.team = team
        player_lookup, team_stats = _load_players_lookup()
        self.players = player_lookup
        try:
            self.roster = load_roster(team.team_id)
        except Exception:
            self.roster = roster

        hist_games = _games_from_history()
        team.season_stats = _normalize_team_stats(team_stats.get(team.team_id))
        team_games = int(team.season_stats.get("g", 0) or 0)
        for pid, entry in self.players.items():
            g_saved = int(entry.season_stats.get("g", 0) or 0)
            g_hist = int(hist_games.get(pid, 0) or 0)
            value = max(g_saved, g_hist)
            if team_games:
                value = min(value, team_games)
            entry.season_stats["g"] = value

        self.setWindowTitle("Team Stats")
        if callable(getattr(self, "resize", None)):
            self.resize(1120, 700)

        self._apply_global_palette()

        layout = QVBoxLayout(self)
        _call_if_exists(layout, "setContentsMargins", 8, 8, 8, 8)
        _call_if_exists(layout, "setSpacing", 8)

        layout.addWidget(self._build_header(team))

        self.tabs = QTabWidget()
        _call_if_exists(self.tabs, "setDocumentMode", True)
        _call_if_exists(self.tabs, "setTabsClosable", False)
        _call_if_exists(self.tabs, "setMovable", False)
        layout.addWidget(self.tabs, 1)

        # Guard: if the active roster is empty or unresolved, fall back to all players
        act_ids = list(self.roster.act)
        if not act_ids:
            act_ids = list(self.players.keys())

        batter_ids = [
            pid
            for pid in act_ids
            if pid in self.players and not getattr(self.players[pid], "is_pitcher", False)
        ]
        pitcher_ids = [
            pid
            for pid in act_ids
            if pid in self.players and getattr(self.players[pid], "is_pitcher", False)
        ]

        batters = [self.players[pid] for pid in batter_ids]
        pitchers = [self.players[pid] for pid in pitcher_ids]
        self._debug_team_id = getattr(team, 'team_id', 'UNK')

        # Debug dump removed to avoid writing temporary files
        if False:
            debug_path = DATA_DIR / f"_debug_team_stats_{team.team_id}.txt"
            with debug_path.open("w", encoding="utf-8") as fh:
                fh.write(f"Team {team.team_id} — roster hitters: {len(batter_ids)}\n")
                fh.write("player_id,name,G,AB,H,BB,HR,SB\n")
                for pid in batter_ids:
                    p = self.players.get(pid)
                    if not p:
                        fh.write(f"{pid},<missing in players.csv>\n")
                        continue
                    s = getattr(p, "season_stats", {}) or {}
                    name = f"{getattr(p,'first_name','')} {getattr(p,'last_name','')}".strip()
                    fh.write(
                        f"{pid},{name},{s.get('g',0)},{s.get('ab',0)},{s.get('h',0)},{s.get('bb',0)},{s.get('hr',0)},{s.get('sb',0)}\n"
                    )
        

        self.tabs.addTab(
            self._build_player_tab(batters, _BATTING_COLS, title="Batting"),
            "Batting",
        )
        self.tabs.addTab(
            self._build_player_tab(pitchers, _PITCHING_COLS, title="Pitching"),
            "Pitching",
        )
        self.tabs.addTab(self._build_team_totals(team), "Team Totals")

        layout.addWidget(RetroStatusFooter(self))

    # ------------------------------------------------------------------
    # Palette helpers
    def _apply_global_palette(self) -> None:
        _set_style(self, 
            f"""
            QDialog#TeamStatsWindow {{
                background:{RETRO_GREEN};
            }}
            QTabWidget::pane {{
                border: 1px solid {RETRO_BORDER};
                background:{RETRO_GREEN_DARK};
            }}
            QTabBar::tab {{
                background:{RETRO_GREEN_DARK};
                color:{RETRO_TEXT};
                padding: 8px 18px;
                border: 1px solid {RETRO_BORDER};
                font-weight:600;
            }}
            QTabBar::tab:selected {{
                background:{RETRO_GREEN_TABLE};
                color:{RETRO_YELLOW};
            }}
            QLabel#SectionHeading {{
                color:{RETRO_YELLOW};
                font-weight:700;
                letter-spacing:0.6px;
            }}
            QLabel#EmptyMessage {{
                color:{RETRO_TEXT};
                font-style:italic;
            }}
            QLineEdit, QComboBox {{
                background:{RETRO_GREEN_TABLE};
                color:{RETRO_TEXT};
                border:1px solid {RETRO_BORDER};
                padding:4px 6px;
            }}
            QPushButton {{
                background:{RETRO_BEIGE};
                color:#222;
                border:1px solid {RETRO_BORDER};
                padding:4px 12px;
                font-weight:600;
            }}
            QPushButton::hover {{
                background:#e8cc9f;
            }}
            """
        )

    # ------------------------------------------------------------------
    # Header & summary widgets
    def _build_header(self, team: Team) -> QWidget:
        wrapper = QFrame()
        _set_style(wrapper, 
            f"background:{RETRO_GREEN_DARK}; border:1px solid {RETRO_BORDER};"
        )
        layout = QVBoxLayout(wrapper)
        _call_if_exists(layout, "setContentsMargins", 12, 10, 12, 12)
        _call_if_exists(layout, "setSpacing", 10)

        name = f"{team.city} {team.name}".strip()
        title = QLabel(name if name.strip() else team.team_id)
        _call_if_exists(title, "setObjectName", "HeaderTitle")
        _set_style(title, 
            f"color:{RETRO_YELLOW}; font-size:20px; font-weight:800; letter-spacing:0.5px;"
        )
        layout.addWidget(title)

        stats = dict(getattr(team, "season_stats", {}) or {})
        wins = int(stats.get("w", 0))
        losses = int(stats.get("l", 0))
        games = stats.get("g", 0)
        run_diff = stats.get("r", 0) - stats.get("ra", 0)
        pct = wins / (wins + losses) if (wins + losses) else 0.0
        metrics = [
            ("Record", f"{wins}-{losses}" if (wins or losses) else "--"),
            ("Win %", format_number(pct, decimals=3) if (wins or losses) else "--"),
            ("Games", format_number(games, decimals=0) if games else "--"),
            ("Run Diff", format_number(run_diff, decimals=0) if games else "--"),
            ("Runs", format_number(stats.get("r", 0), decimals=0) if games else "--"),
            ("Runs Allowed", format_number(stats.get("ra", 0), decimals=0) if games else "--"),
        ]

        strip = QFrame()
        _set_style(strip, 
            f"background:{RETRO_GREEN_TABLE}; border:1px solid {RETRO_BORDER};"
        )
        strip_layout = QHBoxLayout(strip)
        _call_if_exists(strip_layout, "setContentsMargins", 10, 8, 10, 8)
        _call_if_exists(strip_layout, "setSpacing", 12)
        for label, value in metrics:
            strip_layout.addWidget(self._metric_badge(label, value))
        strip_layout.addStretch(1)
        layout.addWidget(strip)
        return wrapper

    def _metric_badge(self, label: str, value: str) -> QWidget:
        badge = QFrame()
        _set_style(badge, 
            f"background:{RETRO_GREEN}; border:1px solid {RETRO_BORDER};"
        )
        layout = QVBoxLayout(badge)
        _call_if_exists(layout, "setContentsMargins", 8, 4, 8, 4)
        _call_if_exists(layout, "setSpacing", 2)
        title = QLabel(label.upper())
        _set_style(title, f"color:{RETRO_YELLOW}; font-size:10px; font-weight:700;")
        val = QLabel(value)
        _set_style(val, f"color:{RETRO_TEXT}; font-size:14px; font-weight:700;")
        layout.addWidget(title)
        layout.addWidget(val)
        return badge

    def _build_summary_strip(self, pairs: List[tuple[str, str]]) -> QWidget:
        strip = QFrame()
        _set_style(strip, 
            f"background:{RETRO_GREEN_DARK}; border:1px solid {RETRO_BORDER};"
        )
        layout = QHBoxLayout(strip)
        _call_if_exists(layout, "setContentsMargins", 10, 6, 10, 6)
        _call_if_exists(layout, "setSpacing", 12)
        for label, value in pairs:
            layout.addWidget(self._metric_badge(label, value))
        layout.addStretch(1)
        return strip

    def _empty_label(self, message: str) -> QLabel:
        label = QLabel(message)
        _call_if_exists(label, "setObjectName", "EmptyMessage")
        align_center = _alignment("AlignCenter")
        if align_center is not None:
            _call_if_exists(label, "setAlignment", align_center)
        return label

    # ------------------------------------------------------------------
    # Tabs and tables
    def _build_player_tab(
        self,
        players: Iterable[BasePlayer],
        columns: List[str],
        *,
        title: str,
    ) -> QWidget:
        player_list = list(players)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        _call_if_exists(layout, "setContentsMargins", 10, 10, 10, 10)
        _call_if_exists(layout, "setSpacing", 8)

        heading = QLabel(title.upper())
        _call_if_exists(heading, "setObjectName", "SectionHeading")
        layout.addWidget(heading)

        headers = ["Name"] + [col.upper() for col in columns]
        table = QTableWidget(len(player_list), len(headers))
        self._configure_table(table, headers)
        # Prevent row reordering while we populate cells; re-enable after filling.
        try:
            table.setSortingEnabled(False)
        except Exception:
            pass

        any_stats = False
        # Debug row output removed to avoid writing temporary files
        debug_rows_path = None
        if False:
            if columns is _BATTING_COLS:
                debug_rows_path = DATA_DIR / f"_debug_team_stats_rows_{getattr(self, '_debug_team_id', 'UNK')}_batting.csv"
            elif columns is _PITCHING_COLS:
                debug_rows_path = DATA_DIR / f"_debug_team_stats_rows_{getattr(self, '_debug_team_id', 'UNK')}_pitching.csv"
                with debug_rows_path.open('w', encoding='utf-8') as fh:
                    fh.write('player_id,name,' + ','.join(columns) + '\n')
        
        for row, player in enumerate(player_list):
            name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
            name_item = self._text_item(name, align_left=True)
            try:
                pid = getattr(player, 'player_id', '')
                name_item.setData(Qt.ItemDataRole.UserRole, pid)
            except Exception:
                pass
            _call_if_exists(table, "setItem", row, 0, name_item)
            stats = getattr(player, "season_stats", {}) or {}
            is_pitching = columns is _PITCHING_COLS
            stats = self._normalize_pitching(stats) if is_pitching else self._normalize_batting(stats)
            has_stats = self._player_has_stats(stats, columns)
            any_stats = any_stats or has_stats
            # Write cells and capture the exact values used
            row_values = []
            for col, key in enumerate(columns, start=1):
                value = stats.get(key, 0)
                stat_item = self._stat_item(key, value, has_stats=has_stats)
                _call_if_exists(table, "setItem", row, col, stat_item)
                row_values.append(value)
            # Debug row output removed

        if not player_list:
            layout.addWidget(self._empty_label("No players on the active roster."))
            layout.addStretch(1)
            return tab

        if any_stats:
            summary = batting_summary(player_list) if columns is _BATTING_COLS else pitching_summary(player_list)
            layout.addWidget(self._build_summary_strip(summary))
        else:
            layout.addWidget(self._empty_label("No statistics recorded yet."))

        # Re-enable sorting now that population is complete
        try:
            table.setSortingEnabled(True)
        except Exception:
            pass
        # Open player profile on double click
        try:
            table.itemDoubleClicked.connect(lambda item, table=table: self._open_player_from_table(item, table))
        except Exception:
            pass
        placeholder = f"Search {'pitchers' if columns is _PITCHING_COLS else 'hitters'}"
        try:
            column_count = table.columnCount()
        except Exception:
            column_count = len(headers)
        default_sort = 1 if column_count > 1 else 0
        layout.addWidget(self._build_filter_bar(table, placeholder=placeholder, default_sort=default_sort))
        layout.addWidget(table, 1)
        return tab

    def _open_player_from_table(self, item: QTableWidgetItem, table: QTableWidget) -> None:
        try:
            row = item.row()
            name_cell = table.item(row, 0)
            pid = name_cell.data(Qt.ItemDataRole.UserRole) if name_cell else None
            if not pid:
                return
            # Load full player objects to feed the profile dialog
            players = {p.player_id: p for p in load_players_from_csv(str(PLAYERS_FILE))}
            player = players.get(pid)
            if not player:
                return
            from .player_profile_dialog import PlayerProfileDialog
            try:
                dlg = PlayerProfileDialog(player, self)
                if callable(getattr(dlg, 'exec', None)):
                    dlg.exec()
            except Exception:
                pass
        except Exception:
            pass

    def _build_team_totals(self, team: Team) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        _call_if_exists(layout, "setContentsMargins", 10, 10, 10, 10)
        _call_if_exists(layout, "setSpacing", 8)

        heading = QLabel("TEAM TOTALS")
        _call_if_exists(heading, "setObjectName", "SectionHeading")
        layout.addWidget(heading)

        stats = dict(getattr(team, "season_stats", {}) or {})
        has_stats = self._team_has_stats(stats)

        headers = ["CATEGORY", "VALUE"]
        table = QTableWidget(len(_TEAM_COLUMNS), len(headers))
        self._configure_table(table, headers)
        try:
            horiz = table.horizontalHeader()
        except Exception:
            horiz = None
        if horiz is not None:
            resize_mode = getattr(QHeaderView, 'ResizeMode', SimpleNamespace(ResizeToContents=None))
            try:
                if resize_mode.ResizeToContents is not None:
                    horiz.setSectionResizeMode(0, resize_mode.ResizeToContents)
                    horiz.setSectionResizeMode(1, resize_mode.ResizeToContents)
            except Exception:
                pass
            try:
                horiz.setStretchLastSection(False)
            except Exception:
                pass
        # Prevent the table from reordering rows while we populate cells.
        # With sorting enabled, Qt may re-sort after each setItem call which
        # can misalign category/value pairs and leave many cells blank.
        try:
            table.setSortingEnabled(False)
        except Exception:
            pass
        for row, key in enumerate(_TEAM_COLUMNS):
            category = key.upper()
            _call_if_exists(table, "setItem", row, 0, self._text_item(category, align_left=True))
            _call_if_exists(
                table,
                "setItem",
                row,
                1,
                self._stat_item(key, stats.get(key, 0), has_stats=has_stats),
            )
        # Re-enable sorting now that the table is fully populated.
        try:
            table.setSortingEnabled(True)
        except Exception:
            pass

        if not has_stats:
            layout.addWidget(self._empty_label("No team totals available yet."))

        layout.addWidget(self._build_filter_bar(table, placeholder="Search categories", default_sort=0))
        layout.addWidget(table, 1)
        return tab

    # ------------------------------------------------------------------
    # Table helpers
    def _configure_table(self, table: QTableWidget, headers: List[str]) -> None:
        try:
            table.setHorizontalHeaderLabels(headers)
        except Exception:
            pass
        try:
            header = table.verticalHeader()
        except Exception:
            header = None
        if header is not None:
            try:
                header.setVisible(False)
            except Exception:
                pass
        try:
            table.setAlternatingRowColors(False)
        except Exception:
            pass
        try:
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        except Exception:
            pass
        try:
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        except Exception:
            pass
        try:
            horiz = table.horizontalHeader()
        except Exception:
            horiz = None
        if horiz is not None:
            resize_mode = getattr(QHeaderView, 'ResizeMode', SimpleNamespace(Stretch=None, ResizeToContents=None))
            try:
                if resize_mode.Stretch is not None:
                    horiz.setSectionResizeMode(resize_mode.Stretch)
            except Exception:
                pass
            if headers:
                try:
                    if resize_mode.ResizeToContents is not None:
                        horiz.setSectionResizeMode(0, resize_mode.ResizeToContents)
                except Exception:
                    pass
            align_flags = _alignment("AlignLeft", "AlignVCenter")
            if align_flags is not None:
                try:
                    horiz.setDefaultAlignment(align_flags)
                except Exception:
                    pass
            try:
                horiz.setSectionsClickable(True)
            except Exception:
                pass
        try:
            table.setWordWrap(False)
        except Exception:
            pass
        try:
            table.setSortingEnabled(True)
        except Exception:
            pass
        try:
            table.setShowGrid(True)
        except Exception:
            pass
        self._style_table(table)


    def _style_table(self, table: QTableWidget) -> None:
        _set_style(table, 
            f"QTableWidget {{ background:{RETRO_GREEN_TABLE}; color:{RETRO_TEXT};"
            f" gridline-color:{RETRO_BORDER}; selection-background-color:#245b2b;"
            f" selection-color:{RETRO_TEXT}; font: 12px 'Segoe UI'; }}"
            f"QHeaderView::section {{ background:{RETRO_GREEN}; color:{RETRO_TEXT};"
            f" border: 1px solid {RETRO_BORDER}; font-weight:600; }}"
            f"QScrollBar:vertical {{ background:{RETRO_GREEN_DARK}; width: 12px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background:{RETRO_BEIGE}; min-height: 24px; }}"
        )

    def _build_filter_bar(
        self,
        table: QTableWidget,
        *,
        placeholder: str,
        default_sort: int = 0,
    ) -> QWidget:
        bar = QFrame()
        _set_style(bar, 
            f"background:{RETRO_GREEN_DARK}; border:1px solid {RETRO_BORDER};"
        )
        layout = QHBoxLayout(bar)
        _call_if_exists(layout, "setContentsMargins", 10, 6, 10, 6)
        _call_if_exists(layout, "setSpacing", 8)

        label = QLabel("Filter")
        _set_style(label, f"color:{RETRO_YELLOW}; font-weight:600;")
        search = QLineEdit()
        _call_if_exists(search, "setPlaceholderText", placeholder)
        clear_btn = QPushButton("Clear")
        sort_label = QLabel("Sort by")
        _set_style(sort_label, f"color:{RETRO_YELLOW}; font-weight:600;")
        sort_combo = QComboBox()
        try:
            column_count = table.columnCount()
        except Exception:
            column_count = 0
        for col in range(column_count):
            try:
                header = table.horizontalHeaderItem(col)
                header_text = header.text() if header else str(col)
            except Exception:
                header_text = str(col)
            try:
                sort_combo.addItem(header_text, col)
            except Exception:
                pass
        if default_sort >= column_count:
            default_sort = 0
        try:
            sort_combo.setCurrentIndex(default_sort)
        except Exception:
            pass

        _call_if_exists(layout, "addWidget", label)
        _call_if_exists(layout, "addWidget", search, 1)
        _call_if_exists(layout, "addWidget", clear_btn)
        _call_if_exists(layout, "addSpacing", 12)
        _call_if_exists(layout, "addWidget", sort_label)
        _call_if_exists(layout, "addWidget", sort_combo)
        _call_if_exists(layout, "addStretch", 1)

        def apply_filter() -> None:
            term = search.text().strip().lower()
            try:
                rows = table.rowCount()
            except Exception:
                rows = 0
            try:
                cols = table.columnCount()
            except Exception:
                cols = 0
            for row in range(rows):
                match = not term
                if not match:
                    for col in range(cols):
                        try:
                            item = table.item(row, col)
                            text = item.text().lower() if item else ""
                        except Exception:
                            text = ""
                        if term in text:
                            match = True
                            break
                try:
                    table.setRowHidden(row, not match)
                except Exception:
                    pass

        def apply_sort() -> None:
            try:
                column = sort_combo.currentData()
            except Exception:
                column = None
            if column is None:
                return
            sort_enum = getattr(Qt, "SortOrder", None)
            ascending = getattr(sort_enum, "AscendingOrder", None) if sort_enum else None
            descending = getattr(sort_enum, "DescendingOrder", None) if sort_enum else None
            if ascending is None or descending is None:
                return
            order = ascending if int(column) == 0 else descending
            try:
                header = table.horizontalHeader()
                header.setSortIndicator(int(column), order)
            except Exception:
                pass
            try:
                table.sortItems(int(column), order)
            except Exception:
                pass

        search.textChanged.connect(apply_filter)
        clear_btn.clicked.connect(lambda: search.clear())
        sort_combo.currentIndexChanged.connect(lambda *_: apply_sort())
        apply_sort()
        return bar

    def _text_item(self, text: str, *, align_left: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        try:
            flags = item.flags()
            if flags is not None:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)
        except Exception:
            pass
        align_enum = getattr(Qt, "AlignmentFlag", None)
        left_flag = getattr(align_enum, "AlignLeft", None) if align_enum else None
        right_flag = getattr(align_enum, "AlignRight", None) if align_enum else None
        vcenter_flag = getattr(align_enum, "AlignVCenter", None) if align_enum else None
        alignment_flag = left_flag if align_left else right_flag
        try:
            if alignment_flag is not None and vcenter_flag is not None:
                item.setTextAlignment(alignment_flag | vcenter_flag)
        except Exception:
            pass
        return item


    def _stat_item(self, key: str, value: Any, *, has_stats: bool) -> QTableWidgetItem:
        key_lower = key.lower()
        # Always display a value (zero if missing) so rows are never blank when a player is listed.
        # This avoids confusion when stats exist but a previous gating heuristic hides them.
        if key_lower in {"avg", "obp", "slg", "era", "whip"}:
            display = format_number(value, decimals=3)
        elif key_lower == "ip":
            display = format_ip(value)
        else:
            display = format_number(value, decimals=0)
        coerced = _coerce_float(value)
        if coerced is None:
            try:
                coerced = float(display) if display else 0.0
            except (TypeError, ValueError):
                coerced = 0.0
        numeric = coerced
        # Use numeric-aware item so sorting is reliable for all numeric columns
        item = _NumericItem(display)
        try:
            flags = item.flags()
            editable = getattr(Qt.ItemFlag, "ItemIsEditable", None)
            if flags is not None and editable is not None:
                item.setFlags(flags & ~editable)
        except Exception:
            pass
        align = _alignment("AlignRight", "AlignVCenter")
        if align is not None:
            try:
                item.setTextAlignment(align)
            except Exception:
                pass
        # Attach numeric sort key (UserRole) without changing display
        try:
            item.setData(Qt.ItemDataRole.UserRole, numeric)
        except Exception:
            pass
        return item

    def _normalize_batting(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(stats)
        if "b2" in data and "2b" not in data:
            data["2b"] = data.get("b2", 0)
        if "b3" in data and "3b" not in data:
            data["3b"] = data.get("b3", 0)
        return data

    def _normalize_pitching(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(stats)
        if "ip" not in data:
            outs = data.get("outs")
            if outs is not None:
                data["ip"] = outs / 3
        ip = data.get("ip", 0)
        if ip:
            er = data.get("er", 0)
            walks_hits = data.get("bb", 0) + data.get("h", 0)
            data.setdefault("era", (er * 9) / ip if ip else 0.0)
            data.setdefault("whip", walks_hits / ip if ip else 0.0)
        data.setdefault("w", data.get("wins", data.get("w", 0)))
        data.setdefault("l", data.get("losses", data.get("l", 0)))
        return data

    # ------------------------------------------------------------------
    # Activity helpers
    def _player_has_stats(self, stats: Dict[str, Any], columns: Iterable[str]) -> bool:
        if not stats:
            return False
        if _has_stat_value(stats.get("g")):
            return True
        for key in columns:
            if key == "g":
                continue
            if _has_stat_value(stats.get(key)):
                return True
        return False

    def _team_has_stats(self, stats: Dict[str, Any]) -> bool:
        if not stats:
            return False
        for key in ["g"] + _TEAM_COLUMNS:
            if _has_stat_value(stats.get(key)):
                return True
        return False











class _NumericItem(QTableWidgetItem):
    """Table item that sorts by a numeric key (UserRole) if present.

    Keeps display text as-is but ensures sorting uses the numeric value.
    """

    def __lt__(self, other: "QTableWidgetItem") -> bool:  # type: ignore[override]
        try:
            a = self.data(Qt.ItemDataRole.UserRole)
            b = other.data(Qt.ItemDataRole.UserRole)
            if a is None:
                a = float(self.text() or 0)
            if b is None:
                b = float(other.text() or 0)
            return float(a) < float(b)
        except Exception:
            # Fallback to default behaviour if conversion fails
            return super().__lt__(other)
