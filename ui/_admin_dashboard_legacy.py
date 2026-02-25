"""Admin dashboard window using modern navigation.

This module restructures the legacy admin dashboard to follow the layout
demonstrated in :mod:`ui_template`.  Navigation is handled through a sidebar
of :class:`NavButton` controls which swap pages in a :class:`QStackedWidget`.
Each page groups related actions inside a :class:`Card` with a small section
header provided by :func:`section_title`.

Only the user interface wiring has changed - the underlying callbacks are the
same routines that existed in the previous tab based implementation.  The goal
is to keep behaviour intact while presenting a cleaner API for future
expansion.
"""

from __future__ import annotations

from typing import Callable, Dict

from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .components import NavButton
from .ui_template import _load_baseball_pixmap, _NAV_ICON_MAP, _load_nav_icon
from .admin_dashboard.navigation import NavigationController, PageRegistry
from .admin_dashboard.context import DashboardContext
from .admin_dashboard.actions import (
    add_user_action,
    auto_reassign_rosters as auto_reassign_rosters_action,
    create_league_action,
    edit_user_action,
    export_reports_action,
    generate_player_avatars_action,
    generate_team_logos_action,
    reset_season_to_opening_day,
    review_pending_trades,
    set_all_lineups as set_all_lineups_action,
    set_all_pitching_roles as set_all_pitching_roles_action,
)
from .admin_dashboard.actions.league import regenerate_schedule_action
from .admin_dashboard.pages import (
    DraftPage,
    LeagueSettingsPage,
    SeasonPage,
    TeamsPage,
    TransactionsPage,
    UsersPage,
    UtilitiesPage,
)
from .admin_home_page import AdminHomePage
from ui.window_utils import show_on_top
from ui.sim_date_bus import sim_date_bus
from . import theme as app_theme
from .exhibition_game_dialog import ExhibitionGameDialog
from .playbalance_editor import PlayBalanceEditor
from playbalance.draft_config import load_draft_config, save_draft_config
from .season_progress_window import SeasonProgressWindow
from .playoffs_window import PlayoffsWindow
from .free_agency_window import FreeAgencyWindow
from .news_window import NewsWindow
from .injury_center_window import InjuryCenterWindow
from .injury_settings_dialog import InjurySettingsDialog
from .hall_of_fame_settings_dialog import HallOfFameSettingsDialog
from .trade_settings_dialog import TradeSettingsDialog
from .financial_settings_dialog import FinancialSettingsDialog
from .finance_stability_dialog import FinanceStabilityDialog
from .offseason_finance_dialog import OffseasonFinanceDialog
from .gm_finance_queue_dialog import GmFinanceQueueDialog
from .league_manager_dialog import LeagueManagerDialog
from .avatar_tutorial_dialog import AvatarTutorialDialog
from .logo_tutorial_dialog import LogoTutorialDialog
from .manual_viewer_dialog import (
    DOC_FINANCE_MANUAL,
    DOC_GAME_MANUAL,
    ManualViewerDialog,
)
from .tutorial_dialog import TutorialDialog, TutorialStep
from .league_history_window import LeagueHistoryWindow
from .change_requests_window import ChangeRequestsWindow
from .owner_dashboard import OwnerDashboard
from services.gm_finance_queue import summarize_queue_decisions
from services import league_lifecycle, league_registry
from utils.trade_utils import load_trades
from utils.league_settings import is_owner_league, load_league_settings
from utils.player_loader import load_players_from_csv
from utils.team_loader import load_teams
from utils.path_utils import get_base_dir, get_data_dir
from utils.sim_date import get_current_sim_date
from ui.version_badge import enable_version_badge
from .theme_assets import load_enhanced_nav_icon

_OPEN_OWNER_DASHBOARDS: list[OwnerDashboard] = []


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
    legacy = getattr(app_theme, "_toggle_theme", None)
    if callable(legacy):
        legacy(status_bar)


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


