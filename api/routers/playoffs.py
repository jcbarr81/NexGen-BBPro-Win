"""Playoffs endpoints.

Reads the persisted ``playoffs_<year>.json`` documents produced by the main
app's playoff flow. Returns them mostly as-is plus a list of years we have
data for, so the React bracket page can render without further shaping.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from utils.path_utils import get_data_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/playoffs", tags=["playoffs"], dependencies=[CurrentIdentity])

_FILE_RE = re.compile(r"^playoffs_(\d{4})\.json$")


def _list_years() -> List[int]:
    base = get_data_dir()
    years: List[int] = []
    try:
        for path in base.iterdir():
            match = _FILE_RE.match(path.name)
            if match:
                try:
                    years.append(int(match.group(1)))
                except ValueError:
                    continue
    except OSError:
        return []
    years.sort(reverse=True)
    return years


def _load_year(year: int) -> Dict[str, Any]:
    path = get_data_dir() / f"playoffs_{year}.json"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No playoffs data for {year}",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse playoffs_{year}.json: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"playoffs_{year}.json is malformed",
        )
    return payload


@router.get("/years")
def list_years() -> Dict[str, Any]:
    years = _list_years()
    return {"years": years, "latest": years[0] if years else None}


@router.get("")
def playoffs_view(
    year: Optional[int] = Query(default=None, description="Defaults to most recent"),
) -> Dict[str, Any]:
    if year is None:
        years = _list_years()
        if not years:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No playoffs data available.",
            )
        year = years[0]
    return _load_year(year)
