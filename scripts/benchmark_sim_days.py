#!/usr/bin/env python3
"""Sprint-1 sim benchmark + parity harness (deep_review_plan.md).

Times an N-day season simulation against a throwaway copy of a league and
emits parity digests so performance changes can prove they didn't alter
behavior:

    python scripts/benchmark_sim_days.py --source data/leagues/cbl/data \
        --days 10 --seed 123

- The league copy is rebuilt fresh every run (file growth from a previous
  run must not skew timings).
- Digests cover the per-game score sequence, season_stats.json, and
  pitcher_recovery.json (canonicalized). Same code + same seed must produce
  identical digests before AND after a pure-performance change.
- CAVEAT: digests are only comparable SAME-DAY. Parts of the pipeline key
  off the wall-clock date (e.g. the recovery tracker's 14-day trim window),
  so when the calendar rolls over, re-baseline by running the pre-change
  code first that day.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

# Cross-process determinism: set iteration order depends on string hashing,
# which Python randomizes per process. Pin it and re-run in a child process
# (os.execv doesn't block on Windows) so identical seeds produce identical
# digests across separate runs.
if os.environ.get("PYTHONHASHSEED") != "0":
    import subprocess

    env = dict(os.environ, PYTHONHASHSEED="0")
    raise SystemExit(
        subprocess.run([sys.executable] + sys.argv, env=env).returncode
    )


def _canonical_json_digest(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unreadable"
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _build_schedule(team_ids: list[str], days: int, start: str) -> list[dict[str, str]]:
    """Round-robin-ish deterministic schedule: every team plays once per day."""
    from datetime import date, timedelta

    year, month, day = (int(x) for x in start.split("-"))
    d0 = date(year, month, day)
    schedule: list[dict[str, str]] = []
    n = len(team_ids)
    for day_idx in range(days):
        date_token = (d0 + timedelta(days=day_idx)).isoformat()
        # Rotate pairings by day so matchups vary deterministically.
        rotated = team_ids[day_idx % n :] + team_ids[: day_idx % n]
        for i in range(0, n - 1, 2):
            schedule.append(
                {"date": date_token, "home": rotated[i], "away": rotated[i + 1]}
            )
    return schedule


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True,
                        help="League data dir to copy (e.g. data/leagues/cbl/data)")
    parser.add_argument("--sandbox", type=Path, default=None,
                        help="Sandbox dir (default: <temp>/nexgen-sim-bench)")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--start-date", default="2026-05-01")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    sandbox = args.sandbox or Path(os.environ.get("TEMP", "/tmp")) / "nexgen-sim-bench"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    ignore = shutil.ignore_patterns("boxscores", "season_history", "*.bak", "logs")
    shutil.copytree(args.source, sandbox, ignore=ignore)

    # Point the app at the sandbox BEFORE importing anything that resolves paths.
    os.environ["NEXGEN_DATA_ROOT"] = str(sandbox)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
    # Boxscore HTML generation is measured separately; keep the default ON so
    # the baseline reflects real season-sim cost.

    from utils.team_loader import load_teams
    from playbalance.season_simulator import SeasonSimulator

    teams = [t.team_id for t in load_teams(str(sandbox / "teams.csv"))]
    teams.sort()
    schedule = _build_schedule(teams, args.days, args.start_date)

    sim = SeasonSimulator(schedule)
    random.seed(args.seed)

    day_times: list[float] = []
    t0 = time.perf_counter()
    for _ in range(args.days):
        d0 = time.perf_counter()
        sim.simulate_next_day()
        day_times.append(time.perf_counter() - d0)
    total = time.perf_counter() - t0

    scores = "|".join(g.get("result", "") for g in schedule)
    digests = {
        "scores": hashlib.sha256(scores.encode("utf-8")).hexdigest()[:16],
        "season_stats": _canonical_json_digest(sandbox / "season_stats.json"),
        "pitcher_recovery": _canonical_json_digest(sandbox / "pitcher_recovery.json"),
    }

    result = {
        "days": args.days,
        "games": len(schedule),
        "seed": args.seed,
        "total_seconds": round(total, 2),
        "seconds_per_day": round(total / args.days, 2),
        "seconds_per_game": round(total / len(schedule), 3),
        "first_day_seconds": round(day_times[0], 2),
        "last_day_seconds": round(day_times[-1], 2),
        "digests": digests,
    }
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(f"days={result['days']} games={result['games']} seed={result['seed']}")
        print(f"total={result['total_seconds']}s  per-day={result['seconds_per_day']}s  "
              f"per-game={result['seconds_per_game']}s")
        print(f"day1={result['first_day_seconds']}s  day{args.days}={result['last_day_seconds']}s")
        print(f"digests: {digests}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
