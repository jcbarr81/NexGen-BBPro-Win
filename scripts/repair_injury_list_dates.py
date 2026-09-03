"""Repair injured-list dates that were stamped with the wall clock.

Before the injured list moved onto the league's clock, ``place_on_injury_list``
stamped ``date.today()`` over the sim dates the simulator had just written. Any
player placed on a list under the old code therefore carries a real-world
``injury_start_date`` / ``injury_eligible_date`` — a date that has nothing to do
with the league's season — while ``return_date`` kept the correct sim date.

This rebuilds those rows:

    injury_eligible_date <- return_date            (the sim-date eligibility)
    injury_start_date    <- return_date - stint    (back-computed)

and leaves everything else alone. A row whose dates already sit inside the
league's season is left untouched, so the script is idempotent and safe to
re-run.

DRY RUN BY DEFAULT. Nothing is written without --apply.

    python scripts/repair_injury_list_dates.py                    # inspect
    python scripts/repair_injury_list_dates.py --apply            # write
    python scripts/repair_injury_list_dates.py --players FILE     # explicit file
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# The tier minimums, duplicated deliberately: this script must be runnable
# against a data file without importing the app (and its league context).
IL_MINIMUM_DAYS = {"il7": 7, "il10": 10, "il15": 15, "il60": 60, "dl15": 15, "ir": 60}


def _parse(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _season_bounds(schedule: Path) -> tuple[Optional[date], Optional[date]]:
    if not schedule.exists():
        return None, None
    dates: List[date] = []
    try:
        with schedule.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                parsed = _parse(row.get("date"))
                if parsed:
                    dates.append(parsed)
    except OSError:
        return None, None
    if not dates:
        return None, None
    return min(dates), max(dates)


def _stint_days(row: Dict[str, str]) -> int:
    tier = str(row.get("injury_list") or "").strip().lower()
    try:
        stored = int(float(row.get("injury_minimum_days") or 0))
    except (TypeError, ValueError):
        stored = 0
    return max(stored, IL_MINIMUM_DAYS.get(tier, 0)) or 0


def inspect(players_path: Path, schedule_path: Path) -> Dict[str, Any]:
    """Return the rows that need repair, without touching anything."""

    season_start, season_end = _season_bounds(schedule_path)
    with players_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    repairs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for row in rows:
        tier = str(row.get("injury_list") or "").strip().lower()
        if not tier or tier in {"none", "null"}:
            continue
        start = _parse(row.get("injury_start_date"))
        eligible = _parse(row.get("injury_eligible_date"))
        return_date = _parse(row.get("return_date"))
        name = f"{row.get('first_name','')} {row.get('last_name','')}".strip()

        # The fingerprint of the bug is the two dates DISAGREEING: the old
        # placement overwrote injury_eligible_date with a wall-clock value
        # while return_date, written afterwards, kept the sim date. A range
        # check can't tell them apart — a real-world date in 2026 falls inside
        # a 2026 schedule just as happily as a league date does.
        if return_date is None:
            skipped.append(
                {
                    "player": name,
                    "reason": "no return_date to rebuild from — needs a manual call",
                }
            )
            continue
        if eligible == return_date:
            skipped.append({"player": name, "reason": "dates already agree"})
            continue

        days = _stint_days(row)
        new_start = return_date - timedelta(days=days) if days else start
        repairs.append(
            {
                "player_id": row.get("player_id"),
                "player": name,
                "tier": tier,
                "stint_days": days,
                "old_start": row.get("injury_start_date"),
                "old_eligible": row.get("injury_eligible_date"),
                "new_start": new_start.isoformat() if new_start else "",
                "new_eligible": return_date.isoformat(),
            }
        )
    return {
        "rows": rows,
        "fieldnames": fieldnames,
        "repairs": repairs,
        "skipped": skipped,
        "season_start": season_start.isoformat() if season_start else None,
        "season_end": season_end.isoformat() if season_end else None,
    }


def apply(players_path: Path, report: Dict[str, Any]) -> Path:
    """Write the repairs back, after taking a backup beside the file."""

    by_id = {r["player_id"]: r for r in report["repairs"]}
    if not by_id:
        raise SystemExit("Nothing to apply.")

    backup = players_path.with_suffix(players_path.suffix + ".bak")
    shutil.copy2(players_path, backup)

    for row in report["rows"]:
        fix = by_id.get(row.get("player_id"))
        if not fix:
            continue
        row["injury_start_date"] = fix["new_start"]
        row["injury_eligible_date"] = fix["new_eligible"]
        row["return_date"] = fix["new_eligible"]
        if fix["stint_days"]:
            row["injury_minimum_days"] = str(fix["stint_days"])

    with players_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=report["fieldnames"])
        writer.writeheader()
        writer.writerows(report["rows"])
    return backup


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=Path, help="players.csv to repair")
    parser.add_argument("--schedule", type=Path, help="schedule.csv for season bounds")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args(argv)

    players_path = args.players
    schedule_path = args.schedule
    if players_path is None:
        from utils.path_utils import get_data_dir

        players_path = Path(get_data_dir()) / "players.csv"
    if schedule_path is None:
        schedule_path = players_path.parent / "schedule.csv"

    if not players_path.exists():
        print(f"No players file at {players_path}")
        return 2

    report = inspect(players_path, schedule_path)
    season = f"{report['season_start']} .. {report['season_end']}"
    print(f"players : {players_path}")
    print(f"season  : {season}")
    print(f"repairs : {len(report['repairs'])}   skipped: {len(report['skipped'])}")
    print()

    if report["repairs"]:
        print(f"{'PLAYER':22} {'TIER':6} {'DAYS':>4}  {'START (old -> new)':26} {'ELIGIBLE (old -> new)':30}")
        print("-" * 100)
        for r in report["repairs"]:
            print(
                f"{r['player'][:22]:22} {r['tier']:6} {r['stint_days']:>4}  "
                f"{r['old_start']} -> {r['new_start']:12} "
                f"{r['old_eligible']} -> {r['new_eligible']}"
            )
        print()
    for s in report["skipped"]:
        print(f"  skipped {s['player']}: {s['reason']}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0

    backup = apply(players_path, report)
    print(f"\nWrote {len(report['repairs'])} repair(s). Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
