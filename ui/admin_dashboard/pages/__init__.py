"""Page scaffolding for the modular admin dashboard."""
from .base import DashboardPage
from .home import AdminHomePage
from .draft import DraftPage
from .league_settings import LeagueSettingsPage
from .season import SeasonPage
from .teams import TeamsPage
from .transactions import TransactionsPage
from .users import UsersPage
from .utilities import UtilitiesPage

__all__ = [
    "AdminHomePage",
    "DashboardPage",
    "DraftPage",
    "LeagueSettingsPage",
    "SeasonPage",
    "TeamsPage",
    "TransactionsPage",
    "UsersPage",
    "UtilitiesPage",
]
