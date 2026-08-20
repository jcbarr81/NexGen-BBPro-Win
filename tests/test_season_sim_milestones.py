"""Regression tests for the 'simulate to milestone' stop/trigger logic in
api/routers/season.py.

Covers two bugs found during the parallel-sim smoke test:
  * 'to draft' stopped one day short of the draft-day intercept (off-by-one).
  * 'to playoffs' sims to the last regular-season day but never seeds the
    bracket / flips into PLAYOFFS.
"""

from types import SimpleNamespace

import pytest

from api.routers import season
from playbalance.season_manager import SeasonPhase


# ---------------------------------------------------------------------------
# Bug 1 — _days_for_kind('to-draft') must REACH the draft-day iteration.
# ---------------------------------------------------------------------------

def _sim(dates, index):
    return SimpleNamespace(dates=list(dates), _index=index)


def test_to_draft_reaches_draft_day_iteration():
    # Draft is at index 5; cursor at index 2. The draft-day intercept fires on
    # the iteration whose target == draft_date (index 5), so the loop must run
    # far enough to PROCESS index 5 => 5 - 2 + 1 = 4 days.
    dates = [f"2025-04-{d:02d}" for d in range(1, 11)]  # indices 0..9
    sim = _sim(dates, index=2)
    n = season._days_for_kind("to-draft", 1, sim, draft_date=dates[5])
    assert n == 4  # was 3 before the fix (one iteration short of the intercept)
    # Simulate the loop cursor advancing by n and confirm it lands ON draft day
    # (so the intercept's `target_date == draft_date` check can fire).
    assert sim._index + (n - 1) == 5


def test_to_draft_when_cursor_already_on_draft_day():
    dates = [f"2025-04-{d:02d}" for d in range(1, 11)]
    sim = _sim(dates, index=5)  # cursor already parked on draft day
    n = season._days_for_kind("to-draft", 1, sim, draft_date=dates[5])
    assert n == 1  # one iteration => intercept fires immediately


def test_to_draft_when_draft_already_passed_returns_zero():
    dates = [f"2025-04-{d:02d}" for d in range(1, 11)]
    sim = _sim(dates, index=7)  # already past the draft
    n = season._days_for_kind("to-draft", 1, sim, draft_date=dates[5])
    assert n == 0


def test_to_playoffs_day_count_runs_to_end_of_schedule():
    dates = [f"2025-04-{d:02d}" for d in range(1, 11)]  # 10 dates
    sim = _sim(dates, index=3)
    n = season._days_for_kind("to-playoffs", 1, sim, draft_date=dates[5])
    assert n == 7  # 10 - 3


# ---------------------------------------------------------------------------
# Bug 2 — _maybe_enter_playoffs seeds the bracket + flips the phase, but only
# when the regular season is complete AND the caller may run progression.
# ---------------------------------------------------------------------------

class _FakeManager:
    def __init__(self, phase=SeasonPhase.REGULAR_SEASON):
        self.phase = phase
        self.advanced = False

    def advance_phase(self):
        self.advanced = True
        self.phase = SeasonPhase.PLAYOFFS
        return self.phase


@pytest.fixture
def stub_bracket(monkeypatch):
    """Stub the bracket seed + standings sync so the helper is exercised
    without a full league on disk."""
    calls = {"sync": 0, "bracket": 0}

    def _sync():
        calls["sync"] += 1

    monkeypatch.setattr(season, "_sync_standings_from_stats", _sync)
    return calls


def test_enter_playoffs_happy_path(monkeypatch, stub_bracket):
    monkeypatch.setattr(
        season, "_ensure_playoff_bracket", lambda: {"saved": True, "teams_seeded": 8}
    )
    mgr = _FakeManager()
    sim = _sim([f"d{i}" for i in range(10)], index=10)  # season complete
    result = {}
    season._maybe_enter_playoffs(mgr, sim, result, can_progress=True)

    assert mgr.advanced is True
    assert mgr.phase == SeasonPhase.PLAYOFFS
    assert result["new_phase"] == "PLAYOFFS"
    assert result["playoffs"] == {"saved": True, "teams_seeded": 8}
    assert stub_bracket["sync"] == 1


def test_enter_playoffs_blocked_when_season_incomplete(monkeypatch, stub_bracket):
    called = {"bracket": False}

    def _boom():
        called["bracket"] = True
        return {"saved": True}

    monkeypatch.setattr(season, "_ensure_playoff_bracket", _boom)
    mgr = _FakeManager()
    sim = _sim([f"d{i}" for i in range(10)], index=7)  # 3 days left
    result = {}
    season._maybe_enter_playoffs(mgr, sim, result, can_progress=True)

    assert mgr.advanced is False
    assert mgr.phase == SeasonPhase.REGULAR_SEASON
    assert result == {}  # untouched — user keeps simming
    assert called["bracket"] is False  # never even tried to seed


def test_enter_playoffs_requires_progression_permission(monkeypatch, stub_bracket):
    called = {"bracket": False}

    def _boom():
        called["bracket"] = True
        return {"saved": True}

    monkeypatch.setattr(season, "_ensure_playoff_bracket", _boom)
    mgr = _FakeManager()
    sim = _sim([f"d{i}" for i in range(10)], index=10)  # complete
    result = {}
    season._maybe_enter_playoffs(mgr, sim, result, can_progress=False)

    assert mgr.advanced is False
    assert mgr.phase == SeasonPhase.REGULAR_SEASON
    assert result["playoffs_pending_commissioner"] is True
    assert called["bracket"] is False  # commissioner gate blocks before seeding


def test_enter_playoffs_surfaces_bracket_error_without_flipping(monkeypatch, stub_bracket):
    monkeypatch.setattr(
        season, "_ensure_playoff_bracket", lambda: {"error": "no standings"}
    )
    mgr = _FakeManager()
    sim = _sim([f"d{i}" for i in range(10)], index=10)
    result = {}
    season._maybe_enter_playoffs(mgr, sim, result, can_progress=True)

    assert mgr.advanced is False  # stays recoverable in REGULAR_SEASON
    assert mgr.phase == SeasonPhase.REGULAR_SEASON
    assert result["playoffs_error"] == "no standings"


def test_enter_playoffs_noop_if_not_regular_season(monkeypatch, stub_bracket):
    monkeypatch.setattr(season, "_ensure_playoff_bracket", lambda: {"saved": True})
    mgr = _FakeManager(phase=SeasonPhase.PLAYOFFS)  # already in playoffs
    sim = _sim([f"d{i}" for i in range(10)], index=10)
    result = {}
    season._maybe_enter_playoffs(mgr, sim, result, can_progress=True)

    assert mgr.advanced is False
    assert result == {}
