from __future__ import annotations

"""Postseason data structures, persistence, and (later) simulation.

This module provides the bracket model and load/save helpers. Seeding and
simulation are implemented in subsequent tickets; here we define the
data-shapes and stable JSON schema to support resume and UI rendering.
"""

import functools
import hashlib
import inspect
import json
import re
from datetime import date as _date
from datetime import timedelta as _timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from playbalance.playoffs_config import DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE
from services.standings_repository import load_standings
from utils.path_utils import get_data_dir


SCHEMA_VERSION = 1

_DEFAULT_SERIES_LENGTHS = {"wildcard": 3, "ds": 5, "cs": 7, "ws": 7}
_DEFAULT_HOME_AWAY_PATTERNS = {3: [1, 1, 1], 5: [2, 2, 1], 7: [2, 3, 2]}


def _extract_series_settings(cfg_like: Any) -> Tuple[Dict[str, Any], Dict[int, List[int]]]:
    if isinstance(cfg_like, dict):
        lengths = dict((cfg_like.get("series_lengths") or {}))
        patterns_raw = cfg_like.get("home_away_patterns") or {}
    else:
        lengths = dict(getattr(cfg_like, "series_lengths", {}) or {})
        patterns_raw = getattr(cfg_like, "home_away_patterns", {}) or {}

    patterns: Dict[int, List[int]] = {}
    for key, value in patterns_raw.items():
        try:
            patterns[int(key)] = [int(x) for x in (value or [])]
        except Exception:
            continue
    return lengths, patterns




def _pattern_for_length(length: int, patterns: Dict[int, List[int]]) -> List[int]:
    pattern = list(patterns.get(length, []))
    if pattern and sum(pattern) == length:
        return pattern
    fallback = _DEFAULT_HOME_AWAY_PATTERNS.get(length)
    if fallback and sum(fallback) == length:
        return list(fallback)
    return [length] if length > 0 else []


def _series_config_from_settings(cfg_like: Any, key: str) -> SeriesConfig:
    lengths, patterns = _extract_series_settings(cfg_like)
    length = int(lengths.get(key, _DEFAULT_SERIES_LENGTHS.get(key, 7)))
    if length <= 0:
        length = _DEFAULT_SERIES_LENGTHS.get(key, 7)
    pattern = _pattern_for_length(length, patterns)
    return SeriesConfig(length=length, pattern=pattern)


@dataclass
class PlayoffTeam:
    team_id: str
    seed: int
    league: str
    wins: int
    run_diff: int = 0


@dataclass
class GameResult:
    home: str
    away: str
    date: Optional[str] = None
    result: Optional[str] = None  # e.g. "4-2"
    boxscore: Optional[str] = None  # relative path to HTML
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SeriesConfig:
    length: int
    # Pattern of home stretches for higher seed. For BO7 2-3-2 -> [2,3,2].
    pattern: List[int]


@dataclass
class Matchup:
    high: PlayoffTeam  # higher seed (home field advantage)
    low: PlayoffTeam
    config: SeriesConfig
    games: List[GameResult] = field(default_factory=list)
    winner: Optional[str] = None  # team_id


@dataclass
class ParticipantRef:
    """Reference to a future matchup participant."""

    kind: str  # 'seed' or 'winner'
    league: Optional[str] = None
    seed: Optional[int] = None
    source_round: Optional[str] = None
    slot: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "league": self.league,
            "seed": self.seed,
            "source_round": self.source_round,
            "slot": self.slot,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ParticipantRef":
        return ParticipantRef(
            kind=str(data.get("kind", "seed")),
            league=data.get("league"),
            seed=data.get("seed"),
            source_round=data.get("source_round"),
            slot=int(data.get("slot", 0)),
        )


@dataclass
class RoundPlanEntry:
    """Plan for creating a matchup once prerequisite winners are known."""

    series_key: str
    sources: List[ParticipantRef] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_key": self.series_key,
            "sources": [ref.to_dict() for ref in self.sources],
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "RoundPlanEntry":
        return RoundPlanEntry(
            series_key=str(data.get("series_key", "cs")),
            sources=[ParticipantRef.from_dict(ref) for ref in (data.get("sources") or [])],
        )


@dataclass
class Round:
    name: str  # e.g. "WC", "DS", "CS", "WS"
    matchups: List[Matchup] = field(default_factory=list)
    plan: List[RoundPlanEntry] = field(default_factory=list)


