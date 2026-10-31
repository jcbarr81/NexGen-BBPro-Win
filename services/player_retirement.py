"""Yearly player retirement.

Runs once per offseason (called from ``LeagueRolloverService``). For each
player on any team's roster, decides whether to retire them based on age
and current overall rating. Retirees are:

  - Removed from their team's roster
  - Released from any active contract
  - Recorded to ``retired_players.json`` so the FA list filters them out
    going forward and the UI can render a Retirements section
  - Surfaced as a ``retirement`` news event so the league feed reflects
    the move

Unsigned free agents are considered too (backlog #52a, 8.6.5): a veteran
nobody signed usually hangs it up, and a player nobody signed all season
often quits at any age.

How it decides (backlog #52a, 8.6.5). Each player has a chance of retiring
that climbs with age (``_ACT_CHANCE_BY_AGE``, close to the real game: hardly
anyone before 31, about half at 39). The minors and free agency read the same
curve some years older (``_AGE_OFFSET``): a 30-year-old still in AAA is where
a 34-year-old big leaguer is. The chance is then scaled by how good the
player is against the others at his level IN HIS OWN LEAGUE (a percentile,
so it means the same on either rating scale and as ratings drift): a top
player's chance is about a third of the average, a bottom one's nearly three
times it. A big leaguer with more than this year left on his deal is a
little less likely to walk away from the money.

The roll is not random: it is drawn from the player's id and the season
(``_draw``), so running the same offseason twice retires the same players.

The rules before 8.6.5 were fixed (age, OVR) bars of 45-99 that engine-scale
overalls (big leaguers ~49-57) almost never reach, so everyone past an age
retired whatever his quality, and free agents never retired at all.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from playbalance.aging import calculate_age
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.player_overall import player_overall_score

# A big leaguer's yearly chance of retiring, by age, for an average player
# at his level. Ages below the first entry carry no chance; ages past the
# last use the last.
_ACT_CHANCE_BY_AGE: Dict[int, float] = {
    31: 0.02,
    32: 0.04,
    33: 0.07,
    34: 0.11,
    35: 0.16,
    36: 0.23,
    37: 0.31,
    38: 0.40,
    39: 0.50,
    40: 0.60,
    41: 0.70,
    42: 0.78,
    43: 0.85,
    44: 0.90,
    45: 0.95,
}

# The minors and free agency read the big-league curve this many years
# older. The injured lists are big leaguers.
_AGE_OFFSET: Dict[str, int] = {
    "ACT": 0,
    "DL": 0,
    "IR": 0,
    "AAA": 4,
    "LOW": 9,
    "FA": 2,
    "FA_NEW": 2,
}

# Unsigned: nobody wanted him this winter.
_FREE_AGENT_FACTOR = 1.5
# Unsigned through the whole season just ended (not a contract that ran
# out at this rollover): an average one quits at least this often, at any
# age, before the quality scaling. Released minor leaguers mostly do.
_IDLE_FREE_AGENT_CHANCE = 0.25
# A big leaguer with more than the coming season left on his contract.
_MULTI_YEAR_CONTRACT_FACTOR = 0.6
_MAX_CHANCE = 0.97

# Quality scaling: chance x 2 ** (_QUALITY_SPREAD * (0.5 - percentile)).
# The median player keeps the curve; the best about x0.35, the worst
# about x2.8.
_QUALITY_SPREAD = 3.0

# A level with fewer players than this has no meaningful ranking; everyone
# on it counts as average.
_MIN_RANKED = 5

# A free agent through the season just ended, and one whose contract ran
# out at this rollover.
FREE_AGENT = "FA"
NEW_FREE_AGENT = "FA_NEW"
_FREE_AGENT_LEVELS = {FREE_AGENT, NEW_FREE_AGENT}


def _level_group(level: Optional[str]) -> str:
    """The pool a player is ranked in: the big leagues (with the injured
    lists), AAA or LOW. A free agent is measured against big leaguers."""

    norm = (level or "ACT").strip().upper()
    if norm in {"AAA", "LOW"}:
        return norm
    return "ACT"


def _age_chance(age: int, level: str) -> float:
    effective = int(age) + _AGE_OFFSET.get(level, 0)
    if effective < min(_ACT_CHANCE_BY_AGE):
        return 0.0
    return _ACT_CHANCE_BY_AGE[min(effective, max(_ACT_CHANCE_BY_AGE))]


def retirement_chance(
    age: Optional[int],
    level: Optional[str] = None,
    percentile: float = 0.5,
    *,
    multi_year_contract: bool = False,
) -> float:
    """The chance (0-1) that a player of ``age`` on ``level`` (ACT, DL, IR,
    AAA, LOW, ``"FA"`` for a free agent unsigned all season or ``"FA_NEW"``
    for one whose contract just ran out) retires this offseason.

    ``percentile`` is where his overall ranks among the players at his level
    in his league (0 the worst, 1 the best; see :func:`level_percentiles`).
    """

    if age is None:
        return 0.0
    norm = (level or "ACT").strip().upper()
    chance = _age_chance(age, norm)
    if norm in _FREE_AGENT_LEVELS:
        chance *= _FREE_AGENT_FACTOR
    if norm == FREE_AGENT:
        chance = max(chance, _IDLE_FREE_AGENT_CHANCE)
    if chance <= 0.0:
        return 0.0
    p = min(1.0, max(0.0, float(percentile)))
    chance *= 2.0 ** (_QUALITY_SPREAD * (0.5 - p))
    if norm not in _FREE_AGENT_LEVELS and multi_year_contract:
        chance *= _MULTI_YEAR_CONTRACT_FACTOR
    return min(_MAX_CHANCE, chance)


def level_percentiles(
    scores: Mapping[str, tuple[str, Optional[float]]],
) -> Dict[str, float]:
    """``{player_id: percentile}`` from ``{player_id: (level, overall)}``.

    Players are ranked within their level group (big leagues with the
    injured lists, AAA, LOW); a free agent (level ``"FA"`` or ``"FA_NEW"``)
    is placed among the big leaguers without joining their pool. Ties share the middle of
    their rank. A player without an overall, or on a level with fewer than
    ``_MIN_RANKED`` rated players, counts as average (0.5).
    """

    pools: Dict[str, List[float]] = {}
    for level, score in scores.values():
        if score is None or (level or "").strip().upper() in _FREE_AGENT_LEVELS:
            continue
        pools.setdefault(_level_group(level), []).append(float(score))
    for pool in pools.values():
        pool.sort()

    from bisect import bisect_left, bisect_right

    out: Dict[str, float] = {}
    for pid, (level, score) in scores.items():
        pool = pools.get(_level_group(level), [])
        if score is None or len(pool) < _MIN_RANKED:
            out[pid] = 0.5
            continue
        below = bisect_left(pool, float(score))
        ties = bisect_right(pool, float(score)) - below
        out[pid] = (below + ties / 2.0) / len(pool)
    return out


def _draw(player_id: str, season_year: int) -> float:
    """A uniform number in [0, 1) fixed by the player and the season."""

    digest = hashlib.sha256(f"retire:{player_id}:{int(season_year)}".encode()).hexdigest()
    return int(digest[:13], 16) / float(16 ** 13)

_RETIREES_FILENAME = "retired_players.json"


def _retirees_path(data_dir: Optional[Path] = None) -> Path:
    return (data_dir or get_data_dir()) / _RETIREES_FILENAME


def load_retirees(data_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Return the retirees registry, keyed by player_id."""

    path = _retirees_path(data_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): dict(v) for k, v in payload.items() if isinstance(v, dict)}


