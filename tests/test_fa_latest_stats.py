"""8.3.1: the Free Agency page's Stats view shows each player's latest season.

This season's line once he has played in it; otherwise the most recent
archived season (the career ledger); nothing when he has neither. Batting
keys for hitters, pitching keys for pitchers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routers.free_agency import _latest_stats


def test_this_season_once_played():
    p = SimpleNamespace(
        season_stats={"g": 20, "pa": 80, "avg": 0.3, "hr": 4},
        career_history={"lg-2026": {"g": 150, "pa": 600, "avg": 0.25}},
    )
    out = _latest_stats(p, is_pitcher=False)
    assert out["season"] == "current"
    assert (out["g"], out["pa"], out["avg"], out["hr"]) == (20, 80, 0.3, 4)


def test_last_season_in_the_offseason():
    p = SimpleNamespace(
        season_stats={"w": 0, "l": 0},
        career_history={
            "lg-2025": {"g": 30, "outs": 300, "era": 3.0},
            "lg-2026": {"g": 59, "gs": 0, "outs": 235, "era": 4.25, "whip": 1.37, "k9": 8.7, "sv": 3},
        },
    )
    out = _latest_stats(p, is_pitcher=True)
    assert out["season"] == "2026"
    assert out["g"] == 59 and out["sv"] == 3
    assert out["ip"] == pytest.approx(78.333, abs=0.001)
    assert out["era"] == 4.25


def test_pitching_keys_for_a_pitcher_batting_keys_for_a_hitter():
    line = {"g": 10, "pa": 3, "avg": 0.333, "outs": 30, "era": 2.7}
    pitcher = _latest_stats(SimpleNamespace(season_stats=line), is_pitcher=True)
    hitter = _latest_stats(SimpleNamespace(season_stats=line), is_pitcher=False)
    assert "avg" not in pitcher and "era" in pitcher
    assert "era" not in hitter and "avg" in hitter


def test_no_line_at_all():
    assert _latest_stats(SimpleNamespace(), is_pitcher=False) is None
    assert _latest_stats(
        SimpleNamespace(season_stats={}, career_history={"lg-2026": {"g": 0}}),
        is_pitcher=False,
    ) is None
