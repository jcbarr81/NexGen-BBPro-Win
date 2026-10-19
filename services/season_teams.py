"""Which club(s) each player played for in a season (8.2.3).

A season's stat line lives in the career ledger (``careers/career_players.json``)
without the club, so the player profile filled every season with the
player's CURRENT club: a free agent's whole history read "--". The rollover
now stores a ``team`` label with each season's line, built here from the
league's files as the season ended (before the contract step clears the
expiring players off the rosters):

* the club whose roster lists him (any level, the injured lists included);
* a player traded during the season gets every club in order, "BOS/CHA",
  from the season's transaction log (``transactions.csv`` is reset at each
  rollover, so it holds this season's moves only);
* a player released during the season (on no roster at its end) gets the
  club of his last logged move.

Read only.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List

__all__ = ["season_team_labels"]

_LEVELS = {"ACT", "AAA", "LOW", "DL", "DL15", "DL45", "IR"}


def _roster_clubs(rosters_dir: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not rosters_dir.exists():
        return out
    for path in sorted(rosters_dir.glob("*.csv")):
        if path.stem.endswith("_pitching") or path.stem.endswith("_lineup"):
            continue
        try:
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) > 1 and row[0].strip() and row[1].strip().upper() in _LEVELS:
                        out.setdefault(row[0].strip(), path.stem.upper())
        except OSError:
            continue
    return out


def _trade_paths(transactions: Path) -> tuple[Dict[str, List[str]], Dict[str, str]]:
    """``({player: [club, club, ...]}, {player: last club in the log})``:
    the clubs the season's trades moved him through, in order (the log is
    append-only, so file order is time order), and the club on his last
    logged move of any kind (a player released during the season is on no
    roster at its end; that club is the one he played for)."""

    paths: Dict[str, List[str]] = {}
    last: Dict[str, str] = {}
    if not transactions.exists():
        return paths, last
    try:
        with transactions.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                action = str(row.get("action") or "").strip().lower()
                pid = str(row.get("player_id") or "").strip()
                team = str(row.get("team_id") or "").strip().upper()
                if not pid or not team:
                    continue
                if action != "trade_out":
                    last[pid] = team
                if action not in {"trade_out", "trade_in"}:
                    continue
                path = paths.setdefault(pid, [])
                if action == "trade_out" and not path:
                    path.append(team)
                elif action == "trade_in" and (not path or path[-1] != team):
                    path.append(team)
    except OSError:
        pass
    return paths, last


def season_team_labels(data_dir: Path | str) -> Dict[str, str]:
    """``{player_id: "BAL"}`` (or "BOS/CHA" after a trade) for the season in
    ``data_dir``'s files; players on no roster and never traded are absent."""

    root = Path(data_dir)
    final = _roster_clubs(root / "rosters")
    labels: Dict[str, str] = dict(final)
    paths, last_logged = _trade_paths(root / "transactions.csv")
    for pid, club in last_logged.items():
        labels.setdefault(pid, club)  # released during the season
    for pid, path in paths.items():
        clubs = list(path)
        last = final.get(pid)
        if last and (not clubs or clubs[-1] != last):
            clubs.append(last)
        if clubs:
            labels[pid] = "/".join(clubs)
    return labels
