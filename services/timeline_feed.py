"""Aggregate timeline feed entries for milestones, awards, and records."""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from playbalance.season_context import CAREER_DATA_DIR, SeasonContext
from services.hall_of_fame import list_inductees
from services.special_events import load_special_events
from utils.path_utils import get_data_dir, resolve_app_path

__all__ = ["build_timeline_feed"]


def build_timeline_feed(*, season_id: str | None = None, limit: int | None = 50) -> List[Dict[str, Any]]:
    ctx = SeasonContext.load()
    current = ctx.ensure_current_season()
    season_id = season_id or str(current.get("season_id") or "").strip()
    league_year = _safe_int(current.get("league_year"), default=date.today().year)
    entries: List[Dict[str, Any]] = []

    events = load_special_events(limit=None)
    if events:
        for event in events:
            if not isinstance(event, dict):
                continue
            if season_id:
                event_season = str(event.get("season_id") or "").strip()
                if event_season and event_season != season_id:
                    continue
            label = str(event.get("label") or event.get("type") or "Milestone")
            detail = str(event.get("detail") or "").strip() or None
            date_val = str(event.get("date") or "").strip()
            entries.append(
                {
                    "date": date_val,
                    "label": label,
                    "detail": detail,
                    "category": event.get("category"),
                    "player_id": event.get("player_id"),
                    "player_name": event.get("player_name"),
                    "team_id": event.get("team_id"),
                    "source": "special_events",
                    "sort_key": _sort_key(date_val, label),
                }
            )

    awards_payload = _load_awards_payload(ctx, season_id)
    if awards_payload:
        awards = awards_payload.get("awards", {}) if isinstance(awards_payload.get("awards"), dict) else {}
        generated_at = str(awards_payload.get("generated_at") or "").strip()
        date_val = generated_at.split("T")[0] if generated_at else ""
        for award_key, info in awards.items():
            if not isinstance(info, dict):
                continue
            player_name = str(info.get("player_name") or info.get("player_id") or "").strip()
            label = _award_label(award_key)
            detail = f"{player_name} won {label}" if player_name else f"{label} awarded"
            entries.append(
                {
                    "date": date_val,
                    "label": f"Award: {label}",
                    "detail": detail,
                    "category": "award",
                    "player_id": info.get("player_id"),
                    "player_name": player_name,
                    "source": "awards",
                    "sort_key": _sort_key(date_val, f"award-{label}"),
                }
            )

    for inductee in list_inductees():
        try:
            inducted_year = _safe_int(inductee.get("inducted_year"))
        except Exception:
            inducted_year = None
        if inducted_year != league_year:
            continue
        player_name = str(inductee.get("player_name") or inductee.get("player_id") or "").strip()
        label = "Hall of Fame Induction"
        detail = f"{player_name} inducted into the Hall of Fame" if player_name else label
        date_val = str(inductee.get("inducted_date") or "").strip()
        entries.append(
            {
                "date": date_val,
                "label": label,
                "detail": detail,
                "category": "hall_of_fame",
                "player_id": inductee.get("player_id"),
                "player_name": player_name,
                "source": "hall_of_fame",
                "sort_key": _sort_key(date_val, f"hof-{player_name}"),
            }
        )

    entries.sort(key=lambda e: e.get("sort_key", ""), reverse=True)
    if limit is not None and limit >= 0:
        entries = entries[:limit]
    return entries


def _load_awards_payload(ctx: SeasonContext, season_id: str | None) -> Dict[str, Any] | None:
    if not season_id:
        return None
    artifacts = _season_artifacts(ctx, season_id)
    path = None
    if artifacts.get("awards"):
        path = _resolve_path(artifacts.get("awards"))
    if path is None:
        candidate = CAREER_DATA_DIR / season_id / "awards.json"
        if candidate.exists():
            path = candidate
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _season_artifacts(ctx: SeasonContext, season_id: str) -> Dict[str, str]:
    for season in ctx.seasons:
        if not isinstance(season, dict):
            continue
        if str(season.get("season_id") or "") != season_id:
            continue
        artifacts = season.get("artifacts")
        if isinstance(artifacts, dict) and artifacts:
            return {str(key): str(value) for key, value in artifacts.items() if value}
    meta_path = get_data_dir() / "careers" / season_id / "metadata.json"
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    meta_artifacts = payload.get("artifacts", {})
    if isinstance(meta_artifacts, dict) and meta_artifacts:
        return {str(key): str(value) for key, value in meta_artifacts.items() if value}
    return {}


def _resolve_path(path_str: str | None) -> Optional[Path]:
    if not path_str:
        return None
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _award_label(key: str) -> str:
    label = str(key or "").strip()
    if not label:
        return "Award"
    return label.replace("_", " ").title()


def _sort_key(date_val: str, label: str) -> str:
    date_token = date_val or "0000-00-00"
    return f"{date_token}|{label}"


def _safe_int(value: Any, *, default: int | None = None) -> int | None:
    try:
        return int(value)
    except Exception:
        return default
