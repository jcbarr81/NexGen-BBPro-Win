"""Release 3 (audit M18): the per-league, persisted physics rest state."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest

from physics_sim.config import load_tuning
from physics_sim.engine import _pitcher_is_rested
from physics_sim.usage import UsageState
from playbalance import parallel_day, usage_store

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_cache():
    usage_store.clear_cache()
    yield
    usage_store.clear_cache()


def _outing(state: UsageState, pid: str, pitches: int, day: int) -> None:
    state.record_outing(
        pitcher_id=pid, pitches=pitches, day=day, multiplier=1.0, tuning=load_tuning()
    )


def test_state_round_trips_through_a_new_process(tmp_path):
    state, day = usage_store.context("2026-04-01", data_dir=tmp_path)
    assert day == 0
    _outing(state, "P1", 30, day)
    usage_store.mark_dirty(data_dir=tmp_path)
    saved = json.loads((tmp_path / usage_store.FILENAME).read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["season_start"] == "2026-04-01"
    assert saved["last_date"] == "2026-04-01"

    usage_store.clear_cache()  # what a fresh process sees
    again, day2 = usage_store.context("2026-04-02", data_dir=tmp_path)
    assert again is not state
    assert again.workloads["P1"] == state.workloads["P1"]
    assert day2 == 1


def test_the_same_date_keeps_its_day(tmp_path):
    state, day = usage_store.context("2026-04-03", data_dir=tmp_path)
    same, day_again = usage_store.context("2026-04-03", data_dir=tmp_path)
    assert same is state and day_again == day


def test_deferred_saves_write_once_at_exit(tmp_path):
    path = tmp_path / usage_store.FILENAME
    with usage_store.deferred_saves(data_dir=tmp_path):
        with usage_store.deferred_saves(data_dir=tmp_path):  # re-entrant
            state, day = usage_store.context("2026-04-01", data_dir=tmp_path)
            _outing(state, "P1", 20, day)
            usage_store.mark_dirty(data_dir=tmp_path)
        assert not path.exists()
    assert path.exists()
    assert usage_store.save_if_dirty(data_dir=tmp_path) is False


def test_deferred_saves_save_when_the_day_fails(tmp_path):
    path = tmp_path / usage_store.FILENAME
    with pytest.raises(RuntimeError):
        with usage_store.deferred_saves(data_dir=tmp_path):
            usage_store.context("2026-04-01", data_dir=tmp_path)
            usage_store.mark_dirty(data_dir=tmp_path)
            raise RuntimeError("boom")
    assert path.exists()


def test_a_new_season_starts_a_fresh_state_and_is_logged(tmp_path, caplog):
    state, _ = usage_store.context("2026-09-28", data_dir=tmp_path)
    _outing(state, "P1", 30, 0)
    with caplog.at_level(logging.INFO, logger="playbalance.usage_store"):
        fresh, day = usage_store.context("2027-04-01", data_dir=tmp_path)
    assert fresh is not state
    assert day == 0
    assert "P1" not in fresh.workloads
    assert "new season" in caplog.text


def test_a_season_that_crosses_new_year_keeps_its_rest_state(tmp_path):
    """Old 20-team schedules end Dec 23 - Jan 12 and dated playoffs can run
    into January: a date in the next calendar year is not a new season."""
    state, _ = usage_store.context("2026-04-01", data_dir=tmp_path)
    when = date(2026, 4, 1)
    while when < date(2026, 12, 23):  # a long season, simmed weekly
        when += timedelta(days=7)
        assert usage_store.context(when.isoformat(), data_dir=tmp_path)[0] is state
    late, day = usage_store.context("2026-12-30", data_dir=tmp_path)
    assert late is state
    _outing(state, "P1", 30, day)
    usage_store.mark_dirty(data_dir=tmp_path)

    january, jan_day = usage_store.context("2027-01-02", data_dir=tmp_path)
    assert january is state
    assert jan_day == day + 3
    assert january.workloads["P1"].last_used_day == day

    # ... and in a new process, from the saved file.
    usage_store.mark_dirty(data_dir=tmp_path)
    usage_store.clear_cache()
    reloaded, reload_day = usage_store.context("2027-01-12", data_dir=tmp_path)
    assert reload_day == day + 13
    assert reloaded.workloads["P1"].last_used_day == day


def test_a_continuous_sim_past_a_full_season_span_starts_fresh(tmp_path, caplog):
    state, _ = usage_store.context("2026-03-01", data_dir=tmp_path)
    _outing(state, "P1", 30, 0)
    when = date(2026, 3, 1)
    # Play every week for a year: no offseason gap, but well past any season.
    for _ in range(50):
        when += timedelta(days=7)
        current, _day = usage_store.context(when.isoformat(), data_dir=tmp_path)
    assert current is not state
    assert "P1" not in current.workloads


def test_a_backwards_date_resets_and_is_logged(tmp_path, caplog):
    state, _ = usage_store.context("2026-05-10", data_dir=tmp_path)
    _outing(state, "P1", 30, 0)
    with caplog.at_level(logging.WARNING, logger="playbalance.usage_store"):
        fresh, day = usage_store.context("2026-05-01", data_dir=tmp_path)
    assert fresh is not state and day == 0
    assert "before the last simmed date" in caplog.text


def test_undated_or_non_date_tokens_have_no_state(tmp_path):
    assert usage_store.context(None, data_dir=tmp_path) == (None, None)
    assert usage_store.context("", data_dir=tmp_path) == (None, None)
    assert usage_store.context("opening-day", data_dir=tmp_path) == (None, None)


def test_two_interleaved_leagues_keep_separate_state(tmp_path):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    a1, a_day1 = usage_store.context("2026-04-01", data_dir=a_dir)
    b1, b_day1 = usage_store.context("2026-06-01", data_dir=b_dir)
    _outing(a1, "PA", 25, a_day1)
    a2, a_day2 = usage_store.context("2026-04-02", data_dir=a_dir)
    b2, b_day2 = usage_store.context("2026-06-02", data_dir=b_dir)
    assert a2 is a1 and b2 is b1 and a1 is not b1
    assert (a_day1, a_day2) == (0, 1)
    assert (b_day1, b_day2) == (0, 1)
    assert "PA" not in b1.workloads


def test_reset_forgets_state_and_deletes_the_file(tmp_path):
    state, _ = usage_store.context("2026-04-01", data_dir=tmp_path)
    _outing(state, "P1", 30, 0)
    usage_store.mark_dirty(data_dir=tmp_path)
    usage_store.reset(data_dir=tmp_path)
    assert not (tmp_path / usage_store.FILENAME).exists()
    fresh, day = usage_store.context("2026-04-02", data_dir=tmp_path)
    assert fresh is not state and "P1" not in fresh.workloads and day == 0


def test_a_damaged_file_starts_fresh(tmp_path):
    (tmp_path / usage_store.FILENAME).write_text("{not json", encoding="utf-8")
    state, day = usage_store.context("2026-04-01", data_dir=tmp_path)
    assert isinstance(state, UsageState) and not state.workloads and day == 0


def test_bootstrap_replays_this_seasons_tracker_appearances(tmp_path):
    def _recent(*entries):
        return [
            {"date": d, "pitches": p, "appeared": a, "warmed_only": w}
            for d, p, a, w in entries
        ]

    tracker = {
        "teams": {
            "AAA": {
                "pitchers": {
                    "P1": {"recent": _recent(("2026-05-10", 30, True, False))},
                    "P2": {
                        "recent": _recent(
                            ("2026-05-11", 15, True, False),
                            ("2026-05-11", 0, False, True),  # warm-up only
                        )
                    },
                    "OLD": {"recent": _recent(("2025-09-28", 30, True, False))},
                    "LATER": {"recent": _recent(("2026-05-12", 30, True, False))},
                }
            }
        }
    }
    (tmp_path / "pitcher_recovery.json").write_text(json.dumps(tracker), encoding="utf-8")
    state, day = usage_store.context("2026-05-12", data_dir=tmp_path)
    assert set(state.workloads) == {"P1", "P2"}
    assert state.workloads["P2"].appearances == 1
    assert state.workloads["P2"].last_pitches == 15
    assert day == 2
    tuning = load_tuning()
    # 15 pitches yesterday: one full day off needed, so not rested today.
    assert not _pitcher_is_rested(
        pitcher_id="P2", role="MR", usage_state=state, game_day=day, tuning=tuning
    )
    # 30 pitches two days ago needs two days off: still not rested today.
    assert not _pitcher_is_rested(
        pitcher_id="P1", role="MR", usage_state=state, game_day=day, tuning=tuning
    )


def test_bootstrap_replays_december_outings_into_a_january_date(tmp_path):
    """A season crossing New Year bootstraps from last month's appearances."""
    tracker = {
        "teams": {
            "AAA": {
                "pitchers": {
                    "P1": {
                        "recent": [
                            {"date": "2026-12-31", "pitches": 30, "appeared": True},
                        ]
                    },
                    "OLD": {
                        "recent": [
                            {"date": "2026-09-28", "pitches": 30, "appeared": True},
                        ]
                    },
                }
            }
        }
    }
    (tmp_path / "pitcher_recovery.json").write_text(json.dumps(tracker), encoding="utf-8")
    state, day = usage_store.context("2027-01-02", data_dir=tmp_path)
    assert set(state.workloads) == {"P1"}
    assert day == 2
    assert state.workloads["P1"].last_used_day == 0


