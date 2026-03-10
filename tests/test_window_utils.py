from __future__ import annotations

from tests.qt_stubs import patch_qt


def test_show_on_top_exec_window_uses_on_top(monkeypatch):
    patch_qt()
    import ui.window_utils as window_utils

    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        window_utils,
        "ensure_on_top",
        lambda window: calls.append(("ensure", window)),
    )

    class _Dialog:
        def exec(self):
            return 7

    dialog = _Dialog()
    result = window_utils.show_on_top(dialog)

    assert result == 7
    assert calls == [("ensure", dialog)]


def test_show_on_top_main_window_clears_on_top(monkeypatch):
    patch_qt()
    import ui.window_utils as window_utils

    calls: list[tuple[str, object]] = []

    class _MainWindow:
        def __init__(self):
            self.shown = False
            self.raised = False
            self.activated = False

        def show(self) -> None:
            self.shown = True

        def raise_(self) -> None:
            self.raised = True

        def activateWindow(self) -> None:
            self.activated = True

    monkeypatch.setattr(window_utils, "QMainWindow", _MainWindow)
    monkeypatch.setattr(
        window_utils,
        "remove_on_top",
        lambda window: calls.append(("remove", window)),
    )
    monkeypatch.setattr(
        window_utils,
        "ensure_on_top",
        lambda window: calls.append(("ensure", window)),
    )

    window = _MainWindow()
    result = window_utils.show_on_top(window)

    assert result is None
    assert calls == [("remove", window)]
    assert window.shown is True
    assert window.raised is True
    assert window.activated is True


def test_show_on_top_regular_window_keeps_on_top(monkeypatch):
    patch_qt()
    import ui.window_utils as window_utils

    calls: list[tuple[str, object]] = []

    class _Window:
        def show(self) -> None:
            return None

        def raise_(self) -> None:
            return None

        def activateWindow(self) -> None:
            return None

    class _MainWindowMarker:
        pass

    monkeypatch.setattr(window_utils, "QMainWindow", _MainWindowMarker)
    monkeypatch.setattr(
        window_utils,
        "remove_on_top",
        lambda window: calls.append(("remove", window)),
    )
    monkeypatch.setattr(
        window_utils,
        "ensure_on_top",
        lambda window: calls.append(("ensure", window)),
    )

    window = _Window()
    result = window_utils.show_on_top(window)

    assert result is None
    assert calls == [("ensure", window)]
