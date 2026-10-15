"""Re-fit the top anchors of the Power curve (``bat_speed_power_table``).

Release 6a, owner decisions 6 and 16: on the full 1-99 stored scale a hitter
with Power in the 90s hits 45 to 55 home runs a year, depending on his
Contact, and the top of the scale keeps paying (stored 99 clearly better
than 90). In engine ratings (stored 80 / 85 / 90 / 99 = engine 60 / 61.67 /
63.33 / 66.33) the targets are home runs per 650 PA:

    Power 60     average Contact      35
    Power 61.67  average Contact      40
    Power 63.33  average Contact      45
    Power 66.33  average Contact      48
    Power 66.33  Contact 60 (st. 80)  57

The two Power 66.33 targets share one anchor: its value is the mean of the
two solves, and both are printed.

Home runs are a distance-against-the-fence threshold, so the bat speed that
gives each number depends on everything between the bat and the wall. This
script re-solves the anchors whenever exit velocity or carry changes
(RELEASE6_PLAN.md 2.2), by the design brief's response-table procedure:

1. For each anchor, a Monte Carlo on the real pitch kernel: the league's
   average hitter at that league-relative Power and Contact, with the bat
   speed his Power adds FORCED to the table's value and to ``--step`` mph
   either side of it, against the fixture's ACT pitchers drawn by expected
   workload, in the generic park (``kpi_extras._simulate_staff_cell``, the
   hitter of the ``power_hr600_p<level>`` table).
2. The forced value that gives the target, interpolated on log home runs.

It prints the solved anchors and the table entries to put in the profile.
The anchors of the 90s are set between and beyond the solved ones (65 half
way from 63.33 to 66.33; 80 on a 0.15 mph-a-point line past 66.33, which no
stored rating can reach).

It does NOT set the weak-bat side or the centre. Those are decision 4's
slope (0.55 mph a point below 50 on average, rising smoothly through the
middle of the scale) and the league home run level, and the level is
settled with seasons, not here: move the 30-to-57 anchors together until
home runs per team-game match the previous generation on
calibration seeds 1-8 and the league fixture seeds 1-4 (0.1 mph at the
centre is about 0.6% of league home runs), then read ``power_hr600_p30``
and ``_p40`` off the matchup grid (4 to 10).

    python scripts/fit_power_table.py --base-dir data/calibration --engine 6 \
        --tuning-overrides scripts/kpi_profiles/r6_power.json

About four minutes at the defaults (600,000 PA an anchor value; one
standard error is about 0.5% of the home runs, 0.1 mph).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# (league-relative Power, league-relative Contact, home runs per 650 PA).
TARGETS: tuple[tuple[float, float, float], ...] = (
    (60.0, 50.0, 35.0),
    (61.67, 50.0, 40.0),
    (63.33, 50.0, 45.0),
    (66.33, 50.0, 48.0),
    (66.33, 60.0, 57.0),
)
# Release 6b (``--whole``): every anchor of the table, not only the top, for
# a batted-ball model on which the whole curve moved (drag carry). Average
# Contact; HR per 650 PA. Decision 4: Power 30 and 40 inside 4-10 HR per
# 600 PA (7.0 and 9.2 per 650 = 6.5 and 8.5 per 600); decision 16 at the
# top (as TARGETS); the middle log-linear between Power 40 and 60, so the
# curve has no flat spot and no kink.
_LOW, _HIGH = (40.0, 9.2), (60.0, 35.0)
_RATE = math.log(_HIGH[1] / _LOW[1]) / (_HIGH[0] - _LOW[0])
WHOLE_TARGETS: tuple[tuple[float, float, float], ...] = (
    (30.0, 50.0, 7.0),
    (40.0, 50.0, 9.2),
    *(
        (power, 50.0, round(_LOW[1] * math.exp(_RATE * (power - _LOW[0])), 2))
        for power in (45.0, 50.0, 52.0, 55.0, 57.0)
    ),
) + TARGETS
SEASON_PA = 650.0
# mph a point past the last anchor a stored rating can reach.
TAIL_SLOPE = 0.15

_ENV: dict[str, Any] = {}


def forced_table(offset: float) -> dict[str, Any]:
    """Overrides under which every hitter's Power adds ``offset`` mph."""
    return {
        "power_curve_model": 1.0,
        "bat_speed_power_table": {"0": float(offset), "100": float(offset)},
    }


def solve_offset(points: list[tuple[float, float]], target: float) -> float:
    """The offset at which the rate reaches ``target``: ``points`` are
    (offset, rate) pairs; log-linear between the two that bracket the
    target, or along the nearest pair when none does."""
    points = sorted(points)
    if len(points) < 2 or any(rate <= 0.0 for _offset, rate in points):
        raise ValueError("need two or more offsets with a positive rate")
    pair = (points[0], points[1])
    for low, high in zip(points, points[1:]):
        pair = (low, high)
        if target <= high[1]:
            break
    (x0, y0), (x1, y1) = pair
    if y0 == y1:
        raise ValueError("the rate does not move with the offset")
    share = (math.log(target) - math.log(y0)) / (math.log(y1) - math.log(y0))
    return x0 + (x1 - x0) * share


def table_from(solved: dict[float, float]) -> dict[str, float]:
    """The profile entries for the solved anchors and the ones set from
    them (module docstring), to two decimals."""
    table = {f"{power:g}": round(offset, 2) for power, offset in sorted(solved.items())}
    if 63.33 in solved and 66.33 in solved:
        table["65"] = round((solved[63.33] + solved[66.33]) / 2.0, 2)
    if 66.33 in solved:
        table["80"] = round(solved[66.33] + (80.0 - 66.33) * TAIL_SLOPE, 2)
    return dict(sorted(table.items(), key=lambda item: float(item[0])))


