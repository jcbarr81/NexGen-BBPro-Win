"""Postseason stat totals: per player, per club and leaders (8.4.0).

Since 8.1.1 a playoff game adds into ``postseason_stats.json`` (the same
structure and keys as ``season_stats.json``), never into the regular season.
At the rollover the file is archived as
``careers/<season_id>/postseason_stats.json`` next to that season's bracket
(``playoffs_<year>.json``) and emptied. This module reads them back:

* ``list_postseasons`` -- the postseasons there are totals for: every
  archived season with a postseason file, plus the current season once a
  playoff game has been played;
* ``load_postseason`` -- one postseason: its player and club lines, the
  bracket, and the club each player played for in it;
* ``player_postseason_lines`` -- one player's line per postseason plus a
  career postseason total (counting stats summed, rates recomputed with the
  engine's own formulas, as the game writer derives them);
* ``club_postseasons`` -- one club's runs: W-L, runs for and against, how
  far it went (from the bracket's own round names), its series and its top
  hitters and pitchers;
* ``leader_inputs`` -- the pool the leaders endpoint ranks, with
  postseason-sized minimums (below).

The club a player played for in a postseason is the season's club in the
career ledger (``services.season_teams``, stored with each season's line
since 8.2.3); a player traded during the season ("BOS/CHA") is credited to
the last of those clubs that is in the bracket. The current season, not yet
in the ledger, reads the same labels from the league's files.

Postseason minimums: the regular-season leaders qualify a hitter at 3.1
plate appearances and a pitcher at 1.0 inning per team game. A postseason
uses the same rates per game HIS CLUB played in it (a club out after three
games asks 9 PA / 3 IP, a champion that played twelve 37 PA / 12 IP),
rounded, at least 1.

Read only.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from playbalance.season_context import SeasonContext, get_career_data_dir
from playbalance.stats import (
    compute_batting_derived,
    compute_batting_rates,
    compute_fielding_derived,
    compute_fielding_rates,
    compute_pitching_derived,
    compute_pitching_rates,
)
from utils.path_utils import get_data_dir

__all__ = [
    "IP_PER_TEAM_GAME",
    "PA_PER_TEAM_GAME",
    "club_postseasons",
    "leader_inputs",
    "list_postseasons",
    "load_postseason",
    "minimums_for_games",
    "player_postseason_lines",
    "round_title",
    "sum_lines",
]

# The regular-season leaders' qualifiers (api.routers.leaders), applied per
# game the player's club played in the postseason.
PA_PER_TEAM_GAME = 3.1
IP_PER_TEAM_GAME = 1.0

_POSTSEASON_FILE = "postseason_stats.json"
_BRACKET_RE = re.compile(r"^playoffs_(\d{4})\.json$")

# Integer keys the game writer derives rather than counts: recomputed for a
# total, never summed (as scripts/split_postseason_stats.py treats them).
_RECOMPUTED_INTS = frozenset(
    {"tb", "xbh", "svo", "k_minus_bb", "tc", "of_a", "cg", "sho", "qs", "2b", "3b"}
)

_STAGE_TITLES = {
    "WC": "Wild Card Series",
    "DS": "Division Series",
    "CS": "Championship Series",
    "WS": "World Series",
}


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------
_JSON_CACHE: Dict[str, Tuple[Tuple[int, int], Any]] = {}


def _read_json(path: Path) -> Any:
    """Parse ``path`` (None when missing or unreadable), cached on the file's
    mtime and size: the career ledger can be several megabytes and the
    profile reads it on every view."""

    try:
        stat = path.stat()
    except OSError:
        return None
    token = (int(stat.st_mtime_ns), int(stat.st_size))
    key = str(path)
    hit = _JSON_CACHE.get(key)
    if hit is not None and hit[0] == token:
        return hit[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    _JSON_CACHE[key] = (token, payload)
    return payload


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _year_of(season_id: str) -> Optional[int]:
    try:
        return int(str(season_id).rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return None


def _players_csv(path: Path) -> Dict[str, Dict[str, Any]]:
    """``{player_id: {first_name, last_name, birthdate, is_pitcher,
    primary_position}}`` from a players.csv."""

    out: Dict[str, Dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                pid = str(row.get("player_id") or "").strip()
                if not pid:
                    continue
                out[pid] = {
                    "first_name": str(row.get("first_name") or ""),
                    "last_name": str(row.get("last_name") or ""),
                    "birthdate": str(row.get("birthdate") or ""),
                    "is_pitcher": str(row.get("is_pitcher") or "").strip().lower()
                    in {"true", "1", "yes"},
                    "primary_position": str(row.get("primary_position") or ""),
                }
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
# Which postseasons there are
# ---------------------------------------------------------------------------
def _has_players(path: Path) -> bool:
    payload = _read_json(path)
    return isinstance(payload, Mapping) and bool(payload.get("players"))


def _current_bracket_year() -> Optional[int]:
    years: List[int] = []
    try:
        for path in get_data_dir().iterdir():
            match = _BRACKET_RE.match(path.name)
            if match:
                years.append(int(match.group(1)))
    except OSError:
        return None
    return max(years) if years else None


def _sources() -> List[Dict[str, Any]]:
    """Every postseason with totals, oldest first: ``{season_id, year,
    current, dir}`` (``dir`` holds its postseason_stats.json and bracket)."""

    ctx = SeasonContext.load()
    careers = get_career_data_dir()
    found: Dict[str, Dict[str, Any]] = {}
    archived_ids: List[str] = []
    for season in list(ctx.data.get("seasons") or []):
        if isinstance(season, Mapping) and season.get("season_id"):
            archived_ids.append(str(season["season_id"]))
    # Season folders the index does not list (an index rebuilt by hand) still
    # count when they hold postseason totals.
    try:
        for child in careers.iterdir():
            if child.is_dir() and child.name not in archived_ids:
                archived_ids.append(child.name)
    except OSError:
        pass
    current_id = str((ctx.data.get("current") or {}).get("season_id") or "")
    for season_id in archived_ids:
        if season_id == current_id:
            continue
        folder = careers / season_id
        if not _has_players(folder / _POSTSEASON_FILE):
            continue
        year = _year_of(season_id)
        if year is None:
            continue
        found[season_id] = {
            "season_id": season_id, "year": year, "current": False, "dir": folder,
        }
    data_dir = get_data_dir()
    if _has_players(data_dir / _POSTSEASON_FILE):
        current = ctx.data.get("current") or {}
        year = _int(current.get("league_year")) or _year_of(current_id) or _current_bracket_year()
        if year:
            # An archived season of the same year (never expected) yields
            # to the live file.
            for sid in [s for s, v in found.items() if v["year"] == year]:
                found.pop(sid)
            found[current_id or f"current-{year}"] = {
                "season_id": current_id, "year": int(year), "current": True, "dir": data_dir,
            }
    return sorted(found.values(), key=lambda s: (s["year"], s["season_id"]))


def list_postseasons() -> List[Dict[str, Any]]:
    """``[{season_id, year, label, current}]``, newest first."""

    return [
        {
            "season_id": s["season_id"],
            "year": s["year"],
            "label": f"{s['year']:04d}",
            "current": s["current"],
        }
        for s in reversed(_sources())
    ]


def _source_for(season: Any) -> Optional[Dict[str, Any]]:
    sources = _sources()
    if not sources:
        return None
    if season in (None, ""):
        return sources[-1]
    token = str(season).strip()
    for source in sources:
        if token == source["season_id"] or token == str(source["year"]):
            return source
    return None


# ---------------------------------------------------------------------------
# One postseason
# ---------------------------------------------------------------------------
def _bracket(source: Mapping[str, Any]) -> Dict[str, Any]:
    folder: Path = source["dir"]
    for name in (f"playoffs_{source['year']}.json", "playoffs.json"):
        payload = _read_json(folder / name)
        if isinstance(payload, Mapping) and payload.get("rounds"):
            if name == "playoffs.json" and _int(payload.get("year")) not in (0, source["year"]):
                continue
            return dict(payload)
    return {}


def _ledger_seasons() -> Dict[str, Any]:
    payload = _read_json(get_career_data_dir() / "career_players.json")
    players = payload.get("players") if isinstance(payload, Mapping) else None
    return players if isinstance(players, Mapping) else {}


def _club_labels(source: Mapping[str, Any], player_ids: Iterable[str]) -> Dict[str, str]:
    """The season's club label per player ("BOS" or "BOS/CHA")."""

    if source["current"]:
        try:
            from services.season_teams import season_team_labels

            return dict(season_team_labels(get_data_dir()))
        except Exception:
            return {}
    ledger = _ledger_seasons()
    out: Dict[str, str] = {}
    for pid in player_ids:
        entry = ledger.get(pid)
        seasons = entry.get("seasons") if isinstance(entry, Mapping) else None
        line = seasons.get(source["season_id"]) if isinstance(seasons, Mapping) else None
        team = line.get("team") if isinstance(line, Mapping) else None
        if team:
            out[pid] = str(team)
    return out


