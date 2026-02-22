#!/usr/bin/env python3
"""Benchmark workflow runtimes for backlog item #15.

Measures:
- New league creation (`playbalance.league_creator.create_league`)
- Auto reassign all rosters (`services.roster_auto_assign.auto_assign_all_teams`)
"""

from __future__ import annotations

import argparse
import csv
import cProfile
import datetime as dt
import gc
import json
import os
import pstats
import shutil
import statistics
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playbalance.league_creator import create_league, MAX_LEAGUE_TEAMS
from services.roster_auto_assign import auto_assign_all_teams
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster


@dataclass
class RunResult:
    workflow: str
    scenario: str
    run_index: int
    seconds: float
    teams: int
    warmup: bool


def _scenario_structure(divisions: int, teams_per_division: int) -> Dict[str, List[tuple[str, str]]]:
    structure: Dict[str, List[tuple[str, str]]] = {}
    for d in range(divisions):
        entries: List[tuple[str, str]] = []
        for t in range(teams_per_division):
            entries.append((f"City{d:02d}{t:02d}", f"Team{d:02d}{t:02d}"))
        structure[f"Division-{d + 1}"] = entries
    return structure


def _teams_count(structure: Dict[str, List[tuple[str, str]]]) -> int:
    return sum(len(v) for v in structure.values())


