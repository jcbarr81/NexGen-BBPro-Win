"""Derive current streak + last-10 form from the played schedule.

The season simulator only persists cumulative W/L/R/RA (to season_stats.json),
never the per-game streak/last10 the standings + dashboard surfaces want — so
those columns always rendered "--". schedule.csv records every played game's
score (``result`` = ``home-away``) in chronological order, which is enough to
reconstruct both without changing the core sim or standings persistence.

Shared by api/routers/standings_league.py (full standings page) and
api/routers/dashboard.py (owner-dashboard division widget) so both read the
same numbers.
"""

from __future__ import annotations

import csv
from typing import Dict, List

from utils.path_utils import get_data_dir


def streak_last10_from_schedule() -> Dict[str, Dict[str, str]]:
    """Return ``{team_id: {"streak": "W3", "last10": "7-3"}}`` from schedule.csv.

    Teams with no played games are omitted. Malformed/tied results are skipped.
    """

    schedule_path = get_data_dir() / "schedule.csv"
    if not schedule_path.exists():
        return {}

    # Per-team ordered list of "W"/"L" outcomes. schedule.csv is written sorted
    # by date, so reading in file order is chronological.
    outcomes: Dict[str, List[str]] = {}
    try:
        with schedule_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                home = str(row.get("home", "") or "").strip()
                away = str(row.get("away", "") or "").strip()
                result = str(row.get("result", "") or "").strip()
                if not (home and away and "-" in result):
                    continue
                try:
                    home_runs, away_runs = (int(p) for p in result.split("-", 1))
                except (TypeError, ValueError):
                    continue
                if home_runs == away_runs:
                    continue  # no ties in baseball; skip anything malformed
                home_won = home_runs > away_runs
                outcomes.setdefault(home, []).append("W" if home_won else "L")
                outcomes.setdefault(away, []).append("L" if home_won else "W")
    except OSError:
        return {}

    derived: Dict[str, Dict[str, str]] = {}
    for team_id, seq in outcomes.items():
        if not seq:
            continue
        # Current streak: trailing run of the same outcome.
        last = seq[-1]
        length = 0
        for outcome in reversed(seq):
            if outcome == last:
                length += 1
            else:
                break
        last10 = seq[-10:]
        wins = last10.count("W")
        losses = last10.count("L")
        derived[team_id] = {
            "streak": f"{last}{length}",
            "last10": f"{wins}-{losses}",
        }
    return derived


__all__ = ["streak_last10_from_schedule"]
