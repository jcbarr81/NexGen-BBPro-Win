"""8.2.3: a player's seasons run oldest first, each with its own club.

An owner showed a free agent's pitching table: 2027 (a row of dashes) on
top, then "2026 (ALPHA-TEST)" with no age and "--" for the team, though he
had pitched all season for Baltimore. The rollover now records each
season's club(s) in the career ledger, and the profile lists seasons oldest
first, the current one last (once played), then Career.
"""

from __future__ import annotations

from types import SimpleNamespace

from services import player_profile_view_model as vm
from services.season_teams import season_team_labels


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_clubs_from_rosters_trades_and_releases(tmp_path):
    _write(tmp_path / "rosters" / "BAL.csv", "P1,ACT\nP2,AAA\nP4,DL15\n")
    _write(tmp_path / "rosters" / "BOS.csv", "P3,ACT\n")
    _write(tmp_path / "rosters" / "BOS_pitching.csv", "P9,SP1\n")
    _write(
        tmp_path / "transactions.csv",
        "timestamp,season_date,team_id,player_id,player_name,action,from_level,to_level,counterparty,details\n"
        "t,2026-05-20,CHA,P3,X,trade_out,ACT,ACT,BOS,\n"
        "t,2026-05-20,BOS,P3,X,trade_in,ACT,ACT,CHA,\n"
        "t,2026-07-21,COL,P5,Y,cut,AAA,FA,,Released to free agency\n",
    )
    labels = season_team_labels(tmp_path)
    assert labels["P1"] == "BAL"
    assert labels["P4"] == "BAL"  # the injured list counts
    assert labels["P3"] == "CHA/BOS"
    assert labels["P5"] == "COL"  # released during the season
    assert "P9" not in labels  # staff files are not rosters


def _player(history, season=None, birthdate="1999-10-01"):
    return SimpleNamespace(
        player_id="P1", birthdate=birthdate,
        season_stats=season or {}, career_history=history,
    )


def test_seasons_run_oldest_first_with_their_own_clubs(monkeypatch):
    monkeypatch.setattr(vm, "_current_season_year", lambda: 2027)
    monkeypatch.setattr(vm, "_current_league_token", lambda: "ALPHA-TEST")
    history = {
        "alpha-test-2026": {"g": 59, "outs": 235, "er": 37, "team": "BAL"},
        "alpha-test-2025": {"g": 40, "outs": 150, "er": 20, "team": "CHA/BOS"},
    }
    rows = vm._collect_stats_rows(
        _player(history, season={"g": 3, "outs": 9, "er": 1}),
        team_id="", is_pitcher=True,
    )
    labels = [label for label, _ in rows]
    assert labels == ["2025", "2026", "2027", "Career"]
    by = dict(rows)
    assert by["2025"]["team"] == "CHA/BOS"
    assert by["2026"]["team"] == "BAL"
    assert by["2026"]["age"] == 26  # born Oct 1999: 26 on July 1, 2026
    assert by["Career"]["g"] == 102


def test_an_unplayed_current_season_is_left_out(monkeypatch):
    monkeypatch.setattr(vm, "_current_season_year", lambda: 2027)
    monkeypatch.setattr(vm, "_current_league_token", lambda: "ALPHA-TEST")
    rows = vm._collect_stats_rows(
        _player({"alpha-test-2026": {"g": 59, "outs": 235, "team": "BAL"}},
                season={"w": 0, "l": 0}),
        team_id="", is_pitcher=True,
    )
    assert [label for label, _ in rows] == ["2026", "Career"]


def test_a_season_with_no_recorded_club_is_not_given_the_current_one(monkeypatch):
    """Seasons archived before 8.2.3 carry no club: they show none rather
    than the club the player is with now."""
    monkeypatch.setattr(vm, "_current_season_year", lambda: 2027)
    monkeypatch.setattr(vm, "_current_league_token", lambda: "ALPHA-TEST")
    rows = dict(vm._collect_stats_rows(
        _player({"alpha-test-2026": {"g": 10, "outs": 30}}),
        team_id="NYY", is_pitcher=True,
    ))
    assert "team" not in rows["2026"]


def test_another_leagues_season_keeps_its_name(monkeypatch):
    monkeypatch.setattr(vm, "_current_league_token", lambda: "ALPHA-TEST")
    assert vm._format_season_label("alpha-test-2026") == "2026"
    assert vm._format_season_label("stats-test-2026") == "2026 (STATS-TEST)"
