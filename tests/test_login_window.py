import os, sys, types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummySignal:
    def __init__(self):
        self._slot = None
    def connect(self, slot):
        self._slot = slot
    def emit(self, *args, **kwargs):
        if self._slot:
            try:
                self._slot(*args, **kwargs)
            except TypeError:
                self._slot()

class QWidget:
    def __init__(self, *args, **kwargs):
        pass
    def setLayout(self, *args, **kwargs):
        pass
    def setWindowTitle(self, *args, **kwargs):
        pass
    def setGeometry(self, *args, **kwargs):
        pass
    def setObjectName(self, *args, **kwargs):
        pass
    def close(self):
        pass
    def show(self):
        pass
    def raise_(self):
        pass
    def activateWindow(self):
        pass
    def showMaximized(self):
        pass
    def hide(self):
        pass
    def setContentsMargins(self, *args, **kwargs):
        pass
    def setSpacing(self, *args, **kwargs):
        pass

class QLabel:
    def __init__(self, *args, **kwargs):
        pass
    def hide(self):
        pass

class QLineEdit:
    class EchoMode:
        Password = 0
    def __init__(self):
        self._text = ""
        self.returnPressed = DummySignal()
    def setPlaceholderText(self, text):
        pass
    def setEchoMode(self, mode):
        pass
    def setFocus(self):
        pass
    def text(self):
        return self._text
    def setText(self, text):
        self._text = text

class QPushButton:
    def __init__(self, *args, **kwargs):
        self.clicked = DummySignal()
    def setDefault(self, val):
        pass
    def setEnabled(self, val):
        pass

class QComboBox:
    def __init__(self, *args, **kwargs):
        self.currentIndexChanged = DummySignal()
        self._items = []
        self._index = -1
        self._signals_blocked = False
    def blockSignals(self, blocked):
        self._signals_blocked = bool(blocked)
    def clear(self):
        self._items = []
        self._index = -1
    def addItem(self, text, userData=None):
        self._items.append((text, userData))
        if self._index < 0:
            self._index = 0
    def setCurrentIndex(self, index):
        self._index = index
        if not self._signals_blocked:
            self.currentIndexChanged.emit(index)
    def currentData(self):
        if 0 <= self._index < len(self._items):
            return self._items[self._index][1]
        return None
    def hide(self):
        pass

class QVBoxLayout:
    def __init__(self, *args, **kwargs):
        pass
    def addWidget(self, *args, **kwargs):
        pass
    def addStretch(self, *args, **kwargs):
        pass
    def addLayout(self, *args, **kwargs):
        pass
    def setContentsMargins(self, *args, **kwargs):
        pass
    def setSpacing(self, *args, **kwargs):
        pass

class QGridLayout(QVBoxLayout):
    pass

class QHBoxLayout(QVBoxLayout):
    pass

class QScrollArea(QWidget):
    pass

class QSizePolicy:
    pass

class QToolButton(QWidget):
    pass

class QBoxLayout(QVBoxLayout):
    pass

class QMessageBox:
    @staticmethod
    def critical(*args, **kwargs):
        pass
    @staticmethod
    def warning(*args, **kwargs):
        pass

class QInputDialog:
    @staticmethod
    def getText(*args, **kwargs):
        return "", False

class QApplication:
    def __init__(self, *args, **kwargs):
        pass

qtwidgets = types.ModuleType("PyQt6.QtWidgets")
qtwidgets.QApplication = QApplication
qtwidgets.QWidget = QWidget
qtwidgets.QLabel = QLabel
qtwidgets.QLineEdit = QLineEdit
qtwidgets.QPushButton = QPushButton
qtwidgets.QComboBox = QComboBox
qtwidgets.QVBoxLayout = QVBoxLayout
qtwidgets.QHBoxLayout = QHBoxLayout
qtwidgets.QGridLayout = QGridLayout
qtwidgets.QScrollArea = QScrollArea
qtwidgets.QSizePolicy = QSizePolicy
qtwidgets.QToolButton = QToolButton
qtwidgets.QBoxLayout = QBoxLayout
qtwidgets.QMessageBox = QMessageBox
qtwidgets.QInputDialog = QInputDialog
def _widgets_getattr(_name):
    return QWidget
qtwidgets.__getattr__ = _widgets_getattr  # type: ignore[attr-defined]
sys.modules['PyQt6'] = types.ModuleType('PyQt6')
sys.modules['PyQt6.QtWidgets'] = qtwidgets

qtcore = types.ModuleType("PyQt6.QtCore")
class Qt:
    class AlignmentFlag:
        AlignCenter = 0
        AlignLeft = 1
        AlignRight = 2
        AlignHCenter = 0
        AlignVCenter = 0
        AlignTop = 0
        AlignBottom = 0
    class ToolButtonStyle:
        ToolButtonTextBesideIcon = None
    class ScrollBarPolicy:
        ScrollBarAlwaysOff = 0
        ScrollBarAsNeeded = 1
qtcore.Qt = Qt
sys.modules['PyQt6.QtCore'] = qtcore

admin_mod = types.ModuleType("ui.admin_dashboard")
class AdminDashboard:
    def __init__(self, *args, **kwargs):
        pass
admin_mod.AdminDashboard = AdminDashboard
sys.modules['ui.admin_dashboard'] = admin_mod

owner_mod = types.ModuleType("ui.owner_dashboard")
class OwnerDashboard:
    def __init__(self, *args, **kwargs):
        pass
owner_mod.OwnerDashboard = OwnerDashboard
sys.modules['ui.owner_dashboard'] = owner_mod

theme_mod = types.ModuleType('ui.theme')
theme_mod.DARK_QSS = ""
theme_mod._toggle_theme = lambda status_bar=None: None
sys.modules['ui.theme'] = theme_mod

import bcrypt
from ui import login_window

def test_login_plain_and_hashed(tmp_path):
    user_file = tmp_path / "users.txt"
    hashed = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
    user_file.write_text(
        f"admin,pass,admin,\nuser,{hashed},owner,team\n"
    )
    login_window.USER_FILE = user_file

    win = login_window.LoginWindow()
    result = {}
    def accept(role, team_id):
        result['role'] = role
        result['team_id'] = team_id
    win.accept_login = accept

    win.username_input.setText("admin")
    win.password_input.setText("pass")
    win.handle_login()
    assert result == {'role': 'admin', 'team_id': ''}

    result.clear()
    win.username_input.setText("user")
    win.password_input.setText("pw")
    win.handle_login()
    assert result == {'role': 'owner', 'team_id': 'team'}
