"""Progression schedule (owner-deadline enforcement, Phase 1).

The commissioner sets an ISO deadline + what runs when it passes (CPU-fill
unready teams + an optional sim timeframe). Once past the deadline, one run
CPU-fills stragglers and starts the sim; a recurring deadline rolls forward.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import api.routers.season as s
from utils import path_utils


@pytest.fixture
def sched_file(tmp_path, monkeypatch):
    path = tmp_path / "season_deadline.json"
    monkeypatch.setattr(s, "_deadline_path", lambda: path)
    return path


def _iso(dt):
    return dt.isoformat()


def test_schedule_roundtrip_and_defaults(sched_file):
    s._write_schedule(
        {
            "deadline": "2026-09-01T20:00:00+00:00",
            "run_kind": "days",
            "run_n": 7,
            "cpu_fill": True,
            "recurring": True,
            "recur_days": 7,
            "auto_run": False,
            "note": "weekly",
        }
    )
    got = s._read_schedule()
    assert got["run_kind"] == "days" and got["run_n"] == 7
    assert got["recurring"] is True and got["recur_days"] == 7
    # An invalid run_kind normalizes to "" (ready-only), bad ints to safe defaults.
    s._write_schedule({"deadline": "x", "run_kind": "bogus", "run_n": "nope"})
    got2 = s._read_schedule()
    assert got2["run_kind"] == "" and got2["run_n"] == 1


def test_legacy_freeform_deadline_is_not_enforceable(sched_file):
    # A free-form label parses to None → not enforceable (display-only legacy).
    assert s._parse_iso_utc("Sun 8pm ET") is None


def test_schedule_view_past_due(sched_file, monkeypatch):
    monkeypatch.setattr(s, "_human_team_ids", lambda: ["A", "B"])
    monkeypatch.setattr(
        s, "_league_readiness", lambda **k: {"unready": ["B"], "all_ready": False}
    )
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s._write_schedule({"deadline": _iso(past), "run_kind": "days", "run_n": 3})
    view = s._schedule_view()
    assert view["is_scheduled"] and view["past_due"] is True
    assert view["seconds_remaining"] < 0
    assert view["unready_count"] == 1
    assert "3 day" in view["run_label"]


def test_run_before_deadline_refuses(sched_file):
    future = datetime.now(timezone.utc) + timedelta(days=1)
    s._write_schedule({"deadline": _iso(future), "run_kind": "days", "run_n": 1})
    with pytest.raises(Exception) as ei:
        s._run_schedule({"r": "admin"})
    assert "hasn't passed" in str(ei.value.detail if hasattr(ei.value, "detail") else ei.value)


def test_run_cpu_fills_starts_sim_and_rolls_recurring(sched_file, monkeypatch):
    calls = {}
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(s, "_cpu_fill_all_unready", lambda: ["B", "C"])
    monkeypatch.setattr(
        s, "_start_sim", lambda kind, identity, n_arg=1: calls.setdefault("sim", (kind, n_arg))
    )
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s._write_schedule(
        {"deadline": _iso(past), "run_kind": "days", "run_n": 5,
         "cpu_fill": True, "recurring": True, "recur_days": 7}
    )
    result = s._run_schedule({"r": "admin"})
    assert result["filled"] == ["B", "C"]
    assert calls["sim"] == ("days", 5)
    # Recurring: deadline rolled forward 7 days, not cleared.
    assert result["next_deadline"] is not None
    rolled = s._parse_iso_utc(result["next_deadline"])
    assert rolled == s._parse_iso_utc(_iso(past)) + timedelta(days=7)
    assert s._read_schedule()["deadline"] == result["next_deadline"]


def test_run_oneshot_clears_deadline(sched_file, monkeypatch):
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(s, "_cpu_fill_all_unready", lambda: [])
    monkeypatch.setattr(s, "_start_sim", lambda *a, **k: {"status": "running"})
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s._write_schedule(
        {"deadline": _iso(past), "run_kind": "week", "cpu_fill": True, "recurring": False}
    )
    result = s._run_schedule({"r": "admin"})
    assert result["next_deadline"] is None
    assert s._read_schedule()["deadline"] is None  # one-shot cleared


# --- Phase 2: automatic firing (Cloud Scheduler tick) -----------------------

_PAST = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _eligible_sched(**over):
    base = {
        "deadline": _PAST, "run_kind": "days", "run_n": 3, "cpu_fill": True,
        "recurring": False, "recur_days": 7, "auto_run": True, "note": "",
    }
    base.update(over)
    return base


def test_tick_requires_configured_token(monkeypatch):
    monkeypatch.delenv("NEXGEN_SCHEDULER_TOKEN", raising=False)
    with pytest.raises(HTTPException) as ei:
        s.tick_season_schedule(x_scheduler_token="anything")
    assert ei.value.status_code == 503


def test_tick_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("NEXGEN_SCHEDULER_TOKEN", "secret")
    with pytest.raises(HTTPException) as ei:
        s.tick_season_schedule(x_scheduler_token="wrong")
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException):
        s.tick_season_schedule(x_scheduler_token=None)  # missing header


def test_tick_fires_eligible_auto_run_league(monkeypatch):
    monkeypatch.setenv("NEXGEN_SCHEDULER_TOKEN", "secret")
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(s, "_iter_league_ids", lambda: ["l1"])
    monkeypatch.setattr(s, "_read_schedule", lambda: _eligible_sched())
    ran = {}

    def fake_run(identity, *, force=False):
        ran["identity"] = identity
        ran["force"] = force
        return {"filled": ["B"], "started": {"status": "running"},
                "run_label": "simulate 3 days", "next_deadline": None,
                "recurring": False}

    monkeypatch.setattr(s, "_run_schedule", fake_run)
    out = s.tick_season_schedule(x_scheduler_token="secret")
    assert out["status"] == "ok"
    assert [f["league"] for f in out["fired"]] == ["l1"]
    # Ran as a synthetic commissioner, honoring the real deadline (force=False).
    assert ran["identity"]["r"] == "admin" and ran["force"] is False


def test_tick_skips_when_auto_run_off(monkeypatch):
    monkeypatch.setenv("NEXGEN_SCHEDULER_TOKEN", "secret")
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(s, "_iter_league_ids", lambda: ["l1"])
    monkeypatch.setattr(s, "_read_schedule", lambda: _eligible_sched(auto_run=False))
    monkeypatch.setattr(
        s, "_run_schedule",
        lambda *a, **k: pytest.fail("auto_run is off; must not run"),
    )
    out = s.tick_season_schedule(x_scheduler_token="secret")
    assert out["fired"] == []
    assert out["considered"][0]["eligible"] is False


def test_tick_skips_when_deadline_not_passed(monkeypatch):
    monkeypatch.setenv("NEXGEN_SCHEDULER_TOKEN", "secret")
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(s, "_iter_league_ids", lambda: ["l1"])
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    monkeypatch.setattr(s, "_read_schedule", lambda: _eligible_sched(deadline=future))
    monkeypatch.setattr(
        s, "_run_schedule", lambda *a, **k: pytest.fail("deadline not passed"),
    )
    out = s.tick_season_schedule(x_scheduler_token="secret")
    assert out["fired"] == []
    assert out["considered"][0]["past_due"] is False


def test_tick_noop_when_sim_already_running(monkeypatch):
    monkeypatch.setenv("NEXGEN_SCHEDULER_TOKEN", "secret")
    monkeypatch.setattr(s, "_sim_running", lambda: True)
    monkeypatch.setattr(
        s, "_run_schedule", lambda *a, **k: pytest.fail("a sim is already running"),
    )
    out = s.tick_season_schedule(x_scheduler_token="secret")
    assert out["status"] == "sim_busy"
    assert out["fired"] == []


def test_tick_starts_at_most_one_sim_per_tick(monkeypatch):
    monkeypatch.setenv("NEXGEN_SCHEDULER_TOKEN", "secret")
    monkeypatch.setattr(s, "_sim_running", lambda: False)
    monkeypatch.setattr(s, "_iter_league_ids", lambda: ["l1", "l2"])
    monkeypatch.setattr(s, "_read_schedule", lambda: _eligible_sched(run_kind="week"))
    ran = []

    def fake_run(identity, *, force=False):
        ran.append(path_utils.get_request_league())
        return {"filled": [], "started": {"status": "running"},
                "run_label": "simulate 1 week", "next_deadline": None,
                "recurring": False}

    monkeypatch.setattr(s, "_run_schedule", fake_run)
    out = s.tick_season_schedule(x_scheduler_token="secret")
    # Sims are a single global job: the first eligible league starts, the loop
    # stops, and the rest wait for a later tick.
    assert ran == ["l1"]
    assert [f["league"] for f in out["fired"]] == ["l1"]
