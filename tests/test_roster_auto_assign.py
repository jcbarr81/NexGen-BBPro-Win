from __future__ import annotations

from types import SimpleNamespace

from services import roster_auto_assign


def test_auto_assign_all_teams_reports_progress(monkeypatch):
    teams = [SimpleNamespace(team_id="AAA"), SimpleNamespace(team_id="BBB")]
    players = [SimpleNamespace(player_id="P1"), SimpleNamespace(player_id="P2")]
    assign_calls: list[str] = []
    progress_events: list[tuple[str, int, int]] = []

    monkeypatch.setattr(roster_auto_assign, "load_teams", lambda _path: teams)
    monkeypatch.setattr(
        roster_auto_assign,
        "load_players_from_csv",
        lambda _path: players,
    )
    monkeypatch.setattr(roster_auto_assign, "load_users", lambda _path: [])
    monkeypatch.setattr(
        roster_auto_assign,
        "auto_assign_team",
        lambda team_id, **_kwargs: assign_calls.append(team_id),
    )
    monkeypatch.setattr(
        roster_auto_assign,
        "auto_fill_lineup_for_team",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        roster_auto_assign.load_roster,
        "cache_clear",
        lambda: None,
    )

    roster_auto_assign.auto_assign_all_teams(
        progress_callback=lambda phase, done, total: progress_events.append(
            (phase, done, total)
        )
    )

    assert assign_calls == ["AAA", "BBB"]
    assert progress_events
    assert progress_events[0] == ("Loading", 0, 2)
    assert ("Processing", 0, 2) in progress_events
    assert ("Processing", 1, 2) in progress_events
    assert ("Saving", 1, 2) in progress_events
    assert ("Saving", 2, 2) in progress_events
    assert progress_events[-1] == ("Complete", 2, 2)
