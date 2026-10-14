"""Put a league that moved to rating scale 2 (8.0.0) back on scale 1.

An operator tool; read ``docs/rating_scale_switch_runbook.md`` first. Run it
on a COPY of the league's data directory with every serving instance
stopped and the scheduler paused, then upload the result (the working copy
refuses to push a scale 1 players.csv over a scale 2 one, and a lower
engine generation over a higher one, by design).

    python scripts/rating_scale_rollback.py --league-dir <.../leagues/<id>/data>
        [--mode backup|inverse] [--season 2027] [--generation 5] [--dry-run]

--mode backup (default): restore ``players.scale1.<season>.csv`` (and the
    open draft pools' backups). Everything that happened to players since
    the move is lost; a re-spread is undone.
--mode inverse: un-stretch today's players.csv in place (exact inverse map;
    a value developed since is rounded to the nearest engine point). Keeps
    every change since the move; does NOT undo a re-spread.
--no-conversion-record: a league CREATED on scale 2 has no move and no
    backup; with --mode inverse --season X this un-stretches it anyway.
--generation N: also rewrite the season's recorded engine generation
    (rating_centers.json entry and the season_progress.json witness). Only
    needed when the league must also leave generation 6 (a binary rollback
    below 8.0.0, which does not know generation 6). Scale 1 plays correctly
    on generation 6, so a scale rollback alone does not need it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from services import rating_scale_migration as migration  # noqa: E402
from utils.rating_scale import players_file_rating_scales, describe_rating_scales  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--league-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("backup", "inverse"), default="backup")
    parser.add_argument("--season", default=None)
    parser.add_argument("--generation", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-conversion-record", action="store_true",
        help="allow --mode inverse --season X on a league with no move recorded "
        "for X (a league created on rating scale 2)",
    )
    args = parser.parse_args(argv)

    base = args.league_dir
    players = base / "players.csv"
    if not players.exists():
        parser.error(f"{players} does not exist")
    log = migration.read_scale_log(base)
    print("players.csv now:", describe_rating_scales(players_file_rating_scales(players)))
    print("rating_scale.json events:", [e.get("event") for e in log.get("events", [])])
    if args.dry_run:
        backups = sorted(p.name for p in base.glob("players.scale1.*.csv"))
        print("backups present:", backups or "none")
        return 0
    event = migration.rollback_league(
        base, mode=args.mode, season=args.season,
        allow_unrecorded=args.no_conversion_record,
    )
    print("rolled back:", json.dumps(event))
    if args.generation is not None:
        season = event["season"]
        print("generation:", json.dumps(
            migration.set_recorded_generation(base, season, args.generation)
        ))
    print("players.csv after:", describe_rating_scales(players_file_rating_scales(players)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
