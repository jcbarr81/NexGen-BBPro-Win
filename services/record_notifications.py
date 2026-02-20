"""Record book change detection and notification helpers."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.record_book import league_record_book
from services.special_events import record_special_events
from utils.news_logger import log_news_event
from utils.path_utils import ActivePath, get_data_dir

RECORD_SNAPSHOT_PATH = ActivePath(lambda: get_data_dir() / "record_book_snapshot.json")
RECORD_PENDING_PATH = ActivePath(lambda: get_data_dir() / "record_notifications_pending.json")
_VERSION = 1


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_record_snapshot(path: Path | None = None) -> Dict[str, Any]:
    target = path or RECORD_SNAPSHOT_PATH
    if not target.exists():
        return {"version": _VERSION, "records": {}}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": _VERSION, "records": {}}
    if not isinstance(payload, dict):
        return {"version": _VERSION, "records": {}}
    records = payload.get("records", {})
    if not isinstance(records, dict):
        records = {}
    payload["records"] = records
    payload.setdefault("version", _VERSION)
    return payload


def save_record_snapshot(records: Dict[str, Any], path: Path | None = None) -> None:
    target = path or RECORD_SNAPSHOT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _VERSION,
        "records": records,
        "updated_at": _now_iso(),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def update_record_notifications(*, ended_on: str | None = None) -> Dict[str, Any]:
    previous = load_record_snapshot()
    old_records = previous.get("records", {})
    book = league_record_book()
    new_records = _build_record_snapshot(book)

    if not old_records:
        save_record_snapshot(new_records)
        return {"events": [], "records": len(new_records)}

    events = _detect_record_changes(old_records, new_records, ended_on=ended_on)
    if events:
        record_special_events(events)
        _write_pending_notifications(events)
        for event in events:
            detail = str(event.get("detail") or event.get("label") or "Record updated")
            team_id = event.get("team_id")
            try:
                log_news_event(detail, category="record", team_id=team_id)
            except Exception:
                pass
    else:
        _clear_pending_notifications()

    save_record_snapshot(new_records)
    return {"events": events, "records": len(new_records)}


def consume_record_notifications() -> List[Dict[str, Any]]:
    payload = _load_pending_notifications()
    events = payload.get("events", []) if isinstance(payload, dict) else []
    if not isinstance(events, list):
        events = []
    _clear_pending_notifications()
    return [event for event in events if isinstance(event, dict)]


def _build_record_snapshot(book: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    for section in book.values():
        for entry in section:
            if not isinstance(entry, dict):
                continue
            record_id = _record_id(entry)
            holders = entry.get("holders", [])
            if not isinstance(holders, list):
                holders = []
            snapshot[record_id] = {
                "label": entry.get("label", ""),
                "stat_key": entry.get("stat_key", ""),
                "category": entry.get("category", ""),
                "scope": entry.get("scope", ""),
                "value": entry.get("value", 0),
                "value_text": entry.get("value_text", ""),
                "holders": [_normalize_holder(holder) for holder in holders],
            }
    return snapshot


def _load_pending_notifications() -> Dict[str, Any]:
    if not RECORD_PENDING_PATH.exists():
        return {"version": _VERSION, "events": []}
    try:
        payload = json.loads(RECORD_PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": _VERSION, "events": []}
    if not isinstance(payload, dict):
        return {"version": _VERSION, "events": []}
    if not isinstance(payload.get("events"), list):
        payload["events"] = []
    return payload


def _write_pending_notifications(events: List[Dict[str, Any]]) -> None:
    RECORD_PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _VERSION,
        "events": events,
        "updated_at": _now_iso(),
    }
    RECORD_PENDING_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clear_pending_notifications() -> None:
    try:
        if RECORD_PENDING_PATH.exists():
            RECORD_PENDING_PATH.unlink()
    except OSError:
        pass


def _detect_record_changes(
    old_records: Dict[str, Any],
    new_records: Dict[str, Any],
    *,
    ended_on: str | None = None,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for record_id, new_entry in new_records.items():
        old_entry = old_records.get(record_id)
        if not isinstance(new_entry, dict) or not isinstance(old_entry, dict):
            continue
        new_value = _safe_float(new_entry.get("value"))
        old_value = _safe_float(old_entry.get("value"))
        value_changed = abs(new_value - old_value) > 1e-6

        new_holders = new_entry.get("holders", []) if isinstance(new_entry.get("holders"), list) else []
        old_holders = old_entry.get("holders", []) if isinstance(old_entry.get("holders"), list) else []
        new_ids = {h.get("holder_id") for h in new_holders if h.get("holder_id")}
        old_ids = {h.get("holder_id") for h in old_holders if h.get("holder_id")}
        holders_changed = new_ids != old_ids

        if not (value_changed or holders_changed):
            continue

        if holders_changed:
            targets = [h for h in new_holders if h.get("holder_id") not in old_ids]
            if not targets:
                targets = list(new_holders)
        else:
            targets = list(new_holders)

        for holder in targets:
            events.append(_record_event(new_entry, holder, ended_on))

    return events


def _record_event(entry: Dict[str, Any], holder: Dict[str, Any], ended_on: str | None) -> Dict[str, Any]:
    label = str(entry.get("label") or "Record")
    value_text = str(entry.get("value_text") or entry.get("value") or "")
    name = str(holder.get("name") or holder.get("player_id") or holder.get("team_id") or "Unknown")
    season_label = str(holder.get("season_label") or "").strip()
    detail = f"{name} set a new {label} record ({value_text})"
    if season_label:
        detail += f" in {season_label}"
    event = {
        "type": "record",
        "label": f"Record Broken: {label}",
        "category": "record",
        "stat_key": entry.get("stat_key"),
        "value": entry.get("value"),
        "scope": entry.get("scope"),
        "detail": detail,
    }
    if ended_on:
        event["date"] = ended_on
    player_id = holder.get("player_id")
    team_id = holder.get("team_id")
    if player_id:
        event["player_id"] = player_id
        event["player_name"] = name
    if team_id:
        event["team_id"] = team_id
    return event


def _record_id(entry: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(entry.get("category", "")),
            str(entry.get("scope", "")),
            str(entry.get("stat_key", "")),
            str(entry.get("label", "")),
        ]
    )


def _normalize_holder(holder: Dict[str, Any]) -> Dict[str, Any]:
    pid = holder.get("player_id")
    tid = holder.get("team_id")
    if pid:
        holder_id = f"player:{pid}"
    elif tid:
        holder_id = f"team:{tid}"
    else:
        holder_id = "unknown"
    return {
        "holder_id": holder_id,
        "player_id": pid,
        "team_id": tid,
        "name": holder.get("name") or holder.get("team_name") or pid or tid or "Unknown",
        "season_label": holder.get("season_label") or "",
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


__all__ = [
    "load_record_snapshot",
    "save_record_snapshot",
    "consume_record_notifications",
    "update_record_notifications",
]
