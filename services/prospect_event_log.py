"""Event persistence for promotion/option/protection lifecycle actions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from playbalance.season_context import SeasonContext
from services.unified_data_service import get_unified_data_service
from utils.path_utils import get_data_dir

SCHEMA_VERSION = 1
EVENTS_DIRNAME = "prospect_events"
EVENTS_TOPIC = "prospect_events"

EVENT_TYPE_PROMOTION = "promotion"
EVENT_TYPE_DEMOTION = "demotion"
EVENT_TYPE_OPTION_DECISION = "option_decision"
EVENT_TYPE_PROTECTION_CHANGE = "protection_change"
_VALID_EVENT_TYPES = {
    EVENT_TYPE_PROMOTION,
    EVENT_TYPE_DEMOTION,
    EVENT_TYPE_OPTION_DECISION,
    EVENT_TYPE_PROTECTION_CHANGE,
}

TRACKED_ROSTER_LEVELS: tuple[str, ...] = ("act", "aaa", "low")
ROSTER_LEVEL_RANK = {"low": 1, "aaa": 2, "act": 3}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_level(value: object) -> str | None:
    token = str(value or "").strip().lower()
    if token in {"act", "active", "mlb", "major"}:
        return "act"
    if token in {"aaa", "triple-a", "triplea"}:
        return "aaa"
    if token in {"low", "a", "single-a", "singlea"}:
        return "low"
    return None


def _normalize_event_type(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in _VALID_EVENT_TYPES:
        return token
    return "unknown"


def _resolve_season_id(
    season_id: str | None = None,
    *,
    data_dir: Path | str | None = None,
) -> str:
    if season_id:
        return str(season_id).strip()
    try:
        if data_dir is None:
            ctx = SeasonContext.load()
        else:
            ctx = SeasonContext.load(path=Path(data_dir) / "career_index.json")
        if ctx.current_season_id:
            return str(ctx.current_season_id).strip()
        current = ctx.ensure_current_season()
        resolved = str(current.get("season_id") or "").strip()
        if resolved:
            return resolved
    except Exception:
        pass
    return f"season-{datetime.now(timezone.utc).year}"


def _events_dir(*, data_dir: Path | str | None = None) -> Path:
    root = get_data_dir() if data_dir is None else Path(data_dir)
    return root / EVENTS_DIRNAME


def events_path_for_season(
    season_id: str | None = None,
    *,
    data_dir: Path | str | None = None,
) -> Path:
    resolved_season = _resolve_season_id(season_id, data_dir=data_dir)
    return _events_dir(data_dir=data_dir) / f"{resolved_season}.jsonl"


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def append_prospect_event(
    event: Mapping[str, object],
    *,
    season_id: str | None = None,
    data_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Append one normalized prospect lifecycle event."""

    resolved_season = _resolve_season_id(season_id, data_dir=data_dir)
    details = event.get("details")
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": str(event.get("timestamp_utc") or _now_utc_iso()),
        "season_id": resolved_season,
        "event_type": _normalize_event_type(event.get("event_type")),
        "team_id": str(event.get("team_id") or "").strip(),
        "player_id": str(event.get("player_id") or "").strip(),
        "player_name": str(event.get("player_name") or "").strip(),
        "actor": str(event.get("actor") or "system").strip() or "system",
        "trigger": str(event.get("trigger") or "").strip(),
        "details": dict(details) if isinstance(details, Mapping) else {},
    }

    from_level = _normalize_level(event.get("from_level"))
    to_level = _normalize_level(event.get("to_level"))
    if from_level:
        record["from_level"] = from_level
    if to_level:
        record["to_level"] = to_level

    path = events_path_for_season(resolved_season, data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    service = get_unified_data_service()
    try:
        cached = service.get_document(path, _read_events, topic=EVENTS_TOPIC)
    except Exception:
        service.invalidate_document(path, topic=EVENTS_TOPIC)
        return record
    if not cached or cached[-1] != record:
        cached.append(dict(record))
    service.update_document(path, cached, topic=EVENTS_TOPIC)
    return record


def load_prospect_events(
    *,
    season_id: str | None = None,
    team_id: str | None = None,
    player_id: str | None = None,
    event_types: Sequence[str] | None = None,
    limit: int | None = None,
    data_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return persisted prospect events with optional filters."""

    events_dir = _events_dir(data_dir=data_dir)
    if season_id:
        paths = [events_path_for_season(season_id, data_dir=data_dir)]
    elif events_dir.exists():
        paths = sorted(events_dir.glob("*.jsonl"), reverse=True)
    else:
        paths = []

    service = get_unified_data_service()
    records: list[dict[str, Any]] = []
    for path in paths:
        rows = service.get_document(path, _read_events, topic=EVENTS_TOPIC)
        records.extend(rows)

    if team_id:
        wanted_team = str(team_id).strip()
        records = [row for row in records if str(row.get("team_id") or "").strip() == wanted_team]
    if player_id:
        wanted_player = str(player_id).strip()
        records = [row for row in records if str(row.get("player_id") or "").strip() == wanted_player]
    if event_types:
        wanted_types = {
            _normalize_event_type(value)
            for value in event_types
            if str(value or "").strip()
        }
        records = [row for row in records if _normalize_event_type(row.get("event_type")) in wanted_types]

    records.sort(key=lambda row: str(row.get("timestamp_utc") or ""), reverse=True)
    if limit is not None and limit >= 0:
        records = records[:limit]
    return records


def roster_level_map(
    roster: object,
    *,
    levels: Sequence[str] = TRACKED_ROSTER_LEVELS,
) -> dict[str, str]:
    """Build a ``player_id -> level`` map for tracked roster levels."""

    mapping: dict[str, str] = {}
    for raw_level in levels:
        level = _normalize_level(raw_level)
        if not level:
            continue
        for raw_player_id in getattr(roster, level, []) or []:
            player_id = str(raw_player_id or "").strip()
            if player_id:
                mapping[player_id] = level
    return mapping


def record_roster_level_movements(
    before_levels: Mapping[str, str],
    after_levels: Mapping[str, str],
    *,
    team_id: str,
    player_names: Mapping[str, str] | None = None,
    actor: str = "system",
    trigger: str = "",
    details: Mapping[str, object] | None = None,
    season_id: str | None = None,
    data_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Persist promotion/demotion events inferred from roster level changes."""

    names = player_names if isinstance(player_names, Mapping) else {}
    base_details = dict(details or {})
    events: list[dict[str, Any]] = []

    player_ids = sorted(
        {
            str(player_id or "").strip()
            for player_id in list(before_levels.keys()) + list(after_levels.keys())
            if str(player_id or "").strip()
        }
    )
    for player_id in player_ids:
        before_level = _normalize_level(before_levels.get(player_id))
        after_level = _normalize_level(after_levels.get(player_id))
        if not before_level or not after_level or before_level == after_level:
            continue

        before_rank = ROSTER_LEVEL_RANK.get(before_level, 0)
        after_rank = ROSTER_LEVEL_RANK.get(after_level, 0)
        if before_rank == after_rank:
            continue
        event_type = (
            EVENT_TYPE_PROMOTION
            if after_rank > before_rank
            else EVENT_TYPE_DEMOTION
        )

        event = append_prospect_event(
            {
                "event_type": event_type,
                "team_id": str(team_id or "").strip(),
                "player_id": player_id,
                "player_name": str(names.get(player_id) or "").strip(),
                "actor": actor,
                "trigger": trigger,
                "from_level": before_level,
                "to_level": after_level,
                "details": dict(base_details),
            },
            season_id=season_id,
            data_dir=data_dir,
        )
        events.append(event)
    return events


def record_option_decision_event(
    *,
    team_id: str,
    player_id: str,
    decision: str,
    option_type: str | None = None,
    option_index: int | None = None,
    player_name: str | None = None,
    actor: str = "system",
    trigger: str = "",
    details: Mapping[str, object] | None = None,
    season_id: str | None = None,
    data_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Persist a contract option decision event."""

    payload_details = dict(details or {})
    payload_details["decision"] = str(decision or "").strip().lower() or "pending"
    if option_type:
        payload_details["option_type"] = str(option_type).strip().lower()
    if option_index is not None:
        payload_details["option_index"] = int(option_index)

    return append_prospect_event(
        {
            "event_type": EVENT_TYPE_OPTION_DECISION,
            "team_id": str(team_id or "").strip(),
            "player_id": str(player_id or "").strip(),
            "player_name": str(player_name or "").strip(),
            "actor": actor,
            "trigger": trigger,
            "details": payload_details,
        },
        season_id=season_id,
        data_dir=data_dir,
    )


def record_protection_event(
    *,
    team_id: str,
    player_id: str,
    status: str,
    player_name: str | None = None,
    actor: str = "system",
    trigger: str = "",
    details: Mapping[str, object] | None = None,
    season_id: str | None = None,
    data_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Persist a prospect protection-status event."""

    payload_details = dict(details or {})
    payload_details["status"] = str(status or "").strip().lower()
    return append_prospect_event(
        {
            "event_type": EVENT_TYPE_PROTECTION_CHANGE,
            "team_id": str(team_id or "").strip(),
            "player_id": str(player_id or "").strip(),
            "player_name": str(player_name or "").strip(),
            "actor": actor,
            "trigger": trigger,
            "details": payload_details,
        },
        season_id=season_id,
        data_dir=data_dir,
    )


def clear_prospect_events(
    *,
    season_id: str | None = None,
    data_dir: Path | str | None = None,
) -> None:
    """Delete persisted prospect event logs for one season or all seasons."""

    if season_id:
        paths = [events_path_for_season(season_id, data_dir=data_dir)]
    else:
        root = _events_dir(data_dir=data_dir)
        paths = list(root.glob("*.jsonl")) if root.exists() else []
    service = get_unified_data_service()
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            continue
        service.update_document(path, [], topic=EVENTS_TOPIC)


__all__ = [
    "SCHEMA_VERSION",
    "EVENT_TYPE_PROMOTION",
    "EVENT_TYPE_DEMOTION",
    "EVENT_TYPE_OPTION_DECISION",
    "EVENT_TYPE_PROTECTION_CHANGE",
    "TRACKED_ROSTER_LEVELS",
    "ROSTER_LEVEL_RANK",
    "events_path_for_season",
    "append_prospect_event",
    "load_prospect_events",
    "roster_level_map",
    "record_roster_level_movements",
    "record_option_decision_event",
    "record_protection_event",
    "clear_prospect_events",
]
