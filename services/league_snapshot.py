"""League snapshot export/import helpers."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional
import zipfile

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

MANIFEST_VERSION = 1

_EXCLUDE_DIRS = {"change_requests", "exports", "backups", "logs", "__pycache__"}
_EXCLUDE_FILES = {"change_requests.json"}


def _now_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _is_excluded(rel_path: Path) -> bool:
    parts = rel_path.parts
    if not parts:
        return True
    if parts[0] in _EXCLUDE_DIRS:
        return True
    if rel_path.name in _EXCLUDE_FILES:
        return True
    return False


def _iter_data_files(data_dir: Path) -> List[Path]:
    files: List[Path] = []
    for root, dirs, filenames in os.walk(data_dir):
        rel_root = Path(root).relative_to(data_dir)
        dirs[:] = [d for d in dirs if not _is_excluded(rel_root / d)]
        for name in filenames:
            rel_path = rel_root / name if rel_root != Path(".") else Path(name)
            if _is_excluded(rel_path):
                continue
            files.append(rel_path)
    files.sort(key=lambda p: p.as_posix())
    return files


def _hash_file(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 64)
            if not chunk:
                break
            total += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), total


def _normalize_zip_path(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    rel = PurePosixPath(path_str)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        return None
    normalized = Path(*rel.parts)
    if _is_excluded(normalized):
        return None
    return normalized


def _build_manifest(
    *,
    league_id: str | None,
    league_name: str | None,
    files: List[Dict[str, object]],
) -> Dict[str, object]:
    total_bytes = sum(int(entry.get("bytes", 0) or 0) for entry in files)
    return {
        "version": MANIFEST_VERSION,
        "exported_at": _now_iso(),
        "league": {"id": league_id or "", "name": league_name or ""},
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }


def _write_snapshot_zip(
    *,
    data_dir: Path,
    output_path: Path,
    league_id: str | None,
    league_name: str | None,
) -> Dict[str, object]:
    file_paths = _iter_data_files(data_dir)
    file_entries: List[Dict[str, object]] = []
    for rel_path in file_paths:
        abs_path = data_dir / rel_path
        digest, size = _hash_file(abs_path)
        file_entries.append(
            {
                "path": rel_path.as_posix(),
                "sha256": digest,
                "bytes": size,
            }
        )

    manifest = _build_manifest(
        league_id=league_id,
        league_name=league_name,
        files=file_entries,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in file_entries:
            rel = entry["path"]
            archive.write(data_dir / rel, arcname=rel)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    return {
        "status": "success",
        "path": str(output_path),
        "file_count": len(file_entries),
    }


def export_league_snapshot(output_dir: Path | None = None) -> Dict[str, object]:
    data_dir = get_data_dir()
    context = SeasonContext.load()
    league_id = context.league.get("id")
    league_name = context.league.get("name")
    out_dir = output_dir or (data_dir / "exports")
    filename = f"league_snapshot_{_now_stamp()}.zip"
    return _write_snapshot_zip(
        data_dir=data_dir,
        output_path=out_dir / filename,
        league_id=league_id,
        league_name=league_name,
    )


def create_backup_snapshot(output_dir: Path | None = None) -> Dict[str, object]:
    data_dir = get_data_dir()
    context = SeasonContext.load()
    league_id = context.league.get("id")
    league_name = context.league.get("name")
    out_dir = output_dir or (data_dir / "backups")
    filename = f"league_backup_{_now_stamp()}.zip"
    return _write_snapshot_zip(
        data_dir=data_dir,
        output_path=out_dir / filename,
        league_id=league_id,
        league_name=league_name,
    )


def import_league_snapshot(
    snapshot_path: Path,
    *,
    require_league_match: bool = True,
) -> Dict[str, object]:
    if not snapshot_path.exists():
        return {"status": "error", "message": "Snapshot file not found."}

    try:
        archive = zipfile.ZipFile(snapshot_path, "r")
    except zipfile.BadZipFile:
        return {"status": "error", "message": "Snapshot file is not a valid zip."}

    with archive:
        try:
            manifest_raw = archive.read("manifest.json")
        except KeyError:
            return {"status": "error", "message": "Snapshot missing manifest.json."}
        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {"status": "error", "message": "Snapshot manifest is invalid JSON."}

        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            return {"status": "error", "message": "Snapshot manifest has no files."}

        league = manifest.get("league", {}) if isinstance(manifest, dict) else {}
        manifest_league_id = ""
        if isinstance(league, dict):
            manifest_league_id = str(league.get("id") or "")

        local_context = SeasonContext.load()
        local_league_id = str(local_context.league.get("id") or "")
        if require_league_match and local_league_id and manifest_league_id:
            if local_league_id != manifest_league_id:
                return {
                    "status": "error",
                    "message": (
                        "League ID mismatch. This snapshot belongs to a different league."
                    ),
                }
        if require_league_match and local_league_id and not manifest_league_id:
            return {
                "status": "error",
                "message": "Snapshot missing league ID.",
            }

        extracted: List[Dict[str, object]] = []
        for entry in files:
            if not isinstance(entry, dict):
                return {"status": "error", "message": "Snapshot manifest is invalid."}
            path_str = str(entry.get("path") or "")
            rel_path = _normalize_zip_path(path_str)
            if rel_path is None:
                return {"status": "error", "message": f"Invalid path in manifest: {path_str}"}
            try:
                payload = archive.read(path_str)
            except KeyError:
                return {"status": "error", "message": f"Missing file in snapshot: {path_str}"}
            digest = hashlib.sha256(payload).hexdigest()
            expected = str(entry.get("sha256") or "")
            if expected and digest != expected:
                return {
                    "status": "error",
                    "message": f"Hash mismatch for {path_str}.",
                }
            extracted.append({"path": rel_path, "payload": payload})

    backup_result = create_backup_snapshot()
    if backup_result.get("status") != "success":
        return {
            "status": "error",
            "message": "Unable to create backup before import.",
        }

    data_dir = get_data_dir()
    for item in extracted:
        rel_path = item["path"]
        payload = item["payload"]
        dest = data_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as handle:
            handle.write(payload)

    return {
        "status": "success",
        "backup_path": backup_result.get("path"),
        "file_count": len(extracted),
    }


__all__ = [
    "export_league_snapshot",
    "import_league_snapshot",
    "create_backup_snapshot",
]
