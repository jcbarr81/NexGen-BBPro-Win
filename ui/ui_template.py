import sys
from pathlib import Path
from types import SimpleNamespace

try:
    from PyQt6.QtCore import Qt, QSize
except ImportError:  # pragma: no cover - test stubs
    Qt = SimpleNamespace(
        AspectRatioMode=SimpleNamespace(KeepAspectRatio=None),
        TransformationMode=SimpleNamespace(SmoothTransformation=None),
        AlignmentFlag=SimpleNamespace(
            AlignCenter=None,
            AlignVCenter=None,
            AlignRight=None,
        ),
        GlobalColor=SimpleNamespace(transparent=None),
        PenStyle=SimpleNamespace(NoPen=None),
        PenCapStyle=SimpleNamespace(RoundCap=None),
        ToolButtonStyle=SimpleNamespace(ToolButtonTextBesideIcon=None),
    )

    class QSize:  # type: ignore[too-many-ancestors]
        def __init__(self, width: int = 0, height: int = 0) -> None:
            self._width = width
            self._height = height

        def width(self) -> int:
            return self._width

        def height(self) -> int:
            return self._height
else:  # pragma: no branch - normalize stub attributes
    if not hasattr(Qt, "AspectRatioMode"):
        Qt.AspectRatioMode = SimpleNamespace(KeepAspectRatio=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "TransformationMode"):
        Qt.TransformationMode = SimpleNamespace(SmoothTransformation=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "AlignmentFlag"):
        Qt.AlignmentFlag = SimpleNamespace(  # type: ignore[attr-defined]
            AlignCenter=None,
            AlignVCenter=None,
            AlignRight=None,
        )
    if not hasattr(Qt, "GlobalColor"):
        Qt.GlobalColor = SimpleNamespace(transparent=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "PenStyle"):
        Qt.PenStyle = SimpleNamespace(NoPen=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "PenCapStyle"):
        Qt.PenCapStyle = SimpleNamespace(RoundCap=None)  # type: ignore[attr-defined]
    if not hasattr(Qt, "ToolButtonStyle"):
        Qt.ToolButtonStyle = SimpleNamespace(ToolButtonTextBesideIcon=None)  # type: ignore[attr-defined]

try:
    from PyQt6.QtGui import QAction, QFont, QPixmap, QPainter, QColor, QPen, QPainterPath, QIcon
except ImportError:  # pragma: no cover - test stubs
    class _Dummy:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name: str):
            def _noop(*_args, **_kwargs):
                return None

            return _noop

    QAction = QFont = QPixmap = QPainter = QColor = QPen = QPainterPath = QIcon = _Dummy  # type: ignore[assignment]

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QLabel,
    QFrame,
    QPushButton,
    QStatusBar,
)

from .components import Card, NavButton, section_title
from .theme import DARK_QSS, _toggle_theme
from .version_badge import install_version_badge

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

_ICON_DIR = Path(__file__).resolve().parent / "icons"
_NAV_ICON_MAP = {
    "dashboard": "nav_dashboard.svg",
    "league": "nav_league.svg",
    "teams": "nav_teams.svg",
    "users": "nav_users.svg",
    "utils": "nav_utilities.svg",
    "draft": "nav_draft.svg",
}


def _load_baseball_pixmap(size: int = 20) -> QPixmap:
    """Load the baseball icon, scaling to the desired size."""
    source = _ICON_DIR / "baseball.png"
    pixmap = QPixmap(str(source))
    if pixmap.isNull():
        pixmap = _draw_baseball_pixmap(size)
        return pixmap
    if size > 0:
        pixmap = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pixmap


