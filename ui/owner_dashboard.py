from __future__ import annotations

import csv
import importlib
import json
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
    QFileDialog,
    QLineEdit,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .components import NavButton
from .roster_page import RosterPage
from .transactions_page import TransactionsPage
from .schedule_page import SchedulePage
from .team_page import TeamPage
from .team_records_page import TeamRecordsPage
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
from .league_command_center_window import LeagueCommandCenterWindow
from .team_schedule_window import TeamScheduleWindow, SCHEDULE_FILE
from .team_stats_window import TeamStatsWindow
from .league_stats_window import LeagueStatsWindow
from .league_leaders_window import LeagueLeadersWindow
from .league_history_window import LeagueHistoryWindow
from .news_window import NewsWindow
from .season_progress_window import SeasonProgressWindow
from .draft_console import DraftConsole
from .draft_results_dialog import DraftResultsDialog
from .player_browser_dialog import PlayerBrowserDialog
from .injury_center_window import InjuryCenterWindow
from .depth_chart_dialog import DepthChartDialog
from .tutorial_dialog import TutorialDialog, TutorialStep
from .manual_viewer_dialog import (
    DOC_FINANCE_MANUAL,
    DOC_GAME_MANUAL,
    ManualViewerDialog,
)
from .training_focus_dialog import TrainingFocusDialog
from .change_request_export_dialog import ChangeRequestExportDialog
from .ui_template import _load_baseball_pixmap, _load_nav_icon
from .playoffs_window import PlayoffsWindow
from .free_agency_window import FreeAgencyWindow
from services import league_registry
from services.contracts_service import sign_free_agent_contract
from services.contracts_service import estimate_salary_for_player
from services.team_strategy_profiles import set_team_strategy_profile
from services.team_auto_reassign_settings import (
    auto_reassign_team_if_enabled,
    set_team_auto_reassign,
)
from services.payroll_policy import (
    evaluate_free_agent_signing,
    format_payroll_policy_message,
    record_payroll_policy_result,
)
from utils.roster_loader import load_roster, save_roster
from utils.player_loader import load_players_from_csv
from utils.free_agent_finder import find_free_agents
from utils.pitcher_role import get_role
from utils.rating_display import rating_display_text
from utils.team_loader import load_teams, save_team_settings
from utils.path_utils import get_base_dir, get_data_dir
from utils.sim_date import get_current_sim_date
from utils.league_settings import (
    can_run_season_progression,
    is_owner_league,
    verify_commissioner_password,
)
from services.quick_metrics import gather_owner_quick_metrics
from ui.dashboard_core import DashboardContext, NavigationController, PageRegistry
from ui.player_profile_launcher import open_player_profile_dialog
from ui.window_utils import show_on_top
from ui.version_badge import enable_version_badge
from ui.sim_date_bus import sim_date_bus
from . import theme as app_theme
from .theme_assets import load_enhanced_nav_icon

_OPEN_ADMIN_WINDOWS: list[object] = []


def _theme_family_classic() -> str:
    return str(getattr(app_theme, "THEME_FAMILY_CLASSIC", "classic"))


def _theme_family_enhanced_warm() -> str:
    return str(
        getattr(app_theme, "THEME_FAMILY_ENHANCED_WARM", "enhanced_warm")
    )


def _theme_state() -> tuple[str, str]:
    getter = getattr(app_theme, "get_active_theme_state", None)
    if callable(getter):
        try:
            family, mode = getter()
            return str(family), str(mode)
        except Exception:
            pass
    return (_theme_family_classic(), "dark")


def _set_theme_family(family: str, status_bar: object) -> None:
    setter = getattr(app_theme, "set_theme_family", None)
    if callable(setter):
        setter(family, status_bar=status_bar)
        return
    toggler = getattr(app_theme, "_toggle_theme", None)
    if callable(toggler):
        toggler(status_bar)


def _toggle_theme_mode(status_bar: object) -> None:
    toggler = getattr(app_theme, "toggle_theme_mode", None)
    if callable(toggler):
        toggler(status_bar=status_bar)
        return
    legacy = getattr(app_theme, "_toggle_theme", None)
    if callable(legacy):
        legacy(status_bar)


def _theme_label(family: str) -> str:
    labeler = getattr(app_theme, "theme_display_name", None)
    if callable(labeler):
        try:
            return str(labeler(family))
        except Exception:
            pass
    return "Enhanced Warm" if family == _theme_family_enhanced_warm() else "Classic"


def _track_admin_window(window: object) -> None:
    _OPEN_ADMIN_WINDOWS.append(window)

    def _remove(*_args, win=window) -> None:
        try:
            _OPEN_ADMIN_WINDOWS.remove(win)
        except ValueError:
            pass

    try:
        window.destroyed.connect(_remove)  # type: ignore[attr-defined]
    except Exception:
        pass


