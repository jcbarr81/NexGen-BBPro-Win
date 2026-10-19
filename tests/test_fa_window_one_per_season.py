"""8.2.2: one free-agency window per season, whatever the real date.

The offseason has no sim date, so the window's start_date is the wall-clock
date, and open_window keyed on it alone: the first poll after midnight UTC
opened a NEW window (day back to 1, the log and any advanced days lost, the
"bidding is open" notice posted again). alpha-test's was replaced overnight
on 2026-10-19. The window now carries its season (career_index.json's
season id) and is reused all season.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

import services.fa_window as w
from tests.test_fa_window_notices import _news, league  # noqa: F401 (fixture)


def _season(root, season_id="test-2027", year=2027):
    (root / "career_index.json").write_text(
        json.dumps({"current": {"season_id": season_id, "league_year": year}}),
        encoding="utf-8",
    )


class _Day(date):
    """date.today() pinned to a chosen day."""

    pinned = date(2026, 10, 18)

    @classmethod
    def today(cls):
        return cls.pinned


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(w, "date", _Day)
    return _Day


def test_the_next_real_day_reuses_the_window(league, clock):  # noqa: F811
    _season(league)
    first = w.open_window("")
    w.advance_day()
    w.advance_day()
    assert w.load_window()["day"] == 3

    clock.pinned = date(2026, 10, 19)  # midnight UTC passes
    again = w.open_window("")
    assert again["start_date"] == first["start_date"] == "2026-10-18"
    assert again["day"] == 3
    assert again["season_key"] == "test-2027"
    opened = [line for line in _news(league) if "bidding is open" in line]
    assert len(opened) == 1  # announced once, not every day


def test_a_closed_window_stays_closed_this_season(league, clock):  # noqa: F811
    _season(league)
    w.open_window("")
    w.close_window()
    clock.pinned = date(2026, 10, 25)
    assert w.open_window("")["status"] == "closed"


def test_the_next_season_opens_a_fresh_window(league, clock):  # noqa: F811
    _season(league, "test-2027", 2027)
    w.open_window("")
    w.close_window()
    _season(league, "test-2028", 2028)
    clock.pinned = date(2027, 10, 18)
    fresh = w.open_window("")
    assert fresh["status"] == "open" and fresh["day"] == 1
    assert fresh["season_key"] == "test-2028"


def test_a_window_opened_before_the_fix_is_adopted(league, clock):  # noqa: F811
    """alpha-test's live window has no season key: still open, it is kept
    and given the key; nothing re-seeds or re-announces."""

    _season(league)
    legacy = {
        "version": 1, "status": "open", "start_date": "2026-10-19",
        "deadline_date": "2026-11-02", "day": 1, "total_days": 14,
        "current_date": "2026-10-19", "log": [{"day": 0, "date": "2026-10-19"}],
    }
    (league / "fa_window.json").write_text(json.dumps(legacy), encoding="utf-8")
    clock.pinned = date(2026, 10, 20)
    kept = w.open_window("")
    assert kept["start_date"] == "2026-10-19"
    assert kept["season_key"] == "test-2027"
    assert _news(league) == []
    status = w.window_status()
    assert status["this_season"] is True