def save_retirees(
    registry: Dict[str, Dict[str, Any]],
    *,
    data_dir: Optional[Path] = None,
) -> None:
    path = _retirees_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def is_retired(player_id: str, *, data_dir: Optional[Path] = None) -> bool:
    return str(player_id) in load_retirees(data_dir)


def _player_overall(player: object) -> int:
    """A player's overall for retirement: the shared overall
    (``utils.player_overall``, backlog #52), rounded. Players are ranked at
    their level by it (:func:`decide_retirements`)."""

    score = player_overall_score(player)
    return int(round(score)) if score is not None else 50


def _reason(level: str, age: int, percentile: float) -> str:
    if level in _FREE_AGENT_LEVELS:
        return "unsigned"
    if level == "AAA":
        return "career minor leaguer"
    if level == "LOW":
        return "prospect washout"
    if percentile >= 0.75:
        return "goes out on top"
    if age >= 40:
        return "can't keep up"
    if percentile < 0.33:
        return "washed"
    return "declining"


def should_retire(
    player: object,
    *,
    season_year: int,
    age: Optional[int] = None,
    level: Optional[str] = None,
    percentile: float = 0.5,
    multi_year_contract: bool = False,
) -> Optional[str]:
    """Return a short reason string when the player retires this offseason.

    ``season_year`` is the league year the rollover starts (it fixes the
    roll, :func:`_draw`); ``percentile`` is his rank at his level
    (:func:`level_percentiles`). Reasons:
      - ``"goes out on top"`` — still one of the better big leaguers
      - ``"declining"`` — an average big leaguer past his prime
      - ``"washed"`` — a fringe big leaguer
      - ``"can't keep up"`` — 40 or older
      - ``"career minor leaguer"`` / ``"prospect washout"`` — AAA / LOW
      - ``"unsigned"`` — a free agent nobody signed

    Returns ``None`` when the player plays on.
    """

    if age is None:
        bd = getattr(player, "birthdate", None)
        if bd:
            age = calculate_age(str(bd))
    if age is None:
        return None
    norm_level = (level or "ACT").strip().upper()
    chance = retirement_chance(
        age, norm_level, percentile, multi_year_contract=multi_year_contract
    )
    if chance <= 0.0:
        return None
    pid = str(getattr(player, "player_id", "") or "")
    if _draw(pid, season_year) >= chance:
        return None
    return _reason(norm_level, age, percentile)


