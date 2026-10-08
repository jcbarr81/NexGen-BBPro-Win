from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Optional
import csv
import json

from .path_utils import get_data_dir

# The league date a step inside a running sim call acts on (see
# ``sim_date_scope``). None outside such a step.
_SIM_DATE_OVERRIDE: ContextVar[Optional[str]] = ContextVar(
    "nexgen_sim_date_override", default=None
)


@contextmanager
def sim_date_scope(sim_date: Optional[str]) -> Iterator[None]:
    """Pin :func:`get_current_sim_date` to ``sim_date`` inside the block.

    The season router persists the schedule and ``season_progress.json`` only
    when a sim call ends, so during a multi-day call the date read from those
    files is still the call's FIRST day. Roster prep before a date's games,
    the per-day injured-list step after them and the playoff-day steps run
    under this scope, so everything they read or stamp (roster caps,
    eligibility, the ``season_date`` of a transaction) uses the date a one-day
    call would have seen. Applies only to the current context (thread /
    request) and only to calls without an explicit ``base_dir``. A blank
    ``sim_date`` leaves the normal lookup in place.
    """

    value = str(sim_date or "").strip()[:10] or None
    token = _SIM_DATE_OVERRIDE.set(value)
    try:
        yield
    finally:
        _SIM_DATE_OVERRIDE.reset(token)


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

    Cached against the mtimes of the two source files (S1-05): this function
    is called from ~15 modules — often several times per request — and used to
    re-parse the entire schedule CSV on every call. The result is an immutable
    string, so sharing is safe.
    """

    if base_dir is None:
        pinned = _SIM_DATE_OVERRIDE.get()
        if pinned:
            return pinned

    from utils.file_cache import cached_read

    base = get_data_dir() if base_dir is None else (base_dir / "data")
    sched = base / "schedule.csv"
    prog = base / "season_progress.json"
    return cached_read(
        f"sim_date|{base}",
        (sched, prog),
        lambda: _compute_sim_date(sched, prog),
    )


def _compute_sim_date(sched: Path, prog: Path) -> str | None:
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
