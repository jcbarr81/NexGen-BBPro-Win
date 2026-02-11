from __future__ import annotations

"""Draft AI helpers: team needs and prospect scoring.

This is an initial heuristic that biases picks toward organizational needs by
position and starter/reliever balance. It relies on players.csv and roster
files to estimate depth.
"""

from typing import Dict, Any, Iterable

from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.path_utils import get_data_dir


BASE = get_data_dir()

# Simple org target counts — tune as needed
POSITION_TARGETS: Dict[str, int] = {
    "C": 4,
    "1B": 4,
    "2B": 5,
    "3B": 4,
    "SS": 5,
    "LF": 5,
    "CF": 5,
    "RF": 5,
}
SP_TARGET = 10
RP_TARGET = 15


def _as_pitcher(p: Any) -> bool:
    return bool(getattr(p, "is_pitcher", False) or str(getattr(p, "primary_position", "")).upper() == "P")


def _is_sp(p: Any) -> bool:
    role = str(getattr(p, "role", "") or "").upper()
    if role == "SP":
        return True
    endu = getattr(p, "endurance", 0) or 0
    return _as_pitcher(p) and endu >= 70


def compute_team_needs(team_id: str) -> Dict[str, float]:
    """Return need scores per position plus 'SP' and 'RP' in [0, 1]."""
    players = {p.player_id: p for p in load_players_from_csv(str(BASE / "players.csv"))}
    try:
        roster = load_roster(team_id)
        ids: list[str] = roster.act + roster.aaa + roster.low
    except FileNotFoundError:
        ids = []
    org: list[Any] = [players[i] for i in ids if i in players]
    counts: Dict[str, int] = {k: 0 for k in POSITION_TARGETS}
    sp = rp = 0
    for p in org:
        prim = str(getattr(p, "primary_position", "")).upper()
        if _as_pitcher(p):
            if _is_sp(p):
                sp += 1
            else:
                rp += 1
        elif prim in counts:
            counts[prim] += 1
    needs: Dict[str, float] = {}
    for pos, target in POSITION_TARGETS.items():
        have = counts.get(pos, 0)
        need = max(0.0, (target - have) / max(target, 1))
        needs[pos] = min(1.0, need)
    needs["SP"] = min(1.0, max(0.0, (SP_TARGET - sp) / max(SP_TARGET, 1)))
    needs["RP"] = min(1.0, max(0.0, (RP_TARGET - rp) / max(RP_TARGET, 1)))
    return needs


def score_prospect(p: Dict[str, Any], needs: Dict[str, float]) -> int:
    """Return a need‑aware score for a prospect.

    Base score uses role‑appropriate ratings; multiplied by (1 + 0.5*need) for
    the relevant position bucket.
    """
    is_pitcher = bool(p.get("is_pitcher"))
    if is_pitcher:
        base = int(p.get("endurance", 0) or 0) + int(p.get("control", 0) or 0) + int(p.get("movement", 0) or 0)
        # Starter vs reliever need bias
        endu = int(p.get("endurance", 0) or 0)
        bucket = "SP" if endu >= 70 else "RP"
    else:
        base = int(p.get("ch", 0) or 0) + int(p.get("ph", 0) or 0) + int(p.get("sp", 0) or 0)
        bucket = str(p.get("primary_position", "SS") or "SS").upper()
        if bucket not in POSITION_TARGETS:
            bucket = "SS"
    need = float(needs.get(bucket, 0.0))
    score = int(base * (1.0 + 0.5 * need))
    return score


__all__ = ["compute_team_needs", "score_prospect"]
