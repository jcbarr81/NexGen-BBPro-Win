"""A playoff day starts the pitcher tracker's day, as a regular-season day does.

The tracker caches each club's rotation for the day it last started. Playoff
days never started one, so the first playoff game reused the last
regular-season day's rotation -- from before the September roster revert --
and named a starter who had just been optioned: "Pitcher ... not found on
pitching staff", and the playoffs could not be played (found 2026-11-06 on a
demo league once 8.12.1 made September call-ups happen).
"""

from __future__ import annotations

from datetime import date

import playbalance.playoffs as P
from playbalance.playoffs import Matchup, PlayoffBracket, PlayoffTeam, Round, SeriesConfig


class _Tracker:
    def __init__(self):
        self.days = []

    def start_day(self, date_str):
        self.days.append(date_str)


def _bracket():
    high = PlayoffTeam(team_id="H1", seed=1, league="LEAGUE", wins=90, run_diff=50)
    low = PlayoffTeam(team_id="L4", seed=4, league="LEAGUE", wins=80, run_diff=10)
    matchup = Matchup(high=high, low=low, config=SeriesConfig(length=3, pattern=[2, 1]))
    return PlayoffBracket(year=2025, rounds=[Round(name="Final", matchups=[matchup])])


def test_a_real_playoff_day_starts_the_pitching_day_after_the_injured_lists(monkeypatch):
    from utils import pitcher_recovery

    tracker = _Tracker()
    order = []
    monkeypatch.setattr(pitcher_recovery.PitcherRecoveryTracker, "instance", classmethod(lambda cls: tracker))
    monkeypatch.setattr(P, "_process_injured_lists_for_playoff_day", lambda d: order.append(("il", d)))
    real_start = P._start_pitching_day
    monkeypatch.setattr(P, "_start_pitching_day", lambda d: (order.append(("day", d)), real_start(d)))

    def play(matchup, **kw):
        order.append(("game", kw["game_date"]))
        return False

    monkeypatch.setattr(P, "_simulate_next_series_game", play)
    monkeypatch.setattr(P, "_regular_season_end", lambda year: date(2025, 9, 28))
    P._play_next_day(_bracket(), year=2025, simulate_game=None, persist=lambda: None)

    kinds = [k for k, _ in order]
    assert kinds[:3] == ["il", "day", "game"]
    game_date = order[2][1]
    assert game_date and tracker.days == [game_date]


def test_a_test_double_game_sim_leaves_the_tracker_alone(monkeypatch):
    from utils import pitcher_recovery

    tracker = _Tracker()
    monkeypatch.setattr(pitcher_recovery.PitcherRecoveryTracker, "instance", classmethod(lambda cls: tracker))
    P.simulate_next_game(
        _bracket(),
        simulate_game=lambda home, away, **kw: (1, 0, "<html></html>", {}),
        persist_cb=lambda b: None,
    )
    assert tracker.days == []


def test_starting_the_day_clears_the_cached_rotations(tmp_path, monkeypatch):
    from utils.pitcher_recovery import PitcherRecoveryTracker

    tracker = PitcherRecoveryTracker.__new__(PitcherRecoveryTracker)
    tracker.data = {"teams": {}, "last_recovery_date": "2025-10-01"}
    tracker._assignments = {"ALB": "P1"}
    tracker._ensured = {("ALB", "p", "r"): {"rotation": ["P1"]}}
    tracker._current_date = "2025-09-28"
    tracker.save = lambda: None
    monkeypatch.setattr(PitcherRecoveryTracker, "instance", classmethod(lambda cls: tracker))

    P._start_pitching_day("2025-10-01")
    assert tracker._ensured == {} and tracker._assignments == {}
    assert tracker._current_date == "2025-10-01"