def _track_owner_dashboard(dashboard: OwnerDashboard) -> None:
    _OPEN_OWNER_DASHBOARDS.append(dashboard)

    def _remove(*_args, dash=dashboard) -> None:
        try:
            _OPEN_OWNER_DASHBOARDS.remove(dash)
        except ValueError:
            pass

    try:
        dashboard.destroyed.connect(_remove)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Administration console for commissioners."""

    def __init__(self) -> None:
        super().__init__()
        enable_version_badge(self)
        self.setWindowTitle("Admin Dashboard")
        self.resize(1000, 700)

        self.team_dashboards: list[OwnerDashboard] = []
        self._cleanup_callbacks: list[Callable[[], None]] = []
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._context = DashboardContext(
            base_path=get_data_dir(),
            run_async=lambda work: self._executor.submit(work),
            register_cleanup=self._cleanup_callbacks.append,
        )

        if not hasattr(self, "_page_registry"):
            self._page_registry = PageRegistry()
        if not hasattr(self, "_navigation"):
            self._navigation = NavigationController(self._page_registry)

        # sidebar ---------------------------------------------------------
        sidebar = QWidget(objectName="Sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 12, 10, 12)
        side.setSpacing(6)

        brand_icon = QLabel()
        icon_size = 40
        baseball = _load_baseball_pixmap(icon_size)
        if not baseball.isNull():
            brand_icon.setPixmap(baseball)
        brand_icon.setFixedSize(icon_size, icon_size)

        brand_text = QLabel("Commissioner")
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

        self.btn_dashboard = NavButton("  Dashboard")
        self.btn_transactions = NavButton("  Transactions")
        self.btn_season = NavButton("  Season")
        self.btn_draft = NavButton("  Draft")
        self.btn_teams = NavButton("  Teams")
        self.btn_users = NavButton("  Users")
        self.btn_settings = NavButton("  League Settings")
        self.btn_utils = NavButton("  Assets & Exports")
        for b in (
            self.btn_dashboard,
            self.btn_transactions,
            self.btn_season,
            self.btn_draft,
            self.btn_teams,
            self.btn_users,
            self.btn_settings,
            self.btn_utils,
        ):
            side.addWidget(b)
        side.addStretch()

        self.nav_buttons = {
            "dashboard": self.btn_dashboard,
            "transactions": self.btn_transactions,
            "season": self.btn_season,
            "draft": self.btn_draft,
            "teams": self.btn_teams,
            "users": self.btn_users,
            "settings": self.btn_settings,
            "utils": self.btn_utils,
        }
        self._nav_icon_size = QSize(24, 24)
        self._nav_tooltips = {
            "dashboard": "League overview and urgent queues",
            "transactions": "Trades, approvals, and owner-change processing",
            "season": "Season simulation, schedule, and reset controls",
            "draft": "Amateur Draft console and settings",
            "teams": "Open team dashboards and bulk actions",
            "users": "Manage accounts and roles",
            "settings": "League setup and policy configuration",
            "utils": "Asset generation and exports",
        }
        self._refresh_nav_icons()

        # header + stacked pages -----------------------------------------
        header = QWidget(objectName="Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.addWidget(QLabel("Admin Dashboard", objectName="Title"))
        h.addStretch()
        self._league_badge = QLabel("League: -")
        self._league_badge.setObjectName("Scoreboard")
        self._league_selector = QComboBox()
        self._league_selector.setMinimumWidth(220)
        self._league_selector.setToolTip("Switch active league")
        self._league_selector.currentIndexChanged.connect(self._on_league_selector_changed)
        h.addWidget(self._league_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self._league_selector, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.stack = QStackedWidget()
        factories = self._page_factories()
        self.pages: Dict[str, QWidget] = {}
        for key, factory in factories.items():
            try:
                if (
                    getattr(self, "_page_registry", None) is not None
                    and hasattr(self._page_registry, "register")
                ):
                    try:
                        self._page_registry.register(key, factory)
                    except KeyError:
                        pass
                page = factory(self._context)
            except Exception:
                continue
            self.pages[key] = page
            self.stack.addWidget(page)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(header)
        rv.addWidget(self.stack)

        # root layout -----------------------------------------------------
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(sidebar)
        root.addWidget(right)
        root.setStretchFactor(right, 1)

        self.setCentralWidget(central)
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        def _toast(kind: str, message: str) -> None:
            prefix = {"info": "?", "success": "?", "error": "?"}.get(kind, "")
            status_bar.showMessage(f"{prefix} {message}".strip(), 5000)

        self._context = self._context.with_overrides(show_toast=_toast)
        self._sim_date_bus = sim_date_bus()
        try:
            self._sim_date_bus.dateChanged.connect(self._on_sim_date_changed)
        except Exception:
            pass

        self._admin_tutorial_keys = {
            "overview": "admin_tutorial_overview",
            "appearance": "admin_tutorial_appearance",
            "league_setup": "admin_tutorial_league_setup",
            "users": "admin_tutorial_users",
            "season_progression": "admin_tutorial_season_progression",
            "transactions": "admin_tutorial_transactions",
            "exports": "admin_tutorial_exports",
        }
        self._admin_tutorial_flags = self._load_admin_tutorial_flags()
        self._admin_tutorial_dialog_open = False

        # menu ------------------------------------------------------------
        self._build_menu()
        self._refresh_theme_ui()

        # signals ---------------------------------------------------------
        # navigation wiring -------------------------------------------------
        navigation = getattr(self, "_navigation", None)
        for key, button in self.nav_buttons.items():
            if navigation is not None and hasattr(navigation, "set_current"):
                button.clicked.connect(lambda _, k=key: navigation.set_current(k))
            else:
                button.clicked.connect(lambda _, k=key: self._on_navigation_changed(k))
        if navigation is not None and hasattr(navigation, "add_listener"):
            navigation.add_listener(self._on_navigation_changed)

        # connect page buttons to actions
        tx = self.pages.get("transactions")
        if isinstance(tx, TransactionsPage):
            tx.review_button.clicked.connect(self.open_trade_review)
            tx.trade_settings_button.clicked.connect(self.open_trade_settings)
            tx.change_requests_button.clicked.connect(self.open_change_requests_window)
            tx.gm_finance_queue_button.clicked.connect(self.open_gm_finance_queue_review)

        season_page = self.pages.get("season")
        if isinstance(season_page, SeasonPage):
            season_page.exhibition_button.clicked.connect(self.open_exhibition_dialog)
            season_page.season_progress_button.clicked.connect(self.open_season_progress)
            season_page.playoffs_view_button.clicked.connect(self.open_playoffs_window)
            season_page.regenerate_schedule_button.clicked.connect(self.regenerate_regular_season_schedule)
            season_page.reset_opening_day_button.clicked.connect(self.reset_to_opening_day)
            season_page.league_history_button.clicked.connect(self.open_league_history)
            season_page.offseason_finance_button.clicked.connect(self.open_offseason_finance_workflow)

        settings = self.pages.get("settings")
        if isinstance(settings, LeagueSettingsPage):
            settings.create_league_button.clicked.connect(self.open_create_league)
            settings.league_manager_button.clicked.connect(self.open_league_manager)
            settings.playbalance_button.clicked.connect(self.open_playbalance_editor)
            settings.injury_center_button.clicked.connect(self.open_injury_center)
            settings.injury_settings_button.clicked.connect(self.open_injury_settings)
            settings.financial_settings_button.clicked.connect(self.open_financial_settings)
            settings.finance_stability_button.clicked.connect(self.open_finance_stability)
            settings.free_agency_hub_button.clicked.connect(self.open_free_agency)
            settings.hall_of_fame_settings_button.clicked.connect(self.open_hall_of_fame_settings)

        dp = self.pages.get("draft")
        if isinstance(dp, DraftPage):
            dp.view_draft_pool_button.clicked.connect(self.open_draft_pool)
            dp.start_resume_draft_button.clicked.connect(self.open_draft_console)
            dp.view_results_button.clicked.connect(self.open_draft_results)
            dp.draft_settings_button.clicked.connect(self.open_draft_settings)

        tp = self.pages.get("teams")
        if isinstance(tp, TeamsPage):
            tp.team_dashboard_button.clicked.connect(self.open_team_dashboard)
            tp.set_lineups_button.clicked.connect(self.set_all_lineups)
            tp.set_pitching_button.clicked.connect(self.set_all_pitching_roles)
            tp.auto_reassign_button.clicked.connect(self.auto_reassign_rosters)

        up = self.pages.get("users")
        if isinstance(up, UsersPage):
            up.add_user_button.clicked.connect(self.open_add_user)
            up.edit_user_button.clicked.connect(self.open_edit_user)

        util = self.pages.get("utils")
        if isinstance(util, UtilitiesPage):
            util.generate_logos_button.clicked.connect(self.generate_team_logos)
            util.logo_tutorial_button.clicked.connect(self.open_logo_tutorial)
            util.generate_avatars_button.clicked.connect(self.generate_player_avatars)
            util.avatar_tutorial_button.clicked.connect(self.open_avatar_tutorial)

        # default page
        try:
            if navigation is not None and hasattr(navigation, "set_current"):
                navigation.set_current("dashboard")
            elif self.pages:
                self._on_navigation_changed(next(iter(self.pages)))
        except Exception:
            pass
        self._refresh_league_header()
        if QTimer:
            QTimer.singleShot(400, self._maybe_auto_show_admin_tutorials)
        else:
            self._maybe_auto_show_admin_tutorials()

    def _build_dashboard_page(self, page_cls: type[QWidget]) -> Callable[[DashboardContext], QWidget]:
        def factory(context: DashboardContext) -> QWidget:
            page = page_cls()
            attach = getattr(page, "attach", None)
            if callable(attach):
                try:
                    attach(context)
                except Exception:
                    pass
            return page

        return factory

    def _page_factories(self) -> Dict[str, Callable[[DashboardContext], QWidget]]:
        return {
            "dashboard": lambda ctx: AdminHomePage(self),
            "transactions": self._build_dashboard_page(TransactionsPage),
            "season": self._build_dashboard_page(SeasonPage),
            "draft": self._build_dashboard_page(DraftPage),
            "teams": self._build_dashboard_page(TeamsPage),
            "users": self._build_dashboard_page(UsersPage),
            "settings": self._build_dashboard_page(LeagueSettingsPage),
            "utils": self._build_dashboard_page(UtilitiesPage),
        }

    # ------------------------------------------------------------------
    # Menu and navigation helpers
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
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

        tutorials_menu = self.menuBar().addMenu("&Tutorials")

        def _add_tutorial_action(
            menu: object,
            label: str,
            callback: Callable[..., None],
        ) -> None:
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, cb=callback: cb(force=True)
            )
            menu.addAction(action)  # type: ignore[attr-defined]

        workflows_menu = tutorials_menu.addMenu("Commissioner Workflows")
        workflow_entries = [
            ("Admin Dashboard Overview", self.show_admin_dashboard_overview_tutorial),
            ("Appearance & Themes", self.show_admin_theme_tutorial),
            ("League Setup & Manager", self.show_admin_league_setup_tutorial),
            ("User Management & Roles", self.show_admin_user_management_tutorial),
            ("Season Progression Flow", self.show_admin_season_progression_tutorial),
            ("Trade & Review Queues", self.show_admin_transaction_queues_tutorial),
            ("Exports & Utilities", self.show_admin_exports_utilities_tutorial),
        ]
        for action_label, callback in workflow_entries:
            _add_tutorial_action(workflows_menu, action_label, callback)

        assets_menu = tutorials_menu.addMenu("Asset Guides")
        logo_tutorial_action = QAction("Team Logo Tutorial", self)
        logo_tutorial_action.triggered.connect(self.open_logo_tutorial)
        assets_menu.addAction(logo_tutorial_action)
        avatar_tutorial_action = QAction("Player Avatar Tutorial", self)
        avatar_tutorial_action.triggered.connect(self.open_avatar_tutorial)
        assets_menu.addAction(avatar_tutorial_action)

        game_manual_action = QAction("Complete Game Manual", self)
        game_manual_action.triggered.connect(self.open_game_manual)
        manuals_menu = tutorials_menu.addMenu("Reference Manuals")
        manuals_menu.addAction(game_manual_action)
        finance_manual_action = QAction("Finance System Manual", self)
        finance_manual_action.triggered.connect(self.open_finance_manual)
        manuals_menu.addAction(finance_manual_action)

    def _set_theme_family(self, family: str) -> None:
        _set_theme_family(family, self.statusBar())
        self._refresh_theme_ui()

    def _toggle_theme_mode(self) -> None:
        _toggle_theme_mode(self.statusBar())
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
        self.statusBar().showMessage(
            self._status_with_date(
                f"Theme: {_theme_label(family)} {mode_label}"
            ),
            3000,
        )

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
                icon_name = _NAV_ICON_MAP.get(key)
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
            tooltip = self._nav_tooltips.get(key)
            if tooltip:
                button.setToolTip(tooltip)

    def _load_admin_tutorial_flags(self) -> dict[str, bool]:
        try:
            import json

            path = get_base_dir() / "config" / "admin_tutorial_flags.json"
            if not path.exists():
                return {}
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {str(key): bool(value) for key, value in payload.items()}
        except Exception:
            pass
        return {}

    def _save_admin_tutorial_flags(self) -> None:
        try:
            import json

            config_dir = get_base_dir() / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            path = config_dir / "admin_tutorial_flags.json"
            path.write_text(
                json.dumps(self._admin_tutorial_flags, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _run_admin_tutorial(
        self,
        key: str,
        title: str,
        steps: list[TutorialStep],
        *,
        force: bool = False,
    ) -> None:
        if not force and self._admin_tutorial_flags.get(key):
            return
        if self._admin_tutorial_dialog_open:
            return
        self._admin_tutorial_dialog_open = True
        try:
            dialog = TutorialDialog(title=title, steps=steps, parent=self)
            dialog.exec()
        finally:
            self._admin_tutorial_dialog_open = False
            if not force:
                self._admin_tutorial_flags[key] = True
                self._save_admin_tutorial_flags()

    def show_admin_dashboard_overview_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Dashboard Home",
                "<p>Start on <b>Dashboard</b> to check pending trades, draft timing, GM finance queue pressure, "
                "and league health before running admin actions.</p>",
            ),
            TutorialStep(
                "Core Navigation",
                "<p>Use left-nav pages for domain-specific work: <b>Transactions</b>, <b>Season</b>, "
                "<b>Draft</b>, <b>Teams</b>, <b>Users</b>, <b>League Settings</b>, and <b>Assets &amp; Exports</b>.</p>",
            ),
            TutorialStep(
                "On-Demand Help",
                "<p>Open <b>Tutorials -> Commissioner Workflows</b> any time to replay focused walkthroughs "
                "for setup, progression, queues, and export workflows.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["overview"],
            "Admin Dashboard Overview",
            steps,
            force=force,
        )

    def show_admin_theme_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Theme Family Selection",
                "<p>Open <b>View -> Theme Family</b> to switch between <b>Classic</b> and "
                "<b>Enhanced Warm</b> while keeping the same workflows.</p>",
            ),
            TutorialStep(
                "Light and Dark Modes",
                "<p>Use <b>View -> Toggle Light/Dark</b> to change brightness without changing families.</p>",
            ),
            TutorialStep(
                "Saved Preference",
                "<p>The selected family and mode are saved automatically and restored on next launch.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["appearance"],
            "Appearance & Themes",
            steps,
            force=force,
        )

    def show_admin_league_setup_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Create and Register Leagues",
                "<p>Open <b>League Settings -> Create League</b> to build structure, schedule template, "
                "and league mode. This action sets active league context and base policy files.</p>",
            ),
            TutorialStep(
                "Switch and Archive",
                "<p>Use <b>League Settings -> League Manager</b> to switch active leagues, archive old saves, "
                "or restore archived leagues during migration and testing cycles.</p>",
            ),
            TutorialStep(
                "Policy Baseline",
                "<p>Before season start, review <b>Trade Settings</b>, <b>Financial System Settings</b>, "
                "<b>Injury Settings</b>, and <b>Hall of Fame Settings</b> to lock commissioner defaults.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["league_setup"],
            "League Setup & Manager",
            steps,
            force=force,
        )

    def show_admin_user_management_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "User Directory",
                "<p>Open <b>Users</b> to search and audit account role/team assignments before each major phase.</p>",
            ),
            TutorialStep(
                "Add and Edit Accounts",
                "<p>Use <b>Add User</b> for new owners/admins and <b>Edit User</b> for role corrections, "
                "team reassignment, and password recovery workflows.</p>",
            ),
            TutorialStep(
                "Role Safety",
                "<p>Reserve commissioner permissions for trusted admins only. In multi-owner leagues, "
                "commissioner permissions control season progression and queue approvals.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["users"],
            "User Management & Roles",
            steps,
            force=force,
        )

    def show_admin_season_progression_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Season Progress Window",
                "<p>Open <b>Season -> Open Season Progress</b> for day/series simulation, phase transitions, "
                "training camp, and free-agency progression controls.</p>",
            ),
            TutorialStep(
                "Schedule and Reset Controls",
                "<p>Use <b>Regenerate Season Schedule</b> and <b>Reset to Opening Day</b> carefully. "
                "Run exports first and notify owners before destructive actions.</p>",
            ),
            TutorialStep(
                "Playoff and Archive Checks",
                "<p>Use <b>Open Playoffs Viewer</b> for bracket progression checks and <b>League History</b> "
                "to validate archived outcomes after phase rollovers.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["season_progression"],
            "Season Progression Flow",
            steps,
            force=force,
        )

    def show_admin_transaction_queues_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Trade Review Queue",
                "<p>Open <b>Transactions -> Review Pending Trades</b> to process commissioner approvals and "
                "owner-accepted deals waiting for execution.</p>",
            ),
            TutorialStep(
                "Owner Change Requests",
                "<p>Use <b>Review Change Requests</b> to import owner ZIP bundles, inspect diffs, and approve "
                "or reject submissions with notes.</p>",
            ),
            TutorialStep(
                "GM Finance Queue",
                "<p>Open <b>Review GM Finance Queue</b> in multi-owner leagues to finalize pending arbitration/"
                "free-agency decisions before advancing phases.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["transactions"],
            "Trade & Review Queues",
            steps,
            force=force,
        )

    def show_admin_exports_utilities_tutorial(self, *, force: bool = False) -> None:
        steps = [
            TutorialStep(
                "Reports and Snapshot Exports",
                "<p>Open <b>Assets &amp; Exports</b> and run <b>Export Reports</b> or "
                "<b>Export Owner Snapshot Zip</b> to distribute league state safely.</p>",
            ),
            TutorialStep(
                "Asset Generation",
                "<p>Generate team logos and player avatars from the same page. Use logo/avatar tutorial entries "
                "for image pipeline conventions and prompt standards.</p>",
            ),
            TutorialStep(
                "Operational Habit",
                "<p>Run exports before major sim/regression steps so rollback artifacts are available for "
                "commissioners and remote owners.</p>",
            ),
        ]
        self._run_admin_tutorial(
            self._admin_tutorial_keys["exports"],
            "Exports & Utilities",
            steps,
            force=force,
        )

    def _maybe_auto_show_admin_tutorials(self) -> None:
        self.show_admin_dashboard_overview_tutorial()

    def _status_with_date(self, base: str) -> str:
        date_str = get_current_sim_date()
        if date_str:
            return f"{base} | Date: {date_str}"
        return base

    def _refresh_league_header(self) -> None:
        records = [
            item
            for item in league_registry.list_leagues()
            if item.status != "archived"
        ]
        active = league_registry.get_active_league()
        active_id = active.id if active is not None else ""
        active_name = active.display_name if active is not None else "None"
        self._league_badge.setText(f"League: {active_name}")
        self.setWindowTitle(f"Admin Dashboard - {active_name}")

        self._league_selector.blockSignals(True)
        self._league_selector.clear()
        selected_index = -1
        for idx, record in enumerate(records):
            self._league_selector.addItem(record.display_name, record.id)
            if record.id == active_id:
                selected_index = idx
        if selected_index >= 0:
            self._league_selector.setCurrentIndex(selected_index)
        self._league_selector.setVisible(bool(records))
        self._league_selector.blockSignals(False)

    def _on_league_selector_changed(self, _index: int) -> None:
        league_id = self._league_selector.currentData()
        if not isinstance(league_id, str) or not league_id:
            return
        current = league_registry.get_active_league()
        if current is not None and current.id == league_id:
            return
        try:
            selected = league_lifecycle.switch_active_league(league_id)
            self._context = self._context.with_overrides(base_path=get_data_dir())
        except Exception as exc:
            QMessageBox.warning(self, "League Switch", f"Unable to switch league: {exc}")
            self._refresh_league_header()
            return
        self._refresh_league_header()
        self._refresh_date_status()
        QMessageBox.information(
            self,
            "League Switched",
            (
                f'Active league switched to "{selected.display_name}".\n'
                "Close and reopen any already-open windows if data appears stale."
            ),
        )

    def _on_sim_date_changed(self, _value: object) -> None:
        """Refresh status and active page when the sim date advances."""

        try:
            QTimer.singleShot(0, self._refresh_date_status)
        except Exception:
            self._refresh_date_status()

    def _go(self, key: str) -> None:
        if key == "league":
            key = "season"
        try:
            self._navigation.set_current(key)
        except KeyError:
            pass

    def _on_navigation_changed(self, key: str | None) -> None:
        if not key:
            return
        if key == "league":
            key = "season"
        for btn in self.nav_buttons.values():
            try:
                btn.setChecked(False)
            except Exception:
                pass
        btn = self.nav_buttons.get(key)
        if btn:
            try:
                btn.setChecked(True)
            except Exception:
                pass
        try:
            idx = list(self.pages.keys()).index(key)
            self.stack.setCurrentIndex(idx)
        except ValueError:
            return
        self.statusBar().showMessage(self._status_with_date(f"Ready - {key.capitalize()}"))
        try:
            page = self.pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()  # type: ignore[attr-defined]
        except Exception:
            pass
        if key == "draft":
            self._refresh_draft_page()

    def closeEvent(self, event) -> None:
        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception:
                pass
        try:
            if hasattr(self, "_sim_date_bus"):
                self._sim_date_bus.dateChanged.disconnect(self._on_sim_date_changed)
        except Exception:
            pass
        self._executor.shutdown(wait=False)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Dashboard metrics helper
    # ------------------------------------------------------------------
    def get_admin_metrics(self) -> dict:
        """Return a small set of overview metrics for the Admin home page."""
        data_dir = get_data_dir()
        # Counts
        try:
            # Match the team list shown in the Standings window, which relies
            # on load_teams(data/teams.csv).
            teams = load_teams(data_dir / "teams.csv")
            team_count = len(teams)
        except Exception:
            team_count = 0
        try:
            players = load_players_from_csv(data_dir / "players.csv")
            player_count = len(players)
        except Exception:
            player_count = 0
        # Pending trades
        try:
            pending = sum(
                1
                for t in load_trades()
                if getattr(t, "status", "") in {"pending", "owner_accepted"}
            )
        except Exception:
            pending = 0
        # Season phase (best-effort)
        try:
            from playbalance.season_manager import SeasonManager
            phase = str(SeasonManager().phase.name)
        except Exception:
            phase = "Unknown"
        # Draft day and status
        try:
            available, cur_date, draft_date, completed = self._draft_availability_details()
            status = "Completed" if completed else ("Ready" if available else "Not yet")
        except Exception:
            draft_date, status = None, None
        try:
            queue_summary = summarize_queue_decisions(data_dir=data_dir)
        except Exception:
            queue_summary = {}
        try:
            league_settings = load_league_settings(data_dir / "league_settings.json")
            queue_required = bool(is_owner_league(league_settings))
        except Exception:
            queue_required = False
        return {
            "teams": team_count,
            "players": player_count,
            "pending_trades": pending,
            "season_phase": phase,
            "draft_day": draft_date,
            "draft_status": status,
            "gm_queue_required": queue_required,
            "gm_queue_total": int(queue_summary.get("total", 0) or 0),
            "gm_queue_pending": int(queue_summary.get("pending", 0) or 0),
            "gm_queue_approved_unapplied": int(
                queue_summary.get("approved_unapplied", 0) or 0
            ),
        }


    # ------------------------------------------------------------------
    # Existing behaviours
    # ------------------------------------------------------------------

    # The methods below are largely unchanged from the original
    # implementation.  They provide the actual behaviour for the various
    # buttons defined on the dashboard pages.

    def open_trade_review(self) -> None:
        review_pending_trades(self._context, self)


    def generate_team_logos(self) -> None:
        generate_team_logos_action(self._context, self)


    def open_logo_tutorial(self) -> None:
        try:
            dialog = LogoTutorialDialog(self)
            dialog.exec()
        except Exception:
            pass


    def generate_player_avatars(self) -> None:
        generate_player_avatars_action(self._context, self)

    def open_avatar_tutorial(self) -> None:
        try:
            dialog = AvatarTutorialDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_game_manual(self) -> None:
        self._open_manual(doc_id=DOC_GAME_MANUAL)

    def open_finance_manual(self) -> None:
        self._open_manual(doc_id=DOC_FINANCE_MANUAL)

    def _open_manual(self, *, doc_id: str) -> None:
        try:
            dialog = ManualViewerDialog(initial_doc_id=doc_id, parent=self)
            dialog.exec()
        except Exception:
            pass

    def export_reports(self) -> None:
        export_reports_action(self._context, self)


    def open_add_user(self) -> None:
        refresh = None
        try:
            users_page = self.pages.get('users')
            if users_page is not None and hasattr(users_page, 'refresh'):
                refresh = users_page.refresh
        except Exception:
            refresh = None
        add_user_action(self._context, self, refresh)


    def open_edit_user(self) -> None:
        refresh = None
        selected = None
        try:
            users_page = self.pages.get('users')
            if users_page is not None:
                selected = getattr(users_page, 'selected_username', None)
                if hasattr(users_page, 'refresh'):
                    refresh = users_page.refresh
        except Exception:
            selected = None
            refresh = None
        edit_user_action(self._context, self, selected, refresh)


    def open_team_dashboard(self) -> None:
        teams = load_teams(get_data_dir() / "teams.csv")
        team_ids = [t.team_id for t in teams]
        if not team_ids:
            QMessageBox.information(self, "No Teams", "No teams available.")
            return
        # Prefer selected value from TeamsPage if available
        selected = None
        try:
            tp = self.pages.get("teams")
            if tp is not None and getattr(tp, "team_select", None) is not None:
                cur = tp.team_select.currentText().strip()
                if cur:
                    selected = cur
        except Exception:
            selected = None
        team_id = None
        if selected and selected in team_ids:
            team_id = selected
        else:
            team_id, ok = QInputDialog.getItem(
                self, "Open Team Dashboard", "Select a team:", team_ids, 0, False
            )
            if not ok:
                return
        if team_id:
            dashboard = OwnerDashboard(team_id, actor_role="commissioner")
            show_on_top(dashboard)
            self.team_dashboards.append(dashboard)
            _track_owner_dashboard(dashboard)
            try:
                self.close()
            except Exception:
                pass

    def set_all_lineups(self) -> None:
        set_all_lineups_action(self._context, self)


    def set_all_pitching_roles(self) -> None:
        set_all_pitching_roles_action(self._context, self)


    def auto_reassign_rosters(self) -> None:
        auto_reassign_rosters_action(self._context, self)


    def open_create_league(self) -> None:
        callbacks = []
        try:
            teams_page = self.pages.get('teams')
            if teams_page is not None and hasattr(teams_page, 'refresh'):
                callbacks.append(teams_page.refresh)
        except Exception:
            pass
        try:
            home_page = self.pages.get('dashboard')
            if home_page is not None and hasattr(home_page, 'refresh'):
                callbacks.append(home_page.refresh)
        except Exception:
            pass
        callbacks.append(self._refresh_league_header)
        create_league_action(self._context, self, callbacks)

    def open_league_manager(self) -> None:
        try:
            dialog = LeagueManagerDialog(self)
            dialog.exec()
            self._refresh_league_header()
            self._refresh_date_status()
        except Exception:
            pass


    def open_exhibition_dialog(self) -> None:
        dlg = ExhibitionGameDialog(self)
        dlg.exec()

    def open_playbalance_editor(self) -> None:
        editor = PlayBalanceEditor(self)
        editor.exec()

    def reset_to_opening_day(self) -> None:
        def refresh_current() -> None:
            try:
                self._refresh_date_status()
            except Exception:
                pass
        reset_season_to_opening_day(self._context, self, refresh_current)

    def regenerate_regular_season_schedule(self) -> None:
        regenerate_schedule_action(self._context, self)


    def open_season_progress(self) -> None:
        win = SeasonProgressWindow(
            self,
            run_async=self._context.run_async,
            show_toast=self._context.show_toast,
            register_cleanup=self._context.register_cleanup,
        )
        try:
            # Refresh status/date while sim is running and on close
            # Bind self as a default to avoid free-var scope issues in lambdas
            win.progressUpdated.connect(lambda *_, s=self: s._refresh_date_status())
            win.destroyed.connect(lambda *_, s=self: s._refresh_date_status())
        except Exception:
            pass
        win.show()

    def _refresh_date_status(self) -> None:
        try:
            # Update status bar and refresh current page if it supports refresh()
            # Determine current page key
            keys = list(self.pages.keys())
            idx = self.stack.currentIndex()
            key = keys[idx] if 0 <= idx < len(keys) else "home"
            self.statusBar().showMessage(self._status_with_date(f"Ready - {key.capitalize()}"))
            page = self.pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()  # type: ignore[attr-defined]
        except Exception:
            # Best effort only
            pass

    def open_injury_center(self) -> None:
        try:
            win = InjuryCenterWindow(self)
            win.show()
        except Exception:
            pass

    def open_injury_settings(self) -> None:
        try:
            dialog = InjurySettingsDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_hall_of_fame_settings(self) -> None:
        try:
            dialog = HallOfFameSettingsDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_trade_settings(self) -> None:
        try:
            dialog = TradeSettingsDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_financial_settings(self) -> None:
        try:
            dialog = FinancialSettingsDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_finance_stability(self) -> None:
        try:
            dialog = FinanceStabilityDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_news_window(self) -> None:
        try:
            win = NewsWindow(self)
            win.show()
        except Exception:
            pass

    def open_free_agency(self) -> None:
        try:
            win = FreeAgencyWindow(self)
            win.show()
        except Exception:
            pass

    def open_playoffs_window(self) -> None:
        try:
            self._playoffs_win = PlayoffsWindow(
                self,
                run_async=self._context.run_async,
                show_toast=self._context.show_toast,
                register_cleanup=self._context.register_cleanup,
            )
            self._playoffs_win.show()
        except Exception:
            # Headless environments may lack full Qt stack
            pass

    def open_league_history(self) -> None:
        try:
            show_on_top(LeagueHistoryWindow(self))
        except Exception:
            pass

    def open_offseason_finance_workflow(self) -> None:
        try:
            dialog = OffseasonFinanceDialog(self)
            dialog.exec()
        except Exception:
            pass

    def open_change_requests_window(self) -> None:
        try:
            show_on_top(ChangeRequestsWindow(self))
        except Exception:
            pass

    def open_gm_finance_queue_review(self) -> None:
        try:
            dialog = GmFinanceQueueDialog(self)
            dialog.exec()
            tx = self.pages.get("transactions")
            if tx is not None and hasattr(tx, "refresh"):
                tx.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Amateur Draft helpers
    # ------------------------------------------------------------------
    def _compute_draft_date_for_year(self, year: int) -> str:
        import datetime as _dt
        d = _dt.date(year, 7, 1)
        while d.weekday() != 1:  # Tuesday is 1
            d += _dt.timedelta(days=1)
        d += _dt.timedelta(days=14)
        return d.isoformat()

    def _current_season_year(self) -> int:
        # Heuristic: attempt to read from schedule.csv if present; else use today
        try:
            from utils.path_utils import get_data_dir
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
        from datetime import date as _date
        return _date.today().year

    def _open_draft_console(self) -> None:
        try:
            from ui.draft_console import DraftConsole
        except Exception as exc:
            QMessageBox.warning(self, "Draft Console", f"Unable to open Draft Console: {exc}")
            return
        year = self._current_season_year()
        date_str = self._compute_draft_date_for_year(year)
        dlg = DraftConsole(date_str, self)
        dlg.exec()
        try:
            self._refresh_draft_page()
        except Exception:
            pass

    def open_draft_console(self) -> None:
        self._open_draft_console()

    def open_draft_pool(self) -> None:
        # For now, open the same console; users can browse pool without drafting
        self._open_draft_console()

    def open_draft_results(self) -> None:
        """Open a simple viewer for current season's draft results CSV, if present."""
        import csv as _csv
        year = self._current_season_year()
        from utils.path_utils import get_data_dir as _gd
        p = _gd() / f"draft_results_{year}.csv"
        if not p.exists():
            QMessageBox.information(self, "Draft Results", f"No draft results found for {year}.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Draft Results {year}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        label = QLabel(str(p))
        lay.addWidget(label)
        lst = QListWidget()
        try:
            with p.open(newline="", encoding="utf-8") as fh:
                r = _csv.DictReader(fh)
                for row in r:
                    rd = row.get("round", "")
                    pick = row.get("overall_pick", "")
                    team = row.get("team_id", "")
                    pid = row.get("player_id", "")
                    lst.addItem(f"R{rd} P{pick}: {team} -> {pid}")
        except Exception:
            lst.addItem("<Unable to read draft results>")
        lay.addWidget(lst)
        show_on_top(dlg)

    def open_draft_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Draft Settings")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        cfg = load_draft_config()

        layout.addWidget(QLabel("Rounds:"))
        rounds_input = QLineEdit(str(cfg.get("rounds", 10)))
        layout.addWidget(rounds_input)

        layout.addWidget(QLabel("Pool Size:"))
        pool_input = QLineEdit(str(cfg.get("pool_size", 200)))
        layout.addWidget(pool_input)

        layout.addWidget(QLabel("Random Seed (blank = default):"))
        seed_val = cfg.get("seed")
        seed_input = QLineEdit("" if seed_val in (None, "") else str(seed_val))
        layout.addWidget(seed_input)

        row = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        row.addWidget(save_btn)
        row.addWidget(cancel_btn)
        layout.addLayout(row)

        def do_save() -> None:
            try:
                rounds = int(rounds_input.text().strip())
                pool_size = int(pool_input.text().strip())
            except ValueError:
                QMessageBox.warning(dialog, "Invalid Input", "Rounds and Pool Size must be integers.")
                return
            seed_txt = seed_input.text().strip()
            seed: int | None
            if seed_txt == "":
                seed = None
            else:
                try:
                    seed = int(seed_txt)
                except ValueError:
                    QMessageBox.warning(dialog, "Invalid Seed", "Seed must be an integer or blank.")
                    return
            try:
                save_draft_config({"rounds": rounds, "pool_size": pool_size, "seed": seed})
                QMessageBox.information(dialog, "Saved", "Draft settings saved. New drafts will use these settings.")
                dialog.accept()
            except Exception as exc:
                QMessageBox.warning(dialog, "Save Failed", str(exc))

        save_btn.clicked.connect(do_save)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.setLayout(layout)
        dialog.exec()

    # Draft gating ------------------------------------------------------
    def _refresh_draft_page(self) -> None:
        try:
            dp = self.pages.get("draft")
            if dp is None:
                return
            available, cur_date, draft_date, completed = self._draft_availability_details()
            # Gate only pool and draft console; keep settings always enabled
            dp.view_draft_pool_button.setEnabled(available)
            dp.start_resume_draft_button.setEnabled(available)
            dp.draft_settings_button.setEnabled(True)
            try:
                dp.view_results_button.setVisible(bool(completed))
                dp.view_results_button.setEnabled(bool(completed))
            except Exception:
                pass
            # Status message
            if completed:
                msg = f"Current date: {cur_date} | Draft Day: {draft_date} | Draft already completed this year"
            elif cur_date and draft_date:
                msg = (
                    f"Current date: {cur_date} | Draft Day: {draft_date} | "
                    f"Status: {'Ready' if available else 'Not yet'}"
                )
            else:
                msg = "Draft status unavailable - missing schedule or progress data"
            try:
                dp.draft_status_label.setText(msg)
                # Update tooltips to mirror availability and guidance
                if completed:
                    tip = "Draft already completed for this season."
                elif cur_date and draft_date:
                    tip = (
                        f"Draft Day: {draft_date}. Current date: {cur_date}. "
                        f"{'Ready to open the Draft Console.' if available else 'Buttons enable on Draft Day.'}"
                    )
                else:
                    tip = "Draft timing unknown. Ensure schedule and season progress exist."
                dp.view_draft_pool_button.setToolTip(tip)
                dp.start_resume_draft_button.setToolTip(tip)
                dp.draft_settings_button.setToolTip("Configure rounds, pool size, and RNG seed (always available).")
                if completed:
                    dp.view_results_button.setToolTip("Open draft results for the current season.")
            except Exception:
                pass
        except Exception:
            pass

    def _is_draft_available(self) -> bool:
        from utils.path_utils import get_data_dir
        import csv as _csv
        import json as _json
        from datetime import date as _date
        base = get_data_dir()
        sched = base / "schedule.csv"
        prog = base / "season_progress.json"
        if not sched.exists() or not prog.exists():
            return False
        try:
            with prog.open("r", encoding="utf-8") as fh:
                progress = _json.load(fh)
        except Exception:
            return False
        with sched.open(newline="") as fh:
            rows = list(_csv.DictReader(fh))
        if not rows:
            return False
        sim_index = int(progress.get("sim_index", 0) or 0)
        sim_index = max(0, min(sim_index, len(rows) - 1))
        cur_date = str(rows[sim_index].get("date") or "")
        if not cur_date:
            return False
        year = int(cur_date.split("-")[0])
        done = set(progress.get("draft_completed_years", []))
        if year in done:
            return False
        draft_date = self._compute_draft_date_for_year(year)
        try:
            y1, m1, d1 = [int(x) for x in cur_date.split("-")]
            y2, m2, d2 = [int(x) for x in draft_date.split("-")]
            return _date(y1, m1, d1) >= _date(y2, m2, d2)
        except Exception:
            return False

    def _draft_availability_details(self) -> tuple[bool, str | None, str | None, bool]:
        """Return (available, current_date, draft_date, completed) with safe fallbacks."""
        from utils.path_utils import get_data_dir
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
        done = set(progress.get("draft_completed_years", [])) if isinstance(progress, dict) else set()
        completed = year in done
        try:
            y1, m1, d1 = [int(x) for x in cur_date.split("-")]
            y2, m2, d2 = [int(x) for x in draft_date.split("-")]
            available = (not completed) and (_date(y1, m1, d1) >= _date(y2, m2, d2))
        except Exception:
            available = False
        return (available, cur_date, draft_date, completed)


__all__ = [
    "MainWindow",
    "LeagueSettingsPage",
    "SeasonPage",
    "TeamsPage",
    "TransactionsPage",
    "UsersPage",
    "UtilitiesPage",
]







