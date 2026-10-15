"""Release 6b, stage 1: carry with drag, five-point fences, altitude, parks.

``carry_model`` 1 (``physics_sim.ballflight``): a batted ball's carry, hang
time and descent angle come from a table of a drag-and-lift trajectory
(``physics_sim/carry_table.json``, built by ``scripts/build_carry_table.py``)
and a home run must clear a five-point fence plus its wall. Off (every
generation up to 6) nothing here is read.
"""

from __future__ import annotations

import csv
import math

import pytest

from physics_sim import ballflight as bf
from physics_sim import physics
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.park import Park, load_park
from playbalance.field_geometry import Stadium
from utils import park_utils


@pytest.fixture(autouse=True)
def _pinned_parks(monkeypatch):
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(park_utils.get_base_dir() / "data"))
    bf.clear_fence_cache()
    yield
    bf.clear_fence_cache()


ON = {"carry_model": 1.0, "bb6_carry_scale": 1.0, "bb6_altitude_strength": 1.0}


def test_the_switch_is_off_by_default_and_registered():
    assert DEFAULT_TUNING["carry_model"] == 0.0
    assert not bf.carry_model_on(load_tuning())
    assert bf.carry_model_on(load_tuning(ON))
    assert set(DEFAULT_TUNING["bb6_park_fence_shift_left_ft"]) == set(bf.FITTED_PARK_IDS)
    assert set(DEFAULT_TUNING["bb6_park_fence_shift_right_ft"]) == set(bf.FITTED_PARK_IDS)
    assert not any(DEFAULT_TUNING["bb6_park_fence_shift_left_ft"].values())


@pytest.mark.parametrize(
    "ev, la", [(70, 10), (90, 25), (100, 28), (104, 31), (110, 40), (60, -5), (86, 60)]
)
def test_the_table_is_the_trajectory_on_its_grid(ev, la):
    carry, hang, descent = bf.flight(ev, la)
    want = bf.trajectory(ev, la)
    assert carry == pytest.approx(round(want[0], 2), abs=0.006)
    assert hang == pytest.approx(round(want[1], 4), abs=1e-4)
    assert descent == pytest.approx(round(want[2], 2), abs=0.006)
    thin = bf.flight(ev, la, bf.THIN_AIR_DENSITY)
    assert thin[0] == pytest.approx(bf.trajectory(ev, la, bf.THIN_AIR_DENSITY)[0], abs=0.006)


def test_the_flight_is_realistic():
    # 100 mph at 28 degrees about 400 ft (the design's table: 404).
    assert 395 < bf.flight(100, 28)[0] < 412
    # Drag: about three quarters of the vacuum range.
    vacuum = (100 * 1.4667) ** 2 / 32.174 * math.sin(math.radians(56))
    assert 0.65 * vacuum < bf.flight(100, 28)[0] < 0.8 * vacuum
    # Further with exit velocity; a peak near 30 degrees, not 45.
    assert bf.flight(105, 28)[0] > bf.flight(100, 28)[0]
    best = max(range(15, 50), key=lambda la: bf.flight(105, la)[0])
    assert 25 <= best <= 35
    # Hang time grows with launch angle; descent is steeper than launch.
    assert bf.flight(95, 45)[1] > bf.flight(95, 25)[1]
    assert bf.flight(100, 28)[2] > 28


def test_altitude_thins_the_air_through_the_table():
    coors = bf.air_density_ratio(5197)
    assert coors == pytest.approx(bf.THIN_AIR_DENSITY, abs=0.001)
    tuning = load_tuning(ON)
    sea = bf.carry(102, 28, 0.0, tuning)[0]
    high = bf.carry(102, 28, 5197.0, tuning)[0]
    assert 1.04 < high / sea < 1.08  # the integrator's +5 to +7%
    half = load_tuning({**ON, "bb6_altitude_strength": 0.5})
    gain = bf.carry(102, 28, 5197.0, half)[0] / sea - 1.0
    assert gain == pytest.approx((high / sea - 1.0) / 2.0, rel=0.02)
    # bb6_carry_scale scales carry and the hang time by its square root.
    scaled = load_tuning({**ON, "bb6_carry_scale": 0.9})
    assert bf.carry(100, 28, 0.0, scaled)[0] == pytest.approx(0.9 * bf.flight(100, 28)[0])
    assert bf.carry(100, 28, 0.0, scaled)[1] == pytest.approx(
        math.sqrt(0.9) * bf.flight(100, 28)[1]
    )


def test_the_generic_park_is_the_mirrored_mean_of_the_30_parks():
    fences = park_utils.park_fences()
    current = [fences[pid] for pid in bf.CURRENT_PARK_IDS]
    assert all(row[2] for row in current)  # each marked generic
    assert sum(1 for row in fences.values() if row[2]) == 30
    assert bf.mean_fence([(d, h) for d, h, _g in current]) == bf.GENERIC_FENCE
    # Symmetric; about 330 / 386 / 403 ft with 10 ft walls.
    d = bf.GENERIC_FENCE.distances
    assert d[0] == d[4] and d[1] == d[3]
    assert d[0] == pytest.approx(330, abs=1) and d[1] == pytest.approx(386, abs=1.5)
    assert d[2] == pytest.approx(403, abs=1)


