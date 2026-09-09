"""The rotation records why each start was awarded.

An owner reported his top two starters taking double the starts of the other
three, and reasoning about the code could not reproduce it — replaying
``assign_starter`` over the real schedule produced an even split. So the
selection now records the decision itself. These tests pin the two properties
that make such a log worth having: it must capture enough to identify the
cause, and it must never be able to break a simulation.
"""

import csv
import json

import pytest

from services import rotation_diagnostics as RD


@pytest.fixture(autouse=True)
def _clear_buffer():
    RD._buffer.clear()
    yield
    RD._buffer.clear()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(RD.ENABLE_ENV, "1")


def _record(tmp_path, **kw):
    kw.setdefault("team_id", "CHI")
    kw.setdefault("date_str", "2026-06-13")
    kw.setdefault("rotation", ["P1", "P2", "P3", "P4", "P5"])
    kw.setdefault("next_index_in", 0)
    kw.setdefault("chosen_index", 0)
    kw.setdefault("next_index_out", 1)
    kw.setdefault("availability", ["2026-06-01"] * 5)
    kw.setdefault("used_fallback", False)
    RD.record_decision(data_dir=tmp_path, **kw)


# --- it has to be off by default -------------------------------------------


def test_nothing_is_written_unless_it_is_switched_on(tmp_path, monkeypatch):
    """This sits in the path of every simulated game."""
    monkeypatch.delenv(RD.ENABLE_ENV, raising=False)
    _record(tmp_path)
    assert not (tmp_path / RD.LOG_FILENAME).exists()
    assert RD.read_decisions(data_dir=tmp_path) == []


# --- what a row has to answer ----------------------------------------------


def test_a_row_identifies_the_slot_that_started(tmp_path, enabled):
    _record(tmp_path, chosen_index=2, next_index_out=3)
    row = RD.read_decisions(data_dir=tmp_path)[0]
    assert row["slot_chosen"] == 2
    assert row["starter"] == "P3"


def test_a_row_shows_the_pointer_moving(tmp_path, enabled):
    """A pointer that jumps on its own is the thing being hunted."""
    _record(tmp_path, next_index_in=1, chosen_index=4, next_index_out=0)
    row = RD.read_decisions(data_dir=tmp_path)[0]
    assert (row["slot_in"], row["slot_out"]) == (1, 0)
    assert row["skipped"] == 3


def test_a_row_carries_every_slots_rest(tmp_path, enabled):
    """Without this you cannot tell a real rest skip from a pointer bug."""
    avail = ["2026-06-16", "2026-06-17", "2026-06-10", "2026-06-11", "2026-06-14"]
    _record(tmp_path, availability=avail, next_index_in=2, chosen_index=2)
    assert RD.read_decisions(data_dir=tmp_path)[0]["available_on"] == avail


def test_the_everyone_is_tired_fallback_is_flagged(tmp_path, enabled):
    """The fallback ignores the pointer and breaks ties on the lowest slot, so
    it is the one branch that can bias starts toward SP1/SP2."""
    _record(tmp_path, used_fallback=True)
    assert RD.read_decisions(data_dir=tmp_path)[0]["fallback"] is True


def test_the_summary_counts_starts_per_slot(tmp_path, enabled):
    for slot in [0, 0, 1, 2, 2, 2]:
        _record(tmp_path, chosen_index=slot)
    summary = RD.summarize(RD.read_decisions(data_dir=tmp_path))
    assert summary["starts_by_slot"] == {0: 2, 1: 1, 2: 3}
    assert summary["decisions"] == 6


# --- it must not grow without bound ----------------------------------------


def test_the_log_keeps_only_the_most_recent_decisions(tmp_path, enabled):
    for i in range(RD.MAX_ENTRIES + 25):
        _record(tmp_path, date_str=f"day-{i}")
    rows = RD.read_decisions(data_dir=tmp_path)
    assert len(rows) == RD.MAX_ENTRIES
    # The newest survive; the oldest are dropped.
    assert rows[-1]["date"] == f"day-{RD.MAX_ENTRIES + 24}"


# --- it must never break a sim ---------------------------------------------


def test_recording_swallows_an_unwritable_destination(tmp_path, enabled):
    """The sim has already decided this start; a diagnostic cannot veto it."""
    blocked = tmp_path / "a-file-not-a-dir"
    blocked.write_text("x", encoding="utf-8")
    _record(blocked / "nested")  # no exception


def test_a_corrupt_log_is_replaced_rather_than_crashing(tmp_path, enabled):
    (tmp_path / RD.LOG_FILENAME).write_text("{not json", encoding="utf-8")
    _record(tmp_path)
    assert len(RD.read_decisions(data_dir=tmp_path)) == 1


def test_reading_a_missing_log_is_empty_not_an_error(tmp_path):
    assert RD.read_decisions(data_dir=tmp_path) == []


# --- the tracker actually calls it -----------------------------------------


def test_assigning_a_starter_records_the_decision(tmp_path, monkeypatch, enabled):
    """Wiring test: the log is worthless if the hook is not in the real path."""
    from utils.pitcher_recovery import PitcherRecoveryTracker

    monkeypatch.setattr(
        "services.rotation_diagnostics._log_path",
        lambda data_dir=None: tmp_path / RD.LOG_FILENAME,
    )
    tracker = PitcherRecoveryTracker(tmp_path / "recovery.json")
    tracker.data["teams"]["CHI"] = {
        "rotation": ["P1", "P2", "P3"],
        "next_index": 1,
        "pitchers": {p: {"available_on": "2026-06-01"} for p in ["P1", "P2", "P3"]},
    }
    monkeypatch.setattr(tracker, "_ensure_team", lambda *a, **k: tracker.data["teams"]["CHI"])

    assert tracker.assign_starter("CHI", "2026-06-13", "players.csv", "rosters") == "P2"
    rows = RD.read_decisions(data_dir=tmp_path)
    assert len(rows) == 1
    assert rows[0]["team"] == "CHI"
    assert rows[0]["slot_chosen"] == 1
