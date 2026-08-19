"""Player list + detail endpoints sourced from ``players.csv``.

The list/detail endpoints surface a trimmed summary so the React table can
render fast. The ``/profile`` endpoint reuses the shared view-model
(``services/player_profile_view_model.py``) -- one source of truth for the
ratings/stats/contract/injury composition -- and serializes it for the
React profile page.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from utils.path_utils import get_base_dir, get_data_dir
from utils.player_loader import load_players_from_csv

from ..schemas import PlayerSummary
from ..security import CurrentIdentity, require_bearer
from ._rating_presentation import compute_overall, rating_context, scale_rating

router = APIRouter(prefix="/players", tags=["players"], dependencies=[CurrentIdentity])

_HEADLINE_RATINGS = ("ch", "ph", "sp", "eye", "arm", "fa", "control", "movement", "endurance")


def _row_raw_int(row: dict, key: str) -> Any:
    """CSV cells come through as strings; coerce to int where possible so
    the shared rating/overall helpers can do arithmetic cleanly."""

    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _row_to_summary(row: dict) -> PlayerSummary:
    is_pitcher = str(row.get("is_pitcher", "")).strip().lower() in {"1", "true", "yes"}
    position = row.get("primary_position") or None

    ratings: Dict[str, Any] = {}
    ratings_context: Dict[str, Dict[str, Any]] = {}
    for key in _HEADLINE_RATINGS:
        raw = _row_raw_int(row, key)
        if raw is None:
            continue
        ratings[key] = scale_rating(
            raw, key=key, position=position, is_pitcher=is_pitcher
        )
        ctx = rating_context(
            raw, key=key, position=position, is_pitcher=is_pitcher
        )
        if ctx is not None:
            ratings_context[key] = ctx

    # PlayerSummary only exposes ``ratings``; the richer fields (context +
    # overall + stars) hang off an extra_data sidecar so clients that care
    # (roster/free-agency/draft pages) can read them while the minimal
    # summary schema stays unchanged.
    summary = PlayerSummary(
        player_id=row.get("player_id", ""),
        first_name=row.get("first_name", ""),
        last_name=row.get("last_name", ""),
        primary_position=row.get("primary_position", ""),
        is_pitcher=is_pitcher,
        bats=row.get("bats", "") or "",
        role=row.get("role", "") or "",
        ratings=ratings,
    )
    return summary


def _iter_players():
    path = get_data_dir() / "players.csv"
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


@router.get("", response_model=List[PlayerSummary])
def list_players(
    position: Optional[str] = Query(default=None, description="Filter by primary_position"),
    pitchers_only: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=5000),
) -> List[PlayerSummary]:
    out: List[PlayerSummary] = []
    for row in _iter_players():
        summary = _row_to_summary(row)
        if pitchers_only and not summary.is_pitcher:
            continue
        if position and summary.primary_position.lower() != position.lower():
            continue
        out.append(summary)
        if len(out) >= limit:
            break
    return out


@router.get("/browse")
def browse_players(
    q: Optional[str] = Query(default=None, description="Substring match on name or id"),
    team_id: Optional[str] = Query(default=None),
    position: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None, description="Hitters/Pitchers/All"),
    free_agents_only: bool = Query(default=False),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> Dict[str, Any]:
    """League-wide player browser with team affiliation joined.

    Walks every team roster once to figure out who plays where (and which
    minors level they're on). Free agents are rows where no team claimed
    them. Filters apply server-side so the React table can stay light.
    """

    from utils.roster_loader import load_roster
    from utils.team_loader import load_teams

    # Build (team_id, level) lookup by walking each team's roster.
    affiliation: Dict[str, Dict[str, str]] = {}
    try:
        for team in load_teams():
            try:
                roster = load_roster(team.team_id)
            except Exception:
                continue
            for level, ids in (
                ("ACT", roster.act),
                ("AAA", roster.aaa),
                ("LOW", roster.low),
                ("DL", roster.dl),
                ("IR", roster.ir),
            ):
                for pid in ids:
                    affiliation.setdefault(
                        pid, {"team_id": team.team_id, "level": level}
                    )
    except Exception:
        affiliation = {}

    needle = q.strip().lower() if q else ""
    role_norm = role.strip().lower() if role else ""

    rows: List[Dict[str, Any]] = []
    for row in _iter_players():
        summary = _row_to_summary(row)
        if position and summary.primary_position.lower() != position.lower():
            continue
        if role_norm == "hitters" and summary.is_pitcher:
            continue
        if role_norm == "pitchers" and not summary.is_pitcher:
            continue

        affil = affiliation.get(summary.player_id)
        team = affil["team_id"] if affil else ""
        level = affil["level"] if affil else "FA"

        if free_agents_only and team:
            continue
        if team_id and team != team_id:
            continue
        if needle:
            haystack = (
                f"{summary.first_name} {summary.last_name} {summary.player_id}".lower()
            )
            if needle not in haystack:
                continue

        # Re-run the rating context + overall helpers to attach them to
        # the browse payload. PlayerSummary doesn't carry these fields;
        # list_players() callers that need them should consume this
        # endpoint's richer dict instead.
        position_raw = row.get("primary_position") or None
        context_map: Dict[str, Dict[str, Any]] = {}
        for key in _HEADLINE_RATINGS:
            raw = _row_raw_int(row, key)
            if raw is None:
                continue
            ctx = rating_context(
                raw,
                key=key,
                position=position_raw,
                is_pitcher=summary.is_pitcher,
            )
            if ctx is not None:
                context_map[key] = ctx
        overall = compute_overall(
            lambda k: _row_raw_int(row, k),
            is_pitcher=summary.is_pitcher,
            position=position_raw,
        )

        rows.append(
            {
                **summary.model_dump(),
                "team_id": team,
                "level": level,
                "ratings_context": context_map,
                "overall_raw": overall["overall_raw"],
                "overall_display": overall["overall_display"],
                "overall_stars_text": overall["overall_stars_text"],
            }
        )
        if len(rows) >= limit:
            break
    rows.sort(key=lambda r: (r["last_name"], r["first_name"]))
    return {"count": len(rows), "players": rows}


@router.get("/{player_id}", response_model=PlayerSummary)
def get_player(player_id: str) -> PlayerSummary:
    for row in _iter_players():
        if row.get("player_id") == player_id:
            return _row_to_summary(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")


@router.get("/{player_id}/avatar")
def get_player_avatar(player_id: str) -> FileResponse:
    """Serve the generated avatar PNG for *player_id*.

    Avatars are produced by utils.avatar_generator and saved under
    <data_dir>/images/avatars/<player_id>.png. Falls back to the bundled
    default.png when a per-player image hasn't been generated yet, so the
    client can always render something.
    """

    clean = "".join(ch for ch in player_id if ch.isalnum() or ch in {"-", "_"})
    if not clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid player id")

    candidates = [
        get_data_dir() / "images" / "avatars" / f"{clean}.png",
        get_data_dir() / "images" / "avatars" / "default.png",
        get_base_dir() / "images" / "avatars" / "default.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return FileResponse(
                str(candidate),
                media_type="image/png",
                headers={"Cache-Control": "no-cache"},
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")


@router.post("/{player_id}/avatar/regenerate")
def regenerate_player_avatar(
    player_id: str,
    identity: Dict[str, Any] = CurrentIdentity,
) -> Dict[str, Any]:
    """Regenerate a single player's avatar via the AI engine. SUPER-ADMIN ONLY
    (platform owner) — lets the admin spot-check the look/colors for pennies
    before committing to a full-league regenerate. Persists to durable storage.
    """
    if not identity.get("super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform-admin (super-admin) access required.",
        )
    try:
        from utils.avatar_generator import regenerate_one_avatar

        regenerate_one_avatar(player_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Avatar generation failed: {exc}",
        ) from exc

    # Persist to GCS so the new avatar survives a restart.
    try:
        from api import working_copy

        if working_copy.is_enabled():
            working_copy.push_changes()
    except Exception:
        logging.getLogger("nexgen.avatars").exception("avatar push failed")

    return {"player_id": player_id, "ok": True}


def _coerce(value: Any) -> Any:
    """Recursively turn dataclasses / tuples / sets into JSON-friendly forms."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return _coerce(asdict(value))
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    return str(value)


@router.get("/{player_id}/profile")
def get_player_profile(
    player_id: str,
    identity: Dict[str, Any] = Depends(require_bearer),
) -> Dict[str, Any]:
    """Hydrate a player and run the existing v2 view-model builder.

    Non-admin viewers see only Scouted + Stars in the overall detail card,
    so raw/uncalibrated underlying ratings stay hidden from team owners.
    """

    try:
        from services.player_profile_view_model import build_player_profile_view_model
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile view-model unavailable: {exc}",
        ) from exc

    try:
        players = load_players_from_csv("data/players.csv")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load players.csv: {exc}",
        ) from exc

    player = next((p for p in players if getattr(p, "player_id", "") == player_id), None)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found.",
        )

    try:
        view_model = build_player_profile_view_model(player)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build profile: {exc}",
        ) from exc

    payload = _coerce(view_model)

    # Contract meta for owner option/renew actions (finance Phase 3). Raw fields
    # the pre-formatted contract_details rows don't carry: the option list, and
    # the service-time / arb-eligibility that decide pre-arb renewal.
    try:
        from services.contracts_service import (
            _normalize_contract,
            load_contracts_payload,
        )

        _craw = (load_contracts_payload().get("players") or {}).get(player_id)
        if isinstance(_craw, dict):
            _c = _normalize_contract(_craw)
            payload["contract_meta"] = {
                "team_id": str(_c.get("team_id") or ""),
                "annual_salary": int(_c.get("annual_salary") or 0),
                "service_time_days": int(_c.get("service_time_days") or 0),
                "arb_eligible": bool(_c.get("arb_eligible")),
                "options": list(_c.get("options") or []),
            }
    except Exception:
        pass

    role = str(identity.get("r", "")).lower()
    if role != "admin":
        details = payload.get("overall_details")
        if isinstance(details, list):
            # Strip the inner-game (Raw) and pre-scouting (Displayed) rows
            # so owners only see Scouted + Stars. Admins still see the
            # full breakdown for tuning/verification.
            payload["overall_details"] = [
                row
                for row in details
                if isinstance(row, list)
                and len(row) >= 1
                and str(row[0]).strip().lower() not in {"raw", "displayed"}
            ]

    # Inject this year's spring training deltas (if any) so the career
    # ledger can render "(+x)" hints next to the most-recent rating row.
    try:
        import json as _json

        from utils.path_utils import get_data_dir

        deltas_path = get_data_dir() / "spring_training_last.json"
        if deltas_path.exists():
            try:
                blob = _json.loads(deltas_path.read_text(encoding="utf-8"))
            except Exception:
                blob = {}
            entry = (blob.get("players") or {}).get(player_id) if isinstance(blob, dict) else None
            if isinstance(entry, dict):
                payload["spring_training_gains"] = {
                    "year": blob.get("year"),
                    "focus": entry.get("focus"),
                    "changes": entry.get("changes") or {},
                }
    except Exception:
        pass

    return payload
