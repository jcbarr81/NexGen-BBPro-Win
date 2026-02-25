from __future__ import annotations

"""In-app searchable HTML manual viewer."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

try:  # pragma: no cover - PyQt fallback stubs
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor, QTextDocument
    from PyQt6.QtWidgets import (
        QComboBox,
        QDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QTextBrowser,
        QVBoxLayout,
    )
except Exception:  # pragma: no cover
    class QDialog:
        def __init__(self, *args, **kwargs): ...
        def setWindowTitle(self, *_args, **_kwargs): ...
        def resize(self, *_args, **_kwargs): ...
        def exec(self): return 0

    class QLabel:
        def __init__(self, *_args, **_kwargs): ...
        def setStyleSheet(self, *_args, **_kwargs): ...
        def setWordWrap(self, *_args, **_kwargs): ...
        def setText(self, *_args, **_kwargs): ...

    class QLineEdit:
        def __init__(self, *_args, **_kwargs): ...
        def setPlaceholderText(self, *_args, **_kwargs): ...
        def text(self) -> str: return ""
        class _Signal:
            def connect(self, *_args, **_kwargs): ...
        @property
        def returnPressed(self):
            return self._Signal()
        @property
        def textChanged(self):
            return self._Signal()

    class QPushButton:
        def __init__(self, *_args, **_kwargs): ...
        class _Signal:
            def connect(self, *_args, **_kwargs): ...
        @property
        def clicked(self):
            return self._Signal()

    class QComboBox:
        def __init__(self, *_args, **_kwargs):
            self._items = []
            self._index = 0
        def addItem(self, label, user_data):
            self._items.append((label, user_data))
        def setCurrentIndex(self, index): self._index = index
        def currentData(self):
            if 0 <= self._index < len(self._items):
                return self._items[self._index][1]
            return ""
        class _Signal:
            def connect(self, *_args, **_kwargs): ...
        @property
        def currentIndexChanged(self):
            return self._Signal()

    class QTextBrowser:
        def __init__(self, *_args, **_kwargs): ...
        def setOpenExternalLinks(self, *_args, **_kwargs): ...
        def setStyleSheet(self, *_args, **_kwargs): ...
        def setHtml(self, *_args, **_kwargs): ...
        def setTextCursor(self, *_args, **_kwargs): ...
        def textCursor(self): return QTextCursor()
        def find(self, *_args, **_kwargs) -> bool: return False

    class QVBoxLayout:
        def __init__(self, *_args, **_kwargs): ...
        def addWidget(self, *_args, **_kwargs): ...
        def addLayout(self, *_args, **_kwargs): ...
        def setContentsMargins(self, *_args, **_kwargs): ...
        def setSpacing(self, *_args, **_kwargs): ...

    class QHBoxLayout(QVBoxLayout):
        def addStretch(self, *_args, **_kwargs): ...

    class QTextCursor:
        class MoveOperation:
            Start = 0
            End = 1
        def movePosition(self, *_args, **_kwargs): ...

    class QTextDocument:
        class FindFlag:
            FindBackward = 1

    class Qt:
        AlignmentFlag = type("AlignmentFlag", (), {"AlignRight": 0})

from utils.path_utils import get_base_dir

DOC_GAME_MANUAL = "game_manual"
DOC_FINANCE_MANUAL = "finance_manual"


@dataclass(frozen=True)
class ManualSpec:
    doc_id: str
    title: str
    filename: str
    description: str


MANUAL_SPECS: List[ManualSpec] = [
    ManualSpec(
        doc_id=DOC_GAME_MANUAL,
        title="Complete Game Manual",
        filename="game_manual.html",
        description="End-to-end game reference covering all major workflows.",
    ),
    ManualSpec(
        doc_id=DOC_FINANCE_MANUAL,
        title="Finance System Manual",
        filename="finance_system_manual.html",
        description="Detailed finance modules, terms, timing, and operational flow.",
    ),
]
MANUAL_BY_ID: Dict[str, ManualSpec] = {item.doc_id: item for item in MANUAL_SPECS}


def get_manual_specs() -> List[ManualSpec]:
    return list(MANUAL_SPECS)


def resolve_manual_path(doc_id: str) -> Path:
    spec = MANUAL_BY_ID.get(str(doc_id or "").strip())
    if spec is None:
        raise KeyError(f"Unknown manual id: {doc_id}")
    return get_base_dir() / "docs" / "manuals" / spec.filename


def load_manual_html(doc_id: str) -> str:
    spec = MANUAL_BY_ID.get(str(doc_id or "").strip())
    if spec is None:
        return "<h2>Manual not found.</h2><p>The requested manual is not available.</p>"
    manual_path = resolve_manual_path(spec.doc_id)
    if manual_path.exists():
        try:
            return manual_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return (
        f"<h2>{spec.title}</h2>"
        "<p>This manual file is missing from the current installation.</p>"
        f"<p>Expected path: <code>{manual_path}</code></p>"
    )


class ManualViewerDialog(QDialog):
    """Searchable HTML viewer for in-app manuals."""

    def __init__(
        self,
        *,
        initial_doc_id: str = DOC_GAME_MANUAL,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Game Manuals")
        self.resize(980, 720)
        self._doc_id = DOC_GAME_MANUAL
        self._doc_specs = get_manual_specs()
        self._doc_index: Mapping[str, ManualSpec] = {
            spec.doc_id: spec for spec in self._doc_specs
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Game Reference Manuals")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(QLabel("Manual:"))
        self.doc_selector = QComboBox()
        for spec in self._doc_specs:
            self.doc_selector.addItem(spec.title, spec.doc_id)
        self.doc_selector.currentIndexChanged.connect(self._on_doc_changed)
        top_row.addWidget(self.doc_selector, 1)
        root.addLayout(top_row)

        self.description_label = QLabel("")
        self.description_label.setWordWrap(True)
        root.addWidget(self.description_label)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search this manual...")
        self.search_input.returnPressed.connect(self.find_next)
        self.search_input.textChanged.connect(self._clear_search_status)
        search_row.addWidget(self.search_input, 1)
        prev_btn = QPushButton("Find Previous")
        prev_btn.clicked.connect(self.find_previous)
        search_row.addWidget(prev_btn)
        next_btn = QPushButton("Find Next")
        next_btn.clicked.connect(self.find_next)
        search_row.addWidget(next_btn)
        root.addLayout(search_row)

        self.search_status = QLabel("")
        self.search_status.setWordWrap(True)
        root.addWidget(self.search_status)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet("font-size: 13px;")
        root.addWidget(self.browser, 1)

        self._set_doc(initial_doc_id)

    def _on_doc_changed(self, _index: int) -> None:
        self._set_doc(str(self.doc_selector.currentData() or DOC_GAME_MANUAL))

    def _set_doc(self, doc_id: str) -> None:
        if doc_id not in self._doc_index:
            doc_id = DOC_GAME_MANUAL
        self._doc_id = doc_id
        # Keep selector in sync when opened with a specific initial doc id.
        for idx, spec in enumerate(self._doc_specs):
            if spec.doc_id == doc_id:
                self.doc_selector.setCurrentIndex(idx)
                break
        spec = self._doc_index.get(doc_id)
        if spec is not None:
            self.description_label.setText(spec.description)
        self.browser.setHtml(load_manual_html(doc_id))
        self._reset_browser_cursor(to_end=False)
        self._clear_search_status()

    def _reset_browser_cursor(self, *, to_end: bool) -> None:
        try:
            cursor = self.browser.textCursor()
            if to_end:
                cursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.browser.setTextCursor(cursor)
        except Exception:
            pass

    def _clear_search_status(self, *_args) -> None:
        self.search_status.setText("")

    def find_next(self) -> None:
        self._find_with_wrap(backward=False)

    def find_previous(self) -> None:
        self._find_with_wrap(backward=True)

    def _find_with_wrap(self, *, backward: bool) -> None:
        query = str(self.search_input.text() or "").strip()
        if not query:
            self.search_status.setText("Enter text to search.")
            return

        if backward:
            flag = QTextDocument.FindFlag.FindBackward
        else:
            try:
                flag = QTextDocument.FindFlag(0)
            except Exception:
                flag = 0
        try:
            found = self.browser.find(query, flag)
        except Exception:
            found = False
        if found:
            self.search_status.setText(f'Found "{query}".')
            return

        self._reset_browser_cursor(to_end=backward)
        try:
            found_after_wrap = self.browser.find(query, flag)
        except Exception:
            found_after_wrap = False
        if found_after_wrap:
            self.search_status.setText(f'Wrapped and found "{query}".')
        else:
            self.search_status.setText(f'No matches for "{query}" in this manual.')


__all__ = [
    "DOC_FINANCE_MANUAL",
    "DOC_GAME_MANUAL",
    "ManualViewerDialog",
    "ManualSpec",
    "get_manual_specs",
    "load_manual_html",
    "resolve_manual_path",
]
