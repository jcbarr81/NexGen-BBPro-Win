"""A fixed scratch league, and every payload that shows an owner a rating.

For test_rating_scale_display.py: :func:`build_display_league` writes the
league fixture (``data/calibration_league``) as a league directory, on rating
scale 1 or as its scale 2 twin, with a draft class, a draft under way, a few
contracts and one archived season; :func:`display_payloads` calls every
endpoint that shows a rating or an overall, in process, and returns what each
one serves. Everything is written under the caller's temporary directory.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from tests import rating_scale_support as support
from utils.rating_scale import FULL_RATING_SCALE, stretch_rows

LEAGUE = "displaytest"
SOURCE = support.FIXTURES["calibration_league"]
DRAFT_YEAR = 2027
ARCHIVED_SEASON = "displaytest-2025"
# Fields of a draft class entry (playbalance.draft_pool.DraftProspect).
_PROSPECT_TEXT = (
    "first_name", "last_name", "bats", "throws", "primary_position",
    "birthdate", "preferred_pitching_role",
)
_PROSPECT_NUMBERS = (
    "ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm",
    "endurance", "control", "movement", "hold_runner",
    "fb", "cu", "cb", "sl", "si", "scb", "kn",
)
# Players whose profile the payloads include: the first hitters and pitchers
# of the first club, and the club's best of each (picked from the file, so
# the list does not depend on any code under test).
PROFILE_COUNT = 4


def _int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _draft_class(rows: List[Dict[str, str]], levels: Dict[str, str]) -> List[Dict[str, Any]]:
    """40 prospects copied from the fixture's low-level players, new ids."""

    picked = [r for r in rows if levels.get(r["player_id"]) == "LOW"][:40]
    pool: List[Dict[str, Any]] = []
    for index, row in enumerate(picked):
        entry: Dict[str, Any] = {"player_id": f"D{DRAFT_YEAR}{index:04d}"}
        for key in _PROSPECT_TEXT:
            entry[key] = row.get(key, "") or ""
        entry["is_pitcher"] = row.get("is_pitcher", "0").strip() in {"1", "true", "True"}
        for key in _PROSPECT_NUMBERS:
            entry[key] = _int(row.get(key, "0"))
        for key in ("ch", "ph", "eye", "fa", "arm", "control", "movement"):
            entry[f"pot_{key}"] = _int(row.get(f"pot_{key}", "0"))
        pool.append(entry)
    return pool