def _load_nav_icon(name: str, size: int = 22) -> QIcon:
    """Load a sidebar navigation icon by filename."""
    safe_size = int(size)
    if safe_size <= 0:
        return QIcon()
    source = _ICON_DIR / name
    icon = QIcon(str(source))
    if icon.isNull():
        placeholder = QPixmap(safe_size, safe_size)
        placeholder.fill(Qt.GlobalColor.transparent)
        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, on=True)
        painter.setBrush(QColor("#3b2810"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, safe_size, safe_size, safe_size * 0.3, safe_size * 0.3)
        painter.setPen(QColor("#fffdf0"))
        font = QFont()
        point_size = max(1, int(round(safe_size * 0.4)))
        font.setPointSize(point_size)
        font.setBold(True)
        painter.setFont(font)
        label = name
        if label.lower().startswith("nav_"):
            label = label[4:]
        label = label.split(".", 1)[0]
        painter.drawText(
            placeholder.rect(),
            Qt.AlignmentFlag.AlignCenter,
            label[:1].upper(),
        )
        painter.end()
        icon = QIcon(placeholder)
    else:
        base_pixmap = icon.pixmap(safe_size, safe_size)
        if not base_pixmap.isNull():
            tinted = QPixmap(base_pixmap.size())
            tinted.setDevicePixelRatio(base_pixmap.devicePixelRatio())
            tinted.fill(Qt.GlobalColor.transparent)
            painter = QPainter(tinted)
            painter.drawPixmap(0, 0, base_pixmap)
            composition_mode = getattr(
                QPainter.CompositionMode,
                "SourceIn",
                getattr(QPainter.CompositionMode, "CompositionMode_SourceIn", None),
            )
            if composition_mode is not None:
                painter.setCompositionMode(composition_mode)
            painter.fillRect(tinted.rect(), QColor("#ffffff"))
            painter.end()
            bright = QIcon()
            bright.addPixmap(tinted, QIcon.Mode.Normal, QIcon.State.Off)
            bright.addPixmap(tinted, QIcon.Mode.Active, QIcon.State.Off)
            bright.addPixmap(tinted, QIcon.Mode.Selected, QIcon.State.Off)
            icon = bright
    return icon


def _draw_baseball_pixmap(size: int) -> QPixmap:
    """Fallback painter when the external asset is unavailable."""
    diameter = max(14, size)
    pixmap = QPixmap(diameter, diameter)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, on=True)

    border_pen = QPen(QColor("#1c1c1c"))
    border_pen.setWidthF(max(1.0, diameter * 0.12))
    painter.setPen(border_pen)
    painter.setBrush(QColor("#fcfcfc"))
    inset = border_pen.widthF() / 2
    painter.drawEllipse(pixmap.rect().adjusted(int(inset), int(inset), -int(inset), -int(inset)))

    shade = QColor("#e8e8e8")
    painter.setBrush(shade)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(pixmap.rect().adjusted(int(diameter * 0.15), int(diameter * 0.04), -int(diameter * 0.02), -int(diameter * 0.04)))

    stitch_pen = QPen(QColor("#c64545"))
    stitch_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    stitch_pen.setWidthF(max(1.0, diameter * 0.14))
    painter.setPen(stitch_pen)

    left_curve = QPainterPath()
    left_curve.moveTo(diameter * 0.32, diameter * 0.12)
    left_curve.quadTo(diameter * 0.12, diameter * 0.5, diameter * 0.32, diameter * 0.88)
    painter.drawPath(left_curve)

    right_curve = QPainterPath()
    right_curve.moveTo(diameter * 0.68, diameter * 0.12)
    right_curve.quadTo(diameter * 0.88, diameter * 0.5, diameter * 0.68, diameter * 0.88)
    painter.drawPath(right_curve)

    painter.end()

    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

# ------------------------------------------------------------
# Pages
# ------------------------------------------------------------

class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        # Row of quick cards
        row = QHBoxLayout()
        row.setSpacing(18)

        c1 = Card()
        c1.layout().addWidget(section_title("Today’s Slate"))
        c1.layout().addWidget(QLabel("• Exhibition: Knights @ Admirals\n• Scrimmage: Monarchs @ Pilots"))
        c1.layout().addStretch()

        c2 = Card()
        c2.layout().addWidget(section_title("Admin Shortcuts"))
        for text in ("Review Trades", "Create League", "Season Progress"):
            btn = QPushButton(f"⚾  {text}")
            btn.setObjectName("Primary")
            c2.layout().addWidget(btn)
        c2.layout().addStretch()

        c3 = Card()
        c3.layout().addWidget(section_title("League Health"))
        c3.layout().addWidget(QLabel("Teams: 30\nPlayers: 900\nOpen Tickets: 3"))
        c3.layout().addStretch()

        row.addWidget(c1)
        row.addWidget(c2)
        row.addWidget(c3)

        big = Card()
        big.layout().addWidget(section_title("Game Control"))
        play = QPushButton("Play Ball – Simulate Exhibition Game")
        play.setObjectName("Success")
        play.setMinimumHeight(48)
        big.layout().addWidget(play)

        root.addLayout(row)
        root.addWidget(big)
        root.addStretch()

