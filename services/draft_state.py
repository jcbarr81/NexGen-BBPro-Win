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


def state_is_complete(state: Dict[str, Any], total_rounds: int) -> bool:
    """True when a draft state has run to its last pick.

    With qualifying-offer compensation the state carries an explicit pick
    sequence; otherwise the order repeats for ``total_rounds`` rounds.

    A draft that has finished is stamped ``completed`` and stays finished:
    ``total_rounds`` is the league's current setting, and raising it for next
    year must not reopen a draft that is over (a preseason draft would
    otherwise reopen at spring training, or pause the season in July for the
    extra rounds).
    """

    if state.get("completed") is True:
        return True
    seq = state.get("pick_sequence")
    if isinstance(seq, list) and seq:
        return int(state.get("overall_pick", 1) or 1) > len(seq)
    return int(state.get("round", 1) or 1) > max(1, int(total_rounds or 1))


# A league year with no amateur draft at all: a new league that drafts in the
# preseason holds its first draft after its first completed season, so its
# first season has neither a preseason draft (no records to order by) nor a
# July one. Recorded when that season's Opening Day arrives, so a league that
# only switches to a preseason draft later in its first season keeps the July
# draft that was already ahead of it.
def _skipped_years_path() -> Path:
    return _state_dir() / "draft_skipped_years.json"


def skipped_years() -> List[int]:
    try:
        payload = json.loads(_skipped_years_path().read_text(encoding="utf-8"))
    except Exception:
        return []
    years = payload.get("years") if isinstance(payload, dict) else None
    out: List[int] = []
    for value in years or []:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def is_year_skipped(year: int) -> bool:
    return int(year) in skipped_years()


def mark_year_skipped(year: int) -> None:
    years = sorted(set(skipped_years()) | {int(year)})
    path = _skipped_years_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"years": years}, indent=2), encoding="utf-8")


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


def _last_archived_stats_path() -> Path | None:
    """The archived ``stats.json`` of the most recently finished season."""

    try:
        from playbalance.season_context import SeasonContext, CAREER_DATA_DIR
    except Exception:
        return None
    try:
        seasons = list(SeasonContext.load().iter_archived_seasons())
    except Exception:
        return None
    for season in reversed(seasons):
        sid = season.get("season_id") if isinstance(season, dict) else None
        if not sid:
            continue
        candidate = CAREER_DATA_DIR / sid / "stats.json"
        if candidate.exists():
            return candidate
    return None


def has_completed_season() -> bool:
    """True once the league has finished (and archived) at least one season.

    A league's first amateur draft follows its first completed season, so a
    preseason draft is never held in a new league's first preseason.
    """

    return _last_archived_stats_path() is not None


def compute_order_from_last_season(seed: int | None = None) -> List[str]:
    """Reverse order of the last completed season's records, or ``[]``.

    The order for a draft held in the preseason: the season it would have
    interrupted has not started, so there are no current standings to fall
    back on (``compute_order_for_draft_year`` would rank a slate of 0-0
    clubs at random). Reads the latest archive whatever its year label.
    """

    archived = _last_archived_stats_path()
    if archived is None:
        return []
    return compute_order_from_season_stats(seed=seed, stats_path=archived)


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


def build_pick_sequence(
    order: List[str],
    total_rounds: int,
    *,
    supplemental: List[str] | None = None,
    forfeited: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Explicit per-pick sequence supporting qualifying-offer compensation.

    Compensation picks (``supplemental`` — teams that lost a QO'd free agent)
    are appended to the end of round 1 as **extra** picks. Teams that signed a
    QO'd free agent (``forfeited``) lose their **round-2** pick. With neither
    set this is exactly ``order`` repeated ``total_rounds`` times, so the draft
    behaves identically to the simple repeating-order model.

    Returns a flat list of ``{"team_id", "round"}`` in overall-pick order.
    """

    clean_order = [str(t).strip() for t in (order or []) if str(t).strip()]
    rounds = max(1, int(total_rounds or 1))
    supp = [str(t).strip() for t in (supplemental or []) if str(t).strip()]
    forf = {str(t).strip() for t in (forfeited or []) if str(t).strip()}

    seq: List[Dict[str, Any]] = []
    for team in clean_order + supp:  # round 1: full order, then extra comp picks
        seq.append({"team_id": team, "round": 1})
    for rnd in range(2, rounds + 1):
        for team in clean_order:
            if rnd == 2 and team in forf:
                continue  # forfeited their second-round pick
            seq.append({"team_id": team, "round": rnd})
    return seq


def initialize_state(
    year: int,
    *,
    order: List[str],
    seed: int | None = None,
    total_rounds: int | None = None,
    supplemental: List[str] | None = None,
    forfeited: List[str] | None = None,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "year": year,
        "round": 1,
        "overall_pick": 1,
        "order": order,
        "selected": [],
        "seed": seed,
    }
    # Only materialize an explicit pick sequence when there's actual
    # qualifying-offer compensation — otherwise the legacy repeating-order
    # math drives the draft unchanged.
    if total_rounds and (supplemental or forfeited):
        state["pick_sequence"] = build_pick_sequence(
            order,
            int(total_rounds),
            supplemental=supplemental,
            forfeited=forfeited,
        )
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
    "compute_order_from_last_season",
    "compute_order_for_draft_year",
    "has_completed_season",
    "state_is_complete",
    "skipped_years",
    "is_year_skipped",
    "mark_year_skipped",
    "initialize_state",
    "append_result",
]