def _levels(data: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in sorted((data / "rosters").glob("*.csv")):
        if "_" in path.stem:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    return out


def build_display_league(root: Path, *, scale: int = 1) -> Path:
    """Write the league under ``root`` (``root/leagues/<id>/data``) on
    rating ``scale``; returns its data directory. Every file the data-dir
    resolver would otherwise seed from the repo is written first."""

    root = Path(root)
    data = root / "leagues" / LEAGUE / "data"
    data.mkdir(parents=True)
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    support.copy_league(SOURCE, data)  # scale 1, blank pitch grades as 0
    (data / "users.txt").write_text("admin,pass,admin,\n", encoding="utf-8")
    fields, rows = support.read_player_rows(data / "players.csv")
    levels = _levels(data)

    # One archived season (the same players, on scale 1, as any league that
    # moved to scale 2 at its next season will have).
    season_dir = data / "careers" / ARCHIVED_SEASON
    season_dir.mkdir(parents=True)
    shutil.copy(data / "players.csv", season_dir / "players.csv")
    (data / "career_index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "league": {"id": LEAGUE, "name": "Display test"},
                "current": {"season_id": f"{LEAGUE}-2026", "league_year": 2026},
                "seasons": [{"season_id": ARCHIVED_SEASON, "league_year": 2025}],
            }
        ),
        encoding="utf-8",
    )

    pool = _draft_class(rows, levels)
    teams = [line.split(",")[0] for line in (data / "teams.csv").read_text(
        encoding="utf-8").splitlines()[1:] if line.strip()]
    first_pick_player = next(r["player_id"] for r in rows if levels.get(r["player_id"]) == "AAA")
    (data / f"draft_state_{DRAFT_YEAR}.json").write_text(
        json.dumps(
            {
                "year": DRAFT_YEAR,
                "round": 1,
                "overall_pick": 3,
                "order": teams,
                "selected": [
                    {"overall": 1, "round": 1, "team_id": teams[0],
                     "player_id": first_pick_player},
                    {"overall": 2, "round": 1, "team_id": teams[1],
                     "player_id": pool[0]["player_id"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    contracts = {
        r["player_id"]: {
            "team_id": teams[0],
            "annual_salary": 1_000_000 + 10_000 * index,
            "years_left": 1 + index % 3,
        }
        for index, r in enumerate(
            r for r in rows if levels.get(r["player_id"]) == "ACT"
        )
        if index < 12
    }
    (data / "contracts.json").write_text(
        json.dumps({"version": 1, "players": contracts}), encoding="utf-8"
    )

    if scale == FULL_RATING_SCALE:
        support.stretch_players_file(data / "players.csv", data / "players.csv")
        pool, _clips = stretch_rows(pool, FULL_RATING_SCALE)
    (data / f"draft_pool_{DRAFT_YEAR}.json").write_text(
        json.dumps(pool, indent=2), encoding="utf-8"
    )
    return data


def profile_ids(data: Path) -> List[str]:
    """The players whose profile :func:`display_payloads` includes."""

    _fields, rows = support.read_player_rows(data / "players.csv")
    levels = _levels(data)
    act = [r for r in rows if levels.get(r["player_id"]) == "ACT"]
    hitters = [r for r in act if r["is_pitcher"].strip() not in {"1", "true", "True"}]
    pitchers = [r for r in act if r["is_pitcher"].strip() in {"1", "true", "True"}]
    ids = [r["player_id"] for r in hitters[:2] + pitchers[:2]]
    low = [r for r in rows if levels.get(r["player_id"]) == "LOW"]
    ids.append(low[0]["player_id"])
    return ids


def _first_team(data: Path) -> List[str]:
    lines = (data / "teams.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [line.split(",")[0] for line in lines if line.strip()]


def display_payloads(data: Path) -> Dict[str, Any]:
    """endpoint -> what it serves, for every page that shows a rating.

    The data dir must already be the request's (``NEXGEN_DATA_ROOT`` and
    ``set_request_league``)."""

    from api.routers import contracts, draft, free_agency, help, players, roster

    teams = _first_team(data)
    out: Dict[str, Any] = {}
    for team_id in teams[:3]:
        out[f"roster/{team_id}"] = roster.team_roster(team_id)
    out["players/list"] = [
        s.model_dump()
        for s in players.list_players(position=None, pitchers_only=False, limit=5000)
    ]
    out["players/browse"] = players.browse_players(
        q=None, team_id=None, position=None, role=None,
        free_agents_only=False, limit=10000,
    )
    out["free-agents"] = free_agency.list_free_agents(limit=1000)
    out["draft/pool"] = draft.draft_pool_view(
        year=DRAFT_YEAR, available_only=False, limit=5000
    )
    state = draft.draft_state_view(year=DRAFT_YEAR)
    out["draft/state.selected"] = state["selected"]
    out["contracts"] = contracts.list_contracts(team_id=None, expiring_only=False)
    for pid in profile_ids(data):
        out[f"profile/{pid}"] = players.get_player_profile(pid, identity={"r": "admin"})
    out["help/tutorials"] = help.tutorials()
    return out


# What a display change can move, per payload (the rest of each payload --
# ages, dates, contract terms -- is the date or other features).
_PLAYER_FIELDS = (
    "player_id", "ratings", "ratings_context",
    "overall_raw", "overall_display", "overall_stars_text", "overall",
)
_PROFILE_FIELDS = (
    "overall_display", "overall_stars_text", "overall_details",
    "defense_ratings", "overview_ratings", "rating_help",
)


def _pick(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row[key] for key in _PLAYER_FIELDS if key in row}


def display_projection(payloads: Dict[str, Any]) -> Dict[str, Any]:
    """The rating and overall fields of :func:`display_payloads`, nothing
    that depends on today's date; the tutorials are left out (their text
    changes with every release)."""

    out: Dict[str, Any] = {}
    for name, payload in payloads.items():
        if name.startswith("roster/"):
            out[name] = {
                level: [_pick(p) for p in group]
                for level, group in payload["levels"].items()
            }
        elif name == "players/list":
            out[name] = [_pick(p) for p in payload]
        elif name == "players/browse":
            out[name] = [_pick(p) for p in payload["players"]]
        elif name == "free-agents":
            out[name] = [_pick(p) for p in payload["free_agents"]]
        elif name == "draft/pool":
            out[name] = [_pick(p) for p in payload["prospects"]]
        elif name == "draft/state.selected":
            out[name] = [_pick(p) for p in payload]
        elif name == "contracts":
            out[name] = [_pick(p) for p in payload["contracts"]]
        elif name.startswith("profile/"):
            entry = {key: payload.get(key) for key in _PROFILE_FIELDS}
            entry["ratings_history"] = [
                row.get("ratings") for row in payload.get("ratings_history") or []
            ]
            out[name] = entry
    return out


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "DRAFT_YEAR",
    "LEAGUE",
    "build_display_league",
    "canonical",
    "display_payloads",
    "display_projection",
    "profile_ids",
]
