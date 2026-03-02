"""Minimal PyQt6 stubs so UI modules can be imported in tests."""

from __future__ import annotations

from types import SimpleNamespace
import sys
import types
from typing import Any


class _QtDummy:
    """Fallback object that quietly absorbs attribute access."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._children: dict[str, _QtDummy] = {}

    def __getattr__(self, name: str) -> "_QtDummy":
        child = self._children.get(name)
        if child is None:
            if name.endswith("Changed") or name in {"clicked"}:
                child = _Signal()
            else:
                child = _QtDummy()
            self._children[name] = child
        return child

    # Common widget methods we touch in tests
    def addWidget(self, *args: Any, **kwargs: Any) -> None:
        pass

    def addLayout(self, *args: Any, **kwargs: Any) -> None:
        pass

    def addTab(self, *args: Any, **kwargs: Any) -> None:
        pass

    def addItem(self, *args: Any, **kwargs: Any) -> None:
        pass

    def addStretch(self, *args: Any, **kwargs: Any) -> None:
        pass

    def addSpacing(self, *args: Any, **kwargs: Any) -> None:
        pass

    def clear(self, *args: Any, **kwargs: Any) -> None:
        pass

    def layout(self, *args: Any, **kwargs: Any) -> "_QtDummy":
        return self

    def setLayout(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setContentsMargins(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setSpacing(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setVerticalSpacing(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setHorizontalSpacing(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setObjectName(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setFrameShape(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setAlignment(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setFixedSize(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setWindowTitle(self, *args: Any, **kwargs: Any) -> None:
        pass

    def adjustSize(self, *args: Any, **kwargs: Any) -> None:
        pass

    def sizeHint(self, *args: Any, **kwargs: Any) -> "_QtDummy":
        return self

    def setWordWrap(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setText(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setPixmap(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setMinimumSize(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setMinimumWidth(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setMargin(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setProperty(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setData(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setTextAlignment(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setEditTriggers(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setSelectionBehavior(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setSelectionMode(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setPlaceholderText(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setCurrentIndex(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setSizePolicy(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setAlternatingRowColors(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setVisible(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setHorizontalHeaderLabels(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setSortingEnabled(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setItem(self, *args: Any, **kwargs: Any) -> None:
        pass

    def horizontalHeader(self, *args: Any, **kwargs: Any) -> "_QtDummy":
        return self

    def verticalHeader(self, *args: Any, **kwargs: Any) -> "_QtDummy":
        return self

    def setSectionResizeMode(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setStretchLastSection(self, *args: Any, **kwargs: Any) -> None:
        pass

    def text(self, *args: Any, **kwargs: Any) -> str:
        return ""

    def setRowCount(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setColumnCount(self, *args: Any, **kwargs: Any) -> None:
        pass

    def setHorizontalHeaderItem(self, *args: Any, **kwargs: Any) -> None:
        pass

    def show(self, *args: Any, **kwargs: Any) -> None:
        pass

    def exec(self, *args: Any, **kwargs: Any) -> None:
        return None


class _QtEnum(SimpleNamespace):
    """Namespace for fake enum values."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        for idx, key in enumerate(list(self.__dict__.keys())):
            if getattr(self, key) is None:
                setattr(self, key, 1 << idx)


class _Signal:
    def __init__(self) -> None:
        self._slot = None

    def connect(self, slot):
        self._slot = slot

    def emit(self, *args, **kwargs):
        if callable(self._slot):
            self._slot(*args, **kwargs)


# ---------------------------------------------------------------------------
# Public helper

