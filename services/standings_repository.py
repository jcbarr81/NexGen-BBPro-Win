from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from services.unified_data_service import get_unified_data_service
from utils.path_utils import resolve_app_path
from utils.standings_utils import normalize_record

_RELATIVE_PATH = Path("data") / "standings.json"
_TOPIC = "standings"


def _resolve_target(base_path: Path | str | None) -> Path:
    if base_path is None:
        return _RELATIVE_PATH
    base = Path(base_path)
    if base.suffix:
        return base
    return base / "standings.json"


def _read_standings(path: Path) -> dict[str, dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            result[str(key)] = value
        else:
            result[str(key)] = {}
    return result


def _derive_from_season_stats(base_path: Path | str | None) -> dict[str, dict[str, Any]]:
    """Best-effort recovery: pull team W/L/RF/RA out of season_stats.json
    when standings.json hasn't been seeded yet (or got reset). The full
    simulator updates the season_stats teams block but historically did
    not write standings.json, so without this fallback the standings
    page reads zeros even after a Sim Day."""

    if base_path is None:
        return {}
    base = Path(base_path)
    candidate = base / "season_stats.json" if not base.suffix else base.parent / "season_stats.json"
    if not candidate.exists():
        return {}
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            stats = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    teams_block = (stats or {}).get("teams") or {}
    if not isinstance(teams_block, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for team_id, raw in teams_block.items():
        if not isinstance(raw, dict):
            continue
        out[str(team_id)] = {
            "wins": int(raw.get("w", 0) or 0),
            "losses": int(raw.get("l", 0) or 0),
            "runs_for": int(raw.get("r", 0) or 0),
            "runs_against": int(raw.get("ra", 0) or 0),
        }
    return out


def load_standings(
    *,
    base_path: Path | str | None = None,
    normalize: bool = True,
) -> dict[str, dict[str, Any]]:
    """Return standings from disk, optionally normalized."""

    service = get_unified_data_service()
    target = _resolve_target(base_path)

    document = service.get_document(target, _read_standings, topic=_TOPIC)
    # Fallback: standings.json is the canonical source, but historically
    # only league_creator / league_rollover wrote to it. The full sim
    # populates the team rollup in ``season_stats.json`` instead, so an
    # empty standings.json means "the sim has run but never persisted
    # standings". Derive on the fly so the standings + dashboard pages
    # show real records without the user having to wait for the next
    # Sim Day to trigger the new persistence path.
    if not document:
        derived = _derive_from_season_stats(base_path)
        if derived:
            document = derived
    if not normalize:
        return document
    return {team_id: normalize_record(data) for team_id, data in document.items()}


def save_standings(
    standings: Mapping[str, Mapping[str, Any]],
    *,
    base_path: Path | str | None = None,
) -> None:
    """Persist *standings* and refresh caches."""

    target = _resolve_target(base_path)
    resolved = resolve_app_path(target)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Dict[str, Any]] = {}
    for key, value in standings.items():
        if isinstance(value, dict):
            payload[str(key)] = value
        else:
            payload[str(key)] = dict(value)

    with resolved.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    service = get_unified_data_service()
    service.update_document(target, payload, topic=_TOPIC)


def invalidate_standings(*, base_path: Path | str | None = None) -> None:
    """Drop cached standings so future loads re-read from storage."""

    service = get_unified_data_service()
    target = _resolve_target(base_path)
    service.invalidate_document(target, topic=_TOPIC)
