from __future__ import annotations

"""Season context helpers for tracking league/year identifiers and archives.

This module centralizes metadata required to manage season rollover flows.
All season-level artifacts (e.g., archived standings, stats, awards) will be
stored under ``data/careers`` with filenames keyed by the season identifier,
which is a slugified league id combined with the league year
(``<league-id>-<year>``).

The context is persisted to ``data/career_index.json`` with a minimal schema:

{
  "version": 1,
  "league": {
    "id": "nexgen",
    "name": "NexGen BBPro",
    "created_at": "2025-10-10T21:04:00Z"
  },
  "current": {
    "season_id": "nexgen-2025",
    "league_year": 2025,
    "sequence": 1,
    "started_on": null,
    "metadata": {},
    "rollover_complete": false
  },
  "seasons": [
    {
      "... archived season metadata ..."
    }
  ]
}

The ``seasons`` list acts as the historical ledger; the ``current`` block
represents the in-flight season.  When a season is archived the current block
is appended to ``seasons`` with an ``archived_on`` timestamp and any artifact
paths, then replaced with the next season descriptor.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import json
import os
import re

from utils.path_utils import get_data_dir

__all__ = [
    "get_career_data_dir",
    "get_career_index_path",
    "CAREER_DATA_DIR",
    "CAREER_INDEX_PATH",
    "SeasonContext",
    "slugify_league_id",
]


def get_career_data_dir() -> Path:
    return get_data_dir() / "careers"


def get_career_index_path() -> Path:
    return get_data_dir() / "career_index.json"


class _DynamicPath:
    """Path-like wrapper that resolves to the active league directory on demand."""

    def __init__(self, resolver):
        self._resolver = resolver

    def _path(self) -> Path:
        return self._resolver()

    def __fspath__(self) -> str:
        return os.fspath(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return repr(self._path())

    def __truediv__(self, key):
        return self._path() / key

    def __getattr__(self, item):
        return getattr(self._path(), item)

    def __eq__(self, other: object) -> bool:
        return self._path() == other


CAREER_DATA_DIR = _DynamicPath(get_career_data_dir)
CAREER_INDEX_PATH = _DynamicPath(get_career_index_path)
_DEFAULT_VERSION = 1


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify_league_id(value: str | None) -> str:
    """Return a filesystem-friendly slug for *value*."""

    if not value:
        return "league"
    value = value.strip().lower()
    # Replace non-alphanumeric characters with hyphen and collapse repeats.
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "league"


def _default_payload() -> Dict[str, Any]:
    return {
        "version": _DEFAULT_VERSION,
        "league": {},
        "current": {},
        "seasons": [],
    }


@dataclass
class SeasonContext:
    """Wrapper for reading/updating ``career_index.json``."""

    data: Dict[str, Any] = field(default_factory=_default_payload)
    path: Path = field(default_factory=get_career_index_path)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str | None = None) -> "SeasonContext":
        resolved = Path(path) if path is not None else get_career_index_path()
        if resolved.exists():
            try:
                payload = json.loads(resolved.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    payload = _default_payload()
            except (OSError, json.JSONDecodeError):
                payload = _default_payload()
        else:
            payload = _default_payload()
        return cls(data=payload, path=resolved)

    # ------------------------------------------------------------------
    # Basic properties
    # ------------------------------------------------------------------
    @property
    def league(self) -> Dict[str, Any]:
        return self.data.setdefault("league", {})

    @property
    def current(self) -> Dict[str, Any]:
        return self.data.setdefault("current", {})

    @property
    def seasons(self) -> list[Dict[str, Any]]:
        return self.data.setdefault("seasons", [])

    @property
    def league_id(self) -> str | None:
        return self.league.get("id")

    @property
    def current_season_id(self) -> str | None:
        return self.current.get("season_id")

    def _career_data_dir(self) -> Path:
        return self.path.parent / "careers"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self) -> None:
        """Persist the current payload to disk."""

        self._career_data_dir().mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)

    # ------------------------------------------------------------------
    # League helpers
    # ------------------------------------------------------------------
    def ensure_league(self, *, name: str | None = None, league_id: str | None = None) -> str:
        """Ensure the league block is populated; return league id."""

        updated = False
        if not self.league:
            lid = slugify_league_id(league_id or name or "league")
            self.league.update(
                {
                    "id": lid,
                    "name": name or lid.upper(),
                    "created_at": _utcnow(),
                }
            )
            updated = True
        else:
            if league_id:
                lid = slugify_league_id(league_id)
                if not self.league.get("id"):
                    self.league["id"] = lid
                    updated = True
            if name and not self.league.get("name"):
                self.league["name"] = name
                updated = True
        if updated:
            self.save()
        return self.league.get("id") or "league"

    # ------------------------------------------------------------------
    # Season helpers
    # ------------------------------------------------------------------
    def ensure_current_season(
        self,
        *,
        league_year: int | None = None,
        started_on: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Populate the current season descriptor if absent or update metadata."""

        lid = self.ensure_league()
        updated = False
        if not self.current:
            year = league_year if league_year is not None else datetime.now().year
            sequence = len(self.seasons) + 1
            self.data["current"] = {
                "season_id": f"{lid}-{year}",
                "league_year": year,
                "sequence": sequence,
                "started_on": started_on,
                "metadata": metadata or {},
                "rollover_complete": False,
                "created_at": _utcnow(),
            }
            updated = True
        else:
            if league_year is not None:
                if self.current.get("league_year") != league_year:
                    self.current["league_year"] = league_year
                    self.current["season_id"] = f"{lid}-{league_year}"
                    updated = True
            if started_on and not self.current.get("started_on"):
                self.current["started_on"] = started_on
                updated = True
            if metadata:
                merged = dict(self.current.get("metadata", {}))
                merged.update(metadata)
                if merged != self.current.get("metadata"):
                    self.current["metadata"] = merged
                    updated = True
            if "rollover_complete" not in self.current:
                self.current["rollover_complete"] = False
                updated = True
            if "sequence" not in self.current:
                self.current["sequence"] = len(self.seasons) + 1
                updated = True
            if "created_at" not in self.current:
                self.current["created_at"] = _utcnow()
                updated = True
        if updated:
            self.save()
        return self.current

    def mark_season_started(self, start_date: str) -> None:
        """Record the first regular season date if not already set."""

        if not start_date:
            return
        current = self.ensure_current_season()
        if not current.get("started_on"):
            current["started_on"] = start_date
            current.setdefault("metadata", {})
            self.save()

    def archive_current_season(
        self,
        *,
        artifacts: Dict[str, str] | None = None,
        ended_on: str | None = None,
        next_league_year: int | None = None,
    ) -> Dict[str, Any]:
        """Move the current season descriptor to the archive and create the next one.

        Parameters
        ----------
        artifacts:
            Mapping of artifact labels to relative file paths.
        ended_on:
            Optional ISO date string indicating when the season concluded.
        next_league_year:
            Explicit league year for the next season. Defaults to incrementing
            the previous season year by one.

        Returns
        -------
        dict
            Descriptor of the new current season.
        """

        if not self.current:
            raise RuntimeError("Cannot archive season; current season is undefined.")

        archived = dict(self.current)
        archived["archived_on"] = _utcnow()
        archived["rollover_complete"] = True
        if ended_on:
            archived["ended_on"] = ended_on
        if artifacts:
            archived["artifacts"] = dict(artifacts)
        self.seasons.append(archived)

        prev_year = archived.get("league_year") or datetime.now().year
        next_year = next_league_year if next_league_year is not None else prev_year + 1
        new_sequence = archived.get("sequence", len(self.seasons)) + 1
        next_descriptor = {
            "season_id": f"{self.ensure_league()}-{next_year}",
            "league_year": next_year,
            "sequence": new_sequence,
            "started_on": None,
            "metadata": {},
            "rollover_complete": False,
            "created_at": _utcnow(),
        }
        self.data["current"] = next_descriptor
        self.save()
        return next_descriptor

    # ------------------------------------------------------------------
    # Artifact directories
    # ------------------------------------------------------------------
    def season_directory(self, season_id: str | None = None) -> Path:
        """Return the base directory for *season_id* (current if omitted)."""

        sid = season_id or self.current_season_id
        if not sid:
            raise RuntimeError("Season identifier unavailable.")
        directory = self._career_data_dir() / sid
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def has_archived_season(self, season_id: str) -> bool:
        """Return True if *season_id* already exists in archive."""

        return any(season.get("season_id") == season_id for season in self.seasons)

    def iter_archived_seasons(self) -> Iterable[Dict[str, Any]]:
        """Yield archived season descriptors in chronological order."""

        return list(self.seasons)
