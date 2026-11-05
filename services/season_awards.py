"""Season awards: MVP, Cy Young, Gold Gloves and Silver Sluggers.

Chosen at the season rollover from the season's stats and written to
``careers/<season_id>/awards.json``. A league split into two named leagues
(``division_to_league`` in the playoff config, alpha-test's Mercado and
Grandberg) gives one of each award per league, as MLB does for the AL and
NL; a league that isn't split gives one set.

* **MVP**: the best OPS among qualified hitters (3.1 plate appearances per
  team game); **Cy Young**: the best ERA among qualified pitchers (an
  inning per team game). Unchanged from before, only per league now.
* **Gold Glove**, one per position (P, C, 1B, 2B, 3B, SS, LF, CF, RF): a
  blend of the player's fielding ratings (70%: fielding, plus arm where the
  position throws, measured on a healthy league's spread so a league whose
  ratings are bunched lets the stats decide) and his season's fielding
  numbers (30%, against the other qualifiers at the position: fielding pct;
  range factor except for catchers and pitchers; passed balls for a
  catcher; assists for an outfielder). A fielder qualifies with games in
  half his club's games, a pitcher with an inning per team game.
* **Silver Slugger**: the best OPS at each position (C, 1B, 2B, 3B, SS,
  three outfielders as MLB gives, and DH), with 2 plate appearances per
  team game.

A player is judged at the position he started at most (the season stats
count games started by position from 8.12.0; an earlier season falls back
to his primary position), and his league is the league of his club at the
season's end. Each award entry is keyed uniquely (``"GOLD_GLOVE:Mercado:SS"``) and
carries its ``award`` type, ``league``, ``position``, display ``label`` and
``metric_label``; seasons archived before this (one league-wide ``MVP`` and
``CY_YOUNG``) are read through :func:`award_type` / :func:`award_label`.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "AWARD_KINDS",
    "news_text",
    "award_key",
    "award_label",
    "award_type",
    "backfill_archived_seasons",
    "metric_text",
    "select_awards",
    "sort_key",
    "team_leagues",
    "winners_text",
]

_LOGGER = logging.getLogger(__name__)

AWARD_KINDS: Tuple[str, ...] = ("MVP", "CY_YOUNG", "GOLD_GLOVE", "SILVER_SLUGGER")
AWARD_NAMES = {
    "MVP": "MVP",
    "CY_YOUNG": "Cy Young",
    "GOLD_GLOVE": "Gold Glove",
    "SILVER_SLUGGER": "Silver Slugger",
}
GOLD_GLOVE_POSITIONS: Tuple[str, ...] = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
SILVER_SLUGGER_SLOTS: Tuple[Tuple[str, int], ...] = (
    ("C", 1), ("1B", 1), ("2B", 1), ("3B", 1), ("SS", 1), ("OF", 3), ("DH", 1),
)
_POSITION_ORDER = {p: i for i, p in enumerate(GOLD_GLOVE_POSITIONS + ("OF", "DH"))}
OUTFIELD = frozenset({"LF", "CF", "RF"})

# Fielding rating weights (fa, arm) by position: the engine's fielding reads
# fa at the position, and the arm makes the throws.
GOLD_GLOVE_RATING_WEIGHTS: Dict[str, Tuple[float, float]] = {
    "P": (1.0, 0.0),
    "C": (0.5, 0.5),
    "1B": (1.0, 0.0),
    "2B": (0.8, 0.2),
    "3B": (0.65, 0.35),
    "SS": (0.7, 0.3),
    "LF": (0.8, 0.2),
    "CF": (0.8, 0.2),
    "RF": (0.65, 0.35),
}
GOLD_GLOVE_RATING_SHARE = 0.7
# A fielding rating's spread at a position in a healthy league (engine
# points; the calibration league's is 6-9 by position).
GOLD_GLOVE_RATING_SPREAD = 8.0
GOLD_GLOVE_MIN_GAMES_SHARE = 0.5
MVP_MIN_PA_PER_GAME = 3.1
CY_MIN_IP_PER_GAME = 1.0
SILVER_SLUGGER_MIN_PA_PER_GAME = 2.0


# --- reading award entries ------------------------------------------------------


def award_key(
    award: str,
    league: Optional[str] = None,
    position: Optional[str] = None,
    slot: Optional[int] = None,
) -> str:
    parts = [award]
    if league:
        parts.append(str(league))
    if position:
        parts.append(str(position))
    if slot:
        parts.append(str(slot))
    return ":".join(parts)


def award_type(key: str, info: Optional[Mapping[str, Any]] = None) -> str:
    """The award an entry is (``MVP``, ``GOLD_GLOVE`` ...)."""

    if isinstance(info, Mapping) and info.get("award"):
        return str(info["award"])
    return str(key or "").split(":", 1)[0].strip().upper()


def award_label(key: str, info: Optional[Mapping[str, Any]] = None) -> str:
    """How an award reads: ``MVP``, ``Mercado MVP``, ``Gold Glove, SS (Mercado)``."""

    if isinstance(info, Mapping) and info.get("label"):
        return str(info["label"])
    kind = award_type(key, info)
    name = AWARD_NAMES.get(kind) or kind.replace("_", " ").title() or "Award"
    league = str((info or {}).get("league") or "") if isinstance(info, Mapping) else ""
    position = str((info or {}).get("position") or "") if isinstance(info, Mapping) else ""
    return _label(name, league, position)


def _label(name: str, league: str, position: str) -> str:
    text = f"{name}, {position}" if position else name
    return f"{text} ({league})" if league else text


def metric_text(key: str, info: Mapping[str, Any]) -> str:
    """The winner's line for display (``1.064 OPS``, ``3.51 ERA``)."""

    if info.get("metric_label"):
        return str(info["metric_label"])
    metric = info.get("metric")
    try:
        value = float(metric)
    except (TypeError, ValueError):
        return str(metric or "")
    kind = award_type(key, info)
    if kind == "MVP":
        return f"{_ops_text(value)} OPS"
    if kind == "CY_YOUNG":
        return f"{value:.2f} ERA"
    return f"{value:.3f}"