def current_offset(tuning: Any, power: float) -> float:
    from physics_sim.physics import _power_bat_speed

    return _power_bat_speed(power, tuning)


def _init(base_dir: str, overrides: dict[str, Any]) -> None:
    from physics_sim.models import PitcherRatings
    from physics_sim.park import load_park
    from services.league_rating_centers import active_pitcher_workloads

    base = Path(base_dir)
    players = base / "players.csv"
    _ENV["overrides"] = overrides
    _ENV["park"] = load_park(None)
    _ENV["staff"] = [
        (PitcherRatings.from_row(row), weight)
        for row, weight in active_pitcher_workloads(base, players_path=players)
    ]


def _cell(job: tuple[float, float, float, int, int]) -> tuple[tuple, dict[str, int]]:
    from physics_sim.config import load_tuning
    from scripts.kpi_extras import _simulate_staff_cell

    power, contact, offset, n, seed = job
    tuning = load_tuning({**_ENV["overrides"], **forced_table(offset)})
    state = random.getstate()
    try:
        counts = _simulate_staff_cell(
            power=power, contact=contact, n=n, seed=seed, tuning=tuning,
            staff=_ENV["staff"], park=_ENV["park"],
        )
    finally:
        random.setstate(state)
    return (power, contact, offset), dict(counts)


def fit(
    *,
    base_dir: Path,
    overrides: dict[str, Any],
    targets: tuple[tuple[float, float, float], ...] = TARGETS,
    pa: int = 200000,
    seeds: tuple[int, ...] = (101, 202, 303),
    step: float = 1.5,
    procs: int = 4,
) -> dict[str, Any]:
    """Solve every target's anchor. ``overrides`` are the run's tuning
    overrides WITH the fixture's rating centres (the harness's
    ``with_rating_centers``). Returns the rows and the table entries."""
    from physics_sim.config import load_tuning

    tuning = load_tuning(overrides)
    jobs = []
    for power, contact, _target in targets:
        centre = current_offset(tuning, power)
        for offset in (centre - step, centre, centre + step):
            for seed in seeds:
                jobs.append((power, contact, round(offset, 4), pa, seed))
    pooled: dict[tuple, Counter] = {}
    if procs <= 1:
        _init(str(base_dir), overrides)
        results = [_cell(job) for job in jobs]
    else:
        setup = (str(base_dir), overrides)
        with Pool(procs, initializer=_init, initargs=setup) as pool:
            results = pool.map(_cell, jobs)
    for key, counts in results:
        pooled.setdefault(key, Counter()).update(counts)
    rows = []
    # Power -> the solve of every target at that Power (one anchor each).
    solves: dict[float, list[float]] = {}
    for power, contact, target in targets:
        points = sorted(
            (offset, SEASON_PA * counts["hr"] / counts["pa"])
            for (p, c, offset), counts in pooled.items()
            if (p, c) == (power, contact)
        )
        now = current_offset(tuning, power)
        offset = solve_offset(points, target)
        solves.setdefault(power, []).append(offset)
        rows.append({
            "power": power, "contact": contact, "target_hr650": target,
            "table_offset": now,
            "table_hr650": dict(points).get(round(now, 4)),
            "solved_offset": offset,
            "response": [{"offset": o, "hr650": r} for o, r in points],
        })
    solved = {power: sum(found) / len(found) for power, found in solves.items()}
    return {"anchors": rows, "table": table_from(solved)}


def main(argv: list[str] | None = None) -> int:
    from scripts.physics_sim_season_kpis import (
        resolve_run_overrides,
        with_rating_centers,
    )

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-dir", type=Path, default=Path("data/calibration"))
    parser.add_argument("--engine", type=int, default=6)
    parser.add_argument("--tuning-overrides", type=Path, default=None)
    parser.add_argument("--pa", type=int, default=200000, help="PA per cell and seed")
    parser.add_argument("--seeds", default="101,202,303")
    parser.add_argument("--step", type=float, default=1.5, help="mph either side")
    parser.add_argument("--procs", type=int, default=4)
    parser.add_argument(
        "--whole", action="store_true",
        help="Re-fit every anchor (WHOLE_TARGETS), not only the top.",
    )
    args = parser.parse_args(argv)
    base = args.base_dir if args.base_dir.is_absolute() else BASE_DIR / args.base_dir
    run = resolve_run_overrides(
        engine=args.engine, overrides_path=args.tuning_overrides
    )
    overrides = with_rating_centers(run, base / "players.csv", base)
    result = fit(
        base_dir=base, overrides=overrides, pa=args.pa,
        targets=WHOLE_TARGETS if args.whole else TARGETS,
        seeds=tuple(int(seed) for seed in args.seeds.split(",")),
        step=args.step, procs=args.procs,
    )
    for row in result["anchors"]:
        at_table = row["table_hr650"]
        print(
            f"Power {row['power']:g}, Contact {row['contact']:g}: target "
            f"{row['target_hr650']:g} HR per 650 PA; the table's "
            f"{row['table_offset']:.2f} mph gives {at_table:.1f}; "
            f"solved {row['solved_offset']:.2f} mph"
        )
    print("bat_speed_power_table entries:")
    print(json.dumps(result["table"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
