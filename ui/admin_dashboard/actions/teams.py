"""Team management actions for the admin dashboard."""
from __future__ import annotations

import csv
from typing import Optional

from PyQt6.QtWidgets import QMessageBox, QWidget

from utils.lineup_autofill import auto_fill_lineup_for_team
from utils.path_utils import get_data_dir
from utils.pitcher_role import get_role
from utils.pitching_autofill import autofill_pitching_staff
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.team_loader import load_teams
from utils.roster_validation import missing_positions
from services.roster_auto_assign import auto_assign_all_teams

from ..context import DashboardContext


def set_all_lineups(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Auto-fill batting orders for every team in the current league."""

    data_dir = get_data_dir()
    teams = load_teams(data_dir / "teams.csv")
    errors: list[str] = []
    for team in teams:
        try:
            auto_fill_lineup_for_team(
                team.team_id,
                players_file=data_dir / "players.csv",
                roster_dir=data_dir / "rosters",
                lineup_dir=data_dir / "lineups",
            )
        except Exception as exc:
            errors.append(f"{team.team_id}: {exc}")

    if parent is None:
        return

    if errors:
        QMessageBox.warning(
            parent,
            "Lineups Set (with issues)",
            "Some lineups could not be auto-filled:\n" + "\n".join(errors),
        )
    else:
        QMessageBox.information(parent, "Lineups Set", "Lineups auto-filled for all teams.")


def set_all_pitching_roles(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Assign pitching roles for all clubs based on current rosters."""

    data_dir = get_data_dir()
    players_file = data_dir / "players.csv"
    if not players_file.exists():
        if parent is not None:
            QMessageBox.warning(parent, "Error", "Players file not found.")
        return

    players = {}
    with players_file.open("r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            player_id = row.get("player_id", "").strip()
            players[player_id] = {
                "primary_position": row.get("primary_position", "").strip(),
                "role": row.get("role", "").strip(),
                "endurance": row.get("endurance", ""),
                "preferred_pitching_role": (row.get("preferred_pitching_role") or "").strip(),
            }

    teams = load_teams(data_dir / "teams.csv")
    for team in teams:
        try:
            roster = load_roster(team.team_id)
        except FileNotFoundError:
            continue
        available = [
            (pid, players[pid])
            for pid in roster.act
            if pid in players and get_role(players[pid])
        ]
        assignments = autofill_pitching_staff(available)
        path = data_dir / "rosters" / f"{team.team_id}_pitching.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists():
                try:
                    path.chmod(0o644)
                except OSError:
                    pass
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                for role, player_id in assignments.items():
                    writer.writerow([player_id, role])
        except PermissionError as exc:
            if parent is not None:
                QMessageBox.warning(
                    parent,
                    "Permission Denied",
                    f"Cannot write pitching roles to {path}.\n{exc}",
                )
            return

    if parent is not None:
        QMessageBox.information(
            parent,
            "Pitching Staff Set",
            "Pitching roles auto-filled for all teams.",
        )


def auto_reassign_rosters(
    context: DashboardContext,
    parent: Optional[QWidget] = None,
) -> None:
    """Reassign players across roster levels for all teams."""

    try:
        auto_assign_all_teams()
    except Exception as exc:
        if parent is not None:
            QMessageBox.warning(parent, "Auto Reassign Failed", str(exc))
        return

    if parent is None:
        return

    data_dir = get_data_dir()
    players = {p.player_id: p for p in load_players_from_csv(data_dir / "players.csv")}
    teams = load_teams(data_dir / "teams.csv")
    issues: list[str] = []
    for team in teams:
        try:
            roster = load_roster(team.team_id)
        except FileNotFoundError:
            continue
        missing = missing_positions(roster, players)
        if missing:
            issues.append(f"{team.team_id}: {', '.join(missing)}")

    if issues:
        QMessageBox.warning(
            parent,
            "Coverage Warnings",
            "Some teams lack defensive coverage on the Active roster:\n"
            + "\n".join(issues),
        )
    else:
        QMessageBox.information(parent, "Rosters Updated", "Auto reassigned rosters for all teams.")


__all__ = [
    "auto_reassign_rosters",
    "set_all_lineups",
    "set_all_pitching_roles",
]