def decide_retirements(
    candidates: Iterable[Mapping[str, Any]],
    *,
    season_year: int,
) -> List[Dict[str, Any]]:
    """Who retires among ``candidates``, each ``{"player", "age", "level",
    "multi_year_contract"?}`` (``level`` ``"FA"`` / ``"FA_NEW"`` for a free
    agent, see :func:`retirement_chance`).

    The candidates are the whole league: they are ranked against each other
    at their level (:func:`level_percentiles`) before anyone is decided.
    Returns the retirees as ``{"player", "age", "level", "overall",
    "percentile", "reason"}``.
    """

    rows = []
    scores: Dict[str, tuple[str, Optional[float]]] = {}
    for item in candidates:
        player = item.get("player")
        pid = str(getattr(player, "player_id", "") or "").strip()
        if not pid:
            continue
        score = player_overall_score(player)
        scores[pid] = (str(item.get("level") or "ACT"), score)
        rows.append((pid, item, score))
    ranks = level_percentiles(scores)
    out: List[Dict[str, Any]] = []
    for pid, item, score in rows:
        level = str(item.get("level") or "ACT").strip().upper()
        reason = should_retire(
            item["player"],
            season_year=season_year,
            age=item.get("age"),
            level=level,
            percentile=ranks[pid],
            multi_year_contract=bool(item.get("multi_year_contract")),
        )
        if not reason:
            continue
        out.append(
            {
                "player": item["player"],
                "age": item.get("age"),
                "level": level,
                "overall": int(round(score)) if score is not None else 50,
                "percentile": round(ranks[pid], 3),
                "reason": reason,
            }
        )
    return out


