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


# ---------------------------------------------------------------------------
# Walking the code (test_rating_scale_reads.py, test_rating_scale_writers.py)
# ---------------------------------------------------------------------------

# The ratings scale 2 moves, by attribute / column name, and their potentials.
MOVED_NAMES = frozenset({"ch", "ph", "eye", "fa", "arm", "control", "movement"})
MOVED_KEYS = MOVED_NAMES | {f"pot_{name}" for name in MOVED_NAMES}
# A line (or the ``def`` line of an enclosing function) carrying this marker
# is a reviewed read: the text after it says why the stored value is right.
READ_MARKER = "# rating-scale:"
ACCESSORS = frozenset({"engine_rating", "engine_potential"})
CODE_DIRS = ("api", "services", "utils", "playbalance", "physics_sim", "models", "scripts")


def code_files(root: Path = REPO) -> List[Path]:
    """Every production Python file the walkers look at."""

    files: List[Path] = []
    for name in CODE_DIRS:
        files.extend(
            path
            for path in sorted((root / name).rglob("*.py"))
            if "__pycache__" not in path.parts
        )
    return files


def _marked(lines: List[str], lineno: int) -> bool:
    """True when 1-based ``lineno``, or a comment directly above it, carries
    the marker."""

    if 1 <= lineno <= len(lines) and READ_MARKER in lines[lineno - 1]:
        return True
    above = lineno - 2
    while above >= 0 and lines[above].lstrip().startswith("#"):
        if READ_MARKER in lines[above]:
            return True
        above -= 1
    return False


def scan_rating_reads(path: Path) -> List[Tuple[int, str]]:
    """Unreviewed direct reads of a moved rating in ``path``.

    A read is an attribute access (``player.ch``) or a string constant
    naming a moved rating or its potential (``getattr(p, "ch")``,
    ``row["control"]``, a key list). It is not reported when it is the key
    handed to ``engine_rating`` / ``engine_potential``, or when its line or
    any statement enclosing it (up to the function or class) is marked
    ``# rating-scale:``, on the line or in a comment directly above.
    Returns ``(line, source line)`` pairs.
    """

    import ast

    text = Path(path).read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    tree = ast.parse(text)
    parents: Dict[int, Any] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    def reviewed(node: Any) -> bool:
        if _marked(lines, node.lineno):
            return True
        current = node
        while id(current) in parents:
            current = parents[id(current)]
            # Any enclosing statement: the assignment, an ``if`` around
            # it, the function.
            if isinstance(current, ast.stmt) and _marked(lines, current.lineno):
                return True
        return False

    def accessor_key(node: Any) -> bool:
        parent = parents.get(id(node))
        if not isinstance(parent, ast.Call) or node not in parent.args[1:2]:
            return False
        func = parent.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return name in ACCESSORS

    found: Dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in MOVED_NAMES:
            pass
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in MOVED_KEYS
            and not accessor_key(node)
        ):
            pass
        else:
            continue
        if not reviewed(node):
            found[node.lineno] = lines[node.lineno - 1].strip()
    return sorted(found.items())


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