def _postseason_club(label: str, participants: set) -> str:
    """The club a season label credits with his postseason: the last of its
    clubs that played in the bracket, else the last one."""

    clubs = [c.strip().upper() for c in str(label or "").split("/") if c.strip()]
    if not clubs:
        return ""
    for club in reversed(clubs):
        if club in participants:
            return club
    return clubs[-1]


def _bracket_participants(bracket: Mapping[str, Any]) -> set:
    teams = set()
    for rnd in bracket.get("rounds") or []:
        for matchup in (rnd or {}).get("matchups") or []:
            for side in ("high", "low"):
                tid = str(((matchup or {}).get(side) or {}).get("team_id") or "")
                if tid:
                    teams.add(tid.upper())
    return teams


def load_postseason(season: Any = None) -> Optional[Dict[str, Any]]:
    """One postseason (``season`` = year or season id; None = the latest):
    ``{season_id, year, label, current, players, teams, bracket, clubs,
    people}``. ``clubs`` maps player -> the club he played for in it,
    ``people`` player -> name/birthdate/is_pitcher."""

    source = _source_for(season)
    return _load(source) if source is not None else None


def _load(source: Mapping[str, Any]) -> Dict[str, Any]:
    payload = _read_json(source["dir"] / _POSTSEASON_FILE) or {}
    players = payload.get("players") if isinstance(payload, Mapping) else None
    teams = payload.get("teams") if isinstance(payload, Mapping) else None
    players = {str(k): dict(v) for k, v in (players or {}).items() if isinstance(v, Mapping)}
    teams = {str(k).upper(): dict(v) for k, v in (teams or {}).items() if isinstance(v, Mapping)}
    bracket = _bracket(source)
    participants = _bracket_participants(bracket) | set(teams)
    labels = _club_labels(source, players.keys())
    clubs = {
        pid: club
        for pid in players
        if (club := _postseason_club(labels.get(pid, ""), participants))
    }
    people = _players_csv(source["dir"] / "players.csv") if not source["current"] else {}
    current_people = _players_csv(get_data_dir() / "players.csv")
    for pid, info in current_people.items():
        people.setdefault(pid, info)
    return {
        "season_id": source["season_id"],
        "year": source["year"],
        "label": f"{source['year']:04d}",
        "current": source["current"],
        "players": players,
        "teams": teams,
        "bracket": bracket,
        "clubs": clubs,
        "people": people,
    }


