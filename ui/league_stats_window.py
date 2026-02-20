from __future__ import annotations

from typing import Any, Dict, Iterable, List

import csv
import json
from pathlib import Path
from types import SimpleNamespace

try:
    from PyQt6.QtCore import Qt
except ImportError:  # pragma: no cover - test stubs
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
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QHeaderView,
    )
except ImportError:  # pragma: no cover - test stubs
    class _QtDummy:
        EditTrigger = SimpleNamespace(NoEditTriggers=None)
        SelectionBehavior = SimpleNamespace(SelectRows=None)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):
            def _dummy(*_args, **_kwargs):
                return self

            return _dummy

    QComboBox = QDialog = QHBoxLayout = QLabel = QLineEdit = QPushButton = QTabWidget = QTableWidget = QTableWidgetItem = QVBoxLayout = _QtDummy

    class QHeaderView:  # type: ignore[too-many-ancestors]
        class ResizeMode:
            Stretch = None
            ResizeToContents = None

from utils.path_utils import ActivePath, get_data_dir
from utils.player_loader import load_players_from_csv
from utils.stats_persistence import load_stats as _load_season_stats

DATA_DIR = ActivePath(get_data_dir)
PLAYERS_FILE = ActivePath(lambda: get_data_dir() / "players.csv")
STATS_FILE = ActivePath(lambda: get_data_dir() / "season_stats.json")


def _games_from_history() -> Dict[str, int]:
    """Return inferred games played per player from history snapshots.

    Uses day-to-day plate-appearance deltas to avoid trusting any pre-existing
    ``g`` values embedded in snapshots, which can carry over from previous
    seasons. If a player's PA increases on a snapshot day, we count that as a
    game appearance. This mirrors the heuristic used by the Team Stats view and
    is robust even when fielding appearances aren't recorded for pinch hitters.
    """
    try:
        stats = _load_season_stats()
    except Exception:
        return {}
    history = stats.get('history', [])
    last_pa: Dict[str, int] = {}
    games: Dict[str, int] = {}
    for snapshot in history:
        players = snapshot.get('players', {}) if isinstance(snapshot, dict) else {}
        if not isinstance(players, dict):
            continue
        for player_id, data in players.items():
            if not isinstance(data, dict):
                continue
            try:
                pa = int(data.get('pa', 0) or 0)
            except Exception:
                pa = 0
            prev = last_pa.get(player_id)
            if prev is None:
                if pa > 0:
                    games[player_id] = games.get(player_id, 0) + 1
            else:
                if pa > prev:
                    games[player_id] = games.get(player_id, 0) + 1
            last_pa[player_id] = pa
    return games


def _normalize_player_stats(data: Dict[str, Any] | None) -> Dict[str, Any]:
    stats = dict(data or {})
    if 'b2' in stats and '2b' not in stats:
        stats['2b'] = stats.get('b2', 0)
    if 'b3' in stats and '3b' not in stats:
        stats['3b'] = stats.get('b3', 0)
    stats.setdefault('w', stats.get('wins', stats.get('w', 0)))
    stats.setdefault('l', stats.get('losses', stats.get('l', 0)))
    return stats


def _normalize_team_stats(data: Dict[str, Any] | None) -> Dict[str, Any]:
    stats = dict(data or {})
    stats.setdefault('w', stats.get('wins', stats.get('w', 0)))
    stats.setdefault('l', stats.get('losses', stats.get('l', 0)))
    stats.setdefault('g', stats.get('g', stats.get('games', 0)))
    stats.setdefault('r', stats.get('r', 0))
    stats.setdefault('ra', stats.get('ra', 0))
    return stats


