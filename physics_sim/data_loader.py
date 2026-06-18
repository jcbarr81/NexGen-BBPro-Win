from __future__ import annotations

import csv
import functools
from pathlib import Path
from typing import List, Tuple, Dict

from .models import BatterRatings, PitcherRatings


def load_players(csv_path: Path) -> Tuple[List[BatterRatings], List[PitcherRatings]]:
    """Load players from ``players.csv`` and split into hitters/pitchers."""

    batters: List[BatterRatings] = []
    pitchers: List[PitcherRatings] = []
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            is_pitcher = str(row.get("is_pitcher", "0")).strip() in {"1", "True", "true", "yes"}
            if is_pitcher:
                pitchers.append(PitcherRatings.from_row(row))
            else:
                batters.append(BatterRatings.from_row(row))
    return batters, pitchers


def _file_token(path: Path) -> tuple[str, int, int]:
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), 0, 0)


@functools.lru_cache(maxsize=8)
def _load_players_by_id_cached(
    token: tuple[str, int, int],
) -> Tuple[Dict[str, BatterRatings], Dict[str, PitcherRatings]]:
    batters, pitchers = load_players(Path(token[0]))
    return (
        {b.player_id: b for b in batters},
        {p.player_id: p for p in pitchers},
    )


def load_players_by_id(
    csv_path: Path,
) -> Tuple[Dict[str, BatterRatings], Dict[str, PitcherRatings]]:
    """Load players and return dictionaries keyed by player_id.

    Cached by (path, mtime, size): every game in a day re-reads the same
    players.csv, so this turns N parses into one. The rating objects are
    immutable read-only snapshots, safe to share across games; the cache
    invalidates automatically if players.csv changes (e.g. an injury write)."""
    return _load_players_by_id_cached(_file_token(csv_path))