@dataclass
class PlayoffBracket:
    year: int
    rounds: List[Round] = field(default_factory=list)
    champion: Optional[str] = None
    runner_up: Optional[str] = None
    schema_version: int = SCHEMA_VERSION
    seeds_by_league: Dict[str, List[PlayoffTeam]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        def team_to_dict(t: PlayoffTeam) -> Dict[str, Any]:
            return {
                "team_id": t.team_id,
                "seed": t.seed,
                "league": t.league,
                "wins": t.wins,
                "run_diff": t.run_diff,
            }

        def game_to_dict(g: GameResult) -> Dict[str, Any]:
            return {
                "home": g.home,
                "away": g.away,
                "date": g.date,
                "result": g.result,
                "boxscore": g.boxscore,
                "meta": dict(g.meta or {}),
            }

        def matchup_to_dict(m: Matchup) -> Dict[str, Any]:
            return {
                "high": team_to_dict(m.high),
                "low": team_to_dict(m.low),
                "config": {
                    "length": m.config.length,
                    "pattern": list(m.config.pattern),
                },
                "games": [game_to_dict(g) for g in m.games],
                "winner": m.winner,
            }

        return {
            "schema_version": self.schema_version,
            "year": self.year,
            "champion": self.champion,
            "runner_up": self.runner_up,
            "seeds": {lg: [team_to_dict(t) for t in (teams or [])] for lg, teams in (self.seeds_by_league or {}).items()},
            "rounds": [
                {
                    "name": r.name,
                    "matchups": [matchup_to_dict(m) for m in r.matchups],
                    "plan": [entry.to_dict() for entry in getattr(r, "plan", [])],
                }
                for r in self.rounds
            ],
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "PlayoffBracket":
        def team_from_dict(d: Dict[str, Any]) -> PlayoffTeam:
            return PlayoffTeam(
                team_id=str(d.get("team_id", "")),
                seed=int(d.get("seed", 0)),
                league=str(d.get("league", "")),
                wins=int(d.get("wins", 0)),
                run_diff=int(d.get("run_diff", 0)),
            )

        def game_from_dict(d: Dict[str, Any]) -> GameResult:
            return GameResult(
                home=str(d.get("home", "")),
                away=str(d.get("away", "")),
                date=d.get("date"),
                result=d.get("result"),
                boxscore=d.get("boxscore"),
                meta=dict(d.get("meta", {}) or {}),
            )

        def matchup_from_dict(d: Dict[str, Any]) -> Matchup:
            cfg = d.get("config", {}) or {}
            return Matchup(
                high=team_from_dict(d.get("high", {})),
                low=team_from_dict(d.get("low", {})),
                config=SeriesConfig(
                    length=int(cfg.get("length", 7)),
                    pattern=[int(x) for x in (cfg.get("pattern") or [])],
                ),
                games=[game_from_dict(x) for x in (d.get("games") or [])],
                winner=d.get("winner"),
            )

        rounds = [
            Round(
                name=str(r.get("name", "")),
                matchups=[matchup_from_dict(m) for m in (r.get("matchups") or [])],
                plan=[RoundPlanEntry.from_dict(p) for p in (r.get("plan") or [])],
            )
            for r in (data.get("rounds") or [])
        ]
        seeds_raw = data.get("seeds") or {}
        seeds_by_league: Dict[str, List[PlayoffTeam]] = {}
        for lg, teams in seeds_raw.items():
            if isinstance(teams, list):
                seeds_by_league[str(lg)] = [team_from_dict(t) for t in teams]

        br = PlayoffBracket(
            year=int(data.get("year", 0)),
            rounds=rounds,
            champion=data.get("champion"),
            runner_up=data.get("runner_up"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            seeds_by_league=seeds_by_league,
        )
        return br


# Bracket documents are ``playoffs.json`` or ``playoffs_<year>.json``. A plain
# ``playoffs_*.json`` glob also matched the league wizard's
# ``playoffs_config.json`` (the playoff *format*), which parsed as an empty
# year-0 bracket and masked the missing real one.
_BRACKET_FILE_RE = re.compile(r"^playoffs_(\d+)\.json$")


def bracket_is_empty(bracket: Optional["PlayoffBracket"]) -> bool:
    """True when ``bracket`` is missing or has nothing to play.

    A bracket with year 0 or no rounds is a placeholder (or a non-bracket
    document parsed as one), never a seeded postseason.
    """

    if bracket is None:
        return True
    try:
        year = int(getattr(bracket, "year", 0) or 0)
    except (TypeError, ValueError):
        year = 0
    return year <= 0 or not list(getattr(bracket, "rounds", None) or [])


def _bracket_path(year: int | None = None) -> Path:
    base = get_data_dir()
    if year:
        return base / f"playoffs_{year}.json"
    return base / "playoffs.json"


def save_bracket(bracket: PlayoffBracket, path: Optional[Path] = None) -> Path:
    """Atomically persist a bracket JSON file and return the path."""

    p = path or _bracket_path(bracket.year)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Roll a simple .bak before replacing if a file exists
    try:
        if p.exists():
            bak = p.with_suffix(p.suffix + ".bak")
            try:
                # Best-effort copy
                bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(bracket.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def load_bracket(path: Optional[Path] = None, *, year: Optional[int] = None) -> Optional[PlayoffBracket]:
    """Load the most relevant bracket if present, otherwise return ``None``."""

    candidates: List[Path] = []
    if path is not None:
        candidates.append(Path(path))
    else:
        matches: List[Path] = []
        if year is not None:
            candidates.append(_bracket_path(year))
            candidates.append(_bracket_path())
        else:
            candidates.append(_bracket_path())
            try:
                inferred_year = _get_year_from_schedule()
            except Exception:
                inferred_year = None
            if inferred_year:
                candidates.append(_bracket_path(inferred_year))
        base = get_data_dir()
        try:
            matches = [
                p for p in base.glob("playoffs_*.json")
                if _BRACKET_FILE_RE.match(p.name)
            ]
        except Exception:
            matches = []
        if year is None and matches:
            def _year_key(p: Path) -> int:
                stem = p.stem
                try:
                    return int(stem.split("_", 1)[1])
                except Exception:
                    return 0
            matches = sorted(matches, key=_year_key, reverse=True)
        else:
            matches = sorted(matches, reverse=True)
        candidates.extend(matches)

    best: Optional[PlayoffBracket] = None
    best_score: tuple[int, float] = (-1, -1.0)
    seen: set[Path] = set()
    for candidate in candidates:
        p = Path(candidate)
        if p in seen:
            continue
        seen.add(p)
        try:
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            if int(data.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
                continue
            br = PlayoffBracket.from_dict(data)
            _normalize_series_configs(br)
            if path is None:
                br = _refresh_bracket_if_stale(br)
        except Exception:
            continue

        br_year = int(getattr(br, "year", 0) or 0)
        if year is not None and br_year == year:
            return br
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = 0.0
        score = (br_year, mtime)
        if year is not None and best is None:
            # With a specific year requested, return the first successfully parsed bracket
            # if no exact match is found.
            best = br
            best_score = score
        elif score > best_score:
            best = br
            best_score = score
    if best is not None and path is None:
        best = _refresh_bracket_if_stale(best)
    return best


# --- Seeding engine (Ticket 2) ---------------------------------------------------------

def _infer_league(division: str, mapping: Dict[str, str]) -> str:
    if division in mapping:
        return mapping[division]
    div = str(division).strip()
    if not div:
        return ""
    if " " in div:
        return div.split(" ", 1)[0]
    return ""


def _get_year_from_schedule() -> int:
    """Infer season year from the last schedule date if available."""

    from datetime import date
    import csv

    sched = get_data_dir() / "schedule.csv"
    try:
        if sched.exists():
            with sched.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            dates = [str(r.get("date") or "") for r in rows if r.get("date")]
            dates.sort()
            if dates:
                return int(dates[-1].split("-")[0])
    except Exception:
        pass
    return date.today().year


def _wins_and_diff(stand: Dict[str, Any]) -> tuple[int, int]:
    try:
        wins = int(stand.get("wins", 0))
        rf = int(stand.get("runs_for", 0))
        ra = int(stand.get("runs_against", 0))
        return wins, (rf - ra)
    except Exception:
        return 0, 0


def _rank_division_winners(teams_in_div: List[Any], standings: Dict[str, Dict[str, Any]]) -> Optional[Any]:
    if not teams_in_div:
        return None
    best = None
    best_key = (-1, -1)
    for t in teams_in_div:
        st = standings.get(getattr(t, "team_id", ""), {}) or {}
        wins, diff = _wins_and_diff(st)
        key = (wins, diff)
        if key > best_key:
            best_key = key
            best = t
    return best


def _seed_league(league_name: str, league_teams: List[Any], standings: Dict[str, Dict[str, Any]], cfg: Any) -> List[PlayoffTeam]:
    # Group by division name (full string)
    by_div: Dict[str, List[Any]] = {}
    for t in league_teams:
        div = getattr(t, "division", "")
        by_div.setdefault(div, []).append(t)

    # Pick division winners
    winners: List[Any] = []
    for div, members in by_div.items():
        w = _rank_division_winners(members, standings)
        if w is not None:
            winners.append(w)

    # Remaining teams are wildcard candidates
    winner_ids = {getattr(t, "team_id", "") for t in winners}
    wildcards = [t for t in league_teams if getattr(t, "team_id", "") not in winner_ids]

    # Rank all by wins -> run diff
    def rank_key(t: Any):
        st = standings.get(getattr(t, "team_id", ""), {}) or {}
        wins, diff = _wins_and_diff(st)
        return (wins, diff)

    winners.sort(key=rank_key, reverse=True)
    wildcards.sort(key=rank_key, reverse=True)

    named_divisions = [div for div in by_div if str(div).strip()]
    division_count = len(named_divisions) or (1 if by_div else 0)
    total_candidates = len(winners) + len(wildcards)

    minimum_winner_slots = min(len(winners), total_candidates)

    preferred_slots = None
    if hasattr(cfg, "slots_for_league") and callable(getattr(cfg, "slots_for_league")):
        try:
            preferred_slots = int(cfg.slots_for_league(len(league_teams)))
        except Exception:
            preferred_slots = None
        else:
            custom_map = getattr(cfg, "playoff_slots_by_league_size", {}) or {}
            desired_raw = getattr(cfg, "num_playoff_teams_per_league", DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE)
            try:
                desired_slots = int(desired_raw)
            except Exception:
                desired_slots = DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE
            desired_baseline = desired_slots
            total_teams = len(league_teams)
            if total_teams > 0 and desired_slots > total_teams:
                desired_slots = total_teams
            if not custom_map and desired_baseline == DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE:
                preferred_slots = None
            elif (
                not custom_map
                and desired_slots > 0
                and desired_baseline != DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE
                and (preferred_slots is None or desired_slots > preferred_slots)
            ):
                preferred_slots = desired_slots

    if division_count > 0:
        base_slots = min(division_count, total_candidates)
    else:
        base_slots = minimum_winner_slots
    base_slots = max(base_slots, minimum_winner_slots)
    wildcard_slots = 1 if wildcards else 0
    desired_slots = min(
        base_slots + min(wildcard_slots, max(total_candidates - base_slots, 0)),
        total_candidates,
    )
    configured_slots = int(
        getattr(cfg, "num_playoff_teams_per_league", desired_slots) or desired_slots
    )
    slots_upper_bound = min(configured_slots, total_candidates) if configured_slots > 0 else total_candidates
    auto_slots = min(desired_slots, slots_upper_bound)

    if preferred_slots is None or preferred_slots <= 0:
        slots = auto_slots
    else:
        slots = min(max(preferred_slots, auto_slots), total_candidates)

    slots = max(slots, minimum_winner_slots)
    if slots < 2 and total_candidates >= 2:
        slots = min(2, total_candidates)

    if getattr(cfg, "division_winners_priority", True):
        pool = winners + wildcards
    else:
        pool = (league_teams or [])
        pool.sort(key=rank_key, reverse=True)

    seeded: List[PlayoffTeam] = []
    for idx, t in enumerate(pool[:slots], start=1):
        st = standings.get(getattr(t, "team_id", ""), {}) or {}
        wins, diff = _wins_and_diff(st)
        seeded.append(
            PlayoffTeam(
                team_id=getattr(t, "team_id", ""),
                seed=idx,
                league=league_name,
                wins=wins,
                run_diff=diff,
            )
        )
    return seeded


def _build_league_rounds(league: str, seeds: List[PlayoffTeam], cfg: Any) -> Tuple[List[Round], Optional[str]]:
    rounds: List[Round] = []
    final_round_name: Optional[str] = None

    if len(seeds) < 2:
        return rounds, final_round_name

    seed_lookup = {team.seed: team for team in seeds}

    def team_for(seed_number: int) -> Optional[PlayoffTeam]:
        return seed_lookup.get(seed_number)

    def add_match(round_obj: Round, high_seed: int, low_seed: int, series_key: str) -> None:
        high = team_for(high_seed)
        low = team_for(low_seed)
        if high is None or low is None:
            return
        round_obj.matchups.append(
            Matchup(high=high, low=low, config=_series_config_from_settings(cfg, series_key))
        )

    n = len(seeds)

    if n == 2:
        cs = Round(name=f"{league} CS")
        add_match(cs, 1, 2, "cs")
        rounds.append(cs)
        final_round_name = cs.name
        return rounds, final_round_name

    if n == 3:
        wc = Round(name=f"{league} WC")
        add_match(wc, 2, 3, "wildcard")
        rounds.append(wc)

        cs = Round(name=f"{league} CS")
        cs.plan.append(
            RoundPlanEntry(
                series_key="cs",
                sources=[
                    ParticipantRef(kind="seed", league=league, seed=1),
                    ParticipantRef(kind="winner", source_round=wc.name, slot=0),
                ],
            )
        )
        rounds.append(cs)
        final_round_name = cs.name
        return rounds, final_round_name

    if n == 4:
        ds = Round(name=f"{league} DS")
        add_match(ds, 1, 4, "ds")
        add_match(ds, 2, 3, "ds")
        rounds.append(ds)

        cs = Round(name=f"{league} CS")
        cs.plan.append(
            RoundPlanEntry(
                series_key="cs",
                sources=[
                    ParticipantRef(kind="winner", source_round=ds.name, slot=0),
                    ParticipantRef(kind="winner", source_round=ds.name, slot=1),
                ],
            )
        )
        rounds.append(cs)
        final_round_name = cs.name
        return rounds, final_round_name

    if n == 5:
        wc = Round(name=f"{league} WC")
        add_match(wc, 4, 5, "wildcard")
        rounds.append(wc)

        ds = Round(name=f"{league} DS")
        add_match(ds, 2, 3, "ds")
        ds.plan.append(
            RoundPlanEntry(
                series_key="ds",
                sources=[
                    ParticipantRef(kind="seed", league=league, seed=1),
                    ParticipantRef(kind="winner", source_round=wc.name, slot=0),
                ],
            )
        )
        rounds.append(ds)

        cs = Round(name=f"{league} CS")
        cs.plan.append(
            RoundPlanEntry(
                series_key="cs",
                sources=[
                    ParticipantRef(kind="winner", source_round=ds.name, slot=0),
                    ParticipantRef(kind="winner", source_round=ds.name, slot=1),
                ],
            )
        )
        rounds.append(cs)
        final_round_name = cs.name
        return rounds, final_round_name

    # n >= 6 -> treat as 6 with wildcards
    wc = Round(name=f"{league} WC")
    add_match(wc, 3, 6, "wildcard")
    add_match(wc, 4, 5, "wildcard")
    rounds.append(wc)

    ds = Round(name=f"{league} DS")
    ds.plan.append(
        RoundPlanEntry(
            series_key="ds",
            sources=[
                ParticipantRef(kind="seed", league=league, seed=1),
                ParticipantRef(kind="winner", source_round=wc.name, slot=0),
            ],
        )
    )
    ds.plan.append(
        RoundPlanEntry(
            series_key="ds",
            sources=[
                ParticipantRef(kind="seed", league=league, seed=2),
                ParticipantRef(kind="winner", source_round=wc.name, slot=1),
            ],
        )
    )
    rounds.append(ds)

    cs = Round(name=f"{league} CS")
    cs.plan.append(
        RoundPlanEntry(
            series_key="cs",
            sources=[
                ParticipantRef(kind="winner", source_round=ds.name, slot=0),
                ParticipantRef(kind="winner", source_round=ds.name, slot=1),
            ],
        )
    )
    rounds.append(cs)
    final_round_name = cs.name
    return rounds, final_round_name




def generate_bracket(standings: Dict[str, Dict[str, Any]], teams: List[Any], cfg: Any) -> PlayoffBracket:
    """Generate an initial bracket based on final standings and configuration."""

    div_map: Dict[str, str] = dict(getattr(cfg, "division_to_league", {}) or {})
    by_league: Dict[str, List[Any]] = {}
    for team in teams:
        league = _infer_league(getattr(team, "division", ""), div_map) or ""
        by_league.setdefault(league or "LEAGUE", []).append(team)

    leagues = sorted(by_league.keys())
    seeds_by_league: Dict[str, List[PlayoffTeam]] = {}
    rounds: List[Round] = []
    league_finals: Dict[str, str] = {}

    for league in leagues:
        seeded = _seed_league(league, by_league[league], standings, cfg)
        default_slots = int(getattr(cfg, "num_playoff_teams_per_league", 6) or 6)
        slot_fn = getattr(cfg, "slots_for_league", None)
        custom_map = getattr(cfg, "playoff_slots_by_league_size", None)
        if callable(slot_fn) and custom_map:
            try:
                slots = int(slot_fn(len(by_league[league])))
            except Exception:
                slots = default_slots
        else:
            slots = default_slots

        slots = min(slots, len(seeded))
        if slots < 2:
            continue

        seeds = seeded[:slots]
        seeds_by_league[league] = seeds

        league_rounds, final_round_name = _build_league_rounds(league, seeds, cfg)
        rounds.extend(league_rounds)
        if final_round_name:
            league_finals[league] = final_round_name

    if len(league_finals) >= 2:
        contenders = sorted(league_finals.keys())[:2]
        ws = Round(name="WS")
        ws.plan.append(
            RoundPlanEntry(
                series_key="ws",
                sources=[
                    ParticipantRef(kind="winner", source_round=league_finals[contenders[0]], slot=0),
                    ParticipantRef(kind="winner", source_round=league_finals[contenders[1]], slot=0),
                ],
            )
        )
        rounds.append(ws)
    elif len(league_finals) == 1:
        # Single-league setup: duplicate the league final for display/metadata
        (_, final_name), = league_finals.items()
        final_round = next((r for r in rounds if r.name == final_name), None)
        if final_round is not None:
            rounds.append(Round(name="Final", matchups=final_round.matchups))

    year = _get_year_from_schedule()
    return PlayoffBracket(year=year, rounds=rounds, seeds_by_league=seeds_by_league)



# --- Series simulation (Ticket 3) ------------------------------------------------------

def _deterministic_seed(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    # Use 30 bits for compatibility with random.randrange ranges used elsewhere
    return int(h[:8], 16) & ((1 << 30) - 1)


def _wins_needed(length: int) -> int:
    return (int(length) // 2) + 1




def _stage_key_from_round_name(name: str) -> Optional[str]:
    tokens = [token.lower() for token in str(name or "").replace("-", " ").replace("_", " ").split() if token]
    for token in reversed(tokens):
        if token in {"ws", "world", "worlds", "final", "finals", "championship"}:
            return "ws"
        if token in {"cs", "lcs"}:
            return "cs"
        if token in {"ds", "division", "divisional"}:
            return "ds"
        if token in {"wc", "wildcard", "play-in", "playin"}:
            return "wildcard"
    return None


def _count_series_wins(matchup: Matchup) -> Tuple[int, int]:
    high_id = getattr(matchup.high, "team_id", "")
    low_id = getattr(matchup.low, "team_id", "")
    wins_high = wins_low = 0
    for game in getattr(matchup, "games", []) or []:
        result = str(getattr(game, "result", "") or "")
        if "-" not in result:
            continue
        try:
            home_runs_str, away_runs_str = result.split("-", 1)
            home_runs = int(home_runs_str.strip())
            away_runs = int(away_runs_str.strip())
        except (TypeError, ValueError):
            continue
        if home_runs == away_runs:
            continue
        home_team = getattr(game, "home", "")
        away_team = getattr(game, "away", "")
        winner = home_team if home_runs > away_runs else away_team
        if winner == high_id:
            wins_high += 1
        elif winner == low_id:
            wins_low += 1
    return wins_high, wins_low


def _normalize_series_configs(bracket: PlayoffBracket) -> None:
    try:
        from playbalance.playoffs_config import load_playoffs_config
        cfg = load_playoffs_config()
    except Exception:
        cfg = None
    lengths, patterns = _extract_series_settings(cfg)
    champ_round_names = _championship_round_names(bracket)
    finals: List[Matchup] = []
    for rnd in getattr(bracket, "rounds", []) or []:
        stage_key = _stage_key_from_round_name(rnd.name)
        if not stage_key:
            continue
        expected_length = int(lengths.get(stage_key, _DEFAULT_SERIES_LENGTHS.get(stage_key, 0)) or 0)
        if expected_length <= 0:
            expected_length = _DEFAULT_SERIES_LENGTHS.get(stage_key, 0)
        if expected_length <= 0:
            continue
        expected_pattern = _pattern_for_length(expected_length, patterns)
        wins_needed = _wins_needed(expected_length)
        for matchup in rnd.matchups:
            cfg_obj = getattr(matchup, "config", None)
            if cfg_obj is None:
                matchup.config = SeriesConfig(length=expected_length, pattern=expected_pattern.copy())
                cfg_obj = matchup.config
            current_length = int(getattr(cfg_obj, "length", 0) or 0)
            current_pattern = list(getattr(cfg_obj, "pattern", []) or [])
            if current_length != expected_length or sum(current_pattern) != expected_length:
                cfg_obj.length = expected_length
                cfg_obj.pattern = expected_pattern.copy()
            wins_high, wins_low = _count_series_wins(matchup)
            if wins_high >= wins_needed or wins_low >= wins_needed:
                matchup.winner = matchup.high.team_id if wins_high >= wins_needed else matchup.low.team_id
            else:
                if getattr(matchup, "winner", None):
                    matchup.winner = None
            if stage_key in {"ws", "final"} or rnd.name in champ_round_names:
                finals.append(matchup)
    if finals:
        decided = [m for m in finals if getattr(m, "winner", None)]
        if decided:
            final_match = decided[0]
            champ_id = final_match.winner
            if champ_id:
                bracket.champion = champ_id
                bracket.runner_up = final_match.low.team_id if champ_id == final_match.high.team_id else final_match.high.team_id
        else:
            bracket.champion = None
            bracket.runner_up = None


def _load_known_teams() -> Tuple[List[Any], set[str]]:
    try:
        from utils.team_loader import load_teams
        teams = load_teams()
    except Exception:
        return [], set()
    known = {
        getattr(t, "team_id", "")
        for t in teams
        if getattr(t, "team_id", "")
    }
    return teams, {tid for tid in known if tid}


def _load_standings_snapshot() -> Dict[str, Dict[str, Any]]:
    return load_standings(normalize=False)


def _refresh_bracket_if_stale(bracket: PlayoffBracket) -> PlayoffBracket:
    teams, known_ids = _load_known_teams()
    if not known_ids:
        return bracket

    unknown: set[str] = set()
    for seeds in (bracket.seeds_by_league or {}).values():
        for team in seeds or []:
            tid = getattr(team, "team_id", "")
            if tid and tid not in known_ids:
                unknown.add(tid)
            if not tid:
                unknown.add(tid)

    for rnd in bracket.rounds:
        for matchup in rnd.matchups:
            for participant in (getattr(matchup, "high", None), getattr(matchup, "low", None)):
                tid = getattr(participant, "team_id", "")
                if tid and tid not in known_ids:
                    unknown.add(tid)
                if not tid:
                    unknown.add(tid)

    if not unknown:
        return bracket

    standings = _load_standings_snapshot()
    if not standings:
        bracket.champion = None
        bracket.runner_up = None
        return bracket

    try:
        from playbalance.playoffs_config import load_playoffs_config
        cfg = load_playoffs_config()
    except Exception:
        bracket.champion = None
        bracket.runner_up = None
        return bracket

    try:
        fresh = generate_bracket(standings, teams, cfg)
    except Exception:
        bracket.champion = None
        bracket.runner_up = None
        return bracket

    _normalize_series_configs(fresh)
    try:
        save_bracket(fresh)
    except Exception:
        pass
    return fresh


def _championship_round_names(bracket: PlayoffBracket) -> set[str]:
    """Return the set of round names that should resolve the champion."""

    rounds = list(getattr(bracket, "rounds", []) or [])

    def _has_content(rnd: Round) -> bool:
        matchups = getattr(rnd, "matchups", []) or []
        plan = getattr(rnd, "plan", []) or []
        return bool(matchups) or bool(plan)

    finals: list[tuple[int, Round]] = [
        (idx, rnd)
        for idx, rnd in enumerate(rounds)
        if _stage_key_from_round_name(rnd.name) in {"ws", "final"}
    ]
    finals_with_content = [rnd for _, rnd in finals if _has_content(rnd)]
    if finals_with_content:
        return {rnd.name for rnd in finals_with_content}
    if finals:
        cutoff = max(idx for idx, _ in finals)
        for rnd in reversed(rounds[:cutoff]):
            if _has_content(rnd):
                return {rnd.name}
    for rnd in reversed(rounds):
        if _has_content(rnd):
            return {rnd.name}
    return set()


# --- Ties, dates and the game call (Release 3, item D) ---------------------------------

# A tied playoff result is never stored: the game is re-simulated with a
# salted seed, up to this many tries in all, and otherwise the slot is left
# unplayed. The engine itself cannot tie a postseason game short of its
# 60-inning hard stop (decision 11), so this is a backstop.
_TIE_TRIES = 3

# Owner decision Q5: MLB-style playoff dates. Day 0 is the second day after
# the last regular-season date (one off day first); each round starts the day
# after the previous round's last possible game (an off day between rounds);
# a series of five or more games gets a travel day at every change of home
# field (after games 2 and 5 of a 2-3-2 seven-game series); a three-game Wild
# Card series is played on consecutive days.
_STAGE_ORDER = {"wildcard": 0, "ds": 1, "cs": 2, "ws": 3}
_PLAN_SERIES_LENGTHS = {"ds": 5, "cs": 7, "ws": 7, "wildcard": 3}
_TRAVEL_DAY_MIN_LENGTH = 5


def _plan_series_settings() -> Dict[str, Any]:
    """Series lengths and home/away patterns for rounds still being planned.

    The league's configured values (``playoffs_config``), the same ones the
    first round is generated with and ``_normalize_series_configs`` restores
    on load; the MLB defaults when the config can't be read. Used both to
    build a planned series (:func:`_populate`) and to size its calendar
    window (:class:`_PlayoffCalendar`), so the two always agree.
    """

    lengths: Dict[str, Any] = dict(_PLAN_SERIES_LENGTHS)
    patterns: Dict[int, List[int]] = {
        k: list(v) for k, v in _DEFAULT_HOME_AWAY_PATTERNS.items()
    }
    try:
        from playbalance.playoffs_config import load_playoffs_config

        cfg_lengths, cfg_patterns = _extract_series_settings(load_playoffs_config())
    except Exception:
        cfg_lengths, cfg_patterns = {}, {}
    lengths.update(cfg_lengths)
    patterns.update(cfg_patterns)
    return {"series_lengths": lengths, "home_away_patterns": patterns}


def _score_pair(game: GameResult) -> Optional[Tuple[int, int]]:
    result = str(getattr(game, "result", "") or "")
    if "-" not in result:
        return None
    try:
        home_runs_str, away_runs_str = result.split("-", 1)
        return int(home_runs_str.strip()), int(away_runs_str.strip())
    except (TypeError, ValueError):
        return None


def _is_tied_game(game: GameResult) -> bool:
    pair = _score_pair(game)
    return pair is not None and pair[0] == pair[1]


def _played_slots(matchup: Matchup) -> int:
    """Series games played so far.

    A tied game stored before Release 3 never counts (self-heal): its slot is
    played again, so a series that used one up can still finish.
    """

    return sum(1 for game in (matchup.games or []) if not _is_tied_game(game))


def _home_order(matchup: Matchup) -> List[str]:
    high_id = matchup.high.team_id
    low_id = matchup.low.team_id
    homes: List[str] = []
    flip = False
    for block in matchup.config.pattern:
        homes.extend([high_id if not flip else low_id] * block)
        flip = not flip
    return homes


def _series_day_offsets(pattern: List[int]) -> List[int]:
    """Day offset of each game of a series from its round's first day."""

    blocks = [int(b) for b in (pattern or []) if int(b) > 0]
    games = sum(blocks)
    travel_after: set[int] = set()
    if games >= _TRAVEL_DAY_MIN_LENGTH:
        played = 0
        for block in blocks[:-1]:
            played += block
            travel_after.add(played)
    offsets: List[int] = []
    day = 0
    for game_no in range(1, games + 1):
        offsets.append(day)
        day += 2 if game_no in travel_after else 1
    return offsets


def _series_span(pattern: List[int]) -> int:
    """Days from a series' first game to its last possible one, inclusive."""

    offsets = _series_day_offsets(pattern)
    return offsets[-1] + 1 if offsets else 0


def _regular_season_end(year: int | None) -> Optional[_date]:
    """Last regular-season date of the league's schedule, or None.

    None when there is no readable schedule or it belongs to another season
    than the bracket (the games then stay undated, as before Release 3).
    """

    import csv

    sched = get_data_dir() / "schedule.csv"
    try:
        if not sched.exists():
            return None
        with sched.open(newline="", encoding="utf-8") as fh:
            tokens = [str(r.get("date") or "").strip() for r in csv.DictReader(fh)]
    except Exception:
        return None
    dates: List[_date] = []
    for token in tokens:
        try:
            dates.append(_date.fromisoformat(token))
        except ValueError:
            continue
    if not dates:
        return None
    end = max(dates)
    if year and end.year != int(year):
        return None
    return end


class _PlayoffCalendar:
    """Day index (and date, when the season's end is known) of every game.

    Rounds are grouped into stages (Wild Card, Division Series, ...) by their
    names; all series of a stage share its days, whatever league they are in.
    A stage lasts as long as its longest possible series, so a sweep does not
    move the next round up, just as MLB's schedule does not.
    """

    def __init__(self, bracket: PlayoffBracket, season_end: Optional[_date]):
        self.season_end = season_end
        settings = _plan_series_settings()
        stages: Dict[str, Dict[str, int]] = {}
        self._stage_of: Dict[str, str] = {}
        for index, rnd in enumerate(bracket.rounds):
            key = _stage_key_from_round_name(rnd.name) or rnd.name
            spans = [_series_span(m.config.pattern) for m in rnd.matchups]
            for entry in getattr(rnd, "plan", []) or []:
                planned = _series_config_from_settings(settings, entry.series_key)
                spans.append(_series_span(planned.pattern))
            if not spans:
                continue
            stage = stages.setdefault(key, {"first": index, "span": 0})
            stage["span"] = max(stage["span"], *spans)
            self._stage_of[rnd.name] = key
        order = sorted(
            stages,
            key=lambda k: (_STAGE_ORDER.get(k, len(_STAGE_ORDER)), stages[k]["first"]),
        )
        self._start: Dict[str, int] = {}
        day = 0
        for key in order:
            self._start[key] = day
            day += stages[key]["span"] + 1

    def game_day(self, round_name: str, matchup: Matchup, slot: int) -> Optional[int]:
        key = self._stage_of.get(round_name)
        if key is None:
            return None
        offsets = _series_day_offsets(matchup.config.pattern)
        if slot >= len(offsets):
            return None
        return self._start[key] + offsets[slot]

    def date_for(self, day: Optional[int]) -> Optional[str]:
        if day is None or self.season_end is None:
            return None
        return (self.season_end + _timedelta(days=2 + day)).isoformat()


def _default_simulate_game():
    """The real game simulator, flagged as a postseason game."""

    from playbalance.game_runner import simulate_game_scores

    return functools.partial(simulate_game_scores, postseason=True)


def _call_simulate_game(simulate_game, home: str, away: str, *, seed: int, game_date: Optional[str]):
    """Call ``simulate_game`` with the keywords it accepts.

    ``seed`` is passed whenever it is accepted, ``game_date`` only when the
    game has a date. Test stubs and older callers keep their signatures.
    """

    kwargs: Dict[str, Any] = {"seed": seed}
    if game_date is not None:
        kwargs["game_date"] = game_date
    try:
        params = inspect.signature(simulate_game).parameters
    except (TypeError, ValueError):
        params = None
    if params is not None and not any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    ):
        kwargs = {key: value for key, value in kwargs.items() if key in params}
    return simulate_game(home, away, **kwargs)


def _unpack_result(result: Any) -> Tuple[Any, Any, Optional[str], Dict[str, Any]]:
    home_runs = away_runs = None
    html = None
    extra: Dict[str, Any] = {}
    if isinstance(result, tuple):
        if len(result) >= 2:
            home_runs, away_runs = result[0], result[1]
        if len(result) >= 3:
            html = result[2] if isinstance(result[2], str) else None
        if len(result) >= 4 and isinstance(result[3], dict):
            extra = result[3]
    return home_runs, away_runs, html, extra


def simulate_series(
    matchup: Matchup,
    *,
    year: int,
    round_name: str,
    series_index: int,
    simulate_game=None,
    date_for_slot=None,
) -> Matchup:
    """Simulate a single series to completion and return the updated matchup.

    ``date_for_slot(slot) -> "YYYY-MM-DD" | None`` dates each game; without it
    the games are undated. The bracket-level entry points date every game.
    """

    while not matchup.winner:
        slot = _played_slots(matchup)
        game_date = date_for_slot(slot) if callable(date_for_slot) else None
        if not _simulate_next_series_game(
            matchup,
            year=year,
            round_name=round_name,
            series_index=series_index,
            simulate_game=simulate_game,
            game_date=game_date,
        ):
            break
    return matchup


def _simulate_next_series_game(
    matchup: Matchup,
    *,
    year: int,
    round_name: str,
    series_index: int,
    simulate_game=None,
    game_date: Optional[str] = None,
) -> bool:
    """Simulate the next unplayed game in a series.

    Returns True when a game was added. A tie is never added (see
    ``_TIE_TRIES``), and a stored tie does not use up a slot.
    """

    wins_needed = _wins_needed(matchup.config.length)
    high_id = matchup.high.team_id
    low_id = matchup.low.team_id
    if not high_id or not low_id:
        return False

    existing_high, existing_low = _count_series_wins(matchup)
    if existing_high >= wins_needed or existing_low >= wins_needed:
        matchup.winner = high_id if existing_high >= wins_needed else low_id
        return False

    real_games = simulate_game is None
    if simulate_game is None:
        simulate_game = _default_simulate_game()

    homes = _home_order(matchup)
    played_games = min(_played_slots(matchup), len(homes))
    if played_games >= len(homes):
        return False

    home = homes[played_games]
    away = low_id if home == high_id else high_id
    seed_parts = [str(year), round_name, str(series_index), str(played_games), home, away]
    if real_games:
        from services.roster_fill import prepare_teams_for_game

        prepare_teams_for_game((home, away))
    for attempt in range(_TIE_TRIES):
        # The first try keeps the pre-Release-3 seed; retries salt it.
        parts = seed_parts if attempt == 0 else seed_parts + [f"tie-retry-{attempt}"]
        result = _call_simulate_game(
            simulate_game,
            home,
            away,
            seed=_deterministic_seed(*parts),
            game_date=game_date,
        )
        home_runs, away_runs, html, extra = _unpack_result(result)
        tied = (
            isinstance(home_runs, int)
            and isinstance(away_runs, int)
            and home_runs == away_runs
        )
        if not tied:
            break
    else:
        try:
            from services import boxscore_diagnostics as _diag

            _diag.record_failure(
                "playoffs:tie",
                f"{year}_{round_name}_S{series_index}_G{played_games}_{away}_at_{home}",
                ValueError(f"game still tied after {_TIE_TRIES} tries; slot left unplayed"),
            )
        except Exception:
            pass
        return False

    high_wins = existing_high
    low_wins = existing_low
    if isinstance(home_runs, int) and isinstance(away_runs, int):
        winner_team = home if home_runs > away_runs else away
        if winner_team == high_id:
            high_wins += 1
        elif winner_team == low_id:
            low_wins += 1

    box_path = None
    # Box score ids run on the stored game count, so a game replayed over a
    # stored tie gets its own file.
    game_id = f"{year}_{round_name}_S{series_index}_G{len(matchup.games)}_{away}_at_{home}"
    if html:
        try:
            from playbalance.simulation import save_boxscore_html as _save_html

            box_path = _save_html("playoffs", html, game_id)
            from services import boxscore_diagnostics as _diag

            _diag.record_success()
        except Exception as exc:
            box_path = None
            try:
                from services import boxscore_diagnostics as _diag

                _diag.record_failure("playoffs_single:save", game_id, exc)
            except Exception:
                pass
    else:
        # `if html:` had no else, so a missing box score vanished without trace.
        # Describe what the simulator actually handed back, so one sim settles
        # whether the HTML is missing or the write is failing.
        try:
            from services import boxscore_diagnostics as _diag

            shape = {
                "result_type": type(result).__name__,
                "result_len": len(result) if isinstance(result, tuple) else "n/a",
                "elem2_type": (
                    type(result[2]).__name__
                    if isinstance(result, tuple) and len(result) >= 3
                    else "absent"
                ),
                "elem2_len": (
                    len(result[2])
                    if isinstance(result, tuple)
                    and len(result) >= 3
                    and isinstance(result[2], str)
                    else "n/a"
                ),
                "simulate_game": getattr(simulate_game, "__name__", str(simulate_game)),
            }
            _diag.record_failure(
                "playoffs_single:no_html",
                game_id,
                ValueError("simulator returned no boxscore html"),
                extra=shape,
            )
        except Exception:
            pass

    result_str = None
    if isinstance(home_runs, int) and isinstance(away_runs, int):
        result_str = f"{home_runs}-{away_runs}"

    matchup.games.append(
        GameResult(home=home, away=away, date=game_date, result=result_str, boxscore=box_path, meta=extra)
    )

    if high_wins >= wins_needed or low_wins >= wins_needed:
        matchup.winner = high_id if high_wins >= wins_needed else low_id
    else:
        matchup.winner = None
    return True


def _league_from_round_name(name: str) -> Optional[str]:
    # e.g., "AL DS" -> "AL"
    parts = str(name).split()
    return parts[0] if parts and parts[0] not in {"WC", "DS", "CS", "WS", "Final"} else (parts[0] if len(parts) > 1 else None)


def _populate_next_round(bracket: PlayoffBracket, cfg: Any) -> None:
    """Populate planned matchups when prerequisites are met."""

    if not bracket.rounds:
        return

    by_name: Dict[str, Round] = {r.name: r for r in bracket.rounds}
    lengths, patterns = _extract_series_settings(cfg)
    seeds_map = getattr(bracket, "seeds_by_league", {}) or {}

    def make_cfg(key: str) -> SeriesConfig:
        length = int(lengths.get(key, _DEFAULT_SERIES_LENGTHS.get(key, 7)))
        if length <= 0:
            length = _DEFAULT_SERIES_LENGTHS.get(key, 7)
        pattern = _pattern_for_length(length, patterns)
        return SeriesConfig(length=length, pattern=pattern)

    def seed_team(ref: ParticipantRef) -> Optional[PlayoffTeam]:
        league = ref.league or ""
        seed_no = ref.seed
        if seed_no is None:
            return None
        for team in seeds_map.get(league, []):
            if team.seed == seed_no:
                return team
        return None

    def round_winner(ref: ParticipantRef) -> Optional[PlayoffTeam]:
        source_round = by_name.get(ref.source_round or "")
        if not source_round or ref.slot >= len(source_round.matchups):
            return None
        matchup = source_round.matchups[ref.slot]
        win_id = matchup.winner
        if not win_id:
            return None
        if matchup.high.team_id == win_id:
            return matchup.high
        if matchup.low.team_id == win_id:
            return matchup.low
        return None

    for rnd in bracket.rounds:
        if not rnd.plan:
            continue
        existing_pairs = {tuple(sorted((m.high.team_id, m.low.team_id))) for m in rnd.matchups}
        for entry in rnd.plan:
            participants: List[PlayoffTeam] = []
            for ref in entry.sources:
                team: Optional[PlayoffTeam] = None
                if ref.kind == "seed":
                    team = seed_team(ref)
                elif ref.kind == "winner":
                    team = round_winner(ref)
                if team is None:
                    participants = []
                    break
                participants.append(team)

            if len(participants) != 2:
                continue

            pair_key = tuple(sorted((participants[0].team_id, participants[1].team_id)))
            if pair_key in existing_pairs:
                continue

            participants.sort(key=lambda t: (t.seed, -t.wins, -t.run_diff, t.team_id))
            high, low = participants[0], participants[1]
            rnd.matchups.append(Matchup(high=high, low=low, config=make_cfg(entry.series_key)))
            existing_pairs.add(pair_key)



def _populate(bracket: PlayoffBracket) -> None:
    # The league's configured lengths (Release 3 fix round): a planned round
    # used to be built with the MLB defaults whatever the league configured,
    # and only reshaped to the configured length on the next load.
    _populate_next_round(bracket, cfg=_plan_series_settings())


def _sync_mirror_matchups(bracket: PlayoffBracket) -> set[int]:
    """Keep display copies of a series in step with the series itself.

    A single-league bracket repeats its league final as a "Final" round. In
    memory the two rounds share the matchup objects, but a saved bracket loads
    them as separate copies; a later copy of the same pairing mirrors the
    first one instead of being played again. Returns the ids of the mirrors.
    """

    seen: Dict[Tuple[str, str], Matchup] = {}
    mirrors: set[int] = set()
    for rnd in bracket.rounds:
        for matchup in rnd.matchups:
            pair = (matchup.high.team_id, matchup.low.team_id)
            source = seen.get(pair)
            if source is None:
                seen[pair] = matchup
                continue
            if source is not matchup:
                matchup.games = list(source.games)
                matchup.winner = source.winner
                mirrors.add(id(matchup))
    return mirrors


def _sync_winner(matchup: Matchup) -> None:
    wins_needed = _wins_needed(matchup.config.length)
    wins_high, wins_low = _count_series_wins(matchup)
    if wins_high >= wins_needed:
        matchup.winner = matchup.high.team_id
    elif wins_low >= wins_needed:
        matchup.winner = matchup.low.team_id


def _is_pending(matchup: Matchup) -> bool:
    return bool(
        not matchup.winner
        and matchup.high
        and matchup.low
        and matchup.high.team_id
        and matchup.low.team_id
    )


def _resolve_champion(bracket: PlayoffBracket) -> bool:
    """Set the champion once a championship round is decided."""

    champ_round_names = _championship_round_names(bracket)
    for rnd in bracket.rounds:
        if rnd.name not in champ_round_names or not rnd.matchups:
            continue
        if not all(m.winner for m in rnd.matchups):
            continue
        final = rnd.matchups[0]
        champ_id = final.winner
        if not champ_id:
            continue
        bracket.champion = champ_id
        bracket.runner_up = (
            final.low.team_id if champ_id == final.high.team_id else final.high.team_id
        )
        return True
    return False


def _scheduled_games(bracket: PlayoffBracket, calendar: _PlayoffCalendar):
    """Every pending series' next game as (day, round, series index, matchup)."""

    mirrors = _sync_mirror_matchups(bracket)
    games = []
    seen: set[int] = set()
    for rnd in bracket.rounds:
        for idx, matchup in enumerate(rnd.matchups):
            if id(matchup) in seen or id(matchup) in mirrors:
                continue
            seen.add(id(matchup))
            _sync_winner(matchup)
            if not _is_pending(matchup):
                continue
            day = calendar.game_day(rnd.name, matchup, _played_slots(matchup))
            if day is None:
                continue
            games.append((day, rnd, idx, matchup))
    return games


def _play_next_day(bracket: PlayoffBracket, *, year: int, simulate_game, persist) -> bool:
    """Play every playoff game on the earliest date that still has one.

    Games run in calendar order across all series and both leagues, so the
    rotation and bullpen rest clocks only ever move forward. Returns True if
    any game was added.
    """

    _populate(bracket)
    calendar = _PlayoffCalendar(bracket, _regular_season_end(year))
    games = _scheduled_games(bracket, calendar)
    if not games:
        return False
    today = min(day for day, _, _, _ in games)
    game_date = calendar.date_for(today)
    progressed = False
    for day, rnd, idx, matchup in games:
        if day != today:
            continue
        if _simulate_next_series_game(
            matchup,
            year=year,
            round_name=rnd.name,
            series_index=idx,
            simulate_game=simulate_game,
            game_date=game_date,
        ):
            progressed = True
            persist()
    _sync_mirror_matchups(bracket)
    _populate(bracket)
    return progressed


def _persist_fn(bracket: PlayoffBracket, persist_cb):
    def persist():
        try:
            if persist_cb:
                persist_cb(bracket)
            else:
                save_bracket(bracket)
        except Exception:
            pass

    return persist


def simulate_playoffs(bracket: PlayoffBracket, *, simulate_game=None, persist_cb=None) -> PlayoffBracket:
    """Simulate playoffs from current state to the end.

    - Plays the postseason one calendar day at a time (see ``_play_next_day``)
    - Populates each round's matchups as their participants are decided
    - Calls ``persist_cb(bracket)`` after each game if provided
    """

    year = bracket.year or _get_year_from_schedule()
    persist = _persist_fn(bracket, persist_cb)
    _sync_mirror_matchups(bracket)
    while not _resolve_champion(bracket):
        if not _play_next_day(bracket, year=year, simulate_game=simulate_game, persist=persist):
            return bracket
    persist()
    return bracket


def simulate_next_game(bracket: PlayoffBracket, *, simulate_game=None, persist_cb=None) -> PlayoffBracket:
    """Simulate the next playoff day: one game in every series scheduled that day."""

    year = bracket.year or _get_year_from_schedule()
    persist = _persist_fn(bracket, persist_cb)
    _sync_mirror_matchups(bracket)
    if not _resolve_champion(bracket):
        _play_next_day(bracket, year=year, simulate_game=simulate_game, persist=persist)
        if _resolve_champion(bracket):
            persist()
    else:
        persist()
    return bracket


def simulate_next_round(bracket: PlayoffBracket, *, simulate_game=None, persist_cb=None) -> PlayoffBracket:
    """Simulate until the next round with pending series is decided.

    Days are played in calendar order, so other series scheduled on the same
    days (the other league's round of the same stage) are played as well.
    """

    year = bracket.year or _get_year_from_schedule()
    persist = _persist_fn(bracket, persist_cb)
    _populate(bracket)
    mirrors = _sync_mirror_matchups(bracket)
    target = None
    for rnd in bracket.rounds:
        for matchup in rnd.matchups:
            _sync_winner(matchup)
        if any(_is_pending(m) and id(m) not in mirrors for m in rnd.matchups):
            target = rnd
            break
    while target is not None and any(_is_pending(m) for m in target.matchups):
        if not _play_next_day(bracket, year=year, simulate_game=simulate_game, persist=persist):
            break
        _sync_mirror_matchups(bracket)
    _resolve_champion(bracket)
    persist()
    return bracket


__all__ = [
    "PlayoffTeam",
    "GameResult",
    "SeriesConfig",
    "Matchup",
    "ParticipantRef",
    "RoundPlanEntry",
    "Round",
    "PlayoffBracket",
    "save_bracket",
    "load_bracket",
    "bracket_is_empty",
    "generate_bracket",
    "simulate_series",
    "simulate_playoffs",
    "simulate_next_game",
    "simulate_next_round",
]
