"""Owner change request queue + import/export helpers."""

from __future__ import annotations

from datetime import datetime
import csv
import hashlib
import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from utils.news_logger import log_news_event
from utils.path_utils import get_active_league_id, get_data_dir
from utils.roster_loader import load_roster
from utils.depth_chart import save_depth_chart

QUEUE_VERSION = 1
REQUEST_VERSION = 1


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _now_bundle_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M")


def _slug_token(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return fallback
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or fallback


def _bundle_filename(
    *,
    action: str,
    team_id: str,
    out_dir: Path,
) -> str:
    league_id = get_active_league_id(default="league")
    league_slug = _slug_token(league_id, fallback="league")
    team_slug = _slug_token(team_id, fallback="team")
    stamp = _now_bundle_stamp()
    if action == "cancel":
        base = f"change_request_cancel_{league_slug}_{team_slug}_{stamp}"
    else:
        base = f"change_request_{league_slug}_{team_slug}_{stamp}"
    filename = f"{base}.zip"
    candidate = out_dir / filename
    suffix = 2
    while candidate.exists():
        candidate = out_dir / f"{base}_{suffix}.zip"
        suffix += 1
    return candidate.name


def _requests_dir() -> Path:
    return get_data_dir() / "change_requests"


def audit_log_path() -> Path:
    return _requests_dir() / "audit_log.jsonl"


def _queue_path() -> Path:
    return get_data_dir() / "change_requests.json"


def inbox_dir() -> Path:
    return _requests_dir() / "inbox"


def outbox_dir() -> Path:
    return _requests_dir() / "outbox"


def imported_dir() -> Path:
    return _requests_dir() / "imported"


def failed_dir() -> Path:
    return _requests_dir() / "failed"


def _ensure_dirs() -> None:
    for path in (inbox_dir(), outbox_dir(), imported_dir(), failed_dir()):
        path.mkdir(parents=True, exist_ok=True)


def load_queue(path: Path | None = None) -> Dict[str, Any]:
    target = path or _queue_path()
    if not target.exists():
        return {"version": QUEUE_VERSION, "requests": []}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": QUEUE_VERSION, "requests": []}
    if not isinstance(payload, dict):
        return {"version": QUEUE_VERSION, "requests": []}
    payload.setdefault("version", QUEUE_VERSION)
    payload.setdefault("requests", [])
    if not isinstance(payload.get("requests"), list):
        payload["requests"] = []
    return payload


def save_queue(payload: Dict[str, Any], path: Path | None = None) -> None:
    target = path or _queue_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["version"] = QUEUE_VERSION
    payload["updated_at"] = _now_iso()
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def list_requests(
    *,
    status: str | None = None,
    team_id: str | None = None,
    path: Path | None = None,
) -> List[Dict[str, Any]]:
    payload = load_queue(path)
    rows = [r for r in payload.get("requests", []) if isinstance(r, dict)]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    if team_id:
        rows = [r for r in rows if str(r.get("team_id")) == team_id]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def create_request(
    *,
    team_id: str,
    owner_name: str,
    files: List[Dict[str, Any]],
    summary: str,
    note: str | None = None,
    status: str = "pending",
) -> Dict[str, Any]:
    if not team_id:
        raise ValueError("team_id is required")
    if not files:
        raise ValueError("At least one file is required")
    request_id = uuid.uuid4().hex[:10]
    now = _now_iso()
    request = {
        "version": REQUEST_VERSION,
        "request_id": request_id,
        "team_id": str(team_id),
        "owner_name": str(owner_name or team_id),
        "type": "bundle",
        "status": status,
        "summary": summary,
        "note": note or "",
        "files": files,
        "created_at": now,
        "updated_at": now,
    }
    return request


def add_request(request: Dict[str, Any], *, path: Path | None = None) -> Dict[str, Any]:
    payload = load_queue(path)
    requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
    req_id = request.get("request_id")
    if req_id and any(r.get("request_id") == req_id for r in requests):
        return {"status": "exists", "request_id": req_id}
    requests.append(request)
    payload["requests"] = requests
    save_queue(payload, path)
    return {"status": "added", "request_id": req_id}


def update_request_status(
    request_id: str,
    *,
    status: str,
    note: str | None = None,
    applied_by: str | None = None,
    path: Path | None = None,
) -> Dict[str, Any]:
    payload = load_queue(path)
    requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
    found = None
    for req in requests:
        if req.get("request_id") == request_id:
            found = req
            break
    if found is None:
        return {"status": "missing", "request_id": request_id}
    found["status"] = status
    found["updated_at"] = _now_iso()
    if note is not None:
        found["admin_note"] = note
    if applied_by:
        found["applied_by"] = applied_by
        found["applied_at"] = _now_iso()
    payload["requests"] = requests
    save_queue(payload, path)
    return {"status": "updated", "request_id": request_id}


def export_request(request: Dict[str, Any], *, out_dir: Path | None = None) -> Path:
    _ensure_dirs()
    target_dir = out_dir or outbox_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    request_id = request.get("request_id") or uuid.uuid4().hex[:10]
    payload = {
        "version": REQUEST_VERSION,
        "action": "submit",
        "exported_at": _now_iso(),
        "request": request,
    }
    filename = _bundle_filename(
        action="submit",
        team_id=str(request.get("team_id") or ""),
        out_dir=target_dir,
    )
    path = target_dir / filename
    _write_export_bundle(path, payload)
    return path


def export_cancel_request(
    *,
    request_id: str,
    team_id: str,
    owner_name: str | None = None,
    out_dir: Path | None = None,
) -> Path:
    _ensure_dirs()
    target_dir = out_dir or outbox_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": REQUEST_VERSION,
        "action": "cancel",
        "exported_at": _now_iso(),
        "request": {
            "request_id": request_id,
            "team_id": team_id,
            "owner_name": owner_name or team_id,
        },
    }
    filename = _bundle_filename(
        action="cancel",
        team_id=team_id,
        out_dir=target_dir,
    )
    path = target_dir / filename
    _write_export_bundle(path, payload)
    return path


