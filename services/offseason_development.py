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
know is lost), only rating and potential cells change, the player ids are
checked, and the write is atomic (``utils.atomic_write``), in the file's
own encoding and line ending. Immediately before the new file replaces the
old one, the old one is read again and must still hold exactly the rows
that were developed; if anyone wrote it meanwhile (an injury, a signing)
nothing is replaced and the step is redone on the new file. Where the
build has the players-file lock (``utils.players_file_lock``, 8.0.0) it
is held throughout. A subset is never written (``save_players`` REPLACES
the file; ``docs/future_work.md``). Retired players are not developed, and
a season is never developed twice (``development_last.json``).

Each club's training focus (``services.training_settings``) shares out its
players' growth, and its budgets (``services.finance_budget_effects``) speed
growth and slow decline. The year's changes are recorded as the season's
training history (``services.training_history``, what the player page
shows) and in ``development_last.json``, from which the spring training camp
reports them (``playbalance.training_camp``).
"""

from __future__ import annotations

import copy
import csv
import io
import json
import locale
import logging
from contextlib import contextmanager
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


def _encoding() -> str:
    """The encoding the product's players loader and writer use: neither
    names one (``utils.player_loader``, ``utils.player_writer``), so both
    use the platform's (UTF-8 on Cloud Run, cp1252 on a Windows desktop).
    Named here so a read and the write that follows always agree."""

    return locale.getpreferredencoding(False)


def _read(path: Path) -> tuple[List[str], List[Dict[str, str]], str]:
    """(fields, rows, line ending) of ``players.csv``, read raw: no model
    round trip, and the file's own line ending (``save_players`` writes
    CRLF) is kept for the write."""

    with path.open("r", encoding=_encoding(), newline="") as handle:
        text = handle.read()
    first = text[: text.find("\n") + 1]
    newline = "\r\n" if first.endswith("\r\n") else "\n"
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), list(reader), newline


def _write(
    path: Path,
    fields: List[str],
    rows: List[Dict[str, str]],
    newline: str,
    expected: List[Dict[str, str]],
) -> None:
    """Write ``rows`` atomically, unless ``players.csv`` no longer holds
    exactly ``expected`` (the rows as read): the check is made after the
    new file is written and immediately before it replaces the old one, so
    a write by anyone else in between (an injury, a signing) is never
    overwritten; :class:`_FileChanged` is raised and the file is left as
    it is."""

    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(path, newline="", encoding=_encoding()) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator=newline)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        if _read(path)[1] != expected:
            raise _FileChanged(f"{path} changed while it was being developed")


class _FileChanged(OffseasonDevelopmentError):
    """``players.csv`` was written by someone else during development."""


@contextmanager
def _players_lock(path: Path):
    """The league's players-file lock, where this build has one
    (``utils.players_file_lock``, added with the 8.0.0 switch); otherwise
    nothing, and :func:`_write`'s full-row check is the guard."""

    try:
        from utils.players_file_lock import players_file_lock  # type: ignore
    except ImportError:
        yield
        return
    with players_file_lock(path):
        yield


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
    attempts: int = 3,
) -> Optional[Dict[str, Any]]:
    """Develop every scale 2 player in the league's ``players.csv``.

    ``season_year`` is the coming season (it seeds the noise, so a repeated
    rollover gives the same result). Ages are taken on ``as_of`` (default:
    the league's sim date, as retirements take them). Retired players
    (``retired_players.json``) are not developed.

    Returns ``None`` when the league has no scale 2 player (nothing read
    beyond the header, nothing written); a summary with ``"skipped"`` when
    this season was already developed (``development_last.json``), so a
    repeated rollover never develops twice; else a summary for the rollover
    artifacts. If the file is written by someone else meanwhile, the whole
    step is redone on the new file, up to ``attempts`` times. Raises
    :class:`OffseasonDevelopmentError` rather than write anything doubtful;
    the file is then as it was.
    """

    resolved = Path(data_dir) if data_dir is not None else get_data_dir()
    path = resolved / "players.csv"
    if not path.exists():
        return None
    with path.open("r", encoding=_encoding(), newline="") as handle:
        header = next(csv.reader(handle), [])
    if RATING_SCALE_FIELD not in header:
        return None
    season = season_year if season_year is not None else (as_of or date.today()).year
    done = load_development_record(resolved).get("season")
    if done is not None and str(done) == str(season):
        _LOGGER.info(
            "offseason development %s: season %s already developed; skipped",
            path, season,
        )
        return {"season": season, "skipped": "already developed"}

    last: Optional[Exception] = None
    for _ in range(max(1, attempts)):
        try:
            with _players_lock(path):
                outcome = _develop_file(
                    path, resolved, season=season, league_id=league_id,
                    as_of=as_of, params=params,
                )
        except _FileChanged as exc:
            last = exc
            _LOGGER.warning("offseason development: %s; developing again", exc)
            continue
        if outcome is None:
            return None
        summary, results, rows = outcome
        _mark_developed(resolved, season, results)
        if record:
            _record_history(results, rows)
        _LOGGER.info("offseason development %s: %s", path, summary)
        return summary
    raise OffseasonDevelopmentError(
        f"{path} kept changing while it was being developed ({last}); not written"
    )


