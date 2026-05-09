from __future__ import annotations

from typing import Iterable, Dict, Any, List, Tuple

from models.base_player import BasePlayer


def format_number(value: Any, *, decimals: int = 3) -> str:
    if value is None:
        return "0"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:.{decimals}f}"
        return str(value)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{numeric:.{decimals}f}"


def format_ip(value: Any) -> str:
    if value is None:
        return "0.0"
    try:
        ip = float(value)
    except (TypeError, ValueError):
        return str(value)
    outs = int(round(ip * 3))
    innings = outs // 3
    remainder = outs % 3
    return f"{innings}.{remainder}"


def _ensure_stats(player: BasePlayer) -> Dict[str, Any]:
    stats = getattr(player, 'season_stats', None)
    return stats or {}


def _is_outlier_stat_line(stats: Dict[str, Any]) -> bool:
    try:
        games = float(stats.get('g', 0) or 0)
        plate_appearances = float(stats.get('pa', 0) or 0)
        at_bats = float(stats.get('ab', 0) or 0)
    except (TypeError, ValueError):
        return False
    if games > 200:
        return True
    if plate_appearances > 900:
        return True
    if at_bats > 800:
        return True
    return False


def batting_summary(players: Iterable[BasePlayer]) -> List[Tuple[str, str]]:
    hitters = list(players)
    totals = dict(ab=0.0, h=0.0, bb=0.0, hbp=0.0, sf=0.0, hr=0.0, r=0.0, sb=0.0, b2=0.0, b3=0.0)
    for player in hitters:
        stats = _ensure_stats(player)
        totals['ab'] += stats.get('ab', 0)
        totals['h'] += stats.get('h', 0)
        totals['bb'] += stats.get('bb', 0)
        totals['hbp'] += stats.get('hbp', 0)
        totals['sf'] += stats.get('sf', 0)
        totals['hr'] += stats.get('hr', 0)
        totals['r'] += stats.get('r', 0)
        totals['sb'] += stats.get('sb', 0)
        totals['b2'] += stats.get('b2', stats.get('2b', 0))
        totals['b3'] += stats.get('b3', stats.get('3b', 0))
    ab = totals['ab']
    hits = totals['h']
    doubles = totals['b2']
    triples = totals['b3']
    homers = totals['hr']
    singles = hits - doubles - triples - homers
    singles = max(singles, 0)
    walks = totals['bb']
    hbp = totals['hbp']
    sf = totals['sf']
    denom_obp = ab + walks + hbp + sf
    total_bases = singles + 2 * doubles + 3 * triples + 4 * homers
    avg = hits / ab if ab else 0.0
    obp = (hits + walks + hbp) / denom_obp if denom_obp else 0.0
    slg = total_bases / ab if ab else 0.0
    return [
        ('AVG', format_number(avg, decimals=3)),
        ('OBP', format_number(obp, decimals=3)),
        ('SLG', format_number(slg, decimals=3)),
        ('RUNS', format_number(totals['r'], decimals=0)),
        ('HR', format_number(homers, decimals=0)),
        ('SB', format_number(totals['sb'], decimals=0)),
    ]


def pitching_summary(players: Iterable[BasePlayer]) -> List[Tuple[str, str]]:
    pitchers = list(players)
    totals = dict(ip=0.0, er=0.0, bb=0.0, h=0.0, so=0.0, w=0.0, l=0.0, sv=0.0)
    for player in pitchers:
        stats = _ensure_stats(player)
        ip = stats.get('ip')
        if ip is None:
            outs = stats.get('outs')
            ip = outs / 3 if outs is not None else 0
        totals['ip'] += ip or 0
        totals['er'] += stats.get('er', 0)
        totals['bb'] += stats.get('bb', 0)
        totals['h'] += stats.get('h', 0)
        totals['so'] += stats.get('so', 0)
        totals['w'] += stats.get('w', stats.get('wins', 0))
        totals['l'] += stats.get('l', stats.get('losses', 0))
        totals['sv'] += stats.get('sv', 0)
    ip = totals['ip']
    era = (totals['er'] * 9) / ip if ip else 0.0
    whip = (totals['bb'] + totals['h']) / ip if ip else 0.0
    k_per9 = (totals['so'] * 9) / ip if ip else 0.0
    return [
        ('ERA', format_number(era, decimals=2)),
        ('WHIP', format_number(whip, decimals=2)),
        ('K/9', format_number(k_per9, decimals=2)),
        ('W-L', f"{int(totals['w'])}-{int(totals['l'])}"),
        ('SV', format_number(totals['sv'], decimals=0)),
    ]


def top_players(players: Iterable[BasePlayer], key: str, *, pitcher_only: bool, descending: bool = True, limit: int = 5) -> List[Tuple[BasePlayer, Any]]:
    eligible: List[Tuple[BasePlayer, Any]] = []
    for player in players:
        if getattr(player, 'is_pitcher', False) != pitcher_only:
            continue
        stats = _ensure_stats(player)
        if _is_outlier_stat_line(stats):
            continue
        value = stats.get(key, 0)
        eligible.append((player, value))
    eligible.sort(key=lambda item: item[1], reverse=descending)
    results: List[Tuple[BasePlayer, Any]] = []
    for player, value in eligible:
        if descending and (value is None or value == 0):
            continue
        if value is None:
            continue
        results.append((player, value))
        if len(results) >= limit:
            break
    return results
