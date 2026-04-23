"""League lifecycle operations for multi-league management."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable

from playbalance.season_context import slugify_league_id
from services import league_registry
from utils import path_utils
from utils.path_utils import get_data_root, get_leagues_root


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_league_id(league_id: str | None, display_name: str | None = None) -> str:
    candidate = league_id or display_name or ""
    if not str(candidate).strip():
        raise ValueError("A valid league ID or display name is required.")
    resolved = slugify_league_id(candidate)
    if not resolved:
        raise ValueError("A valid league ID or display name is required.")
    return resolved


def _league_dir(league_id: str) -> Path:
    return get_leagues_root(data_root=get_data_root()) / league_id


def _league_data_dir(league_id: str, *, create: bool = False) -> Path:
    return league_registry.get_league_data_dir(league_id, create=create)


def _write_metadata(league_id: str, display_name: str) -> None:
    metadata_path = _league_dir(league_id) / "metadata.json"
    payload: Dict[str, Any]
    if metadata_path.exists():
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            payload = raw if isinstance(raw, dict) else {}
        except Exception:
            payload = {}
    else:
        payload = {}
    payload.update(
        {
            "id": league_id,
            "display_name": display_name,
            "updated_at": _utcnow(),
        }
    )
    payload.setdefault("created_at", _utcnow())
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_data_tree(source_data_dir: Path, target_data_dir: Path, *, overwrite: bool) -> None:
    if not source_data_dir.exists():
        raise ValueError(f"Source league data does not exist: {source_data_dir}")
    target_data_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_data_dir.exists():
        if not overwrite:
            raise ValueError(
                f"Target league data already exists: {target_data_dir}. "
                "Set overwrite=True to replace it."
            )
        _clear_directory(target_data_dir)
    else:
        target_data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_data_dir, target_data_dir, dirs_exist_ok=True)


def _rewrite_career_index(
    target_data_dir: Path,
    *,
    new_league_id: str,
    new_display_name: str,
) -> None:
    path = target_data_dir / "career_index.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    league = payload.get("league")
    if not isinstance(league, dict):
        league = {}
        payload["league"] = league
    league["id"] = new_league_id
    league["name"] = new_display_name

    def _retag(entry: Dict[str, Any]) -> None:
        year = entry.get("league_year")
        if isinstance(year, int):
            entry["season_id"] = f"{new_league_id}-{year}"

    current = payload.get("current")
    if isinstance(current, dict):
        _retag(current)
    seasons = payload.get("seasons")
    if isinstance(seasons, list):
        for season in seasons:
            if isinstance(season, dict):
                _retag(season)

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _rewrite_trade_settings(
    target_data_dir: Path,
    *,
    source_league_id: str,
    target_league_id: str,
) -> None:
    path = target_data_dir / "trade_settings.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    leagues = payload.get("leagues")
    if not isinstance(leagues, dict):
        return
    if target_league_id in leagues:
        return
    if source_league_id in leagues:
        leagues[target_league_id] = leagues[source_league_id]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_league_entry(
    *,
    display_name: str,
    league_id: str | None = None,
    mode: str = league_registry.DEFAULT_MODE,
    template_league_id: str | None = None,
    overwrite: bool = False,
    activate: bool = False,
) -> league_registry.LeagueRecord:
    """Create/register a league entry and optionally seed from a template league."""

    resolved_id = _resolve_league_id(league_id, display_name)
    resolved_name = display_name.strip() or resolved_id
    existing = league_registry.get_league(resolved_id)
    if existing is not None and not overwrite:
        raise ValueError(f"League already exists: {resolved_id}")

    target_data_dir = _league_data_dir(resolved_id, create=True)
    source_id = _resolve_league_id(template_league_id) if template_league_id else None
    if source_id:
        source_data_dir = _league_data_dir(source_id, create=False)
        _copy_data_tree(source_data_dir, target_data_dir, overwrite=True)
        _rewrite_career_index(
            target_data_dir,
            new_league_id=resolved_id,
            new_display_name=resolved_name,
        )
        _rewrite_trade_settings(
            target_data_dir,
            source_league_id=source_id,
            target_league_id=resolved_id,
        )

    if existing is None:
        record = league_registry.register_league(
            resolved_id,
            display_name=resolved_name,
            mode=mode,
            status="active",
            set_active_if_first=False,
        )
    else:
        record = league_registry.update_league(
            resolved_id,
            display_name=resolved_name,
            mode=mode,
            status="active",
        )

    _write_metadata(record.id, record.display_name)

    if activate:
        return switch_active_league(record.id)
    refreshed = league_registry.get_league(record.id)
    if refreshed is None:
        raise ValueError(f"League not found after create: {record.id}")
    return refreshed


def clone_league(
    source_league_id: str,
    *,
    display_name: str,
    target_league_id: str | None = None,
    overwrite: bool = False,
    activate: bool = False,
) -> league_registry.LeagueRecord:
    """Clone an existing league's data into a new league entry."""

    source = league_registry.get_league(source_league_id)
    if source is None:
        raise ValueError(f"Source league not found: {source_league_id}")
    return create_league_entry(
        display_name=display_name,
        league_id=target_league_id,
        mode=source.mode,
        template_league_id=source.id,
        overwrite=overwrite,
        activate=activate,
    )


