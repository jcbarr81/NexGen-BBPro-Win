from __future__ import annotations

"""Utility helpers for recording and reading team transactions."""

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.sim_date import get_current_sim_date
from services.unified_data_service import get_unified_data_service


TRANSACTION_COLUMNS = [
    "timestamp",
    "season_date",
    "team_id",
    "player_id",
    "player_name",
    "action",
    "from_level",
    "to_level",
    "counterparty",
    "details",
]

_PLAYER_NAME_CACHE: dict[Path, dict[str, str]] = {}
_TRANSACTIONS_TOPIC = "transactions"


def _transactions_path() -> Path:
    return get_data_dir() / "transactions.csv"


def _ensure_path(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(TRANSACTION_COLUMNS)


def _player_name(pid: str) -> str:
    players_path = (get_data_dir() / "players.csv").resolve(strict=False)
    names = _PLAYER_NAME_CACHE.get(players_path)
    if names is None:
        try:
            players = load_players_from_csv(str(players_path))
        except Exception:
            players = []
        names = {
            p.player_id: f"{p.first_name} {p.last_name}".strip()
            for p in players
        }
        _PLAYER_NAME_CACHE[players_path] = names
    return names.get(pid, pid)


def reset_player_cache() -> None:
    """Clear cached player name lookups (e.g., after adding new players)."""

    _PLAYER_NAME_CACHE.clear()


def _read_transactions(path: Path) -> List[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def record_transaction(
    *,
    action: str,
    team_id: str,
    player_id: str,
    player_name: str | None = None,
    from_level: str | None = None,
    to_level: str | None = None,
    counterparty: str | None = None,
    details: str | None = None,
    season_date: str | None = None,
    timestamp: datetime | None = None,
    path: Path | None = None,
) -> None:
    """Append a transaction entry for *team_id* related to *player_id*."""

    target_path = path or _transactions_path()
    _ensure_path(target_path)
    stamp = timestamp or datetime.now()
    ts_str = stamp.strftime("%Y-%m-%d %H:%M:%S")
    season_val = season_date if season_date is not None else get_current_sim_date()
    row = {
        "timestamp": ts_str,
        "season_date": season_val or "",
        "team_id": team_id,
        "player_id": player_id,
        "player_name": player_name or _player_name(player_id),
        "action": action,
        "from_level": from_level or "",
        "to_level": to_level or "",
        "counterparty": counterparty or "",
        "details": details or "",
    }
    with target_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRANSACTION_COLUMNS)
        writer.writerow(row)
    service = get_unified_data_service()
    try:
        cached = service.get_document(target_path, _read_transactions, topic=_TRANSACTIONS_TOPIC)
    except Exception:
        service.invalidate_document(target_path, topic=_TRANSACTIONS_TOPIC)
        return
    if not cached or cached[-1] != row:
        cached.append(dict(row))
    service.update_document(target_path, cached, topic=_TRANSACTIONS_TOPIC)


def load_transactions(
    *,
    team_id: str | None = None,
    actions: Iterable[str] | None = None,
    limit: int | None = None,
    path: Path | None = None,
) -> List[dict[str, str]]:
    """Return recorded transactions, optionally filtered by team/action."""

    target_path = path or _transactions_path()
    service = get_unified_data_service()
    rows = service.get_document(target_path, _read_transactions, topic=_TRANSACTIONS_TOPIC)
    rows.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
    if team_id:
        rows = [row for row in rows if row.get("team_id") == team_id]
    if actions:
        wanted = {a.lower() for a in actions}
        rows = [row for row in rows if row.get("action", "").lower() in wanted]
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


def clear_transactions(*, path: Path | None = None) -> None:
    """Reset transactions to an empty file with just the CSV header."""

    target_path = path or _transactions_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRANSACTION_COLUMNS)
        writer.writeheader()
    service = get_unified_data_service()
    service.update_document(target_path, [], topic=_TRANSACTIONS_TOPIC)


__all__ = [
    "record_transaction",
    "load_transactions",
    "clear_transactions",
    "reset_player_cache",
]
