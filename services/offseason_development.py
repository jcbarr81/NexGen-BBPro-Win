"""The yearly development step of the season rollover, for rating scale 2.

``LeagueRolloverService`` calls :func:`run_offseason_development` once per
offseason, after the season archive and before retirements (so a player
retires on his new ratings). It develops every row of ``players.csv`` that
is stored on rating scale 2 (``playbalance.development``) and leaves every
other row exactly as it is.

A league with no scale 2 row is not touched at all: the file is not
rewritten, nothing is recorded, and the rollover's artifacts do not change.
That is every league until the rating-scale switch, and every league on
scale 1 keeps the paused aging of 7.51.2.

The file is written whole and safely, the way the rating-scale conversion
writes it (``RATING_SCALE_DESIGN.md`` section 6): the rows are read as raw
CSV (no round trip through the player models, so no column a model does not
know is lost), only rating and potential cells change, the row count and the
set of player ids are checked before the write, and the write is atomic
(``utils.atomic_write``). A subset is never written (``save_players``
REPLACES the file; ``docs/future_work.md``).

Each club's training focus (``services.training_settings``) shares out its
players' growth, and its budgets (``services.finance_budget_effects``) speed
growth and slow decline. The year's changes are recorded as the season's
training history (``services.training_history``, what the player page
shows) and in ``development_last.json``, from which the spring training camp
reports them (``playbalance.training_camp``).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from playbalance.aging import calculate_age
from playbalance.development import (
    DEFAULT_PARAMS,
    DevelopmentParams,
    DevelopmentResult,
    develop_row,
    is_developed,
    summarize,
)
from utils.path_utils import get_data_dir
from utils.rating_scale import RATING_SCALE_FIELD

__all__ = [
    "DEVELOPMENT_RECORD",
    "OffseasonDevelopmentError",
    "load_development_record",
    "run_offseason_development",
]

_LOGGER = logging.getLogger(__name__)

# The last offseason's changes, for the spring training camp to report.
DEVELOPMENT_RECORD = "development_last.json"
# The label the training history shows for the offseason's development.
DEVELOPMENT_TIER = "offseason"
DEVELOPMENT_NOTE = (
    "Offseason development: growth toward potential, shared out by the "
    "training focus; decline after the peak years."
)


class OffseasonDevelopmentError(RuntimeError):
    """The players file could not be developed safely; nothing was written."""


def _read(path: Path) -> tuple[List[str], List[Dict[str, str]], str]:
    text = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text[: text.find("\n") + 1] else "\n"
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), list(reader), newline


def _write(path: Path, fields: List[str], rows: List[Dict[str, str]], newline: str) -> None:
    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(path, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator=newline)
        writer.writeheader()
        writer.writerows(rows)


def _team_lookup(data_dir: Path) -> Dict[str, str]:
    """player id -> team id, from the roster files (every level)."""

    out: Dict[str, str] = {}
    roster_dir = data_dir / "rosters"
    if not roster_dir.exists():
        return out
    for roster_file in sorted(roster_dir.glob("*.csv")):
        team_id = roster_file.stem
        if team_id.endswith(("_pitching", "_lineup")):
            continue
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if row and row[0].strip():
                        out.setdefault(row[0].strip(), team_id)
        except OSError:
            continue
    return out


def _weights(team_lookup: Mapping[str, str]):
    """A function: player id -> his ``TrainingWeights`` (his own, his
    team's or the league default), or ``None`` when the settings cannot be
    read (the default focus)."""

    try:
        from services.training_settings import load_training_settings

        settings = load_training_settings()
    except Exception:
        _LOGGER.warning("offseason development: training settings unavailable", exc_info=True)
        return lambda pid: None
    return lambda pid: settings.for_player(pid, team_lookup.get(pid))


def _budgets(team_lookup: Mapping[str, str], data_dir: Path, league_id: Optional[str]):
    """(development, training camp intensity) multipliers by player id."""

    try:
        from services.finance_budget_effects import (
            development_multiplier_by_player,
            training_camp_multiplier_by_player,
        )

        development = development_multiplier_by_player(
            team_lookup, data_dir=data_dir, league_id=league_id
        )
        intensity = training_camp_multiplier_by_player(
            team_lookup, data_dir=data_dir, league_id=league_id
        )
        return development, intensity
    except Exception:
        _LOGGER.warning("offseason development: budgets unavailable; neutral", exc_info=True)
        return {}, {}


def run_offseason_development(
    *,
    season_year: Optional[int],
    data_dir: Optional[Path] = None,
    league_id: Optional[str] = None,
    as_of: Optional[date] = None,
    params: DevelopmentParams = DEFAULT_PARAMS,
    record: bool = True,
) -> Optional[Dict[str, Any]]:
    """Develop every scale 2 player in the league's ``players.csv``.

    ``season_year`` is the coming season (it seeds the noise, so a repeated
    rollover gives the same result). Ages are taken on ``as_of`` (default:
    the league's sim date, as retirements take them). Returns ``None`` when
    the league has no scale 2 player (nothing read beyond the header,
    nothing written), else a summary for the rollover artifacts. Raises
    :class:`OffseasonDevelopmentError` rather than write anything doubtful.
    """

    resolved = Path(data_dir) if data_dir is not None else get_data_dir()
    path = resolved / "players.csv"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle), [])
    if RATING_SCALE_FIELD not in header:
        return None
    fields, rows, newline = _read(path)
    targets = [row for row in rows if is_developed(row)]
    if not targets:
        return None
    ids_before = [row.get("player_id", "") for row in rows]

    team_lookup = _team_lookup(resolved)
    weights = _weights(team_lookup)
    development, intensity = _budgets(team_lookup, resolved, league_id)
    season = season_year if season_year is not None else (as_of or date.today()).year

    results: List[DevelopmentResult] = []
    skipped = 0
    for row in targets:
        pid = str(row.get("player_id", "") or "")
        birthdate = str(row.get("birthdate", "") or "").split("T", 1)[0]
        try:
            age = calculate_age(birthdate, as_of=as_of)
        except (TypeError, ValueError):
            skipped += 1
            continue
        results.append(
            develop_row(
                row,
                age=age,
                season=season,
                development=float(development.get(pid, 1.0) or 1.0),
                intensity=float(intensity.get(pid, 1.0) or 1.0),
                weights=weights(pid),
                params=params,
            )
        )

    if [row.get("player_id", "") for row in rows] != ids_before:
        raise OffseasonDevelopmentError("the player ids changed while developing")
    changed = [r for r in results if r.changes]
    if changed:
        on_disk = _read(path)[1]
        if [r.get("player_id", "") for r in on_disk] != ids_before:
            raise OffseasonDevelopmentError(
                f"{path} changed while it was being developed; not written"
            )
        _write(path, fields, rows, newline)
        _clear_player_caches()

    summary = {"season": season, **summarize(results), "skipped": skipped}
    if record:
        _record(results, rows, season, resolved)
    _LOGGER.info("offseason development %s: %s", path, summary)
    return summary


def _clear_player_caches() -> None:
    try:
        from utils.player_loader import load_players_from_csv

        load_players_from_csv.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def _record(
    results: List[DevelopmentResult],
    rows: List[Dict[str, str]],
    season: int,
    data_dir: Path,
) -> None:
    """The training history and the record the camp reports from. Never
    blocks the rollover: the ratings are already written."""

    from playbalance.player_development import TrainingReport, track_label

    names = {
        str(row.get("player_id", "")): f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        for row in rows
    }
    reports = [
        TrainingReport(
            player_id=r.player_id,
            player_name=names.get(r.player_id, r.player_id),
            focus=track_label(r.focus) if r.focus else "Veteran upkeep",
            tier=DEVELOPMENT_TIER,
            attributes=tuple(sorted(r.changes)),
            note=DEVELOPMENT_NOTE,
            changes=dict(r.changes),
        )
        for r in results
        if r.changes
    ]
    try:
        payload = {
            "season": season,
            "players": {
                report.player_id: {"focus": report.focus, "changes": report.changes}
                for report in reports
            },
        }
        (data_dir / DEVELOPMENT_RECORD).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except Exception:
        _LOGGER.exception("offseason development: record not written")
    try:
        from services.training_history import record_training_session

        record_training_session(reports)
    except Exception:
        _LOGGER.exception("offseason development: training history not written")


def load_development_record(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """The last offseason's record (``{}`` when there is none)."""

    path = (Path(data_dir) if data_dir is not None else get_data_dir()) / DEVELOPMENT_RECORD
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
