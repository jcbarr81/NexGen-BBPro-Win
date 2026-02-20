"""Persist and retrieve spring training development reports."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from playbalance.player_development import TrainingReport
from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "record_training_session",
    "load_player_training_history",
]


def _reports_dir() -> Path:
    return get_data_dir() / "training_reports"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _season_path(season_id: str) -> Path:
    return _reports_dir() / f"{season_id}.json"


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


def record_training_session(
    reports: Sequence[TrainingReport],
    *,
    season_id: str | None = None,
    run_at: str | None = None,
) -> None:
    """Append ``reports`` to the current season's training history."""

    if not reports:
        return

    resolved_season = season_id or _resolve_season_id()
    timestamp = run_at or _utcnow()

    reports_dir = _reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = _season_path(resolved_season)
    payload: Dict[str, object]
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            payload = {}
    else:
        payload = {}

    if payload.get("season_id") and payload["season_id"] != resolved_season:
        payload = {}

    runs: List[Dict[str, object]] = list(payload.get("runs", [])) if isinstance(payload, dict) else []
    runs.append(
        {
            "run_at": timestamp,
            "reports": [asdict(report) for report in reports],
        }
    )

    payload = {"season_id": resolved_season, "runs": runs}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_player_training_history(
    player_id: str,
    *,
    limit: int = 5,
) -> List[Dict[str, object]]:
    """Return recent training sessions for ``player_id`` across seasons."""

    if not player_id:
        return []
    reports_dir = _reports_dir()
    if not reports_dir.exists():
        return []

    entries: List[Dict[str, object]] = []
    for path in sorted(reports_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        season_id = payload.get("season_id") or path.stem
        for run in payload.get("runs", []):
            if not isinstance(run, dict):
                continue
            reports = run.get("reports", [])
            if not isinstance(reports, Iterable):
                continue
            for report in reports:
                if not isinstance(report, dict):
                    continue
                if report.get("player_id") != player_id:
                    continue
                record = dict(report)
                record["season_id"] = season_id
                record["run_at"] = run.get("run_at")
                entries.append(record)
    entries.sort(key=lambda item: str(item.get("run_at") or ""), reverse=True)
    if limit > 0:
        entries = entries[:limit]
    return entries
