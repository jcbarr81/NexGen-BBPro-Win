"""League-wide draft pick ownership helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Dict, Iterable, List, MutableMapping, Tuple

from playbalance.draft_config import load_draft_config
from playbalance.season_context import SeasonContext
from services.trade_settings import current_league_year, load_trade_settings
from utils.path_utils import get_data_dir
from utils.team_loader import load_teams

__all__ = [
    "DraftPick",
    "format_pick_label",
    "get_pick_owner",
    "list_team_picks",
    "list_team_tradable_picks",
    "make_pick_id",
    "parse_pick_id",
    "transfer_pick",
]

VERSION = 1
LEDGER_PATH = get_data_dir() / "draft_pick_ledger.json"


@dataclass(frozen=True)
class DraftPick:
    pick_id: str
    year: int
    round_no: int
    original_team: str
    owner_team: str


def make_pick_id(year: int, round_no: int, original_team: str) -> str:
    return f"{int(year)}|{int(round_no)}|{str(original_team).strip()}"


def parse_pick_id(pick_id: str) -> Tuple[int, int, str]:
    token = str(pick_id or "").strip()
    parts = token.split("|")
    if len(parts) != 3:
        raise ValueError(f"Invalid draft pick id: {pick_id!r}")
    year = int(parts[0])
    round_no = int(parts[1])
    original_team = parts[2].strip()
    if year < 1900 or round_no < 1 or not original_team:
        raise ValueError(f"Invalid draft pick id: {pick_id!r}")
    return year, round_no, original_team


def format_pick_label(pick_id: str) -> str:
    year, round_no, original_team = parse_pick_id(pick_id)
    return f"{year} Round {round_no} ({original_team})"


def list_team_tradable_picks(team_id: str) -> List[DraftPick]:
    settings = load_trade_settings()
    base_year = current_league_year()
    years = [
        base_year + offset
        for offset in range(1, max(1, int(settings.max_pick_trade_years)) + 1)
    ]
    return list_team_picks(team_id, years=years)


def list_team_picks(team_id: str, *, years: Iterable[int] | None = None) -> List[DraftPick]:
    normalized_team = str(team_id or "").strip()
    if not normalized_team:
        return []

    if years is None:
        years = [current_league_year() + 1]
    year_values = sorted({int(y) for y in years if int(y) >= 1900})
    if not year_values:
        return []

    payload = _load_payload()
    league_id = _resolve_league_id()
    picks = _league_pick_map(payload, league_id)
    _seed_missing_picks(picks, year_values)
    _write_payload(payload)

    owned: List[DraftPick] = []
    for pick_id, owner_team in picks.items():
        if str(owner_team) != normalized_team:
            continue
        try:
            year, round_no, original_team = parse_pick_id(pick_id)
        except ValueError:
            continue
        if year not in year_values:
            continue
        owned.append(
            DraftPick(
                pick_id=pick_id,
                year=year,
                round_no=round_no,
                original_team=original_team,
                owner_team=str(owner_team),
            )
        )
    owned.sort(key=lambda p: (p.year, p.round_no, p.original_team))
    return owned


def get_pick_owner(year: int, round_no: int, original_team: str) -> str:
    pick_id = make_pick_id(year, round_no, original_team)
    payload = _load_payload()
    league_id = _resolve_league_id()
    picks = _league_pick_map(payload, league_id)
    _seed_missing_picks(picks, [int(year)])
    owner = str(picks.get(pick_id) or str(original_team))
    picks[pick_id] = owner
    _write_payload(payload)
    return owner


def transfer_pick(pick_id: str, from_team: str, to_team: str) -> None:
    normalized_from = str(from_team or "").strip()
    normalized_to = str(to_team or "").strip()
    if not normalized_from or not normalized_to:
        raise ValueError("Both source and destination teams are required.")

    year, round_no, original_team = parse_pick_id(pick_id)
    payload = _load_payload()
    league_id = _resolve_league_id()
    picks = _league_pick_map(payload, league_id)
    _seed_missing_picks(picks, [year])

    canonical_id = make_pick_id(year, round_no, original_team)
    current_owner = str(picks.get(canonical_id) or original_team)
    if current_owner != normalized_from:
        raise ValueError(
            f"{format_pick_label(canonical_id)} is owned by {current_owner}, "
            f"not {normalized_from}."
        )
    picks[canonical_id] = normalized_to
    _write_payload(payload)


def _seed_missing_picks(pick_map: MutableMapping[str, object], years: Iterable[int]) -> None:
    team_ids = _team_ids()
    if not team_ids:
        return
    rounds = _draft_rounds()
    for year in years:
        season_year = int(year)
        if season_year < 1900:
            continue
        for round_no in range(1, rounds + 1):
            for team_id in team_ids:
                pick_id = make_pick_id(season_year, round_no, team_id)
                pick_map.setdefault(pick_id, team_id)


def _team_ids() -> List[str]:
    try:
        return [str(t.team_id) for t in load_teams() if getattr(t, "team_id", None)]
    except Exception:
        return []


def _draft_rounds() -> int:
    try:
        cfg = load_draft_config()
        rounds = int(cfg.get("rounds", 10) or 10)
    except Exception:
        rounds = 10
    return max(1, rounds)


def _resolve_league_id() -> str:
    try:
        ctx = SeasonContext.load()
        league_id = ctx.league_id
        if league_id:
            return league_id
        return ctx.ensure_league()
    except Exception:
        return "league"


def _load_payload() -> Dict[str, object]:
    if LEDGER_PATH.exists():
        try:
            data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _league_pick_map(payload: MutableMapping[str, object], league_id: str) -> MutableMapping[str, object]:
    leagues = payload.setdefault("leagues", {})
    if not isinstance(leagues, MutableMapping):
        payload["leagues"] = {}
        leagues = payload["leagues"]  # type: ignore[assignment]
    league_payload = leagues.setdefault(league_id, {})
    if not isinstance(league_payload, MutableMapping):
        leagues[league_id] = {}
        league_payload = leagues[league_id]  # type: ignore[assignment]
    picks = league_payload.setdefault("picks", {})
    if not isinstance(picks, MutableMapping):
        league_payload["picks"] = {}
        picks = league_payload["picks"]  # type: ignore[assignment]
    return picks


def _write_payload(payload: MutableMapping[str, object]) -> None:
    payload["version"] = VERSION
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
