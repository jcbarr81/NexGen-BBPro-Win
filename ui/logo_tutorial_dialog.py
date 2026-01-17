"""Static tutorial dialog for team logo workflows."""

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
<h3>Generate Logos (Auto)</h3>
<ul>
  <li>Open <b>Admin Dashboard</b> &gt; <b>Utilities</b> &gt; <b>Generate Team Logos</b>.</li>
  <li>Logos are written to <code>logo/teams/&lt;team_id&gt;.png</code> (team_id is lower-case).</li>
  <li>Running the generator replaces existing logos in <code>logo/teams</code>.</li>
  <li>If the OpenAI client is not configured, the legacy auto-logo generator is used.</li>
</ul>
<h3>Manual Overrides</h3>
<ul>
  <li>Create a PNG and name it <code>&lt;team_id&gt;.png</code>.</li>
  <li>Place the file in <code>logo/teams/</code> to override the generated logo.</li>
  <li>Team IDs can be found in <code>data/teams.csv</code>.</li>
  <li>Square PNGs work best (512x512 or 1024x1024 recommended).</li>
</ul>
<p><b>Tip:</b> Reopen the team screen after replacing a logo to refresh the view.</p>
"""


class LogoTutorialDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Team Logo Tutorial")
        self.resize(600, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Creating and managing team logos")
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


__all__ = ["LogoTutorialDialog"]