def test_no_bootstrap_after_an_explicit_reset(tmp_path):
    tracker = {
        "teams": {
            "AAA": {
                "pitchers": {
                    "P1": {
                        "recent": [
                            {"date": "2026-05-10", "pitches": 30, "appeared": True}
                        ]
                    }
                }
            }
        }
    }
    (tmp_path / "pitcher_recovery.json").write_text(json.dumps(tracker), encoding="utf-8")
    usage_store.reset(data_dir=tmp_path)
    state, _ = usage_store.context("2026-05-11", data_dir=tmp_path)
    assert not state.workloads


def test_live_path_writes_into_the_league_not_repo_data(tmp_path, monkeypatch):
    from playbalance import game_runner
    from utils import path_utils

    root = tmp_path / "root"
    league_data = root / "leagues" / "lg1" / "data"
    league_data.mkdir(parents=True)
    # A complete league dir, so nothing is seeded into it from the repo.
    for name in ("teams.csv", "players.csv", "users.txt"):
        (league_data / name).write_text("", encoding="utf-8")
    repo_file = REPO_ROOT / "data" / usage_store.FILENAME
    existed = repo_file.exists()
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    path_utils._DATA_DIR_CACHE.clear()
    token = path_utils.set_request_league("lg1")
    try:
        state, day = game_runner._physics_usage_context("2026-04-01")
        _outing(state, "P1", 20, day)
        usage_store.mark_dirty()
        written = usage_store.usage_path()
    finally:
        path_utils.reset_request_league(token)
        path_utils._DATA_DIR_CACHE.clear()
    assert written.exists()
    assert written.resolve().is_relative_to(league_data.resolve())
    assert repo_file.exists() == existed


