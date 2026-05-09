"""All-Star Game roster selection + flavor simulation.

Runs once per season when the simulator crosses the All-Star break
(midpoint of the schedule). The break itself was already a 6-day gap;
this adds the actual game.

v1 is intentionally lightweight:

  - **Roster selection** picks the top hitter at every position from
    each "squad" (division grouping) plus the top N pitchers, scored
    against current-season stats (OPS for hitters, ERA inverse + IP
    for pitchers).
  - **Game sim** is a flavor pass — combined squad-strength score
    drives a believable result; an MVP is picked from the winning
    squad with a generated stat line. Doesn't run through the full
    game engine because rosters are synthetic and don't have lineups
    or pitching staffs configured.
  - **Persistence** lives in ``<league>/all_star_games.json`` keyed by
    year so the page can scroll through history.

A future v2 could splice the all-star squads into temporary teams and
run the real game engine, but the flavor pass closes the gap that
"the break exists in name only".
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.stats_persistence import load_stats
from utils.team_loader import load_teams

_FILENAME = "all_star_games.json"
_HITTER_SLOTS = ("C", "1B", "2B", "SS", "3B", "LF", "CF", "RF", "DH")
_PITCHERS_PER_SQUAD = 5


# ---------------------------------------------------------------------------
# Persistence


def _path(data_dir: Optional[Path] = None) -> Path:
    return (data_dir or get_data_dir()) / _FILENAME


def load_all_star_history(
    data_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    path = _path(data_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_all_star_history(
    history: Dict[str, Dict[str, Any]],
    *,
    data_dir: Optional[Path] = None,
) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def load_all_star_year(
    year: int, *, data_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    return load_all_star_history(data_dir).get(str(year))


# ---------------------------------------------------------------------------
# Roster selection


def _squad_split(teams: Sequence[Any]) -> Dict[str, List[str]]:
    """Group the league's teams into two All-Star squads by division.

    Sorts divisions alphabetically and splits into halves so the result
    is stable. With 2 divisions each becomes a squad; with 4 the first
    two pair up against the second two.
    """

    by_div: Dict[str, List[str]] = {}
    for team in teams:
        team_id = str(getattr(team, "team_id", "") or "").strip().upper()
        division = str(getattr(team, "division", "") or "").strip()
        if not team_id or not division:
            continue
        by_div.setdefault(division, []).append(team_id)

    divisions = sorted(by_div.keys())
    if not divisions:
        return {}
    if len(divisions) == 1:
        # Tiny league — split the single division in half by team_id.
        only = sorted(by_div[divisions[0]])
        midpoint = max(1, len(only) // 2)
        return {
            "Squad A": only[:midpoint],
            "Squad B": only[midpoint:],
        }
    midpoint = max(1, len(divisions) // 2)
    a_divs = divisions[:midpoint]
    b_divs = divisions[midpoint:]
    return {
        " / ".join(a_divs): [
            t for div in a_divs for t in sorted(by_div.get(div, []))
        ],
        " / ".join(b_divs): [
            t for div in b_divs for t in sorted(by_div.get(div, []))
        ],
    }


def _player_team(rosters_dir: Path) -> Dict[str, str]:
    """Map player_id → current team_id from roster CSV files."""

    out: Dict[str, str] = {}
    if not rosters_dir.exists():
        return out
    import csv as _csv

    for roster_file in rosters_dir.glob("*.csv"):
        team_id = roster_file.stem
        if team_id.endswith("_pitching") or team_id.endswith("_lineup"):
            continue
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                for row in _csv.reader(fh):
                    if not row or len(row) < 2:
                        continue
                    pid = (row[0] or "").strip()
                    level = (row[1] or "").strip().upper()
                    # Only ACT players are All-Star eligible.
                    if pid and level == "ACT":
                        out.setdefault(pid, team_id)
        except OSError:
            continue
    return out


def _score_hitter(stats: Dict[str, Any]) -> float:
    obp = float(stats.get("obp") or 0)
    slg = float(stats.get("slg") or 0)
    pa = int(stats.get("pa") or stats.get("ab") or 0)
    if pa < 50:
        return 0.0
    return obp + slg


def _score_pitcher(stats: Dict[str, Any]) -> float:
    era = float(stats.get("era") or 99.0)
    ip = float(stats.get("ip") or 0)
    k = int(stats.get("k") or stats.get("so") or 0)
    if ip < 20:
        return 0.0
    # Lower ERA wins; bonus for IP and strikeouts.
    return (5.0 - min(era, 5.0)) + (ip / 50.0) + (k / 100.0)


def select_all_star_rosters(
    *,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute squads + their rosters from current season-stats data."""

    resolved = data_dir or get_data_dir()
    teams = load_teams(resolved / "teams.csv")
    squads = _squad_split(teams)
    if not squads:
        return {"squads": {}, "reason": "no_teams"}

    player_team = _player_team(resolved / "rosters")
    players = list(load_players_from_csv(resolved / "players.csv"))
    players_by_id = {getattr(p, "player_id", ""): p for p in players}
    stats = load_stats(resolved / "season_stats.json")
    player_stats: Dict[str, Dict[str, Any]] = stats.get("players", {}) or {}

    squad_rosters: Dict[str, Dict[str, Any]] = {}
    for squad_name, team_ids in squads.items():
        team_set = set(team_ids)
        # Pool of squad-eligible players.
        eligible = [
            (pid, players_by_id[pid])
            for pid, team_id in player_team.items()
            if team_id in team_set and pid in players_by_id
        ]
        # One slot per hitter position — best by OPS.
        hitters: List[Dict[str, Any]] = []
        used: set[str] = set()
        for slot in _HITTER_SLOTS:
            best: tuple[float, str, Any] | None = None
            for pid, player in eligible:
                if pid in used:
                    continue
                if bool(getattr(player, "is_pitcher", False)):
                    continue
                primary = str(getattr(player, "primary_position", "") or "").upper()
                if slot != "DH" and primary != slot:
                    continue
                stat = player_stats.get(pid) or {}
                score = _score_hitter(stat)
                if score <= 0.0:
                    continue
                if best is None or score > best[0]:
                    best = (score, pid, player)
            if best is None:
                continue
            score, pid, player = best
            used.add(pid)
            hitters.append(
                {
                    "player_id": pid,
                    "team_id": player_team.get(pid, ""),
                    "first_name": getattr(player, "first_name", "") or "",
                    "last_name": getattr(player, "last_name", "") or "",
                    "position": slot,
                    "stats": {
                        "avg": player_stats.get(pid, {}).get("avg"),
                        "ops": round(score, 3),
                        "hr": player_stats.get(pid, {}).get("hr"),
                        "rbi": player_stats.get(pid, {}).get("rbi"),
                    },
                }
            )

        # Top N pitchers — best by combined score.
        pitcher_scores: List[tuple[float, str, Any]] = []
        for pid, player in eligible:
            if not bool(getattr(player, "is_pitcher", False)):
                continue
            stat = player_stats.get(pid) or {}
            score = _score_pitcher(stat)
            if score <= 0.0:
                continue
            pitcher_scores.append((score, pid, player))
        pitcher_scores.sort(key=lambda t: t[0], reverse=True)
        pitchers: List[Dict[str, Any]] = []
        for score, pid, player in pitcher_scores[:_PITCHERS_PER_SQUAD]:
            pitchers.append(
                {
                    "player_id": pid,
                    "team_id": player_team.get(pid, ""),
                    "first_name": getattr(player, "first_name", "") or "",
                    "last_name": getattr(player, "last_name", "") or "",
                    "position": "P",
                    "stats": {
                        "era": player_stats.get(pid, {}).get("era"),
                        "ip": player_stats.get(pid, {}).get("ip"),
                        "k": player_stats.get(pid, {}).get("k")
                        or player_stats.get(pid, {}).get("so"),
                    },
                }
            )

        squad_rosters[squad_name] = {
            "team_ids": team_ids,
            "hitters": hitters,
            "pitchers": pitchers,
        }
    return {"squads": squad_rosters}


