"""Stretched twins for the rating-scale tests (test_rating_scale_*.py).

A TWIN of a league directory is the same league with every player row
re-expressed on rating scale 2 (``utils.rating_scale.stretch_row``) and the
``rating_scale`` column added; nothing else differs. The scale change is
play-neutral exactly when a league and its twin give the same games, the
same rating centres and the same CPU decisions, and that is what those
tests compare.

Twins are only ever written under pytest's ``tmp_path``. Nothing here
touches a fixture in place or a real league.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from utils.rating_scale import (
    FULL_RATING_SCALE,
    RATING_SCALE_FIELD,
    RatingClip,
    stretch_rows,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = {
    "calibration": REPO / "data" / "calibration",
    "calibration_league": REPO / "data" / "calibration_league",
    "calibration_flat": REPO / "data" / "calibration_flat",
}
# Blocks of a harness summary that describe the season played. ``runtime_s``
# is the only value in them that is not the season.
SEASON_BLOCKS = (
    "metrics",
    "report_only",
    "leaders",
    "team_stats",
    "platoon",
    "tto_splits",
    "usage_kpis",
)
PITCH_KEYS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")


def read_player_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def write_player_rows(
    path: Path, fields: Iterable[str], rows: Iterable[Dict[str, Any]]
) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def stretch_players_file(
    src: Path, dst: Path, *, scale: int = FULL_RATING_SCALE
) -> List[RatingClip]:
    """Write ``src`` (a players.csv) to ``dst`` on ``scale``; the clips."""

    fields, rows = read_player_rows(src)
    stretched, clips = stretch_rows(rows, scale)
    if RATING_SCALE_FIELD not in fields:
        fields = fields + [RATING_SCALE_FIELD]
    write_player_rows(dst, fields, stretched)
    return clips


def write_stretched_twin(
    src: Path, dst: Path, *, scale: int = FULL_RATING_SCALE
) -> List[RatingClip]:
    """Copy the league directory ``src`` to ``dst`` with players.csv
    stretched to ``scale``. Returns every clipped value (the fixtures have
    none; a test that needs an exact twin asserts so)."""

    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name == "players.csv":
            continue
        if entry.is_dir():
            shutil.copytree(entry, dst / entry.name)
        else:
            shutil.copy(entry, dst / entry.name)
    return stretch_players_file(src / "players.csv", dst / "players.csv", scale=scale)


def floor_potentials(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    """``rows`` with every potential raised to the current rating.

    The scale 2 potential rule never stores a potential below current, so a
    twin differs from its original, in engine terms, by exactly this floor
    (plus any gap cut at 99). Consumers that read potentials are compared
    against the floored original, which isolates the scale from the rule.
    """

    out: List[Dict[str, str]] = []
    for row in rows:
        new = dict(row)
        for key, value in row.items():
            if not key.startswith("pot_") or key[4:] not in row:
                continue
            try:
                current, potential = float(row[key[4:]]), float(value)
            except (TypeError, ValueError):
                continue
            if current > 0 and 0 < potential < current:
                new[key] = row[key[4:]]
        out.append(new)
    return out


def flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
    """A nested summary as ``{dotted.path: leaf}``."""

    flat: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            flat.update(flatten(item, f"{prefix}[{index}]"))
    else:
        flat[prefix] = value
    return flat


def season_values(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Every value of a harness summary that describes the season."""

    flat = flatten({block: summary.get(block) for block in SEASON_BLOCKS})
    return {
        key: value
        for key, value in flat.items()
        if not key.endswith("runtime_s")
    }


def differences(left: Dict[str, Any], right: Dict[str, Any]) -> List[str]:
    """Keys whose values differ between two flattened summaries.

    Exact comparison, floats included; NaN equals NaN.
    """

    out: List[str] = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key, "<missing>"), right.get(key, "<missing>")
        if a == b:
            continue
        if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
            continue
        out.append(f"{key}: {a!r} != {b!r}")
    return out


def run_season(
    base_dir: Path,
    *,
    games: int,
    seed: int = 1,
    engine: int | None = None,
    teams: int | None = None,
) -> Dict[str, Any]:
    """A harness season on the league directory ``base_dir``, in process.

    ``teams`` plays only the first N clubs (the schedule needs at least
    ``4 * (N - 1)`` games a club), which is what keeps a test season short;
    the rating centres are still the whole league's.
    """

    import scripts.physics_sim_season_kpis as kpis

    base_dir = Path(base_dir)
    overrides = kpis.resolve_run_overrides(
        engine=engine, overrides_path=None, disable_park_factors=False
    )
    real_team_ids = kpis._team_ids
    if teams is not None:
        kpis._team_ids = lambda *a, **k: real_team_ids(*a, **k)[:teams]
    try:
        return kpis.run_sim(
            games, seed, base_dir / "players.csv", overrides, base_dir
        )
    finally:
        kpis._team_ids = real_team_ids
