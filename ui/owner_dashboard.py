from __future__ import annotations

import csv
import importlib
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional
from types import SimpleNamespace

import bcrypt

try:
    from PyQt6.QtCore import Qt, QSize, QTimer
except ImportError:  # pragma: no cover - test stubs
    Qt = SimpleNamespace(
        AlignmentFlag=SimpleNamespace(
            AlignCenter=0x0004,
            AlignRight=0x0002,
            AlignVCenter=0x0080,
        ),
        TransformationMode=SimpleNamespace(SmoothTransformation=None),
        ToolButtonStyle=SimpleNamespace(ToolButtonTextBesideIcon=None),
        WindowState=SimpleNamespace(WindowMaximized=None),
        ItemDataRole=SimpleNamespace(
            UserRole=0,
            DisplayRole=1,
            EditRole=2,
        ),
        ItemFlag=SimpleNamespace(ItemIsEditable=0x0002),
    )

    class QSize:  # type: ignore[too-many-ancestors]
        def __init__(self, width: int = 0, height: int = 0) -> None:
            self._width = width
            self._height = height

        def width(self) -> int:
            return self._width

        def height(self) -> int:
            return self._height
    QTimer = None
else:  # pragma: no branch - normalize stubs
    if not hasattr(Qt, "AlignmentFlag"):
        Qt.AlignmentFlag = SimpleNamespace(  # type: ignore[attr-defined]
            AlignCenter=None,
            AlignRight=None,
            AlignVCenter=None,
        )
    if not hasattr(Qt, "TransformationMode"):
        Qt.TransformationMode = SimpleNamespace(SmoothTransformation=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "ToolButtonStyle"):
        Qt.ToolButtonStyle = SimpleNamespace(ToolButtonTextBesideIcon=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "WindowState"):
        Qt.WindowState = SimpleNamespace(WindowMaximized=None)  # type: ignore[attr-defined]

try:
    from PyQt6.QtGui import QAction, QFont, QPixmap, QIcon
except ImportError:  # pragma: no cover - support test stubs
    from PyQt6.QtGui import QFont, QPixmap
    from PyQt6.QtWidgets import QAction
    QIcon = None  # type: ignore[assignment]
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QInputDialog,
    QMessageBox,
    QLineEdit,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .components import NavButton
from .theme import _toggle_theme
from .roster_page import RosterPage
from .transactions_page import TransactionsPage
from .schedule_page import SchedulePage
from .team_page import TeamPage
from .owner_home_page import OwnerHomePage
from .lineup_editor import LineupEditor
from .pitching_editor import PitchingEditor
from .position_players_dialog import PositionPlayersDialog
from .pitchers_dialog import PitchersDialog
from .reassign_players_dialog import ReassignPlayersDialog
from .transactions_window import TransactionsWindow
from .trade_dialog import TradeDialog
from .standings_window import StandingsWindow
from .schedule_window import ScheduleWindow
from .team_schedule_window import TeamScheduleWindow, SCHEDULE_FILE
from .team_stats_window import TeamStatsWindow
from .league_stats_window import LeagueStatsWindow
from .league_leaders_window import LeagueLeadersWindow
from .league_history_window import LeagueHistoryWindow
from .news_window import NewsWindow
from .season_progress_window import SeasonProgressWindow
from .draft_console import DraftConsole
from .player_browser_dialog import PlayerBrowserDialog
from .injury_center_window import InjuryCenterWindow
from .depth_chart_dialog import DepthChartDialog
from .tutorial_dialog import TutorialDialog, TutorialStep
from .training_focus_dialog import TrainingFocusDialog
from .ui_template import _load_baseball_pixmap, _load_nav_icon
from utils.roster_loader import load_roster
from utils.player_loader import load_players_from_csv
from utils.free_agent_finder import find_free_agents
from utils.pitcher_role import get_role
from utils.rating_display import rating_display_text
from utils.team_loader import load_teams, save_team_settings
from utils.path_utils import get_base_dir
from utils.sim_date import get_current_sim_date
from ui.analytics import gather_owner_quick_metrics
from ui.dashboard_core import DashboardContext, NavigationController, PageRegistry
from ui.window_utils import show_on_top
from ui.version_badge import enable_version_badge
from ui.sim_date_bus import sim_date_bus


