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

from utils.park_utils import (
    GENERATION7_NAME_SINCE,
    _load_latest_parks,
    _park_config_path,
    generation7_only_parks,
    generation7_parks,
    list_ballpark_names,
)
from utils.path_utils import get_base_dir, get_data_dir

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
    if items and _ballflight_league():
        _as_generation7_plays(items)
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


def _ballflight_league() -> bool:
    """True when the league's season is on engine generation 7 (read, never
    fixed). Every other league's catalog is exactly as before."""
    try:
        from services.league_rating_centers import get_league_engine_generation

        return get_league_engine_generation(store=False) >= 7
    except Exception:
        return False


def _as_generation7_plays(items: List[Dict[str, Any]]) -> None:
    """Release 6b: a generation 7 league's catalog shows the dimensions it
    plays. A park in ``ParkFences.csv`` reads its five-point fence there
    (Comerica's centre field 412 ft, not ParkConfig's 420), with left- and
    right-centre and the five wall heights added; the parks only generation
    7 knows (Sutter Health Park, George M. Steinbrenner Field) are added.
    The fitted per-side shifts (owner decisions 18 and 20) are a model of
    each park's home runs, not its measurements, and are not shown."""
    fences = generation7_parks()
    if not fences:
        return
    # A name one of these parks carried only before GENERATION7_NAME_SINCE
    # (Royals Stadium) plays the generic park on generation 7: not offered.
    items[:] = [
        item for item in items
        if not (
            str(item.get("park_id") or "").upper() in fences
            and int(item.get("year") or 0) < GENERATION7_NAME_SINCE
        )
    ]
    for item in items:
        row = fences.get(str(item.get("park_id") or "").upper())
        if row is None:
            continue
        _put_fence(item, row)
    for pid, row in sorted(generation7_only_parks().items()):
        item = {
            "park_id": pid, "name": row["name"], "year": row["year"],
            "lf": None, "cf": None, "rf": None, "foul_territory": None,
            # No ParkConfig row, so no diagram to draw.
            "has_preview": False,
        }
        _put_fence(item, row)
        items.append(item)
    items.sort(key=lambda item: str(item.get("name") or ""))


def _put_fence(item: Dict[str, Any], row: Dict[str, Any]) -> None:
    lf, lc, cf, rc, rf = row["distances"]
    item.update({
        "lf": lf, "cf": cf, "rf": rf, "lc": lc, "rc": rc,
        "walls": list(row["heights"]), "fence_year": row["year"],
    })


@router.get("/preview")
def park_preview(park_id: str, year: int) -> FileResponse:
    if not park_id or year <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="park_id and year required.",
        )
    # Prefer existing bundled / previously-rendered diagrams; fall back to
    # generating on demand into the user data dir (install dir is read-only
    # in packaged mode).
    candidates = [
        get_data_dir() / "images" / "parks" / f"{park_id}_{year}.png",
        get_base_dir() / "images" / "parks" / f"{park_id}_{year}.png",
    ]
    existing = next((p for p in candidates if p.exists()), None)
    if existing is None:
        target = get_data_dir() / "images" / "parks" / f"{park_id}_{year}.png"
        try:
            from scripts import generate_park_diagrams as gen

            parks = gen.load_parks(_park_config_path())
            matching = [r for r in parks if r.park_id == park_id and r.year == year]
            if matching:
                target.parent.mkdir(parents=True, exist_ok=True)
                gen.draw_diagram(matching[0], target)
                existing = target if target.exists() else None
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to render diagram: {exc}",
            ) from exc
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No diagram available."
        )
    return FileResponse(str(existing), media_type="image/png")