def sort_key(key: str, info: Mapping[str, Any]) -> Tuple[int, str, int, str]:
    kind = award_type(key, info)
    order = AWARD_KINDS.index(kind) if kind in AWARD_KINDS else len(AWARD_KINDS)
    league = str(info.get("league") or "")
    position = str(info.get("position") or "")
    return (order, league, _POSITION_ORDER.get(position, 99), key)


def winners_text(awards: Mapping[str, Any], kind: str) -> str:
    """Every winner of ``kind`` in a season's awards: ``Leroy Harris`` or
    ``A (Mercado), B (Grandberg)``; ``-`` when there is none."""

    names: List[str] = []
    for key, info in sorted(
        ((k, v) for k, v in awards.items() if isinstance(v, Mapping)),
        key=lambda kv: sort_key(kv[0], kv[1]),
    ):
        if award_type(key, info) != kind:
            continue
        name = str(info.get("player_name") or info.get("player_id") or "").strip()
        if not name:
            continue
        league = str(info.get("league") or "")
        names.append(f"{name} ({league})" if league else name)
    return ", ".join(names) or "-"


def news_text(awards: Mapping[str, Any], league_year: Any = None) -> str:
    """One news line for a season's awards: the MVP and Cy Young of each
    league, and where to find the rest."""

    year = f"{league_year} " if league_year else ""
    entries = [(k, v) for k, v in awards.items() if isinstance(v, Mapping)]
    leagues = sorted({str(v.get("league") or "") for _k, v in entries})
    parts: List[str] = []
    for league in leagues:
        bits: List[str] = []
        for kind in ("MVP", "CY_YOUNG"):
            for key, info in entries:
                if award_type(key, info) == kind and str(info.get("league") or "") == league:
                    team = str(info.get("team_id") or "")
                    who = str(info.get("player_name") or info.get("player_id") or "")
                    bits.append(f"{AWARD_NAMES[kind]} {who}" + (f" ({team})" if team else ""))
        if bits:
            parts.append((f"{league}: " if league else "") + ", ".join(bits))
    text = f"{year}season awards: " + ("; ".join(parts) if parts else "announced") + "."
    if any(award_type(k, v) in ("GOLD_GLOVE", "SILVER_SLUGGER") for k, v in entries):
        text += " The Gold Gloves and Silver Sluggers are on the Awards page (League > Awards)."
    return text