# ---------------------------------------------------------------------------
# Flavor game sim


def _squad_strength(roster: Dict[str, Any]) -> float:
    """Sum of selection scores — drives the score margin."""

    score = 0.0
    for h in roster.get("hitters", []) or []:
        ops = float(h.get("stats", {}).get("ops") or 0.0)
        score += ops * 10.0
    for p in roster.get("pitchers", []) or []:
        era = p.get("stats", {}).get("era")
        try:
            era_v = float(era) if era is not None else 4.5
        except (TypeError, ValueError):
            era_v = 4.5
        score += max(0.0, 5.0 - era_v) * 1.2
    return score


def _generate_score(
    strength_a: float,
    strength_b: float,
    *,
    rng: random.Random,
) -> tuple[int, int]:
    """Random but stronger-side-favored score."""

    base = 4
    a_runs = max(0, int(round(rng.gauss(base + (strength_a - strength_b) * 0.1, 1.5))))
    b_runs = max(0, int(round(rng.gauss(base + (strength_b - strength_a) * 0.1, 1.5))))
    if a_runs == b_runs:
        # No ties at the All-Star game.
        if rng.random() < 0.5:
            a_runs += 1
        else:
            b_runs += 1
    return a_runs, b_runs


def _pick_mvp(
    winning_roster: Dict[str, Any],
    *,
    rng: random.Random,
) -> Optional[Dict[str, Any]]:
    """Pick the game's MVP from the winning squad with a flavor stat line."""

    pool = list(winning_roster.get("hitters", []) or []) + list(
        winning_roster.get("pitchers", []) or []
    )
    if not pool:
        return None
    weights = []
    for entry in pool:
        if entry.get("position") == "P":
            weight = 1.0
        else:
            ops = float(entry.get("stats", {}).get("ops") or 0.5)
            weight = max(0.5, ops * 2.0)
        weights.append(weight)
    pick = rng.choices(pool, weights=weights, k=1)[0]

    # Generate a flavor stat line.
    if pick.get("position") == "P":
        ip = round(rng.uniform(2.0, 4.0), 1)
        k = rng.randint(2, 6)
        line = f"{ip} IP, {k} K, 0 ER"
    else:
        ab = rng.randint(3, 5)
        h = rng.randint(2, ab)
        hr = rng.choices([0, 1, 2], weights=[3, 4, 1])[0]
        rbi = rng.randint(hr, hr + 3)
        line = f"{h}-for-{ab}"
        if hr:
            line += f", {hr} HR"
        if rbi:
            line += f", {rbi} RBI"
    return {
        "player_id": pick.get("player_id"),
        "team_id": pick.get("team_id"),
        "name": f"{pick.get('first_name', '')} {pick.get('last_name', '')}".strip()
        or pick.get("player_id"),
        "position": pick.get("position"),
        "line": line,
    }