def _contract_years_left(data_dir: Path) -> Dict[str, int]:
    """``{player_id: years_left}`` from the league's contracts (empty when
    there are none or they can't be read)."""

    try:
        from services.contracts_service import load_contracts_payload

        contracts = load_contracts_payload(data_dir=data_dir).get("players") or {}
    except Exception:
        return {}
    out: Dict[str, int] = {}
    for pid, raw in contracts.items():
        if not isinstance(raw, Mapping):
            continue
        try:
            out[str(pid)] = int(raw.get("years_left", 1) or 1)
        except (TypeError, ValueError):
            out[str(pid)] = 1
    return out


def _load_team_rosters(
    rosters_dir: Path,
) -> Dict[str, Dict[str, str]]:
    """Return ``{team_id: {player_id: level}}`` for every roster file."""

    out: Dict[str, Dict[str, str]] = {}
    if not rosters_dir.exists():
        return out
    for roster_file in rosters_dir.glob("*.csv"):
        team_id = roster_file.stem
        if team_id.endswith("_pitching") or team_id.endswith("_lineup"):
            continue
        levels: Dict[str, str] = {}
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if not row or len(row) < 2:
                        continue
                    pid = (row[0] or "").strip()
                    level = (row[1] or "").strip().upper()
                    if not pid:
                        continue
                    # DL15/DL45 collapse to DL/IR for retirement purposes.
                    if level in {"DL", "DL15"}:
                        level = "DL"
                    elif level in {"DL45", "IR"}:
                        level = "IR"
                    levels[pid] = level
        except OSError:
            continue
        if levels:
            out[team_id] = levels
    return out


