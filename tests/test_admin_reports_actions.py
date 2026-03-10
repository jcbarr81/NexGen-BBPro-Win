from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ui.dashboard_core.context import DashboardContext
from ui.admin_dashboard.actions import reports as reports_actions


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


def test_export_reports_success_with_parent_uses_export_dialog(monkeypatch):
    toasts: list[tuple[str, str]] = []
    dialogs: list[dict[str, object]] = []
    opened: list[str] = []
    parent = object()
    calls: list[dict[str, object]] = []

    def _fake_export_reports(**kwargs):
        calls.append(dict(kwargs))
        return SimpleNamespace(
            output_dir=Path("exports/out"),
            pdf_written=False,
            files={"reports_index_html": Path("exports/out/reports_index.html")},
        )

    monkeypatch.setattr(reports_actions, "export_reports", _fake_export_reports)
    monkeypatch.setattr(reports_actions.webbrowser, "open", lambda value: opened.append(str(value)))
    monkeypatch.setattr(
        reports_actions,
        "show_export_success_dialog",
        lambda **kwargs: dialogs.append(kwargs),
    )
    monkeypatch.setattr(
        reports_actions.QTimer,
        "singleShot",
        lambda _ms, callback: callback(),
    )
    monkeypatch.setattr(reports_actions, "QProgressDialog", _FakeProgressDialog)

    context = DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: _ImmediateFuture(worker()),
        show_toast=lambda kind, msg: toasts.append((kind, msg)),
        register_cleanup=None,
    )

    reports_actions.export_reports_action(context, parent=parent, export_format="html")

    assert dialogs
    assert dialogs[0]["parent"] is parent
    assert Path(str(dialogs[0]["export_path"])) == Path("exports/out")
    assert ("success", "HTML reports exported.") in toasts
    assert opened
    assert calls and calls[0].get("report_format") == "html"
    assert calls[0].get("include_csv") is False


def test_export_reports_csv_mode_uses_csv_settings(monkeypatch):
    toasts: list[tuple[str, str]] = []
    calls: list[dict[str, object]] = []
    parent = object()

    def _fake_export_reports(**kwargs):
        calls.append(dict(kwargs))
        return SimpleNamespace(output_dir=Path("exports/out"), pdf_written=True, files={})

    monkeypatch.setattr(reports_actions, "export_reports", _fake_export_reports)
    monkeypatch.setattr(
        reports_actions,
        "show_export_success_dialog",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        reports_actions.QTimer,
        "singleShot",
        lambda _ms, callback: callback(),
    )
    monkeypatch.setattr(reports_actions, "QProgressDialog", _FakeProgressDialog)

    context = DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: _ImmediateFuture(worker()),
        show_toast=lambda kind, msg: toasts.append((kind, msg)),
        register_cleanup=None,
    )

    reports_actions.export_reports_action(context, parent=parent, export_format="csv")

    assert calls and calls[0].get("report_format") == "csv"
    assert calls[0].get("include_csv") is True
    assert calls[0].get("include_pdf") is True
    assert ("success", "CSV reports exported.") in toasts
