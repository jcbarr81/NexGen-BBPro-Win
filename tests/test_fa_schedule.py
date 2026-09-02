"""Per-day deadline for the free-agency bidding window.

The commissioner sets when the current window day is due and (optionally) lets
it advance on its own. The safety properties under test matter more than the
feature: an un-configured league must behave exactly as it always did, and a
stale deadline must never let the window burn through several days at once.
"""

from datetime import timedelta

import pytest

import api.routers.season as s
from services import fa_schedule


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fa_schedule, "get_data_dir", lambda: tmp_path)
    return tmp_path


# --- config -----------------------------------------------------------------


def test_unconfigured_league_is_inert(data_dir):
    """No file → no deadline, auto-advance OFF. Existing leagues can't fire."""
    sched = fa_schedule.read_schedule()
    assert sched == {"deadline": None, "auto_advance": False, "advance_hours": 24}
    assert fa_schedule.is_due() is False
    view = fa_schedule.schedule_view(window_open=True)
    assert view["is_scheduled"] is False and view["will_auto_advance"] is False


def test_corrupt_file_falls_back_to_inert_defaults(data_dir):
    (data_dir / fa_schedule.FILENAME).write_text("{not json", encoding="utf-8")
    assert fa_schedule.read_schedule()["auto_advance"] is False
    assert fa_schedule.is_due() is False


def test_set_schedule_merges_and_validates(data_dir):
    fa_schedule.set_schedule(
        deadline="2026-11-01T20:00:00+00:00", auto_advance=True, advance_hours=12
    )
    got = fa_schedule.read_schedule()
    assert got["auto_advance"] is True and got["advance_hours"] == 12
    # Partial update leaves the rest alone.
    fa_schedule.set_schedule(advance_hours=48)
    got = fa_schedule.read_schedule()
    assert got["advance_hours"] == 48 and got["auto_advance"] is True
    assert got["deadline"].startswith("2026-11-01T20:00")
    # Empty string clears the deadline; garbage is rejected.
    fa_schedule.set_schedule(deadline="")
    assert fa_schedule.read_schedule()["deadline"] is None
    with pytest.raises(ValueError):
        fa_schedule.set_schedule(deadline="next Sunday-ish")


def test_advance_hours_is_clamped(data_dir):
    fa_schedule.set_schedule(advance_hours=0)
    assert fa_schedule.read_schedule()["advance_hours"] == fa_schedule.MIN_ADVANCE_HOURS
    fa_schedule.set_schedule(advance_hours=10_000)
    assert fa_schedule.read_schedule()["advance_hours"] == fa_schedule.MAX_ADVANCE_HOURS
    fa_schedule.set_schedule(advance_hours="nope")
    assert fa_schedule.read_schedule()["advance_hours"] == 24


# --- the clock --------------------------------------------------------------


def test_past_due_and_countdown(data_dir):
    future = (fa_schedule.now_utc() + timedelta(hours=3)).isoformat()
    fa_schedule.set_schedule(deadline=future, auto_advance=True)
    view = fa_schedule.schedule_view(window_open=True)
    assert view["past_due"] is False
    assert 0 < view["seconds_remaining"] <= 3 * 3600
    assert view["will_auto_advance"] is True
    assert fa_schedule.is_due() is False

    past = (fa_schedule.now_utc() - timedelta(minutes=1)).isoformat()
    fa_schedule.set_schedule(deadline=past)
    assert fa_schedule.schedule_view(window_open=True)["past_due"] is True
    assert fa_schedule.is_due() is True


def test_auto_advance_off_is_never_due(data_dir):
    past = (fa_schedule.now_utc() - timedelta(days=2)).isoformat()
    fa_schedule.set_schedule(deadline=past, auto_advance=False)
    assert fa_schedule.schedule_view(window_open=True)["past_due"] is True
    assert fa_schedule.is_due() is False  # past due, but nobody asked us to fire


def test_closed_window_never_auto_advances(data_dir):
    past = (fa_schedule.now_utc() - timedelta(minutes=5)).isoformat()
    fa_schedule.set_schedule(deadline=past, auto_advance=True)
    assert fa_schedule.schedule_view(window_open=False)["will_auto_advance"] is False


def test_stale_deadline_rolls_from_now_not_from_the_deadline(data_dir):
    """The anti-cascade guarantee: a week-old deadline still buys a full cadence,
    so the window can't blow through several days in consecutive ticks."""
    stale = (fa_schedule.now_utc() - timedelta(days=7)).isoformat()
    fa_schedule.set_schedule(deadline=stale, auto_advance=True, advance_hours=24)
    fa_schedule.roll_after_advance(closed=False)
    assert fa_schedule.is_due() is False
    remaining = fa_schedule.schedule_view(window_open=True)["seconds_remaining"]
    assert 23 * 3600 < remaining <= 24 * 3600


def test_roll_does_not_arm_an_unscheduled_league(data_dir):
    """Advancing by hand must not silently opt a league into a schedule."""
    fa_schedule.set_schedule(auto_advance=False, advance_hours=24)
    assert fa_schedule.roll_after_advance(closed=False) is None
    assert fa_schedule.read_schedule()["deadline"] is None


def test_closing_the_window_clears_the_deadline(data_dir):
    soon = (fa_schedule.now_utc() + timedelta(hours=1)).isoformat()
    fa_schedule.set_schedule(deadline=soon, auto_advance=True)
    assert fa_schedule.roll_after_advance(closed=True) is None
    got = fa_schedule.read_schedule()
    assert got["deadline"] is None
    # Cadence + toggle survive, so reopening next offseason keeps the setting.
    assert got["auto_advance"] is True


