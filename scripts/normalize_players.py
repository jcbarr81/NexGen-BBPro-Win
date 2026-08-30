#!/usr/bin/env python3
"""Normalize player ratings using shared template sampling.

This script rewrites ``data/players.csv`` (or a provided CSV) so that hitter
and pitcher ratings align with the template sampling used by the runtime
generator. Existing IDs/names/biographical data are preserved; only ratings
are resampled.

Usage examples::

    python scripts/normalize_players.py --players data/players.csv \
        --output data/players_normalized.csv

    # Overwrite the source file after review
    python scripts/normalize_players.py --players data/players.csv --in-place
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Dict

import sys

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from playbalance import player_generator as pg


HITTER_FIELDS = ("ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm")
PITCHER_FIELDS = (
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "arm",
    "fa",
    "gf",
    "vl",
    "fb",
    "cu",
    "cb",
    "sl",
    "si",
    "scb",
    "kn",
)


def _clamp(val: int, low: int = 30, high: int = 99) -> int:
    return max(low, min(high, val))


def _infer_hitter_template(row: Dict[str, str]) -> str:
    try:
        ch = float(row.get("ch") or 0)
        ph = float(row.get("ph") or 0)
        sp = float(row.get("sp") or 0)
    except (TypeError, ValueError):
        return "balanced"
    if sp >= 75:
        return "speed"
    if ph >= ch + 8:
        return "power"
    if ch >= ph + 8:
        return "spray"
    if ch < 58 and ph < 58:
        return "average"
    return "balanced"


def normalize_hitter(row: Dict[str, str]) -> None:
    position = (row.get("primary_position") or "CF").strip().upper()
    bats = (row.get("bats") or "R").strip().upper()
    archetype = row.get("hitter_archetype") or _infer_hitter_template(row)
    ratings = pg._sample_normalized_hitter(position, bats, archetype)
    if not ratings:
        return
    row["hitter_archetype"] = ratings["hitter_archetype"]
    for key in HITTER_FIELDS:
        if key in ratings:
            row[key] = str(_clamp(int(ratings[key])))


def normalize_pitcher(row: Dict[str, str]) -> None:
    archetype = (
        row.get("pitcher_archetype")
        or row.get("preferred_pitching_role")
        or row.get("role")
        or ""
    ).strip().lower()
    archetype = archetype or None
    throws = (row.get("bats") or "R").strip().upper()
    ratings = pg._sample_normalized_pitcher(archetype, throws)
    if not ratings:
        return
    row["pitcher_archetype"] = ratings.get("pitcher_archetype", "")
    for key in PITCHER_FIELDS:
        if key in ratings:
            row[key] = str(_clamp(int(ratings[key])))
    preferred = ratings.get("preferred_pitching_role") or ""
    if preferred:
        row["preferred_pitching_role"] = preferred
    role = ratings.get("role")
    if role:
        row["role"] = role


def normalize(players_path: Path, output_path: Path) -> None:
    pg._RATING_DISTRIBUTIONS = pg._load_rating_distributions(players_path)
    with players_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        rows = list(reader)

    fieldnames = reader.fieldnames or []
    for row in rows:
        if row.get("is_pitcher") == "1":
            normalize_pitcher(row)
        else:
            normalize_hitter(row)
        # Track any new fields added during normalization (e.g., archetype tags)
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    if not fieldnames:
        fieldnames = sorted({k for row in rows for k in row})
    with output_path.open("w", newline="", encoding="utf-8") as dest:
        writer = csv.DictWriter(dest, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--players",
        type=Path,
        default=Path("data/players.csv"),
        help="Input players CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted use --in-place.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducibility",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file instead of writing a new one",
    )
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    if args.output is None and not args.in_place:
        parser.error("Specify --output or --in-place")

    output_path = args.players if args.in_place else args.output
    assert output_path is not None
    # Guard against the ratings-compression feedback loop: normalize() samples
    # each rating from the INPUT file's OWN distribution (line 113), so writing
    # back over the input narrows the spread toward the median — and re-running
    # collapses every rating toward ~50 with hard floors (this flattened a live
    # league once: pitcher endurance 48-54, movement pinned to 52). Always read
    # from a healthy wide-spread source and write to a DIFFERENT file.
    if output_path.resolve(strict=False) == args.players.resolve(strict=False):
        parser.error(
            "Refusing in-place normalization: this samples from the input's own "
            "distribution, so overwriting it compresses ratings toward the mean "
            "(re-running collapses them to ~50). Use --output to a DIFFERENT file "
            "sourced from a healthy, wide-spread players.csv."
        )
    normalize(args.players, output_path)
    print(f"Normalized players written to {output_path}")


if __name__ == "__main__":
    main()
