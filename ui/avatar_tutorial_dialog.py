"""Static tutorial dialog for player avatar workflows."""

from __future__ import annotations

try:  # pragma: no cover - PyQt fallback stubs
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QLabel,
        QTextBrowser,
        QPushButton,
        QHBoxLayout,
    )
except Exception:  # pragma: no cover
    class QDialog:
        def __init__(self, *a, **k): ...
        def exec(self): return 0
        def accept(self): ...

    class QLabel:
        def __init__(self, *a, **k): ...
        def setText(self, *a, **k): ...
        def setWordWrap(self, *a, **k): ...

    class QTextBrowser:
        def __init__(self, *a, **k): ...
        def setHtml(self, *a, **k): ...
        def setOpenExternalLinks(self, *a, **k): ...
        def setStyleSheet(self, *a, **k): ...

    class QPushButton:
        def __init__(self, *a, **k): ...
        def clicked(self, *a, **k): ...

    class QVBoxLayout:
        def __init__(self, *a, **k): ...
        def addWidget(self, *a, **k): ...
        def addLayout(self, *a, **k): ...
        def setContentsMargins(self, *a, **k): ...
        def setSpacing(self, *a, **k): ...

    class QHBoxLayout(QVBoxLayout):
        def addStretch(self, *a, **k): ...


_BODY_HTML = """
<h3>Generate Avatars (Auto)</h3>
<ul>
  <li>Open <b>Admin Dashboard</b> &gt; <b>Utilities</b> &gt; <b>Generate Player Avatars</b>.</li>
  <li>Choose <b>Yes</b> for initial creation to rebuild all avatars (keeps only <code>Template</code> and <code>default.png</code>).</li>
  <li>Choose <b>No</b> to fill only missing avatars.</li>
  <li>Output images are written to <code>images/avatars/&lt;player_id&gt;.png</code>.</li>
  <li>Templates live in <code>images/avatars/Template</code> and are recolored using team colors.</li>
</ul>
<h3>Manual Overrides</h3>
<ul>
  <li>Create a PNG for the player and name it <code>&lt;player_id&gt;.png</code>.</li>
  <li>Place the file in <code>images/avatars/</code> to override the generated image.</li>
  <li>Player IDs can be found in <code>data/players.csv</code>.</li>
  <li>Square PNGs work best (256x256 or 512x512 recommended).</li>
  <li>Profiles fall back to <code>images/avatars/default.png</code> if no file exists.</li>
</ul>
<p><b>Tip:</b> Reopen the player profile dialog after replacing an avatar to see the change.</p>
"""


class AvatarTutorialDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Player Avatar Tutorial")
        self.resize(600, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Creating and managing player avatars")
        try:
            title.setStyleSheet("font-size: 16px; font-weight: 600;")
        except Exception:
            pass
        root.addWidget(title)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setStyleSheet("background: transparent; border: none; font-size: 13px;")
        body.setHtml(_BODY_HTML)
        root.addWidget(body, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Close")
        try:
            close_btn.clicked.connect(self.accept)
        except Exception:
            pass
        row.addWidget(close_btn)
        root.addLayout(row)


__all__ = ["AvatarTutorialDialog"]
