"""Major-league service time, per player (8.5.1).

Service time used to live only on the contract (``service_time_days``) and
only grew inside the offseason arbitration step, which a league with the
arbitration module off (alpha-test's "simple" finance preset) never runs; a
contract that expired was deleted with its service, and every new contract
started at 0. Both live leagues read 0 days on every contract, so every
player priced, and was treated, as a rookie.

Now service time belongs to the player, in ``service_time.json``:

* **Accrual.** Each played regular-season date credits every player on a
  major-league level of any club -- the active roster or an injured list
  (MLB counts both) -- once (``credit_played_date``, from the daily
  automations). At the rollover the season closes (``close_season``): each
  player gets ``172 x credited dates / the season's dates`` days, at most a
  full season (172), whatever the finance modules are.
* **Contracts mirror it.** ``close_season`` writes every contract's
  ``service_time_days`` from the ledger, and a new contract takes the
  player's ledger figure (``contracts_service.upsert_contract``), so every
  existing reader keeps reading the contract.
* **Back-fill** (``scripts/backfill_service_time.py``, owner's calls
  2026-10-25): a league's first-season big leaguers get one season per year
  past 22 (at most 15) for their careers before the league began, and each
  completed season is credited by big-league playing time
  (:func:`playing_time_days`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

_LOGGER = logging.getLogger(__name__)

FILENAME = "service_time.json"
FULL_SEASON_DAYS = 172
MLB_LEVELS = {"ACT", "DL", "DL15", "DL45", "IR"}
# Back-fill: a full season of playing time.
FULL_SEASON_HITTER_GAMES = 140
FULL_SEASON_STARTS = 28
FULL_SEASON_RELIEF_GAMES = 55
PRE_LEAGUE_FROM_AGE = 22
PRE_LEAGUE_MAX_SEASONS = 15


def _base(data_dir: Path | str | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    from utils.path_utils import get_data_dir

    return Path(get_data_dir())


def load(data_dir: Path | str | None = None) -> Dict[str, Any]:
    """The ledger. A league without one starts from the service its
    contracts already carry (a league whose arbitration step accrued it)."""

    base = _base(data_dir)
    try:
        data = json.loads((base / FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"players": _from_contracts(base)}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("players", {})
    data.setdefault("season", {"dates": [], "credit": {}})
    return data


def _from_contracts(base: Path) -> Dict[str, int]:
    try:
        from services.contracts_service import load_contracts_payload

        players = load_contracts_payload(data_dir=base).get("players") or {}
    except Exception:
        return {}
    out: Dict[str, int] = {}
    for pid, contract in players.items():
        if isinstance(contract, Mapping):
            days = int(contract.get("service_time_days", 0) or 0)
            if days > 0:
                out[str(pid)] = days
    return out


def save(ledger: Mapping[str, Any], data_dir: Path | str | None = None) -> None:
    from utils.atomic_write import atomic_text_writer

    with atomic_text_writer(_base(data_dir) / FILENAME, encoding="utf-8") as fh:
        fh.write(json.dumps(ledger, indent=1, sort_keys=True))


def exists(data_dir: Path | str | None = None) -> bool:
    return (_base(data_dir) / FILENAME).exists()


def service_days(player_id: str, data_dir: Path | str | None = None) -> int:
    """The player's service time in days (0 when he has none)."""

    return int(load(data_dir)["players"].get(str(player_id), 0) or 0)


def _mlb_players(base: Path) -> Iterable[str]:
    import csv

    for path in sorted((base / "rosters").glob("*.csv")):
        if path.stem.endswith("_pitching"):
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 2 and row[0].strip() and row[1].strip().upper() in MLB_LEVELS:
                        yield row[0].strip()
        except OSError:
            continue


def credit_played_date(played_date: str, *, phase: Optional[str],
                       data_dir: Path | str | None = None) -> int:
    """Credit one regular-season date to every major leaguer; once per
    date. Returns how many players were credited."""

    if str(phase or "").upper() != "REGULAR_SEASON":
        return 0
    date = str(played_date or "")[:10]
    if not date:
        return 0
    base = _base(data_dir)
    ledger = load(base)
    season = ledger["season"]
    if date in season["dates"]:
        return 0
    season["dates"].append(date)
    credit = season["credit"]
    n = 0
    for pid in set(_mlb_players(base)):
        credit[pid] = int(credit.get(pid, 0)) + 1
        n += 1
    save(ledger, base)
    return n