# ---------------------------------------------------------------------------
# Summing lines
# ---------------------------------------------------------------------------
def _batting_rates(s: Mapping[str, Any]) -> Dict[str, Any]:
    st = SimpleNamespace(**{k: _int(s.get(k)) for k in (
        "b1", "b2", "b3", "hr", "lob", "pitches", "pa", "ab", "h", "bb", "hbp",
        "sf", "so", "so_looking", "sb", "cs", "gb", "ld", "fb")})
    out = dict(compute_batting_derived(st))
    out.update(compute_batting_rates(st))
    out["2b"] = _int(s.get("b2"))
    out["3b"] = _int(s.get("b3"))
    return out


def _pitching_rates(s: Mapping[str, Any]) -> Dict[str, Any]:
    keys = ("outs", "gs", "gf", "r", "er", "so", "bb", "hbp", "hr", "h", "gb", "ld",
            "fb", "pitches_thrown", "bf", "first_pitch_strikes", "zone_pitches",
            "o_zone_pitches", "zone_swings", "o_zone_swings", "zone_contacts",
            "o_zone_contacts", "so_looking")
    st = SimpleNamespace(**{k: _int(s.get(k)) for k in keys})
    out: Dict[str, Any] = {"svo": _int(s.get("sv")) + _int(s.get("bs"))}
    out.update(compute_pitching_derived(st))
    out.update(compute_pitching_rates(st))
    return out