class LeaguePage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        card = Card()
        card.layout().addWidget(section_title("League Management"))
        card.layout().addWidget(QLabel("Create leagues, edit rules, schedule seasons."))
        card.layout().addWidget(QPushButton("New League", objectName="Primary"))
        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()

class TeamsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        card = Card()
        card.layout().addWidget(section_title("Team Management"))
        card.layout().addWidget(QLabel("Manage rosters, depth charts, and finances."))
        card.layout().addWidget(QPushButton("Open Team Directory", objectName="Primary"))
        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()

class UsersPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        card = Card()
        card.layout().addWidget(section_title("User Management"))
        card.layout().addWidget(QLabel("Invites, roles, and permissions for your GMs."))
        card.layout().addWidget(QPushButton("Add User", objectName="Primary"))
        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()

class UtilitiesPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        card = Card()
        card.layout().addWidget(section_title("Utilities"))
        card.layout().addWidget(QLabel("Import/export data, backups, and tools."))
        card.layout().addWidget(QPushButton("Open Utilities", objectName="Primary"))
        card.layout().addStretch()
        layout.addWidget(card)
        layout.addStretch()

# ------------------------------------------------------------
# Main Window
# ------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Commissioner's Office – Admin Dashboard")
        self.resize(1100, 720)

        # Central area: sidebar + content
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar (dugout)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
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

        # Make them mutually exclusive
        for b in (self.btn_dashboard, self.btn_league, self.btn_teams, self.btn_users, self.btn_utils):
            side.addWidget(b)

        self.nav_buttons = {
            "dashboard": self.btn_dashboard,
            "league": self.btn_league,
            "teams": self.btn_teams,
            "users": self.btn_users,
            "utils": self.btn_utils,
        }
        icon_size = QSize(24, 24)
        for key, button in self.nav_buttons.items():
            icon_name = _NAV_ICON_MAP.get(key)
            if not icon_name:
                continue
            icon = _load_nav_icon(icon_name, icon_size.width())
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        side.addStretch()
        side.addWidget(QLabel("  Settings"))
        self.btn_settings = NavButton("  Preferences")
        side.addWidget(self.btn_settings)

        # Header (scoreboard)
        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.setSpacing(12)

        title = QLabel("Welcome to the Admin Dashboard")
        title.setObjectName("Title")
        title.setFont(QFont(title.font().family(), 11, weight=QFont.Weight.ExtraBold))
        h.addWidget(title)
        h.addStretch()

        self.scoreboard = QLabel("Top 1st • 0–0 • No Outs")
        self.scoreboard.setObjectName("Scoreboard")
        h.addWidget(self.scoreboard, alignment=Qt.AlignmentFlag.AlignRight)

        # Stacked content
        self.stack = QStackedWidget()
        self.pages = {
            "dashboard": DashboardPage(),
            "league": LeaguePage(),
            "teams": TeamsPage(),
            "users": UsersPage(),
            "utils": UtilitiesPage(),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)

        # Right side: header + stacked pages
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

        # Menu
        self._build_menu()

        # Signals
        self.btn_dashboard.clicked.connect(lambda: self._go("dashboard"))
        self.btn_league.clicked.connect(lambda: self._go("league"))
        self.btn_teams.clicked.connect(lambda: self._go("teams"))
        self.btn_users.clicked.connect(lambda: self._go("users"))
        self.btn_utils.clicked.connect(lambda: self._go("utils"))
        self.btn_settings.clicked.connect(lambda: _toggle_theme(self.statusBar()))

        # Default selection
        self.btn_dashboard.setChecked(True)
        self._go("dashboard")

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        theme_action = QAction("Toggle Dark Mode", self)
        theme_action.triggered.connect(lambda: _toggle_theme(self.statusBar()))
        view_menu.addAction(theme_action)

    def _go(self, key):
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
        btn = self.nav_buttons.get(key)
        if btn:
            btn.setChecked(True)
        idx = list(self.pages.keys()).index(key)
        self.stack.setCurrentIndex(idx)
        self.statusBar().showMessage(f"Ready • {key.capitalize()}")


# ------------------------------------------------------------
# Run
# ------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)  # start in dark; toggle with View > Toggle Dark Mode
    install_version_badge(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
