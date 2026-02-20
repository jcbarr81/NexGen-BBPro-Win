"""Persistence helpers for league-wide trade controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import csv
import json
from pathlib import Path
from typing import Dict, MutableMapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir
from utils.sim_date import get_current_sim_date

__all__ = [
    "TradeSettings",
    "DEFAULT_TRADES_ENABLED",
    "DEFAULT_DRAFT_PICK_TRADING_ENABLED",
    "DEFAULT_REQUIRE_COMMISSIONER_APPROVAL",
    "DEFAULT_MAX_PICK_TRADE_YEARS",
    "MAX_ALLOWED_PICK_TRADE_YEARS",
    "MIN_ALLOWED_PICK_TRADE_YEARS",
    "current_league_year",
    "load_trade_settings",
    "save_trade_settings",
    "update_trade_settings",
]

VERSION = 1

DEFAULT_TRADES_ENABLED = True
DEFAULT_DRAFT_PICK_TRADING_ENABLED = False
DEFAULT_REQUIRE_COMMISSIONER_APPROVAL = False
DEFAULT_MAX_PICK_TRADE_YEARS = 3
MIN_ALLOWED_PICK_TRADE_YEARS = 1
MAX_ALLOWED_PICK_TRADE_YEARS = 10


@dataclass
class TradeSettings:
    league_id: str
    trades_enabled: bool = DEFAULT_TRADES_ENABLED
    draft_pick_trading_enabled: bool = DEFAULT_DRAFT_PICK_TRADING_ENABLED
    require_commissioner_approval: bool = DEFAULT_REQUIRE_COMMISSIONER_APPROVAL
    max_pick_trade_years: int = DEFAULT_MAX_PICK_TRADE_YEARS

    def normalized(self) -> "TradeSettings":
        return TradeSettings(
            league_id=self.league_id or "league",
            trades_enabled=bool(self.trades_enabled),
            draft_pick_trading_enabled=bool(self.draft_pick_trading_enabled),
            require_commissioner_approval=bool(self.require_commissioner_approval),
            max_pick_trade_years=_normalize_max_years(self.max_pick_trade_years),
        )


def current_league_year() -> int:
    """Return the best-known current league year."""

    sim_date = str(get_current_sim_date() or "").strip()
    if sim_date:
        try:
            return int(sim_date.split("-")[0])
        except (TypeError, ValueError):
            pass

    sched = get_data_dir() / "schedule.csv"
    if sched.exists():
        try:
            with sched.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                first = next(reader, None)
            if first and first.get("date"):
                return int(str(first["date"]).split("-")[0])
        except Exception:
            pass

    return date.today().year


def load_trade_settings(
    path: Path | str | None = None,
    *,
    league_id: str | None = None,
) -> TradeSettings:
    payload = _load_payload(path=path)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    data = leagues.get(resolved_league_id, {})
    if not data and len(leagues) == 1:
        # Backward-compatible fallback for payloads keyed by a previous id.
        data = next(iter(leagues.values()), {})
    if not isinstance(data, dict):
        data = {}
    settings = TradeSettings(
        league_id=resolved_league_id,
        trades_enabled=bool(data.get("trades_enabled", DEFAULT_TRADES_ENABLED)),
        draft_pick_trading_enabled=bool(
            data.get(
                "draft_pick_trading_enabled",
                DEFAULT_DRAFT_PICK_TRADING_ENABLED,
            )
        ),
        require_commissioner_approval=bool(
            data.get(
                "require_commissioner_approval",
                DEFAULT_REQUIRE_COMMISSIONER_APPROVAL,
            )
        ),
        max_pick_trade_years=_normalize_max_years(
            data.get("max_pick_trade_years", DEFAULT_MAX_PICK_TRADE_YEARS)
        ),
    )
    return settings.normalized()


def save_trade_settings(
    settings: TradeSettings,
    path: Path | str | None = None,
    *,
    league_id: str | None = None,
) -> None:
    payload = _load_payload(path=path)
    leagues = payload.setdefault("leagues", {})
    normalized = settings.normalized()
    target_league_id = _normalize_league_id(league_id) or normalized.league_id
    leagues[target_league_id] = {
        "trades_enabled": normalized.trades_enabled,
        "draft_pick_trading_enabled": normalized.draft_pick_trading_enabled,
        "require_commissioner_approval": normalized.require_commissioner_approval,
        "max_pick_trade_years": normalized.max_pick_trade_years,
    }
    payload["version"] = VERSION
    _write_payload(payload, path=path)


def update_trade_settings(
    *,
    trades_enabled: bool | None = None,
    draft_pick_trading_enabled: bool | None = None,
    require_commissioner_approval: bool | None = None,
    max_pick_trade_years: int | None = None,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> TradeSettings:
    settings = load_trade_settings(path=path, league_id=league_id)
    if trades_enabled is not None:
        settings.trades_enabled = bool(trades_enabled)
    if draft_pick_trading_enabled is not None:
        settings.draft_pick_trading_enabled = bool(draft_pick_trading_enabled)
    if require_commissioner_approval is not None:
        settings.require_commissioner_approval = bool(require_commissioner_approval)
    if max_pick_trade_years is not None:
        settings.max_pick_trade_years = _normalize_max_years(max_pick_trade_years)
    save_trade_settings(settings, path=path, league_id=league_id)
    return settings.normalized()


def _normalize_max_years(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except Exception:
        return DEFAULT_MAX_PICK_TRADE_YEARS
    return max(MIN_ALLOWED_PICK_TRADE_YEARS, min(number, MAX_ALLOWED_PICK_TRADE_YEARS))


def _resolve_league_id() -> str:
    try:
        ctx = SeasonContext.load()
        league_id = ctx.league_id
        if league_id:
            return league_id
        return ctx.ensure_league()
    except Exception:
        return "league"


def _normalize_league_id(value: object) -> str:
    text = str(value or "").strip()
    return text or "league"


def _settings_path(path: Path | str | None = None) -> Path:
    return Path(path) if path is not None else (get_data_dir() / "trade_settings.json")


def _load_payload(path: Path | str | None = None) -> Dict[str, object]:
    settings_path = _settings_path(path)
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_payload(payload: MutableMapping[str, object], path: Path | str | None = None) -> None:
    settings_path = _settings_path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
