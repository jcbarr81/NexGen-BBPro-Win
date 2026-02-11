import csv
from datetime import date
from pathlib import Path

from models.trade import Trade
from utils.path_utils import resolve_app_path
from playbalance.season_manager import TRADE_DEADLINE


def _today() -> date:
    return date.today()


def _resolve(file_path: str | Path) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path
    return resolve_app_path(path)


def load_trades(file_path: str | Path = "data/trades_pending.csv"):
    path = _resolve(file_path)
    trades = []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trade = Trade(
                    trade_id=row["trade_id"],
                    from_team=row["from_team"],
                    to_team=row["to_team"],
                    give_player_ids=row["give_player_ids"].split("|"),
                    receive_player_ids=row["receive_player_ids"].split("|"),
                    status=row["status"],
                )
                trades.append(trade)
    except FileNotFoundError:
        pass
    return trades


def save_trade(trade: Trade, file_path: str | Path = "data/trades_pending.csv"):
    """Save ``trade`` to ``file_path`` replacing any existing entry.

    The previous implementation always appended a trade, which caused
    duplicates whenever a trade was updated (e.g. when an owner accepted or
    rejected a proposal).  We now remove any trade with the same ``trade_id``
    before writing the updated list back to disk.
    """

    if _today() > TRADE_DEADLINE:
        raise RuntimeError("Trade deadline has passed")

    path = _resolve(file_path)
    existing = [t for t in load_trades(path) if t.trade_id != trade.trade_id]
    existing.append(trade)
    with path.open("w", newline="") as f:
        fieldnames = [
            "trade_id",
            "from_team",
            "to_team",
            "give_player_ids",
            "receive_player_ids",
            "status",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in existing:
            writer.writerow(
                {
                    "trade_id": t.trade_id,
                    "from_team": t.from_team,
                    "to_team": t.to_team,
                    "give_player_ids": "|".join(t.give_player_ids),
                    "receive_player_ids": "|".join(t.receive_player_ids),
                    "status": t.status,
                }
            )


def get_pending_trades(team_id: str, file_path: str | Path = "data/trades_pending.csv"):
    """Return trades awaiting response for ``team_id``."""

    path = _resolve(file_path)
    return [t for t in load_trades(path) if t.to_team == team_id and t.status == "pending"]
