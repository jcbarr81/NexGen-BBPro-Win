from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ui.dashboard_core.context import DashboardContext
from ui.admin_dashboard.actions import almanac as almanac_actions


class _ImmediateFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value

    def add_done_callback(self, callback):
        callback(self)

    def cancel(self):
        return False


class _FakeProgressDialog:
    def __init__(self, *_args, **_kwargs):
        pass

    def setWindowTitle(self, *_args, **_kwargs):
        return None

    def setWindowModality(self, *_args, **_kwargs):
        return None

    def setCancelButton(self, *_args, **_kwargs):
        return None

    def setMinimumDuration(self, *_args, **_kwargs):
        return None

    def setAutoClose(self, *_args, **_kwargs):
        return None

    def setAutoReset(self, *_args, **_kwargs):
        return None

    def setValue(self, *_args, **_kwargs):
        return None

    def show(self):
        return None

    def close(self):
        return None


def test_export_almanac_success_with_parent(monkeypatch):
    toasts: list[tuple[str, str]] = []
    dialogs: list[dict[str, object]] = []
    opened: list[str] = []
    parent = object()

    monkeypatch.setattr(
        almanac_actions,
        "export_almanac",
        lambda: SimpleNamespace(
            output_dir=Path("exports/almanac_out"),
            index_html=Path("exports/almanac_out/almanac/index.html"),
            season_ids=["test-2025", "test-2026"],
        ),
    )
    monkeypatch.setattr(
        almanac_actions.webbrowser,
        "open",
        lambda value: opened.append(str(value)),
    )
    monkeypatch.setattr(
        almanac_actions,
        "show_export_success_dialog",
        lambda **kwargs: dialogs.append(kwargs),
    )
    monkeypatch.setattr(
        almanac_actions.QTimer,
        "singleShot",
        lambda _ms, callback: callback(),
    )
    monkeypatch.setattr(
        almanac_actions,
        "QProgressDialog",
        _FakeProgressDialog,
    )

    context = DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: _ImmediateFuture(worker()),
        show_toast=lambda kind, msg: toasts.append((kind, msg)),
        register_cleanup=None,
    )

    almanac_actions.export_almanac_action(context, parent=parent)

    assert dialogs
    assert dialogs[0]["parent"] is parent
    assert Path(str(dialogs[0]["export_path"])) == Path("exports/almanac_out")
    assert opened
    assert ("success", "League almanac exported.") in toasts
