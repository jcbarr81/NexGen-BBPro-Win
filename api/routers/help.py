"""Help + tutorials endpoints.

Serves:
- The Electron UI manual (`docs/manuals/electron_ui_guide.md`).
- The tutorial catalog extracted from ``services.tutorials``.
- The legacy HTML manuals under ``docs/manuals/``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from services.tutorials import tutorial_catalog, tutorial_list
from utils.path_utils import get_base_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/help", tags=["help"], dependencies=[CurrentIdentity])


# The installer manual is deliberately not served: it documents the retired
# desktop build's setup flow, and the app has been cloud-only for some time.
# The file stays on disk for reference. The two below describe the old desktop
# UI and are kept as historical reference, which the Help page says on the tab.
_LEGACY_MANUALS: Dict[str, str] = {
    "game": "game_manual.html",
    "finance": "finance_system_manual.html",
}


@router.get("/manual")
def manual() -> Dict[str, Any]:
    """Return the Electron UI guide as markdown text."""

    path = get_base_dir() / "docs" / "manuals" / "electron_ui_guide.md"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manual file missing.",
        )
    return {
        "format": "markdown",
        "source": "docs/manuals/electron_ui_guide.md",
        "content": path.read_text(encoding="utf-8"),
    }


@router.get("/tutorials")
def tutorials() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = tutorial_list()  # type: ignore[assignment]
    return {"count": len(items), "tutorials": items}


@router.get("/tutorials/{tutorial_id}")
def tutorial_detail(tutorial_id: str) -> Dict[str, Any]:
    catalog = tutorial_catalog()
    data = catalog.get(tutorial_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tutorial {tutorial_id!r} not found.",
        )
    return data


@router.get("/legacy-manuals")
def legacy_manual_list() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    manuals_dir = get_base_dir() / "docs" / "manuals"
    for doc_id, filename in _LEGACY_MANUALS.items():
        path = manuals_dir / filename
        if path.exists():
            items.append(
                {"doc_id": doc_id, "filename": filename, "available": True}
            )
        else:
            items.append(
                {"doc_id": doc_id, "filename": filename, "available": False}
            )
    return {"manuals": items}


@router.get("/legacy-manuals/{doc_id}")
def legacy_manual(doc_id: str) -> FileResponse:
    filename = _LEGACY_MANUALS.get(doc_id)
    if filename is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown legacy manual {doc_id!r}.",
        )
    path = get_base_dir() / "docs" / "manuals" / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Manual file {filename!r} missing.",
        )
    return FileResponse(str(path), media_type="text/html")