def _write_export_bundle(path: Path, payload: Dict[str, Any]) -> None:
    request = payload.get("request")
    if not isinstance(request, dict):
        request = {}
    action = str(payload.get("action") or "submit").lower()
    files_manifest: list[dict[str, Any]] = []
    written_paths: set[str] = set()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in request.get("files", []) if isinstance(request.get("files"), list) else []:
            if not isinstance(entry, dict):
                continue
            rel_path = _normalize_path(entry.get("path"))
            content = entry.get("content")
            if not rel_path or not isinstance(content, str):
                continue
            archive_path = f"files/{rel_path}"
            if archive_path in written_paths:
                continue
            payload_bytes = content.encode("utf-8")
            archive.writestr(archive_path, payload_bytes)
            written_paths.add(archive_path)
            files_manifest.append(
                {
                    "path": rel_path,
                    "archive_path": archive_path,
                    "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                    "bytes": len(payload_bytes),
                }
            )

        manifest = {
            "version": REQUEST_VERSION,
            "type": "change_request_bundle",
            "action": action,
            "exported_at": str(payload.get("exported_at") or _now_iso()),
            "request_id": str(request.get("request_id") or ""),
            "team_id": str(request.get("team_id") or ""),
            "owner_name": str(request.get("owner_name") or ""),
            "summary": str(request.get("summary") or ""),
            "files": files_manifest,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("request.json", json.dumps(payload, indent=2))


def _load_export_payload(file_path: Path) -> Dict[str, Any]:
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid request payload")
        return payload
    if suffix == ".zip":
        return _load_export_payload_from_zip(file_path)
    raise ValueError(f"Unsupported change request file type: {file_path.suffix}")


def _load_export_payload_from_zip(file_path: Path) -> Dict[str, Any]:
    try:
        archive = zipfile.ZipFile(file_path, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid zip file") from exc
    with archive:
        request_member = "request.json"
        if request_member not in archive.namelist():
            raise ValueError("bundle missing request.json")
        try:
            payload = json.loads(archive.read(request_member).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("bundle request.json is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("bundle payload must be an object")

        request = payload.get("request")
        if isinstance(request, dict):
            files = request.get("files")
            if isinstance(files, list):
                for entry in files:
                    if not isinstance(entry, dict):
                        continue
                    if isinstance(entry.get("content"), str):
                        continue
                    rel_path = _normalize_path(entry.get("path"))
                    if not rel_path:
                        continue
                    content = None
                    for member in (f"files/{rel_path}", rel_path):
                        try:
                            content = archive.read(member).decode("utf-8")
                            break
                        except KeyError:
                            continue
                    if content is not None:
                        entry["content"] = content
        return payload


def import_requests_from_inbox(*, inbox: Path | None = None, path: Path | None = None) -> Dict[str, Any]:
    _ensure_dirs()
    inbox_path = inbox or inbox_dir()
    imported = 0
    canceled = 0
    failed = 0
    errors: List[str] = []
    inbox_files = sorted(
        [
            path_obj
            for path_obj in inbox_path.iterdir()
            if path_obj.is_file() and path_obj.suffix.lower() in {".json", ".zip"}
        ]
    )
    for file_path in inbox_files:
        try:
            payload = _load_export_payload(file_path)
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            failed += 1
            errors.append(f"{file_path.name}: {exc}")
            _move_file(file_path, failed_dir())
            continue
        action = str(payload.get("action") or "submit").lower()
        request = payload.get("request", {})
        if not isinstance(request, dict):
            failed += 1
            errors.append(f"{file_path.name}: invalid request payload")
            _move_file(file_path, failed_dir())
            continue
        if action == "cancel":
            req_id = str(request.get("request_id") or "").strip()
            team_id = str(request.get("team_id") or "").strip()
            if not req_id or not team_id:
                failed += 1
                errors.append(f"{file_path.name}: missing cancel identifiers")
                _move_file(file_path, failed_dir())
                continue
            cancel_request(req_id, team_id=team_id, path=path)
            canceled += 1
            _move_file(file_path, imported_dir())
            continue
        # submit
        if request.get("status") in {"exported", "pending"}:
            request["status"] = "pending"
        result = add_request(request, path=path)
        if result.get("status") in {"added", "exists"}:
            imported += 1
            _move_file(file_path, imported_dir())
        else:
            failed += 1
            errors.append(f"{file_path.name}: import failed")
            _move_file(file_path, failed_dir())
    return {
        "imported": imported,
        "canceled": canceled,
        "failed": failed,
        "errors": errors,
    }


def cancel_request(
    request_id: str,
    *,
    team_id: str,
    note: str | None = None,
    path: Path | None = None,
) -> Dict[str, Any]:
    payload = load_queue(path)
    requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
    found = None
    for req in requests:
        if req.get("request_id") == request_id and str(req.get("team_id")) == str(team_id):
            found = req
            break
    if found is None:
        return {"status": "missing", "request_id": request_id}
    if found.get("status") in {"applied", "failed"}:
        return {"status": "locked", "request_id": request_id}
    found["status"] = "canceled"
    found["updated_at"] = _now_iso()
    if note:
        found["owner_note"] = note
    payload["requests"] = requests
    save_queue(payload, path)
    _append_audit(
        _build_audit_event(
            "canceled",
            found,
            actor=str(found.get("owner_name") or team_id),
            note=note,
        )
    )
    return {"status": "canceled", "request_id": request_id}


def approve_request(
    request_id: str,
    *,
    applied_by: str,
    auto_apply: bool = True,
    path: Path | None = None,
) -> Dict[str, Any]:
    payload = load_queue(path)
    request = _find_request(payload, request_id)
    if request is None:
        return {"status": "missing", "request_id": request_id}
    request["status"] = "approved"
    request["updated_at"] = _now_iso()
    payload["requests"] = _replace_request(payload, request)
    save_queue(payload, path)
    _append_audit(
        _build_audit_event(
            "approved",
            request,
            actor=applied_by,
        )
    )
    if auto_apply:
        return apply_request(request_id, applied_by=applied_by, path=path)
    return {"status": "approved", "request_id": request_id}


def reject_request(
    request_id: str,
    *,
    note: str | None = None,
    applied_by: str | None = None,
    path: Path | None = None,
) -> Dict[str, Any]:
    payload = load_queue(path)
    request = _find_request(payload, request_id)
    if request is None:
        return {"status": "missing", "request_id": request_id}
    result = update_request_status(
        request_id,
        status="rejected",
        note=note,
        applied_by=applied_by,
        path=path,
    )
    if result.get("status") == "updated":
        _append_audit(
            _build_audit_event(
                "rejected",
                request,
                actor=applied_by or "",
                note=note,
            )
        )
    return result


def apply_request(
    request_id: str,
    *,
    applied_by: str,
    path: Path | None = None,
) -> Dict[str, Any]:
    payload = load_queue(path)
    request = _find_request(payload, request_id)
    if request is None:
        return {"status": "missing", "request_id": request_id}
    try:
        _apply_request_files(request)
    except Exception as exc:
        update_request_status(
            request_id,
            status="failed",
            note=str(exc),
            applied_by=applied_by,
            path=path,
        )
        _append_audit(
            _build_audit_event(
                "apply_failed",
                request,
                actor=applied_by,
                error=str(exc),
            )
        )
        return {"status": "failed", "request_id": request_id, "error": str(exc)}
    update_request_status(
        request_id,
        status="applied",
        note="Applied successfully.",
        applied_by=applied_by,
        path=path,
    )
    _append_audit(
        _build_audit_event(
            "applied",
            request,
            actor=applied_by,
        )
    )
    summary = str(request.get("summary") or "Change request applied.")
    team_id = request.get("team_id")
    try:
        log_news_event(summary, category="change_request", team_id=team_id)
    except Exception:
        pass
    return {"status": "applied", "request_id": request_id}


def _find_request(payload: Dict[str, Any], request_id: str) -> Dict[str, Any] | None:
    for req in payload.get("requests", []) if isinstance(payload.get("requests"), list) else []:
        if isinstance(req, dict) and req.get("request_id") == request_id:
            return req
    return None


def _replace_request(payload: Dict[str, Any], request: Dict[str, Any]) -> List[Dict[str, Any]]:
    requests = [r for r in payload.get("requests", []) if isinstance(r, dict)]
    replaced = []
    for req in requests:
        if req.get("request_id") == request.get("request_id"):
            replaced.append(request)
        else:
            replaced.append(req)
    return replaced


def _apply_request_files(request: Dict[str, Any]) -> None:
    team_id = str(request.get("team_id") or "").strip()
    if not team_id:
        raise ValueError("Missing team_id")
    files = request.get("files", [])
    if not isinstance(files, list) or not files:
        raise ValueError("No files to apply")
    allowed = _allowed_paths(team_id)
    data_dir = get_data_dir()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid file entry")
        rel_path = _normalize_path(entry.get("path"))
        if rel_path not in allowed:
            raise ValueError(f"Unauthorized file path: {rel_path}")
        content = entry.get("content")
        if not isinstance(content, str):
            raise ValueError(f"Missing content for {rel_path}")
        _validate_file(allowed[rel_path], rel_path, content)
        dest = data_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if allowed[rel_path] == "depth_chart":
            data = json.loads(content)
            save_depth_chart(team_id, data)
        else:
            dest.write_text(content, encoding="utf-8")
    try:
        load_roster.cache_clear(team_id=team_id, roster_dir="data/rosters")  # type: ignore[attr-defined]
    except Exception:
        pass


def _hash_request_files(request: Dict[str, Any]) -> List[Dict[str, Any]]:
    files = request.get("files", [])
    hashes: List[Dict[str, Any]] = []
    if not isinstance(files, list):
        return hashes
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "")
        content = entry.get("content")
        if not isinstance(content, str):
            continue
        payload = content.encode("utf-8")
        hashes.append(
            {
                "path": path,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    return hashes


def _build_audit_event(
    action: str,
    request: Dict[str, Any],
    *,
    actor: str,
    note: str | None = None,
    error: str | None = None,
) -> Dict[str, Any]:
    event = {
        "timestamp": _now_iso(),
        "action": action,
        "request_id": request.get("request_id"),
        "team_id": request.get("team_id"),
        "owner_name": request.get("owner_name"),
        "summary": request.get("summary"),
        "actor": actor,
        "files": _hash_request_files(request),
    }
    if note:
        event["note"] = note
    if error:
        event["error"] = error
    return event


def _append_audit(event: Dict[str, Any]) -> None:
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception:
        pass


def _allowed_paths(team_id: str) -> Dict[str, str]:
    return {
        f"rosters/{team_id}.csv": "roster",
        f"rosters/{team_id}_pitching.csv": "pitching",
        f"lineups/{team_id}_vs_lhp.csv": "lineup",
        f"lineups/{team_id}_vs_rhp.csv": "lineup",
        f"depth_charts/{team_id}.json": "depth_chart",
    }


def _normalize_path(path: Any) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    raw = raw.lstrip("/")
    parts = [p for p in raw.split("/") if p and p != "."]
    if any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _validate_file(kind: str, path: str, content: str) -> None:
    if kind == "lineup":
        _validate_lineup_csv(path, content)
    elif kind == "roster":
        _validate_roster_csv(path, content)
    elif kind == "pitching":
        _validate_pitching_csv(path, content)
    elif kind == "depth_chart":
        _validate_depth_chart_json(path, content)


def _validate_lineup_csv(path: str, content: str) -> None:
    reader = csv.DictReader(content.splitlines())
    if "player_id" not in (reader.fieldnames or []):
        raise ValueError(f"Lineup file missing player_id header: {path}")
    entries = []
    for row in reader:
        pid = str(row.get("player_id") or "").strip()
        pos = str(row.get("position") or "").strip()
        if not pid or not pos:
            raise ValueError(f"Lineup row missing player_id/position: {path}")
        entries.append(pid)
    if len(entries) != 9:
        raise ValueError(f"Lineup must contain 9 players: {path}")
    if len(set(entries)) != 9:
        raise ValueError(f"Lineup has duplicate players: {path}")


def _validate_roster_csv(path: str, content: str) -> None:
    reader = csv.reader(content.splitlines())
    allowed_levels = {"ACT", "AAA", "LOW", "DL", "DL15", "DL45", "IR"}
    for row in reader:
        if len(row) < 2:
            raise ValueError(f"Roster row missing fields: {path}")
        pid = row[0].strip()
        level = row[1].strip().upper()
        if not pid:
            raise ValueError(f"Roster row missing player_id: {path}")
        if level not in allowed_levels:
            raise ValueError(f"Roster row invalid level {level}: {path}")


def _validate_pitching_csv(path: str, content: str) -> None:
    reader = csv.reader(content.splitlines())
    entries = 0
    for row in reader:
        if len(row) < 2:
            raise ValueError(f"Pitching row missing fields: {path}")
        pid = row[0].strip()
        if not pid:
            raise ValueError(f"Pitching row missing player_id: {path}")
        entries += 1
    if entries == 0:
        raise ValueError(f"Pitching file empty: {path}")


def _validate_depth_chart_json(path: str, content: str) -> None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Depth chart JSON invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Depth chart JSON must be object: {path}")


def _move_file(path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / path.name
    try:
        if target.exists():
            target.unlink()
    except OSError:
        pass
    try:
        path.replace(target)
    except OSError:
        pass


__all__ = [
    "load_queue",
    "save_queue",
    "list_requests",
    "create_request",
    "add_request",
    "update_request_status",
    "approve_request",
    "reject_request",
    "apply_request",
    "cancel_request",
    "export_request",
    "export_cancel_request",
    "import_requests_from_inbox",
    "inbox_dir",
    "outbox_dir",
    "imported_dir",
    "failed_dir",
    "audit_log_path",
]
