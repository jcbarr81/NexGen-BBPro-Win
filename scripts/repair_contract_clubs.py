"""Find (and with OUT_DIR, fix) contracts that name the wrong club (8.1.1).

usage: repair_contract_clubs.py DATA_DIR [OUT_DIR]

A player's club is the one whose roster file lists him (any level). A
contract whose team_id differs, for a player on exactly one club, is moved to
that club; nothing else in the contract changes. Players on no roster or on
two are reported and left alone. With OUT_DIR, writes OUT_DIR/contracts.json.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

data = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else None

clubs = defaultdict(set)
for f in sorted((data / "rosters").glob("*.csv")):
    if f.stem.endswith("_pitching"):
        continue
    with f.open(encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip():
                clubs[row[0].strip()].add(f.stem)

last_trade = {}
with (data / "transactions.csv").open(encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh):
        if row.get("action") == "trade_in":
            last_trade[row["player_id"]] = (row["team_id"], row.get("counterparty"), row.get("season_date"))

raw = (data / "contracts.json").read_text(encoding="utf-8")
payload = json.loads(raw)
contracts = payload["players"]
moves, no_roster, two_clubs = [], [], []
for pid, c in contracts.items():
    on = clubs.get(pid, set())
    team = str(c.get("team_id") or "")
    if not on:
        no_roster.append((pid, team))
        continue
    if len(on) > 1:
        two_clubs.append((pid, sorted(on)))
        continue
    club = next(iter(on))
    if club != team:
        moves.append((pid, team, club, last_trade.get(pid), c.get("annual_salary"), c.get("years_left")))

print(f"contracts {len(contracts)}; to move {len(moves)}; on no roster {len(no_roster)}; on two clubs {len(two_clubs)}")
by_trade = sum(1 for m in moves if m[3] and m[3][0] == m[2] and m[3][1] == m[1])
print(f"moves explained by a logged trade (old club -> roster club): {by_trade} of {len(moves)}")
for pid, team, club, trade, salary, years in moves:
    print(f"  {pid}: contract {team} -> roster {club}  ${salary:,}/yr x{years}  trade {trade}")
if no_roster:
    print("on no roster (left alone):", no_roster[:20], "..." if len(no_roster) > 20 else "")
if two_clubs:
    print("on two clubs (left alone):", two_clubs)

payroll = defaultdict(lambda: [0, 0])
for pid, team, club, *_rest, salary, years in [(m[0], m[1], m[2], m[4], m[5]) for m in moves]:
    payroll[team][0] -= int(salary or 0)
    payroll[club][1] += int(salary or 0)
print("payroll change by club (annual):")
for club in sorted(payroll):
    out_amt, in_amt = payroll[club]
    print(f"  {club}: {out_amt + in_amt:+,}")

if out is not None:
    for pid, _team, club, *_ in moves:
        contracts[pid]["team_id"] = club
    out.mkdir(parents=True, exist_ok=True)
    # Keep the file's own layout (indent) and line endings.
    indent = 2 if raw.startswith("{\n  ") or raw.startswith("{\r\n  ") else None
    text = json.dumps(payload, indent=indent)
    if "\r\n" in raw:
        text = text.replace("\n", "\r\n")
    if raw.endswith("\n") and not text.endswith("\n"):
        text += "\r\n" if "\r\n" in raw else "\n"
    (out / "contracts.json").write_text(text, encoding="utf-8", newline="")
    print("wrote", out / "contracts.json")
