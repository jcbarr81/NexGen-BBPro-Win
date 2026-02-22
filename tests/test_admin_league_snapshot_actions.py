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
