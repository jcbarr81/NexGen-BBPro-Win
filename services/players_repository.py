from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from services.unified_data_service import get_unified_data_service
from utils.path_utils import resolve_app_path
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv

_RELATIVE_PATH = Path("data") / "players.csv"


def _resolve_target(path: Path | str | None) -> Path:
    if path is None:
        return _RELATIVE_PATH
    return Path(path)


def load_players(path: Path | str | None = None) -> list[Any]:
    """Return players from *path* via the shared player loader/cache."""

    target = _resolve_target(path)
    return list(load_players_from_csv(target))


def save_players(
    players: Iterable[Any],
    path: Path | str | None = None,
) -> list[Any]:
    """Persist *players* and refresh the unified players cache."""

    target = _resolve_target(path)
    resolved = resolve_app_path(target)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    snapshot = list(players)
    save_players_to_csv(snapshot, str(resolved))

    service = get_unified_data_service()
    service.update_players(target, snapshot)
    return snapshot


def invalidate_players(path: Path | str | None = None) -> None:
    """Invalidate cached players for *path* (or all players when omitted)."""

    service = get_unified_data_service()
    service.invalidate_players(path)


__all__ = ["invalidate_players", "load_players", "save_players"]
