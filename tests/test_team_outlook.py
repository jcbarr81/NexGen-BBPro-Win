"""S2-09: standings-based competitive outlook classification."""
from __future__ import annotations

from types import SimpleNamespace

from services.team_outlook import (
    OUTLOOK_CONTEND,
    OUTLOOK_REBUILD,
    OUTLOOK_BUBBLE,
    games_back,
    team_outlook,
)


def _team(team_id: str, division: str = "E") -> SimpleNamespace:
    return SimpleNamespace(team_id=team_id, division=division)


def _rec(wins: int, losses: int) -> dict[str, int]:
    return {"wins": wins, "losses": losses}


def test_outlook_contender_by_win_pct():
    standings = {"AAA": _rec(40, 20), "BBB": _rec(30, 30)}
    teams = {"AAA": _team("AAA"), "BBB": _team("BBB")}
    assert team_outlook("AAA", standings=standings, teams_by_id=teams) == OUTLOOK_CONTEND


def test_outlook_contender_by_games_back():
    # .532 team, only 2 GB behind a .560 division leader -> contend on the GB rule.
    standings = {"LEAD": _rec(42, 33), "CHASE": _rec(41, 36)}
    teams = {"LEAD": _team("LEAD"), "CHASE": _team("CHASE")}
    assert games_back("CHASE", standings=standings, teams_by_id=teams) == 2.0
    assert team_outlook("CHASE", standings=standings, teams_by_id=teams) == OUTLOOK_CONTEND


def test_outlook_rebuild_by_games_back():
    # .475 team, 14 GB back -> rebuild on the GB rule (win_pct alone wouldn't).
    standings = {"LEAD": _rec(50, 26), "BACK": _rec(38, 42)}
    teams = {"LEAD": _team("LEAD"), "BACK": _team("BACK")}
    assert games_back("BACK", standings=standings, teams_by_id=teams) == 14.0
    assert team_outlook("BACK", standings=standings, teams_by_id=teams) == OUTLOOK_REBUILD


def test_outlook_bubble_early_season():
    # 8-6 is over the win-pct threshold but < 20 games played -> bubble.
    standings = {"NEW": _rec(8, 6), "OTH": _rec(6, 8)}
    teams = {"NEW": _team("NEW"), "OTH": _team("OTH")}
    assert team_outlook("NEW", standings=standings, teams_by_id=teams) == OUTLOOK_BUBBLE


def test_outlook_tied_division_leaders():
    standings = {"T1": _rec(45, 30), "T2": _rec(45, 30)}
    teams = {"T1": _team("T1"), "T2": _team("T2")}
    assert games_back("T1", standings=standings, teams_by_id=teams) == 0.0
    assert games_back("T2", standings=standings, teams_by_id=teams) == 0.0
    assert team_outlook("T1", standings=standings, teams_by_id=teams) == OUTLOOK_CONTEND
    assert team_outlook("T2", standings=standings, teams_by_id=teams) == OUTLOOK_CONTEND