def run_yearly_retirements(
    *,
    season_year: Optional[int] = None,
    data_dir: Optional[Path] = None,
    new_free_agents: Iterable[str] = (),
) -> Dict[str, Any]:
    """Apply retirement rules to every rostered player and every unsigned
    free agent. Returns a summary.

    ``new_free_agents`` are the players whose contracts ran out at this
    rollover (the contract step's expired ids): they are judged as free
    agents by age, not as players nobody signed all season."""

    resolved = data_dir or get_data_dir()
    rosters_dir = resolved / "rosters"
    team_rosters = _load_team_rosters(rosters_dir)
    if not team_rosters:
        return {"retirees": [], "count": 0}

    rostered_ids: set[str] = set()
    team_for: Dict[str, str] = {}
    level_for: Dict[str, str] = {}
    for team_id, ids_with_levels in team_rosters.items():
        for pid, level in ids_with_levels.items():
            rostered_ids.add(pid)
            team_for.setdefault(pid, team_id)
            level_for.setdefault(pid, level)

    try:
        players = list(load_players_from_csv(resolved / "players.csv"))
    except Exception:
        return {"retirees": [], "count": 0, "error": "failed to load players.csv"}

    # A free agent is a player no club owns (no roster file, no contract)
    # who has not retired already; a contract on no roster file keeps the
    # player his club's, as the free-agent list counts him.
    from utils.roster_ownership import club_owned_players

    owned = club_owned_players(resolved)
    registry = load_retirees(resolved)
    years_left = _contract_years_left(resolved)
    year = int(season_year or datetime.utcnow().year)
    new_free = {str(pid).strip() for pid in (new_free_agents or ())}

    candidates: List[Dict[str, Any]] = []
    for player in players:
        pid = str(getattr(player, "player_id", "") or "").strip()
        if not pid or pid in registry:
            continue
        if pid in rostered_ids:
            level = level_for.get(pid, "ACT")
        elif pid not in owned:
            level = NEW_FREE_AGENT if pid in new_free else FREE_AGENT
        else:
            continue
        bd = getattr(player, "birthdate", None)
        candidates.append(
            {
                "player": player,
                "age": calculate_age(str(bd)) if bd else None,
                "level": level,
                "multi_year_contract": years_left.get(pid, 0) > 1,
            }
        )

    retirees: List[Dict[str, Any]] = []
    for decided in decide_retirements(candidates, season_year=year):
        player = decided["player"]
        pid = str(getattr(player, "player_id", "") or "").strip()
        retirees.append(
            {
                "player_id": pid,
                "first_name": getattr(player, "first_name", "") or "",
                "last_name": getattr(player, "last_name", "") or "",
                "primary_position": getattr(player, "primary_position", "") or "",
                "is_pitcher": bool(getattr(player, "is_pitcher", False)),
                "team_id": team_for.get(pid, ""),
                "level": decided["level"],
                "age": decided["age"],
                "overall": decided["overall"],
                "reason": decided["reason"],
            }
        )

    if not retirees:
        return {"retirees": [], "count": 0}

    # Persist to the registry keyed by player_id so other services can
    # check is_retired() and the UI can render a Retirements section.
    timestamp = datetime.utcnow().isoformat() + "Z"
    for entry in retirees:
        registry[entry["player_id"]] = {
            **entry,
            "retired_year": year,
            "retired_at": timestamp,
        }
    save_retirees(registry, data_dir=resolved)

    # Remove from rosters + release contracts. Roster cleanup is the
    # safety net for downstream code that filters by roster membership;
    # contract release stops the team from paying a retiree.
    try:
        from services.contracts_service import release_contracts_to_free_agency

        signed = [e["player_id"] for e in retirees if e["level"] not in _FREE_AGENT_LEVELS]
        if signed:
            release_contracts_to_free_agency(signed, data_dir=resolved)
    except Exception:
        pass

    # The contract release helper already strips retirees from rosters
    # via its internal sweep, but we double-check by rewriting any
    # roster file that still references a retiree.
    _scrub_rosters(rosters_dir, {entry["player_id"] for entry in retirees})

    # Log a news event per retiree so the league feed reflects the move.
    try:
        from utils.news_logger import log_news_event

        news_path = resolved / "news_feed.txt"
        for entry in retirees:
            name = (
                f"{entry['first_name']} {entry['last_name']}".strip()
                or entry["player_id"]
            )
            label = (
                f"{entry['primary_position']} {name}".strip()
                if entry["primary_position"]
                else name
            )
            log_news_event(
                f"{label} retires at age {entry['age']} ({entry['reason']}).",
                category="retirement",
                team_id=entry["team_id"] or None,
                file_path=news_path,
            )
    except Exception:
        pass

    return {"retirees": retirees, "count": len(retirees)}


def _scrub_rosters(rosters_dir: Path, retired_ids: Iterable[str]) -> None:
    """Defensive: strip any retired player_ids from roster CSVs."""

    targets = set(retired_ids)
    if not targets or not rosters_dir.exists():
        return
    departed: dict[str, list] = {}
    for roster_file in rosters_dir.glob("*.csv"):
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                rows = [row for row in csv.reader(fh) if row]
        except OSError:
            continue
        kept = [row for row in rows if not row or (row[0] or "").strip() not in targets]
        if len(kept) == len(rows):
            continue
        try:
            with roster_file.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                for row in kept:
                    writer.writerow(row)
        except OSError:
            continue
        if not roster_file.stem.endswith("_pitching"):
            departed[roster_file.stem] = [
                (row[0] or "").strip() for row in rows if (row[0] or "").strip() in targets
            ]
    # 8.4.1: off the club's lineups, depth chart and staff as well.
    if departed:
        from services.departure_cleanup import clear_departures

        clear_departures(departed, data_dir=rosters_dir.parent)


__all__ = [
    "FREE_AGENT",
    "NEW_FREE_AGENT",
    "decide_retirements",
    "is_retired",
    "level_percentiles",
    "load_retirees",
    "retirement_chance",
    "run_yearly_retirements",
    "save_retirees",
    "should_retire",
]
