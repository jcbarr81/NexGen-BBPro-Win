from __future__ import annotations

from typing import Iterable, List, Tuple, Dict, Any, Optional

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
        QDialog,
        QGridLayout,
        QHeaderView,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QTabWidget,
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

    QDialog = QGridLayout = QTableWidget = QTableWidgetItem = QVBoxLayout = QTabWidget = _QtDummy

    class QHeaderView:  # type: ignore[too-many-ancestors]
        class ResizeMode:
            Stretch = None
            ResizeToContents = None

from models.base_player import BasePlayer
from .components import Card, section_title, ensure_layout


def _call_if_exists(obj, method: str, *args, **kwargs) -> None:
    func = getattr(obj, method, None)
    if callable(func):
        try:
            func(*args, **kwargs)
        except Exception:
            pass


def _set_style(widget: Any, style: str) -> None:
    if not hasattr(widget, "setStyleSheet"):
        return
    try:
        widget.setStyleSheet(style)
    except Exception:
        pass


from .stat_helpers import format_number, top_players
from utils.player_loader import load_players_from_csv
from utils.path_utils import get_base_dir
from utils.stats_persistence import load_stats as _load_season_stats

DATA_DIR = get_base_dir() / "data"
PLAYERS_FILE = DATA_DIR / "players.csv"

RETRO_GREEN = "#0f3b19"
RETRO_GREEN_DARK = "#0b2a12"
RETRO_GREEN_TABLE = "#164a22"
RETRO_BEIGE = "#d2ba8f"
RETRO_YELLOW = "#ffd34d"
RETRO_TEXT = "#ffffff"
RETRO_BORDER = "#3a5f3a"

_BATTING_CATEGORIES: List[Tuple[str, str, bool, bool, int]] = [
    # Batting rate stats should sort high→low (descending=True)
    ("Average", "avg", True, False, 3),
    ("Home Runs", "hr", True, False, 0),
    ("RBI", "rbi", True, False, 0),
    ("Stolen Bases", "sb", True, False, 0),
    ("On-Base %", "obp", True, False, 3),
]

_PITCHING_CATEGORIES: List[Tuple[str, str, bool, bool, int]] = [
    ("ERA", "era", False, True, 2),
    ("WHIP", "whip", False, True, 2),
    ("Wins", "w", True, True, 0),
    ("Strikeouts", "so", True, True, 0),
    ("Saves", "sv", True, True, 0),
]