def switch_active_league(
    league_id: str,
    *,
    allow_archived: bool = False,
) -> league_registry.LeagueRecord:
    """Switch active league with archive-safety checks."""

    record = league_registry.get_league(league_id)
    if record is None:
        raise ValueError(f"League not found: {league_id}")
    if record.status == "archived" and not allow_archived:
        raise ValueError("Archived leagues cannot be set active.")
    return league_registry.set_active_league(record.id, ensure_data_dir=True)


def archive_league(league_id: str) -> league_registry.LeagueRecord:
    """Archive a league and switch active context when needed."""

    record = league_registry.get_league(league_id)
    if record is None:
        raise ValueError(f"League not found: {league_id}")
    if record.status == "archived":
        return record

    non_archived = [item for item in league_registry.list_leagues() if item.status != "archived"]
    if len(non_archived) <= 1:
        raise ValueError("Cannot archive the last active league.")

    updated = league_registry.update_league(record.id, status="archived")
    active = league_registry.get_active_league()
    if active is not None and active.id == updated.id:
        replacement = next(
            (
                item
                for item in league_registry.list_leagues()
                if item.id != updated.id and item.status != "archived"
            ),
            None,
        )
        if replacement is not None:
            league_registry.set_active_league(replacement.id, ensure_data_dir=True)
    refreshed = league_registry.get_league(updated.id)
    if refreshed is None:
        raise ValueError(f"League not found after archive: {updated.id}")
    return refreshed


def unarchive_league(
    league_id: str,
    *,
    activate: bool = False,
) -> league_registry.LeagueRecord:
    """Restore an archived league."""

    record = league_registry.get_league(league_id)
    if record is None:
        raise ValueError(f"League not found: {league_id}")
    updated = league_registry.update_league(record.id, status="active")
    if activate:
        return switch_active_league(updated.id)
    refreshed = league_registry.get_league(updated.id)
    if refreshed is None:
        raise ValueError(f"League not found after restore: {updated.id}")
    return refreshed


def delete_league(
    league_id: str,
    *,
    delete_data: bool = True,
    force_if_active: bool = False,
) -> bool:
    """Delete a league registry entry and optionally its on-disk data."""

    record = league_registry.get_league(league_id)
    if record is None:
        return False
    all_leagues = list(league_registry.list_leagues())
    if len(all_leagues) <= 1:
        raise ValueError("Cannot delete the last league.")

    active = league_registry.get_active_league()
    deleting_active = active is not None and active.id == record.id
    if deleting_active and not force_if_active:
        raise ValueError("Cannot delete the active league without force_if_active=True.")

    removed = league_registry.remove_league(record.id)
    if not removed:
        return False

    if delete_data:
        target = _league_dir(record.id)
        if target.exists():
            shutil.rmtree(target)

    # When the active league is the one we just removed, re-point the
    # active pointer at any surviving non-archived league so downstream
    # calls to get_data_dir() don't resolve to a deleted directory and
    # leave the sidecar in a half-broken state.
    if deleting_active:
        remaining = [
            item
            for item in league_registry.list_leagues()
            if item.id != record.id and item.status != "archived"
        ]
        if remaining:
            league_registry.set_active_league(remaining[0].id, ensure_data_dir=True)
        else:
            path_utils.clear_active_league_id()
    return True


def available_leagues(*, include_archived: bool = False) -> Iterable[league_registry.LeagueRecord]:
    """Return leagues with optional archived filtering."""

    for record in league_registry.list_leagues():
        if include_archived or record.status != "archived":
            yield record


__all__ = [
    "archive_league",
    "available_leagues",
    "clone_league",
    "create_league_entry",
    "delete_league",
    "switch_active_league",
    "unarchive_league",
]
