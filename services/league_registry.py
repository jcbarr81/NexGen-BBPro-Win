"""League registry persistence for multi-league management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, MutableMapping

from utils.path_utils import (
    clear_active_league_id,
    get_active_league_id,
    get_active_league_pointer_path,
    get_data_root,
    get_league_registry_path,
    get_leagues_root,
    set_active_league_id,
)

REGISTRY_VERSION = 1
DEFAULT_MODE = "single_player"
DEFAULT_STATUS = "active"
VALID_MODES = {"single_player", "owner_league"}
VALID_STATUSES = {"active", "archived"}


@dataclass(frozen=True)
class LeagueRecord:
    """Serializable league metadata entry."""

    id: str
    display_name: str
    created_at: str
    last_opened_at: str | None = None
    mode: str = DEFAULT_MODE
    status: str = DEFAULT_STATUS
    version_created: str | None = None
    version_last_opened: str | None = None

    @classmethod
    def from_mapping(cls, payload: Dict[str, Any]) -> "LeagueRecord":
        league_id = _normalize_league_id(payload.get("id"))
        if not league_id:
            raise ValueError("League entry missing id")
        mode = _normalize_mode(payload.get("mode", DEFAULT_MODE))
        status = _normalize_status(payload.get("status", DEFAULT_STATUS))
        display_name = str(payload.get("display_name") or league_id).strip() or league_id
        created_at = _normalize_timestamp(payload.get("created_at")) or _utcnow()
        last_opened = _normalize_timestamp(payload.get("last_opened_at"))
        version_created = _string_or_none(payload.get("version_created"))
        version_last_opened = _string_or_none(payload.get("version_last_opened"))
        return cls(
            id=league_id,
            display_name=display_name,
            created_at=created_at,
            last_opened_at=last_opened,
            mode=mode,
            status=status,
            version_created=version_created,
            version_last_opened=version_last_opened,
        )

    def to_mapping(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "last_opened_at": self.last_opened_at,
            "mode": self.mode,
            "status": self.status,
            "version_created": self.version_created,
            "version_last_opened": self.version_last_opened,
        }


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_league_id(value: Any) -> str:
    if value is None:
        return ""
    candidate = str(value).strip().lower()
    if not candidate:
        return ""
    allowed = []
    for char in candidate:
        if char.isalnum() or char in {"-", "_"}:
            allowed.append(char)
    return "".join(allowed).strip("-_")


def _normalize_mode(value: Any) -> str:
    mode = str(value or DEFAULT_MODE).strip().lower()
    if mode not in VALID_MODES:
        return DEFAULT_MODE
    return mode


def _normalize_status(value: Any) -> str:
    status = str(value or DEFAULT_STATUS).strip().lower()
    if status not in VALID_STATUSES:
        return DEFAULT_STATUS
    return status


def _normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _default_payload() -> Dict[str, Any]:
    return {"version": REGISTRY_VERSION, "leagues": []}


def load_registry(path: Path | None = None) -> Dict[str, Any]:
    registry_path = path if path is not None else get_league_registry_path()
    if not registry_path.exists():
        return _default_payload()
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_payload()
    if not isinstance(payload, dict):
        return _default_payload()
    raw_leagues = payload.get("leagues")
    normalized_leagues: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    if isinstance(raw_leagues, list):
        for raw_entry in raw_leagues:
            if not isinstance(raw_entry, dict):
                continue
            try:
                record = LeagueRecord.from_mapping(raw_entry)
            except ValueError:
                continue
            if record.id in seen_ids:
                continue
            normalized_leagues.append(record.to_mapping())
            seen_ids.add(record.id)
    return {"version": REGISTRY_VERSION, "leagues": normalized_leagues}


def save_registry(payload: MutableMapping[str, Any], path: Path | None = None) -> Dict[str, Any]:
    registry_path = path if path is not None else get_league_registry_path()
    normalized = load_registry(path=registry_path)
    if isinstance(payload, dict):
        raw_leagues = payload.get("leagues")
        if isinstance(raw_leagues, list):
            leagues: List[Dict[str, Any]] = []
            seen_ids: set[str] = set()
            for raw_entry in raw_leagues:
                if not isinstance(raw_entry, dict):
                    continue
                try:
                    record = LeagueRecord.from_mapping(raw_entry)
                except ValueError:
                    continue
                if record.id in seen_ids:
                    continue
                leagues.append(record.to_mapping())
                seen_ids.add(record.id)
            normalized["leagues"] = leagues
    normalized["version"] = REGISTRY_VERSION
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return normalized


def list_leagues() -> List[LeagueRecord]:
    payload = load_registry()
    leagues = payload.get("leagues", [])
    if not isinstance(leagues, list):
        return []
    records: List[LeagueRecord] = []
    for entry in leagues:
        if not isinstance(entry, dict):
            continue
        try:
            records.append(LeagueRecord.from_mapping(entry))
        except ValueError:
            continue
    return records


def get_league(league_id: str) -> LeagueRecord | None:
    normalized_id = _normalize_league_id(league_id)
    if not normalized_id:
        return None
    for record in list_leagues():
        if record.id == normalized_id:
            return record
    return None


def register_league(
    league_id: str,
    *,
    display_name: str | None = None,
    mode: str = DEFAULT_MODE,
    status: str = DEFAULT_STATUS,
    version_created: str | None = None,
    set_active_if_first: bool = True,
) -> LeagueRecord:
    normalized_id = _normalize_league_id(league_id)
    if not normalized_id:
        raise ValueError("league_id is required")
    payload = load_registry()
    leagues = payload.get("leagues")
    if not isinstance(leagues, list):
        leagues = []
        payload["leagues"] = leagues
    if any(str(entry.get("id")) == normalized_id for entry in leagues if isinstance(entry, dict)):
        raise ValueError(f"League already exists: {normalized_id}")

    record = LeagueRecord(
        id=normalized_id,
        display_name=(display_name or normalized_id).strip() or normalized_id,
        created_at=_utcnow(),
        last_opened_at=None,
        mode=_normalize_mode(mode),
        status=_normalize_status(status),
        version_created=_string_or_none(version_created),
        version_last_opened=None,
    )
    leagues.append(record.to_mapping())
    save_registry(payload)

    if set_active_if_first and len(leagues) == 1:
        set_active_league(normalized_id, ensure_data_dir=True)
    return record


def update_league(
    league_id: str,
    *,
    display_name: str | None = None,
    mode: str | None = None,
    status: str | None = None,
    version_last_opened: str | None = None,
) -> LeagueRecord:
    normalized_id = _normalize_league_id(league_id)
    if not normalized_id:
        raise ValueError("league_id is required")
    payload = load_registry()
    leagues = payload.get("leagues")
    if not isinstance(leagues, list):
        raise ValueError(f"League not found: {league_id}")

    updated_entry: Dict[str, Any] | None = None
    for entry in leagues:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id", "")).strip().lower() != normalized_id:
            continue
        if display_name is not None:
            clean_name = display_name.strip()
            if clean_name:
                entry["display_name"] = clean_name
        if mode is not None:
            entry["mode"] = _normalize_mode(mode)
        if status is not None:
            entry["status"] = _normalize_status(status)
        if version_last_opened is not None:
            entry["version_last_opened"] = _string_or_none(version_last_opened)
        updated_entry = entry
        break

    if updated_entry is None:
        raise ValueError(f"League not found: {league_id}")
    save_registry(payload)
    return LeagueRecord.from_mapping(updated_entry)


def remove_league(league_id: str) -> bool:
    normalized_id = _normalize_league_id(league_id)
    if not normalized_id:
        return False
    payload = load_registry()
    leagues = payload.get("leagues")
    if not isinstance(leagues, list):
        return False

    before = len(leagues)
    leagues[:] = [
        entry
        for entry in leagues
        if not isinstance(entry, dict)
        or str(entry.get("id", "")).strip().lower() != normalized_id
    ]
    changed = len(leagues) != before
    if not changed:
        return False

    save_registry(payload)
    active_id = get_active_league_id()
    if active_id == normalized_id:
        for record in list_leagues():
            if record.status != "archived":
                set_active_league(record.id, ensure_data_dir=False)
                break
        else:
            clear_active_league_id()
    return True


def set_active_league(
    league_id: str,
    *,
    ensure_data_dir: bool = True,
    version_last_opened: str | None = None,
) -> LeagueRecord:
    record = get_league(league_id)
    if record is None:
        raise ValueError(f"League not found: {league_id}")
    set_active_league_id(record.id)
    update_league(
        record.id,
        version_last_opened=version_last_opened,
    )
    payload = load_registry()
    leagues = payload.get("leagues")
    if isinstance(leagues, list):
        for entry in leagues:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("id", "")).strip().lower() == record.id:
                entry["last_opened_at"] = _utcnow()
                break
        save_registry(payload)
    if ensure_data_dir:
        get_league_data_dir(record.id, create=True)
    updated = get_league(record.id)
    if updated is None:
        raise ValueError(f"League not found: {record.id}")
    return updated


def get_active_league() -> LeagueRecord | None:
    active_id = get_active_league_id()
    if not active_id:
        return None
    return get_league(active_id)


def get_league_data_dir(league_id: str, *, create: bool = False) -> Path:
    normalized_id = _normalize_league_id(league_id)
    if not normalized_id:
        raise ValueError("league_id is required")
    data_root = get_data_root()
    data_dir = get_leagues_root(data_root=data_root) / normalized_id / "data"
    if create:
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def ensure_registry_exists() -> Dict[str, Any]:
    path = get_league_registry_path()
    payload = load_registry(path=path)
    if not path.exists():
        return save_registry(payload, path=path)
    return payload


def get_active_pointer_path() -> Path:
    return get_active_league_pointer_path()


__all__ = [
    "DEFAULT_MODE",
    "DEFAULT_STATUS",
    "LeagueRecord",
    "REGISTRY_VERSION",
    "ensure_registry_exists",
    "get_active_league",
    "get_active_pointer_path",
    "get_league",
    "get_league_data_dir",
    "list_leagues",
    "load_registry",
    "register_league",
    "remove_league",
    "save_registry",
    "set_active_league",
    "update_league",
]