# --- choosing winners -------------------------------------------------------------


def team_leagues(teams: Iterable[Any], division_to_league: Mapping[str, str]) -> Dict[str, str]:
    """``{team_id: league}`` when the league is split into two or more named
    leagues, else ``{}`` (one set of awards)."""

    mapping = {str(k): str(v) for k, v in (division_to_league or {}).items() if v}
    if len(set(mapping.values())) < 2:
        return {}
    out: Dict[str, str] = {}
    for team in teams:
        tid = str(getattr(team, "team_id", "") or "").strip().upper()
        league = mapping.get(str(getattr(team, "division", "") or ""))
        if tid and league:
            out[tid] = league
    return out


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _name(player: Any) -> str:
    first = str(getattr(player, "first_name", "") or "").strip()
    last = str(getattr(player, "last_name", "") or "").strip()
    return f"{first} {last}".strip() or str(getattr(player, "player_id", ""))


def _position(player: Any, line: Optional[Mapping[str, Any]] = None) -> str:
    """The position a player is judged at: ``P`` for a pitcher, else the
    one he started at most (``gs_<pos>``, counted from 8.12.0), else his
    primary position."""

    if bool(getattr(player, "is_pitcher", False)):
        return "P"
    starts = _starts(line)
    if starts:
        return max(starts, key=lambda pos: (starts[pos], pos))
    return str(getattr(player, "primary_position", "") or "").strip().upper()


