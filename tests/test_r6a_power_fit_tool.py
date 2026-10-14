"""Release 6a (power): ``scripts/fit_power_table.py``, the re-fit of the
Power curve's top anchors (owner decision 6).

The script forces the bat speed a hitter's Power adds and solves it for a
home run total per 650 PA at each of the four anchors. It is re-run when
exit velocity or carry changes; these tests pin its arithmetic and that the
Monte Carlo it stands on answers to the forced value and to Contact. The
fitted numbers themselves are Monte Carlo work (the build report).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

import scripts.fit_power_table as fit_tool
import scripts.kpi_extras as kpi_extras
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import load_tuning
from physics_sim.models import PitcherRatings
from physics_sim.park import load_park
from services.league_rating_centers import active_pitcher_workloads

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_power.json"


def _overrides():
    run = kpis.resolve_run_overrides(engine=6, overrides_path=PROFILE_PATH)
    return kpis.with_rating_centers(run, CALIBRATION / "players.csv", CALIBRATION)


def test_the_targets_are_the_owners_anchors():
    """Decision 6 (35 / 40 / 45 at stored 80 / 85 / 90) and decision 16
    (stored 99: about 48 with average Contact, 57 with Contact 80)."""
    assert fit_tool.TARGETS == (
        (60.0, 50.0, 35.0), (61.67, 50.0, 40.0), (63.33, 50.0, 45.0),
        (66.33, 50.0, 48.0), (66.33, 60.0, 57.0),
    )
    assert fit_tool.SEASON_PA == 650.0


def test_solve_offset_interpolates_on_log_home_runs():
    rate = lambda offset: 30.0 * math.exp(0.05 * (offset - 9.0))  # noqa: E731
    points = [(offset, rate(offset)) for offset in (7.5, 9.0, 10.5)]
    assert fit_tool.solve_offset(points, rate(9.6)) == pytest.approx(9.6)
    assert fit_tool.solve_offset(points, rate(8.1)) == pytest.approx(8.1)
    # Outside the offsets that were run, the nearest pair is carried on.
    assert fit_tool.solve_offset(points, rate(11.5)) == pytest.approx(11.5)
    assert fit_tool.solve_offset(points, rate(6.0)) == pytest.approx(6.0)
    assert fit_tool.solve_offset(list(reversed(points)), 30.0) == pytest.approx(9.0)
    for bad in ([(9.0, 30.0)], [(8.0, 0.0), (9.0, 30.0)], [(8.0, 30.0), (9.0, 30.0)]):
        with pytest.raises(ValueError):
            fit_tool.solve_offset(bad, 31.0)


def test_the_table_entries_fill_in_the_nineties_and_the_tail():
    table = fit_tool.table_from({60.0: 9.9, 61.67: 12.3, 63.33: 14.5, 66.33: 15.0})
    assert table == {
        "60": 9.9, "61.67": 12.3, "63.33": 14.5, "65": 14.75, "66.33": 15.0,
        "80": 17.05,
    }
    assert list(table) == ["60", "61.67", "63.33", "65", "66.33", "80"]
    # Every key is an anchor a profile may set.
    from physics_sim.config import DEFAULT_TUNING

    assert set(table) <= set(DEFAULT_TUNING["bat_speed_power_table"])


def test_generation_6_holds_the_anchors_the_script_solved():
    """The profile's top anchors are the script's output (to 0.05 mph)."""
    import json

    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    table = profile["bat_speed_power_table"]
    assert table["65"] == pytest.approx((table["63.33"] + table["66.33"]) / 2.0)
    assert table["80"] == pytest.approx(
        table["66.33"] + (80.0 - 66.33) * fit_tool.TAIL_SLOPE, abs=0.006
    )
    tuning = load_tuning(_overrides())
    for level in ("60", "61.67", "63.33", "66.33"):
        assert fit_tool.current_offset(tuning, float(level)) == pytest.approx(
            table[level]
        )


def test_a_forced_table_gives_every_hitter_the_same_bat_speed():
    tuning = load_tuning({**_overrides(), **fit_tool.forced_table(11.25)})
    for power in (1.0, 30.0, 50.0, 63.33, 99.0):
        assert fit_tool.current_offset(tuning, power) == 11.25


def _cell(tuning, **kwargs):
    staff = [
        (PitcherRatings.from_row(row), weight)
        for row, weight in active_pitcher_workloads(CALIBRATION)
    ]
    state = random.getstate()
    try:
        return kpi_extras._simulate_staff_cell(
            n=6000, seed=77, tuning=tuning, staff=staff, park=load_park(None), **kwargs
        )
    finally:
        random.setstate(state)


def test_the_monte_carlo_answers_to_the_forced_value_and_to_contact():
    overrides = _overrides()
    slow = _cell(load_tuning({**overrides, **fit_tool.forced_table(6.0)}), power=63.33)
    fast = _cell(load_tuning({**overrides, **fit_tool.forced_table(18.0)}), power=63.33)
    assert fast["hr"] > slow["hr"] * 1.4
    assert fast["k"] == slow["k"] and fast["bb"] == slow["bb"]  # the same pitches
    tuning = load_tuning(overrides)
    average = _cell(tuning, power=63.33)
    # Contact 50 is the table's hitter, cell for cell.
    assert _cell(tuning, power=63.33, contact=50.0) == average
    contact = _cell(tuning, power=63.33, contact=60.0)
    assert contact["k"] < average["k"] * 0.7
    assert contact["hr"] > average["hr"]


def test_a_small_fit_runs_end_to_end():
    result = fit_tool.fit(
        base_dir=CALIBRATION, overrides=_overrides(), pa=4000, seeds=(5,),
        step=3.0, procs=1, targets=((63.33, 50.0, 45.0),),
    )
    (row,) = result["anchors"]
    assert row["power"] == 63.33 and row["target_hr650"] == 45.0
    assert [point["offset"] for point in row["response"]] == pytest.approx(
        [row["table_offset"] - 3.0, row["table_offset"], row["table_offset"] + 3.0]
    )
    rates = [point["hr650"] for point in row["response"]]
    assert rates[0] < rates[2]
    # 12,000 PA cannot fit an anchor; it lands in the right part of the scale.
    assert 8.0 < row["solved_offset"] < 22.0
    assert list(result["table"]) == ["63.33"]


def test_two_targets_at_one_power_share_the_anchor():
    """Decision 16 names two targets at stored 99; the anchor is the mean
    of the two solves, and both rows are reported."""
    result = fit_tool.fit(
        base_dir=CALIBRATION, overrides=_overrides(), pa=3000, seeds=(9,),
        step=3.0, procs=1, targets=((66.33, 50.0, 48.0), (66.33, 60.0, 57.0)),
    )
    rows = result["anchors"]
    assert [(r["contact"], r["target_hr650"]) for r in rows] == [
        (50.0, 48.0), (60.0, 57.0),
    ]
    mean = (rows[0]["solved_offset"] + rows[1]["solved_offset"]) / 2.0
    assert result["table"]["66.33"] == pytest.approx(round(mean, 2))
