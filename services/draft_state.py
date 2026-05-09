from __future__ import annotations

import json
import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple, Any

from utils.path_utils import get_data_dir
import os
import time


def _state_dir() -> Path:
    return get_data_dir()


def _state_path(year: int) -> Path:
    return _state_dir() / f"draft_state_{year}.json"


def _results_path(year: int) -> Path:
    return _state_dir() / f"draft_results_{year}.csv"


def load_state(year: int) -> Dict[str, Any]:
    path = _state_path(year)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(year: int, state: Dict[str, Any]) -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)
    path = _state_path(year)
    _with_lock(path.with_suffix(path.suffix + ".lock"), lambda: path.write_text(json.dumps(state, indent=2), encoding="utf-8"))


def _order_from_team_stats(
    teams: Dict[str, Dict[str, Any]],
    seed: int | None,
) -> List[str]:
    """Worst-record-first ordering: pct asc, run diff asc, then deterministic rng."""

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

    return [tid for tid, _ in sorted(teams.items(), key=_key)]


def compute_order_from_season_stats(
    seed: int | None = None,
    *,
    stats_path: Path | None = None,
) -> List[str]:
    """Compute draft order from a season-stats JSON file.

    Worst winning percentage first; tie-breakers by run differential (asc),
    then a deterministic random using the provided seed. Defaults to the
    current league's ``season_stats.json``; pass ``stats_path`` to score a
    different snapshot (e.g. an archived prior year).
    """

    path = stats_path or (_state_dir() / "season_stats.json")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    teams: Dict[str, Dict[str, Any]] = data.get("teams", {}) or {}
    return _order_from_team_stats(teams, seed)


def _archived_stats_path_for_league_year(league_year: int) -> Path | None:
    """Resolve the archived ``stats.json`` for a finished league year.

    Reads the SeasonContext catalog rather than guessing at directory
    names so this stays in lock-step with however ``LeagueRolloverService``
    chose to identify the season (``<league_id>-<year>`` today).
    Returns ``None`` if no archive matches.
    """

    try:
        from playbalance.season_context import SeasonContext, CAREER_DATA_DIR
    except Exception:
        return None
    try:
        ctx = SeasonContext.load()
    except Exception:
        return None
    for season in ctx.iter_archived_seasons():
        if int(season.get("league_year") or 0) == int(league_year):
            sid = season.get("season_id")
            if not sid:
                continue
            candidate = CAREER_DATA_DIR / sid / "stats.json"
            if candidate.exists():
                return candidate
    return None


def compute_order_for_draft_year(
    draft_year: int,
    seed: int | None = None,
) -> List[str]:
    """Pick the right standings source for *draft_year*'s amateur draft.

    Year 2+ leagues should draft in worst-record-first order based on the
    PRIOR season's final standings (the MLB convention). If no archived
    season exists for ``draft_year - 1`` we fall back to the current
    season's running stats so first-year leagues still get an order
    seeded from whatever's been played to date.
    """

    archived = _archived_stats_path_for_league_year(draft_year - 1)
    if archived is not None:
        order = compute_order_from_season_stats(seed=seed, stats_path=archived)
        if order:
            return order
    # First year of the league (or no archive yet) — use the current
    # season's standings as the best available signal.
    return compute_order_from_season_stats(seed=seed)


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
    "compute_order_for_draft_year",
    "initialize_state",
    "append_result",
]
