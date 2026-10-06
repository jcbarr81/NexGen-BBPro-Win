import csv
import json
import os
import re
from pathlib import Path

try:  # Allow running as a standalone script
    from models.team import Team
    from utils.path_utils import (
        get_base_dir as _get_base_dir,
        get_data_dir as _get_data_dir,
        resolve_app_path,
    )
    from utils.stats_persistence import load_stats
    from playbalance.season_context import CAREER_DATA_DIR
except ModuleNotFoundError:  # pragma: no cover - for direct script execution
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from models.team import Team
    from utils.path_utils import (
        get_base_dir as _get_base_dir,
        get_data_dir as _get_data_dir,
        resolve_app_path,
    )
    from utils.stats_persistence import load_stats
    from playbalance.season_context import CAREER_DATA_DIR

# Backwards compatibility: tests patch these attributes directly.
get_base_dir = _get_base_dir
get_data_dir = _get_data_dir


def _resolve_path(file_path: str | Path) -> Path:
    """Return an absolute :class:`Path` for ``file_path`` relative to the project root."""

    path = Path(file_path)
    if path.is_absolute():
        return path
    candidate = resolve_app_path(path)
    if candidate.exists():
        return candidate
    fallback_root = Path(__file__).resolve().parents[1]
    return fallback_root / path


def _load_career_teams() -> dict[str, dict]:
    path = CAREER_DATA_DIR / "career_teams.json"
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    teams = data.get("teams", {})
    if isinstance(teams, dict):
        return teams
    return {}


def load_teams(file_path: str | Path = "data/teams.csv"):
    file_path = _resolve_path(file_path)
    teams = []
    with file_path.open(mode="r", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        # Audit L13: leagues created since the fix carry a park_id column
        # (empty unless a park was explicitly chosen). Older files have none;
        # their teams keep park_id=None and the legacy name lookup.
        has_park_id = "park_id" in (reader.fieldnames or [])
        for row in reader:
            team = Team(
                team_id=row["team_id"],
                name=row["name"],
                city=row["city"],
                abbreviation=row["abbreviation"],
                division=row["division"],
                stadium=row["stadium"],
                primary_color=row["primary_color"],
                secondary_color=row["secondary_color"],
                owner_id=row["owner_id"],
                park_id=(
                    (row.get("park_id") or "").strip() if has_park_id else None
                ),
            )
            teams.append(team)
    stats = load_stats()
    career_map = _load_career_teams()
    for team in teams:
        season = stats["teams"].get(team.team_id)
        if season:
            team.season_stats = season
        career_entry = career_map.get(team.team_id)
        if career_entry:
            totals = career_entry.get("totals", {})
            if isinstance(totals, dict):
                team.career_stats = dict(totals)
            seasons = career_entry.get("seasons", {})
            if isinstance(seasons, dict):
                team.career_history = {
                    sid: dict(data) if isinstance(data, dict) else data
                    for sid, data in seasons.items()
                }
    return teams


def save_team_settings(team: Team, file_path: str | Path = "data/teams.csv") -> None:
    """Persist updates to a single team's stadium, park pick or colors.

    Reads the entire teams file, updates the matching team's fields and
    overwrites the CSV. Only the ``stadium``, ``park_id`` and color fields are
    modified so other information remains unchanged. ``park_id`` is written
    only when the file already has that column: a legacy league stays on the
    name lookup rather than gaining a column whose blanks would mean
    "generic park" for every other club (audit L13).
    """

    def _sanitize_color(value: str, field: str) -> str:
        """Return a normalized hex color or raise ``ValueError``.

        The function ensures the color string begins with ``#`` and matches the
        ``#RRGGBB`` or ``#RGB`` formats. If the value cannot be normalized into a
        valid hex color a descriptive ``ValueError`` is raised.
        """

        value = value.strip()
        if not value.startswith("#"):
            value = f"#{value}"
        if re.fullmatch(r"#(?:[0-9a-fA-F]{3}){1,2}$", value):
            return value.upper()
        raise ValueError(f"Invalid hex color for {field}: {value}")

    file_path = _resolve_path(file_path)
    teams = []
    with file_path.open(mode="r", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        file_fields = list(reader.fieldnames or [])
        for row in reader:
            if row["team_id"] == team.team_id:
                row["stadium"] = team.stadium
                if "park_id" in file_fields and team.park_id is not None:
                    row["park_id"] = team.park_id
                row["primary_color"] = _sanitize_color(team.primary_color, "primary_color")
                row["secondary_color"] = _sanitize_color(team.secondary_color, "secondary_color")
            teams.append(row)

    fieldnames = [
        "team_id",
        "name",
        "city",
        "abbreviation",
        "division",
        "stadium",
        "primary_color",
        "secondary_color",
        "owner_id",
    ]
    # Keep any extra columns (park_id) the file carries; DictWriter would
    # otherwise reject them.
    fieldnames += [name for name in file_fields if name not in fieldnames]
    with file_path.open(mode="w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(teams)

