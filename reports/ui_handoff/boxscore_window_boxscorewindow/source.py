from __future__ import annotations

from pathlib import Path
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit


class BoxScoreWindow(QDialog):
    """Simple dialog to display a box score HTML file."""

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        try:
            self.setWindowTitle("Box Score")
            self.setGeometry(100, 100, 800, 600)
        except Exception:  # pragma: no cover - dummy widgets
            pass

        layout = QVBoxLayout(self)
        self.viewer = QTextEdit()
        try:
            self.viewer.setReadOnly(True)
            self.viewer.setMinimumHeight(560)
        except Exception:  # pragma: no cover
            pass
        layout.addWidget(self.viewer)

        try:
            html = Path(path).read_text(encoding="utf-8")
        except OSError:
            html = "<html><body><p>Box score not available.</p></body></html>"
        try:
            self.viewer.setHtml(html)
        except Exception:  # pragma: no cover
            pass
