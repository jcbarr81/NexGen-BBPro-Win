from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from services.unified_data_service import get_unified_data_service
from utils.path_utils import resolve_app_path
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv

_RELATIVE_PATH = Path("data") / "players.csv"

# Below this many existing rows there is nothing worth protecting (a new or
# fixture league), so the guard stays out of the way.
_GUARD_MIN_EXISTING_ROWS = 10

# Writing fewer than this fraction of what is already on disk is treated as a
# mistake rather than an intentional cull. Real shrinkage — retirements at the
# offseason rollover, a handful of releases — is a few percent; the incident
# this guards against wrote 1 row over 1,000.
_GUARD_MIN_KEEP_FRACTION = 0.5


class PlayersFileShrinkError(RuntimeError):
    """Raised when a write would destroy most of the players file.

    ``save_players`` REPLACES the file with what it is handed. Passing a subset
    — ``save_players([player])`` being the obvious trap — silently deletes
    everyone else. That happened in production: one Place-on-IL click rewrote a
    1,000-player league down to a single row, and it was only recoverable
    because the bucket had object versioning.

    Callers that genuinely mean to shrink the file pass ``allow_shrink=True``.
    """


def _resolve_target(path: Path | str | None) -> Path:
    if path is None:
        return _RELATIVE_PATH
    return Path(path)


def load_players(path: Path | str | None = None) -> list[Any]:
    """Return players from *path* via the shared player loader/cache."""

    target = _resolve_target(path)
    return list(load_players_from_csv(target))


def _existing_row_count(resolved: Path) -> int:
    """Rows currently in the file, counted cheaply.

    ``save_players`` runs once per simulated game, so this must not parse the
    CSV — it counts newlines and drops the header.
    """

    try:
        if not resolved.exists():
            return 0
        with resolved.open("rb") as fh:
            lines = sum(1 for _ in fh)
        return max(0, lines - 1)
    except OSError:  # pragma: no cover - defensive
        return 0


def save_players(
    players: Iterable[Any],
    path: Path | str | None = None,
    *,
    allow_shrink: bool = False,
) -> list[Any]:
    """Replace the players file with *players* and refresh the cache.

    This is a REPLACE, not an upsert: whatever is not in *players* is gone. To
    change one player use :func:`update_players`, which reads the rest back for
    you.

    Raises :class:`PlayersFileShrinkError` when the write would drop most of an
    existing file, unless ``allow_shrink=True``.
    """

    target = _resolve_target(path)
    resolved = resolve_app_path(target)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    snapshot = list(players)

    if not allow_shrink:
        existing = _existing_row_count(resolved)
        if (
            existing >= _GUARD_MIN_EXISTING_ROWS
            and len(snapshot) < existing * _GUARD_MIN_KEEP_FRACTION
        ):
            raise PlayersFileShrinkError(
                f"Refusing to write {len(snapshot)} player(s) over {existing} in "
                f"{resolved}: save_players REPLACES the file, so this would "
                "delete the rest of the league. Use update_players() to change "
                "individual players, or pass allow_shrink=True if you really "
                "mean to cull the file."
            )

    save_players_to_csv(snapshot, str(resolved))

    service = get_unified_data_service()
    service.update_players(target, snapshot)
    return snapshot


def update_players(
    changed: Iterable[Any],
    path: Path | str | None = None,
) -> list[Any]:
    """Upsert *changed* into the players file, leaving everyone else alone.

    This is what almost every caller actually wants when a player's state moves
    — an injury, an activation, a rating change. It reads the current set,
    swaps in the changed players by id, and writes the whole thing back.

    Refuses to write rather than risk truncation if the read comes back empty
    while changes were requested: a lost field is recoverable, a lost league is
    not.
    """

    updates = {
        str(getattr(p, "player_id", "") or ""): p
        for p in changed
        if str(getattr(p, "player_id", "") or "")
    }
    if not updates:
        return []

    target = _resolve_target(path)
    try:
        everyone = list(load_players_from_csv(target))
    except Exception:
        # A missing or unreadable file is exactly when writing "just the
        # change" would be destructive, so treat it the same as an empty read.
        everyone = []
    if not everyone:
        raise PlayersFileShrinkError(
            f"Refusing to update {len(updates)} player(s): {target} read back "
            "empty, so writing now would create a file containing only them."
        )

    merged = [updates.get(str(getattr(p, "player_id", "") or ""), p) for p in everyone]

    known = {str(getattr(p, "player_id", "") or "") for p in everyone}
    merged.extend(p for pid, p in updates.items() if pid not in known)

    return save_players(merged, path)


def invalidate_players(path: Path | str | None = None) -> None:
    """Invalidate cached players for *path* (or all players when omitted)."""

    service = get_unified_data_service()
    service.invalidate_players(path)


__all__ = [
    "PlayersFileShrinkError",
    "invalidate_players",
    "load_players",
    "save_players",
    "update_players",
]
