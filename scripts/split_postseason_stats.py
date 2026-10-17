"""Split a league's 2026 stats into regular season and postseason (8.1.1).

usage: split_postseason_stats.py REPO REGULAR.json FINAL.json PLAYERS.csv OUT_DIR

REGULAR is the season_stats.json version saved at the end of the regular
season (every club at its scheduled game count), FINAL the current one (with
the playoff games added in). Writes OUT_DIR/season_stats.json (REGULAR's
bytes unchanged) and OUT_DIR/postseason_stats.json: every counting stat is
FINAL minus REGULAR, every derived stat recomputed from those counts with the
engine's own formulas, in the order the game writer applies them (batting,
pitching, fielding; later blocks win the shared keys). Prints a report and
checks REGULAR + POST == FINAL for every counting stat.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

repo, regular_path, final_path, players_csv, out_dir = sys.argv[1:6]
sys.path.insert(0, repo)

from playbalance.stats import (  # noqa: E402
    compute_batting_derived,
    compute_batting_rates,
    compute_fielding_derived,
    compute_fielding_rates,
    compute_pitching_derived,
    compute_pitching_rates,
    compute_team_rates,
)

regular = json.loads(Path(regular_path).read_text(encoding="utf-8"))
final = json.loads(Path(final_path).read_text(encoding="utf-8"))
positions = {}
with open(players_csv, encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh):
        positions[row.get("player_id")] = row.get("primary_position") or ""

# Integer keys that are derived, not counted: recomputed, never differenced.
RECOMPUTED_INTS = {"tb", "xbh", "svo", "k_minus_bb", "tc", "of_a", "cg", "sho", "qs", "2b", "3b"}


def _i(d, k):
    try:
        return int(d.get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _batting(s):
    st = SimpleNamespace(**{k: _i(s, k) for k in (
        "b1", "b2", "b3", "hr", "lob", "pitches", "pa", "ab", "h", "bb", "hbp",
        "sf", "so", "so_looking", "sb", "cs", "gb", "ld", "fb")})
    out = dict(compute_batting_derived(st))
    out.update(compute_batting_rates(st))
    out["2b"] = _i(s, "b2")
    out["3b"] = _i(s, "b3")
    return out


def _pitching(s):
    keys = ("outs", "gs", "gf", "r", "er", "so", "bb", "hbp", "hr", "h", "gb", "ld",
            "fb", "pitches_thrown", "bf", "first_pitch_strikes", "zone_pitches",
            "o_zone_pitches", "zone_swings", "o_zone_swings", "zone_contacts",
            "o_zone_contacts", "so_looking")
    st = SimpleNamespace(**{k: _i(s, k) for k in keys})
    out = {"svo": _i(s, "sv") + _i(s, "bs")}
    out.update(compute_pitching_derived(st))
    out.update(compute_pitching_rates(st))
    return out


def _fielding(s, pid):
    st = SimpleNamespace(
        player=SimpleNamespace(primary_position=positions.get(pid, "")),
        g=_i(s, "g"), po=_i(s, "f_po"), a=_i(s, "a"), e=_i(s, "e"), dp=_i(s, "dp"),
        tp=_i(s, "tp"), pk=_i(s, "f_pk"), pb=_i(s, "pb"), ci=_i(s, "f_ci"),
        cs=_i(s, "f_cs"), sba=_i(s, "sba"),
    )
    out = dict(compute_fielding_derived(st))
    out.update(compute_fielding_rates(st))
    return out


def split_player(pid, fin, reg):
    post = {}
    for k, v in fin.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and k not in RECOMPUTED_INTS:
            post[k] = v - _i(reg, k)
    if not any(post.values()):
        return None, []
    derived = {}
    if "avg" in fin:
        derived.update(_batting(post))
    if "era" in fin or "ip" in fin:
        derived.update(_pitching(post))
    if "fpct" in fin:
        derived.update(_fielding(post, pid))
    unhandled = []
    for k, v in fin.items():
        if k in post:
            continue
        if k in derived:
            post[k] = derived[k]
        else:
            unhandled.append(k)
    return post, unhandled


players_out, unhandled_keys, negatives = {}, {}, []
for pid, fin in final["players"].items():
    post, unhandled = split_player(pid, fin, regular["players"].get(pid, {}))
    if post is None:
        continue
    players_out[pid] = post
    for k in unhandled:
        unhandled_keys[k] = unhandled_keys.get(k, 0) + 1
    if any(isinstance(v, int) and v < 0 for v in post.values()):
        negatives.append(pid)

teams_out = {}
for tid, fin in final["teams"].items():
    reg = regular["teams"].get(tid, {})
    post = {k: v - _i(reg, k) for k, v in fin.items() if isinstance(v, int)}
    if not post.get("g"):
        continue
    post.update(compute_team_rates(post))
    teams_out[tid] = {k: post[k] for k in fin if k in post}

# Check: regular + post == final for every counting stat.
mismatch = 0
for pid, fin in final["players"].items():
    reg = regular["players"].get(pid, {})
    post = players_out.get(pid, {})
    for k, v in fin.items():
        if isinstance(v, int) and not isinstance(v, bool) and k not in RECOMPUTED_INTS:
            if _i(reg, k) + _i(post, k) != v:
                mismatch += 1

out = Path(out_dir)
out.mkdir(parents=True, exist_ok=True)
shutil.copyfile(regular_path, out / "season_stats.json")
payload = {"players": players_out, "teams": teams_out, "history": []}
(out / "postseason_stats.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

reg_games = {t: v.get("g") for t, v in regular["teams"].items()}
print("regular-season games per club:", sorted(set(reg_games.values())))
print("postseason players:", len(players_out), "clubs:", len(teams_out))
for tid, t in sorted(teams_out.items(), key=lambda x: -x[1]["g"]):
    print(f"  {tid}: {t['g']} games, {t.get('w', 0)}-{t.get('l', 0)}, {t.get('r', 0)} runs for, {t.get('ra', 0)} against")
print("counting-stat mismatches:", mismatch)
print("players with a negative count:", negatives)
print("final keys not rebuilt:", unhandled_keys)
lead = sorted(
    ((pid, p) for pid, p in players_out.items() if "avg" in p and "era" not in p),
    key=lambda x: -x[1].get("hr", 0),
)[:5]
for pid, p in lead:
    print(f"  {pid}: {p.get('g')} G, {p.get('pa')} PA, {p.get('h')} H, {p.get('hr')} HR, {p.get('rbi')} RBI, avg {p.get('avg', 0):.3f}")