# --- the scheduler tick -----------------------------------------------------


class _FakeWindow:
    """Stand-in for services.fa_window with just the surface the tick uses."""

    def __init__(self, *, open_: bool = True, closes_on_advance: bool = False):
        self.open = open_
        self.closes_on_advance = closes_on_advance
        self.advances = 0

    def is_open(self):
        return self.open

    def advance_day(self):
        self.advances += 1
        if self.closes_on_advance:
            self.open = False
        return {"ok": True, "day": self.advances, "signed": [{"player_id": "p1"}]}

    def window_status(self):
        return {
            "exists": True,
            "status": "closed" if not self.open else "open",
            "day": self.advances + 1,
        }


@pytest.fixture
def tick_env(monkeypatch, tmp_path):
    """One league, no sim running, fa_window swapped for a fake."""
    monkeypatch.setattr(s, "_iter_league_ids", lambda: ["alpha"])
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(fa_schedule, "get_data_dir", lambda: tmp_path)

    from utils import path_utils

    monkeypatch.setattr(path_utils, "set_request_league", lambda lid: lid)
    monkeypatch.setattr(path_utils, "reset_request_league", lambda tok: None)
    return tmp_path


def _install_fake_window(monkeypatch, fake):
    import services.fa_window as real

    monkeypatch.setattr(real, "is_open", fake.is_open)
    monkeypatch.setattr(real, "advance_day", fake.advance_day)
    monkeypatch.setattr(real, "window_status", fake.window_status)
    return fake


def test_tick_advances_a_due_league(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow())
    fa_schedule.set_schedule(
        deadline=(fa_schedule.now_utc() - timedelta(minutes=1)).isoformat(),
        auto_advance=True,
    )
    out = s._tick_fa_windows()
    assert fake.advances == 1
    assert out and out[0]["league"] == "alpha" and out[0]["signed"] == 1
    # Re-armed, so an immediate second tick does nothing.
    assert s._tick_fa_windows() == []
    assert fake.advances == 1


def test_tick_skips_when_auto_advance_is_off(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow())
    fa_schedule.set_schedule(
        deadline=(fa_schedule.now_utc() - timedelta(hours=5)).isoformat(),
        auto_advance=False,
    )
    assert s._tick_fa_windows() == []
    assert fake.advances == 0


def test_tick_skips_an_unconfigured_league(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow())
    assert s._tick_fa_windows() == []
    assert fake.advances == 0


def test_tick_skips_before_the_deadline(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow())
    fa_schedule.set_schedule(
        deadline=(fa_schedule.now_utc() + timedelta(hours=2)).isoformat(),
        auto_advance=True,
    )
    assert s._tick_fa_windows() == []
    assert fake.advances == 0


def test_tick_clears_a_stale_deadline_on_a_closed_window(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow(open_=False))
    fa_schedule.set_schedule(
        deadline=(fa_schedule.now_utc() - timedelta(days=3)).isoformat(),
        auto_advance=True,
    )
    assert s._tick_fa_windows() == []
    assert fake.advances == 0
    assert fa_schedule.read_schedule()["deadline"] is None


def test_tick_does_nothing_while_a_sim_holds_the_lock(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow())
    fa_schedule.set_schedule(
        deadline=(fa_schedule.now_utc() - timedelta(minutes=1)).isoformat(),
        auto_advance=True,
    )
    monkeypatch.setattr(s, "_sim_running", lambda: True)
    assert s._tick_fa_windows() == []
    assert fake.advances == 0


def test_tick_clears_the_deadline_when_the_final_day_closes(tick_env, monkeypatch):
    fake = _install_fake_window(monkeypatch, _FakeWindow(closes_on_advance=True))
    fa_schedule.set_schedule(
        deadline=(fa_schedule.now_utc() - timedelta(minutes=1)).isoformat(),
        auto_advance=True,
    )
    out = s._tick_fa_windows()
    assert fake.advances == 1 and out[0]["closed"] is True
    assert fa_schedule.read_schedule()["deadline"] is None


def test_tick_caps_advances_per_tick(monkeypatch, tmp_path):
    """Many due leagues must not make one tick run long."""
    leagues = [f"L{i}" for i in range(10)]
    monkeypatch.setattr(s, "_iter_league_ids", lambda: leagues)
    monkeypatch.setattr(s, "_sim_running", lambda: False)

    from utils import path_utils

    # Each league gets its own data dir, all of them due.
    current = {"id": leagues[0]}

    def _set(lid):
        current["id"] = lid
        return lid

    monkeypatch.setattr(path_utils, "set_request_league", _set)
    monkeypatch.setattr(path_utils, "reset_request_league", lambda tok: None)

    def _dir():
        d = tmp_path / current["id"]
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(fa_schedule, "get_data_dir", _dir)
    for lid in leagues:
        current["id"] = lid
        fa_schedule.set_schedule(
            deadline=(fa_schedule.now_utc() - timedelta(minutes=1)).isoformat(),
            auto_advance=True,
        )
    _install_fake_window(monkeypatch, _FakeWindow())

    out = s._tick_fa_windows()
    assert len(out) == s._FA_MAX_ADVANCES_PER_TICK
