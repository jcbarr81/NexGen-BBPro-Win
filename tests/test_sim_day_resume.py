"""A sim day that fails partway through resumes with only its missing games.

Audit H9: when game k of a day raised, the games before it kept their results
but the resume check counted the date as played as soon as ANY game on it had
a result, so the rest of the day was never played (the 8 clubs involved
finished on 161 of 162). Now a date counts only when every game on it is done,
and the simulator plays only the games still without a result.
"""

import json
from pathlib import Path

import pytest

from playbalance.season_simulator import SeasonSimulator
from utils.depth_chart import has_depth_chart, load_depth_chart, save_depth_chart


def test_a_partly_played_day_plays_only_its_missing_games():
    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B", "result": "3-2"},
        {"date": "2024-04-01", "home": "C", "away": "D"},
        {"date": "2024-04-01", "home": "E", "away": "F"},
    ]
    played = []
    sim = SeasonSimulator(schedule, simulate_game=lambda h, a: played.append((h, a)))
    sim.simulate_next_day()
    assert played == [("C", "D"), ("E", "F")]


def test_a_fully_played_day_is_skipped():
    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B", "result": "3-2"},
        {"date": "2024-04-02", "home": "C", "away": "D"},
    ]
    played = []
    sim = SeasonSimulator(schedule, simulate_game=lambda h, a: played.append((h, a)))
    sim.simulate_next_day()   # 04-01: nothing left to play
    sim.simulate_next_day()   # 04-02
    assert played == [("C", "D")]


def test_resume_check_needs_every_game_on_the_date(monkeypatch):
    import api.routers.season as season

    schedule = [
        {"date": "2024-04-01", "home": "A", "away": "B", "result": "1-0", "played": "1"},
        {"date": "2024-04-02", "home": "A", "away": "B", "result": "2-1", "played": "1"},
        {"date": "2024-04-02", "home": "C", "away": "D"},
        {"date": "2024-04-03", "home": "C", "away": "D"},
    ]
    monkeypatch.setattr(season, "_load_schedule", lambda: schedule)
    monkeypatch.setattr(season, "_compute_draft_date", lambda first: None)
    monkeypatch.setattr(season, "SeasonManager", lambda: object())
    _, simulator, _ = season._build_manager_and_simulator()
    assert simulator.dates[simulator._index] == "2024-04-02"


# --- default depth charts ----------------------------------------------------


@pytest.fixture
def league_dir(tmp_path, monkeypatch):
    import utils.depth_chart as dc

    monkeypatch.setattr(dc, "get_data_dir", lambda: tmp_path)
    return tmp_path


def test_ensure_default_depth_chart_never_overwrites(league_dir, monkeypatch):
    import utils.depth_chart_autofill as auto

    calls = []
    monkeypatch.setattr(auto, "auto_generate_depth_chart", lambda tid, persist=True: calls.append(tid))
    save_depth_chart("OWN", {"SS": ["p1"]})
    assert auto.ensure_default_depth_chart("OWN") is False
    assert calls == []
    assert load_depth_chart("OWN")["SS"] == ["p1"]


def test_ensure_default_depth_chart_creates_a_missing_one(league_dir, monkeypatch):
    import utils.depth_chart_autofill as auto

    monkeypatch.setattr(
        auto, "auto_generate_depth_chart",
        lambda tid, persist=True: save_depth_chart(tid, {"C": ["c1"]}),
    )
    assert not has_depth_chart("CPU")
    assert auto.ensure_default_depth_chart("CPU") is True
    assert load_depth_chart("CPU")["C"] == ["c1"]
