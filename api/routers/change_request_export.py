"""Owner-side change-request export endpoints.

Ports ui/change_request_export_dialog.py so owners in the Electron UI can
bundle their roster/lineup/pitching/depth-chart files into an export ZIP
and send it to the commissioner.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import FileResponse

from services import change_requests as cr
from utils.path_utils import get_data_dir

from ..security import require_bearer

router = APIRouter(
    prefix="/teams/{team_id}/change-requests",
    tags=["change-requests"],
)


def _identity(identity: Dict[str, Any] = Depends(require_bearer)) -> Dict[str, Any]:
    return identity


def _owner_can_access(identity: Dict[str, Any], team_id: str) -> bool:
    role = str(identity.get("r", "")).lower()
    if role == "admin":
        return True
    return str(identity.get("t", "")).lower() == team_id.lower()


def _collect_files(team_id: str, selected: Dict[str, bool]) -> List[Dict[str, Any]]:
    data_dir = get_data_dir()
    files: List[Dict[str, Any]] = []

    def add(rel_path: str) -> None:
        path = data_dir / rel_path
        if path.exists():
            files.append(
                {"path": rel_path, "content": path.read_text(encoding="utf-8")}
            )

    if selected.get("roster"):
        add(f"rosters/{team_id}.csv")
    if selected.get("pitching"):
        add(f"rosters/{team_id}_pitching.csv")
    if selected.get("lineups"):
        add(f"lineups/{team_id}_vs_lhp.csv")
        add(f"lineups/{team_id}_vs_rhp.csv")
    if selected.get("depth"):
        add(f"depth_charts/{team_id}.json")
    return files


def _summary_label(selected: Dict[str, bool]) -> str:
    parts: List[str] = []
    if selected.get("roster"):
        parts.append("Roster")
    if selected.get("lineups"):
        parts.append("Lineups")
    if selected.get("pitching"):
        parts.append("Pitching Staff")
    if selected.get("depth"):
        parts.append("Depth Chart")
    return " / ".join(parts) or "Change Request"


@router.get("")
def list_team_requests(
    team_id: str,
    identity: Dict[str, Any] = Depends(_identity),
) -> Dict[str, Any]:
    if not _owner_can_access(identity, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own team's requests.",
        )
    rows = cr.list_requests(team_id=team_id)
    return {"team_id": team_id, "count": len(rows), "requests": rows}


@router.post("/export")
def export_team_request(
    team_id: str,
    payload: Dict[str, Any] = Body(...),
    identity: Dict[str, Any] = Depends(_identity),
) -> Dict[str, Any]:
    if not _owner_can_access(identity, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only export your own team's requests.",
        )
    sections = payload.get("sections") or {}
    if not isinstance(sections, dict):
        sections = {}
    bool_sections = {k: bool(v) for k, v in sections.items()}
    files = _collect_files(team_id, bool_sections)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files to export — select at least one section with data.",
        )
    owner_name = str(payload.get("owner_name") or team_id).strip() or team_id
    note = str(payload.get("note") or "")
    try:
        request = cr.create_request(
            team_id=team_id,
            owner_name=owner_name,
            files=files,
            summary=_summary_label(bool_sections),
            note=note,
            status="exported",
        )
        cr.add_request(request)
        export_path = cr.export_request(request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {exc}",
        ) from exc
    return {
        "request_id": request["request_id"],
        "export_path": str(export_path),
        "filename": export_path.name,
        "summary": request["summary"],
        "file_count": len(files),
    }


@router.post("/{request_id}/cancel")
def export_cancel(
    team_id: str,
    request_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(_identity),
) -> Dict[str, Any]:
    if not _owner_can_access(identity, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own team's requests.",
        )
    owner_name = str(payload.get("owner_name") or team_id).strip() or team_id
    try:
        export_path = cr.export_cancel_request(
            request_id=request_id,
            team_id=team_id,
            owner_name=owner_name,
        )
        cr.update_request_status(
            request_id, status="canceled", note="Owner canceled."
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cancel export failed: {exc}",
        ) from exc
    return {
        "request_id": request_id,
        "export_path": str(export_path),
        "filename": export_path.name,
    }


@router.get("/download/{filename}")
def download_export(
    team_id: str,
    filename: str,
    identity: Dict[str, Any] = Depends(_identity),
) -> FileResponse:
    if not _owner_can_access(identity, team_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only download your own team's exports.",
        )
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename."
        )
    path = cr.outbox_dir() / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export {filename} not found.",
        )
    return FileResponse(
        str(path), media_type="application/zip", filename=filename
    )