def _fielding_rates(s: Mapping[str, Any], position: str) -> Dict[str, Any]:
    st = SimpleNamespace(
        player=SimpleNamespace(primary_position=position or ""),
        g=_int(s.get("g")), po=_int(s.get("f_po")), a=_int(s.get("a")),
        e=_int(s.get("e")), dp=_int(s.get("dp")), tp=_int(s.get("tp")),
        pk=_int(s.get("f_pk")), pb=_int(s.get("pb")), ci=_int(s.get("f_ci")),
        cs=_int(s.get("f_cs")), sba=_int(s.get("sba")),
    )
    out = dict(compute_fielding_derived(st))
    out.update(compute_fielding_rates(st))
    return out


def sum_lines(lines: Iterable[Mapping[str, Any]], *, position: str = "") -> Dict[str, Any]:
    """Total of several cumulative lines: counting stats summed, every derived
    stat recomputed from the totals in the game writer's order (batting,
    pitching, fielding; later blocks win the shared keys), and only for the
    blocks the player had a line in (a rate a block never wrote is not
    invented)."""

    totals: Dict[str, Any] = {}
    keys: set = set()
    for line in lines:
        if not isinstance(line, Mapping):
            continue
        keys.update(line.keys())
        for key, value in line.items():
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if key in _RECOMPUTED_INTS:
                continue
            totals[key] = totals.get(key, 0) + value
    derived: Dict[str, Any] = {}
    if "avg" in keys or "ops" in keys:
        derived.update(_batting_rates(totals))
    if "era" in keys or "outs" in keys:
        derived.update(_pitching_rates(totals))
    if "fpct" in keys:
        derived.update(_fielding_rates(totals, position))
    for key, value in derived.items():
        if key in keys:
            totals[key] = value
    return totals


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
def _age(birthdate: str, year: Optional[int]) -> Optional[int]:
    """Age as the player profile shows a past season's: on July 1 of it."""

    text = str(birthdate or "").strip()[:10]
    if not text or year is None:
        return None
    try:
        from playbalance.aging import calculate_age

        return max(int(calculate_age(text, as_of=date(int(year), 7, 1))), 0)
    except Exception:
        return None


def _played(line: Mapping[str, Any]) -> bool:
    return any(_float(line.get(k)) > 0 for k in ("g", "pa", "ab", "bf", "outs"))


