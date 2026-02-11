from __future__ import annotations

import json
import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple, Any

from utils.path_utils import get_data_dir
import os
import time


STATE_DIR = get_data_dir()


def _state_path(year: int) -> Path:
    return STATE_DIR / f"draft_state_{year}.json"


def _results_path(year: int) -> Path:
    return STATE_DIR / f"draft_results_{year}.csv"


def load_state(year: int) -> Dict[str, Any]:
    path = _state_path(year)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(year: int, state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(year)
    _with_lock(path.with_suffix(path.suffix + ".lock"), lambda: path.write_text(json.dumps(state, indent=2), encoding="utf-8"))


def compute_order_from_season_stats(seed: int | None = None) -> List[str]:
    """Compute draft order from current season stats.

    Worst winning percentage first; tie‑breakers by run differential (asc),
    then a deterministic random using the provided seed.
    """
    stats_path = STATE_DIR / "season_stats.json"
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    teams: Dict[str, Dict[str, Any]] = data.get("teams", {})
    if not teams:
        return []
    rng = random.Random(seed)
    def _key(item: Tuple[str, Dict[str, Any]]):
        tid, s = item
        w = int(s.get("w", 0) or 0)
        l = int(s.get("l", 0) or 0)
        g = max(int(s.get("g", 0) or 0), w + l)
        pct = (w / g) if g else 0.0
        rd = int(s.get("r", 0) or 0) - int(s.get("ra", 0) or 0)
        return (pct, rd, rng.random())
    # Worst first: sort by pct asc, rd asc
    order = [tid for tid, _ in sorted(teams.items(), key=_key)]
    return order


def initialize_state(year: int, *, order: List[str], seed: int | None = None) -> Dict[str, Any]:
    state = {
        "year": year,
        "round": 1,
        "overall_pick": 1,
        "order": order,
        "selected": [],
        "seed": seed,
    }
    save_state(year, state)
    return state


def append_result(year: int, *, team_id: str, player_id: str, rnd: int, overall: int) -> None:
    path = _results_path(year)
    header = ["round", "overall_pick", "team_id", "player_id"]
    def _append():
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([rnd, overall, team_id, player_id])
    _with_lock(path.with_suffix(path.suffix + ".lock"), _append)


def _with_lock(lock_path: Path, action) -> None:
    # Simple cross‑platform lock using create‑and‑hold semantics
    for _ in range(200):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                action()
            finally:
                os.close(fd)
                try:
                    os.remove(str(lock_path))
                except OSError:
                    pass
            return
        except FileExistsError:
            time.sleep(0.05)
    # Fallback: run without lock after timeout
    action()


__all__ = [
    "load_state",
    "save_state",
    "compute_order_from_season_stats",
    "initialize_state",
    "append_result",
]