class OwnerDashboard(QMainWindow):
    """Owner-facing dashboard with sidebar navigation."""

    def __init__(self, team_id: str, *, actor_role: str = "owner"):
        super().__init__()
        enable_version_badge(self)
        self.team_id = team_id
        self._actor_role = str(actor_role or "owner").strip().lower() or "owner"
        self._season_progress_allowed = can_run_season_progression(self._actor_role)
        self._season_progress_block_reason = (
            "Season progression is commissioner-only in multi-owner leagues."
        )
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
        self._submit_change_request_action: Optional[QAction] = None
        self._change_request_tutorial_action: Optional[QAction] = None

        self.setWindowTitle(f"Owner Dashboard - {team_id}")
        self.resize(1100, 720)
        self._admin_window = None
        self._season_progress_window: Optional[SeasonProgressWindow] = None
        self._playoffs_win = None

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
        self.btn_records = NavButton("  Records & Leaders")
        self.btn_transactions = NavButton("  Moves & Trades")
        self.btn_finance = NavButton("  Finance")
        self.btn_league = NavButton("  League Hub")

        for b in (
            self.btn_home,
            self.btn_roster,
            self.btn_team,
            self.btn_records,
            self.btn_transactions,
            self.btn_finance,
            self.btn_league,
        ):
            side.addWidget(b)

        self.nav_buttons = {
            "home": self.btn_home,
            "roster": self.btn_roster,
            "team": self.btn_team,
            "records": self.btn_records,
            "transactions": self.btn_transactions,
            "finance": self.btn_finance,
            "league": self.btn_league,
        }

        self._nav_icon_size = QSize(24, 24)
        self._nav_icon_sources = {
            "home": "nav_dashboard.svg",
            "roster": "nav_roster.svg",
            "team": "nav_team.svg",
            "records": "nav_team.svg",
            "transactions": "nav_transactions.svg",
            "finance": "nav_utilities.svg",
            "league": "nav_league.svg",
        }
        self._nav_tooltips = {
            "home": "Overview and quick actions",
            "roster": "Roster management and player tools",
            "team": "Team schedule and stats",
            "records": "Team records and leaders",
            "transactions": "Transactions, trades, and movement",
            "finance": "Owner finance projection and transaction history",
            "league": "League schedule, standings, and stats",
        }
        self._refresh_nav_icons()

        side.addStretch()
        self.btn_settings = NavButton("  Toggle Light/Dark")
        self.btn_settings.clicked.connect(self._toggle_theme_mode)
        side.addWidget(self.btn_settings)
        self.btn_admin_panel = NavButton("  Admin Panel")
        self.btn_admin_panel.clicked.connect(self._prompt_admin_dashboard)
        side.addWidget(self.btn_admin_panel)

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
        self.league_badge = QLabel("League: -")
        self.league_badge.setObjectName("Scoreboard")
        h.addWidget(self.league_badge, alignment=Qt.AlignmentFlag.AlignRight)
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
        self._refresh_theme_ui()
        self._sim_date_bus = sim_date_bus()
        try:
            self._sim_date_bus.dateChanged.connect(self._on_sim_date_changed)
        except Exception:
            pass

        # Navigation signals
        self.btn_home.clicked.connect(lambda: self._go("home"))
        self.btn_roster.clicked.connect(lambda: self._go("roster"))
        self.btn_team.clicked.connect(lambda: self._go("team"))
        self.btn_records.clicked.connect(lambda: self._go("records"))
        self.btn_transactions.clicked.connect(lambda: self._go("transactions"))
        self.btn_finance.clicked.connect(lambda: self._go("finance"))
        self.btn_league.clicked.connect(lambda: self._go("league"))
        self._go("home")
        self._update_league_badge()

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
            "appearance": f"appearance_theme_tutorial_{team_id}",
            "training_camp": f"training_camp_tutorial_{team_id}",
            "player_training": f"player_training_focus_tutorial_{team_id}",
            "draft": f"draft_console_tutorial_{team_id}",
            "trades": f"trade_workflow_tutorial_{team_id}",
            "change_requests": f"change_requests_tutorial_{team_id}",
            "free_agency": f"free_agency_tutorial_{team_id}",
            "team_settings": f"team_settings_tutorial_{team_id}",
            "finance_snapshot": f"finance_snapshot_tutorial_{team_id}",
            "schedule": f"schedule_tutorial_{team_id}",
            "command_center": f"league_command_center_tutorial_{team_id}",
            "league_hub": f"league_hub_tutorial_{team_id}",
            "reports": f"reports_exports_tutorial_{team_id}",
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
        if QTimer:
            QTimer.singleShot(600, self._maybe_notify_playoff_berth)
        else:
            self._maybe_notify_playoff_berth()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        admin_action = QAction("Open Admin Dashboard", self)
        admin_action.triggered.connect(self._prompt_admin_dashboard)
        file_menu.addAction(admin_action)
        import_snapshot_action = QAction("Import League Snapshot...", self)
        import_snapshot_action.triggered.connect(self.import_league_snapshot)
        file_menu.addAction(import_snapshot_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        theme_menu = view_menu.addMenu("Theme Family")
        self._theme_family_actions: dict[str, QAction] = {}
        for family in (
            _theme_family_classic(),
            _theme_family_enhanced_warm(),
        ):
            action = QAction(_theme_label(family), self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, f=family: self._set_theme_family(f)
            )
            theme_menu.addAction(action)
            self._theme_family_actions[family] = action

        toggle_theme_action = QAction("Toggle Light/Dark", self)
        toggle_theme_action.triggered.connect(self._toggle_theme_mode)
        view_menu.addAction(toggle_theme_action)
        news_action = QAction("News Feed", self)
        news_action.triggered.connect(self.open_news_window)
        view_menu.addAction(news_action)
        try:
            settings_action = QAction("Team Settings", self)
            settings_action.triggered.connect(self.open_team_settings_dialog)
            view_menu.addAction(settings_action)
        except Exception:
            pass

    def _set_theme_family(self, family: str) -> None:
        _set_theme_family(family, self.statusBar())
        self._refresh_theme_ui()

    def _toggle_theme_mode(self) -> None:
        _toggle_theme_mode(self.statusBar())
        self._refresh_theme_ui()

    def on_theme_changed(self, _family: str = "", _mode: str = "") -> None:
        self._refresh_theme_ui()

    def _refresh_theme_ui(self) -> None:
        self._refresh_theme_menu_checks()
        self._refresh_nav_icons()
        for page in self.pages.values():
            hook = getattr(page, "apply_theme_assets", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    pass

    def _refresh_theme_menu_checks(self) -> None:
        family, mode = _theme_state()
        for action_family, action in getattr(
            self, "_theme_family_actions", {}
        ).items():
            try:
                action.setChecked(action_family == family)
            except Exception:
                pass
        mode_label = "dark" if mode == "dark" else "light"
        tip = (
            f"Toggle Light/Dark (current: {_theme_label(family)} {mode_label})"
        )
        try:
            self.btn_settings.setToolTip(tip)
        except Exception:
            pass

    def _refresh_nav_icons(self) -> None:
        icon_size = getattr(self, "_nav_icon_size", QSize(24, 24))
        family, _mode = _theme_state()
        for key, button in self.nav_buttons.items():
            icon = QIcon()
            if family == _theme_family_enhanced_warm():
                icon = load_enhanced_nav_icon(key, icon_size.width())

            is_null = True
            try:
                is_null = bool(icon.isNull())
            except Exception:
                is_null = False
            if is_null:
                icon_name = self._nav_icon_sources.get(key)
                icon = (
                    _load_nav_icon(icon_name, icon_size.width())
                    if icon_name
                    else QIcon()
                )

            try:
                if not icon.isNull():
                    button.setIcon(icon)
                    button.setIconSize(icon_size)
                    button.setToolButtonStyle(
                        Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                    )
            except Exception:
                pass

            tip = self._nav_tooltips.get(key)
            if tip:
                button.setToolTip(tip)

    def _build_tutorial_menu(self) -> None:
        tutorials_menu = self.menuBar().addMenu("&Tutorials")

        def _add_tutorial_action(
            menu: object,
            label: str,
            callback: Callable[..., None],
        ) -> QAction:
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, cb=callback: cb(force=True)
            )
            menu.addAction(action)  # type: ignore[attr-defined]
            return action

        tutorial_categories = [
            (
                "Getting Started",
                [
                    ("Dashboard Overview", self.show_dashboard_overview_tutorial),
                    ("Appearance & Themes", self.show_theme_tutorial),
                    ("League Hub Tour", self.show_league_hub_tutorial),
                    ("League Command Center", self.show_command_center_tutorial),
                    ("Schedule & Calendar", self.show_schedule_tutorial),
                ],
            ),
            (
                "Roster & Team",
                [
                    ("Roster Moves Guide", self.show_roster_moves_tutorial),
                    ("Lineup & Strategy Tutorial", self.show_lineup_strategy_tutorial),
                    ("Pitching Staff Tutorial", self.show_pitching_staff_tutorial),
                    ("Depth Chart Basics", self.show_depth_chart_tutorial),
                    ("Injury Center Guide", self.show_injury_center_tutorial),
                    ("Team Settings", self.show_team_settings_tutorial),
                ],
            ),
            (
                "Development",
                [
                    ("Training Camp & Development", self.show_training_camp_tutorial),
                    (
                        "Individual Training Focus",
                        self.show_player_training_focus_tutorial,
                    ),
                    ("Draft Console Guide", self.show_draft_console_tutorial),
                    ("Free Agency Basics", self.show_free_agency_tutorial),
                ],
            ),
            (
                "Transactions & Finance",
                [
                    ("Trades & Transactions", self.show_trades_tutorial),
                    ("Owner Change Requests", self.show_change_request_tutorial),
                    ("Finance Hub Overview", self.show_finance_snapshot_tutorial),
                    ("Reports & Exports", self.show_reports_tutorial),
                ],
            ),
            (
                "Commissioner",
                [
                    ("Admin Tools Overview", self.show_admin_tools_tutorial),
                ],
            ),
        ]

        for category_label, entries in tutorial_categories:
            category_menu = tutorials_menu.addMenu(category_label)
            for action_label, callback in entries:
                action = _add_tutorial_action(category_menu, action_label, callback)
                if action_label == "Owner Change Requests":
                    self._change_request_tutorial_action = action

        manuals_menu = tutorials_menu.addMenu("Reference Manuals")
        game_manual_action = QAction("Complete Game Manual", self)
        game_manual_action.triggered.connect(self.open_game_manual)
        manuals_menu.addAction(game_manual_action)
        finance_manual_action = QAction("Finance System Manual", self)
        finance_manual_action.triggered.connect(self.open_finance_manual)
        manuals_menu.addAction(finance_manual_action)
        self._refresh_change_request_ui_state()

        owner_tools_menu = self.menuBar().addMenu("&Owner Tools")

        submit_change_request_action = QAction("Submit Change Request...", self)
        submit_change_request_action.setStatusTip(
            "Export roster, lineup, pitching, and depth chart updates for commissioner approval"
        )
        submit_change_request_action.triggered.connect(self.open_change_request_export_dialog)
        owner_tools_menu.addAction(submit_change_request_action)
        self._submit_change_request_action = submit_change_request_action

        lineup_editor_action = QAction("Lineup Editor...", self)
        lineup_editor_action.setStatusTip("Open lineup editor for vs LHP and vs RHP lineups")
        lineup_editor_action.triggered.connect(self.open_lineup_editor)
        owner_tools_menu.addAction(lineup_editor_action)

        pitching_staff_action = QAction("Pitching Staff...", self)
        pitching_staff_action.setStatusTip("Open pitching staff roles and rotation editor")
        pitching_staff_action.triggered.connect(self.open_pitching_editor)
        owner_tools_menu.addAction(pitching_staff_action)

        reassign_players_action = QAction("Reassign Players...", self)
        reassign_players_action.setStatusTip("Move players across ACT/AAA/LOW roster levels")
        reassign_players_action.triggered.connect(self.open_reassign_players_dialog)
        owner_tools_menu.addAction(reassign_players_action)

        trade_center_action = QAction("Trade Center...", self)
        trade_center_action.setStatusTip("Open trade dialog to submit offers")
        trade_center_action.triggered.connect(self.open_trade_dialog)
        owner_tools_menu.addAction(trade_center_action)

        free_agency_action = QAction("Free Agency Hub...", self)
        free_agency_action.setStatusTip("Browse unsigned players and simulate free-agent bids")
        free_agency_action.triggered.connect(self.open_free_agency_hub)
        owner_tools_menu.addAction(free_agency_action)

        finance_snapshot_action = QAction("Open Finance Hub...", self)
        finance_snapshot_action.setStatusTip(
            "Open the Finance hub (Owner Ops + GM/Coach Ops) for projections and queue visibility"
        )
        finance_snapshot_action.triggered.connect(self.open_finance_hub)
        owner_tools_menu.addAction(finance_snapshot_action)

        command_center_action = QAction("League Command Center...", self)
        command_center_action.setStatusTip(
            "Open league-wide attention cards for injuries, approvals, roster issues, deadlines, and finance risk."
        )
        command_center_action.triggered.connect(self.open_league_command_center)
        owner_tools_menu.addAction(command_center_action)

        owner_tools_menu.addSeparator()

        team_settings_tools_action = QAction("Team Settings...", self)
        team_settings_tools_action.setStatusTip("Open team branding and stadium settings")
        team_settings_tools_action.triggered.connect(self.open_team_settings_dialog)
        owner_tools_menu.addAction(team_settings_tools_action)

        simulate_menu = self.menuBar().addMenu("&Simulate")
        self.season_progress_action = QAction("Season Progress...", self)
        self.season_progress_action.setStatusTip("Open season progress controls")
        self.season_progress_action.triggered.connect(self.open_season_progress_window)
        simulate_menu.addAction(self.season_progress_action)
        if not self._season_progress_allowed:
            self.season_progress_action.setEnabled(False)
            self.season_progress_action.setStatusTip(self._season_progress_block_reason)
            try:
                simulate_menu.menuAction().setVisible(False)
            except Exception:
                pass
        self._refresh_change_request_ui_state()

    def is_change_request_submission_available(self) -> bool:
        try:
            return bool(is_owner_league())
        except Exception:
            return True

    def _refresh_change_request_ui_state(self) -> None:
        enabled = self.is_change_request_submission_available()

        try:
            if self._submit_change_request_action is not None:
                self._submit_change_request_action.setVisible(enabled)
                self._submit_change_request_action.setEnabled(enabled)
        except Exception:
            pass

        try:
            if self._change_request_tutorial_action is not None:
                self._change_request_tutorial_action.setVisible(enabled)
                self._change_request_tutorial_action.setEnabled(enabled)
        except Exception:
            pass

        try:
            roster_page = self.pages.get("roster")
            updater = getattr(roster_page, "refresh_change_request_visibility", None)
            if callable(updater):
                updater(enabled)
        except Exception:
            pass

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

    def open_game_manual(self, *_args, **_kwargs) -> None:
        self._open_manual(doc_id=DOC_GAME_MANUAL)

    def open_finance_manual(self, *_args, **_kwargs) -> None:
        self._open_manual(doc_id=DOC_FINANCE_MANUAL)

    def _open_manual(self, *, doc_id: str) -> None:
        try:
            dialog = ManualViewerDialog(initial_doc_id=doc_id, parent=self)
            dialog.exec()
        except Exception:
            pass

    def show_theme_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Theme Families",
                "<p>Open <b>View -> Theme Family</b> to switch between <b>Classic</b> and "
                "<b>Enhanced Warm</b> styles without changing gameplay.</p>",
            ),
            TutorialStep(
                "Light and Dark Modes",
                "<p>Use <b>View -> Toggle Light/Dark</b> or the sidebar "
                "<b>Toggle Light/Dark</b> button to flip brightness while staying in the same family.</p>",
            ),
            TutorialStep(
                "Saved Preference",
                "<p>Your theme choice is saved automatically and restored the next time you launch the app.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["appearance"],
            "Appearance & Themes",
            steps,
            force=force,
        )

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
                "<p>Use <b>Owner Tools -> Reassign Players</b> (or the Roster page button)"
                " to promote/demote between ACT, AAA, and Low. The dialog enforces roster limits"
                " and highlights when a level is full.</p>",
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
                "<p>Open <b>Owner Tools -> Pitching Staff</b> (or the Roster page action)"
                " to drag your rotation slots. "
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
                "<p>Open <b>Owner Tools -> Lineup Editor</b> (or the Roster page button)."
                " The <b>Lineups</b> editor stores separate batting orders for left- and right-handed starters."
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
        if self.is_change_request_submission_available():
            owner_tools_text = (
                "<p>The top menu includes <b>Owner Tools</b> for fast access to Submit Change Request,"
                " Lineup Editor, Pitching Staff, Reassign Players, Trade Center, Free Agency Hub, Open Finance Hub,"
                " and Team Settings.</p>"
            )
        else:
            owner_tools_text = (
                "<p>The top menu includes <b>Owner Tools</b> for fast access to Lineup Editor, Pitching Staff,"
                " Reassign Players, Trade Center, Free Agency Hub, Open Finance Hub, and Team Settings.</p>"
            )
        steps = [
            TutorialStep(
                "Scoreboard Strip",
                "<p>The top scoreboard summarizes record, run differential, streak, upcoming opponent, injuries,"
                " and bullpen readiness/budget percentage."
                " It updates whenever the sim date advances.</p>",
            ),
            TutorialStep(
                "Quick Actions",
                "<p>Use the Quick Actions card on the Dashboard page to jump to common tasks like lineups, pitching staff,"
                " injuries, and stats.</p>",
            ),
            TutorialStep(
                "Owner Tools Menu",
                owner_tools_text,
            ),
            TutorialStep(
                "Performers & Standings",
                "<p>The dashboard highlights hot/cold performers from recent games and a snapshot of your division standings."
                " Toggle \"View all\" to expand the news feed preview.</p>",
            ),
            TutorialStep(
                "Navigation Tips",
                "<p>The sidebar buttons switch between Dashboard, Roster, Team schedule, Moves & Trades,"
                " Finance, and League Hub."
                " The Tutorials menu is always available up top.</p>",
            ),
        ]
        self._run_tutorial(self._tutorial_keys["overview"], "Owner Dashboard Overview", steps, force=force)

    def show_training_camp_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "When to Run Camp",
                "<p>Open <b>Admin Dashboard -> Season -> Season Progress</b> once free agency prep is complete."
                " The <b>Run Training Camp</b> button unlocks after you finish required preseason tasks.</p>",
            ),
            TutorialStep(
                "Customize Focus Budgets",
                "<p>Before running camp you can tailor hitter and pitcher allocations."
                " Use the <b>Training Focus</b> button on the Roster page or the <b>Training Focus...</b> button in"
                " the Season Progress window to split training time across tracks. You can also override individual players from their profile or the roster tables. League defaults are used when"
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

    def show_player_training_focus_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Where to Find It",
                "<p>Open any player profile and click <b>Training Focus...</b> in the header actions. "
                "You can also open it from roster tables by right-clicking a player or double-clicking "
                "the new <b>FOCUS</b> column.</p>",
            ),
            TutorialStep(
                "Focus Sources",
                "<p>Each player uses one of three sources:</p>"
                "<ul>"
                "<li><b>Player</b> = custom allocations set just for this player.</li>"
                "<li><b>Team</b> = team-wide allocations from the owner dashboard.</li>"
                "<li><b>League</b> = league defaults from Season Progress.</li>"
                "</ul>",
            ),
            TutorialStep(
                "Bulk Updates",
                "<p>Select multiple players in the roster tables, right-click, and choose "
                "<b>Apply Training Focus to Selected</b>. This writes the same allocations "
                "to each chosen player.</p>",
            ),
            TutorialStep(
                "Reverting",
                "<p>Use <b>Use Team Default</b> (or <b>Use League Default</b> for free agents) "
                "to clear a player override. They immediately fall back to team or league settings.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["player_training"],
            "Individual Training Focus",
            steps,
            force=force,
        )

    def show_draft_console_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Open the Draft Room",
                "<p>Commissioners can open the Draft Console from the Admin tools when the draft window is active."
                " Owners can review draft pools from League pages or the draft results history.</p>",
            ),
            TutorialStep(
                "Draft Board Flow",
                "<p>Each pick advances in order. Use manual selection or the auto-pick button to speed through."
                " The console logs picks with round, overall, and team IDs.</p>",
            ),
            TutorialStep(
                "Prospect Details",
                "<p>Double-click a prospect to open their profile. Compare ratings, age, and potential before"
                " committing a pick.</p>",
            ),
            TutorialStep(
                "Results & History",
                "<p>Draft results are stored per season and are viewable from the league history screens."
                " Export reports if you want to share picks with owners.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["draft"],
            "Draft Console Guide",
            steps,
            force=force,
        )

    def show_trades_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Trade Dialog",
                "<p>Open <b>Owner Tools -> Trade Center</b> (or the dashboard Trades action) to propose offers."
                " Select a partner, add players,"
                " and include draft picks when enabled. Commissioners can disable trading,"
                " disable draft pick trades, require commissioner approval, or cap how many"
                " years out picks are tradable via <b>League -> Trade Settings</b>. CPU-initiated"
                " offers and proactive CPU trade cadence are also controlled there.</p>",
            ),
            TutorialStep(
                "Pending Queue",
                "<p>Submitted offers appear in the pending queue. Owners can accept or reject based"
                " on roster needs. If commissioner approval is off, owner acceptance executes the trade"
                " immediately. If commissioner approval is required, owner acceptance marks the trade"
                " for commissioner review and no assets move until final approval.</p>",
            ),
            TutorialStep(
                "Roster Impact",
                "<p>After a trade completes, review depth charts and lineups. Promotions or demotions may be"
                " needed if a level exceeds roster limits. Draft pick ownership also updates and is honored"
                " on draft day.</p>",
            ),
            TutorialStep(
                "Audit Trail",
                "<p>Every completed trade writes player and draft-pick movement entries to the"
                " transactions log plus a news feed event so the league can audit what changed and when.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["trades"],
            "Trades & Transactions",
            steps,
            force=force,
        )

    def show_change_request_tutorial(self, *, force: bool = False) -> None:
        if not self.is_change_request_submission_available():
            QMessageBox.information(
                self,
                "Owner Change Requests",
                "Submit Change Request is only available in multi-owner leagues.",
            )
            return
        steps = [
            TutorialStep(
                "Where to Start",
                "<p>Open <b>Owner Tools -> Submit Change Request</b> (or use the Roster page button)."
                " This opens the export dialog used for commissioner approval workflows.</p>",
            ),
            TutorialStep(
                "Choose What to Send",
                "<p>Select the sections to include: roster, lineups, pitching staff, and depth chart. Add an"
                " optional owner note so the commissioner knows why you made the updates.</p>",
            ),
            TutorialStep(
                "Export and Deliver",
                "<p>Click <b>Export Request</b>. The app writes a JSON bundle to your change-request outbox."
                " Send that file to the commissioner/admin for import and review.</p>",
            ),
            TutorialStep(
                "Track and Cancel",
                "<p>The dialog lists your previously exported requests. Select one and click"
                " <b>Export Cancel</b> if you need to withdraw it before the commissioner applies it.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["change_requests"],
            "Owner Change Requests",
            steps,
            force=force,
        )

    def show_free_agency_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Review the Pool",
                "<p>Open <b>Owner Tools -> Free Agency Hub</b> to browse unsigned players."
                " Use the filters to sort by position and overall.</p>",
            ),
            TutorialStep(
                "Signing Players",
                "<p>Select a free agent, review their ratings, and commit the signing. The roster limit rules"
                " still apply, so make room if needed.</p>",
            ),
            TutorialStep(
                "Depth Chart Updates",
                "<p>After a signing, update depth charts or lineups so the simulator knows where to use the"
                " new player.</p>",
            ),
            TutorialStep(
                "League Visibility",
                "<p>Free agent moves appear in the news feed and transactions window for transparency.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["free_agency"],
            "Free Agency Basics",
            steps,
            force=force,
        )

    def show_team_settings_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Access Team Settings",
                "<p>Open <b>Owner Tools -> Team Settings</b> (or use <b>View -> Team Settings</b>)."
                " This is where you manage branding, stadium, and team metadata,"
                " including team strategy and roster auto-reassign overrides.</p>",
            ),
            TutorialStep(
                "Branding Options",
                "<p>Update team name, city, colors, and logos. If you change logos, refresh any open windows"
                " to see the new artwork. The uniform preview updates live as you edit primary/secondary colors.</p>",
            ),
            TutorialStep(
                "Stadium & Park Factors",
                "<p>Pick a home park that matches your roster strategy. Park settings are reflected in sim"
                " outputs and stats, and the Team Settings dialog now shows a live park preview when available.</p>",
            ),
            TutorialStep(
                "Team Strategy & Auto-Reassign",
                "<p>Use the <b>Team Strategy</b> dropdown to keep <b>League Default</b> or set a team-specific"
                " profile (for example <b>Win Now</b> or <b>Development Focus</b>) to steer automation intent."
                " Use <b>Roster Auto-Reassign</b> to inherit league default behavior or explicitly enable/disable"
                " automatic ACT/AAA/LOW balancing for this team.</p>",
            ),
            TutorialStep(
                "Save & Verify",
                "<p>Click save before closing the dialog. Reopen the dashboard to verify the new branding"
                " and color palette applied correctly.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["team_settings"],
            "Team Settings",
            steps,
            force=force,
        )

    def show_finance_snapshot_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Open Finance Hub",
                "<p>Use the <b>Finance</b> sidebar tab or <b>Owner Tools -> Open Finance Hub</b>"
                " to open a two-tab finance hub: <b>Owner Ops</b> and <b>GM/Coach Ops</b>.</p>",
            ),
            TutorialStep(
                "Owner Ops Tab",
                "<p><b>Owner Ops</b> breaks out projected monthly <b>Revenue</b>, <b>Expenses</b>, and"
                " recommended <b>Budgets</b> for training, scouting, development, and facilities."
                " When Owner Budgets is enabled, you can edit and save those budget targets directly from this tab."
                " Training/development/facilities budget levels now influence preseason"
                " training-camp development intensity, and development budgets now also"
                " influence offseason aging/development outcomes."
                " Scouting budget now also affects player-profile scouting confidence"
                " and estimated rating uncertainty."
                " Use the <b>Scouting Controls</b> card in Owner Ops to set team scouting"
                " intensity (<b>Low</b>/<b>Normal</b>/<b>High</b>) and monitor confidence"
                " plus estimated rating error bands.</p>",
            ),
            TutorialStep(
                "GM/Coach Ops Tab",
                "<p><b>GM/Coach Ops</b> shows module status, payroll commitments, contract outlook,"
                " arbitration/free-agency queue visibility, and a <b>Next Finance Actions</b>"
                " panel so owners can follow the current phase step-by-step.</p>",
            ),
            TutorialStep(
                "Quick Actions",
                "<p>From GM/Coach Ops, use <b>Queue Recommended Arbitration</b> and"
                " <b>Queue Recommended FA Targets</b> to store decisions, then use"
                " <b>Open Trade Center</b> and <b>Open Free Agency Hub</b> to execute moves.</p>",
            ),
            TutorialStep(
                "Contract Terms",
                "<p>In the GM/Coach Ops contract list, select a player to manage advanced terms:"
                " <b>Extend Contract</b>, <b>Edit Guarantees</b>, <b>Add/Edit/Remove Option</b>,"
                " <b>Add/Edit/Remove Incentive</b>, and option decisions"
                " (<b>Exercise Option</b> / <b>Decline Option</b>)."
                " Advanced term actions require the GM Contracts module set to"
                " <b>Advanced</b> or <b>MLB-Like</b>.</p>",
            ),
            TutorialStep(
                "League Mode Behavior",
                "<p>In single-player mode, recommended finance decisions are auto-approved."
                " In multi-owner mode, those decisions are queued for commissioner review.</p>",
            ),
            TutorialStep(
                "Transaction History",
                "<p>The page includes recent finance ledger entries for your club so you can audit revenue/expense"
                " postings as the season simulation advances.</p>",
            ),
            TutorialStep(
                "Commissioner Controls",
                "<p>Commissioners can tune the system from <b>Admin -> League Settings -> Financial System"
                " Settings</b>. The dialog now includes projection preview and prioritized finance alerts"
                " (cash risk, payroll threshold/floor, offseason deadlines) with explicit next steps."
                " It also includes scouting fog-of-war enablement and scouting pace tuning controls.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["finance_snapshot"],
            "Finance Hub Overview",
            steps,
            force=force,
        )

    def show_schedule_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Team Schedule",
                "<p>Open <b>Team Schedule</b> from the dashboard to see upcoming games, results, and home/away"
                " splits.</p>",
            ),
            TutorialStep(
                "League Calendar",
                "<p>The League schedule view shows every matchup. It is useful for spotting doubleheaders or"
                " long road trips.</p>",
            ),
            TutorialStep(
                "Generating Schedules",
                "<p>Commissioners can generate a new schedule from <b>Admin Dashboard -> Season -> Regenerate Schedule</b>."
                " Do this once per season and"
                " before running simulations.</p>",
            ),
            TutorialStep(
                "Tracking Dates",
                "<p>The sim date controls what appears as current. Use the progress window to advance the"
                " season safely.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["schedule"],
            "Schedule & Calendar",
            steps,
            force=force,
        )

    def show_command_center_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Open Command Center",
                "<p>Open <b>League Command Center</b> from the League Hub page, the dashboard quick actions,"
                " or <b>Owner Tools</b> for league-wide attention cards.</p>",
            ),
            TutorialStep(
                "Card Priorities",
                "<p>Cards summarize injuries, pending approvals, roster conflicts, deadlines, and finance"
                " risks with severity and count indicators.</p>",
            ),
            TutorialStep(
                "Refresh Workflow",
                "<p>Use <b>Refresh</b> after major simulation steps or transaction reviews to pull the latest"
                " command-center snapshot before making league decisions.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["command_center"],
            "League Command Center",
            steps,
            force=force,
        )

    def show_league_hub_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Standings Snapshot",
                "<p>The League hub surfaces standings by division and league. Use it to track playoff races"
                " and seed positions.</p>",
            ),
            TutorialStep(
                "Leaders & Records",
                "<p>Open the Leaders and Records pages for seasonal highs, milestones, and record book context."
                " These views help narrative building and award discussions.</p>",
            ),
            TutorialStep(
                "League History",
                "<p>Use the History screen to review past seasons, playoff results, and award winners.</p>",
            ),
            TutorialStep(
                "Quick Navigation",
                "<p>The League sidebar links to stats, standings, leaders, and history. Keep it open while"
                " scouting other teams.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["league_hub"],
            "League Hub Tour",
            steps,
            force=force,
        )

    def show_reports_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Export Options",
                "<p>Admins can export league reports as HTML bundles by default, with optional CSV exports from the Admin utilities page.</p>",
            ),
            TutorialStep(
                "What Gets Exported",
                "<p>Exports include standings, team stats, leaderboards, and record books so owners can"
                " share snapshots offline.</p>",
            ),
            TutorialStep(
                "Where Files Go",
                "<p>Choose a destination folder when prompted. Keep exports in a shared drive if the league"
                " uses a common file hub.</p>",
            ),
            TutorialStep(
                "Best Practices",
                "<p>Run exports after major milestones like the All-Star break, playoffs, or season end for"
                " clean archival snapshots.</p>",
            ),
        ]
        self._run_tutorial(
            self._tutorial_keys["reports"],
            "Reports & Exports",
            steps,
            force=force,
        )

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
                "<p>Use the <b>Season</b> page for season flow controls: Season Progress,"
                " exhibition games, playoffs, schedule regeneration, and Opening Day reset."
                " Each action logs to the news feed and should be run once per phase.</p>",
            ),
            TutorialStep(
                "Transactions & Settings",
                "<p>Use <b>Transactions</b> to review pending trades, open Trade Settings,"
                " process owner change requests, and review pending GM Finance Queue decisions."
                " Use <b>League Settings</b> for league creation,"
                " tuning, and commissioner policy tools.</p>",
            ),
            TutorialStep(
                "Training Focus",
                "<p>Use the <b>Training Focus...</b> button on Season Progress to set league-wide hitter and pitcher"
                " allocations. Commissioners can balance defaults here before teams override them.</p>",
            ),
            TutorialStep(
                "Finance Workflow",
                "<p>Use <b>League Settings -> Financial System Settings</b> to control module levels."
                " Use the projection preview/alerts panel to validate cash/payroll risk."
                " Then use <b>Season -> Offseason Finance Workflow</b> to run and review contracts,"
                " arbitration, GM queue decisions, and budgets before owners continue in the Finance hub's"
                " <b>Owner Ops</b> and <b>GM/Coach Ops</b> tabs.</p>",
            ),
            TutorialStep(
                "Safety & Backups",
                "<p>Use <b>Assets &amp; Exports</b> for report/almanac/snapshot exports before destructive tasks like season resets."
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

        if is_owner_league():
            comm_password, ok = QInputDialog.getText(
                self,
                "Commissioner Access",
                "Enter commissioner password:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
            comm_password = comm_password.strip()
            if not verify_commissioner_password(comm_password):
                QMessageBox.warning(
                    self,
                    "Commissioner Access",
                    "Incorrect commissioner password.",
                )
                return

        self._open_admin_dashboard()

    def _validate_admin_password(self, password: str) -> bool:
        user_file = get_data_dir() / "users.txt"
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

        _track_admin_window(self._admin_window)
        show_on_top(self._admin_window)
        self._suppress_splash_on_close = True
        try:
            self.close()
        except Exception:
            pass

    def _register_pages(self) -> None:
        factories: Dict[str, Callable[[DashboardContext], QWidget]] = {
            "home": lambda ctx: OwnerHomePage(self),
            "roster": lambda ctx: RosterPage(self),
            "team": lambda ctx: TeamPage(self),
            "records": lambda ctx: TeamRecordsPage(self),
            "transactions": lambda ctx: TransactionsPage(self),
            "finance": lambda ctx: __import__(
                "ui.owner_finance_page", fromlist=["OwnerFinancePage"]
            ).OwnerFinancePage(self),
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
        self._on_nav_changed(key)
        if QTimer is not None and hasattr(QTimer, "singleShot"):
            QTimer.singleShot(0, lambda k=key: self._maybe_show_roster_tutorial(k))
        else:
            self._maybe_show_roster_tutorial(key)

    def _on_nav_changed(self, key: Optional[str]) -> None:
        self._refresh_change_request_ui_state()
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
            self._update_league_badge()
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
            self._reload_team_data()
        except Exception:
            pass
        try:
            self._update_status_bar()
        except Exception:
            pass
        try:
            self._update_league_badge()
        except Exception:
            pass
        try:
            self._update_header_context()
        except Exception:
            pass
        try:
            self._refresh_active_page()
        except Exception:
            pass
        try:
            self._maybe_notify_playoff_berth()
        except Exception:
            pass

    def _refresh_active_page(self) -> None:
        self._refresh_change_request_ui_state()
        page = None
        key = self._nav_controller.current_key
        if key is not None:
            page = self.pages.get(key)
        if page is None:
            try:
                page = self.stack.currentWidget()
            except Exception:
                page = None
        if page is None:
            return
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _reload_team_data(self) -> None:
        try:
            cache_clear = getattr(load_players_from_csv, "cache_clear", None)
            if callable(cache_clear):
                cache_clear("data/players.csv")
        except Exception:
            pass

    def _maybe_notify_playoff_berth(self) -> None:
        if not getattr(self, "team_id", None):
            return
        try:
            from playbalance.playoffs import load_bracket
        except Exception:
            return
        try:
            bracket = load_bracket()
        except Exception:
            return
        if bracket is None:
            return
        seeds = getattr(bracket, "seeds_by_league", {}) or {}
        if not seeds:
            return
        year = int(getattr(bracket, "year", 0) or 0)
        if year <= 0:
            return
        cur_date = get_current_sim_date()
        if cur_date:
            try:
                cur_year = int(str(cur_date).split("-")[0])
                if cur_year != year:
                    return
            except Exception:
                pass
        in_playoffs = False
        for league_seeds in seeds.values():
            for team in league_seeds or []:
                if getattr(team, "team_id", "") == self.team_id:
                    in_playoffs = True
                    break
            if in_playoffs:
                break
        if not in_playoffs:
            return

        progress_path = get_data_dir() / "season_progress.json"
        progress: Dict[str, Any] = {}
        try:
            if progress_path.exists():
                progress = json.loads(progress_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            progress = {}
        notified = progress.get("playoffs_berth_notified", {})
        if not isinstance(notified, dict):
            notified = {}
        year_key = str(year)
        notified_teams = notified.get(year_key, [])
        if not isinstance(notified_teams, list):
            notified_teams = []
        if self.team_id in notified_teams:
            return

        team_name = None
        if getattr(self, "team", None) is not None:
            try:
                label = f"{self.team.city} {self.team.name}".strip()
                team_name = label if label.strip() else None
            except Exception:
                team_name = None
        message_team = team_name or self.team_id
        QMessageBox.information(
            self,
            "Playoff Berth",
            f"Congratulations! {message_team} have clinched a postseason spot.",
        )

        notified_teams = [tid for tid in notified_teams if tid]
        if self.team_id not in notified_teams:
            notified_teams.append(self.team_id)
        notified[year_key] = notified_teams
        progress["playoffs_berth_notified"] = notified
        try:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text(json.dumps(progress, indent=2), encoding="utf-8")
        except Exception:
            pass
        try:
            cache_clear = getattr(load_roster, "cache_clear", None)
            if callable(cache_clear):
                cache_clear(team_id=self.team_id, roster_dir="data/rosters")
        except Exception:
            pass
        try:
            self.players = {
                p.player_id: p for p in load_players_from_csv("data/players.csv")
            }
        except Exception:
            pass
        try:
            self.roster = load_roster(self.team_id)
        except Exception:
            pass
        try:
            teams = load_teams()
            self.team = next((t for t in teams if t.team_id == self.team_id), None)
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

    def open_change_request_export_dialog(self) -> None:
        if not self.is_change_request_submission_available():
            QMessageBox.information(
                self,
                "Owner Change Requests",
                "Submit Change Request is only available in multi-owner leagues.",
            )
            return
        try:
            self.show_change_request_tutorial()
        except Exception:
            pass
        try:
            show_on_top(ChangeRequestExportDialog(self.team_id, self))
        except Exception:
            pass

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
            open_player_profile_dialog(player, self)
        except Exception:
            pass

    def open_reassign_players_dialog(self) -> None:
        show_on_top(ReassignPlayersDialog(self.players, self.roster, self))

    def open_transactions_page(self) -> None:
        show_on_top(TransactionsWindow(self.team_id))

    def open_trade_dialog(self) -> None:
        show_on_top(TradeDialog(self.team_id, self))

    def open_free_agency_hub(self) -> None:
        show_on_top(FreeAgencyWindow(self))

    def open_finance_hub(self) -> None:
        self._go("finance")

    def open_finance_snapshot(self) -> None:
        # Backward-compatible alias for older callback wiring.
        self.open_finance_hub()

    def open_roster_page(self) -> None:
        """Switch the main view to the roster page."""
        self._go("roster")

    def sign_free_agent(self) -> None:
        try:
            free_agents = find_free_agents(self.players.values(), "data/rosters")
            if not free_agents:
                QMessageBox.information(self, "Free Agents", "No free agents available to sign.")
                return
            player = free_agents[0]
            pid = str(getattr(player, "player_id", "") or "").strip()
            if not pid:
                QMessageBox.warning(self, "Free Agents", "Selected player is missing an id.")
                return
            if pid in self.roster.act:
                QMessageBox.information(self, "Free Agents", f"{pid} is already on your active roster.")
                return
            estimated_salary = int(estimate_salary_for_player(player))
            policy = evaluate_free_agent_signing(
                self.team_id,
                annual_salary=estimated_salary,
                player=player,
            )
            if not policy.allowed:
                record_payroll_policy_result(
                    policy,
                    action="owner_sign_free_agent",
                    data_dir=get_data_dir(),
                )
                QMessageBox.warning(
                    self,
                    "Payroll Policy Blocked",
                    format_payroll_policy_message(policy),
                )
                return
            if policy.warning:
                record_payroll_policy_result(
                    policy,
                    action="owner_sign_free_agent",
                    data_dir=get_data_dir(),
                )
            player_name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip() or pid
            summary = (
                f"Sign {player_name} ({pid})?\n"
                f"Estimated annual salary: ${estimated_salary:,}\n\n"
                f"{format_payroll_policy_message(policy)}"
            )
            if policy.warning:
                proceed = QMessageBox.question(
                    self,
                    "Payroll Policy Warning",
                    summary + "\n\nProceed anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return
            else:
                proceed = QMessageBox.question(
                    self,
                    "Confirm Free-Agent Signing",
                    summary,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if proceed != QMessageBox.StandardButton.Yes:
                    return
            self.roster.act.append(pid)
            save_roster(self.team_id, self.roster)
            sign_free_agent_contract(pid, self.team_id, player=player)
            try:
                data_dir = get_data_dir()
                auto_reassign_team_if_enabled(
                    self.team_id,
                    players_file=data_dir / "players.csv",
                    roster_dir=data_dir / "rosters",
                    data_dir=data_dir,
                )
                self.roster = load_roster(self.team_id)
            except Exception:
                pass
            QMessageBox.information(self, "Free Agents", f"Signed free agent: {pid}")
            try:
                self._refresh_active_page()
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to sign free agent: {e}")

    def open_standings_window(self) -> None:
        show_on_top(StandingsWindow(self))

    def open_schedule_window(self) -> None:
        show_on_top(ScheduleWindow(self))

    def open_league_command_center(self) -> None:
        show_on_top(LeagueCommandCenterWindow(self))

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
                allow_progress_actions=self._season_progress_allowed,
                progress_block_reason=self._season_progress_block_reason,
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
                self._reload_team_data()
            except Exception:
                pass
            try:
                self._update_status_bar()
            except Exception:
                pass
            try:
                self._update_header_context()
            except Exception:
                pass
            try:
                self._refresh_active_page()
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

    def open_draft_results_window(self) -> None:
        show_on_top(DraftResultsDialog(self))

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

            sched = get_data_dir() / "schedule.csv"
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

        base = get_data_dir()
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

    def open_playoffs_window(self) -> None:
        existing = getattr(self, "_playoffs_win", None)
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return
        except Exception:
            self._playoffs_win = None

        try:
            self._playoffs_win = PlayoffsWindow(
                self,
                run_async=self._context.run_async,
                show_toast=self._context.show_toast,
                register_cleanup=self._context.register_cleanup,
            )
            self._playoffs_win.show()
            self._playoffs_win.raise_()
            self._playoffs_win.activateWindow()
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
                set_team_strategy_profile(
                    self.team.team_id,
                    data.get("strategy_profile_override"),
                )
                set_team_auto_reassign(
                    self.team.team_id,
                    data.get("auto_reassign_override"),
                )
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

    def import_league_snapshot(self) -> None:
        from services.league_snapshot import import_league_snapshot

        start_dir = get_data_dir() / "exports"
        if not start_dir.exists():
            start_dir = get_data_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import League Snapshot",
            str(start_dir),
            "League Snapshot (*.zip)",
        )
        if not path:
            return
        result = import_league_snapshot(Path(path))
        status = result.get("status")
        if status != "success":
            message = result.get("message", "Import failed.")
            QMessageBox.warning(self, "Import League Snapshot", str(message))
            return
        backup = result.get("backup_path", "")
        QMessageBox.information(
            self,
            "Import Complete",
            "League snapshot imported successfully.\n"
            f"Backup saved at:\n{backup}\n\n"
            "Please restart the app to load updated league data.",
        )

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
                base_path=get_data_dir(),
                roster=self.roster,
                players=self.players,
            )
        except Exception:
            metrics = {}
        self._latest_metrics = metrics
        return metrics

    def get_draft_notice(self) -> Dict[str, object]:
        available, cur_date, draft_date, _completed = self._draft_availability_details()
        if not available:
            return {"visible": False}
        if draft_date and cur_date:
            message = f"Draft is ready. Draft Day: {draft_date}. Current date: {cur_date}."
        elif draft_date:
            message = f"Draft is ready. Draft Day: {draft_date}."
        else:
            message = "Draft is ready."
        return {"visible": True, "message": message}

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
        avg_budget_pct = bullpen.get("avg_available_pct")
        try:
            avg_budget_text = f"{float(avg_budget_pct) * 100:.0f}%"
        except (TypeError, ValueError):
            avg_budget_text = "--"
        bp_summary = (
            f"{bp_ready}/{bp_total} ({avg_budget_text})" if bp_total else "--"
        )
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

    def _update_league_badge(self) -> None:
        active = league_registry.get_active_league()
        league_name = active.display_name if active is not None else "Unknown"
        try:
            self.league_badge.setText(f"League: {league_name}")
        except Exception:
            pass
        try:
            self.setWindowTitle(f"Owner Dashboard - {self.team_id} ({league_name})")
        except Exception:
            pass
