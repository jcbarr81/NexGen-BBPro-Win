"""Utilities for loading player ratings from CSV data."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping
import csv

from utils.rating_scale import engine_row

from .ratings import clamp_rating


@dataclass
class Player:
    """Lightweight representation of a player with mapped ratings."""

    player_id: str
    name: str
    is_pitcher: bool
    ratings: Dict[str, float]


def _to_rating(value: str | float) -> float:
    """Convert ``value`` to a 0-100 rating."""
    # The CSV may contain empty strings or malformed data.  Converting via
    # ``float`` inside a ``try`` block normalises numeric input while falling
    # back to a neutral rating when conversion fails.
    try:
        return clamp_rating(float(value))
    except (TypeError, ValueError):
        return 50.0


# rating-scale: every row goes through engine_row before it is read
def load_players(path: str | Path) -> Dict[str, Player]:
    """Load players from ``path`` returning a mapping by ``player_id``.

    The CSV is expected to contain the fields used by the internal play-balance
    schema.  Pitching ratings map ``fb`` and ``sl`` to ``fastball`` and
    ``slider`` respectively along with ``control`` and ``movement``.  Batting
    ratings map ``ch`` to ``contact`` and ``pl`` to ``discipline``.
    """

    path = Path(path)
    players: Dict[str, Player] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = row.get("player_id")
            if not pid:
                # Skip rows without a primary identifier.
                continue
            # Ratings here feed an engine: read the row on the engine scale.
            row = engine_row(row)
            is_pitcher = row.get("is_pitcher", "0") == "1"
            # Combine first and last name fields; ``strip`` handles missing parts.
            name = f"{row.get('first_name','')} {row.get('last_name','')}".strip()
            ratings: Dict[str, float] = {}
            if is_pitcher:
                # Map short rating keys to internal names used by the engine.
                ratings["fastball"] = _to_rating(row.get("fb", 50))
                ratings["slider"] = _to_rating(row.get("sl", 50))
                ratings["control"] = _to_rating(row.get("control", 50))
                ratings["movement"] = _to_rating(row.get("movement", 50))
            else:
                ratings["contact"] = _to_rating(row.get("ch", 50))
                ratings["discipline"] = _to_rating(row.get("pl", 50))
            players[pid] = Player(pid, name, is_pitcher, ratings)
    return players


def load_lineup(path: str | Path, players: Mapping[str, Player]) -> list[Player]:
    """Return batting order from ``path`` using ``players`` mapping.

    The function attempts to read a CSV file describing the batting order.  A
    missing file should not be treated as a fatal error for simulations, so a
    ``FileNotFoundError`` is caught and results in an empty lineup.  Callers can
    then fall back to a default ordering.
    """

    path = Path(path)
    lineup: list[Player] = []
    try:
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                pid = row.get("player_id")
                if pid and pid in players:
                    # Preserve the order from the CSV which defines the batting
                    # order.
                    lineup.append(players[pid])
    except FileNotFoundError:
        # Allow the caller to handle a missing file gracefully by returning an
        # empty lineup.
        return []
    return lineup


def load_pitching_staff(path: str | Path, players: Mapping[str, Player]) -> list[Player]:
    """Return pitching staff from roster ``path`` using ``players`` mapping.

    Similar to :func:`load_lineup`, this helper swallows ``FileNotFoundError``
    and returns an empty list so that higher level utilities can fall back to a
    default staff when roster data is unavailable.
    """

    path = Path(path)
    staff: list[Player] = []
    try:
        with path.open(newline="") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if not row:
                    continue
                pid = row[0]
                if pid in players and players[pid].is_pitcher:
                    # Only include entries that correspond to loaded pitchers.
                    staff.append(players[pid])
    except FileNotFoundError:
        # Missing roster data results in an empty staff which callers may handle
        # with a fallback.
        return []
    return staff


__all__ = ["Player", "load_players", "load_lineup", "load_pitching_staff"]
