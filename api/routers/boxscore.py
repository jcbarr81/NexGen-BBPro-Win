"""Boxscore HTML viewer.

Boxscore files are pre-rendered HTML written by ``playbalance.game_runner``
into ``data/boxscores/`` (regular season) and ``data/boxscores/playoffs/``
during sims. This endpoint reads them back so the React UI can render the
same view the PyQt ``ui/boxscore_window.py`` shows.

Path safety: the requested file MUST resolve to something under the active
data dir's ``boxscores`` tree -- absolute paths from outside that root are
rejected with a 400. This guards against a token-holding client probing
the filesystem.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status

from utils.path_utils import get_data_dir

from ..security import CurrentIdentity

router = APIRouter(prefix="/boxscore", tags=["boxscore"], dependencies=[CurrentIdentity])


def _safe_resolve(raw: str) -> Path:
    """Resolve *raw* against the active boxscores root and refuse escapes."""

    boxscores_root = (get_data_dir() / "boxscores").resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = boxscores_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(boxscores_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Boxscore path must live under the data/boxscores tree.",
        ) from exc
    return resolved


@router.get("")
def get_boxscore(
    path: str = Query(..., description="Absolute or boxscores-relative path"),
) -> dict:
    resolved = _safe_resolve(path)
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Boxscore file not found: {resolved.name}",
        )
    try:
        html = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read boxscore: {exc}",
        ) from exc
    return {"path": str(resolved), "filename": resolved.name, "html": html}
