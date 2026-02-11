"""Persist and retrieve per-season injury history for player profiles."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List, Mapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "record_injury_event",
    "load_player_injury_history",
]

_REPORTS_DIR = get_data_dir() / "injury_reports"


def _season_path(season_id: str) -> Path:
    return _REPORTS_DIR / f"{season_id}.json"


def _resolve_season_id() -> str:
    try:
        ctx = SeasonContext.load()
        season_id = ctx.current_season_id
        if season_id:
            return season_id
        current = ctx.ensure_current_season()
        return current.get("season_id") or "season"
    except Exception:
        year = datetime.now().year
        return f"season-{year}"


def record_injury_event(
    event: Mapping[str, object],
    *,
    season_id: str | None = None,
) -> None:
    """Append an injury record for the current season."""

    if not event:
        return
    player_id = str(event.get("player_id") or "").strip()
    if not player_id:
        return

    resolved_season = season_id or _resolve_season_id()
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _season_path(resolved_season)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            payload = {}
    else:
        payload = {}

    if payload.get("season_id") and payload["season_id"] != resolved_season:
        payload = {}

    events: List[Dict[str, object]] = (
        list(payload.get("events", [])) if isinstance(payload, dict) else []
    )
    record = {
        "date": str(event.get("date") or event.get("game_date") or "").strip(),
        "player_id": player_id,
        "team_id": str(event.get("team_id") or "").strip(),
        "description": str(event.get("description") or "Injury").strip(),
        "trigger": str(event.get("trigger") or "").strip(),
        "severity": str(event.get("severity") or "").strip(),
        "days": int(event.get("days") or 0),
        "dl_tier": str(event.get("dl_tier") or "").strip(),
    }
    events.append(record)

    payload = {"season_id": resolved_season, "events": events}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_player_injury_history(
    player_id: str,
    *,
    limit: int = 10,
) -> List[Dict[str, object]]:
    """Return recent injury events for ``player_id`` across seasons."""

    if not player_id:
        return []
    if not _REPORTS_DIR.exists():
        return []

    entries: List[Dict[str, object]] = []
    for path in sorted(_REPORTS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        season_id = payload.get("season_id") or path.stem
        for event in payload.get("events", []):
            if not isinstance(event, dict):
                continue
            if event.get("player_id") != player_id:
                continue
            record = dict(event)
            record["season_id"] = season_id
            entries.append(record)

    entries.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    if limit > 0:
        entries = entries[:limit]
    return entries
