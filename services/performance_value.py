"""What a player's record adds to his price (8.9.0, backlog #66).

A player used to be priced on his ratings alone, so two players with the
same ratings asked the same whatever they had hit. Owner's call
(2026-11-03, "moderate"): his big-league record counts too, as much as his
ratings for a full-time regular.

* **His record.** His last three big-league seasons (this season first once
  he has played in it, then the career ledger), weighted 5/4/3 by recency
  and by playing time. A hitter is measured by OPS+ (on-base and slugging
  against that season's league), a pitcher by run prevention and his
  strikeouts, walks and home runs (ERA and FIP against that season's
  league, half each). Each season becomes a z-score against the league's
  spread that season, so one league's offense level never prices another's.
* **How much it counts.** ``STATS_WEIGHT`` (one half) times his playing
  time: a season of ``FULL_PA`` plate appearances or ``FULL_OUTS`` outs is
  full time; older seasons count less. A player with no big-league time is
  priced on his ratings alone, a part-timer mostly on them.
* **Into the price.** The record becomes a quality (``QUALITY_CENTER`` for a
  league-average season, ``QUALITY_SD`` per standard deviation: the
  big-league mean and spread of the ratings quality on generation 6), and
  the price quality moves that share of the way from his ratings to it.

Postseason games are not here (``postseason_stats.json``), nor minor-league
games (they are not played). Every read is best effort: no stats, no change.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "STATS_WEIGHT",
    "price_note",
    "price_quality",
    "record",
]

STATS_WEIGHT = 0.5
RECENCY = (5.0, 4.0, 3.0)
FULL_PA = 500.0
FULL_OUTS = 450.0  # 150 innings
QUALITY_CENTER = 52.3
QUALITY_SD = 2.5
Z_CAP = 3.0
# Who sets a season's league spread: regulars and near-regulars.
NORM_MIN_PA = 100.0
NORM_MIN_OUTS = 150.0

CURRENT = "current"

_LOCK = threading.Lock()
_NORMS: Optional[Tuple[Any, Dict[str, Dict[str, float]]]] = None


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _is_pitching(line: Mapping[str, Any]) -> bool:
    return _num(line.get("outs")) > 0


def _is_batting(line: Mapping[str, Any]) -> bool:
    return _num(line.get("pa")) > 0 and not _is_pitching(line)


def _obp_slg(line: Mapping[str, Any]) -> Tuple[float, float, float, float]:
    """(on-base numerator, its denominator, total bases, at-bats)."""

    h, bb, hbp = _num(line.get("h")), _num(line.get("bb")), _num(line.get("hbp"))
    ab, sf = _num(line.get("ab")), _num(line.get("sf"))
    tb = _num(line.get("tb"))
    if tb <= 0:
        tb = (_num(line.get("b1")) + 2 * _num(line.get("b2"))
              + 3 * _num(line.get("b3")) + 4 * _num(line.get("hr")))
    return h + bb + hbp, ab + bb + hbp + sf, tb, ab


def _fip_raw(line: Mapping[str, Any]) -> float:
    ip = _num(line.get("outs")) / 3.0
    return (13 * _num(line.get("hr")) + 3 * (_num(line.get("bb")) + _num(line.get("hbp")))
            - 2 * _num(line.get("so"))) / ip


def _era(line: Mapping[str, Any]) -> float:
    return 27.0 * _num(line.get("er")) / _num(line.get("outs"))


def _weighted_sd(pairs: List[Tuple[float, float]]) -> float:
    total = sum(w for _, w in pairs)
    if total <= 0 or len(pairs) < 5:
        return 0.0
    mean = sum(v * w for v, w in pairs) / total
    return math.sqrt(sum(w * (v - mean) ** 2 for v, w in pairs) / total)


def _season_norms(lines: List[Mapping[str, Any]]) -> Optional[Dict[str, float]]:
    """One season's league: on-base and slugging, ERA and FIP, and the
    spread of OPS+, ERA and FIP among its regulars."""

    on = on_d = tb = ab = 0.0
    er = outs = fip_num = 0.0
    for line in lines:
        if _is_batting(line):
            a, b, c, d = _obp_slg(line)
            on, on_d, tb, ab = on + a, on_d + b, tb + c, ab + d
        elif _is_pitching(line):
            o = _num(line.get("outs"))
            er += _num(line.get("er"))
            outs += o
            fip_num += _fip_raw(line) * o / 3.0
    # Batting and pitching norms stand alone: a season with only one kind
    # of line still prices that kind.
    norms: Dict[str, float] = {}
    if on_d > 0 and ab > 0 and on > 0 and tb > 0:
        norms.update(obp=on / on_d, slg=tb / ab)
        norms["ops_plus_sd"] = _weighted_sd([
            (_ops_plus(line, norms), _num(line.get("pa")))
            for line in lines
            if _is_batting(line) and _num(line.get("pa")) >= NORM_MIN_PA
        ])
    if outs > 0:
        norms.update(era=27.0 * er / outs, fip=fip_num / (outs / 3.0))
        regulars = [line for line in lines
                    if _is_pitching(line) and _num(line.get("outs")) >= NORM_MIN_OUTS]
        norms["era_sd"] = _weighted_sd([(_era(line), _num(line.get("outs"))) for line in regulars])
        norms["fip_sd"] = _weighted_sd([(_fip_raw(line), _num(line.get("outs"))) for line in regulars])
    return norms or None


def _obp_and_slg(line: Mapping[str, Any]) -> Tuple[float, float]:
    on, on_d, tb, ab = _obp_slg(line)
    return (on / on_d if on_d > 0 else 0.0), (tb / ab if ab > 0 else 0.0)


def _ops_plus(line: Mapping[str, Any], norms: Mapping[str, float]) -> float:
    obp, slg = _obp_and_slg(line)
    return 100.0 * (obp / norms["obp"] + slg / norms["slg"] - 1.0)


def _payloads() -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """(cache token, {pid: {season id: line}}, {pid: this season's line})."""

    from utils import player_loader as pl
    from utils.path_utils import get_data_dir

    stats_path = get_data_dir() / "season_stats.json"
    career_path = pl.CAREER_DATA_DIR / "career_players.json"
    token = (pl._cache_token(stats_path), pl._cache_token(career_path))
    stats = pl._stats_payload() or {}
    current = stats.get("players", {}) if isinstance(stats, dict) else {}
    career = pl._career_payload() or {}
    seasons = {
        pid: entry.get("seasons", {})
        for pid, entry in career.items()
        if isinstance(entry, dict) and isinstance(entry.get("seasons"), dict)
    }
    return token, seasons, current if isinstance(current, dict) else {}


def _norms() -> Dict[str, Dict[str, float]]:
    """``{season id or CURRENT: norms}`` for the active league, cached on
    the stats files."""

    global _NORMS
    try:
        token, seasons, current = _payloads()
    except Exception:
        return {}
    with _LOCK:
        if _NORMS is not None and _NORMS[0] == token:
            return _NORMS[1]
    by_season: Dict[str, List[Mapping[str, Any]]] = {}
    for entry in seasons.values():
        for sid, line in entry.items():
            if isinstance(line, dict):
                by_season.setdefault(str(sid), []).append(line)
    if current:
        by_season[CURRENT] = [line for line in current.values() if isinstance(line, dict)]
    out: Dict[str, Dict[str, float]] = {}
    for sid, lines in by_season.items():
        norms = _season_norms(lines)
        if norms is not None:
            out[sid] = norms
    with _LOCK:
        _NORMS = (token, out)
    return out


def _year(season_id: str) -> Optional[int]:
    try:
        return int(str(season_id).rsplit("-", 1)[-1])
    except ValueError:
        return None


def _seasons(player: Any, pitcher: bool) -> List[Tuple[str, str, Mapping[str, Any]]]:
    """His most recent big-league seasons, newest first: ``(norms key,
    label, line)``, at most ``len(RECENCY)``."""

    keep = _is_pitching if pitcher else _is_batting
    out: List[Tuple[str, str, Mapping[str, Any]]] = []
    current = getattr(player, "season_stats", None)
    if isinstance(current, dict) and keep(current):
        out.append((CURRENT, "this season", current))
    history = getattr(player, "career_history", None)
    if isinstance(history, dict):
        dated = sorted(
            ((y, sid, line) for sid, line in history.items()
             if isinstance(line, dict) and keep(line) and (y := _year(sid)) is not None),
            reverse=True,
        )
        out.extend((sid, str(y), line) for y, sid, line in dated)
    return out[: len(RECENCY)]


def _season_z(line: Mapping[str, Any], norms: Mapping[str, float], pitcher: bool) -> Optional[float]:
    if pitcher:
        era_sd, fip_sd = norms.get("era_sd") or 0.0, norms.get("fip_sd") or 0.0
        if era_sd <= 0 or fip_sd <= 0:
            return None
        z = 0.5 * (norms["era"] - _era(line)) / era_sd + 0.5 * (norms["fip"] - _fip_raw(line)) / fip_sd
    else:
        sd = norms.get("ops_plus_sd") or 0.0
        if sd <= 0:
            return None
        z = (_ops_plus(line, norms) - 100.0) / sd
    return max(-Z_CAP, min(Z_CAP, z))


def record(player: Any) -> Optional[Dict[str, Any]]:
    """His record as the price reads it: ``{z, share, seasons}``, ``z`` his
    playing-time-weighted standing against the league (in standard
    deviations), ``share`` how much of full time it covers (0..1), and each
    season's ``{label, pa | ip, ops_plus | era, fip}``. None without a
    big-league season."""

    try:
        pitcher = bool(getattr(player, "is_pitcher", False))
        norms = _norms()
        if not norms:
            return None
        weighted = total = playing = 0.0
        shown: List[Dict[str, Any]] = []
        for (key, label, line), recency in zip(_seasons(player, pitcher), RECENCY):
            season_norms = norms.get(key)
            if season_norms is None:
                continue
            z = _season_z(line, season_norms, pitcher)
            if z is None:
                continue
            time = _num(line.get("outs")) if pitcher else _num(line.get("pa"))
            weighted += recency * time * z
            total += recency * time
            playing += recency / RECENCY[0] * time / (FULL_OUTS if pitcher else FULL_PA)
            row: Dict[str, Any] = {"label": label}
            if pitcher:
                row.update(ip=round(_num(line.get("outs")) / 3.0, 1),
                           era=round(_era(line), 2))
            else:
                row.update(pa=int(_num(line.get("pa"))),
                           ops=round(sum(_obp_and_slg(line)), 3),
                           ops_plus=int(round(_ops_plus(line, season_norms))))
            shown.append(row)
        if total <= 0:
            return None
        return {"z": weighted / total, "share": min(1.0, playing), "seasons": shown}
    except Exception:
        return None


def price_quality(player: Any, quality: float) -> float:
    """``quality`` (his ratings) moved toward what his record is worth, by
    ``STATS_WEIGHT`` times his playing time."""

    rec = record(player)
    if rec is None:
        return quality
    earned = QUALITY_CENTER + rec["z"] * QUALITY_SD
    return quality + STATS_WEIGHT * rec["share"] * (earned - quality)


def _money(value: float) -> str:
    return f"${value / 1_000_000:.1f}M"


def _season_text(row: Mapping[str, Any]) -> str:
    if "era" in row:
        return f"{row['label']}: {row['ip']:g} IP, {row['era']:.2f} ERA"
    return f"{row['label']}: {row['pa']} PA, {row['ops']:.3f} OPS (OPS+ {row['ops_plus']})"


def price_note(player: Any) -> Optional[Dict[str, Any]]:
    """Why his record moves his price, for the offer dialogs:
    ``{pct, text}`` ("His record raises his price (about $1.1M on his
    ratings alone): 2026: 375 PA, .835 OPS (OPS+ 122)."), or None when it moves it under 5% (or not at
    all: no record, or both prices at the minimum)."""

    try:
        from services.contracts_service import estimate_market_value_for_player

        rec = record(player)
        if rec is None:
            return None
        with_record = estimate_market_value_for_player(player)
        ratings_only = estimate_market_value_for_player(player, use_stats=False)
        if ratings_only <= 0:
            return None
        pct = int(round(100.0 * (with_record / ratings_only - 1.0)))
        if abs(pct) < 5:
            return None
        seasons = "; ".join(_season_text(row) for row in rec["seasons"][:2])
        verb = "raises" if pct > 0 else "lowers"
        # Dollars, not a percentage: from a low base a percentage balloons
        # (+222% is $1.1M to $3.6M).
        return {
            "pct": pct,
            "text": f"His record {verb} his price (about {_money(ratings_only)} on his "
                    f"ratings alone): {seasons}.",
        }
    except Exception:
        return None
