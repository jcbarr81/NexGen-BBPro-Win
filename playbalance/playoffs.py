from __future__ import annotations

"""Postseason data structures, persistence, and (later) simulation.

This module provides the bracket model and load/save helpers. Seeding and
simulation are implemented in subsequent tickets; here we define the
data-shapes and stable JSON schema to support resume and UI rendering.
"""

import hashlib
import json
from datetime import date as _date
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from playbalance.playoffs_config import DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE
from services.standings_repository import load_standings
from utils.path_utils import get_base_dir


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


def _bracket_path(year: int | None = None) -> Path:
    base = get_base_dir() / "data"
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
        base = get_base_dir() / "data"
        try:
            matches = list(base.glob("playoffs_*.json"))
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

    sched = get_base_dir() / "data" / "schedule.csv"
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


def simulate_series(matchup: Matchup, *, year: int, round_name: str, series_index: int, simulate_game=None) -> Matchup:
    """Simulate a single series to completion and return the updated matchup."""

    wins_needed = _wins_needed(matchup.config.length)
    high_id = matchup.high.team_id
    low_id = matchup.low.team_id

    # Build home/away order for games according to pattern
    homes: List[str] = []
    flip = False
    for block in matchup.config.pattern:
        homes.extend([high_id if not flip else low_id] * block)
        flip = not flip

    existing_high, existing_low = _count_series_wins(matchup)
    if existing_high >= wins_needed or existing_low >= wins_needed:
        matchup.winner = high_id if existing_high >= wins_needed else low_id
        return matchup

    if simulate_game is None:
        from playbalance.game_runner import simulate_game_scores as _sim
        simulate_game = _sim

    high_wins = existing_high
    low_wins = existing_low
    played_games = min(len(matchup.games), len(homes))
    game_no = played_games

    for home in homes[played_games:]:
        if high_wins >= wins_needed or low_wins >= wins_needed:
            break
        away = low_id if home == high_id else high_id
        seed = _deterministic_seed(str(year), round_name, str(series_index), str(game_no), home, away)
        # Call simulate_game with keyword seed if accepted; otherwise rely on RNG state
        try:
            result = simulate_game(home, away, seed=seed)
        except TypeError:
            result = simulate_game(home, away)

        # Parse result tuple
        home_runs = away_runs = None
        html = None
        extra = {}
        if isinstance(result, tuple):
            if len(result) >= 2:
                home_runs, away_runs = result[0], result[1]
            if len(result) >= 3:
                html = result[2] if isinstance(result[2], str) else None
            if len(result) >= 4 and isinstance(result[3], dict):
                extra = result[3]
        # Winning side
        if isinstance(home_runs, int) and isinstance(away_runs, int):
            if home_runs > away_runs:
                winner_team = home
            elif away_runs > home_runs:
                winner_team = away
            else:
                winner_team = None
            if winner_team == high_id:
                high_wins += 1
            elif winner_team == low_id:
                low_wins += 1
        # Save boxscore html if provided
        box_path = None
        if html:
            try:
                from playbalance.simulation import save_boxscore_html as _save_html
                game_id = f"{year}_{round_name}_S{series_index}_G{game_no}_{away}_at_{home}"
                box_path = _save_html("playoffs", html, game_id)
            except Exception:
                box_path = None

        result_str = None
        if isinstance(home_runs, int) and isinstance(away_runs, int):
            result_str = f"{home_runs}-{away_runs}"

        matchup.games.append(
            GameResult(home=home, away=away, date=None, result=result_str, boxscore=box_path, meta=extra)
        )
        game_no += 1

    if high_wins >= wins_needed or low_wins >= wins_needed:
        matchup.winner = high_id if high_wins >= wins_needed else low_id
    else:
        matchup.winner = None
    return matchup


