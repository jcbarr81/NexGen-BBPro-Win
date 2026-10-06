"""Depth chart storage and helpers.

Provides lightweight persistence for per-position depth charts so that
automations (lineup autofill, injury handling, etc.) can respect the
owner-set preference order when choosing replacements.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from utils.path_utils import get_data_dir

# Standard scorecard / lineup-style ordering: catcher, infield around the
# horn, then outfield left-to-right, then DH.
DEPTH_CHART_POSITIONS: List[str] = [
    "C",
    "1B",
    "2B",
    "SS",
    "3B",
    "LF",
    "CF",
    "RF",
    "DH",
]
MAX_DEPTH = 3


def _normalize_position(pos: str | None) -> str:
    return (pos or "").strip().upper()


def _chart_dir() -> Path:
    return get_data_dir() / "depth_charts"


def _chart_path(team_id: str) -> Path:
    return _chart_dir() / f"{team_id}.json"


def default_depth_chart() -> Dict[str, List[str]]:
    return {pos: [] for pos in DEPTH_CHART_POSITIONS}


def _sanitize_chart(data: object) -> Dict[str, List[str]]:
    chart = default_depth_chart()
    if not isinstance(data, dict):
        return chart
    for raw_pos, entries in data.items():
        pos = _normalize_position(raw_pos)
        if pos not in chart:
            continue
        if not isinstance(entries, list):
            continue
        cleaned: List[str] = []
        for pid in entries:
            if not isinstance(pid, str):
                continue
            pid = pid.strip()
            if not pid or pid in cleaned:
                continue
            cleaned.append(pid)
            if len(cleaned) >= MAX_DEPTH:
                break
        chart[pos] = cleaned
    return chart


# Charts the sim generated itself. Only these are rebuilt automatically and
# only these are "advisory" for lineups; every other chart -- including any
# that existed before this marker did -- belongs to a person and is never
# overwritten (audit H9 review). Saving a chart by hand removes the mark;
# the Auto-fill button puts it back.
_AUTO_FILE = "_auto.json"


def _auto_path() -> Path:
    return _chart_dir() / _AUTO_FILE


def _auto_set() -> set:
    try:
        data = json.loads(_auto_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(t) for t in data} if isinstance(data, list) else set()


def _write_auto_set(teams: set) -> None:
    path = _auto_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(teams), indent=2), encoding="utf-8")


def mark_depth_chart_auto(team_id: str) -> None:
    """Record that automation generated *team_id*'s chart (refreshable)."""

    teams = _auto_set()
    if str(team_id) not in teams:
        teams.add(str(team_id))
        _write_auto_set(teams)


def mark_depth_chart_manual(team_id: str) -> None:
    """A person saved *team_id*'s chart: automation never rebuilds it."""

    teams = _auto_set()
    if str(team_id) in teams:
        teams.discard(str(team_id))
        _write_auto_set(teams)


def is_depth_chart_auto(team_id: str) -> bool:
    return str(team_id) in _auto_set()


def is_depth_chart_manual(team_id: str) -> bool:
    """A saved chart automation did not generate (or a person since edited)."""

    return has_depth_chart(team_id) and not is_depth_chart_auto(team_id)


def has_depth_chart(team_id: str) -> bool:
    """Whether *team_id* has a saved depth chart (even an empty one)."""

    return _chart_path(team_id).exists()


def load_depth_chart(team_id: str) -> Dict[str, List[str]]:
    path = _chart_path(team_id)
    if not path.exists():
        return default_depth_chart()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_depth_chart()
    return _sanitize_chart(data)


def save_depth_chart(team_id: str, chart: Dict[str, List[str]]) -> None:
    safe_chart = _sanitize_chart(chart)
    path = _chart_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe_chart, indent=2, sort_keys=True), encoding="utf-8")


def depth_order_for_position(chart: Dict[str, List[str]], position: str | None) -> List[str]:
    pos = _normalize_position(position)
    return list(chart.get(pos, []))


__all__ = [
    "DEPTH_CHART_POSITIONS",
    "MAX_DEPTH",
    "default_depth_chart",
    "depth_order_for_position",
    "load_depth_chart",
    "save_depth_chart",
]
