from __future__ import annotations

from pathlib import Path
import csv
import json

from .path_utils import get_data_dir


def _infer_completed_days(
    schedule_rows: list[dict[str, str]], ordered_dates: list[str]
) -> int:
    """Estimate how many schedule days have finished based on CSV flags."""

    by_date: dict[str, list[dict[str, str]]] = {}
    for row in schedule_rows:
        date_val = str(row.get("date") or "").strip()
        if not date_val:
            continue
        by_date.setdefault(date_val, []).append(row)

    completed = 0
    for date_val in ordered_dates:
        games = by_date.get(date_val, [])
        if not games:
            continue
        all_done = True
        for game in games:
            played = str(game.get("played") or "").strip()
            result = str(game.get("result") or "").strip()
            if not (played == "1" or result):
                all_done = False
                break
        if all_done:
            completed += 1
        else:
            break
    return completed


def get_current_sim_date(base_dir: Path | None = None) -> str | None:
    """Return the best-known simulation date or ``None`` when unavailable.

    Prefers the ``sim_index`` stored in ``season_progress.json`` but falls back
    to inferring progress from the schedule file when the persisted index is
    stale. The returned value corresponds to the next scheduled date that has
    not yet been fully simulated.
    """

    base = get_data_dir() if base_dir is None else (base_dir / "data")
    sched = base / "schedule.csv"
    prog = base / "season_progress.json"
    if not sched.exists():
        return None
    try:
        with sched.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return None
    if not rows:
        return None

    unique_dates: list[str] = []
    seen: set[str] = set()
    for row in rows:
        date_val = str(row.get("date") or "").strip()
        if not date_val or date_val in seen:
            continue
        unique_dates.append(date_val)
        seen.add(date_val)
    if not unique_dates:
        return None

    inferred_index = _infer_completed_days(rows, unique_dates)
    progress_index = 0
    if prog.exists():
        try:
            with prog.open("r", encoding="utf-8") as fh:
                progress = json.load(fh)
            progress_index = int(progress.get("sim_index", 0) or 0)
        except Exception:
            progress_index = 0

    sim_index = max(progress_index, inferred_index)
    sim_index = max(0, min(sim_index, len(unique_dates) - 1))
    return unique_dates[sim_index]