def _load_players_with_stats() -> tuple[list[SimpleNamespace], Dict[str, Any]]:
    try:
        stats = _load_season_stats()
    except Exception:
        stats = {"players": {}, "teams": {}}
    player_stats: Dict[str, Dict[str, Any]] = stats.get('players', {})
    team_stats: Dict[str, Dict[str, Any]] = stats.get('teams', {})
    entries: list[SimpleNamespace] = []
    meta: Dict[str, Dict[str, str]] = {}
    try:
        with PLAYERS_FILE.open('r', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            meta = {row['player_id']: row for row in reader}
    except OSError:
        meta = {}
    for pid, data in meta.items():
        stats_block = _normalize_player_stats(player_stats.get(pid))
        is_pitcher = str(data.get('is_pitcher', '')).strip().lower() in {'1', 'true', 'yes'}
        entry = SimpleNamespace(
            player_id=pid,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            is_pitcher=is_pitcher,
            season_stats=stats_block,
        )
        entries.append(entry)
    return entries, team_stats


from models.base_player import BasePlayer
from .components import Card, section_title, build_metric_row, ensure_layout


def _call_if_exists(obj, method: str, *args, **kwargs) -> None:
    func = getattr(obj, method, None)
    if callable(func):
        try:
            func(*args, **kwargs)
        except Exception:
            pass


def _alignment(*names: str):
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
from .stat_helpers import (
    format_number,
    format_ip,
    batting_summary,
    pitching_summary,
)

_TEAM_COLUMNS: List[str] = ["team", "g", "w", "l", "r", "ra", "der"]
_BATTING_COLS: List[str] = ["g", "ab", "r", "h", "2b", "3b", "hr", "rbi", "bb", "so", "sb", "avg", "obp", "slg"]
_PITCHING_COLS: List[str] = ["w", "l", "era", "g", "gs", "sv", "ip", "h", "er", "bb", "so", "whip"]


class LeagueStatsWindow(QDialog):
    def __init__(
        self,
        teams: Iterable[Team],
        players: Iterable[BasePlayer],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if callable(getattr(self, "setWindowTitle", None)):
            self.setWindowTitle("League Statistics")
        if callable(getattr(self, "resize", None)):
            self.resize(1120, 700)

        layout = QVBoxLayout(self)
        if callable(getattr(layout, "setContentsMargins", None)):
            layout.setContentsMargins(24, 24, 24, 24)
        if callable(getattr(layout, "setSpacing", None)):
            layout.setSpacing(18)

        teams = list(teams)
        player_entries, team_stats = _load_players_with_stats()

        # Determine a reasonable upper bound on games from team totals so
        # individual players never exceed the number of games any team has
        # actually played.
        try:
            games_list = [int(v.get("g", v.get("games", 0)) or 0) for v in team_stats.values()]
            max_team_games = max(games_list) if games_list else 0
        except Exception:
            max_team_games = 0

        hist_games = _games_from_history()
        for e in player_entries:
            g = int(e.season_stats.get('g', 0) or 0)
            g = max(g, int(hist_games.get(e.player_id, 0)))
            if max_team_games:
                g = min(g, max_team_games)
            e.season_stats['g'] = g


        for team in teams:
            team.season_stats = _normalize_team_stats(team_stats.get(team.team_id))

        batters = [p for p in player_entries if not getattr(p, "is_pitcher", False)]
        pitchers = [p for p in player_entries if getattr(p, "is_pitcher", False)]

        layout.addWidget(self._build_header(teams, batters, pitchers))

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_team_tab(teams), "Teams")
        self.tabs.addTab(self._build_player_tab(batters, _BATTING_COLS, title="League Batting"), "Batters")
        self.tabs.addTab(self._build_player_tab(pitchers, _PITCHING_COLS, title="League Pitching"), "Pitchers")

    def _build_header(
        self,
        teams: List[Team],
        batters: List[BasePlayer],
        pitchers: List[BasePlayer],
    ) -> Card:
        card = Card()
        layout = ensure_layout(card)
        _call_if_exists(layout, "addWidget", section_title("League Snapshot"))

        batting_metrics = batting_summary(batters)
        pitching_metrics = pitching_summary(pitchers)
        metrics = [
            ("Teams", format_number(len(teams), decimals=0)),
            batting_metrics[0],  # AVG
            batting_metrics[1],  # OBP
            ("HR", batting_metrics[4][1]),
            pitching_metrics[0],  # ERA
            pitching_metrics[1],  # WHIP
            ("K/9", pitching_metrics[2][1]),
        ]
        _call_if_exists(layout, "addWidget", build_metric_row(metrics, columns=4))
        return card

    def _build_team_tab(self, teams: List[Team]) -> Card:
        card = Card()
        layout = ensure_layout(card)
        _call_if_exists(layout, "addWidget", section_title("Team Totals"))

        table = QTableWidget(len(teams), len(_TEAM_COLUMNS))
        self._configure_table(table, [col.upper() for col in _TEAM_COLUMNS])

        for row, team in enumerate(teams):
            stats = team.season_stats or {}
            _call_if_exists(
                table,
                "setItem",
                row,
                0,
                self._text_item(f"{team.city} {team.name}", align_left=True),
            )
            for col, key in enumerate(_TEAM_COLUMNS[1:], start=1):
                value = stats.get(key, 0)
                _call_if_exists(table, "setItem", row, col, self._stat_item(key, value))

        self._attach_table_controls(card, table, layout=layout, placeholder="Search teams or metrics", default_sort=1)
        _call_if_exists(layout, "addWidget", table)
        return card

    def _build_player_tab(
        self,
        players: List[BasePlayer],
        columns: List[str],
        *,
        title: str,
    ) -> Card:
        card = Card()
        layout = ensure_layout(card)
        _call_if_exists(layout, "addWidget", section_title(title))

        headers = ["Player"] + [col.upper() for col in columns]
        table = QTableWidget(len(players), len(headers))
        self._configure_table(table, headers)

        is_pitching = columns is _PITCHING_COLS
        for row, player in enumerate(players):
            name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
            item = self._text_item(name, align_left=True)
            try:
                item.setData(Qt.ItemDataRole.UserRole, getattr(player, 'player_id', ''))
            except Exception:
                pass
            _call_if_exists(table, "setItem", row, 0, item)
            stats = getattr(player, 'season_stats', {}) or {}
            stats = self._normalize_pitching(stats) if is_pitching else self._normalize_batting(stats)
            for col, key in enumerate(columns, start=1):
                value = stats.get(key, 0)
                _call_if_exists(table, "setItem", row, col, self._stat_item(key, value))

        try:
            sort_index = 1 if table.columnCount() > 1 else 0
        except Exception:
            sort_index = 0
        placeholder = "Search players or stats"
        self._attach_table_controls(card, table, layout=layout, placeholder=placeholder, default_sort=sort_index)
        try:
            table.itemDoubleClicked.connect(lambda item, table=table: self._open_player_from_table(item, table))
        except Exception:
            pass
        _call_if_exists(layout, "addWidget", table)
        return card

    def _open_player_from_table(self, item: QTableWidgetItem, table: QTableWidget) -> None:
        try:
            row = item.row()
            name_cell = table.item(row, 0)
            pid = name_cell.data(Qt.ItemDataRole.UserRole) if name_cell else None
            if not pid:
                return
            players = {p.player_id: p for p in load_players_from_csv(str(PLAYERS_FILE))}
            player = players.get(pid)
            if not player:
                return
            from .player_profile_dialog import PlayerProfileDialog
            dlg = PlayerProfileDialog(player, self)
            if callable(getattr(dlg, 'exec', None)):
                dlg.exec()
        except Exception:
            pass

    def _configure_table(self, table: QTableWidget, headers: List[str]) -> None:
        try:
            table.setHorizontalHeaderLabels(headers)
        except Exception:
            pass
        try:
            table.verticalHeader().setVisible(False)
        except Exception:
            pass
        try:
            table.setAlternatingRowColors(True)
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
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            if headers:
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
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

    def _attach_table_controls(
        self,
        card: Card,
        table: QTableWidget,
        *,
        layout: Any = None,
        placeholder: str,
        default_sort: int = 0,
    ) -> None:
        controls = QHBoxLayout()
        _call_if_exists(controls, "setContentsMargins", 0, 0, 0, 0)
        _call_if_exists(controls, "setSpacing", 8)
        label = QLabel("Filter:")
        search = QLineEdit()
        _call_if_exists(search, "setPlaceholderText", placeholder)
        clear_btn = QPushButton("Clear")
        sort_label = QLabel("Sort by:")
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

        _call_if_exists(controls, "addWidget", label)
        _call_if_exists(controls, "addWidget", search, 1)
        _call_if_exists(controls, "addWidget", clear_btn)
        _call_if_exists(controls, "addSpacing", 12)
        _call_if_exists(controls, "addWidget", sort_label)
        _call_if_exists(controls, "addWidget", sort_combo)
        _call_if_exists(controls, "addStretch", 1)
        parent_layout = layout or ensure_layout(card)
        _call_if_exists(parent_layout, "addLayout", controls)

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
                table.sortItems(int(column), order)
            except Exception:
                pass

        search.textChanged.connect(apply_filter)
        clear_btn.clicked.connect(lambda: search.clear())
        sort_combo.currentIndexChanged.connect(lambda _: apply_sort())

        apply_sort()

    def _text_item(self, text: str, *, align_left: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        try:
            flags = item.flags()
            editable = getattr(Qt.ItemFlag, "ItemIsEditable", None)
            if flags is not None and editable is not None:
                item.setFlags(flags & ~editable)
        except Exception:
            pass
        align = _alignment("AlignLeft" if align_left else "AlignRight", "AlignVCenter")
        if align is not None:
            try:
                item.setTextAlignment(align)
            except Exception:
                pass
        return item

    def _stat_item(self, key: str, value: Any) -> QTableWidgetItem:
        key_lower = key.lower()
        if key_lower in {"avg", "obp", "slg", "era", "whip"}:
            display = format_number(value, decimals=3)
        elif key_lower == "ip":
            display = format_ip(value)
        else:
            display = format_number(value, decimals=0)
        item = QTableWidgetItem(display)
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
        try:
            numeric = float(display)
        except ValueError:
            numeric = 0.0
        try:
            edit_role = getattr(Qt.ItemDataRole, "EditRole", None)
            if edit_role is not None:
                item.setData(edit_role, numeric)
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