def player_postseason_lines(
    player_id: str, *, birthdate: str = ""
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """``(lines, career)``: one entry per postseason he played in, oldest
    first (``{season_id, year, label, current, team, age, stats}``), and his
    career postseason total (``{}`` when he never played one)."""

    pid = str(player_id or "")
    lines: List[Dict[str, Any]] = []
    position = ""
    for source in _sources():
        season = _load(source)
        stats = season["players"].get(pid)
        if not stats or not _played(stats):
            continue
        person = season["people"].get(pid) or {}
        position = position or str(person.get("primary_position") or "")
        lines.append(
            {
                "season_id": season["season_id"],
                "year": season["year"],
                "label": season["label"],
                "current": season["current"],
                "team": season["clubs"].get(pid, ""),
                "age": _age(birthdate or str(person.get("birthdate") or ""), season["year"]),
                "stats": dict(stats),
            }
        )
    if not lines:
        return [], {}
    career = sum_lines((entry["stats"] for entry in lines), position=position)
    return lines, career


# ---------------------------------------------------------------------------
# Clubs
# ---------------------------------------------------------------------------
def round_title(name: str) -> str:
    """A bracket round's name spelled out: "AL DS" -> "AL Division Series",
    "WS" -> "World Series". The generic single-league prefix "LEAGUE" is
    dropped; a name the bracket spells out itself is kept as it is."""

    text = str(name or "").strip()
    parts = text.split()
    if not parts:
        return text
    stage = parts[-1].upper()
    if stage not in _STAGE_TITLES:
        return text
    league = " ".join(parts[:-1]).strip()
    if league.upper() == "LEAGUE":
        league = ""
    return f"{league} {_STAGE_TITLES[stage]}".strip()


def _series_wins(matchup: Mapping[str, Any], team: str) -> Tuple[int, int]:
    wins = losses = 0
    for game in matchup.get("games") or []:
        result = str((game or {}).get("result") or "")
        if "-" not in result:
            continue
        try:
            home_runs, away_runs = (int(x.strip()) for x in result.split("-", 1))
        except ValueError:
            continue
        if home_runs == away_runs:
            continue
        winner = game.get("home") if home_runs > away_runs else game.get("away")
        if str(winner or "").upper() == team:
            wins += 1
        elif str(game.get("home") or "").upper() == team or str(game.get("away") or "").upper() == team:
            losses += 1
    return wins, losses


def _club_series(bracket: Mapping[str, Any], team: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """The club's series in bracket order and its seed. The single-league
    bracket repeats its final round as "Final" for display; a round whose
    series is the one just listed is skipped."""

    series: List[Dict[str, Any]] = []
    seed: Optional[int] = None
    last_key: Optional[Tuple[str, str, int]] = None
    for rnd in bracket.get("rounds") or []:
        name = str((rnd or {}).get("name") or "")
        for matchup in (rnd or {}).get("matchups") or []:
            high = (matchup or {}).get("high") or {}
            low = (matchup or {}).get("low") or {}
            ids = (str(high.get("team_id") or "").upper(), str(low.get("team_id") or "").upper())
            if team not in ids:
                continue
            key = (ids[0], ids[1], len(matchup.get("games") or []))
            if key == last_key:
                continue
            last_key = key
            mine, theirs = (high, low) if ids[0] == team else (low, high)
            if seed is None and mine.get("seed") not in (None, ""):
                seed = _int(mine.get("seed")) or None
            wins, losses = _series_wins(matchup, team)
            winner = str(matchup.get("winner") or "").upper()
            outcome = "won" if winner == team else ("lost" if winner else "playing")
            series.append(
                {
                    "round": name,
                    "round_title": round_title(name),
                    "opponent": str(theirs.get("team_id") or ""),
                    "wins": wins,
                    "losses": losses,
                    "outcome": outcome,
                }
            )
    return series, seed


def _how_far(series: List[Dict[str, Any]], champion: bool) -> str:
    """"Won World Series", "Lost AL Division Series", "Playing ..."."""

    if not series:
        return "Champion" if champion else ""
    last = series[-1]
    title = last["round_title"] or last["round"]
    if champion:
        return f"Won {title}"
    if last["outcome"] == "lost":
        return f"Lost {title}"
    if last["outcome"] == "playing":
        return f"Playing {title}"
    return f"Won {title}"


def minimums_for_games(games: int) -> Tuple[int, int]:
    """``(min PA, min IP)`` for a club that played ``games`` postseason games."""

    g = max(int(games or 0), 0)
    if not g:
        return 1, 1
    return (
        max(1, int(round(g * PA_PER_TEAM_GAME))),
        max(1, int(round(g * IP_PER_TEAM_GAME))),
    )


def _ip(line: Mapping[str, Any]) -> float:
    if line.get("ip") not in (None, ""):
        return _float(line.get("ip"))
    return _int(line.get("outs")) / 3.0


def _pa(line: Mapping[str, Any]) -> int:
    pa = _int(line.get("pa"))
    if pa:
        return pa
    return sum(_int(line.get(k)) for k in ("ab", "bb", "hbp", "sf", "sh"))


_HITTER_KEYS = ("g", "pa", "ab", "r", "h", "2b", "3b", "hr", "rbi", "bb", "so", "sb",
                "avg", "obp", "slg", "ops")
_PITCHER_KEYS = ("g", "gs", "w", "l", "sv", "ip", "h", "er", "bb", "so", "era", "whip")


def _person(season: Mapping[str, Any], pid: str) -> Dict[str, Any]:
    info = season["people"].get(pid) or {}
    return {
        "player_id": pid,
        "first_name": info.get("first_name", ""),
        "last_name": info.get("last_name", ""),
    }


def _is_pitcher(season: Mapping[str, Any], pid: str, line: Mapping[str, Any]) -> bool:
    info = season["people"].get(pid)
    if info is not None:
        return bool(info.get("is_pitcher"))
    return "era" in line and "avg" not in line


def _top_players(
    season: Mapping[str, Any], team: str, games: int, limit: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The club's best hitters (by OPS) and pitchers (by ERA) in the run.
    Those who reached the postseason minimum come first; when fewer than
    ``limit`` did, the rest follow by plate appearances / innings."""

    min_pa, min_ip = minimums_for_games(games)
    hitters: List[Tuple[Tuple, str, Mapping[str, Any]]] = []
    pitchers: List[Tuple[Tuple, str, Mapping[str, Any]]] = []
    for pid, line in season["players"].items():
        if season["clubs"].get(pid) != team:
            continue
        if _is_pitcher(season, pid, line):
            ip = _ip(line)
            if ip <= 0:
                continue
            if ip >= min_ip:
                key = (0, _float(line.get("era")), -ip)
            else:
                key = (1, -ip, _float(line.get("era")))
            pitchers.append((key, pid, line))
        else:
            pa = _pa(line)
            if pa <= 0:
                continue
            if pa >= min_pa:
                key = (0, -_float(line.get("ops")), -pa)
            else:
                key = (1, -pa, -_float(line.get("ops")))
            hitters.append((key, pid, line))

    def rows(items, keys):
        items.sort(key=lambda item: (item[0], item[1]))
        return [
            {**_person(season, pid), "qualified": key[0] == 0,
             **{k: line.get(k) for k in keys if line.get(k) is not None}}
            for key, pid, line in items[:limit]
        ]

    return rows(hitters, _HITTER_KEYS), rows(pitchers, _PITCHER_KEYS)


def _club_entry(season: Mapping[str, Any], team: str, *, top: int) -> Optional[Dict[str, Any]]:
    bracket = season["bracket"]
    series, seed = _club_series(bracket, team)
    line = season["teams"].get(team) or {}
    if not series and not line:
        return None
    champion = str(bracket.get("champion") or "").upper() == team
    wins = _int(line.get("w")) if line else sum(s["wins"] for s in series)
    losses = _int(line.get("l")) if line else sum(s["losses"] for s in series)
    games = _int(line.get("g")) or (wins + losses)
    runs = _int(line.get("r"))
    allowed = _int(line.get("ra"))
    hitters, pitchers = _top_players(season, team, games, top)
    return {
        "season_id": season["season_id"],
        "year": season["year"],
        "label": season["label"],
        "current": season["current"],
        "team_id": team,
        "seed": seed,
        "g": games,
        "w": wins,
        "l": losses,
        "r": runs,
        "ra": allowed,
        "champion": champion,
        "result": _how_far(series, champion),
        "series": series,
        "top_hitters": hitters,
        "top_pitchers": pitchers,
    }


def club_postseasons(team_id: str, *, top: int = 3) -> List[Dict[str, Any]]:
    """The club's postseason runs, newest first (empty when it has none)."""

    team = str(team_id or "").strip().upper()
    out: List[Dict[str, Any]] = []
    if not team:
        return out
    for source in reversed(_sources()):
        entry = _club_entry(_load(source), team, top=top)
        if entry is not None:
            out.append(entry)
    return out



# ---------------------------------------------------------------------------
# Leaders
# ---------------------------------------------------------------------------
def leader_inputs(season: Any = None) -> Optional[Dict[str, Any]]:
    """What the leaders endpoint ranks for one postseason: ``{season_id,
    year, label, players, team_index, minimums, max_team_games}``.
    ``players`` are objects with ``player_id``, names, ``is_pitcher`` and
    ``season_stats`` (his postseason line); ``minimums`` maps player ->
    ``(min PA, min IP)`` from his club's postseason games (the most games
    any club played when his club is unknown)."""

    data = load_postseason(season)
    if data is None:
        return None
    games = {tid: _int(line.get("g")) for tid, line in data["teams"].items()}
    max_g = max(games.values()) if games else 0
    players: List[Any] = []
    minimums: Dict[str, Tuple[int, int]] = {}
    for pid, line in data["players"].items():
        info = data["people"].get(pid) or {}
        players.append(
            SimpleNamespace(
                player_id=pid,
                first_name=info.get("first_name", ""),
                last_name=info.get("last_name", ""),
                is_pitcher=_is_pitcher(data, pid, line),
                season_stats=line,
            )
        )
        club = data["clubs"].get(pid, "")
        minimums[pid] = minimums_for_games(games.get(club) or max_g)
    return {
        "season_id": data["season_id"],
        "year": data["year"],
        "label": data["label"],
        "current": data["current"],
        "players": players,
        "team_index": dict(data["clubs"]),
        "minimums": minimums,
        "max_team_games": max_g,
    }
