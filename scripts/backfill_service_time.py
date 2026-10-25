"""Back-fill major-league service time for a league (8.5.1).

usage: backfill_service_time.py DATA_DIR [--current-season] [--apply]

Owner's calls (2026-10-25):

* **Before the league began:** a player with at least a quarter-season of
  big-league playing time in the league's first season gets one season
  (172 days) for each year past 22 at that season (at most 15). A quarter
  rather than any game: before 7.45.6 alpha-test's games could use
  minor leaguers.
* **Each completed season** (``careers/career_players.json``): big-league
  playing time (``services.service_time.playing_time_days``).
* ``--current-season``: also credit the season in progress from
  ``season_stats.json`` (regular season only; for a league past its
  regular season but not yet rolled over, e.g. stats-test in its playoffs).

Writes ``service_time.json`` and every contract's ``service_time_days`` only
with ``--apply``; refuses when a ledger already exists. Run on a downloaded
copy and upload the two files.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import service_time as st  # noqa: E402
from services.contracts_service import _player_age  # noqa: E402
from utils.player_loader import load_players_from_csv  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
apply = "--apply" in sys.argv
current = "--current-season" in sys.argv
data = Path(args[0])

if st.exists(data) and apply:
    sys.exit("service_time.json already exists; not overwriting it")

career_path = data / "careers" / "career_players.json"
careers = (json.loads(career_path.read_text(encoding="utf-8")).get("players", {})
           if career_path.exists() else {})
season_keys = sorted({k for e in careers.values() for k in (e.get("seasons") or {})})
season_lines = {key: {pid: e["seasons"][key] for pid, e in careers.items()
                      if key in (e.get("seasons") or {})} for key in season_keys}
if current:
    stats = json.loads((data / "season_stats.json").read_text(encoding="utf-8"))
    index = json.loads((data / "career_index.json").read_text(encoding="utf-8"))
    now = index.get("current") or {}
    key = str(now.get("season_id") or f"current-{now.get('league_year')}")
    season_lines[key] = {pid: line for pid, line in (stats.get("players") or {}).items()
                         if isinstance(line, dict)}
    season_keys = season_keys + [key]
if not season_keys:
    sys.exit("no completed season to credit")

first = season_keys[0]
first_year = int(first[-4:]) if first[-4:].isdigit() else None
players = {str(p.player_id): p for p in load_players_from_csv(str(data / "players.csv"))}

days = collections.Counter()
pre_count = 0
for pid, line in season_lines[first].items():
    if st.playing_time_share(line) >= 0.25:
        pre = st.pre_league_days(_player_age(players.get(pid), season_year=first_year))
        if pre:
            days[pid] += pre
            pre_count += 1
for key in season_keys:
    for pid, line in season_lines[key].items():
        days[pid] += st.playing_time_days(line)

years = collections.Counter(min(d // 172, 10) for d in days.values() if d > 0)
print(f"seasons credited: {season_keys}; first season {first} ({first_year})")
print(f"players with service: {sum(1 for d in days.values() if d > 0)}; "
      f"pre-league credit: {pre_count}")
print("by full years:", dict(sorted(years.items())))
try:
    contracts = json.loads((data / "contracts.json").read_text(encoding="utf-8"))["players"]
    tiers = collections.Counter(
        "pre-arb" if days.get(pid, 0) < 3 * 172 else "arb" if days.get(pid, 0) < 6 * 172 else "FA"
        for pid in contracts)
    print("contracted players by tier:", dict(tiers))
except (OSError, KeyError, json.JSONDecodeError):
    pass

if apply:
    ledger = st.load(data)
    ledger["players"] = {pid: int(d) for pid, d in sorted(days.items()) if d > 0}
    ledger["season"] = {"dates": [], "credit": {}}
    ledger["backfill"] = {"seasons": season_keys, "first_year": first_year}
    st.save(ledger, data)
    print("contracts updated:", st.sync_contracts(data, ledger))
