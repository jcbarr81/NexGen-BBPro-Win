"""Standings-based competitive outlook shared by trading + callups.

A team's *outlook* is a coarse, liquidity-free read on whether it should be
buying (``contend``), selling (``rebuild``), or standing pat (``bubble``) — the
signal deadline-aware CPU trading (S2-09), CPU→CPU trades (S2-10), and in-season
callups (S2-11) all consume. Deliberately kept separate from
``finance_ai._resolve_profile`` (which entangles cash/debt); thresholds are
numerically aligned with it so the two views rarely disagree.
"""
from __future__ import annotations

from typing import Mapping

__all__ = [
    "OUTLOOK_CONTEND",
    "OUTLOOK_BUBBLE",
    "OUTLOOK_REBUILD",
    "games_back",
    "team_outlook",
    "load_outlooks",
]

OUTLOOK_CONTEND = "contend"
OUTLOOK_BUBBLE = "bubble"
OUTLOOK_REBUILD = "rebuild"

_MIN_GAMES_FOR_SIGNAL = 20   # before ~3 weeks of games, everyone is a bubble team
_CONTEND_WIN_PCT = 0.565     # aligned with finance_ai._resolve_profile (finance_ai.py:491)
_REBUILD_WIN_PCT = 0.445     # aligned with finance_ai._resolve_profile (finance_ai.py:493)
_CONTEND_GB = 4.0            # within 4 of the division lead == in the race
_REBUILD_GB = 12.0          # 12+ back == out of it


def _wl(standings: Mapping[str, Mapping[str, object]], team_id: str) -> tuple[int, int]:
    """Return (wins, losses) for ``team_id`` from a normalized standings map.

    Tolerant of casing (standings.json keys vs upper-cased team ids) and of
    teams missing entirely from the standings (returns 0-0)."""

    token = str(team_id or "").strip()
    record = standings.get(token) or standings.get(token.upper()) or standings.get(token.lower())
    if not isinstance(record, Mapping):
        return 0, 0
    try:
        wins = int(record.get("wins", 0) or 0)
    except (TypeError, ValueError):
        wins = 0
    try:
        losses = int(record.get("losses", 0) or 0)
    except (TypeError, ValueError):
        losses = 0
    return wins, losses


def _division_of(teams_by_id: Mapping[str, object], team_id: str) -> str:
    token = str(team_id or "").strip().upper()
    team = teams_by_id.get(token) or teams_by_id.get(str(team_id or "").strip())
    return str(getattr(team, "division", "") or "").strip()


def games_back(
    team_id: str,
    *,
    standings: Mapping[str, Mapping[str, object]],
    teams_by_id: Mapping[str, object],
) -> float:
    """GB vs the leader of the team's division (models/team.py:18 ``division``).

    Teams with unknown division compare against the overall league leader.
    ``GB = ((lead_w - w) + (l - lead_l)) / 2``, floored at 0.0. The division
    leader is whichever team sorts first by ``(-wins, losses, team_id)`` —
    deterministic under ties; co-leaders all get GB 0.0.
    """

    division = _division_of(teams_by_id, team_id)
    # Peers: same division, or the whole league when division is unknown.
    peers: list[str] = []
    for tid in teams_by_id:
        if not division or _division_of(teams_by_id, tid) == division:
            peers.append(str(tid).strip().upper())
    if not peers:
        peers = [str(team_id).strip().upper()]

    def _sort_key(tid: str) -> tuple[int, int, str]:
        wins, losses = _wl(standings, tid)
        return (-wins, losses, tid)

    leader = sorted(peers, key=_sort_key)[0]
    lead_w, lead_l = _wl(standings, leader)
    w, l = _wl(standings, team_id)
    gb = ((lead_w - w) + (l - lead_l)) / 2.0
    return max(0.0, gb)


def team_outlook(
    team_id: str,
    *,
    standings: Mapping[str, Mapping[str, object]],
    teams_by_id: Mapping[str, object],
    sim_date: str | None = None,
) -> str:
    """Classify ``team_id`` as contend / bubble / rebuild (first rule wins).

    1. games_played (wins+losses) < ``_MIN_GAMES_FOR_SIGNAL`` -> bubble
    2. win_pct >= ``_CONTEND_WIN_PCT`` or games_back <= ``_CONTEND_GB`` -> contend
    3. win_pct <= ``_REBUILD_WIN_PCT`` or games_back >= ``_REBUILD_GB`` -> rebuild
    4. else -> bubble

    ``win_pct`` is wins/(wins+losses) from the normalized standings record
    (0.500 when the team is missing from standings). ``sim_date`` is accepted
    for signature stability (S2-11 passes it) but unused here.
    """

    wins, losses = _wl(standings, team_id)
    games_played = wins + losses
    if games_played < _MIN_GAMES_FOR_SIGNAL:
        return OUTLOOK_BUBBLE
    win_pct = wins / games_played if games_played else 0.500
    gb = games_back(team_id, standings=standings, teams_by_id=teams_by_id)
    if win_pct >= _CONTEND_WIN_PCT or gb <= _CONTEND_GB:
        return OUTLOOK_CONTEND
    if win_pct <= _REBUILD_WIN_PCT or gb >= _REBUILD_GB:
        return OUTLOOK_REBUILD
    return OUTLOOK_BUBBLE


def load_outlooks(*, data_dir=None) -> dict[str, str]:
    """Convenience: classify every team in ``teams.csv``.

    Loads standings (normalized) via ``services.standings_repository`` and teams
    via ``utils.team_loader``; returns ``{TEAM_ID_UPPER: outlook}``. Returns an
    empty dict on any failure so callers can treat every team as ``bubble``
    (i.e. behavior identical to the pre-S2-09 standings-blind path).
    """

    try:
        from services.standings_repository import load_standings
        from utils.team_loader import load_teams

        standings = load_standings(base_path=data_dir, normalize=True)
        teams = load_teams((data_dir / "teams.csv")) if data_dir is not None else load_teams()
    except Exception:
        return {}

    teams_by_id = {
        str(getattr(team, "team_id", "") or "").strip().upper(): team
        for team in teams
    }
    teams_by_id.pop("", None)
    outlooks: dict[str, str] = {}
    for team_id in teams_by_id:
        try:
            outlooks[team_id] = team_outlook(
                team_id, standings=standings, teams_by_id=teams_by_id
            )
        except Exception:
            outlooks[team_id] = OUTLOOK_BUBBLE
    return outlooks
