"""Team dashboard endpoints.

Phase 4 focus: the headline metrics and division standings rendered by
``ui/owner_home_page.py`` via ``ui/analytics/quick_metrics.py``. We reuse the
existing Python implementation (no reimplementation in the sidecar) and
surface a trimmed JSON subset tailored to the Electron owner dashboard.

Heavier widgets (bullpen readiness, hot/cold performers, leaders, finance)
land in later Phase 4 iterations.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from ui.analytics.quick_metrics import gather_owner_quick_metrics

from ..security import CurrentIdentity

router = APIRouter(prefix="/teams/{team_id}", tags=["dashboard"], dependencies=[CurrentIdentity])


def _load_roster_and_players(team_id: str):
    """Best-effort load of the team's roster + the player map. Without
    these, ``gather_owner_quick_metrics`` skips the bullpen, hot/cold,
    leaders, and probable-SP widgets entirely (they all early-return on
    a None roster). Failures degrade gracefully by returning ``None``
    so the dashboard still renders the standings + matchup-record bits."""

    try:
        from utils.roster_loader import load_roster

        roster = load_roster(team_id)
    except Exception:
        roster = None
    try:
        from utils.player_loader import load_players_from_csv

        players_list = load_players_from_csv("data/players.csv")
        players = {
            getattr(p, "player_id", ""): p for p in players_list
        }
    except Exception:
        players = None
    return roster, players


def _safe_metrics(team_id: str) -> Dict[str, Any]:
    try:
        roster, players = _load_roster_and_players(team_id)
        return gather_owner_quick_metrics(team_id, roster=roster, players=players)
    except Exception as exc:  # defensive: never let a helper failure 500 the UI
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to gather metrics for {team_id}: {exc}",
        ) from exc


@router.get("/snapshot")
def team_snapshot(team_id: str) -> Dict[str, Any]:
    """Headline numbers for the owner dashboard hero card."""

    metrics = _safe_metrics(team_id)
    return {
        "team_id": team_id,
        "record": metrics.get("record", "--"),
        "run_diff": metrics.get("run_diff", "--"),
        "streak": metrics.get("streak", "--"),
        "last10": metrics.get("last10", "--"),
        "next_opponent": metrics.get("next_opponent", "--"),
        "next_date": metrics.get("next_date", "--"),
        "injuries": metrics.get("injuries", 0),
        "prob_sp": metrics.get("prob_sp"),
    }


@router.get("/division")
def team_division_standings(team_id: str) -> Dict[str, Any]:
    """Division standings table with the caller's team highlighted."""

    metrics = _safe_metrics(team_id)
    division = metrics.get("division_standings") or {"division": "--", "teams": []}
    rows: List[Dict[str, Any]] = []
    for row in division.get("teams", []) or []:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "team_id": row.get("team_id", ""),
                "label": row.get("label") or row.get("name") or row.get("team_id", ""),
                "name": row.get("name") or row.get("label") or row.get("team_id", ""),
                "wins": int(row.get("wins", 0) or 0),
                "losses": int(row.get("losses", 0) or 0),
                "pct": float(row.get("pct", 0.0) or 0.0),
                "gb": str(row.get("gb", "0")),
                "streak": str(row.get("streak", "--")),
                "last10": str(row.get("last10", "--")),
                "is_current": bool(row.get("is_current", False)),
            }
        )
    return {"division": str(division.get("division", "--")), "teams": rows}


def _coerce(value: Any) -> Any:
    """Turn arbitrary nested data into JSON-friendly primitives."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    return str(value)


@router.get("/widgets")
def team_dashboard_widgets(team_id: str) -> Dict[str, Any]:
    """Secondary dashboard widgets: bullpen, matchup, performers, leaders.

    All four come from ``gather_owner_quick_metrics``; we just trim the
    noisy fields and coerce to JSON-safe primitives.
    """

    metrics = _safe_metrics(team_id)
    bullpen = metrics.get("bullpen") or {}
    matchup_raw = metrics.get("matchup") or {}
    performers = metrics.get("performers") or {}
    batting_leaders = metrics.get("batting_leaders") or []
    pitching_leaders = metrics.get("pitching_leaders") or []
    leader_meta = metrics.get("leader_meta") or {}

    # Map quick_metrics' matchup field names to the React MatchupCard's
    # expected shape. The Python helper returns ``record / run_diff /
    # streak / opponent_probable`` but the React reads ``opp_record /
    # opp_run_diff / opp_streak / opp_probable``. Without this mapping
    # the matchup card on the dashboard renders three blank tiles.
    matchup: Dict[str, Any] = {**matchup_raw}
    if "record" in matchup_raw:
        matchup["opp_record"] = matchup_raw["record"]
    if "run_diff" in matchup_raw:
        matchup["opp_run_diff"] = matchup_raw["run_diff"]
    if "streak" in matchup_raw:
        matchup["opp_streak"] = matchup_raw["streak"]
    if "opponent_probable" in matchup_raw:
        matchup["opp_probable"] = matchup_raw["opponent_probable"]

    return {
        "team_id": team_id,
        "bullpen": _coerce(bullpen),
        "matchup": _coerce(matchup),
        "performers": _coerce(performers),
        "batting_leaders": _leader_rows(batting_leaders, leader_meta.get("batting")),
        "pitching_leaders": _leader_rows(pitching_leaders, leader_meta.get("pitching")),
        "leader_meta": _coerce(leader_meta),
    }


def _leader_rows(source: Any, meta: Any) -> List[Dict[str, Any]]:
    """Normalize quick_metrics' dict-or-list leader shape to a flat list.

    The PyQt quick_metrics helper returns these as ``{stat: formatted_value}``
    dicts (plus a parallel ``leader_meta`` with player ids). The Electron
    client expects a list of ``{label, value_text, player_id}`` rows.
    """

    rows: List[Dict[str, Any]] = []
    meta_map = meta if isinstance(meta, dict) else {}
    if isinstance(source, dict):
        for key, value in source.items():
            entry = meta_map.get(key) if isinstance(meta_map.get(key), dict) else {}
            rows.append(
                {
                    "label": str(key),
                    "value_text": _coerce(value),
                    "value": _coerce(entry.get("value")) if entry else None,
                    "player_id": str(entry.get("player_id"))
                    if entry and entry.get("player_id")
                    else None,
                }
            )
        return rows
    if isinstance(source, (list, tuple)):
        for item in source:
            if isinstance(item, dict):
                rows.append(
                    {
                        "label": str(item.get("label") or ""),
                        "value_text": _coerce(item.get("value_text")),
                        "value": _coerce(item.get("value")),
                        "player_id": (
                            str(item.get("player_id"))
                            if item.get("player_id")
                            else None
                        ),
                    }
                )
        return rows
    return rows