class OwnerDashboard(QMainWindow):
    """Owner-facing dashboard with sidebar navigation."""

    def __init__(self, team_id: str):
        super().__init__()
        enable_version_badge(self)
        self.team_id = team_id
        self.players: Dict[str, object] = {
            p.player_id: p for p in load_players_from_csv("data/players.csv")
        }
        self.roster = load_roster(team_id)
        teams = load_teams()
        self.team = next((t for t in teams if t.team_id == team_id), None)

        base_path = get_base_dir()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._background_futures: set[Future[Any]] = set()
        self._cleanup_callbacks: list[Callable[[], None]] = []
        self._context = DashboardContext(
            base_path=base_path,
            run_async=self._submit_background,
            show_toast=self._show_toast,
            register_cleanup=self._register_cleanup,
        )
        self.context = self._context
        self._latest_metrics: Dict[str, Any] = {}
        self._registry = PageRegistry()
        self._nav_controller = NavigationController(self._registry)
        self._nav_controller.add_listener(self._on_nav_changed_with_tutorial)

        self.setWindowTitle(f"Owner Dashboard - {team_id}")
        self.resize(1100, 720)
        self._admin_window = None
        self._season_progress_window: Optional[SeasonProgressWindow] = None

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 12, 10, 12)
        side.setSpacing(6)

        logo_path = base_path / "logo" / "teams" / f"{team_id.lower()}.png"
        if logo_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(logo_path)).scaledToWidth(
                96, Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            side.addWidget(logo_label)

        brand_icon = QLabel()
        brand_icon_size = 40
        baseball = _load_baseball_pixmap(brand_icon_size)
        if not baseball.isNull():
            brand_icon.setPixmap(baseball)
        brand_icon.setFixedSize(brand_icon_size, brand_icon_size)

        brand_text = QLabel(f"{team_id} Owner")
        brand_text.setStyleSheet("font-weight:900; font-size:16px;")

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 2, 0)
        brand_row.setSpacing(8)
        brand_row.addWidget(brand_icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        brand_row.addWidget(brand_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        brand_row.addStretch()

        brand_container = QWidget()
        brand_container.setLayout(brand_row)
        side.addWidget(brand_container)

        self.btn_home = NavButton("  Dashboard")
        self.btn_roster = NavButton("  Roster")
        self.btn_team = NavButton("  Team")
        self.btn_transactions = NavButton("  Moves & Trades")
        self.btn_league = NavButton("  League Hub")

        for b in (self.btn_home, self.btn_roster, self.btn_team, self.btn_transactions, self.btn_league):
            side.addWidget(b)

        self.nav_buttons = {
            "home": self.btn_home,
            "roster": self.btn_roster,
            "team": self.btn_team,
            "transactions": self.btn_transactions,
            "league": self.btn_league,
        }

        icon_size = QSize(24, 24)
        icon_sources = {
            "home": "nav_dashboard.svg",
            "roster": "nav_roster.svg",
            "team": "nav_team.svg",
            "transactions": "nav_transactions.svg",
            "league": "nav_league.svg",
        }
        tooltips = {
            "home": "Overview and quick actions",
            "roster": "Roster management and player tools",
            "team": "Team schedule and stats",
            "transactions": "Transactions, trades, and movement",
            "league": "League schedule, standings, and stats",
        }
        for key, button in self.nav_buttons.items():
            icon_name = icon_sources.get(key)
            if not icon_name:
                continue
            icon = _load_nav_icon(icon_name, icon_size.width())
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            tip = tooltips.get(key)
            if tip:
                button.setToolTip(tip)

        side.addStretch()
        self.btn_settings = NavButton("  Toggle Theme")
        self.btn_settings.clicked.connect(lambda: _toggle_theme(self.statusBar()))
        side.addWidget(self.btn_settings)

        # Header
        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.setSpacing(12)

        title = QLabel("Team Dashboard")
        title.setObjectName("Title")
        title.setFont(QFont(title.font().family(), 11, weight=QFont.Weight.ExtraBold))
        h.addWidget(title)
        h.addStretch()
        self.scoreboard = QLabel("Ready")
        self.scoreboard.setObjectName("Scoreboard")
        h.addWidget(self.scoreboard, alignment=Qt.AlignmentFlag.AlignRight)

        # Stacked pages
        self.stack = QStackedWidget()
        self.pages: Dict[str, QWidget] = {}
        self._register_pages()

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(header)
        rv.addWidget(self.stack)

        root.addWidget(sidebar)
        root.addWidget(right)
        root.setStretchFactor(right, 1)
        sidebar.setFixedWidth(210)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        try:
            self.setWindowState(Qt.WindowState.WindowMaximized)
        except Exception:
            pass

        self._build_menu()
        self._sim_date_bus = sim_date_bus()
        try:
            self._sim_date_bus.dateChanged.connect(self._on_sim_date_changed)
        except Exception:
            pass

        # Navigation signals
        self.btn_home.clicked.connect(lambda: self._go("home"))
        self.btn_roster.clicked.connect(lambda: self._go("roster"))
        self.btn_team.clicked.connect(lambda: self._go("team"))
        self.btn_transactions.clicked.connect(lambda: self._go("transactions"))
        self.btn_league.clicked.connect(lambda: self._go("league"))
        self._go("home")

        # Expose actions for tests
        self.schedule_action = QAction(self)
        self.schedule_action.triggered.connect(self.open_schedule_window)
        self.team_schedule_action = QAction(self)
        self.team_schedule_action.triggered.connect(self.open_team_schedule_window)

        self._tutorial_keys = {
            "depth_chart": f"depth_chart_tutorial_done_{team_id}",
            "injury_center": f"injury_center_tutorial_{team_id}",
            "roster_moves": f"roster_moves_tutorial_{team_id}",
            "pitching": f"pitching_staff_tutorial_{team_id}",
            "lineup": f"lineup_strategy_tutorial_{team_id}",
            "overview": f"dashboard_overview_tutorial_{team_id}",
            "training_camp": f"training_camp_tutorial_{team_id}",
            "admin": "admin_tools_tutorial",
        }
        self._tutorial_flags = self._load_tutorial_flags()
        self._migrate_tutorial_flags()
        self._tutorial_dialog_open = False
        self._build_tutorial_menu()
        if QTimer:
            QTimer.singleShot(400, self._maybe_auto_show_tutorials)
        else:
            self._maybe_auto_show_tutorials()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        admin_action = QAction("Open Admin Dashboard", self)
        admin_action.triggered.connect(self._prompt_admin_dashboard)
        file_menu.addAction(admin_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        theme_action = QAction("Toggle Dark Mode", self)
        theme_action.triggered.connect(lambda: _toggle_theme(self.statusBar()))
        view_menu.addAction(theme_action)
        news_action = QAction("News Feed", self)
        news_action.triggered.connect(self.open_news_window)
        view_menu.addAction(news_action)
        try:
            settings_action = QAction("Team Settings", self)
            settings_action.triggered.connect(self.open_team_settings_dialog)
            view_menu.addAction(settings_action)
        except Exception:
            pass

        simulate_menu = self.menuBar().addMenu("&Simulate")
        self.season_progress_action = QAction("Season Progress...", self)
        self.season_progress_action.setStatusTip("Open season progress controls")
        self.season_progress_action.triggered.connect(self.open_season_progress_window)
        simulate_menu.addAction(self.season_progress_action)

    def _build_tutorial_menu(self) -> None:
        tutorials_menu = self.menuBar().addMenu("&Tutorials")

        depth_action = QAction("Depth Chart Basics", self)
        depth_action.triggered.connect(lambda: self.show_depth_chart_tutorial(force=True))
        tutorials_menu.addAction(depth_action)

        injury_action = QAction("Injury Center Guide", self)
        injury_action.triggered.connect(lambda: self.show_injury_center_tutorial(force=True))
        tutorials_menu.addAction(injury_action)

        roster_action = QAction("Roster Moves Guide", self)
        roster_action.triggered.connect(lambda: self.show_roster_moves_tutorial(force=True))
        tutorials_menu.addAction(roster_action)

        pitching_action = QAction("Pitching Staff Tutorial", self)
        pitching_action.triggered.connect(lambda: self.show_pitching_staff_tutorial(force=True))
        tutorials_menu.addAction(pitching_action)

        lineup_action = QAction("Lineup & Strategy Tutorial", self)
        lineup_action.triggered.connect(lambda: self.show_lineup_strategy_tutorial(force=True))
        tutorials_menu.addAction(lineup_action)

        overview_action = QAction("Dashboard Overview", self)
        overview_action.triggered.connect(lambda: self.show_dashboard_overview_tutorial(force=True))
        tutorials_menu.addAction(overview_action)

        training_action = QAction("Training Camp & Development", self)
        training_action.triggered.connect(lambda: self.show_training_camp_tutorial(force=True))
        tutorials_menu.addAction(training_action)

        admin_action = QAction("Admin Tools Overview", self)
        admin_action.triggered.connect(lambda: self.show_admin_tools_tutorial(force=True))
        tutorials_menu.addAction(admin_action)

    def _load_tutorial_flags(self) -> dict[str, bool]:
        try:
            import json
            path = get_base_dir() / "config" / "tutorial_flags.json"
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): bool(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save_tutorial_flags(self) -> None:
        try:
            import json
            path = get_base_dir() / "config"
            path.mkdir(parents=True, exist_ok=True)
            dest = path / "tutorial_flags.json"
            dest.write_text(json.dumps(self._tutorial_flags, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _migrate_tutorial_flags(self) -> None:
        legacy = self._tutorial_flags.get("injury_center_tutorial")
        if legacy is not None:
            self._tutorial_flags.setdefault(self._tutorial_keys["injury_center"], bool(legacy))

    def _run_tutorial(self, key: str, title: str, steps: list[TutorialStep], *, force: bool = False) -> None:
        if not force and self._tutorial_flags.get(key):
            return
        if self._tutorial_dialog_open:
            return
        self._tutorial_dialog_open = True
        try:
            dlg = TutorialDialog(title=title, steps=steps, parent=self)
            dlg.exec()
        finally:
            self._tutorial_dialog_open = False
            if not force:
                self._tutorial_flags[key] = True
                self._save_tutorial_flags()

    def show_depth_chart_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Why Depth Charts?",
                "<p>The depth chart lets you choose who replaces a starter when injuries or promotions occur. "
                "Set three players for each position to keep simulations flowing without pauses.</p>",
            ),
            TutorialStep(
                "Drag & Drop Ordering",
                "<p>Use the <b>Depth Chart Priorities</b> tiles on the Roster page. Drag players to reorder them. "
                "Top entries are first in line when a roster move is needed.</p>",
            ),
            TutorialStep(
                "Saving Changes",
                "<p>After rearranging, click <b>Save Depth Chart</b>. This updates the fallback logic used by lineup "
                "autofill and injury recovery so your choices stick.</p>",
            ),
            TutorialStep(
                "Full Editor",
                "<p>Need to add or remove players from the chart? Open the full <b>Depth Chart</b> dialog from the "
                "Roster quick actions. That dialog lets you pick anyone from ACT/AAA/Low for each slot.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["depth_chart"], "Depth Chart Basics", steps, force=force)

    def maybe_show_depth_chart_tutorial(self) -> None:
        self.show_depth_chart_tutorial()

    def show_injury_center_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Accessing the Center",
                "<p>Open <b>Injury Center</b> from the roster quick actions or the Tutorials menu."
                " It filters to your team automatically and lists every injured player.</p>",
            ),
            TutorialStep(
                "Review & Sort",
                "<p>Sort the columns to check return dates and list assignments."
                " The fields underneath let you revise the description, target return date, list tier, and"
                " preferred destination for the selected player. Roster counts and the legend update as you click.</p>",
            ),
            TutorialStep(
                "Managing Injuries",
                "<p>Once a player is highlighted, use the action row:</p>"
                "<ul>"
                "<li><b>Place on DL</b> moves the player to the 15-day list and opens a roster spot by"
                " promoting a depth chart replacement.</li>"
                "<li><b>Place on IR</b> stashes long-term injuries on injured reserve without a fixed return window,"
                " freeing the active roster until you manually bring them back.</li>"
                "<li><b>Recover to Destination</b> clears the injury and returns the player to the level selected in"
                " <b>Destination</b>, enforcing DL minimums unless they have served the required days.</li>"
                "<li><b>Promote Best Replacement</b> pulls the next healthy option from your depth chart to keep the"
                " active roster full.</li>"
                "</ul>",
            ),
            TutorialStep(
                "Tracking Progress",
                "<p>Watch the roster counts footer and the return date column to know when someone is coming back."
                " A player must satisfy the DL minimum before <b>Recover to Destination</b> will clear them. Each"
                " move is also written to the news feed so owners can audit what happened and when.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["injury_center"], "Injury Center Guide", steps, force=force)

    def show_roster_moves_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Reassigning Players",
                "<p>Use <b>Reassign Players</b> on the Roster page to promote/demote between ACT, AAA, and Low."
                " The dialog enforces roster limits and highlights when a level is full.</p>",
            ),
            TutorialStep(
                "Replacing Injured Players",
                "<p>After moving someone to the DL/IR, promote a replacement from AAA or Low. "
                "The depth chart priority helps determine who should move up.</p>",
            ),
            TutorialStep(
                "Tracking Capacity",
                "<p>Watch the roster counts at the bottom of the Injury Center and Reassign dialogs."
                " Staying within 25/15/10 keeps simulations running without interruptions.</p>",
            ),
            TutorialStep(
                "Saving & Notifications",
                "<p>Every move writes to the news feed so you can audit changes later. "
                "Remember to save rosters or lineups after a major reshuffle.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["roster_moves"], "Roster Moves Guide", steps, force=force)

    def show_pitching_staff_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Rotation Order",
                "<p>Open <b>Pitching Staff</b> to drag your rotation slots. "
                "The order drives which starter the simulator schedules next.</p>",
            ),
            TutorialStep(
                "Bullpen Roles",
                "<p>Assign CL, SU, MR, and LR roles so the AI knows who to call upon."
                " Role icons update instantly and help balance workload.</p>",
            ),
            TutorialStep(
                "Rest & Fatigue",
                "<p>Hover over a pitcher to see stamina and rest days."
                " Avoid using arms that show red fatigue indicators to prevent injuries.</p>",
            ),
            TutorialStep(
                "Injury Returns",
                "<p>Pitchers marked ready in the Injury Center can be activated and slotted"
                " back into the bullpen or rotation.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["pitching"], "Pitching Staff Tutorial", steps, force=force)

    def show_lineup_strategy_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Vs LHP/RHP Lineups",
                "<p>The <b>Lineups</b> editor stores separate batting orders for left- and right-handed starters."
                " Edit both tabs so the simulator always has coverage.</p>",
            ),
            TutorialStep(
                "Positions & DH",
                "<p>Assign positions directly in the grid. The DH slot can host any hitter;"
                " make sure someone covers every defensive spot.</p>",
            ),
            TutorialStep(
                "Auto-Fill vs Manual",
                "<p>Use Auto-Fill to generate a baseline lineup from ratings, then fine-tune manually."
                " Auto-Fill respects your depth chart priorities when possible.</p>",
            ),
            TutorialStep(
                "Saving Changes",
                "<p>Click <b>Save</b> before closing the editor. Saved CSVs feed the simulation engine immediately.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["lineup"], "Lineup & Strategy Tutorial", steps, force=force)

    def show_dashboard_overview_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Scoreboard Strip",
                "<p>The top scoreboard summarizes record, run differential, streak, upcoming opponent, and injuries."
                " It updates whenever the sim date advances.</p>",
            ),
            TutorialStep(
                "Quick Actions",
                "<p>Use the Quick Actions card on the Dashboard page to jump to common tasks like lineups, pitching staff,"
                " injuries, and stats.</p>",
            ),
            TutorialStep(
                "Performers & Standings",
                "<p>The dashboard highlights hot/cold performers from recent games and a snapshot of your division standings."
                " Toggle \"View all\" to expand the news feed preview.</p>",
            ),
            TutorialStep(
                "Navigation Tips",
                "<p>The sidebar buttons switch between Dashboard, Roster, Team schedule, Moves & Trades, and League Hub."
                " The Tutorials menu is always available up top.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["overview"], "Owner Dashboard Overview", steps, force=force)

    def show_training_camp_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "When to Run Camp",
                "<p>Open <b>Admin Tools → Season Progress</b> once free agency prep is complete."
                " The <b>Run Training Camp</b> button unlocks after you finish required preseason tasks.</p>",
            ),
            TutorialStep(
                "Customize Focus Budgets",
                "<p>Before running camp you can tailor hitter and pitcher allocations."
                " Use the <b>Training Focus</b> button on the Roster page or the <b>Training Focus…</b> button in"
                " the Season Progress window to split training time across tracks. League defaults are used when"
                " a team hasn't set its own mix.</p>",
            ),
            TutorialStep(
                "Development Highlights",
                "<p>After camp runs, check the progress window for the highlight reel."
                " It calls out the biggest rating gains so you can brief your front office.</p>",
            ),
            TutorialStep(
                "Detailed Reports",
                "<p>Each camp writes a JSON report under <code>data/training_reports</code> by season."
                " These files record the focus track, notes, and exact rating changes for every player.</p>",
            ),
            TutorialStep(
                "Profile History",
                "<p>Player profile dialogs include a <b>Recent Training Focus</b> card showing the last few camps."
                " Use it during trade talks or to plan development meetings.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["training_camp"], "Training Camp & Development", steps, force=force)

    def _open_training_focus_dialog(self) -> None:
        team_label = getattr(self.team, "name", self.team_id)
        try:
            dialog = TrainingFocusDialog(
                parent=self,
                team_id=self.team_id,
                team_name=team_label,
                mode="team",
            )
        except Exception:
            return
        result = dialog.exec()
        try:
            accepted = bool(result)
        except Exception:
            accepted = False
        if not accepted:
            return
        message = dialog.result_message or "Training focus updated."
        try:
            status = self.statusBar()
            if status is not None:
                status.showMessage(message, 5000)
        except Exception:
            pass

    def show_admin_tools_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Admin Dashboard",
                "<p>From the File menu choose <b>Open Admin Dashboard</b>. "
                "Only admins with credentials should use this area.</p>",
            ),
            TutorialStep(
                "Season Operations",
                "<p>Generate schedules, run training camp, and progress playoffs from the admin tools."
                " Each action logs to the news feed and should be run once per phase.</p>",
            ),
            TutorialStep(
                "Training Focus",
                "<p>Use the <b>Training Focus…</b> button on Season Progress to set league-wide hitter and pitcher"
                " allocations. Commissioners can balance defaults here before teams override them.</p>",
            ),
            TutorialStep(
                "Safety & Backups",
                "<p>Use the backup utilities before performing destructive tasks like resetting seasons."
                " Keep exports if you plan to share league files.</p>",
            ),
            TutorialStep(
                "Communication",
                "<p>Notify owners before major admin actions. Tutorials are available so commissioners can explain changes "
                "using a consistent script.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["admin"], "Admin Tools Overview", steps, force=force)

    def _maybe_auto_show_tutorials(self) -> None:
        self.show_dashboard_overview_tutorial()

    def _maybe_show_roster_tutorial(self, key: Optional[str]) -> None:
        if key == "roster":
            self.maybe_show_depth_chart_tutorial()

    def _prompt_admin_dashboard(self) -> None:
        password, accepted = QInputDialog.getText(
            self,
            "Admin Access",
            "Enter admin password:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return

        password = password.strip()
        if not password:
            QMessageBox.warning(
                self,
                "Admin Access",
                "Password is required to open the admin dashboard.",
            )
            return

        try:
            if not self._validate_admin_password(password):
                QMessageBox.warning(self, "Admin Access", "Incorrect admin password.")
                return
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Admin Access",
                "User accounts file not found. Contact your administrator.",
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Admin Access",
                f"Unable to verify password: {exc}",
            )
            return

        self._open_admin_dashboard()

    def _validate_admin_password(self, password: str) -> bool:
        user_file = get_base_dir() / "data" / "users.txt"
        if not user_file.exists():
            raise FileNotFoundError(user_file)

        try:
            with user_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    parts = line.strip().split(",")
                    if len(parts) != 4:
                        continue
                    _, stored_password, role, _ = parts
                    if role != "admin":
                        continue
                    try:
                        if bcrypt.checkpw(
                            password.encode("utf-8"), stored_password.encode("utf-8")
                        ):
                            return True
                    except ValueError:
                        pass
                    if stored_password == password:
                        return True
        except FileNotFoundError:
            raise

        return False

    def _open_admin_dashboard(self) -> None:
        try:
            module = importlib.import_module("ui.admin_dashboard")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Admin Access",
                f"Unable to load admin dashboard module: {exc}",
            )
            return

        dash_cls = getattr(module, "AdminDashboard", None) or getattr(
            module, "MainWindow", None
        )
        if dash_cls is None:
            QMessageBox.critical(
                self,
                "Admin Access",
                "Admin dashboard is unavailable.",
            )
            return

        try:
            self._admin_window = dash_cls()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Admin Access",
                f"Unable to open admin dashboard: {exc}",
            )
            return

        show_on_top(self._admin_window)

    def _register_pages(self) -> None:
        factories: Dict[str, Callable[[DashboardContext], QWidget]] = {
            "home": lambda ctx: OwnerHomePage(self),
            "roster": lambda ctx: RosterPage(self),
            "team": lambda ctx: TeamPage(self),
            "transactions": lambda ctx: TransactionsPage(self),
            "league": lambda ctx: SchedulePage(self),
        }
        for key, factory in factories.items():
            self._registry.register(key, factory)
            widget = self._registry.build(key, self._context)
            self.pages[key] = widget
            self.stack.addWidget(widget)


    def _submit_background(self, worker: Callable[[], Any]) -> Future[Any]:
        future = self._executor.submit(worker)
        self._background_futures.add(future)

        def _cleanup(fut: Future[Any]) -> None:
            self._background_futures.discard(fut)

        future.add_done_callback(_cleanup)
        return future

    def _register_cleanup(self, callback: Callable[[], None]) -> None:
        if callback not in self._cleanup_callbacks:
            self._cleanup_callbacks.append(callback)

    def _show_toast(self, kind: str, message: str) -> None:
        prefixes = {
            "success": "SUCCESS",
            "error": "ERROR",
            "warning": "WARN",
            "info": "INFO",
        }
        prefix = prefixes.get(kind, kind.upper())
        try:
            self.statusBar().showMessage(f"[{prefix}] {message}", 5000)
        except Exception:
            pass


    def _go(self, key: str) -> None:
        if key not in self.pages:
            return
        try:
            self._nav_controller.set_current(key)
        except KeyError:
            return

    def _on_nav_changed_with_tutorial(self, key: Optional[str]) -> None:
        self._maybe_show_roster_tutorial(key)
        self._on_nav_changed(key)

    def _on_nav_changed(self, key: Optional[str]) -> None:
        for name, btn in self.nav_buttons.items():
            btn.setChecked(name == key)
        if key is None:
            return
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self._update_status_bar(key)
        refresh = getattr(page, 'refresh', None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass
        try:
            self._update_header_context()
        except Exception:
            pass

    def _update_status_bar(self, key: Optional[str] = None) -> None:
        """Render the status bar message with the current sim date."""

        if key is None:
            key = self._nav_controller.current_key or "home"
        label = key.capitalize() if isinstance(key, str) else "Home"
        date_str = get_current_sim_date()
        suffix = f" | Date: {date_str}" if date_str else ""
        try:
            self.statusBar().showMessage(f"Ready - {label}{suffix}")
        except Exception:
            pass

    def _on_sim_date_changed(self, _value: object) -> None:
        """Update status bar and metrics when the sim date advances."""

        try:
            self._update_status_bar()
        except Exception:
            pass
        try:
            self._update_header_context()
        except Exception:
            pass

    def open_lineup_editor(self) -> None:
        show_on_top(LineupEditor(self.team_id))

    def open_depth_chart_dialog(self) -> None:
        show_on_top(DepthChartDialog(self))

    def open_pitching_editor(self) -> None:
        show_on_top(PitchingEditor(self.team_id))

    def open_training_focus_dialog(self) -> None:
        self._open_training_focus_dialog()

    def open_position_players_dialog(self) -> None:
        show_on_top(PositionPlayersDialog(self.players, self.roster))

    def open_pitchers_dialog(self) -> None:
        show_on_top(PitchersDialog(self.players, self.roster))

    def open_player_browser_dialog(self) -> None:
        show_on_top(PlayerBrowserDialog(self.players, self.roster, self))

    def open_player_profile(self, player_id: str) -> None:
        player = None
        try:
            if isinstance(self.players, Mapping):
                player = self.players.get(player_id)
            else:
                player = getattr(self.players, "get", lambda _pid: None)(player_id)
        except Exception:
            player = None
        if player is None:
            return
        try:
            from ui.player_profile_dialog import PlayerProfileDialog

            show_on_top(PlayerProfileDialog(player, self))
        except Exception:
            pass

    def open_reassign_players_dialog(self) -> None:
        show_on_top(ReassignPlayersDialog(self.players, self.roster, self))

    def open_transactions_page(self) -> None:
        show_on_top(TransactionsWindow(self.team_id))

    def open_trade_dialog(self) -> None:
        show_on_top(TradeDialog(self.team_id, self))

    def open_roster_page(self) -> None:
        """Switch the main view to the roster page."""
        self._go("roster")

    def sign_free_agent(self) -> None:
        try:
            free_agents = find_free_agents(self.players, self.roster)
            if not free_agents:
                QMessageBox.information(self, "Free Agents", "No free agents available to sign.")
                return
            pid = free_agents[0]
            self.roster.act.append(pid)
            QMessageBox.information(self, "Free Agents", f"Signed free agent: {pid}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to sign free agent: {e}")

    def open_standings_window(self) -> None:
        show_on_top(StandingsWindow(self))

    def open_schedule_window(self) -> None:
        show_on_top(ScheduleWindow(self))

    def open_team_schedule_window(self) -> None:
        if not getattr(self, "team_id", None):
            QMessageBox.warning(self, "Error", "Team information not available.")
            return
        has_games = False
        if SCHEDULE_FILE.exists():
            with SCHEDULE_FILE.open(newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if row.get("home") == self.team_id or row.get("away") == self.team_id:
                        has_games = True
                        break
        if not has_games:
            QMessageBox.information(self, "Schedule", "No schedule available for this team.")
            return
        show_on_top(TeamScheduleWindow(self.team_id, self))

    def open_season_progress_window(self) -> None:
        """Open the season progress dialog without blocking the dashboard."""
        existing = getattr(self, "_season_progress_window", None)
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return
        except Exception:
            self._season_progress_window = None

        try:
            win = SeasonProgressWindow(
                self,
                run_async=self._context.run_async,
                show_toast=self._context.show_toast,
                register_cleanup=self._context.register_cleanup,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Season Progress",
                f"Unable to open season progress: {exc}",
            )
            return

        self._season_progress_window = win

        def _refresh_after_progress() -> None:
            try:
                self._update_status_bar()
            except Exception:
                pass
            try:
                self._update_header_context()
            except Exception:
                pass

        def _clear_reference() -> None:
            self._season_progress_window = None
            _refresh_after_progress()

        try:
            win.progressUpdated.connect(lambda *_, cb=_refresh_after_progress: cb())
            win.destroyed.connect(lambda *_: _clear_reference())
        except Exception:
            pass

        try:
            win.show()
            win.raise_()
            win.activateWindow()
        except Exception:
            pass

    def open_draft_console(self) -> None:
        available, cur_date, draft_date, completed = self._draft_availability_details()
        if completed:
            QMessageBox.information(
                self,
                "Draft Console",
                "Draft already completed for this season.",
            )
            return
        if not available:
            if cur_date and draft_date:
                message = (
                    f"Draft Day: {draft_date}. Current date: {cur_date}. "
                    "Draft Console opens on Draft Day."
                )
            else:
                message = (
                    "Draft timing unavailable. Ensure schedule and season progress "
                    "exist before opening the Draft Console."
                )
            QMessageBox.information(self, "Draft Console", message)
            return

        if not draft_date:
            year = self._current_season_year()
            draft_date = self._compute_draft_date_for_year(year)
        try:
            dlg = DraftConsole(draft_date, self)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Draft Console",
                f"Unable to open Draft Console: {exc}",
            )
            return
        dlg.exec()

    def _compute_draft_date_for_year(self, year: int) -> str:
        import datetime as _dt

        d = _dt.date(year, 7, 1)
        while d.weekday() != 1:
            d += _dt.timedelta(days=1)
        d += _dt.timedelta(days=14)
        return d.isoformat()

    def _current_season_year(self) -> int:
        try:
            import csv as _csv

            sched = get_base_dir() / "data" / "schedule.csv"
            if sched.exists():
                with sched.open(newline="") as fh:
                    r = _csv.DictReader(fh)
                    first = next(r, None)
                    if first and first.get("date"):
                        return int(str(first["date"]).split("-")[0])
        except Exception:
            pass

        date_str = get_current_sim_date()
        if date_str:
            try:
                return int(str(date_str).split("-")[0])
            except Exception:
                pass

        from datetime import date as _date

        return _date.today().year

    def _draft_availability_details(
        self,
    ) -> tuple[bool, str | None, str | None, bool]:
        import csv as _csv
        import json as _json
        from datetime import date as _date

        base = get_base_dir() / "data"
        sched = base / "schedule.csv"
        prog = base / "season_progress.json"
        if not sched.exists() or not prog.exists():
            return (False, None, None, False)

        try:
            with prog.open("r", encoding="utf-8") as fh:
                progress = _json.load(fh)
        except Exception:
            progress = {}

        cur_date = get_current_sim_date()
        if not cur_date:
            try:
                with sched.open(newline="") as fh:
                    rows = list(_csv.DictReader(fh))
                first = next((r for r in rows if r.get("date")), None)
                cur_date = str(first.get("date")) if first else ""
            except Exception:
                cur_date = ""
        if not cur_date:
            return (False, None, None, False)

        year = int(cur_date.split("-")[0])
        draft_date = self._compute_draft_date_for_year(year)
        done = (
            set(progress.get("draft_completed_years", []))
            if isinstance(progress, dict)
            else set()
        )
        completed = year in done
        try:
            y1, m1, d1 = [int(x) for x in cur_date.split("-")]
            y2, m2, d2 = [int(x) for x in draft_date.split("-")]
            available = (not completed) and (_date(y1, m1, d1) >= _date(y2, m2, d2))
        except Exception:
            available = False
        return (available, cur_date, draft_date, completed)

    def open_team_stats_window(self, tab: str = "team") -> None:
        """Open the team statistics window with the specified default tab."""
        if not getattr(self, "team", None):
            QMessageBox.warning(self, "Error", "Team information not available.")
            return
        w = TeamStatsWindow(self.team, self.players, self.roster, self)
        index_map = {"batting": 0, "pitching": 1, "team": 2}
        if isinstance(tab, bool) or tab is None:
            tab_name = "team"
        else:
            tab_name = str(tab).lower()
        w.tabs.setCurrentIndex(index_map.get(tab_name, 2))
        show_on_top(w)

    def open_league_stats_window(self) -> None:
        teams = load_teams()
        show_on_top(LeagueStatsWindow(teams, self.players.values(), self))

    def open_league_leaders_window(self) -> None:
        show_on_top(LeagueLeadersWindow(self.players.values(), self))

    def open_league_history_window(self) -> None:
        show_on_top(LeagueHistoryWindow(self))

    def open_news_window(self) -> None:
        try:
            show_on_top(NewsWindow(self))
        except Exception:
            pass

    def open_team_settings_dialog(self) -> None:
        """Open the Team Settings dialog for the current team and persist changes."""
        try:
            if not getattr(self, "team", None):
                QMessageBox.warning(self, "Team Settings", "No team loaded for this owner.")
                return
            from ui.team_settings_dialog import TeamSettingsDialog
            dlg = TeamSettingsDialog(self.team, self)
            if dlg.exec():
                data = dlg.get_settings()
                # Update the in-memory team and persist to CSV
                self.team.primary_color = data.get("primary_color", self.team.primary_color) or self.team.primary_color
                self.team.secondary_color = data.get("secondary_color", self.team.secondary_color) or self.team.secondary_color
                self.team.stadium = data.get("stadium", self.team.stadium) or self.team.stadium
                save_team_settings(self.team)
                QMessageBox.information(self, "Team Settings", "Team settings saved.")
                # Notify pages to refresh if they implement refresh()
                try:
                    for p in self.pages.values():
                        if hasattr(p, "refresh"):
                            p.refresh()  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "Team Settings", f"Failed to update settings: {e}")

    def open_team_injury_center(self) -> None:
        try:
            self._injury_window = InjuryCenterWindow(self, team_filter=self.team_id)
            self._injury_window.show()
        except Exception:
            pass

    # ---------- Utilities ----------
    def calculate_age(self, birthdate_str: str):
        try:
            birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
            today = datetime.today().date()
            return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        except Exception:
            return "?"

    def _make_player_item(self, p):
        age = self.calculate_age(p.birthdate)
        role = get_role(p)
        if role:
            arm_display = rating_display_text(
                getattr(p, "arm", 0), key="AS", is_pitcher=True
            )
            endurance_display = rating_display_text(
                getattr(p, "endurance", 0), key="EN", is_pitcher=True
            )
            control_display = rating_display_text(
                getattr(p, "control", 0), key="CO", is_pitcher=True
            )
            core = (
                f"AS:{arm_display} EN:{endurance_display} "
                f"CO:{control_display}"
            )
            
        else:
            ch_display = rating_display_text(
                getattr(p, "ch", 0),
                key="CH",
                position=getattr(p, "primary_position", None),
                is_pitcher=False,
            )
            ph_display = rating_display_text(
                getattr(p, "ph", 0),
                key="PH",
                position=getattr(p, "primary_position", None),
                is_pitcher=False,
            )
            sp_display = rating_display_text(
                getattr(p, "sp", 0),
                key="SP",
                position=getattr(p, "primary_position", None),
                is_pitcher=False,
            )
            core = f"CH:{ch_display} PH:{ph_display} SP:{sp_display}"
        label = f"{p.first_name} {p.last_name} ({age}) - {role or p.primary_position} | {core}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, p.player_id)
        return item

    # ---------- Metrics for Home page and header ----------
    def get_quick_metrics(self) -> dict:
        """Return cached metrics for the header and home page."""
        try:
            metrics = gather_owner_quick_metrics(
                self.team_id,
                base_path=self.context.base_path,
                roster=self.roster,
                players=self.players,
            )
        except Exception:
            metrics = {}
        self._latest_metrics = metrics
        return metrics

    def closeEvent(self, event) -> None:  # type: ignore[override]
        for callback in list(self._cleanup_callbacks):
            try:
                callback()
            except Exception:
                pass
        for fut in list(self._background_futures):
            try:
                fut.cancel()
            except Exception:
                pass
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass
        try:
            if hasattr(self, "_sim_date_bus"):
                self._sim_date_bus.dateChanged.disconnect(self._on_sim_date_changed)
        except Exception:
            pass
        super().closeEvent(event)

    def _update_header_context(self) -> None:
        """Update header scoreboard label with quick context."""
        metrics = self.get_quick_metrics()
        rec = metrics.get("record", "--")
        rd = metrics.get("run_diff", "--")
        opp = metrics.get("next_opponent", "--")
        date = metrics.get("next_date", "--")
        streak = metrics.get("streak", "--")
        last10 = metrics.get("last10", "--")
        injuries = metrics.get("injuries", 0)
        prob = metrics.get("prob_sp", "--")
        bullpen = metrics.get("bullpen", {}) or {}
        bp_ready = int(bullpen.get("ready", 0) or 0)
        bp_total = int(bullpen.get("total", 0) or 0)
        bp_summary = f"{bp_ready}/{bp_total}" if bp_total else "--"
        trend_series = ((metrics.get("trends") or {}).get("series") or {})
        win_pct_series = trend_series.get("win_pct") or []
        win_pct = f"{win_pct_series[-1]:.3f}" if win_pct_series else "--"
        text = (
            f"Next: {opp} {date} | Record {rec} RD {rd} | "
            f"Stk {streak} L10 {last10} | Inj {injuries} | Prob SP {prob} | "
            f"BP {bp_summary} | Win% {win_pct}"
        )
        try:
            self.scoreboard.setText(text)
        except Exception:
            pass
        # Update roster nav tooltip with coverage summary
        try:
            miss = missing_positions(self.roster, self.players)
            if miss:
                self.btn_roster.setToolTip("Missing coverage: " + ", ".join(miss))
            else:
                self.btn_roster.setToolTip("Defensive coverage looks good.")
        except Exception:
            pass
