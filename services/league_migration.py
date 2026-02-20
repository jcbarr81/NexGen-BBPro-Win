"""One-time migration helpers for legacy single-league layouts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, Iterable, List
import zipfile
from zipfile import ZipFile

from playbalance.season_context import slugify_league_id
from services import league_registry
from utils.path_utils import (
    get_active_league_pointer_path,
    get_data_root,
    get_league_registry_path,
)

MIGRATION_NAME = "multi_league_v1"
RESTORE_NAME = "multi_league_v1_restore"
LEGACY_SENTINELS = (
    "teams.csv",
    "players.csv",
    "users.txt",
    "schedule.csv",
    "league.txt",
    "rosters",
)
ROOT_RESERVED_NAMES = {
    "league_registry.json",
    "active_league.txt",
    "leagues",
    "system",
}
SYSTEM_DIRNAME = "system"
BACKUPS_DIRNAME = "backups"
MIGRATIONS_DIRNAME = "migrations"


@dataclass
class MigrationResult:
    status: str
    message: str
    data_root: Path
    marker_path: Path
    backup_path: Path | None = None
    league_id: str | None = None
    validation_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "data_root": str(self.data_root),
            "marker_path": str(self.marker_path),
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "league_id": self.league_id,
            "validation_errors": list(self.validation_errors),
        }


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _migration_marker_path(data_root: Path) -> Path:
    return data_root / SYSTEM_DIRNAME / MIGRATIONS_DIRNAME / f"{MIGRATION_NAME}.json"


def _backups_dir(data_root: Path) -> Path:
    return data_root / SYSTEM_DIRNAME / BACKUPS_DIRNAME


def _load_marker(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _write_marker(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def has_legacy_layout(data_root: Path | None = None) -> bool:
    root = data_root if data_root is not None else get_data_root()
    if get_league_registry_path(data_root=root).exists():
        return False
    return any((root / name).exists() for name in LEGACY_SENTINELS)


def _iter_legacy_items(data_root: Path) -> Iterable[Path]:
    for child in data_root.iterdir():
        if child.name in ROOT_RESERVED_NAMES:
            continue
        yield child


def _infer_display_name(data_root: Path) -> str:
    league_file = data_root / "league.txt"
    if league_file.exists():
        try:
            text = league_file.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    return "Legacy League"


def _make_unique_league_id(data_root: Path, preferred_name: str) -> str:
    base = slugify_league_id(preferred_name) or "legacy-league"
    if not base:
        base = "legacy-league"
    candidate = base
    index = 2
    existing = {
        entry.id
        for entry in league_registry.list_leagues()
    }
    leagues_root = data_root / "leagues"
    while candidate in existing or (leagues_root / candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _write_league_metadata(data_root: Path, league_id: str, display_name: str) -> None:
    league_dir = data_root / "leagues" / league_id
    metadata_path = league_dir / "metadata.json"
    payload = {
        "id": league_id,
        "display_name": display_name,
        "migrated_at": _utcnow(),
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _create_backup_zip(data_root: Path) -> Path:
    backups = _backups_dir(data_root)
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backups / f"pre_{MIGRATION_NAME}_{stamp}.zip"

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(data_root.rglob("*")):
            if path == backup_path:
                continue
            if path.is_dir():
                continue
            relative = path.relative_to(data_root)
            if relative.parts[:2] == (SYSTEM_DIRNAME, BACKUPS_DIRNAME):
                continue
            archive.write(path, arcname=str(relative).replace("\\", "/"))
    return backup_path


def _latest_migration_backup(data_root: Path) -> Path | None:
    backups = _backups_dir(data_root)
    if not backups.exists():
        return None
    candidates = sorted(backups.glob(f"pre_{MIGRATION_NAME}_*.zip"))
    if not candidates:
        return None
    return candidates[-1]


def _resolve_restore_backup_path(data_root: Path, requested: Path | None = None) -> Path | None:
    if requested is not None:
        return requested.resolve(strict=False)

    marker = _load_marker(_migration_marker_path(data_root))
    marker_backup = marker.get("backup_path")
    if marker_backup:
        candidate = Path(str(marker_backup)).resolve(strict=False)
        if candidate.exists():
            return candidate

    return _latest_migration_backup(data_root)


def _clear_data_root(data_root: Path) -> None:
    if not data_root.exists():
        return
    for child in data_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _safe_zip_relative_path(member_name: str) -> Path:
    normalized = member_name.replace("\\", "/").strip("/")
    candidate = Path(normalized)
    if not normalized:
        raise ValueError("Zip contains an empty path entry.")
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe archive member path: {member_name}")
    return candidate


def _extract_backup_zip(backup_zip: Path, data_root: Path) -> None:
    with ZipFile(backup_zip, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            rel_path = _safe_zip_relative_path(info.filename)
            target = data_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def restore_pre_multi_league_layout(
    *,
    backup_path: Path | None = None,
    data_root: Path | None = None,
    force: bool = False,
) -> MigrationResult:
    """Restore a pre-migration layout from a backup created during migration."""

    root = data_root if data_root is not None else get_data_root()
    marker_path = _migration_marker_path(root)
    root.mkdir(parents=True, exist_ok=True)

    backup = _resolve_restore_backup_path(root, backup_path)
    if backup is None or not backup.exists():
        return MigrationResult(
            status="failed",
            message="No migration backup zip was found for restore.",
            data_root=root,
            marker_path=marker_path,
            backup_path=backup,
        )

    has_existing_content = any(root.iterdir())
    if has_existing_content and not force:
        return MigrationResult(
            status="blocked",
            message=(
                "Data root contains existing files. Re-run restore with force=True "
                "or --force to overwrite."
            ),
            data_root=root,
            marker_path=marker_path,
            backup_path=backup,
        )

    temp_backup: Path | None = None
    backup_for_restore = backup
    try:
        if root in backup.resolve(strict=False).parents:
            with tempfile.NamedTemporaryFile(
                prefix=f"restore_{MIGRATION_NAME}_",
                suffix=".zip",
                delete=False,
            ) as handle:
                temp_backup = Path(handle.name)
            shutil.copy2(backup, temp_backup)
            backup_for_restore = temp_backup

        if has_existing_content:
            _clear_data_root(root)
        _extract_backup_zip(backup_for_restore, root)
    except Exception as exc:
        return MigrationResult(
            status="failed",
            message=f"Restore failed: {exc}",
            data_root=root,
            marker_path=marker_path,
            backup_path=backup,
        )
    finally:
        if temp_backup is not None:
            try:
                temp_backup.unlink()
            except OSError:
                pass

    restore_note_path = root / SYSTEM_DIRNAME / MIGRATIONS_DIRNAME / f"{RESTORE_NAME}.json"
    restore_payload = {
        "name": RESTORE_NAME,
        "status": "completed",
        "completed_at": _utcnow(),
        "source_backup_path": str(backup),
    }
    _write_marker(restore_note_path, restore_payload)

    return MigrationResult(
        status="restored",
        message="Restored pre-migration layout from backup zip.",
        data_root=root,
        marker_path=restore_note_path,
        backup_path=backup,
    )


def _move_legacy_into_league(data_root: Path, target_data_dir: Path) -> None:
    target_data_dir.mkdir(parents=True, exist_ok=True)
    for item in list(_iter_legacy_items(data_root)):
        destination = target_data_dir / item.name
        if destination.exists():
            if item.is_dir() and destination.is_dir():
                for nested in item.iterdir():
                    nested_dest = destination / nested.name
                    if nested_dest.exists():
                        continue
                    shutil.move(str(nested), str(nested_dest))
                try:
                    item.rmdir()
                except OSError:
                    pass
                continue
            if item.is_file():
                try:
                    item.unlink()
                except OSError:
                    pass
                continue
            continue
        shutil.move(str(item), str(destination))


def _validate_migrated_layout(league_data_dir: Path) -> List[str]:
    errors: List[str] = []

    teams_path = league_data_dir / "teams.csv"
    users_path = league_data_dir / "users.txt"
    schedule_path = league_data_dir / "schedule.csv"

    if not teams_path.exists():
        errors.append("teams.csv missing after migration")
    else:
        try:
            with teams_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    errors.append("teams.csv unreadable (missing header)")
        except Exception as exc:
            errors.append(f"teams.csv unreadable: {exc}")

    if not users_path.exists():
        errors.append("users.txt missing after migration")
    else:
        try:
            users_path.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"users.txt unreadable: {exc}")

    if schedule_path.exists():
        try:
            with schedule_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    errors.append("schedule.csv unreadable (missing header)")
        except Exception as exc:
            errors.append(f"schedule.csv unreadable: {exc}")

    return errors


def _repair_registry_from_existing_leagues(data_root: Path) -> MigrationResult:
    leagues_root = data_root / "leagues"
    league_dirs = [
        path for path in leagues_root.iterdir()
        if path.is_dir() and (path / "data").exists()
    ]
    marker_path = _migration_marker_path(data_root)
    if not league_dirs:
        return MigrationResult(
            status="skipped",
            message="No migration needed.",
            data_root=data_root,
            marker_path=marker_path,
        )

    for league_dir in sorted(league_dirs, key=lambda p: p.name):
        league_id = slugify_league_id(league_dir.name)
        if not league_id:
            continue
        if league_registry.get_league(league_id) is None:
            display_name = league_dir.name
            metadata = league_dir / "metadata.json"
            if metadata.exists():
                try:
                    payload = json.loads(metadata.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        display_name = str(payload.get("display_name") or display_name)
                except Exception:
                    pass
            league_registry.register_league(
                league_id,
                display_name=display_name,
                set_active_if_first=True,
            )

    active = league_registry.get_active_league()
    if active is None:
        leagues = league_registry.list_leagues()
        if leagues:
            league_registry.set_active_league(leagues[0].id, ensure_data_dir=True)

    payload = {
        "name": MIGRATION_NAME,
        "status": "repaired",
        "repaired_at": _utcnow(),
        "message": "Rebuilt missing league registry from existing multi-league layout.",
    }
    _write_marker(marker_path, payload)
    return MigrationResult(
        status="repaired_registry",
        message="Rebuilt missing registry from existing league folders.",
        data_root=data_root,
        marker_path=marker_path,
        league_id=(league_registry.get_active_league().id if league_registry.get_active_league() else None),
    )


def migrate_legacy_layout_if_needed(*, data_root: Path | None = None) -> MigrationResult:
    """Migrate legacy root-level league data into the multi-league layout."""

    root = data_root if data_root is not None else get_data_root()
    marker_path = _migration_marker_path(root)
    marker = _load_marker(marker_path)

    if get_league_registry_path(data_root=root).exists():
        if marker.get("status") != "completed":
            payload = {
                "name": MIGRATION_NAME,
                "status": "completed",
                "completed_at": _utcnow(),
                "message": "Registry already present; migration not required.",
            }
            _write_marker(marker_path, payload)
        return MigrationResult(
            status="skipped",
            message="Registry already present; migration not required.",
            data_root=root,
            marker_path=marker_path,
        )

    if marker.get("status") == "completed":
        return MigrationResult(
            status="skipped",
            message="Migration already completed.",
            data_root=root,
            marker_path=marker_path,
        )

    if not any((root / name).exists() for name in LEGACY_SENTINELS):
        return _repair_registry_from_existing_leagues(root)

    started_payload = {
        "name": MIGRATION_NAME,
        "status": "in_progress",
        "started_at": _utcnow(),
    }
    _write_marker(marker_path, started_payload)

    backup_path: Path | None = None
    league_id: str | None = None
    validation_errors: List[str] = []

    try:
        backup_path = _create_backup_zip(root)
        display_name = _infer_display_name(root)
        league_id = _make_unique_league_id(root, display_name)
        target_data_dir = root / "leagues" / league_id / "data"

        _move_legacy_into_league(root, target_data_dir)

        league_registry.register_league(
            league_id,
            display_name=display_name,
            set_active_if_first=False,
        )
        league_registry.set_active_league(league_id, ensure_data_dir=True)
        _write_league_metadata(root, league_id, display_name)

        validation_errors = _validate_migrated_layout(target_data_dir)
        completed_payload = {
            "name": MIGRATION_NAME,
            "status": "completed",
            "completed_at": _utcnow(),
            "backup_path": str(backup_path),
            "league_id": league_id,
            "validation_errors": validation_errors,
        }
        _write_marker(marker_path, completed_payload)
        return MigrationResult(
            status="migrated",
            message="Legacy league migrated to multi-league layout.",
            data_root=root,
            marker_path=marker_path,
            backup_path=backup_path,
            league_id=league_id,
            validation_errors=validation_errors,
        )
    except Exception as exc:
        failed_payload = {
            "name": MIGRATION_NAME,
            "status": "failed",
            "failed_at": _utcnow(),
            "backup_path": str(backup_path) if backup_path else None,
            "league_id": league_id,
            "error": str(exc),
        }
        _write_marker(marker_path, failed_payload)
        return MigrationResult(
            status="failed",
            message=f"Legacy migration failed: {exc}",
            data_root=root,
            marker_path=marker_path,
            backup_path=backup_path,
            league_id=league_id,
            validation_errors=validation_errors,
        )


def inspect_layout(*, data_root: Path | None = None) -> Dict[str, Any]:
    """Return a diagnostic snapshot of the current data layout."""

    root = data_root if data_root is not None else get_data_root()
    registry_path = get_league_registry_path(data_root=root)
    pointer_path = get_active_league_pointer_path(data_root=root)
    marker_path = _migration_marker_path(root)
    leagues_root = root / "leagues"
    league_dirs = []
    if leagues_root.exists():
        for child in sorted(leagues_root.iterdir(), key=lambda p: p.name):
            if child.is_dir():
                league_dirs.append(child.name)
    return {
        "data_root": str(root),
        "registry_exists": registry_path.exists(),
        "active_pointer_exists": pointer_path.exists(),
        "legacy_layout_detected": any((root / name).exists() for name in LEGACY_SENTINELS),
        "league_dirs": league_dirs,
        "marker_path": str(marker_path),
        "marker": _load_marker(marker_path),
    }


__all__ = [
    "MIGRATION_NAME",
    "RESTORE_NAME",
    "MigrationResult",
    "has_legacy_layout",
    "inspect_layout",
    "migrate_legacy_layout_if_needed",
    "restore_pre_multi_league_layout",
]