def test_a_real_park_reads_its_own_fence_and_a_made_up_one_the_generic():
    tuning = load_tuning(ON)
    fenway = bf.park_fence(load_park("Fenway Park"), tuning)
    assert fenway.park_id == "BOS07"
    assert fenway.distances[0] == 310.0 and fenway.heights[0] == 37.0
    assert bf.park_fence(load_park("Generic Park"), tuning) is bf.GENERIC_FENCE
    assert bf.park_fence(Park(name="", stadium=Stadium()), tuning) is bf.GENERIC_FENCE
    # The 2023-2026 changes generation 7 reads from ParkFences.csv only.
    assert bf.park_fence(load_park("Comerica Park"), tuning).distances[2] == 412.0
    assert bf.park_fence(load_park("Kauffman Stadium"), tuning).distances[1] == 379.0
    # ... while every earlier engine still reads ParkConfig.csv's row.
    assert park_utils.stadium_from_name("Comerica Park").center == 420.0


def test_the_fence_is_five_straight_lines_and_the_wall_counts():
    fence = bf.Fence((330.0, 380.0, 400.0, 370.0, 320.0), (10.0, 10.0, 10.0, 20.0, 20.0))
    assert bf.fence_at(fence, -45.0) == (330.0, 10.0)
    assert bf.fence_at(fence, 0.0) == (400.0, 10.0)
    assert bf.fence_at(fence, 33.75)[0] == pytest.approx(345.0)
    assert bf.fence_at(fence, 60.0) == (320.0, 20.0)
    needed, wall = bf.home_run_fence(fence, 45.0, 45.0)
    assert wall == 320.0 and needed == pytest.approx(340.0)
    # A flatter descent needs more carry over the same wall.
    assert bf.home_run_fence(fence, 45.0, 30.0)[0] > needed


def test_a_parks_sides_move_by_its_shifts():
    tuning = load_tuning({
        **ON,
        "bb6_park_fence_shift_left_ft": {"BOS07": 10.0},
        "bb6_park_fence_shift_right_ft": {"BOS07": -4.0},
    })
    base = bf.park_fence(load_park("Fenway Park"), load_tuning(ON)).distances
    moved = bf.park_fence(load_park("Fenway Park"), tuning).distances
    assert [m - b for m, b in zip(moved, base)] == pytest.approx([10, 10, 3, -4, -4])
    # The generic park has no shift.
    assert bf.park_fence(load_park("Generic Park"), tuning) is bf.GENERIC_FENCE


def test_resolve_batted_ball_uses_the_table_and_the_fence_only_when_on():
    park = load_park("Generic Park")
    off = load_tuning()
    on = load_tuning(ON)
    legacy = physics.resolve_batted_ball(
        exit_velo=100.0, launch_angle=28.0, spray_angle=0.0, park=park, tuning=off
    )
    assert legacy[0] == pytest.approx(physics.estimate_carry_distance(100.0, 28.0, off, park))
    flown = physics.resolve_batted_ball(
        exit_velo=100.0, launch_angle=28.0, spray_angle=0.0, park=park, tuning=on
    )
    assert flown[0] == pytest.approx(bf.flight(100.0, 28.0)[0])
    # 404 ft to straightaway centre is not out of a 403 ft park with a
    # 9.4 ft wall; the same ball down the line is.
    assert flown[1] is False
    line = physics.resolve_batted_ball(
        exit_velo=100.0, launch_angle=28.0, spray_angle=40.0, park=park, tuning=on
    )
    assert line[1] is True and line[3] == "hr"


def test_the_targets_file_and_the_fences_file_name_the_fitted_parks():
    from scripts.fit_park_hr_factors import read_targets

    targets = read_targets()
    assert set(targets) == set(bf.FITTED_PARK_IDS)
    for pid in bf.CURRENT_PARK_IDS:
        assert targets[pid]["hr_lhb"] and targets[pid]["hr_rhb"], pid
    # The shrinkage rule: s seasons -> w = s / (s + 1) where flagged.
    assert targets["KAN06"]["shrink_weight"] == pytest.approx(0.5)
    assert targets["SAC01"]["shrink_weight"] == pytest.approx(2 / 3, abs=1e-3)
    assert targets["SAC01"]["hr"] == pytest.approx(100 + (124 - 100) * 2 / 3, abs=0.1)
    fences = park_utils.park_fences()
    assert set(bf.CURRENT_PARK_IDS) <= set(fences)


def test_the_two_temporary_parks_resolve():
    # Through generation 7's own file only (tests/test_r7_park_data.py).
    for name, pid in (("Sutter Health Park", "SAC01"), ("George M. Steinbrenner Field", "TAM02")):
        found = park_utils.park_fence_for_name(name)
        assert found is not None and found[0] == pid
    with open(park_utils._parks_master_path(), newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert not {"SAC01", "TAM02"} & {r["PARKID"] for r in rows}