def test_parallel_payload_carries_and_merges_game_index():
    state = UsageState(current_day=4, game_index=3)
    _outing(state, "P1", 20, 4)
    payload = parallel_day.usage_state_to_payload(state, 4)
    assert payload["game_index"] == 3
    rebuilt = parallel_day.usage_payload_to_state(payload)
    assert rebuilt.game_index == 3
    assert rebuilt.workloads["P1"] == state.workloads["P1"]

    out = dict(payload, current_day=5, game_index=4)
    diff = parallel_day.diff_usage_out(payload, out)
    assert diff["game_index"] == 4
    parent = UsageState(current_day=4, game_index=3)
    parallel_day.merge_usage_into_state(parent, diff)
    parallel_day.merge_usage_into_state(parent, dict(diff, game_index=4))
    assert parent.game_index == 4 and parent.current_day == 5


def test_payload_ignores_unknown_workload_fields():
    payload = {
        "current_day": 1,
        "workloads": {"P1": {"fatigue_debt": 3.0, "field_from_the_future": 1}},
        "batter_workloads": {},
    }
    state = parallel_day.usage_payload_to_state(payload)
    assert state.workloads["P1"].fatigue_debt == 3.0
    assert state.game_index == 0


# ---------------------------------------------------------------------------
# The calendar-day rest clock (decision 9)
# ---------------------------------------------------------------------------
class _Arm:
    def __init__(self, player_id: str, durability: float = 50.0) -> None:
        self.player_id = player_id
        self.durability = durability


def _advance(state: UsageState, day: int, *ids: str) -> None:
    state.advance_day(day=day, pitchers=[_Arm(i) for i in ids], tuning=load_tuning())


def test_context_day_is_the_calendar_day(tmp_path):
    _, opening = usage_store.context("2026-04-01", data_dir=tmp_path)
    _, after_off_day = usage_store.context("2026-04-03", data_dir=tmp_path)
    _, next_week = usage_store.context("2026-04-08", data_dir=tmp_path)
    assert (opening, after_off_day, next_week) == (0, 2, 7)


