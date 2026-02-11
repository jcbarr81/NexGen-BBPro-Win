"""Simple draft manager for three-round draft.

Loads draft pool and team list, runs a three round draft and logs selections.
After the draft, selected players are appended to each team's LOW roster file.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List

from utils.path_utils import resolve_app_path
from utils.roster_loader import load_roster, save_roster


def _resolve_path(path: str | Path) -> Path:
    """Return an absolute path based on project root."""
    path = Path(path)
    if path.is_absolute():
        return path
    return resolve_app_path(path)


def load_draft_pool(pool_path: str | Path = "playbalance/draft_pool.csv") -> List[dict]:
    """Load draft candidates from a CSV file."""
    pool_path = _resolve_path(pool_path)
    with pool_path.open(newline="") as csvfile:
        return list(csv.DictReader(csvfile))


def load_teams(team_path: str | Path = "data/teams.csv") -> List[str]:
    """Load team identifiers in draft order."""
    team_path = _resolve_path(team_path)
    with team_path.open(newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        return [row["team_id"] for row in reader]


def run_draft(
    rounds: int = 3,
    pool_path: str | Path = "playbalance/draft_pool.csv",
    team_path: str | Path = "data/teams.csv",
    log_path: str | Path = "data/draft_log.txt",
) -> Dict[str, List[str]]:
    """Run a multi-round draft and update rosters.

    Returns a mapping of team ids to drafted player ids.
    """
    players = load_draft_pool(pool_path)
    teams = load_teams(team_path)
    selections: Dict[str, List[str]] = {tid: [] for tid in teams}

    log_path = _resolve_path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_file:
        pick_idx = 0
        for rnd in range(1, rounds + 1):
            for team in teams:
                if pick_idx >= len(players):
                    break
                player = players[pick_idx]
                pick_idx += 1
                player_id = player.get("player_id")
                selections[team].append(player_id)
                log_file.write(f"Round {rnd}: {team} selects {player_id}\n")

    for team, picks in selections.items():
        if not picks:
            continue
        roster = load_roster(team)
        roster.low.extend(picks)
        save_roster(team, roster)

    return selections


__all__ = ["load_draft_pool", "load_teams", "run_draft"]


if __name__ == "__main__":  # pragma: no cover
    run_draft()
