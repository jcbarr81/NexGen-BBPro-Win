"""Box-score save failures must not be swallowed.

Production has 1,620 played games in one league and not a single box score
file. Every save site wrapped the write in a bare ``except Exception: pass``,
so the reason died at the call site — and ``nexgen.*`` logging does not surface
in Cloud Run, leaving nothing to diagnose from.

These cover the recorder itself and the two things it has to distinguish: the
write failing, versus the simulator handing back no HTML at all (which would
point upstream instead).
"""

import types

import pytest

from services import boxscore_diagnostics as diag


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "_log_path", lambda data_dir=None: tmp_path / diag.LOG_FILENAME)
    return tmp_path


def test_nothing_logged_by_default(log_dir):
    assert diag.read_failures() == []


def test_a_failure_records_the_reason(log_dir):
    diag.record_failure("season:save", "2026-04-01_BBB_at_AAA", PermissionError("read-only fs"))
    entries = diag.read_failures()
    assert len(entries) == 1
    assert entries[0]["stage"] == "season:save"
    assert entries[0]["error_type"] == "PermissionError"
    assert "read-only" in entries[0]["error"]
    assert entries[0]["game_id"] == "2026-04-01_BBB_at_AAA"


def test_success_clears_the_log(log_dir):
    """A fixed league should stop reporting stale problems."""
    diag.record_failure("season:save", "g1", OSError("boom"))
    assert diag.read_failures()
    diag.record_success()
    assert diag.read_failures() == []


def test_the_log_is_capped(log_dir):
    """A full season of identical failures is noise, not signal."""
    for i in range(diag.MAX_ENTRIES + 25):
        diag.record_failure("season:save", f"g{i}", OSError("boom"))
    entries = diag.read_failures()
    assert len(entries) == diag.MAX_ENTRIES
    # The most recent are kept.
    assert entries[-1]["game_id"] == f"g{diag.MAX_ENTRIES + 24}"


def test_recording_never_raises(monkeypatch, log_dir):
    """Diagnostics must never be able to break a sim."""

    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(diag, "_log_path", boom)
    diag.record_failure("season:save", "g1", OSError("x"))  # must not raise
    diag.record_success()
    assert diag.read_failures() == []


def test_corrupt_log_is_survivable(log_dir):
    (log_dir / diag.LOG_FILENAME).write_text("{not json", encoding="utf-8")
    assert diag.read_failures() == []
    diag.record_failure("season:save", "g1", OSError("x"))
    assert len(diag.read_failures()) == 1


# --- the persist path actually records ------------------------------------


def _persist(tmp_path, monkeypatch, schedule):
    import api.routers.season as S

    monkeypatch.setattr(diag, "_log_path", lambda data_dir=None: tmp_path / diag.LOG_FILENAME)
    monkeypatch.setattr(S, "_schedule_path", lambda: tmp_path / "schedule.csv")
    monkeypatch.setattr(S, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(S, "_sync_standings_from_stats", lambda *a, **k: None)
    monkeypatch.setattr(S, "_reconcile_team_records_with_schedule", lambda *a, **k: None)
    S._persist_post_sim_state(types.SimpleNamespace(schedule=schedule), ["2026-04-01"])


def test_missing_html_is_reported_distinctly(tmp_path, monkeypatch):
    """No HTML from the simulator is a different bug from a failed write, and
    the log has to say which."""
    schedule = [{"date": "2026-04-01", "home": "AAA", "away": "BBB", "result": "3-2"}]
    _persist(tmp_path, monkeypatch, schedule)

    entries = diag.read_failures()
    assert entries and entries[-1]["stage"] == "season:no_html"
    assert entries[-1]["game_id"] == "2026-04-01_BBB_at_AAA"


def test_a_successful_save_still_records_the_path(tmp_path, monkeypatch):
    """The diagnostics must not disturb the working path."""
    import playbalance.simulation as sim_mod

    monkeypatch.setattr(sim_mod, "get_data_dir", lambda: tmp_path)
    schedule = [
        {
            "date": "2026-04-01",
            "home": "AAA",
            "away": "BBB",
            "result": "3-2",
            "boxscore_html": "<html>box</html>",
        }
    ]
    _persist(tmp_path, monkeypatch, schedule)

    assert schedule[0]["boxscore"].endswith("2026-04-01_BBB_at_AAA.html")
    assert schedule[0]["played"] == "1"
    assert diag.read_failures() == []


# --- every save site must be instrumented ----------------------------------


def test_every_boxscore_save_site_is_instrumented():
    """There are two save sites in playoffs.py and one in the season persist
    path. Instrumenting only some of them wastes a whole diagnose-deploy-sim
    round trip on the one that wasn't covered — which is exactly what happened.
    """
    import inspect

    import api.routers.season as season_mod
    import playbalance.playoffs as playoffs_mod

    for module in (playoffs_mod, season_mod):
        src = inspect.getsource(module)
        saves = src.count("save_boxscore_html")
        # Each site imports the saver once; every one needs a recorded outcome.
        assert src.count("record_failure") >= 1, module.__name__
        # playoffs has two independent save sites; both must report.
        if module is playoffs_mod:
            assert saves >= 2
            assert src.count("playoffs:") >= 1
            assert src.count("playoffs_single:") >= 1


def test_no_bare_swallow_remains_around_a_boxscore_save():
    """A bare `except Exception: pass` immediately after a save is what hid
    this for months."""
    import inspect

    import playbalance.playoffs as playoffs_mod

    src = inspect.getsource(playoffs_mod)
    for chunk in src.split("save_boxscore_html")[1:]:
        window = chunk[:400]
        assert "record_failure" in window or "record_success" in window
