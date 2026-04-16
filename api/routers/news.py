"""News feed endpoint.

Wraps :func:`utils.news_reader.read_latest_news` plus a substring filter
matching the PyQt ``ui/news_window.py`` interaction.

News lines are written by the sim (injuries, key plays, transactions,
etc.) via ``utils.news_logger`` and arrive in the format::

    [2026-02-16 09:33:11] [injury] [TST] Pitch P1 injured (Elbow)

The parser splits that into timestamp / category / team / message so the
React feed can render badges instead of raw strings.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from utils.news_reader import read_latest_news

from ..security import CurrentIdentity

router = APIRouter(prefix="/news", tags=["news"], dependencies=[CurrentIdentity])

# Matches "[ts] [category] [team] message" with category and team optional.
_LINE_RE = re.compile(
    r"^\s*\[(?P<timestamp>[^\]]+)\]\s*"
    r"(?:\[(?P<category>[^\]]+)\]\s*)?"
    r"(?:\[(?P<team>[^\]]+)\]\s*)?"
    r"(?P<message>.*)$"
)


def _parse_line(raw: str) -> Dict[str, str]:
    text = raw.strip()
    match = _LINE_RE.match(text)
    if not match:
        return {"timestamp": "", "category": "", "team": "", "message": text, "raw": text}
    return {
        "timestamp": (match.group("timestamp") or "").strip(),
        "category": (match.group("category") or "").strip(),
        "team": (match.group("team") or "").strip(),
        "message": (match.group("message") or "").strip(),
        "raw": text,
    }


@router.get("")
def get_news(
    limit: int = Query(default=200, ge=1, le=2000),
    q: Optional[str] = Query(default=None, description="Case-insensitive substring filter"),
    team_id: Optional[str] = Query(default=None, description="Filter to entries tagged with this team"),
    category: Optional[str] = Query(default=None, description="Filter to entries with this category tag"),
) -> Dict[str, Any]:
    raw_lines: List[str] = read_latest_news(n=limit)
    parsed = [_parse_line(line) for line in raw_lines if line.strip()]

    if q:
        needle = q.lower()
        parsed = [p for p in parsed if needle in p["raw"].lower()]
    if team_id:
        team_norm = team_id.upper()
        parsed = [p for p in parsed if p["team"].upper() == team_norm]
    if category:
        cat_norm = category.lower()
        parsed = [p for p in parsed if p["category"].lower() == cat_norm]

    return {"count": len(parsed), "items": parsed}