# ---------------------------------------------------------------------------
# Public entry point


def play_all_star_game(
    *,
    year: int,
    data_dir: Optional[Path] = None,
    seed: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run the All-Star Game for the given year. Idempotent.

    Returns the persisted record. ``force=True`` re-rolls if a game
    already exists for this year.
    """

    resolved = data_dir or get_data_dir()
    history = load_all_star_history(resolved)
    if not force and str(year) in history:
        return history[str(year)]

    selection = select_all_star_rosters(data_dir=resolved)
    squads = selection.get("squads") or {}
    if len(squads) < 2:
        # Not enough teams to fill two squads.
        return {
            "year": year,
            "skipped": True,
            "reason": squads and "single_squad" or "no_teams",
        }

    rng = random.Random(seed if seed is not None else year * 31)
    squad_names = list(squads.keys())
    home_name, away_name = squad_names[0], squad_names[1]
    home_strength = _squad_strength(squads[home_name])
    away_strength = _squad_strength(squads[away_name])
    home_runs, away_runs = _generate_score(home_strength, away_strength, rng=rng)
    winner = home_name if home_runs > away_runs else away_name
    mvp = _pick_mvp(squads[winner], rng=rng)

    record = {
        "year": year,
        "played_at": datetime.utcnow().isoformat() + "Z",
        "home_squad": home_name,
        "away_squad": away_name,
        "home_runs": home_runs,
        "away_runs": away_runs,
        "winner": winner,
        "mvp": mvp,
        "squads": squads,
    }
    history[str(year)] = record
    save_all_star_history(history, data_dir=resolved)

    # Surface to the news feed so owners see it.
    try:
        from utils.news_logger import log_news_event

        news_path = resolved / "news_feed.txt"
        log_news_event(
            f"{year} All-Star Game: {away_name} {away_runs}, {home_name} {home_runs}. "
            f"MVP: {mvp.get('name')} ({mvp.get('line')}).",
            category="all_star",
            file_path=news_path,
        )
    except Exception:
        pass

    return record


__all__ = [
    "load_all_star_history",
    "load_all_star_year",
    "play_all_star_game",
    "select_all_star_rosters",
]
