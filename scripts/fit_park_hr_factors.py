"""Fit each real park's home runs by batter side (Release 6b; owner
decisions 18 and 20).

Generation 7 plays every real park at its own shape (the five-point fence
and walls of ``data/parks/ParkFences.csv``, its altitude through the carry
table). Its home runs are then fitted, BY BATTER SIDE, to Baseball Savant's
park factors (``data/parks/ParkHRTargets.csv``): each park's left-field
side (LF line and left-centre) and right-field side are moved out or in
(``bb6_park_fence_shift_left_ft`` / ``_right_ft``; centre field by their
mean). Only home runs are fitted; the singles, doubles and triples each
park's shape gives are reported against Savant's for the owner.

Procedure (Monte Carlo, neutral talent):

1. Play one season of the fixture on the given engine and keep every ball
   in play (exit velocity, launch angle, physical spray angle, batting
   side). Talent does not depend on the park, so every ball can be replayed
   in every park.
2. A park's home-run rate for a side is the share of that side's balls
   that leave it; its factor is that rate over the mean rate of the 30 home
   parks of 2026 (``physics_sim.ballflight.CURRENT_PARK_IDS``), times 100,
   as Savant's are (100 = the league's average for that side).
3. Solve each park's two shifts for its two targets (a left-handed
   batter's home runs go mostly to the right-field side, a right-handed
   batter's to the left), then re-read the league mean and repeat until no
   shift moves by more than 0.05 ft.

    python scripts/fit_park_hr_factors.py --engine 7 --base-dir data/calibration \
        --players data/calibration/players.csv --seed 1 \
        [--tuning-overrides X.json] [--geometry-only] [--hit-types N] \
        [--write-profile scripts/kpi_profiles/r7_parks.json] [--report out.json]

``--geometry-only`` reports the factors at every shift 0 and fits nothing.
``--hit-types N`` also replays N balls through the fielding play model in
every park for its 1B / 2B / 3B factors (neutral fielders; slow).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

TARGETS_FILE = REPO / "data" / "parks" / "ParkHRTargets.csv"
SHIFT_LIMIT_FT = 60.0


def read_targets(path: Path = TARGETS_FILE) -> dict[str, dict[str, Any]]:
    """Park id -> its row of the targets file (numbers as floats)."""
    out: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        lines = (line for line in fh if not line.lstrip().startswith("#"))
        for row in csv.DictReader(lines):
            parsed: dict[str, Any] = {}
            for key, value in row.items():
                value = (value or "").strip()
                try:
                    parsed[key] = float(value)
                except ValueError:
                    parsed[key] = value or None
            out[str(row["park_id"]).strip().upper()] = parsed
    return out


def collect_balls(args: argparse.Namespace) -> np.ndarray:
    """Play one season with the KPI harness and keep its balls in play:
    columns exit velocity, launch angle, physical spray, left-handed side."""
    from scripts import physics_sim_season_kpis as harness

    hands: dict[str, tuple[str, str]] = {}
    with Path(args.players).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            hands[row["player_id"]] = (
                (row.get("bats") or "R").upper(), (row.get("throws") or "R").upper()
            )
    rows: list[tuple[float, float, float, float]] = []
    original = harness.simulate_matchup_from_files

    def keep(**kwargs):
        result = original(**kwargs)
        for entry in result.pitch_log:
            if entry.get("outcome") != "in_play" or entry.get("exit_velo") is None:
                continue
            if entry.get("foul_out"):
                continue
            bats = hands.get(str(entry.get("batter_id")), ("R", "R"))[0]
            throws = hands.get(str(entry.get("pitcher_id")), ("R", "R"))[1]
            if bats == "S":
                bats = "L" if throws == "R" else "R"
            rows.append((
                float(entry["exit_velo"]), float(entry.get("launch_angle") or 0.0),
                float(entry.get("spray_angle") or 0.0), 1.0 if bats == "L" else 0.0,
            ))
        return result

    overrides = harness.resolve_run_overrides(
        engine=args.engine, overrides_path=args.tuning_overrides
    )
    harness.simulate_matchup_from_files = keep
    os.environ.setdefault("PYTHONHASHSEED", "0")
    try:
        harness.run_sim(
            args.games, args.seed, Path(args.players), overrides,
            Path(args.base_dir),
        )
    finally:
        harness.simulate_matchup_from_files = original
    return np.array(rows, dtype=float)


class ParkModel:
    """Every ball's carry and descent in each park's air, and the fence."""

    def __init__(self, balls: np.ndarray, tuning: Any, park_ids: list[str]):
        from physics_sim import ballflight
        from utils.park_utils import park_fences, park_fence_for_name, _load_parks_master

        self.bf = ballflight
        self.balls = balls
        self.left = balls[:, 3] > 0.5
        alt_by_id, _ = _load_parks_master()
        fences = park_fences()
        self.parks: dict[str, Any] = {}
        evs, las = balls[:, 0].tolist(), balls[:, 1].tolist()
        cache: dict[float, tuple[np.ndarray, np.ndarray]] = {}
        for pid in park_ids:
            listed = fences.get(pid)
            if listed is None:
                found = None
                for name in _park_names_for(pid):
                    found = park_fence_for_name(name)
                    if found:
                        break
                if not found:
                    continue
                distances, heights = found[1], found[2]
            else:
                distances, heights = listed[0], listed[1]
            altitude = float(alt_by_id.get(pid, 0.0))
            key = round(altitude, 1)
            if key not in cache:
                dist, desc = [], []
                for ev, la in zip(evs, las):
                    d, _h, a = ballflight.carry(ev, la, altitude, tuning)
                    dist.append(d)
                    desc.append(a)
                cache[key] = (np.array(dist), np.array(desc))
            self.parks[pid] = {
                "distances": np.array(distances, dtype=float),
                "heights": np.array(heights, dtype=float),
                "altitude": altitude,
                "carry": cache[key],
            }

    def hr_mask(self, pid: str, left: float, right: float) -> np.ndarray:
        park = self.parks[pid]
        dist, desc = park["carry"]
        moves = np.array([left, left, (left + right) / 2.0, right, right])
        d = park["distances"] + moves
        h = park["heights"]
        phi = np.clip(self.balls[:, 2], -45.0, 45.0)
        pos = (phi + 45.0) / 22.5
        idx = np.minimum(3, pos.astype(int))
        frac = pos - idx
        wall = d[idx] * (1 - frac) + d[idx + 1] * frac
        height = h[idx] * (1 - frac) + h[idx + 1] * frac
        slope = np.maximum(0.3, np.tan(np.radians(np.maximum(15.0, desc))))
        return dist > wall + np.maximum(0.0, height) / slope

    def rates(self, pid: str, left: float, right: float) -> tuple[float, float]:
        hr = self.hr_mask(pid, left, right)
        return float(hr[self.left].mean()), float(hr[~self.left].mean())


def _park_names_for(pid: str) -> list[str]:
    from utils.park_utils import _load_latest_parks

    return [info.name for info in _load_latest_parks().values() if info.park_id == pid]


def fit(model: ParkModel, targets: dict[str, dict[str, Any]], current: list[str],
        fit_ids: list[str]) -> dict[str, Any]:
    shifts = {pid: [0.0, 0.0] for pid in fit_ids}

    def league() -> tuple[float, float]:
        rows = [model.rates(pid, *shifts.get(pid, (0.0, 0.0))) for pid in current]
        return (
            sum(r[0] for r in rows) / len(rows), sum(r[1] for r in rows) / len(rows)
        )

    def solve(pid: str, side: int, goal_rate: float) -> float:
        lo, hi = -SHIFT_LIMIT_FT, SHIFT_LIMIT_FT
        for _ in range(40):
            mid = (lo + hi) / 2.0
            trial = list(shifts[pid])
            trial[1 - side] = mid  # side 0 = LHB -> right side; 1 = RHB -> left
            rate = model.rates(pid, trial[0], trial[1])[side]
            if rate > goal_rate:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2.0, 2)

    for _outer in range(20):
        base = league()
        moved = 0.0
        for pid in fit_ids:
            target = targets.get(pid)
            if not target or pid not in model.parks:
                continue
            for _inner in range(3):
                for side, key in ((0, "hr_lhb"), (1, "hr_rhb")):
                    goal = target.get(key)
                    if goal is None:
                        continue
                    new = solve(pid, side, base[side] * float(goal) / 100.0)
                    moved = max(moved, abs(new - shifts[pid][1 - side]))
                    shifts[pid][1 - side] = new
        if moved < 0.05:
            break
    return {pid: {"left": s[0], "right": s[1]} for pid, s in shifts.items()}


def factors(model: ParkModel, shifts: dict[str, dict[str, float]], current: list[str]):
    def at(pid):
        s = shifts.get(pid, {"left": 0.0, "right": 0.0})
        return model.rates(pid, s["left"], s["right"])

    base = [at(pid) for pid in current if pid in model.parks]
    league = (sum(r[0] for r in base) / len(base), sum(r[1] for r in base) / len(base))
    league_all = sum(
        (r[0] * model.left.mean() + r[1] * (1 - model.left.mean())) for r in base
    ) / len(base)
    out = {}
    for pid in model.parks:
        lhb, rhb = at(pid)
        both = lhb * model.left.mean() + rhb * (1 - model.left.mean())
        out[pid] = {
            "hr": round(100.0 * both / league_all, 1),
            "hr_lhb": round(100.0 * lhb / league[0], 1),
            "hr_rhb": round(100.0 * rhb / league[1], 1),
        }
    return out


def hit_type_factors(balls: np.ndarray, tuning: Any, park_ids: list[str],
                     shifts: dict[str, dict[str, float]], count: int,
                     current: list[str]) -> dict[str, dict[str, float]]:
    """Singles, doubles and triples per ball in play in each park (neutral
    fielders, the play model's chance of a hit times its hit type), over
    the mean of the current parks, times 100."""
    from physics_sim import ballflight
    from physics_sim.config import load_tuning
    from physics_sim.park import Park
    from playbalance.field_geometry import Stadium
    from utils.park_utils import _load_latest_parks, _load_parks_master

    sample = balls[:count]
    alt_by_id, _ = _load_parks_master()
    names = {}
    for info in _load_latest_parks().values():
        names.setdefault(info.park_id, info.name)
    rates = {}
    for pid in park_ids:
        if pid not in names:
            continue
        s = shifts.get(pid, {"left": 0.0, "right": 0.0})
        local = load_tuning({
            **tuning.values,
            "bb6_park_fence_shift_left_ft": {
                **tuning.values["bb6_park_fence_shift_left_ft"], pid: s["left"]},
            "bb6_park_fence_shift_right_ft": {
                **tuning.values["bb6_park_fence_shift_right_ft"], pid: s["right"]},
        })
        park = Park(name=names[pid], stadium=Stadium(),
                    altitude_ft=float(alt_by_id.get(pid, 0.0)))
        tally = defaultdict(float)
        for ev, la, spray, _left in sample.tolist():
            ball = ballflight.resolve_ball(ev, la, spray, park=park, tuning=local)
            if ball.is_hr:
                continue
            ballflight.play(ball, local)
            tally[ball.hit_type] += 1.0 - ball.out0
            tally["n"] += 1.0
        rates[pid] = {k: tally[k] / max(1.0, tally["n"]) for k in ("single", "double", "triple")}
    cur = [rates[p] for p in current if p in rates]
    league = {k: sum(r[k] for r in cur) / len(cur) for k in ("single", "double", "triple")}
    return {
        pid: {
            "b1": round(100.0 * r["single"] / league["single"], 1),
            "b2": round(100.0 * r["double"] / league["double"], 1),
            "b3": round(100.0 * r["triple"] / league["triple"], 1) if league["triple"] else None,
        }
        for pid, r in rates.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", type=int, default=7)
    parser.add_argument("--tuning-overrides", type=Path, default=None)
    parser.add_argument("--base-dir", default="data/calibration")
    parser.add_argument("--players", default="data/calibration/players.csv")
    parser.add_argument("--games", type=int, default=162)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--balls", type=Path, default=None,
                        help="Reuse a ball sample (.npy) instead of playing a season.")
    parser.add_argument("--save-balls", type=Path, default=None)
    parser.add_argument("--targets", type=Path, default=TARGETS_FILE)
    parser.add_argument("--geometry-only", action="store_true")
    parser.add_argument("--hit-types", type=int, default=0)
    parser.add_argument("--write-profile", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    os.environ.setdefault("NEXGEN_PARK_DATA_ROOT", str(REPO / "data"))

    from physics_sim import ballflight
    from physics_sim.config import load_tuning
    from scripts import physics_sim_season_kpis as harness

    if args.balls is not None:
        balls = np.load(args.balls)
    else:
        balls = collect_balls(args)
        if args.save_balls is not None:
            np.save(args.save_balls, balls)
    overrides = harness.resolve_run_overrides(
        engine=args.engine, overrides_path=args.tuning_overrides
    ) or {}
    # Fitted from shift 0: the shape alone.
    for key in ("bb6_park_fence_shift_left_ft", "bb6_park_fence_shift_right_ft"):
        overrides.pop(key, None)
    tuning = load_tuning(overrides)
    targets = read_targets(args.targets)
    current = list(ballflight.CURRENT_PARK_IDS)
    fit_ids = list(ballflight.FITTED_PARK_IDS)
    model = ParkModel(balls, tuning, fit_ids)
    zero = {pid: {"left": 0.0, "right": 0.0} for pid in fit_ids}
    geometric = factors(model, zero, current)
    report: dict[str, Any] = {
        "balls": int(len(balls)), "lhb_share": float(model.left.mean()),
        "geometric": geometric,
    }
    if not args.geometry_only:
        shifts = fit(model, targets, current, fit_ids)
        report["shifts"] = shifts
        report["fitted"] = factors(model, shifts, current)
    else:
        shifts = zero
    if args.hit_types:
        report["hit_types"] = hit_type_factors(
            balls, tuning, fit_ids, shifts, args.hit_types, current
        )
    print(f"{len(balls)} balls in play, LHB share {model.left.mean():.3f}")
    print(f"{'park':6} {'target L/R':>12} {'geometry L/R':>14} {'fitted L/R':>12} {'shift L/R ft':>14}")
    for pid in fit_ids:
        if pid not in model.parks:
            print(f"{pid:6} (no fence)")
            continue
        t = targets.get(pid, {})
        g = geometric[pid]
        line = (
            f"{pid:6} {t.get('hr_lhb') or 0:5.0f}/{t.get('hr_rhb') or 0:<5.0f}"
            f" {g['hr_lhb']:6.1f}/{g['hr_rhb']:<6.1f}"
        )
        if "fitted" in report:
            f = report["fitted"][pid]
            s = report["shifts"][pid]
            line += f" {f['hr_lhb']:5.1f}/{f['hr_rhb']:<5.1f} {s['left']:6.1f}/{s['right']:<6.1f}"
        print(line)
    if args.report is not None:
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    if args.write_profile is not None and "shifts" in report:
        profile = {
            "bb6_park_fence_shift_left_ft": {
                pid: s["left"] for pid, s in report["shifts"].items()
            },
            "bb6_park_fence_shift_right_ft": {
                pid: s["right"] for pid, s in report["shifts"].items()
            },
        }
        args.write_profile.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.write_profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
