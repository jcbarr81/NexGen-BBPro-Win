"""Regenerate ``data/players.csv`` with the wide-spread ``arr`` profile.

Why this exists: the bundled seed used to only have meaningful spread
for ch/ph/sp; eye/fa/arm/gf/pl/vl/sc were essentially flat at ~50. New
leagues sample from this seed via ``_sample_normalized_hitter`` —
narrow seed → narrow new-league distributions → no player ever shows
a 90+ OVR.

This script regenerates the seed with the ``arr`` rating profile (which
goes through ``_generate_hitter_ratings`` / ``_generate_pitcher_ratings``
guardrail samplers — they produce the documented 40-92 outliers).
Existing leagues are NOT touched; only future league creation reads
this seed.

Usage::

    python scripts/regenerate_seed_players.py --hitters 320 --pitchers 280

The output overwrites ``data/players.csv`` at the repo root.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from playbalance.player_generator import generate_player


def _coerce_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, list):
        return "|".join(str(v) for v in value if v is not None)
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hitters", type=int, default=320)
    parser.add_argument("--pitchers", type=int, default=280)
    parser.add_argument("--seed", type=int, default=20260427)
    parser.add_argument("--profile", default="arr", help="Rating profile (arr | normalized).")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "players.csv",
        help="Output CSV (defaults to data/players.csv at repo root).",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    age_ranges = [(22, 26), (27, 30), (31, 34), (35, 38)]

    rows: list[dict] = []
    used_ids: set[str] = set()

    def _ensure_id(player: dict) -> dict:
        pid = str(player.get("player_id", ""))
        while not pid or pid in used_ids:
            pid = f"P{random.randint(1000, 9999)}"
        player["player_id"] = pid
        used_ids.add(pid)
        return player

    print(f"Generating {args.hitters} hitters + {args.pitchers} pitchers with profile={args.profile!r}…")

    for i in range(args.hitters):
        pos = positions[i % len(positions)]
        age_lo, age_hi = age_ranges[(i // len(positions)) % len(age_ranges)]
        player = generate_player(
            is_pitcher=False,
            primary_position=pos,
            age_range=(age_lo, age_hi),
            rating_profile=args.profile,
        )
        player["is_pitcher"] = False
        rows.append(_ensure_id(player))

    for i in range(args.pitchers):
        # Mix of starters + relievers via archetype rotation.
        archetype = None
        if i % 7 == 0:
            archetype = "closer"
        elif i % 5 == 0:
            archetype = "long_relief"
        age_lo, age_hi = age_ranges[(i // 8) % len(age_ranges)]
        player = generate_player(
            is_pitcher=True,
            age_range=(age_lo, age_hi),
            pitcher_archetype=archetype,
            rating_profile=args.profile,
        )
        player["is_pitcher"] = True
        rows.append(_ensure_id(player))

    # Build the column list from the union of all keys, with the canonical
    # order roughly matching the existing CSV so diffs are readable.
    canonical_order = (
        "player_id first_name last_name birthdate height weight ethnicity skin_tone hair_color "
        "facial_hair bats throws primary_position other_positions is_pitcher role "
        "preferred_pitching_role ch ph sp eye gf pl vl sc fa arm endurance control movement "
        "hold_runner fb cu cb sl si scb kn pot_ch pot_ph pot_sp pot_eye pot_gf pot_pl pot_vl "
        "pot_sc pot_fa pot_arm pot_control pot_movement pot_endurance pot_hold_runner pot_fb "
        "pot_cu pot_cb pot_sl pot_si pot_scb pot_kn injured injury_description return_date ready "
        "injury_list injury_start_date injury_minimum_days injury_eligible_date "
        "injury_rehab_assignment injury_rehab_days durability pitcher_archetype hitter_archetype"
    ).split()
    seen_extras: list[str] = []
    for row in rows:
        for key in row:
            if key not in canonical_order and key not in seen_extras:
                seen_extras.append(key)
    fieldnames = canonical_order + seen_extras

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _coerce_str(row.get(k)) for k in fieldnames})

    print(f"Wrote {len(rows)} rows to {args.out}")

    # Quick spread report so the operator can sanity-check.
    hitters = [r for r in rows if not r.get("is_pitcher")]
    print("\nHitter rating spread:")
    for stat in ("ch", "ph", "sp", "eye", "fa", "arm"):
        vals = [int(r.get(stat, 0) or 0) for r in hitters]
        if not vals:
            continue
        print(f"  {stat:5}: min={min(vals)}, max={max(vals)}, avg={sum(vals)/len(vals):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
