"""Run one harness season and dump each player's counting stats to CSV.

Regenerates ``tests/fixtures/calibration_seed1_player_lines.csv``, the
per-player outcomes ``tests/test_overall_tracks_production.py`` correlates the
shared overall against (audit H8: displayed OVR must track OPS+ / FIP-).

    PYTHONHASHSEED=0 python scripts/dump_season_player_lines.py \
        --base-dir data/calibration --players data/calibration/players.csv \
        --games 162 --seed 1 --output tests/fixtures/calibration_seed1_player_lines.csv

It reuses ``physics_sim_season_kpis.run_sim`` unchanged, wrapping the per-game
call to collect the batting and pitching lines the harness already produces.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

import physics_sim_season_kpis as harness  # noqa: E402

BATTING_KEYS = ("pa", "ab", "h", "b2", "b3", "hr", "bb", "hbp", "sf", "so")
PITCHING_KEYS = ("outs", "bf", "er", "hr", "bb", "hbp", "so")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--players", type=Path, required=True)
    parser.add_argument("--games", type=int, default=162)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    batting: dict[str, Counter] = defaultdict(Counter)
    pitching: dict[str, Counter] = defaultdict(Counter)
    original = harness.simulate_matchup_from_files

    def _capture(*a, **kw):
        result = original(*a, **kw)
        meta = result.metadata or {}
        for side_lines in (meta.get("batting_lines") or {}).values():
            for line in side_lines:
                pid = str(line.get("player_id", ""))
                for key in BATTING_KEYS:
                    batting[pid][key] += int(line.get(key, 0) or 0)
        for side_lines in (meta.get("pitcher_lines") or {}).values():
            for line in side_lines:
                pid = str(line.get("player_id", ""))
                for key in PITCHING_KEYS:
                    pitching[pid][key] += int(line.get(key, 0) or 0)
        return result

    harness.simulate_matchup_from_files = _capture
    harness.run_sim(
        args.games,
        args.seed,
        args.players.resolve(),
        None,
        args.base_dir.resolve(),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        # Pitching columns are prefixed: hr/bb/hbp/so exist on both lines.
        pitching_header = [f"p_{key}" for key in PITCHING_KEYS]
        writer.writerow(
            ("player_id", "line_type", *BATTING_KEYS, *pitching_header)
        )
        for pid in sorted(batting):
            if pid:
                row = [batting[pid][k] for k in BATTING_KEYS]
                writer.writerow((pid, "hitting", *row, *[""] * len(PITCHING_KEYS)))
        for pid in sorted(pitching):
            if pid:
                row = [pitching[pid][k] for k in PITCHING_KEYS]
                writer.writerow((pid, "pitching", *[""] * len(BATTING_KEYS), *row))


if __name__ == "__main__":
    main()
