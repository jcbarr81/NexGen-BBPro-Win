"""Twenty seasons of player development for a whole league, without games.

The stationarity gate of the development model (``playbalance/development``,
``RATING_SCALE_DESIGN.md`` section 3): a league converted to rating scale 2
(``utils.rating_scale.stretch_rows``) is run through N offseasons of

1. development (the real model, every player in the file);
2. retirements (the real rules, ``services.player_retirement.should_retire``,
   by roster level);
3. the amateur draft: a class from the real generator on scale 2
   (``playbalance.draft_pool.generate_draft_pool``), picked in a random
   order by the real draft AI (``services.draft_ai.score_prospect``), the
   picks joining the low minors;
4. roster upkeep: an organisation over the limit (``ORG_LIMIT``) releases
   its weakest players (never this year's picks) to free agency, one under
   it signs the best free agents, and every club re-sorts into the active
   roster (13 pitchers, 13 hitters), AAA and LOW by the shared overall, a
   prospect's youth counting as the roster auto-assign counts it.

and the league's regulars are measured each year: every club's best nine
active hitters and best ten active pitchers by the shared overall. No game
is played: playing time does not feed development.

Simplifications, stated plainly: positions are not balanced on the active
roster; free agents never retire (as in a league today) and are not signed
past 35; injuries are ignored; the draft order is random; budgets and
training focus are neutral unless given.

Nothing here touches a league directory. The league is read, converted in
memory and worked on in a temporary folder.

Usage::

    python scripts/development_population_sim.py --league data/calibration_league \
        --seasons 20 --seed 1 --output out.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from playbalance.development import (  # noqa: E402
    DEFAULT_PARAMS,
    DevelopmentParams,
    develop_player,
    params_with,
)
from utils.rating_scale import (  # noqa: E402
    FULL_RATING_SCALE,
    RATING_SCALE_FIELD,
    rating_scale_of,
    stretch_rows,
)
from utils.roster_rules import (  # noqa: E402
    AAA_CAP,
    ACT_HITTER_TARGET,
    LOW_CAP,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
)

PITCH_KEYS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")
HITTER_GATE = ("ch", "ph", "eye")
PITCHER_GATE = ("control", "movement")
HITTER_ALSO = ("sp", "fa", "arm")
PITCHER_ALSO = ("arm", "endurance", "fb")
REGULAR_HITTERS = 9
REGULAR_PITCHERS = 10
LOW_MAX_AGE = 27
FREE_AGENT_MAX_AGE = 35
AGE_BANDS: Tuple[Tuple[str, int, int], ...] = (
    ("<=21", 0, 21),
    ("22-24", 22, 24),
    ("25-27", 25, 27),
    ("28-30", 28, 30),
    ("31-33", 31, 33),
    ("34+", 34, 99),
)
INJURED_LEVELS = {"DL", "DL15", "DL45", "DL60", "IR"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _read_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _write_rows(path: Path, fields: List[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})


def _load_objects(path: Path) -> Dict[str, Any]:
    from utils.player_loader import _read_players_from_csv

    return {p.player_id: p for p in _read_players_from_csv(path)}


def _stretched_rows(league: Path) -> Tuple[List[str], List[Dict[str, str]], int]:
    fields, rows = _read_rows(league / "players.csv")
    for row in rows:
        for key in PITCH_KEYS:
            if row.get(key, None) == "":
                row[key] = "0"
    stretched, clips = stretch_rows(rows, FULL_RATING_SCALE)
    added = sorted({k for r in stretched for k in r} - set(fields) - {RATING_SCALE_FIELD})
    fields = [f for f in fields if f != RATING_SCALE_FIELD] + added + [RATING_SCALE_FIELD]
    return fields, stretched, sum(1 for c in clips if c.kind == "rating")


def _rosters(league: Path) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for path in sorted((league / "rosters").glob("*.csv")):
        if path.stem.endswith(("_pitching", "_lineup")):
            continue
        levels: Dict[str, str] = {}
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and row[0].strip():
                    level = row[1].strip().upper()
                    levels[row[0].strip()] = "ACT" if level in INJURED_LEVELS else level
        out[path.stem] = levels
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _age(player: Any, on: date) -> int:
    born = date.fromisoformat(str(player.birthdate).split("T", 1)[0])
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _overall(player: Any) -> float:
    from utils.player_overall import player_overall_score

    score = player_overall_score(player)
    return 0.0 if score is None else float(score)


def _is_pitcher(player: Any) -> bool:
    from utils.roster_rules import counts_as_pitcher

    return bool(counts_as_pitcher(player))


def _prospect_value(player: Any, on: date) -> float:
    # services.roster_auto_assign: 1.5 a year under 21.
    return _overall(player) + max(0, 21 - _age(player, on)) * 1.5


def _stored(player: Any, key: str) -> Optional[float]:
    value = getattr(player, key, None)  # rating-scale: measures stored values
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _summary(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "sd": 0.0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "sd": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# The league in memory
# ---------------------------------------------------------------------------

class League:
    def __init__(self, league_dir: Path, work: Path, *, start_year: int) -> None:
        fields, rows, clipped = _stretched_rows(league_dir)
        self.fields = fields
        self.clipped = clipped
        work.mkdir(parents=True, exist_ok=True)
        path = work / "players_start.csv"
        _write_rows(path, fields, rows)
        self.players: Dict[str, Any] = _load_objects(path)
        rosters = _rosters(league_dir)
        self.level: Dict[str, str] = {}
        self.team: Dict[str, str] = {}
        for team, levels in rosters.items():
            for pid, level in levels.items():
                if pid in self.players:
                    self.team[pid] = team
                    self.level[pid] = level if level in ("ACT", "AAA", "LOW") else "ACT"
        self.teams = sorted(rosters)
        self.work = work
        self.year = start_year
        self.draft_round = 0

    def org(self, team: str) -> List[str]:
        return [pid for pid, t in self.team.items() if t == team]

    def free_agents(self) -> List[str]:
        return [pid for pid in self.players if pid not in self.team]


def _develop_all(league: League, season: int, params: DevelopmentParams,
                 budgets: Mapping[str, float], weights: Mapping[str, Any]) -> None:
    on = date(season - 1, 10, 31)
    for pid, player in league.players.items():
        if rating_scale_of(player) != FULL_RATING_SCALE:
            continue
        team = league.team.get(pid)
        budget = float(budgets.get(team, 1.0)) if team else 1.0
        develop_player(
            player,
            age=_age(player, on),
            season=season,
            development=budget,
            intensity=budget,
            weights=weights.get(team) if team else None,
            params=params,
        )


def _retire(league: League, season: int) -> int:
    from services.player_retirement import should_retire

    on = date(season - 1, 10, 31)
    gone = []
    for pid, team in list(league.team.items()):
        player = league.players[pid]
        if should_retire(player, age=_age(player, on), level=league.level.get(pid, "ACT")):
            gone.append(pid)
    for pid in gone:
        league.team.pop(pid, None)
        league.level.pop(pid, None)
        league.players.pop(pid, None)
    # Free agents never retire in a league; past signing age they are only
    # dead weight for this simulation.
    for pid in league.free_agents():
        if _age(league.players[pid], on) > FREE_AGENT_MAX_AGE + 4:
            league.players.pop(pid, None)
    return len(gone)


def _needs(league: League, team: str) -> Dict[str, float]:
    from services.draft_ai import POSITION_TARGETS, RP_TARGET, SP_TARGET
    from utils.pitcher_role import get_role

    counts = {key: 0 for key in POSITION_TARGETS}
    sp = rp = 0
    for pid in league.org(team):
        player = league.players[pid]
        if _is_pitcher(player):
            if get_role(player) == "SP":
                sp += 1
            else:
                rp += 1
        else:
            primary = str(getattr(player, "primary_position", "")).upper()
            if primary in counts:
                counts[primary] += 1
    needs = {
        pos: min(1.0, max(0.0, (target - counts[pos]) / max(target, 1)))
        for pos, target in POSITION_TARGETS.items()
    }
    needs["SP"] = min(1.0, max(0.0, (SP_TARGET - sp) / SP_TARGET))
    needs["RP"] = min(1.0, max(0.0, (RP_TARGET - rp) / RP_TARGET))
    return needs


def _draft(league: League, season: int, *, rounds: int, pool_size: int, seed: int,
           rng: random.Random) -> List[str]:
    from playbalance.draft_pool import generate_draft_pool
    from services.draft_ai import score_prospect

    pool = generate_draft_pool(
        season, size=pool_size, seed=seed, rating_scale=FULL_RATING_SCALE
    )
    today = date.today()
    entries: List[Dict[str, Any]] = []
    for prospect in pool:
        row = asdict(prospect)
        # The generator dates a birth from the real calendar, not the
        # league's (docs/future_work.md): re-date it to the league year so
        # a 19-year-old is 19 in this draft.
        born = date.fromisoformat(str(row["birthdate"]).split("T", 1)[0])
        rolled = today.year - born.year
        row["birthdate"] = date(season - rolled, born.month, min(born.day, 28)).isoformat()
        entries.append(row)
    order = list(league.teams)
    rng.shuffle(order)
    picked: List[Dict[str, Any]] = []
    remaining = list(entries)
    for _ in range(rounds):
        for team in order:
            if not remaining:
                break
            needs = _needs_cache.setdefault(team, _needs(league, team))
            best = max(remaining, key=lambda p: score_prospect(p, needs))
            remaining.remove(best)
            best["_team"] = team
            picked.append(best)
    _needs_cache.clear()
    if not picked:
        return []
    fields = list(league.fields)
    rows = []
    for entry in picked:
        row = {k: entry.get(k, "") for k in fields}
        row["other_positions"] = "|".join(entry.get("other_positions") or [])
        row["is_pitcher"] = "1" if entry.get("is_pitcher") else "0"
        row[RATING_SCALE_FIELD] = str(entry.get("rating_scale", FULL_RATING_SCALE))
        for key in ("injured",):
            row[key] = "False"
        rows.append(row)
    path = league.work / f"draft_{season}.csv"
    _write_rows(path, fields, rows)
    drafted = _load_objects(path)
    ids = []
    for entry in picked:
        pid = entry["player_id"]
        new_id = f"{pid}"
        player = drafted[pid]
        league.players[new_id] = player
        league.team[new_id] = entry["_team"]
        league.level[new_id] = "LOW"
        ids.append(new_id)
    return ids


_needs_cache: Dict[str, Dict[str, float]] = {}


def _upkeep(league: League, season: int, picks: Iterable[str]) -> Dict[str, int]:
    on = date(season, 3, 1)
    protected = set(picks)
    released = signed = 0
    for team in league.teams:
        org = league.org(team)
        if len(org) > ORG_LIMIT:
            spare = sorted(
                (pid for pid in org if pid not in protected),
                key=lambda pid: _prospect_value(league.players[pid], on),
            )
            for pid in spare[: len(org) - ORG_LIMIT]:
                league.team.pop(pid, None)
                league.level.pop(pid, None)
                released += 1
    pool = sorted(
        (pid for pid in league.free_agents()
         if _age(league.players[pid], on) <= FREE_AGENT_MAX_AGE),
        key=lambda pid: _overall(league.players[pid]),
        reverse=True,
    )
    for team in sorted(league.teams, key=lambda t: len(league.org(t))):
        org = league.org(team)
        pitchers = sum(1 for pid in org if _is_pitcher(league.players[pid]))
        hitters = len(org) - pitchers
        while len(org) < ORG_LIMIT and pool:
            want_pitcher = pitchers < MAX_ACTIVE_PITCHERS + 6 and (
                hitters >= ACT_HITTER_TARGET + 6 or pitchers <= hitters
            )
            choice = next(
                (pid for pid in pool if _is_pitcher(league.players[pid]) == want_pitcher),
                pool[0],
            )
            pool.remove(choice)
            league.team[choice] = team
            league.level[choice] = "AAA"
            org.append(choice)
            signed += 1
            if _is_pitcher(league.players[choice]):
                pitchers += 1
            else:
                hitters += 1
    for team in league.teams:
        _assign_levels(league, team, on)
    return {"released": released, "signed": signed}


def _assign_levels(league: League, team: str, on: date) -> None:
    org = league.org(team)
    pitchers = sorted(
        (pid for pid in org if _is_pitcher(league.players[pid])),
        key=lambda pid: _overall(league.players[pid]),
        reverse=True,
    )
    hitters = sorted(
        (pid for pid in org if not _is_pitcher(league.players[pid])),
        key=lambda pid: _overall(league.players[pid]),
        reverse=True,
    )
    act = set(pitchers[:MAX_ACTIVE_PITCHERS]) | set(hitters[:ACT_HITTER_TARGET])
    rest = sorted(
        (pid for pid in org if pid not in act),
        key=lambda pid: _prospect_value(league.players[pid], on),
        reverse=True,
    )
    young = [pid for pid in rest if _age(league.players[pid], on) < LOW_MAX_AGE]
    low = set(sorted(young, key=lambda pid: _age(league.players[pid], on))[:LOW_CAP])
    for pid in org:
        if pid in act:
            league.level[pid] = "ACT"
        elif pid in low:
            league.level[pid] = "LOW"
        else:
            league.level[pid] = "AAA"


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def _regulars(league: League) -> Tuple[List[Any], List[Any]]:
    hitters: List[Any] = []
    pitchers: List[Any] = []
    for team in league.teams:
        act = [league.players[pid] for pid in league.org(team) if league.level.get(pid) == "ACT"]
        hit = sorted((p for p in act if not _is_pitcher(p)), key=_overall, reverse=True)
        pit = sorted((p for p in act if _is_pitcher(p)), key=_overall, reverse=True)
        hitters.extend(hit[:REGULAR_HITTERS])
        pitchers.extend(pit[:REGULAR_PITCHERS])
    return hitters, pitchers


def _measure(league: League, season: int) -> Dict[str, Any]:
    on = date(season, 7, 1)
    hitters, pitchers = _regulars(league)
    out: Dict[str, Any] = {"season": season, "players": len(league.players)}
    regulars: Dict[str, Any] = {}
    for key in HITTER_GATE + HITTER_ALSO:
        regulars[f"h_{key}"] = _summary([v for v in (_stored(p, key) for p in hitters) if v])
    for key in PITCHER_GATE + PITCHER_ALSO:
        regulars[f"p_{key}"] = _summary([v for v in (_stored(p, key) for p in pitchers) if v])
    out["regulars"] = regulars
    out["regular_age"] = {
        "hitters": round(statistics.fmean(_age(p, on) for p in hitters), 2),
        "pitchers": round(statistics.fmean(_age(p, on) for p in pitchers), 2),
    }
    # Everyone rostered: spread and the count at 99, per rating.
    rostered = [league.players[pid] for pid in league.team]
    every = list(league.players.values())
    spread: Dict[str, Any] = {}
    at_99: Dict[str, int] = {}
    hitter_keys = HITTER_GATE + HITTER_ALSO
    pitcher_keys = PITCHER_GATE + ("arm", "endurance", "hold_runner") + PITCH_KEYS
    for prefix, keys, pitcher in (("h", hitter_keys, False), ("p", pitcher_keys, True)):
        group = [p for p in rostered if _is_pitcher(p) == pitcher]
        whole = [p for p in every if _is_pitcher(p) == pitcher]
        for key in keys:
            values = [v for v in (_stored(p, key) for p in group) if v]
            spread[f"{prefix}_{key}"] = _summary(values)
            at_99[f"{prefix}_{key}"] = sum(1 for p in whole if (_stored(p, key) or 0) >= 99)
    out["rostered"] = spread
    out["at_99"] = at_99
    # Age curve: rostered players' mean composite by age band.
    curve: Dict[str, Dict[str, Any]] = {}
    for label, low, high in AGE_BANDS:
        hit = [p for p in rostered if not _is_pitcher(p) and low <= _age(p, on) <= high]
        pit = [p for p in rostered if _is_pitcher(p) and low <= _age(p, on) <= high]
        curve[label] = {
            "hitters": _summary([
                statistics.fmean(_stored(p, k) or 0 for k in HITTER_GATE) for p in hit
            ]),
            "pitchers": _summary([
                statistics.fmean(_stored(p, k) or 0 for k in PITCHER_GATE) for p in pit
            ]),
            "hitter_overall": _summary([_overall(p) for p in hit]),
            "pitcher_overall": _summary([_overall(p) for p in pit]),
        }
    out["age_curve"] = curve
    return out


def _track(league: League, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for pid in ids:
        player = league.players.get(pid)
        if player is None:
            continue
        keys = PITCHER_GATE + ("arm",) if _is_pitcher(player) else HITTER_GATE
        out[pid] = {
            "team": league.team.get(pid, "FA"),
            "level": league.level.get(pid, "FA"),
            **{k: _stored(player, k) for k in keys},
            **{f"pot_{k}": (player.potential or {}).get(k) for k in keys},
        }
    return out


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def simulate(
    league_dir: Path,
    *,
    seasons: int = 20,
    seed: int = 1,
    start_year: int = 2026,
    rounds: int = 10,
    pool_size: int = 200,
    params: DevelopmentParams = DEFAULT_PARAMS,
    budgets: Optional[Mapping[str, float]] = None,
    weights: Optional[Mapping[str, Any]] = None,
    work_dir: Optional[Path] = None,
    progress: Optional[Callable[[str], None]] = None,
    track: int = 6,
) -> Dict[str, Any]:
    """Run the population; returns the yearly measurements and the paths of
    a few tracked prospects (the first ``track`` picks of the first draft)."""

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(work_dir) if work_dir else Path(tmp)
        league = League(Path(league_dir), work, start_year=start_year)
        # Year 0 is measured with the clubs sorted by the same rule as every
        # later year, so the first year's change is development, not a
        # different way of choosing the regulars.
        for team in league.teams:
            _assign_levels(league, team, date(start_year, 3, 1))
        rng = random.Random(f"population:{seed}")
        report: Dict[str, Any] = {
            "league": str(league_dir),
            "seed": seed,
            "seasons": seasons,
            "clipped_at_conversion": league.clipped,
            "years": [_measure(league, start_year)],
        }
        tracked: List[str] = []
        paths: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for season in range(start_year + 1, start_year + seasons + 1):
            _develop_all(league, season, params, budgets or {}, weights or {})
            retired = _retire(league, season)
            picks = _draft(
                league, season, rounds=rounds, pool_size=pool_size,
                seed=seed * 1000 + season, rng=rng,
            )
            if not tracked:
                tracked = picks[:track]
            moves = _upkeep(league, season, picks)
            year = _measure(league, season)
            year.update({"retired": retired, "drafted": len(picks), **moves})
            report["years"].append(year)
            for pid, state in _track(league, tracked).items():
                paths[pid].append({"season": season, **state})
            if progress:
                r = year["regulars"]
                progress(
                    f"{season}: players {year['players']} retired {retired} "
                    f"ch {r['h_ch']['mean']} ph {r['h_ph']['mean']} "
                    f"eye {r['h_eye']['mean']} con {r['p_control']['mean']} "
                    f"mov {r['p_movement']['mean']}"
                )
        report["tracked"] = dict(paths)
        return report


def gate(report: Mapping[str, Any], *, band: float = 3.0) -> Dict[str, Any]:
    """The stationarity gate on a report: each gated regular mean's largest
    distance from year 0, and the most players at 99 in any rating."""

    years = report["years"]
    base = years[0]["regulars"]
    worst: Dict[str, float] = {}
    for key in [f"h_{k}" for k in HITTER_GATE] + [f"p_{k}" for k in PITCHER_GATE]:
        worst[key] = round(
            max(abs(y["regulars"][key]["mean"] - base[key]["mean"]) for y in years), 2
        )
    most_99 = max(max(y["at_99"].values()) for y in years)
    return {
        "max_mean_drift": worst,
        "within_band": all(v <= band for v in worst.values()),
        "most_at_99": most_99,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--league", required=True, type=Path)
    parser.add_argument("--seasons", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--start-year", type=int, default=2026)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--pool-size", type=int, default=200)
    parser.add_argument("--params", type=Path, default=None,
                        help="JSON of DevelopmentParams fields to override")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    params = DEFAULT_PARAMS
    if args.params:
        params = params_with(params, **json.loads(args.params.read_text(encoding="utf-8")))
    report = simulate(
        args.league,
        seasons=args.seasons,
        seed=args.seed,
        start_year=args.start_year,
        rounds=args.rounds,
        pool_size=args.pool_size,
        params=params,
        progress=lambda line: print(line, flush=True),
    )
    report["gate"] = gate(report)
    args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["gate"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