def close_season(data_dir: Path | str | None = None) -> Dict[str, Any]:
    """Turn the season's credited dates into service days, start the next
    season empty, and write every contract's ``service_time_days`` from
    the ledger. Run at the rollover, before arbitration reads it."""

    base = _base(data_dir)
    ledger = load(base)
    season = ledger["season"]
    dates = len(season["dates"])
    added = 0
    if dates:
        for pid, n in season["credit"].items():
            days = min(FULL_SEASON_DAYS, round(FULL_SEASON_DAYS * int(n) / dates))
            if days > 0:
                ledger["players"][pid] = int(ledger["players"].get(pid, 0)) + days
                added += 1
    ledger["season"] = {"dates": [], "credit": {}}
    save(ledger, base)
    synced = sync_contracts(base, ledger)
    return {"season_dates": dates, "players_credited": added, "contracts_synced": synced}


def sync_contracts(data_dir: Path | str | None = None,
                   ledger: Optional[Mapping[str, Any]] = None) -> int:
    """Set every contract's ``service_time_days`` from the ledger."""

    from services.contracts_service import load_contracts_payload, save_contracts_payload

    base = _base(data_dir)
    ledger = ledger or load(base)
    days = ledger["players"]
    payload = load_contracts_payload(data_dir=base)
    players = payload.get("players")
    if not isinstance(players, dict):
        return 0
    changed = 0
    for pid, contract in players.items():
        if not isinstance(contract, dict):
            continue
        want = int(days.get(str(pid), 0) or 0)
        if int(contract.get("service_time_days", 0) or 0) != want:
            contract["service_time_days"] = want
            changed += 1
    if changed:
        save_contracts_payload(payload, data_dir=base)
    return changed


# ---------------------------------------------------------------------------
# Back-fill


def playing_time_share(line: Mapping[str, Any]) -> float:
    """How much of a full big-league season one stat line is (0..1)."""

    g = float(line.get("g") or 0)
    gs = float(line.get("gs") or 0)
    pitcher = bool(line.get("outs") or line.get("ip") or line.get("bf"))
    if pitcher:
        share = gs / FULL_SEASON_STARTS + max(0.0, g - gs) / FULL_SEASON_RELIEF_GAMES
    else:
        share = g / FULL_SEASON_HITTER_GAMES
    return max(0.0, min(1.0, share))


def playing_time_days(line: Mapping[str, Any]) -> int:
    return round(FULL_SEASON_DAYS * playing_time_share(line))


def seed_new_league(data_dir: Path | str | None = None, *,
                    season_year: Optional[int] = None) -> int:
    """A new league's ledger: every player on an active roster gets
    :func:`pre_league_days` for his age. Only when there is no ledger yet.
    Returns how many players got service."""

    base = _base(data_dir)
    if exists(base):
        return 0
    import csv

    from services.contracts_service import _player_age
    from utils.player_loader import load_players_from_csv

    try:
        players = {str(p.player_id): p for p in load_players_from_csv(str(base / "players.csv"))}
    except Exception:
        players = {}
    ledger = load(base)
    n = 0
    for path in sorted((base / "rosters").glob("*.csv")):
        if path.stem.endswith("_pitching"):
            continue
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) < 2 or row[1].strip().upper() != "ACT":
                    continue
                pid = row[0].strip()
                days = pre_league_days(_player_age(players.get(pid), season_year=season_year))
                if days:
                    ledger["players"][pid] = days
                    n += 1
    save(ledger, base)
    sync_contracts(base, ledger)
    return n


def pre_league_days(age: Optional[int]) -> int:
    if age is None:
        return 0
    seasons = max(0, min(PRE_LEAGUE_MAX_SEASONS, int(age) - PRE_LEAGUE_FROM_AGE))
    return seasons * FULL_SEASON_DAYS