def _starts(line: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    if not isinstance(line, Mapping):
        return {}
    out: Dict[str, float] = {}
    for key, value in line.items():
        if isinstance(key, str) and key.startswith("gs_") and len(key) > 3:
            games = _f(value)
            if games > 0:
                out[key[3:].upper()] = games
    return out


def _games_at(line: Mapping[str, Any], position: str) -> float:
    """Games a fielder played at ``position``: his starts there when they
    are counted, else all his games."""

    starts = _starts(line)
    if starts:
        return starts.get(position, 0.0)
    return _f(line.get("g"))


def _pa(stats: Mapping[str, Any]) -> float:
    if stats.get("pa") is not None:
        return _f(stats.get("pa"))
    return sum(_f(stats.get(k)) for k in ("ab", "bb", "hbp", "sf", "ci"))


def _ip(stats: Mapping[str, Any]) -> float:
    if stats.get("ip") is not None:
        return _f(stats.get("ip"))
    return _f(stats.get("outs")) / 3.0


def _ops(stats: Mapping[str, Any]) -> float:
    if stats.get("ops") is not None:
        return _f(stats.get("ops"))
    ab, h = _f(stats.get("ab")), _f(stats.get("h"))
    bb, hbp, sf = _f(stats.get("bb")), _f(stats.get("hbp")), _f(stats.get("sf"))
    b2 = _f(stats.get("b2", stats.get("2b")))
    b3 = _f(stats.get("b3", stats.get("3b")))
    hr = _f(stats.get("hr"))
    tb = (h - b2 - b3 - hr) + 2 * b2 + 3 * b3 + 4 * hr
    obp_den = ab + bb + hbp + sf
    obp = (h + bb + hbp) / obp_den if obp_den else 0.0
    return obp + (tb / ab if ab else 0.0)


def _era(stats: Mapping[str, Any]) -> float:
    if stats.get("era") is not None:
        return _f(stats.get("era"), float("inf"))
    ip = _ip(stats)
    return _f(stats.get("er")) * 9.0 / ip if ip > 0 else float("inf")


def _ops_text(ops: float) -> str:
    """OPS as baseball writes it: .949, 1.064."""

    text = f"{ops:.3f}"
    return text[1:] if text.startswith("0.") else text


def _fpct(stats: Mapping[str, Any]) -> Optional[float]:
    if stats.get("fpct") is not None:
        return _f(stats.get("fpct"))
    po, a, e = _f(stats.get("po")), _f(stats.get("a")), _f(stats.get("e"))
    return (po + a) / (po + a + e) if (po + a + e) else None


def _zscores(values: Sequence[Optional[float]]) -> List[float]:
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return [0.0 for _ in values]
    mean = sum(present) / len(present)
    sd = math.sqrt(sum((v - mean) ** 2 for v in present) / len(present))
    if sd <= 0:
        return [0.0 for _ in values]
    return [((v - mean) / sd) if v is not None else 0.0 for v in values]


def _rating(player: Any, key: str) -> float:
    from utils.rating_scale import engine_rating

    return _f(engine_rating(player, key, 50), 50.0)


def _entry(
    kind: str,
    league: Optional[str],
    position: Optional[str],
    player: Any,
    team: str,
    metric: float,
    metric_label: str,
) -> Dict[str, Any]:
    return {
        "award": kind,
        "league": league,
        "position": position,
        "label": _label(AWARD_NAMES[kind], league or "", position or ""),
        "player_id": str(getattr(player, "player_id", "")),
        "player_name": _name(player),
        "team_id": team,
        "metric": metric,
        "metric_label": metric_label,
    }


def select_awards(
    *,
    players: Mapping[str, Any],
    stats: Mapping[str, Mapping[str, Any]],
    team_of: Mapping[str, str],
    team_league: Mapping[str, str],
    max_games: int,
    kinds: Iterable[str] = AWARD_KINDS,
) -> Dict[str, Dict[str, Any]]:
    """The season's awards, keyed by :func:`award_key`.

    ``players`` and ``stats`` are keyed by player id; ``team_of`` is each
    player's club label for the season (``"BOS"``, or ``"BOS/CHA"`` after a
    trade: the last club counts); ``team_league`` comes from
    :func:`team_leagues` (empty for one set of awards); ``max_games`` is the
    most games a club played.
    """

    wanted = set(kinds)
    games = max(0, int(max_games or 0))

    def club(pid: str) -> str:
        label = str(team_of.get(pid) or "").strip()
        return label.split("/")[-1].strip().upper() if label else ""

    pools: Dict[Optional[str], List[str]] = {}
    for pid in sorted(stats):
        if pid not in players or not isinstance(stats.get(pid), Mapping):
            continue
        if team_league:
            league = team_league.get(club(pid))
            if not league:
                continue
            pools.setdefault(league, []).append(pid)
        else:
            pools.setdefault(None, []).append(pid)

    awards: Dict[str, Dict[str, Any]] = {}
    for league in sorted(pools, key=lambda x: x or ""):
        pool = pools[league]
        if "MVP" in wanted:
            _pick_mvp(awards, league, pool, players, stats, club, games)
        if "CY_YOUNG" in wanted:
            _pick_cy_young(awards, league, pool, players, stats, club, games)
        if "GOLD_GLOVE" in wanted:
            for position in GOLD_GLOVE_POSITIONS:
                _pick_gold_glove(awards, league, position, pool, players, stats, club, games)
        if "SILVER_SLUGGER" in wanted:
            for position, count in SILVER_SLUGGER_SLOTS:
                _pick_silver_sluggers(
                    awards, league, position, count, pool, players, stats, club, games
                )
    return awards


def _pick_mvp(awards, league, pool, players, stats, club, games) -> None:
    hitters = [p for p in pool if _pa(stats[p]) > 0]
    qualified = [p for p in hitters if _pa(stats[p]) >= games * MVP_MIN_PA_PER_GAME] or hitters
    if not qualified:
        return
    best = max(qualified, key=lambda p: (_ops(stats[p]), p))
    ops = _ops(stats[best])
    awards[award_key("MVP", league)] = _entry(
        "MVP", league, None, players[best], club(best), ops, f"{_ops_text(ops)} OPS"
    )


def _pick_cy_young(awards, league, pool, players, stats, club, games) -> None:
    arms = [p for p in pool if _ip(stats[p]) > 0]
    qualified = [p for p in arms if _ip(stats[p]) >= games * CY_MIN_IP_PER_GAME] or arms
    if not qualified:
        return
    best = min(qualified, key=lambda p: (_era(stats[p]), p))
    era = _era(stats[best])
    awards[award_key("CY_YOUNG", league)] = _entry(
        "CY_YOUNG", league, None, players[best], club(best), era, f"{era:.2f} ERA"
    )


def _pick_gold_glove(awards, league, position, pool, players, stats, club, games) -> None:
    def qualifies(pid: str) -> bool:
        line = stats[pid]
        if position == "P":
            return _ip(line) >= games * CY_MIN_IP_PER_GAME
        return _games_at(line, position) >= games * GOLD_GLOVE_MIN_GAMES_SHARE

    candidates = [
        p for p in pool if _position(players[p], stats[p]) == position and qualifies(p)
    ]
    if not candidates:
        return
    w_fa, w_arm = GOLD_GLOVE_RATING_WEIGHTS[position]
    ratings = [
        # rating-scale: _rating reads through engine_rating
        w_fa * _rating(players[p], "fa") + w_arm * _rating(players[p], "arm")
        for p in candidates
    ]
    # Fielding pct everywhere; range factor where it measures range (a
    # catcher's putouts are mostly strikeouts, a pitcher's chances few);
    # passed balls for a catcher, assists for an outfielder.
    stat_columns: List[List[Optional[float]]] = [[_fpct(stats[p]) for p in candidates]]
    if position not in ("P", "C"):
        stat_columns.append(
            [_f(stats[p].get("rf9")) if stats[p].get("rf9") is not None else None for p in candidates]
        )
    if position == "C":
        stat_columns.append(
            [-_f(stats[p].get("pb")) / max(1.0, _f(stats[p].get("g"))) for p in candidates]
        )
    if position in OUTFIELD:
        stat_columns.append(
            [_f(stats[p].get("of_a", stats[p].get("a"))) / max(1.0, _f(stats[p].get("g"))) for p in candidates]
        )
    # Ratings against a fixed yardstick, not each other: in a league whose
    # ratings are bunched (alpha-test 2026: fielding 50-52 for nearly all)
    # a one-point gap is noise, and the season's numbers should decide.
    mean_rating = sum(ratings) / len(ratings)
    rating_z = [(r - mean_rating) / GOLD_GLOVE_RATING_SPREAD for r in ratings]
    stat_z = [_zscores(col) for col in stat_columns]
    scores = [
        GOLD_GLOVE_RATING_SHARE * rating_z[i]
        + (1 - GOLD_GLOVE_RATING_SHARE) * (sum(col[i] for col in stat_z) / len(stat_z))
        for i in range(len(candidates))
    ]
    i_best = max(range(len(candidates)), key=lambda i: (scores[i], candidates[i]))
    best = candidates[i_best]
    line = stats[best]
    parts = []
    fpct = _fpct(line)
    if fpct is not None:
        parts.append(f"{fpct:.3f} fielding pct".lstrip("0"))
    if position not in ("P", "C") and line.get("rf9") is not None:
        parts.append(f"{_f(line.get('rf9')):.2f} range factor")
    if position == "C":
        parts.append(f"{int(_f(line.get('pb')))} passed balls")
    if position in OUTFIELD:
        parts.append(f"{int(_f(line.get('of_a', line.get('a'))))} assists")
    awards[award_key("GOLD_GLOVE", league, position)] = _entry(
        "GOLD_GLOVE", league, position, players[best], club(best),
        round(scores[i_best], 3), ", ".join(parts),
    )


def _pick_silver_sluggers(awards, league, position, count, pool, players, stats, club, games) -> None:
    def plays(pid: str) -> bool:
        pos = _position(players[pid], stats[pid])
        return pos in OUTFIELD if position == "OF" else pos == position

    candidates = [
        p for p in pool
        if plays(p) and _pa(stats[p]) >= games * SILVER_SLUGGER_MIN_PA_PER_GAME
    ]
    ranked = sorted(candidates, key=lambda p: (_ops(stats[p]), p), reverse=True)[:count]
    for slot, pid in enumerate(ranked, start=1):
        ops = _ops(stats[pid])
        hr = int(_f(stats[pid].get("hr")))
        key = award_key("SILVER_SLUGGER", league, position, slot if count > 1 else None)
        awards[key] = _entry(
            "SILVER_SLUGGER", league, position, players[pid], club(pid),
            ops, f"{_ops_text(ops)} OPS, {hr} HR",
        )


# --- archived seasons -----------------------------------------------------------


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_awards_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".awards-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def max_team_games(team_stats: Mapping[str, Any]) -> int:
    games = [
        int(_f((v or {}).get("g", (v or {}).get("games", 0))))
        for v in (team_stats or {}).values()
        if isinstance(v, Mapping)
    ]
    return max(games) if games else 0


def current_team_leagues(data_dir: Path) -> Dict[str, str]:
    """:func:`team_leagues` from the league's teams.csv and playoff config."""

    from playbalance.playoffs_config import load_playoffs_config
    from utils.team_loader import load_teams

    try:
        teams = load_teams(data_dir / "teams.csv")
    except Exception:
        return {}
    try:
        d2l = load_playoffs_config(data_dir / "playoffs_config.json").division_to_league
    except Exception:
        d2l = {}
    return team_leagues(teams, d2l)


def backfill_archived_seasons(
    kinds: Sequence[str] = ("GOLD_GLOVE", "SILVER_SLUGGER"),
    *,
    data_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Hand out ``kinds`` for every archived season that doesn't have them
    yet (seasons archived before 8.12.0 have only a league-wide MVP and Cy
    Young, which are left exactly as awarded).

    Each season is judged on its own archive: its stats, its players' ratings
    as the season ended and each player's club from the career ledger. A
    season is marked done (``kinds``) even when no one qualified, so it is
    never judged twice. Returns ``[{season_id, league_year, added}]`` for
    the seasons it changed.
    """

    from playbalance.season_context import SeasonContext
    from utils.path_utils import get_data_dir
    from utils.player_loader import load_players_from_csv

    data = Path(data_dir) if data_dir is not None else get_data_dir()
    careers = data / "careers"
    try:
        ctx = SeasonContext.load(data / "career_index.json")
    except Exception:
        return []
    ledger: Optional[Dict[str, Any]] = None
    leagues: Optional[Dict[str, str]] = None
    changed: List[Dict[str, Any]] = []
    for season in ctx.iter_archived_seasons():
        season_id = str((season or {}).get("season_id") or "").strip()
        if not season_id:
            continue
        season_dir = careers / season_id
        stats_path = season_dir / "stats.json"
        if not stats_path.exists():
            continue
        awards_path = season_dir / "awards.json"
        payload = _read_json(awards_path, {})
        if not isinstance(payload, dict):
            payload = {}
        existing = payload.get("awards") if isinstance(payload.get("awards"), dict) else {}
        done = {str(k) for k in (payload.get("kinds") or [])}
        done |= {award_type(k, v) for k, v in existing.items()}
        missing = [k for k in kinds if k not in done]
        if not missing:
            continue
        stats_doc = _read_json(stats_path, {})
        player_stats = stats_doc.get("players") if isinstance(stats_doc, dict) else None
        if not isinstance(player_stats, dict):
            player_stats = {}
        roster_file = season_dir / "players.csv"
        try:
            players = {
                str(p.player_id): p
                for p in load_players_from_csv(
                    roster_file if roster_file.exists() else data / "players.csv"
                )
            }
        except Exception:
            _LOGGER.exception("awards: could not read the players of %s", season_id)
            continue
        if ledger is None:
            doc = _read_json(careers / "career_players.json", {})
            ledger = doc.get("players") if isinstance(doc, dict) else {}
            if not isinstance(ledger, dict):
                ledger = {}
        if leagues is None:
            leagues = current_team_leagues(data)
        team_of = {
            pid: str(((entry or {}).get("seasons") or {}).get(season_id, {}).get("team") or "")
            for pid, entry in ledger.items()
            if isinstance(entry, dict)
        }
        new = select_awards(
            players=players,
            stats=player_stats,
            team_of=team_of,
            team_league=leagues,
            max_games=max_team_games(stats_doc.get("teams") or {}),
            kinds=missing,
        )
        merged = dict(existing)
        merged.update(new)
        payload["awards"] = merged
        payload["kinds"] = sorted(done | set(missing))
        payload["backfilled_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_awards_file(awards_path, payload)
        changed.append(
            {
                "season_id": season_id,
                "league_year": season.get("league_year"),
                "added": len(new),
                "awards": new,
            }
        )
    return changed