def test_calendar_day_helper():
    from datetime import date

    from physics_sim.usage import calendar_day

    assert calendar_day("2026-04-03", "2026-04-01") == 2
    assert calendar_day(date(2026, 5, 1), date(2026, 4, 1)) == 30
    with pytest.raises(ValueError):
        calendar_day("not-a-date", "2026-04-01")


def test_an_off_day_is_rest_for_a_reliever(tmp_path):
    tuning = load_tuning()
    every_day, off_day = tmp_path / "every", tmp_path / "off"
    for league in (every_day, off_day):
        state, day = usage_store.context("2026-04-01", data_dir=league)
        _advance(state, day, "RP")
        _outing(state, "RP", 20, day)  # 20 pitches: one full day off needed
    # One league plays again on 04-02; the other is off and plays on 04-03.
    tired, next_day = usage_store.context("2026-04-02", data_dir=every_day)
    rested, after_off_day = usage_store.context("2026-04-03", data_dir=off_day)
    assert not _pitcher_is_rested(
        pitcher_id="RP", role="MR", usage_state=tired, game_day=next_day, tuning=tuning
    )
    assert _pitcher_is_rested(
        pitcher_id="RP",
        role="MR",
        usage_state=rested,
        game_day=after_off_day,
        tuning=tuning,
    )


def test_off_days_break_pitcher_and_batter_streaks():
    tuning = load_tuning()
    state = UsageState()
    for day in (0, 1):
        state.advance_day(day=day, pitchers=[_Arm("RP")], batters=[_Arm("B")], tuning=tuning)
        _outing(state, "RP", 10, day)
        state.record_batter_game(player_id="B", day=day, durability=50.0, tuning=tuning)
    assert state.workloads["RP"].consecutive_days_used == 2
    assert state.batter_workloads["B"].consecutive_days_used == 2
    # Day 2 is an off day; day 3 starts a new streak.
    state.advance_day(day=3, pitchers=[_Arm("RP")], batters=[_Arm("B")], tuning=tuning)
    assert state.workloads["RP"].consecutive_days_used == 0
    assert state.batter_workloads["B"].consecutive_days_used == 0
    _outing(state, "RP", 10, 3)
    state.record_batter_game(player_id="B", day=3, durability=50.0, tuning=tuning)
    assert state.workloads["RP"].consecutive_days_used == 1
    assert state.batter_workloads["B"].consecutive_days_used == 1


def test_game_index_counts_game_dates_not_calendar_days(tmp_path):
    for token in ("2026-04-01", "2026-04-02", "2026-04-04", "2026-04-04", "2026-04-08"):
        state, day = usage_store.context(token, data_dir=tmp_path)
        _advance(state, day, "RP")
    assert state.current_day == 7
    assert state.game_index == 3  # four game dates, 0-based
    usage_store.mark_dirty(data_dir=tmp_path)
    usage_store.clear_cache()
    again, _ = usage_store.context("2026-04-09", data_dir=tmp_path)
    assert again.game_index == 3  # persisted; the game's advance_day bumps it


def test_rotation_fallback_uses_the_game_index():
    from physics_sim.engine import _order_pitchers_for_game
    from physics_sim.models import PitcherRatings

    staff = [PitcherRatings.from_row({"player_id": f"S{i}"}) for i in range(1, 6)]
    roles = {f"S{i}": f"SP{i}" for i in range(1, 6)}
    state = UsageState(current_day=9, game_index=7)
    ordered = _order_pitchers_for_game(
        staff, roles_by_id=roles, usage_state=state, game_day=9, tuning=load_tuning()
    )
    assert ordered[0].player_id == "S3"  # slot 7 % 5, not calendar day 9 % 5


def test_closer_appearance_cap_counts_game_dates():
    from physics_sim.engine import PitcherState, _apply_usage_state
    from physics_sim.models import PitcherRatings

    tuning = load_tuning()
    # Calendar day 20 but only the 10th game date: the 45% cap is
    # int(10 * 0.45) = 4 appearances, not int(21 * 0.45) = 9.
    state = UsageState(current_day=20, game_index=9)
    workload = state.workload_for("CL1")
    workload.last_used_day = 15
    workload.last_pitches = 10
    workload.appearances = 5
    closer = PitcherState(
        pitcher=PitcherRatings.from_row({"player_id": "CL1"}),
        fatigue_start=50.0,
        fatigue_limit=60.0,
        rest_role="CL",
        staff_role="CL",
    )
    _apply_usage_state(closer, state, 20, tuning)
    assert closer.available is False
