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
    generate_player_avatars_action,
    generate_team_logos_action,
    reset_season_to_opening_day,
    review_pending_trades,
    set_all_lineups as set_all_lineups_action,
    set_all_pitching_roles as set_all_pitching_roles_action,
)
from .admin_dashboard.pages import (
    DraftPage,
    LeaguePage,
    TeamsPage,
    UsersPage,
    UtilitiesPage,
)
from .admin_home_page import AdminHomePage
from ui.window_utils import show_on_top
from ui.sim_date_bus import sim_date_bus
from .theme import _toggle_theme
from .exhibition_game_dialog import ExhibitionGameDialog
from .playbalance_editor import PlayBalanceEditor
from playbalance.draft_config import load_draft_config, save_draft_config
from .season_progress_window import SeasonProgressWindow
from .playoffs_window import PlayoffsWindow
from .free_agency_window import FreeAgencyWindow
from .news_window import NewsWindow
from .injury_center_window import InjuryCenterWindow
from .injury_settings_dialog import InjurySettingsDialog
from .avatar_tutorial_dialog import AvatarTutorialDialog
from .logo_tutorial_dialog import LogoTutorialDialog
from .league_history_window import LeagueHistoryWindow
from .owner_dashboard import OwnerDashboard
from utils.trade_utils import load_trades
from utils.player_loader import load_players_from_csv
from utils.team_loader import load_teams
from utils.path_utils import get_base_dir
from utils.sim_date import get_current_sim_date
from ui.version_badge import enable_version_badge

_OPEN_OWNER_DASHBOARDS: list[OwnerDashboard] = []


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
            base_path=get_base_dir(),
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
        self.btn_league = NavButton("  League")
        self.btn_teams = NavButton("  Teams")
        self.btn_users = NavButton("  Users")
        self.btn_utils = NavButton("  Utilities")
        self.btn_draft = NavButton("  Draft")
        for b in (
            self.btn_dashboard,
            self.btn_league,
            self.btn_teams,
            self.btn_users,
            self.btn_utils,
            self.btn_draft,
        ):
            side.addWidget(b)
        side.addStretch()

        self.nav_buttons = {
            "dashboard": self.btn_dashboard,
            "league": self.btn_league,
            "teams": self.btn_teams,
            "users": self.btn_users,
            "utils": self.btn_utils,
            "draft": self.btn_draft,
        }
        icon_size = QSize(24, 24)
        nav_tooltips = {
            "dashboard": "League overview and quick actions",
            "league": "Season control and operations",
            "teams": "Open team dashboards and bulk actions",
            "users": "Manage accounts and roles",
            "utils": "Logos, avatars, and data tools",
            "draft": "Amateur Draft console and settings",
        }
        for key, button in self.nav_buttons.items():
            icon_name = _NAV_ICON_MAP.get(key)
            icon = _load_nav_icon(icon_name, icon_size.width()) if icon_name else QIcon()
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            tooltip = nav_tooltips.get(key)
            if tooltip:
                button.setToolTip(tooltip)

        # header + stacked pages -----------------------------------------
        header = QWidget(objectName="Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.addWidget(QLabel("Admin Dashboard", objectName="Title"))
        h.addStretch()

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

        # menu ------------------------------------------------------------
        self._build_menu()

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
        lp = self.pages.get("league")
        if isinstance(lp, LeaguePage):
            lp.review_button.clicked.connect(self.open_trade_review)
            lp.create_league_button.clicked.connect(self.open_create_league)
            lp.exhibition_button.clicked.connect(self.open_exhibition_dialog)
            lp.playbalance_button.clicked.connect(self.open_playbalance_editor)
            lp.injury_center_button.clicked.connect(self.open_injury_center)
            lp.injury_settings_button.clicked.connect(self.open_injury_settings)
            lp.free_agency_hub_button.clicked.connect(self.open_free_agency)
            lp.season_progress_button.clicked.connect(self.open_season_progress)
            lp.playoffs_view_button.clicked.connect(self.open_playoffs_window)
            lp.reset_opening_day_button.clicked.connect(self.reset_to_opening_day)
            lp.league_history_button.clicked.connect(self.open_league_history)
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
            "league": self._build_dashboard_page(LeaguePage),
            "teams": self._build_dashboard_page(TeamsPage),
            "users": self._build_dashboard_page(UsersPage),
            "utils": self._build_dashboard_page(UtilitiesPage),
            "draft": self._build_dashboard_page(DraftPage),
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
        theme_action = QAction("Toggle Dark Mode", self)
        theme_action.triggered.connect(lambda: _toggle_theme(self.statusBar()))
        view_menu.addAction(theme_action)
        news_action = QAction("News Feed", self)
        news_action.triggered.connect(self.open_news_window)
        view_menu.addAction(news_action)

    def _status_with_date(self, base: str) -> str:
        date_str = get_current_sim_date()
        if date_str:
            return f"{base} | Date: {date_str}"
        return base

    def _on_sim_date_changed(self, _value: object) -> None:
        """Refresh status and active page when the sim date advances."""

        try:
            QTimer.singleShot(0, self._refresh_date_status)
        except Exception:
            self._refresh_date_status()

    def _go(self, key: str) -> None:
        try:
            self._navigation.set_current(key)
        except KeyError:
            pass

    def _on_navigation_changed(self, key: str | None) -> None:
        if not key:
            return
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
        # Counts
        try:
            # Match the team list shown in the Standings window, which relies
            # on load_teams(data/teams.csv).
            teams = load_teams("data/teams.csv")
            team_count = len(teams)
        except Exception:
            team_count = 0
        try:
            players = load_players_from_csv("data/players.csv")
            player_count = len(players)
        except Exception:
            player_count = 0
        # Pending trades
        try:
            pending = sum(1 for t in load_trades() if getattr(t, "status", "") == "pending")
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
        return {
            "teams": team_count,
            "players": player_count,
            "pending_trades": pending,
            "season_phase": phase,
            "draft_day": draft_date,
            "draft_status": status,
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
        teams = load_teams(get_base_dir() / "data" / "teams.csv")
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
            dashboard = OwnerDashboard(team_id)
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
        create_league_action(self._context, self, callbacks)


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
            from utils.path_utils import get_base_dir
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
        from utils.path_utils import get_base_dir as _gb
        p = _gb() / "data" / f"draft_results_{year}.csv"
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
        from utils.path_utils import get_base_dir
        import csv as _csv
        import json as _json
        from datetime import date as _date
        base = get_base_dir() / "data"
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
        from utils.path_utils import get_base_dir
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
    "LeaguePage",
    "TeamsPage",
    "UsersPage",
    "UtilitiesPage",
]







