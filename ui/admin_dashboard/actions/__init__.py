"""Action module namespace for the modular admin dashboard."""

from .assets import (
    generate_player_avatars_action,
    generate_team_logos_action,
)
from .almanac import export_almanac_action
from .league import create_league_action, reset_season_to_opening_day
from .league_snapshot import export_league_snapshot_action
from .reports import export_reports_action
from .teams import (
    auto_reassign_rosters,
    set_all_lineups,
    set_all_pitching_roles,
)
from .trades import review_pending_trades
from .users import add_user_action, edit_user_action

__all__ = [
    "add_user_action",
    "auto_reassign_rosters",
    "create_league_action",
    "edit_user_action",
    "export_almanac_action",
    "export_league_snapshot_action",
    "export_reports_action",
    "generate_player_avatars_action",
    "generate_team_logos_action",
    "reset_season_to_opening_day",
    "review_pending_trades",
    "set_all_lineups",
    "set_all_pitching_roles",
]
