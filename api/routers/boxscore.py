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
    """Resolve *raw* against the active boxscores root and refuse escapes.

    Accepts every form league data has stored:

    * ``boxscores/season/x.html`` -- relative to the league data dir (current);
    * ``season/x.html`` -- relative to the boxscores tree;
    * an absolute path from ANY machine or league -- a Cloud Run
      ``/work/data/leagues/<id>/data/boxscores/season/x.html`` or a Windows
      ``C:/Users/.../boxscores/season/x.html`` -- re-rooted on its last
      ``boxscores`` segment, so a league that was restored locally, cloned or
      moved to a new mount still opens its own files.
    """

    boxscores_root = (get_data_dir() / "boxscores").resolve()
    segments = [s for s in str(raw).replace("\\", "/").split("/") if s]
    if "boxscores" in segments:
        last = len(segments) - 1 - segments[::-1].index("boxscores")
        segments = segments[last + 1:]
    elif str(raw).startswith(("/", "\\")) or (
        segments and segments[0].endswith(":")
    ):
        # Absolute on any platform (a POSIX path is not "absolute" to Windows).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Boxscore path must live under the data/boxscores tree.",
        )
    if not segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Boxscore path must name a file.",
        )
    resolved = boxscores_root.joinpath(*segments).resolve()
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
    path: str = Query(
        ...,
        description=(
            "Stored box score path: league-relative, boxscores-relative "
            "or legacy absolute"
        ),
    ),
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
