from __future__ import annotations

from pathlib import Path

import ui.export_dialogs as export_dialogs


class _FakeMessageBox:
    class Icon:
        Information = object()

    class ButtonRole:
        ActionRole = object()
        AcceptRole = object()

    next_click = "open"
    warnings: list[tuple[str, str]] = []
    infos: list[tuple[str, str]] = []

    def __init__(self, _parent=None) -> None:
        self._open_button = None
        self._close_button = None
        self._clicked = None

    def setWindowTitle(self, _title: str) -> None:
        return None

    def setIcon(self, _icon) -> None:
        return None

    def setText(self, _text: str) -> None:
        return None

    def addButton(self, text: str, _role):
        button = {"text": text}
        if text == "Open Folder":
            self._open_button = button
        if text == "Close":
            self._close_button = button
        return button

    def setDefaultButton(self, _button) -> None:
        return None

    def exec(self) -> None:
        if self.next_click == "open":
            self._clicked = self._open_button
        else:
            self._clicked = self._close_button

    def clickedButton(self):
        return self._clicked

    @staticmethod
    def warning(_parent, title: str, message: str) -> None:
        _FakeMessageBox.warnings.append((title, message))

    @staticmethod
    def information(_parent, title: str, message: str) -> None:
        _FakeMessageBox.infos.append((title, message))


def test_show_export_success_dialog_opens_folder(monkeypatch, tmp_path: Path) -> None:
    _FakeMessageBox.next_click = "open"
    _FakeMessageBox.warnings.clear()
    _FakeMessageBox.infos.clear()
    monkeypatch.setattr(export_dialogs, "QMessageBox", _FakeMessageBox)

    opened: list[Path] = []
    monkeypatch.setattr(
        export_dialogs,
        "open_containing_folder",
        lambda path: opened.append(Path(path)),
    )

    export_dialogs.show_export_success_dialog(
        parent=None,
        title="Export",
        message="Done",
        export_path=tmp_path / "export.zip",
    )

    assert opened == [tmp_path / "export.zip"]


def test_show_export_success_dialog_no_open_when_close_clicked(monkeypatch, tmp_path: Path) -> None:
    _FakeMessageBox.next_click = "close"
    _FakeMessageBox.warnings.clear()
    _FakeMessageBox.infos.clear()
    monkeypatch.setattr(export_dialogs, "QMessageBox", _FakeMessageBox)

    opened: list[Path] = []
    monkeypatch.setattr(
        export_dialogs,
        "open_containing_folder",
        lambda path: opened.append(Path(path)),
    )

    export_dialogs.show_export_success_dialog(
        parent=None,
        title="Export",
        message="Done",
        export_path=tmp_path / "export.zip",
    )

    assert opened == []


def test_show_export_success_dialog_warns_when_open_fails(monkeypatch, tmp_path: Path) -> None:
    _FakeMessageBox.next_click = "open"
    _FakeMessageBox.warnings.clear()
    _FakeMessageBox.infos.clear()
    monkeypatch.setattr(export_dialogs, "QMessageBox", _FakeMessageBox)

    def _raise(_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(export_dialogs, "open_containing_folder", _raise)

    export_dialogs.show_export_success_dialog(
        parent=None,
        title="Export",
        message="Done",
        export_path=tmp_path / "export.zip",
    )

    assert _FakeMessageBox.warnings
    assert _FakeMessageBox.warnings[0][0] == "Export"
    assert "Unable to open export folder" in _FakeMessageBox.warnings[0][1]