class LeagueLeadersWindow(QDialog):
    def __init__(
        self,
        players: Iterable[BasePlayer],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if callable(getattr(self, "setObjectName", None)):
            self.setObjectName("LeagueLeadersWindow")
        if callable(getattr(self, "setWindowTitle", None)):
            self.setWindowTitle("League Leaders")
        if callable(getattr(self, "resize", None)):
            self.resize(960, 640)

        self._apply_global_palette()

        layout = QVBoxLayout(self)
        if callable(getattr(layout, "setContentsMargins", None)):
            layout.setContentsMargins(24, 24, 24, 24)
        if callable(getattr(layout, "setSpacing", None)):
            layout.setSpacing(18)

        # Always refresh from season_stats.json to ensure accuracy
        player_entries = self._load_players_with_stats()
        hitters = [p for p in player_entries if not getattr(p, "is_pitcher", False)]
        pitchers = [p for p in player_entries if getattr(p, "is_pitcher", False)]

        # Determine qualification thresholds from team games
        try:
            stats = _load_season_stats()
            team_stats: Dict[str, Dict[str, Any]] = stats.get("teams", {})
            games_list = [int(v.get("g", 0) or 0) for v in team_stats.values()]
            max_g = max(games_list) if games_list else 0
        except Exception:
            max_g = 0
        # MLB guidelines: 3.1 PA per game and 1.0 IP per game.
        if max_g:
            self._min_pa = max(1, int(round(max_g * 3.1)))
            self._min_ip = max(1, int(round(max_g * 1.0)))
        else:
            self._min_pa = 0
            self._min_ip = 0

        tabs = QTabWidget()
        layout.addWidget(tabs)
        tabs.addTab(
            self._build_leader_tab(
                "Batting Leaders",
                self._qualified_batters(hitters),
                _BATTING_CATEGORIES,
                fallback_players=hitters,
            ),
            "Batting",
        )
        tabs.addTab(
            self._build_leader_tab(
                "Pitching Leaders",
                self._qualified_pitchers(pitchers),
                _PITCHING_CATEGORIES,
                fallback_players=pitchers,
            ),
            "Pitching",
        )

    def _build_leader_tab(
        self,
        title: str,
        players: List[BasePlayer],
        categories: List[Tuple[str, str, bool, bool, int]],
        *,
        fallback_players: Optional[Iterable[BasePlayer]] = None,
        limit: int = 5,
    ) -> Card:
        card = Card()
        layout = ensure_layout(card)
        _call_if_exists(layout, "addWidget", section_title(title))
        grid = QGridLayout()
        if callable(getattr(grid, "setContentsMargins", None)):
            grid.setContentsMargins(0, 0, 0, 0)
        if callable(getattr(grid, "setSpacing", None)):
            grid.setSpacing(16)
        base_pool = list(players)
        fallback_pool = list(fallback_players) if fallback_players is not None else list(base_pool)
        for idx, (label, key, descending, pitcher_only, decimals) in enumerate(categories):
            category_players = base_pool
            if key == "sv" and pitcher_only:
                # Saves should not be limited by the innings qualifier; consider every pitcher.
                category_players = fallback_pool
            leaders = self._leaders_for_category(
                category_players,
                fallback_pool,
                key,
                pitcher_only=pitcher_only,
                descending=descending,
                limit=limit,
            )
            table = QTableWidget(len(leaders), 3)
            try:
                table.setHorizontalHeaderLabels(["#", "Player", label])
                table.verticalHeader().setVisible(False)
                table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
                header = table.horizontalHeader()
                header.setStretchLastSection(True)
                header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
                header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            except Exception:
                pass
            try:
                table.setAlternatingRowColors(False)
            except Exception:
                pass
            try:
                table.setShowGrid(True)
            except Exception:
                pass
            for row, (player, value) in enumerate(leaders):
                rank_item = QTableWidgetItem(str(row + 1))
                try:
                    rank_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                except Exception:
                    pass
                try:
                    table.setItem(row, 0, rank_item)
                except Exception:
                    pass
                name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip()
                item = QTableWidgetItem(name)
                try:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                except Exception:
                    pass
                try:
                    item.setData(Qt.ItemDataRole.UserRole, getattr(player, 'player_id', ''))
                except Exception:
                    pass
                try:
                    table.setItem(row, 1, item)
                    value_item = QTableWidgetItem(format_number(value, decimals=decimals))
                    try:
                        value_item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    except Exception:
                        pass
                    table.setItem(row, 2, value_item)
                except Exception:
                    pass
            try:
                table.itemDoubleClicked.connect(lambda item, table=table: self._open_player_from_table(item, table))
            except Exception:
                pass
            self._style_table(table)
            _call_if_exists(grid, "addWidget", table, idx // 2, idx % 2)
        _call_if_exists(layout, "addLayout", grid)
        return card

    def _apply_global_palette(self) -> None:
        if not hasattr(self, "setStyleSheet"):
            return
        _set_style(
            self,
            f"""
            QDialog#LeagueLeadersWindow {{
                background:{RETRO_GREEN};
            }}
            QFrame#Card {{
                background:{RETRO_GREEN_DARK};
                border: 1px solid {RETRO_BORDER};
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
            QLabel#SectionTitle {{
                color:{RETRO_YELLOW};
                font-weight:700;
                letter-spacing:0.6px;
            }}
            """
        )

    def _style_table(self, table: QTableWidget) -> None:
        _set_style(
            table,
            f"QTableWidget {{ background:{RETRO_GREEN_TABLE}; color:{RETRO_TEXT};"
            f" gridline-color:{RETRO_BORDER}; selection-background-color:#245b2b;"
            f" selection-color:{RETRO_TEXT}; font: 12px 'Segoe UI'; }}"
            f"QHeaderView::section {{ background:{RETRO_GREEN}; color:{RETRO_TEXT};"
            f" border: 1px solid {RETRO_BORDER}; font-weight:600; }}"
            f"QScrollBar:vertical {{ background:{RETRO_GREEN_DARK}; width: 12px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background:{RETRO_BEIGE}; min-height: 24px; }}"
        )

    def _leaders_for_category(
        self,
        players: Iterable[BasePlayer],
        fallback_players: Iterable[BasePlayer],
        key: str,
        *,
        pitcher_only: bool,
        descending: bool,
        limit: int,
    ) -> List[Tuple[BasePlayer, Any]]:
        apply_qualifier = key != "sv"

        def collect_leaders(pool: Iterable[BasePlayer]) -> List[Tuple[BasePlayer, Any]]:
            pool_list = list(pool)
            if not pool_list:
                return []
            candidates = top_players(
                pool_list,
                key,
                pitcher_only=pitcher_only,
                descending=descending,
                limit=len(pool_list),
            )
            return [
                (player, value)
                for player, value in candidates
                if self._has_stat_sample(
                    player,
                    key,
                    pitcher_only=pitcher_only,
                    apply_qualifier=apply_qualifier,
                )
            ]

        leaders = collect_leaders(players)
        if len(leaders) >= limit:
            return leaders[:limit]
        fallback_list = list(fallback_players)
        if not fallback_list:
            return leaders
        existing = {
            getattr(player, "player_id", None) or id(player) for player, _ in leaders
        }
        for candidate, value in collect_leaders(fallback_list):
            identifier = getattr(candidate, "player_id", None) or id(candidate)
            if identifier in existing:
                continue
            leaders.append((candidate, value))
            existing.add(identifier)
            if len(leaders) >= limit:
                break
        leaders.sort(key=lambda item: self._stat_sort_key(item[1]), reverse=descending)
        return leaders[:limit]

    @staticmethod
    def _stat_sort_key(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _has_stat_sample(
        self,
        player: BasePlayer,
        key: str,
        *,
        pitcher_only: bool,
        apply_qualifier: bool,
    ) -> bool:
        stats = getattr(player, "season_stats", {}) or {}
        min_ip = self.__dict__.get("_min_ip", 0)
        min_pa = self.__dict__.get("_min_pa", 0)
        if pitcher_only and apply_qualifier and min_ip:
            if self._pitcher_ip(stats) < min_ip:
                return False
        if not pitcher_only and apply_qualifier and min_pa:
            if self._batter_pa(stats) < min_pa:
                return False
        if key in {"era", "whip"}:
            ip = stats.get("ip")
            if ip is None:
                outs = stats.get("outs")
                try:
                    ip = (outs or 0) / 3.0
                except Exception:
                    ip = 0.0
            try:
                return float(ip or 0) > 0.0
            except Exception:
                return False
        if key == "avg":
            try:
                return int(stats.get("ab", 0) or 0) > 0
            except Exception:
                return False
        if key == "obp":
            try:
                ab = float(stats.get("ab", 0) or 0)
                bb = float(stats.get("bb", 0) or 0)
                hbp = float(stats.get("hbp", 0) or 0)
                sf = float(stats.get("sf", 0) or 0)
            except Exception:
                return False
            return (ab + bb + hbp + sf) > 0
        return True

    # Load players merged with season stats so leaders reflect current file
    def _load_players_with_stats(self) -> List[BasePlayer]:
        try:
            stats = _load_season_stats()
        except Exception:
            stats = {"players": {}}
        players = {p.player_id: p for p in load_players_from_csv(str(PLAYERS_FILE))}
        for pid, season in stats.get("players", {}).items():
            if pid in players:
                players[pid].season_stats = season
        return list(players.values())

    # ------------------------------------------------------------------
    # Qualification helpers
    def _qualified_batters(self, players: List[BasePlayer]) -> List[BasePlayer]:
        min_pa = self.__dict__.get("_min_pa", 0)
        qualified: List[BasePlayer] = []
        for p in players:
            stats = getattr(p, "season_stats", {}) or {}
            if self._batter_pa(stats) >= min_pa:
                qualified.append(p)
        # Fall back to all hitters if no one qualifies
        return qualified or players

    def _qualified_pitchers(self, players: List[BasePlayer]) -> List[BasePlayer]:
        min_ip = self.__dict__.get("_min_ip", 0)
        qualified: List[BasePlayer] = []
        for p in players:
            stats = getattr(p, "season_stats", {}) or {}
            if self._pitcher_ip(stats) >= min_ip:
                qualified.append(p)
        # Fall back to all pitchers if no one qualifies
        return qualified or players

    @staticmethod
    def _batter_pa(stats: Dict[str, Any]) -> int:
        pa = stats.get("pa")
        if pa is None:
            ab = stats.get("ab", 0) or 0
            bb = stats.get("bb", 0) or 0
            hbp = stats.get("hbp", 0) or 0
            sf = stats.get("sf", 0) or 0
            ci = stats.get("ci", 0) or 0
            pa = ab + bb + hbp + sf + ci
        try:
            return int(pa or 0)
        except Exception:
            return 0

    @staticmethod
    def _pitcher_ip(stats: Dict[str, Any]) -> float:
        ip = stats.get("ip")
        if ip is None:
            outs = stats.get("outs")
            try:
                ip = (outs or 0) / 3.0
            except Exception:
                ip = 0.0
        try:
            return float(ip or 0)
        except Exception:
            return 0.0

    def _open_player_from_table(self, item: QTableWidgetItem, table: QTableWidget) -> None:
        try:
            row = item.row()
            pid = table.item(row, 1).data(Qt.ItemDataRole.UserRole) if table.item(row,1) else None
            if not pid:
                return
            from pathlib import Path
            from utils.path_utils import get_base_dir
            players = {p.player_id: p for p in load_players_from_csv(str(get_base_dir() / 'data' / 'players.csv'))}
            player = players.get(pid)
            if not player:
                return
            from .player_profile_dialog import PlayerProfileDialog
            dlg = PlayerProfileDialog(player, self)
            if callable(getattr(dlg, 'exec', None)):
                dlg.exec()
        except Exception:
            pass


