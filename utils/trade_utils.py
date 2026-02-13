import csv
from datetime import date
from pathlib import Path

from models.trade import Trade
from services.draft_pick_ledger import get_pick_owner, parse_pick_id
from services.trade_settings import current_league_year, load_trade_settings
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
                    give_player_ids=_split_ids(row.get("give_player_ids")),
                    receive_player_ids=_split_ids(row.get("receive_player_ids")),
                    status=str(row.get("status") or "pending"),
                    give_pick_ids=_split_pick_ids(row.get("give_pick_ids")),
                    receive_pick_ids=_split_pick_ids(row.get("receive_pick_ids")),
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

    if _today() > TRADE_DEADLINE and str(trade.status).lower() == "pending":
        raise RuntimeError("Trade deadline has passed")

    if str(trade.status).lower() == "pending":
        _validate_pending_trade(trade)

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
            "give_pick_ids",
            "receive_pick_ids",
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
                    "give_pick_ids": _join_pick_ids(getattr(t, "give_pick_ids", []) or []),
                    "receive_pick_ids": _join_pick_ids(getattr(t, "receive_pick_ids", []) or []),
                }
            )


def get_pending_trades(team_id: str, file_path: str | Path = "data/trades_pending.csv"):
    """Return trades awaiting response for ``team_id``."""

    path = _resolve(file_path)
    return [t for t in load_trades(path) if t.to_team == team_id and t.status == "pending"]


def _split_ids(raw_value: object) -> list[str]:
    if raw_value is None:
        return []
    text = str(raw_value).strip()
    if not text:
        return []
    return [item for item in text.split("|") if item]


def _split_pick_ids(raw_value: object) -> list[str]:
    if raw_value is None:
        return []
    text = str(raw_value).strip()
    if not text:
        return []
    if "," in text:
        return [item for item in text.split(",") if item]

    # Backward compatibility: an old serializer used "|" which conflicts with
    # the pick-id format itself (YYYY|R|TEAM). Reconstruct grouped tokens.
    tokens = [item for item in text.split("|") if item]
    if len(tokens) == 3:
        return ["|".join(tokens)]
    if len(tokens) > 3 and len(tokens) % 3 == 0:
        rebuilt = []
        for idx in range(0, len(tokens), 3):
            rebuilt.append("|".join(tokens[idx : idx + 3]))
        return rebuilt
    return [text]


def _join_pick_ids(pick_ids: list[str]) -> str:
    return ",".join(str(pid) for pid in pick_ids if str(pid).strip())


def _validate_pending_trade(trade: Trade) -> None:
    settings = load_trade_settings()

    if not settings.trades_enabled:
        raise RuntimeError("Trading is currently disabled by the commissioner.")

    give_players = list(getattr(trade, "give_player_ids", []) or [])
    recv_players = list(getattr(trade, "receive_player_ids", []) or [])
    give_picks = list(getattr(trade, "give_pick_ids", []) or [])
    recv_picks = list(getattr(trade, "receive_pick_ids", []) or [])

    if not give_players and not give_picks:
        raise RuntimeError("The proposing team must send at least one player or draft pick.")
    if not recv_players and not recv_picks:
        raise RuntimeError("The receiving team must send at least one player or draft pick.")

    includes_picks = bool(give_picks or recv_picks)
    if includes_picks and not settings.draft_pick_trading_enabled:
        raise RuntimeError("Draft pick trading is currently disabled by the commissioner.")

    if includes_picks:
        try:
            _validate_pick_year_window(give_picks + recv_picks, settings.max_pick_trade_years)
            _validate_pick_ownership(give_picks, trade.from_team)
            _validate_pick_ownership(recv_picks, trade.to_team)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc


def _validate_pick_year_window(pick_ids: list[str], max_years: int) -> None:
    current_year = current_league_year()
    latest_year = current_year + max(1, int(max_years))
    earliest_year = current_year + 1
    for pick_id in pick_ids:
        year, _round_no, _original_team = parse_pick_id(pick_id)
        if year < earliest_year or year > latest_year:
            raise RuntimeError(
                f"{pick_id} is outside the allowed trade window ({earliest_year}-{latest_year})."
            )


def _validate_pick_ownership(pick_ids: list[str], expected_owner: str) -> None:
    for pick_id in pick_ids:
        year, round_no, original_team = parse_pick_id(pick_id)
        owner = get_pick_owner(year, round_no, original_team)
        if owner != expected_owner:
            raise RuntimeError(
                f"{pick_id} is owned by {owner}, not {expected_owner}."
            )
