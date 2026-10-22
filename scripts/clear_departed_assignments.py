"""Take players who already left a club off its lineups, depth chart and
pitching staff (8.4.1 catch-up).

usage: NEXGEN_DATA_ROOT=DATA_DIR clear_departed_assignments.py DATA_DIR [--apply] [--no-news]

From 8.4.1 a roster write clears a departing player on the spot
(``services.departure_cleanup``); this does the same for departures that
happened before, e.g. alpha-test's 2027 rollover. A player has left a club
when its roster file (any level) no longer lists him. Without ``--apply`` it
only reports. ``--apply`` writes the club's lineups, depth chart and staff
file in DATA_DIR and, unless ``--no-news``, posts the owner news item the
live hook posts. Run on a downloaded copy; NEXGEN_DATA_ROOT must point at
the same DATA_DIR (the lineup fill reads the league through it).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.departure_cleanup import clear_departed, org_player_ids  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
apply = "--apply" in sys.argv
news = "--no-news" not in sys.argv
data = Path(args[0])


def lineup_ids(team: str) -> set:
    ids = set()
    for hand in ("lhp", "rhp"):
        path = data / "lineups" / f"{team}_vs_{hand}.csv"
        if path.exists():
            with path.open(encoding="utf-8", newline="") as fh:
                ids |= {r["player_id"].strip() for r in csv.DictReader(fh) if r.get("player_id")}
    return ids


def chart_ids(team: str) -> set:
    path = data / "depth_charts" / f"{team}.json"
    try:
        chart = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {pid for ids in chart.values() if isinstance(ids, list) for pid in ids if pid}


def staff_ids(team: str) -> set:
    path = data / "rosters" / f"{team}_pitching.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {row[0].strip() for row in csv.reader(fh) if row and row[0].strip()}


total = 0
for roster in sorted((data / "rosters").glob("*.csv")):
    team = roster.stem
    if team.endswith("_pitching"):
        continue
    org = org_player_ids(roster)
    named = lineup_ids(team) | chart_ids(team) | staff_ids(team)
    gone = sorted(pid for pid in named - org if pid)
    if not gone:
        continue
    total += len(gone)
    print(f"{team}: {len(gone)} departed still named: {', '.join(gone)}")
    if apply:
        result = clear_departed(team, gone, data_dir=data, notify=news)
        for hand, made in result["lineups"].items():
            for m in made:
                print(f"   vs {hand.upper()}: {m['gone']} -> {m['replacement'] or '(lineup rebuilt)'} {m['position']}")
        if result["depth_chart"]:
            print(f"   depth chart: removed {len(result['depth_chart'])}")
        if result["staff"]:
            print("   staff: opened " + ", ".join(e["role"] for e in result["staff"]))
print(f"{'cleared' if apply else 'to clear'}: {total} player entries")
