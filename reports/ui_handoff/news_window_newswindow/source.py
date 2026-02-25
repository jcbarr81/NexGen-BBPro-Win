from __future__ import annotations

"""News Feed Viewer.

Displays the narrative/analytics news feed appended via utils.news_logger.
Simple text viewer with refresh and basic substring filter.
"""

try:
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QLineEdit,
        QTextEdit,
    )
except Exception:  # pragma: no cover - headless stubs
    class QDialog:
        def __init__(self, *a, **k): pass
        def show(self): pass
    class QLabel:
        def __init__(self, *a, **k): pass
        def setText(self, *a, **k): pass
    class QPushButton:
        def __init__(self, *a, **k): self._s=None
        def clicked(self, *a, **k): pass
    class QLineEdit:
        def __init__(self, *a, **k): self._t=""
        def text(self): return self._t
        def setText(self, t): self._t=t
    class QTextEdit:
        def __init__(self, *a, **k): pass
        def setReadOnly(self, *a, **k): pass
        def setPlainText(self, *a, **k): pass
    class QVBoxLayout:
        def __init__(self, *a, **k): pass
        def addWidget(self, *a, **k): pass
        def addLayout(self, *a, **k): pass
        def setContentsMargins(self, *a, **k): pass
        def setSpacing(self, *a, **k): pass
    class QHBoxLayout(QVBoxLayout): pass

from pathlib import Path
from utils.news_logger import NEWS_FILE, sanitize_news_text


class NewsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.setWindowTitle("News Feed")
            self.resize(800, 600)
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("Narrative & Analytics Feed")
        header.addWidget(self.title)
        header.addStretch()
        self.filter_edit = QLineEdit()
        try:
            self.filter_edit.setPlaceholderText("Filter (substring)...")
        except Exception:
            pass
        header.addWidget(self.filter_edit)
        self.refresh_btn = QPushButton("Refresh")
        try:
            self.refresh_btn.clicked.connect(self.refresh)
        except Exception:
            pass
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        self.text = QTextEdit()
        try:
            self.text.setReadOnly(True)
        except Exception:
            pass
        root.addWidget(self.text)

        self.refresh()

    def refresh(self) -> None:
        try:
            path = Path(NEWS_FILE)
            if not path.exists():
                self.text.setPlainText("No news yet.")
                return
            raw = path.read_text(encoding="utf-8")
            lines = [sanitize_news_text(line) for line in raw.splitlines()]
            txt = "\n".join(lines)
            term = ""
            try:
                term = self.filter_edit.text().strip()
            except Exception:
                term = ""
            if term:
                filtered = "\n".join(line for line in txt.splitlines() if term.lower() in line.lower())
                self.text.setPlainText(filtered or "(no matches)")
            else:
                self.text.setPlainText(txt)
        except Exception:
            try:
                self.text.setPlainText("Failed to load news feed.")
            except Exception:
                pass


__all__ = ["NewsWindow"]
