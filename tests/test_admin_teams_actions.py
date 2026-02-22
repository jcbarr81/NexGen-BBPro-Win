from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ui.dashboard_core.context import DashboardContext
from ui.admin_dashboard.actions import teams as team_actions


def _build_context():
    return DashboardContext(
        base_path=Path("."),
        run_async=lambda worker: worker(),
        show_toast=None,
        register_cleanup=None,
    )


def test_auto_reassign_rosters_reports_success(monkeypatch):
    messages: list[tuple[str, str]] = []

    monkeypatch.setattr(team_actions, "auto_assign_all_teams", lambda **_kwargs: None)
    monkeypatch.setattr(
        team_actions,
        "load_players_from_csv",
        lambda _path: [SimpleNamespace(player_id="P1")],
    )
    monkeypatch.setattr(
        team_actions,
        "load_teams",
        lambda _path: [SimpleNamespace(team_id="AAA")],
    )
    monkeypatch.setattr(
        team_actions,
        "load_roster",
        lambda _team_id: SimpleNamespace(act=["P1"]),
    )
    monkeypatch.setattr(team_actions, "missing_positions", lambda _r, _p: [])
    monkeypatch.setattr(
        team_actions.QMessageBox,
        "information",
        lambda _parent, title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        team_actions.QMessageBox,
        "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )

    team_actions.auto_reassign_rosters(_build_context(), parent=object())

    assert ("Rosters Updated", "Auto reassigned rosters for all teams.") in messages


def test_auto_reassign_rosters_reports_failure(monkeypatch):
    messages: list[tuple[str, str]] = []

    monkeypatch.setattr(
        team_actions,
        "auto_assign_all_teams",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        team_actions.QMessageBox,
        "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )

    team_actions.auto_reassign_rosters(_build_context(), parent=object())

    assert ("Auto Reassign Failed", "boom") in messages