def _develop_file(
    path: Path,
    data_dir: Path,
    *,
    season: int,
    league_id: Optional[str],
    as_of: Optional[date],
    params: DevelopmentParams,
):
    fields, rows, newline = _read(path)
    original = copy.deepcopy(rows)
    retired = _retired_ids(data_dir)
    targets = [
        row for row in rows
        if is_developed(row) and str(row.get("player_id", "") or "") not in retired
    ]
    if not any(is_developed(row) for row in rows):
        return None

    team_lookup = _team_lookup(data_dir)
    weights = _weights(team_lookup)
    development, intensity = _budgets(team_lookup, data_dir, league_id)

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

    if [row.get("player_id", "") for row in rows] != [
        row.get("player_id", "") for row in original
    ]:
        raise OffseasonDevelopmentError("the player ids changed while developing")
    if any(r.changes for r in results):
        _write(path, fields, rows, newline, original)
        _clear_player_caches()
    summary = {
        "season": season,
        **summarize(results),
        "skipped": skipped,
        "retired_not_developed": sum(
            1 for row in rows
            if is_developed(row) and str(row.get("player_id", "") or "") in retired
        ),
    }
    return summary, results, rows


def _retired_ids(data_dir: Path) -> set:
    try:
        from services.player_retirement import load_retirees

        return set(load_retirees(data_dir))
    except Exception:
        _LOGGER.warning("offseason development: retirees unreadable", exc_info=True)
        return set()


def _clear_player_caches() -> None:
    try:
        from utils.player_loader import load_players_from_csv

        load_players_from_csv.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def _reports(results: List[DevelopmentResult], rows: List[Dict[str, str]]):
    from playbalance.player_development import TrainingReport, track_label

    names = {
        str(row.get("player_id", "")): f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        for row in rows
    }
    return [
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


def _mark_developed(data_dir: Path, season: int, results: List[DevelopmentResult]) -> None:
    """``development_last.json``: the season developed (what stops a second
    run) and each player's changes (what spring camp reports)."""

    from playbalance.player_development import track_label

    payload = {
        "season": season,
        "players": {
            r.player_id: {
                "focus": track_label(r.focus) if r.focus else "Veteran upkeep",
                "changes": dict(r.changes),
            }
            for r in results
            if r.changes
        },
    }
    (data_dir / DEVELOPMENT_RECORD).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _record_history(results: List[DevelopmentResult], rows: List[Dict[str, str]]) -> None:
    """The season's training history (the player page). Never blocks the
    rollover: the ratings are already written."""

    try:
        from services.training_history import record_training_session

        record_training_session(_reports(results, rows))
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