@contextmanager
def _pushd(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _clear_runtime_caches() -> None:
    try:
        load_players_from_csv.cache_clear()
    except Exception:
        pass
    try:
        load_roster.cache_clear()
    except Exception:
        pass


def _profile_text(path: Path, target: Callable[[], None]) -> None:
    profile = cProfile.Profile()
    profile.enable()
    target()
    profile.disable()

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        stats = pstats.Stats(profile, stream=handle)
        stats.sort_stats("cumulative")
        stats.print_stats(35)


def _time_call(target: Callable[[], None]) -> float:
    started = time.perf_counter()
    target()
    return time.perf_counter() - started


def _run_create_league_benchmark(
    *,
    work_root: Path,
    scenario: str,
    structure: Dict[str, List[tuple[str, str]]],
    runs: int,
    warmups: int,
    profile: bool,
    profile_dir: Path,
) -> List[RunResult]:
    results: List[RunResult] = []
    team_count = _teams_count(structure)
    total = runs + warmups
    for idx in range(total):
        run_dir = work_root / f"create_{scenario}_{idx:02d}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        data_dir = run_dir / "data"
        run_dir.mkdir(parents=True, exist_ok=True)
        league_name = f"Benchmark {scenario} {idx}"

        gc.collect()
        _clear_runtime_caches()

        def _target() -> None:
            create_league(str(data_dir), structure, league_name)

        if profile and idx == warmups:
            _profile_text(profile_dir / f"create_{scenario}.txt", _target)

        elapsed = _time_call(_target)
        results.append(
            RunResult(
                workflow="create_league",
                scenario=scenario,
                run_index=idx,
                seconds=elapsed,
                teams=team_count,
                warmup=idx < warmups,
            )
        )
    return results


def _run_auto_assign_benchmark(
    *,
    work_root: Path,
    scenario: str,
    structure: Dict[str, List[tuple[str, str]]],
    runs: int,
    warmups: int,
    profile: bool,
    profile_dir: Path,
) -> List[RunResult]:
    results: List[RunResult] = []
    team_count = _teams_count(structure)
    total = runs + warmups
    for idx in range(total):
        run_dir = work_root / f"assign_{scenario}_{idx:02d}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        data_dir = run_dir / "data"
        run_dir.mkdir(parents=True, exist_ok=True)
        create_league(str(data_dir), structure, f"AutoAssign {scenario} {idx}")

        gc.collect()
        _clear_runtime_caches()

        def _target() -> None:
            with _pushd(run_dir):
                auto_assign_all_teams(
                    players_file="data/players.csv",
                    roster_dir="data/rosters",
                    teams_file="data/teams.csv",
                )

        if profile and idx == warmups:
            _profile_text(profile_dir / f"auto_assign_{scenario}.txt", _target)

        elapsed = _time_call(_target)
        results.append(
            RunResult(
                workflow="auto_assign_all_teams",
                scenario=scenario,
                run_index=idx,
                seconds=elapsed,
                teams=team_count,
                warmup=idx < warmups,
            )
        )
    return results


def _summarize(results: Iterable[RunResult]) -> list[dict[str, object]]:
    by_group: dict[tuple[str, str], list[RunResult]] = {}
    for row in results:
        if row.warmup:
            continue
        key = (row.workflow, row.scenario)
        by_group.setdefault(key, []).append(row)

    summary: list[dict[str, object]] = []
    for (workflow, scenario), rows in sorted(by_group.items()):
        values = [item.seconds for item in rows]
        if not values:
            continue
        entry: dict[str, object] = {
            "workflow": workflow,
            "scenario": scenario,
            "runs": len(values),
            "teams": rows[0].teams,
            "mean_seconds": round(statistics.mean(values), 4),
            "median_seconds": round(statistics.median(values), 4),
            "min_seconds": round(min(values), 4),
            "max_seconds": round(max(values), 4),
        }
        if len(values) >= 2:
            entry["stdev_seconds"] = round(statistics.pstdev(values), 4)
        summary.append(entry)
    return summary


def _write_csv(path: Path, results: Iterable[RunResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(row) for row in results]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "workflow",
                "scenario",
                "run_index",
                "seconds",
                "teams",
                "warmup",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="Measured runs per scenario/workflow.")
    parser.add_argument("--warmups", type=int, default=1, help="Warmup runs per scenario/workflow.")
    parser.add_argument("--typical-divisions", type=int, default=2, help="Typical scenario divisions.")
    parser.add_argument("--typical-teams", type=int, default=8, help="Typical scenario teams per division.")
    parser.add_argument(
        "--skip-max",
        action="store_true",
        help=f"Skip max-size scenario ({MAX_LEAGUE_TEAMS} teams).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "performance",
        help="Directory for benchmark reports.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Optional workspace directory for temporary benchmark data.",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Capture one cProfile text report per workflow/scenario.",
    )
    args = parser.parse_args(argv)

    if args.runs <= 0:
        raise ValueError("--runs must be > 0")
    if args.warmups < 0:
        raise ValueError("--warmups must be >= 0")

    typical = _scenario_structure(args.typical_divisions, args.typical_teams)
    if _teams_count(typical) > MAX_LEAGUE_TEAMS:
        raise ValueError(
            f"Typical scenario has {_teams_count(typical)} teams, exceeding max {MAX_LEAGUE_TEAMS}."
        )
    scenarios: dict[str, Dict[str, List[tuple[str, str]]]] = {"typical": typical}
    if not args.skip_max:
        scenarios["max_40"] = _scenario_structure(4, 10)

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / f"workflow_benchmark_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root = args.work_dir if args.work_dir is not None else out_dir / "workspace"
    work_root.mkdir(parents=True, exist_ok=True)
    profile_dir = out_dir / "profiles"

    all_results: list[RunResult] = []
    for scenario, structure in scenarios.items():
        all_results.extend(
            _run_create_league_benchmark(
                work_root=work_root,
                scenario=scenario,
                structure=structure,
                runs=args.runs,
                warmups=args.warmups,
                profile=args.profile,
                profile_dir=profile_dir,
            )
        )
        all_results.extend(
            _run_auto_assign_benchmark(
                work_root=work_root,
                scenario=scenario,
                structure=structure,
                runs=args.runs,
                warmups=args.warmups,
                profile=args.profile,
                profile_dir=profile_dir,
            )
        )

    summary = _summarize(all_results)
    csv_path = out_dir / "workflow_timings.csv"
    json_path = out_dir / "workflow_summary.json"
    _write_csv(csv_path, all_results)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.now().isoformat(),
                "config": {
                    "runs": args.runs,
                    "warmups": args.warmups,
                    "typical_divisions": args.typical_divisions,
                    "typical_teams": args.typical_teams,
                    "skip_max": bool(args.skip_max),
                    "work_dir": str(work_root),
                    "profile": bool(args.profile),
                },
                "summary": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote timing CSV: {csv_path}")
    print(f"Wrote summary JSON: {json_path}")
    print("\nSummary:")
    for row in summary:
        print(
            f"- {row['workflow']} [{row['scenario']}] "
            f"runs={row['runs']} teams={row['teams']} "
            f"mean={row['mean_seconds']:.3f}s median={row['median_seconds']:.3f}s "
            f"min={row['min_seconds']:.3f}s max={row['max_seconds']:.3f}s"
        )
    if args.profile:
        print(f"Profile reports: {profile_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
