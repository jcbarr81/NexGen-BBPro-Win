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

# Order roughly mirrors the scarcity-aware lineup build sequence.
DEPTH_CHART_POSITIONS: List[str] = [
    "C",
    "SS",
    "CF",
    "3B",
    "2B",
    "1B",
    "LF",
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
