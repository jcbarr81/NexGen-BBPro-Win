"""Playoffs endpoints.

Reads the persisted ``playoffs_<year>.json`` documents produced by the main
app's playoff flow. Returns them mostly as-is plus a list of years we have
data for, so the React bracket page can render without further shaping.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from utils.path_utils import get_data_dir

from ..security import CurrentIdentity, require_bearer

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


def _self_heal_bracket_if_missing() -> bool:
    """Regenerate the playoff bracket if the league is in PLAYOFFS but no
    ``playoffs_<year>.json`` exists.

    The bracket is written once, during the REGULAR_SEASON -> PLAYOFFS
    transition. If that write is ever lost (a background-sim write that misses
    the working-copy push cutoff, an interrupted transition, etc.) the league is
    stranded in PLAYOFFS with an empty page and no way forward. Re-seeding here
    from the final standings — using the league's stored PlayoffsConfig, so the
    commissioner's format is preserved — makes the postseason self-healing.

    Returns True if it generated (and persisted) a bracket. No-op unless the
    phase is PLAYOFFS and no bracket is present.
    """

    import logging

    log = logging.getLogger("nexgen.playoffs")

    if _list_years():
        return False
    try:
        from playbalance.season_manager import SeasonManager, SeasonPhase

        phase = SeasonManager().phase
        if phase != SeasonPhase.PLAYOFFS:
            log.warning("[playoff-heal] skip: phase=%s (not PLAYOFFS)", getattr(phase, "value", phase))
            return False
    except Exception:
        log.exception("[playoff-heal] phase check failed")
        return False

    # Standings sync is best-effort — a failure here must not block the heal.
    try:
        from api.routers.season import _sync_standings_from_stats

        _sync_standings_from_stats()
    except Exception:
        log.exception("[playoff-heal] standings sync failed (continuing)")

    try:
        from api.routers.season import _ensure_playoff_bracket

        result = _ensure_playoff_bracket()
    except Exception:
        log.exception("[playoff-heal] _ensure_playoff_bracket raised")
        return False

    log.warning("[playoff-heal] ensure result=%r", result)
    if not isinstance(result, dict) or result.get("error") or not (
        result.get("saved") or result.get("reused_existing")
    ):
        return False

    # Persist immediately — the whole reason we're here is a lost write, so don't
    # rely on a later mutating request to push the freshly-seeded bracket.
    try:
        from api import working_copy

        if working_copy.is_enabled():
            working_copy.push_changes()
    except Exception:
        pass
    return True


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
    if not years and _self_heal_bracket_if_missing():
        years = _list_years()
    return {"years": years, "latest": years[0] if years else None}


@router.get("")
def playoffs_view(
    year: Optional[int] = Query(default=None, description="Defaults to most recent"),
) -> Dict[str, Any]:
    if year is None:
        years = _list_years()
        if not years and _self_heal_bracket_if_missing():
            years = _list_years()
        if not years:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No playoffs data available.",
            )
        year = years[0]
    return _load_year(year)


def _run_playoff_sim(mode: str) -> Dict[str, Any]:
    """Advance the current playoff bracket and return its new state.

    Reuses the battle-tested engine in ``playbalance.playoffs`` (same code the
    legacy UI and the long-term sim drive). Each function mutates the bracket
    in place and persists via ``save_bracket``; we return ``to_dict`` so the
    page can re-render immediately.

    ``mode``: ``"game"`` (one game per active series), ``"round"`` (the next
    round with pending series), or ``"all"`` (run to a champion).
    """

    from playbalance import playoffs as _pf

    bracket = _pf.load_bracket()
    if bracket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No playoff bracket to simulate. Advance the season into the "
                "Playoffs first."
            ),
        )

    # Already finished — no-op so a stray click just refreshes the view.
    if str(getattr(bracket, "champion", "") or "").strip():
        return {
            "bracket": bracket.to_dict(),
            "champion": bracket.champion,
            "complete": True,
            "changed": False,
        }

    try:
        if mode == "game":
            _pf.simulate_next_game(bracket)
        elif mode == "round":
            _pf.simulate_next_round(bracket)
        else:  # "all"
            _pf.simulate_playoffs(bracket)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Playoff simulation failed: {exc}",
        ) from exc

    champion = str(getattr(bracket, "champion", "") or "").strip() or None
    return {
        "bracket": bracket.to_dict(),
        "champion": champion,
        "complete": champion is not None,
        "changed": True,
    }


@router.post("/simulate/game")
def simulate_playoff_game(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Simulate the next playoff day — one game per active series."""

    return _run_playoff_sim("game")


@router.post("/simulate/round")
def simulate_playoff_round(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Simulate the next round that still has unfinished series."""

    return _run_playoff_sim("round")


@router.post("/simulate/all")
def simulate_playoff_all(
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Simulate the remaining playoffs through to a champion."""

    return _run_playoff_sim("all")


def _playoff_games_played(bracket) -> bool:
    for rnd in getattr(bracket, "rounds", []) or []:
        for m in getattr(rnd, "matchups", []) or []:
            for g in getattr(m, "games", []) or []:
                if str(getattr(g, "result", "") or "").strip():
                    return True
    return False


_ALLOWED_FIELD_SIZES = {2, 4, 6, 8}


@router.post("/rebuild")
def rebuild_bracket(
    payload: Dict[str, Any] = Body(default_factory=dict),
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Regenerate the current playoff bracket from final standings.

    Optionally sets the playoff field size (``num_playoff_teams``, default 4)
    and persists it to the league's playoffs_config.json so future seasons keep
    the same shape. A 4-team field yields a clean, symmetric bracket (Division
    Series 1v4 / 2v3 → Championship Series) with no odd wildcard play-in.

    Safe-guarded: refuses if any playoff game already has a result, so a
    postseason in progress can't be wiped.
    """

    from playbalance import playoffs as _pf

    existing = _pf.load_bracket()
    if existing is not None and _playoff_games_played(existing):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Playoff games have already been played — rebuilding would "
                "wipe results. Can't rebuild a postseason in progress."
            ),
        )

    # Standings feed the seeding; make sure they reflect the finished season.
    try:
        from api.routers.season import _sync_standings_from_stats

        _sync_standings_from_stats()
    except Exception:
        pass

    try:
        from utils.team_loader import load_teams
        from playbalance.playoffs_config import (
            load_playoffs_config,
            save_playoffs_config,
        )

        teams = load_teams()
        standings = _pf._load_standings_snapshot()
        cfg = load_playoffs_config()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load data for rebuild: {exc}",
        ) from exc

    if not teams or not standings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Standings or teams are missing — can't seed a bracket yet.",
        )

    # Apply + persist the requested field size (default 4 for a clean bracket).
    field_size = payload.get("num_playoff_teams", 4)
    try:
        field_size = int(field_size)
    except (TypeError, ValueError):
        field_size = 4
    if field_size in _ALLOWED_FIELD_SIZES:
        cfg.num_playoff_teams_per_league = field_size
        try:
            save_playoffs_config(cfg)
        except Exception:
            pass

    bracket = _pf.generate_bracket(standings, teams, cfg)
    _pf.save_bracket(bracket)
    return {
        "bracket": bracket.to_dict(),
        "rebuilt": True,
        "num_playoff_teams": cfg.num_playoff_teams_per_league,
    }
