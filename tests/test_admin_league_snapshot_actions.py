from __future__ import annotations

from pathlib import Path

from ui.dashboard_core.context import DashboardContext
from ui.admin_dashboard.actions import league_snapshot as snapshot_actions


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


def test_export_league_snapshot_success_with_future_callback(monkeypatch):
    toasts: list[tuple[str, str]] = []
    scheduled: list[str] = []

    monkeypatch.setattr(
        snapshot_actions,
        "export_league_snapshot",
        lambda: {"status": "success", "path": "snapshot.zip"},
    )
    monkeypatch.setattr(
        snapshot_actions,
        "_schedule",
        lambda callback: (scheduled.append("queued"), callback()),
    )

    context = DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: _ImmediateFuture(worker()),
        show_toast=lambda kind, msg: toasts.append((kind, msg)),
        register_cleanup=None,
    )

    snapshot_actions.export_league_snapshot_action(context, parent=None)

    assert "queued" in scheduled
    assert ("info", "Exporting league snapshot...") in toasts
    assert ("success", "League snapshot exported.") in toasts


def test_export_league_snapshot_success_with_sync_worker(monkeypatch):
    toasts: list[tuple[str, str]] = []

    monkeypatch.setattr(
        snapshot_actions,
        "export_league_snapshot",
        lambda: {"status": "success", "path": "snapshot.zip"},
    )
    monkeypatch.setattr(snapshot_actions, "_schedule", lambda callback: callback())

    context = DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: worker(),
        show_toast=lambda kind, msg: toasts.append((kind, msg)),
        register_cleanup=None,
    )

    snapshot_actions.export_league_snapshot_action(context, parent=None)

    assert ("success", "League snapshot exported.") in toasts


def test_export_league_snapshot_with_parent_uses_export_dialog(monkeypatch):
    toasts: list[tuple[str, str]] = []
    dialogs: list[dict[str, object]] = []
    parent = object()

    monkeypatch.setattr(
        snapshot_actions,
        "export_league_snapshot",
        lambda: {"status": "success", "path": "snapshot.zip"},
    )
    monkeypatch.setattr(snapshot_actions, "_schedule", lambda callback: callback())
    monkeypatch.setattr(snapshot_actions, "QProgressDialog", _FakeProgressDialog)
    monkeypatch.setattr(
        snapshot_actions,
        "show_export_success_dialog",
        lambda **kwargs: dialogs.append(kwargs),
    )

    context = DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: worker(),
        show_toast=lambda kind, msg: toasts.append((kind, msg)),
        register_cleanup=None,
    )

    snapshot_actions.export_league_snapshot_action(context, parent=parent)

    assert dialogs
    assert dialogs[0]["parent"] is parent
    assert dialogs[0]["export_path"] == "snapshot.zip"
    assert ("success", "League snapshot exported.") in toasts
