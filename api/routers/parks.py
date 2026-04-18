"""Ballpark catalog + diagram preview endpoints.

Wraps :mod:`utils.park_utils` so the Electron UI can port the PyQt
park-selector dialog. Diagrams are generated on-demand by
``scripts.generate_park_diagrams`` and cached under
``<base>/images/parks/<park_id>_<year>.png``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from utils.park_utils import _load_latest_parks, list_ballpark_names, _park_config_path
from utils.path_utils import get_base_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/parks", tags=["parks"], dependencies=[CurrentIdentity])


@router.get("")
def list_parks() -> Dict[str, Any]:
    infos = list(_load_latest_parks().values())
    items: List[Dict[str, Any]] = []
    for info in sorted(infos, key=lambda p: p.name):
        items.append(
            {
                "park_id": info.park_id or "",
                "name": info.name,
                "year": info.year,
                "lf": info.lf,
                "cf": info.cf,
                "rf": info.rf,
                "foul_territory": info.foul_territory,
                "has_preview": bool(info.park_id and info.year > 0),
            }
        )
    if not items:
        for name in list_ballpark_names():
            items.append(
                {
                    "park_id": "",
                    "name": name,
                    "year": 0,
                    "lf": None,
                    "cf": None,
                    "rf": None,
                    "foul_territory": None,
                    "has_preview": False,
                }
            )
    return {"count": len(items), "parks": items}


@router.get("/preview")
def park_preview(park_id: str, year: int) -> FileResponse:
    if not park_id or year <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="park_id and year required.",
        )
    img_dir = get_base_dir() / "images" / "parks"
    img_path = img_dir / f"{park_id}_{year}.png"
    if not img_path.exists():
        try:
            from scripts import generate_park_diagrams as gen

            parks = gen.load_parks(_park_config_path())
            matching = [r for r in parks if r.park_id == park_id and r.year == year]
            if matching:
                img_dir.mkdir(parents=True, exist_ok=True)
                gen.draw_diagram(matching[0], img_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to render diagram: {exc}",
            ) from exc
    if not img_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No diagram available."
        )
    return FileResponse(str(img_path), media_type="image/png")