def patch_qt() -> None:
    """Install PyQt6 stubs into sys.modules if they are missing."""

    if "PyQt6" in sys.modules:
        return

    qt_core = types.ModuleType("PyQt6.QtCore")
    qt_core.Qt = SimpleNamespace(
        AlignmentFlag=_QtEnum(
            AlignCenter=None,
            AlignHCenter=None,
            AlignVCenter=None,
            AlignLeft=None,
            AlignRight=None,
            AlignTop=None,
        ),
        ItemDataRole=_QtEnum(DisplayRole=None, EditRole=None, UserRole=None),
        ItemFlag=_QtEnum(ItemIsEditable=None),
        SortOrder=_QtEnum(AscendingOrder=None, DescendingOrder=None),
        GlobalColor=_QtEnum(darkGray=None),
        AspectRatioMode=_QtEnum(KeepAspectRatio=None),
        TransformationMode=_QtEnum(SmoothTransformation=None),
    )
    qt_core.QPoint = _QtDummy
    qt_core.QTimer = _QtDummy
    qt_gui = types.ModuleType("PyQt6.QtGui")

    class _Pixmap:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._null = True

        def isNull(self) -> bool:
            return self._null

        def scaled(self, *args: Any, **kwargs: Any) -> "_Pixmap":
            return self

        def scaledToWidth(self, *args: Any, **kwargs: Any) -> "_Pixmap":
            return self

        def fill(self, *args: Any, **kwargs: Any) -> None:
            self._null = False

    qt_gui.QPixmap = _Pixmap
    qt_gui.QColor = _QtDummy
    qt_gui.QPainter = _QtDummy
    qt_gui.QAction = _QtDummy

    qt_widgets = types.ModuleType("PyQt6.QtWidgets")
    for name in [
        "QDialog",
        "QLabel",
        "QVBoxLayout",
        "QHBoxLayout",
        "QGridLayout",
        "QScrollArea",
        "QTabWidget",
        "QHeaderView",
        "QWidget",
        "QCheckBox",
        "QComboBox",
        "QGroupBox",
        "QPushButton",
        "QLineEdit",
        "QMessageBox",
        "QInputDialog",
        "QListWidget",
        "QListWidgetItem",
        "QStatusBar",
        "QMenu",
        "QToolButton",
    ]:
        setattr(qt_widgets, name, _QtDummy)

    class _TableWidgetItem(_QtDummy):
        def __init__(self, text: Any = "", *args: Any, **kwargs: Any) -> None:
            super().__init__()
            self._data = {}
            self._flags = 0
            self._text = text

        def setData(self, role: Any, value: Any) -> None:  # pragma: no cover - trivial
            self._data[role] = value

        def data(self, role: Any) -> Any:
            return self._data.get(role)

        def text(self) -> Any:
            return self._text

        def flags(self) -> int:
            return self._flags

        def setFlags(self, value: int) -> None:
            self._flags = value

    qt_widgets.QTableWidgetItem = _TableWidgetItem

    class _TableWidget(_QtDummy):
        EditTrigger = _QtEnum(NoEditTriggers=None)
        SelectionBehavior = _QtEnum(SelectRows=None)
        SelectionMode = _QtEnum(NoSelection=None)

        def __init__(self, rows: int = 0, columns: int = 0, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._row_count = rows
            self._column_count = columns
            self._headers = []
            self._items: dict[tuple[int, int], Any] = {}
            self._hidden_rows: dict[int, bool] = {}

        def setRowCount(self, count: int) -> None:
            self._row_count = count

        def setColumnCount(self, count: int) -> None:
            self._column_count = count

        def rowCount(self) -> int:
            return getattr(self, "_row_count", 0)

        def columnCount(self) -> int:
            return getattr(self, "_column_count", 0)

        def setHorizontalHeaderLabels(self, labels: Any) -> None:
            self._headers = list(labels) if labels is not None else []

        def horizontalHeaderItem(self, index: int):
            headers = getattr(self, "_headers", [])
            if 0 <= index < len(headers):
                return _TableWidgetItem(headers[index])
            return _TableWidgetItem(str(index))

        def setItem(self, row: int, column: int, item: Any) -> None:
            self._items[(row, column)] = item

        def item(self, row: int, column: int):
            return self._items.get((row, column))

        def setRowHidden(self, row: int, hidden: bool) -> None:
            self._hidden_rows[row] = hidden

        def sortItems(self, *args: Any, **kwargs: Any) -> None:
            pass

    qt_widgets.QTableWidget = _TableWidget

    class _Frame(_QtDummy):
        Shape = _QtEnum(StyledPanel=None)

    qt_widgets.QFrame = _Frame

    class _SpacerItem(_QtDummy):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__()

    qt_widgets.QSpacerItem = _SpacerItem

    class _SizePolicy(_QtDummy):
        Policy = _QtEnum(
            Fixed=None,
            Expanding=None,
            Preferred=None,
            Minimum=None,
        )

    qt_widgets.QSizePolicy = _SizePolicy

    class _ComboBox(_QtDummy):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._items = []
            self._current_index = 0

        def addItem(self, text: Any, data: Any = None) -> None:
            self._items.append((text, data))

        def setCurrentIndex(self, index: int) -> None:
            self._current_index = index

        def currentData(self) -> Any:
            if 0 <= self._current_index < len(self._items):
                return self._items[self._current_index][1]
            return None

    qt_widgets.QComboBox = _ComboBox

    class _HeaderView(_QtDummy):
        ResizeMode = _QtEnum(Stretch=None, ResizeToContents=None)

    qt_widgets.QHeaderView = _HeaderView

    qt_widgets.QApplication = _QtDummy

    sys.modules["PyQt6"] = types.ModuleType("PyQt6")
    sys.modules["PyQt6.QtCore"] = qt_core
    sys.modules["PyQt6.QtGui"] = qt_gui
    sys.modules["PyQt6.QtWidgets"] = qt_widgets