def _simulate_next_series_game(
    matchup: Matchup,
    *,
    year: int,
    round_name: str,
    series_index: int,
    simulate_game=None,
) -> bool:
    """Simulate the next unplayed game in a series."""

    wins_needed = _wins_needed(matchup.config.length)
    high_id = matchup.high.team_id
    low_id = matchup.low.team_id
    if not high_id or not low_id:
        return False

    existing_high, existing_low = _count_series_wins(matchup)
    if existing_high >= wins_needed or existing_low >= wins_needed:
        matchup.winner = high_id if existing_high >= wins_needed else low_id
        return False

    if simulate_game is None:
        from playbalance.game_runner import simulate_game_scores as _sim
        simulate_game = _sim

    homes: List[str] = []
    flip = False
    for block in matchup.config.pattern:
        homes.extend([high_id if not flip else low_id] * block)
        flip = not flip

    played_games = min(len(matchup.games), len(homes))
    if played_games >= len(homes):
        return False

    home = homes[played_games]
    away = low_id if home == high_id else high_id
    seed = _deterministic_seed(str(year), round_name, str(series_index), str(played_games), home, away)
    try:
        result = simulate_game(home, away, seed=seed)
    except TypeError:
        result = simulate_game(home, away)

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

    high_wins = existing_high
    low_wins = existing_low
    if isinstance(home_runs, int) and isinstance(away_runs, int):
        winner_team = None
        if home_runs > away_runs:
            winner_team = home
        elif away_runs > home_runs:
            winner_team = away
        if winner_team == high_id:
            high_wins += 1
        elif winner_team == low_id:
            low_wins += 1

    box_path = None
    if html:
        try:
            from playbalance.simulation import save_boxscore_html as _save_html
            game_id = f"{year}_{round_name}_S{series_index}_G{played_games}_{away}_at_{home}"
            box_path = _save_html("playoffs", html, game_id)
        except Exception:
            box_path = None

    result_str = None
    if isinstance(home_runs, int) and isinstance(away_runs, int):
        result_str = f"{home_runs}-{away_runs}"

    matchup.games.append(
        GameResult(home=home, away=away, date=None, result=result_str, boxscore=box_path, meta=extra)
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



def simulate_playoffs(bracket: PlayoffBracket, *, simulate_game=None, persist_cb=None) -> PlayoffBracket:
    """Simulate playoffs from current state to the end.

    - Simulates outstanding matchups in the first non-empty round(s)
    - After each round, populates the next round's matchups
    - Calls ``persist_cb(bracket)`` after each game if provided
    """

    year = bracket.year or _get_year_from_schedule()

    def persist():
        try:
            if persist_cb:
                persist_cb(bracket)
            else:
                save_bracket(bracket)
        except Exception:
            pass

    # Iterate until no progress can be made
    made_progress = True
    while made_progress:
        made_progress = False
        champ_round_names = _championship_round_names(bracket)
        # Simulate the first round that has pending matchups
        for r_index, rnd in enumerate(bracket.rounds):
            pendings = [i for i, m in enumerate(rnd.matchups) if not m.winner and m.high and m.low and m.high.team_id and m.low.team_id]
            if not pendings:
                if rnd.name in champ_round_names and rnd.matchups and all(m.winner for m in rnd.matchups):
                    champ_id = rnd.matchups[0].winner
                    if champ_id:
                        bracket.champion = champ_id
                        m = rnd.matchups[0]
                        bracket.runner_up = m.low.team_id if champ_id == m.high.team_id else m.high.team_id
                        persist()
                        return bracket
                continue
            for i in pendings:
                simulate_series(rnd.matchups[i], year=year, round_name=rnd.name, series_index=i, simulate_game=simulate_game)
                made_progress = True
                persist()
            # After completing this round (all winners set), populate next stage
            if all(m.winner for m in rnd.matchups):
                # Champion resolution if WS/Final
                if rnd.name in champ_round_names and rnd.matchups:
                    champ_id = rnd.matchups[0].winner
                    if champ_id:
                        bracket.champion = champ_id
                        # Runner-up is the other participant
                        m = rnd.matchups[0]
                        bracket.runner_up = m.low.team_id if champ_id == m.high.team_id else m.high.team_id
                        # Nothing else to populate; playoffs complete
                        persist()
                    return bracket
                _populate_next_round(bracket, cfg={
                    "series_lengths": getattr(bracket, "series_lengths", {"ds": 5, "cs": 7, "ws": 7, "wildcard": 3}),
                    "home_away_patterns": _DEFAULT_HOME_AWAY_PATTERNS,
                })
            break  # simulate one round at a time
    return bracket


def simulate_next_game(bracket: PlayoffBracket, *, simulate_game=None, persist_cb=None) -> PlayoffBracket:
    """Simulate the next playoff day (one game per active series in the round)."""

    year = bracket.year or _get_year_from_schedule()

    def persist():
        try:
            if persist_cb:
                persist_cb(bracket)
            else:
                save_bracket(bracket)
        except Exception:
            pass

    _populate_next_round(bracket, cfg={
        "series_lengths": getattr(bracket, "series_lengths", {"ds": 5, "cs": 7, "ws": 7, "wildcard": 3}),
        "home_away_patterns": _DEFAULT_HOME_AWAY_PATTERNS,
    })

    champ_round_names = _championship_round_names(bracket)
    for rnd in bracket.rounds:
        pendings = [
            i
            for i, m in enumerate(rnd.matchups)
            if not m.winner and m.high and m.low and m.high.team_id and m.low.team_id
        ]
        if not pendings:
            if rnd.name in champ_round_names and rnd.matchups and all(m.winner for m in rnd.matchups):
                champ_id = rnd.matchups[0].winner
                if champ_id:
                    bracket.champion = champ_id
                    m = rnd.matchups[0]
                    bracket.runner_up = m.low.team_id if champ_id == m.high.team_id else m.high.team_id
                    persist()
            continue
        progressed_any = False
        for idx in pendings:
            progressed = _simulate_next_series_game(
                rnd.matchups[idx],
                year=year,
                round_name=rnd.name,
                series_index=idx,
                simulate_game=simulate_game,
            )
            if progressed:
                progressed_any = True
                persist()
        if all(m.winner for m in rnd.matchups):
            if rnd.name in champ_round_names and rnd.matchups:
                champ_id = rnd.matchups[0].winner
                if champ_id:
                    bracket.champion = champ_id
                    m = rnd.matchups[0]
                    bracket.runner_up = m.low.team_id if champ_id == m.high.team_id else m.high.team_id
                persist()
                return bracket
            _populate_next_round(bracket, cfg={
                "series_lengths": getattr(bracket, "series_lengths", {"ds": 5, "cs": 7, "ws": 7, "wildcard": 3}),
                "home_away_patterns": _DEFAULT_HOME_AWAY_PATTERNS,
            })
            persist()
        break
    return bracket


def simulate_next_round(bracket: PlayoffBracket, *, simulate_game=None, persist_cb=None) -> PlayoffBracket:
    """Simulate only the next round that has any pending matchups."""

    year = bracket.year or _get_year_from_schedule()

    def persist():
        try:
            if persist_cb:
                persist_cb(bracket)
            else:
                save_bracket(bracket)
        except Exception:
            pass

    # Find the next round with pending matchups
    for r_index, rnd in enumerate(bracket.rounds):
        pendings = [i for i, m in enumerate(rnd.matchups) if not m.winner and m.high and m.low and m.high.team_id and m.low.team_id]
        if not pendings:
            champ_round_names = _championship_round_names(bracket)
            if rnd.name in champ_round_names and rnd.matchups and all(m.winner for m in rnd.matchups):
                champ_id = rnd.matchups[0].winner
                if champ_id:
                    bracket.champion = champ_id
                    m = rnd.matchups[0]
                    bracket.runner_up = m.low.team_id if champ_id == m.high.team_id else m.high.team_id
                persist()
            continue
        for i in pendings:
            simulate_series(rnd.matchups[i], year=year, round_name=rnd.name, series_index=i, simulate_game=simulate_game)
            persist()
        # After finishing this round, populate next round matchups
        if all(m.winner for m in rnd.matchups):
            champ_round_names = _championship_round_names(bracket)
            if rnd.name in champ_round_names and rnd.matchups:
                # Champion resolved
                champ_id = rnd.matchups[0].winner
                if champ_id:
                    bracket.champion = champ_id
                    m = rnd.matchups[0]
                    bracket.runner_up = m.low.team_id if champ_id == m.high.team_id else m.high.team_id
            else:
                _populate_next_round(bracket, cfg={
                    "series_lengths": getattr(bracket, "series_lengths", {"ds": 5, "cs": 7, "ws": 7, "wildcard": 3}),
                    "home_away_patterns": _DEFAULT_HOME_AWAY_PATTERNS,
                })
            persist()
        break
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
    "generate_bracket",
    "simulate_series",
    "simulate_playoffs",
    "simulate_next_game",
    "simulate_next_round",
]
