from __future__ import annotations

"""Simple multi-step tutorial dialog with next/previous controls."""

from dataclasses import dataclass
from typing import Iterable, List

try:  # pragma: no cover - PyQt fallback stubs
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QLabel,
        QTextBrowser,
        QDialogButtonBox,
        QPushButton,
        QWidget,
    )
    from PyQt6.QtCore import Qt
except Exception:  # pragma: no cover
    class QWidget:
        def __init__(self, *a, **k): ...

    class QDialog(QWidget):
        def exec(self): return 0
        def reject(self): ...

    class QLabel(QWidget):
        def __init__(self, text="", *a, **k): self._text = text
        def setText(self, text): self._text = text

    class QTextBrowser(QWidget):
        def setHtml(self, *_): ...

    class QPushButton(QWidget):
        def __init__(self, *a, **k): ...

    class QDialogButtonBox(QWidget):
        def __init__(self, *a, **k):
            self.accepted = lambda *a, **k: None
            self.rejected = lambda *a, **k: None
        class StandardButton:
            Close = 0

    class QVBoxLayout:
        def __init__(self, *a, **k): ...
        def addWidget(self, *a, **k): ...
        def addLayout(self, *a, **k): ...
        def setContentsMargins(self, *a, **k): ...
        def setSpacing(self, *a, **k): ...

    class Qt:
        AlignmentFlag = type("AlignmentFlag", (), {"AlignCenter": 0})


@dataclass
class TutorialStep:
    title: str
    body_html: str


class TutorialDialog(QDialog):
    def __init__(self, *, title: str, steps: Iterable[TutorialStep], parent=None):
        super().__init__(parent)
        self.steps: List[TutorialStep] = list(steps)
        self._index = 0
        self.setWindowTitle(title)
        self.resize(560, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self.step_label = QLabel("")
        self.step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(self.step_label)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet("background: transparent; border: none; font-size: 14px;")
        root.addWidget(self.browser)

        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        controls.addButton(self.prev_btn, QDialogButtonBox.ButtonRole.ActionRole)
        controls.addButton(self.next_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.prev_btn.clicked.connect(self._prev_step)
        self.next_btn.clicked.connect(self._next_step)
        controls.rejected.connect(self.reject)
        root.addWidget(controls)
        self._refresh()

    def _refresh(self) -> None:
        if not self.steps:
            self.step_label.setText("No tutorial steps.")
            self.browser.setHtml("")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        self._index = max(0, min(self._index, len(self.steps) - 1))
        step = self.steps[self._index]
        self.step_label.setText(f"Step {self._index + 1} of {len(self.steps)} - {step.title}")
        self.browser.setHtml(step.body_html)
        self.prev_btn.setEnabled(self._index > 0)
        has_next = self._index < len(self.steps) - 1
        self.next_btn.setEnabled(True)
        self.next_btn.setText("Next" if has_next else "Finish")

    def _prev_step(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._refresh()

    def _next_step(self) -> None:
        if self._index < len(self.steps) - 1:
            self._index += 1
            self._refresh()
        else:
            self.accept()


__all__ = ["TutorialDialog", "TutorialStep"]
