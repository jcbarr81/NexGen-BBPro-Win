"""Contract lifecycle helpers for basic payroll/finance workflows."""

from __future__ import annotations

import csv
from datetime import date, datetime
import json
from pathlib import Path
from typing import Dict, Mapping

from playbalance.season_context import SeasonContext
from services.finance_ledger import post_contract_buyout
from utils.path_utils import get_data_dir

__all__ = [
    "CONTRACTS_VERSION",
    "DEFAULT_CONTRACT_YEARS",
    "DEFAULT_MIN_SALARY",
    "load_contracts_payload",
    "save_contracts_payload",
    "get_contract",
    "upsert_contract",
    "sign_free_agent_contract",
    "transfer_contract",
    "transfer_contracts",
    "remove_contract",
    "release_contracts_to_free_agency",
    "rollover_contracts_for_new_season",
    "extend_contract",
    "set_contract_option_decision",
    "contract_payroll_value",
    "estimate_salary_for_player",
]

CONTRACTS_VERSION = 1
DEFAULT_CONTRACT_YEARS = 1
DEFAULT_MIN_SALARY = 800_000
MAX_ESTIMATED_SALARY = 35_000_000
def load_contracts_payload(*, data_dir: Path | str | None = None) -> Dict[str, object]:
    """Load ``contracts.json`` for the current league."""

    path = _contracts_path(data_dir=data_dir)
    if not path.exists():
        return {"version": CONTRACTS_VERSION, "players": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": CONTRACTS_VERSION, "players": {}}
    if not isinstance(payload, dict):
        return {"version": CONTRACTS_VERSION, "players": {}}
    players = payload.get("players")
    if not isinstance(players, Mapping):
        payload["players"] = {}
    payload["version"] = CONTRACTS_VERSION
    return payload


def save_contracts_payload(
    payload: Mapping[str, object],
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Persist a normalized contracts payload."""

    normalized = {"version": CONTRACTS_VERSION, "players": {}}
    players = payload.get("players") if isinstance(payload, Mapping) else None
    if isinstance(players, Mapping):
        normalized_players: Dict[str, Dict[str, object]] = {}
        for player_id, contract in players.items():
            pid = str(player_id or "").strip()
            if not pid:
                continue
            normalized_players[pid] = _normalize_contract(contract)
        normalized["players"] = normalized_players
    path = _contracts_path(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return normalized


def get_contract(
    player_id: str,
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, object] | None:
    """Return a normalized contract for *player_id* when present."""

    pid = str(player_id or "").strip()
    if not pid:
        return None
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, Mapping):
        return None
    contract = players.get(pid)
    if not isinstance(contract, Mapping):
        return None
    return _normalize_contract(contract)


def upsert_contract(
    player_id: str,
    *,
    team_id: str,
    annual_salary: int,
    years_left: int = DEFAULT_CONTRACT_YEARS,
    season_year: int | None = None,
    service_time_days: int = 0,
    arb_eligible: bool = False,
    guaranteed: bool = True,
    buyout_guarantee: int = 0,
    options: list[object] | None = None,
    incentives: list[object] | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Create or update a player's contract entry and persist it."""

    pid = str(player_id or "").strip()
    clean_team = str(team_id or "").strip()
    if not pid:
        raise ValueError("player_id is required")
    if not clean_team:
        raise ValueError("team_id is required")

    resolved_year = _resolve_season_year(data_dir=data_dir, season_year=season_year)
    clean_years = max(1, int(years_left))
    clean_salary = max(DEFAULT_MIN_SALARY, int(round(float(annual_salary))))
    contract = {
        "team_id": clean_team,
        "years_left": clean_years,
        "annual_salary": clean_salary,
        "service_time_days": max(0, int(service_time_days)),
        "arb_eligible": bool(arb_eligible),
        "fa_year": resolved_year + clean_years,
        "guaranteed": bool(guaranteed),
        "buyout_guarantee": max(0, int(round(_safe_number(buyout_guarantee)))),
        "options": list(options or []),
        "incentives": list(incentives or []),
    }

    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        players = {}
        payload["players"] = players
    players[pid] = contract
    save_contracts_payload(payload, data_dir=data_dir)
    return _normalize_contract(contract)


def sign_free_agent_contract(
    player_id: str,
    team_id: str,
    *,
    years_left: int = DEFAULT_CONTRACT_YEARS,
    annual_salary: int | None = None,
    options: list[object] | None = None,
    incentives: list[object] | None = None,
    player: object | None = None,
    season_year: int | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Create a default contract for a newly signed free agent."""

    salary = annual_salary
    if salary is None:
        salary = estimate_salary_for_player(player)
    return upsert_contract(
        player_id,
        team_id=team_id,
        annual_salary=max(DEFAULT_MIN_SALARY, int(salary)),
        years_left=years_left,
        options=options,
        incentives=incentives,
        season_year=season_year,
        data_dir=data_dir,
    )


def transfer_contract(
    player_id: str,
    to_team_id: str,
    *,
    player: object | None = None,
    create_if_missing: bool = True,
    season_year: int | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object] | None:
    """Transfer a contract to *to_team_id* after a roster move/trade."""

    pid = str(player_id or "").strip()
    clean_team = str(to_team_id or "").strip()
    if not pid or not clean_team:
        return None

    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        players = {}
        payload["players"] = players

    current = players.get(pid)
    if isinstance(current, Mapping):
        normalized = _normalize_contract(current)
        normalized["team_id"] = clean_team
        players[pid] = normalized
        save_contracts_payload(payload, data_dir=data_dir)
        return normalized

    if not create_if_missing:
        return None
    return sign_free_agent_contract(
        pid,
        clean_team,
        player=player,
        season_year=season_year,
        data_dir=data_dir,
    )


def transfer_contracts(
    player_ids: list[str] | tuple[str, ...],
    to_team_id: str,
    *,
    players_by_id: Mapping[str, object] | None = None,
    create_if_missing: bool = True,
    season_year: int | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, Dict[str, object]]:
    """Transfer multiple player contracts and return updated entries."""

    updated: Dict[str, Dict[str, object]] = {}
    source_players = players_by_id if isinstance(players_by_id, Mapping) else {}
    for raw_id in player_ids:
        pid = str(raw_id or "").strip()
        if not pid:
            continue
        contract = transfer_contract(
            pid,
            to_team_id,
            player=source_players.get(pid),
            create_if_missing=create_if_missing,
            season_year=season_year,
            data_dir=data_dir,
        )
        if contract is not None:
            updated[pid] = contract
    return updated


def remove_contract(
    player_id: str,
    *,
    data_dir: Path | str | None = None,
) -> bool:
    """Delete a player's contract entry."""

    pid = str(player_id or "").strip()
    if not pid:
        return False
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        return False
    if pid not in players:
        return False
    del players[pid]
    save_contracts_payload(payload, data_dir=data_dir)
    return True


def extend_contract(
    player_id: str,
    *,
    additional_years: int = 1,
    annual_salary: int | None = None,
    guaranteed: bool | None = None,
    buyout_guarantee: int | None = None,
    options: list[object] | None = None,
    incentives: list[object] | None = None,
    season_year: int | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object] | None:
    """Extend an existing contract or update advanced terms."""

    pid = str(player_id or "").strip()
    if not pid:
        return None
    bump_years = max(0, int(additional_years))
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        return None
    raw = players.get(pid)
    if not isinstance(raw, Mapping):
        return None
    contract = _normalize_contract(raw)
    contract["years_left"] = max(1, int(contract.get("years_left", 1))) + bump_years
    if annual_salary is not None:
        contract["annual_salary"] = max(DEFAULT_MIN_SALARY, int(round(float(annual_salary))))
    if guaranteed is not None:
        contract["guaranteed"] = bool(guaranteed)
    if buyout_guarantee is not None:
        contract["buyout_guarantee"] = max(
            0,
            int(round(_safe_number(buyout_guarantee))),
        )
    if options is not None:
        contract["options"] = _normalize_options(options)
    if incentives is not None:
        contract["incentives"] = _normalize_incentives(incentives)
    resolved_year = _resolve_season_year(data_dir=data_dir, season_year=season_year)
    contract["fa_year"] = resolved_year + int(contract["years_left"])
    players[pid] = contract
    save_contracts_payload(payload, data_dir=data_dir)
    return _normalize_contract(contract)


def set_contract_option_decision(
    player_id: str,
    *,
    decision: str,
    option_index: int = 0,
    data_dir: Path | str | None = None,
) -> Dict[str, object] | None:
    """Set a contract option decision for a player's contract."""

    pid = str(player_id or "").strip()
    if not pid:
        return None
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        return None
    raw = players.get(pid)
    if not isinstance(raw, Mapping):
        return None
    contract = _normalize_contract(raw)
    options = list(contract.get("options") or [])
    if option_index < 0 or option_index >= len(options):
        return None
    option = options[option_index]
    if not isinstance(option, Mapping):
        return None
    updated = _normalize_option(
        {
            **dict(option),
            "decision": decision,
        }
    )
    options[option_index] = updated
    contract["options"] = options
    players[pid] = contract
    save_contracts_payload(payload, data_dir=data_dir)
    return _normalize_contract(contract)


def contract_payroll_value(
    contract: Mapping[str, object] | object,
    *,
    include_expected_incentives: bool = True,
) -> int:
    """Return annual payroll value for a contract, including incentives."""

    payload = contract if isinstance(contract, Mapping) else {}
    salary = int(round(_safe_number(payload.get("annual_salary", DEFAULT_MIN_SALARY))))
    total = salary if salary > 0 else DEFAULT_MIN_SALARY
    if not include_expected_incentives:
        return total
    incentives = _normalize_incentives(payload.get("incentives"))
    for raw in incentives:
        total += max(0, int(_safe_number(raw.get("expected_payout", 0))))
    return total


def release_contracts_to_free_agency(
    player_ids: list[str] | tuple[str, ...],
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Remove contract entries and release players from roster files."""

    ids = [str(player_id or "").strip() for player_id in player_ids]
    ids = [player_id for player_id in ids if player_id]
    if not ids:
        return {
            "released_contracts": 0,
            "released_from_rosters": 0,
            "release_teams": [],
        }

    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        players = {}
        payload["players"] = players

    removed_contracts = 0
    for player_id in ids:
        if player_id in players:
            del players[player_id]
            removed_contracts += 1
    save_contracts_payload(payload, data_dir=data_dir)
    release_summary = _release_players_from_rosters(ids, data_dir=data_dir)
    return {
        "released_contracts": removed_contracts,
        "released_from_rosters": int(release_summary.get("released_count", 0)),
        "release_teams": list(release_summary.get("teams", [])),
    }


def rollover_contracts_for_new_season(
    *,
    season_year: int | None = None,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Advance contract state by one offseason.

    Contracts with no remaining years after decrement are removed, which
    effectively marks those players as free agents for payroll purposes.
    """

    target_year = _resolve_season_year(data_dir=data_dir, season_year=season_year)
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, Mapping):
        save_contracts_payload(payload, data_dir=data_dir)
        return {
            "season_year": target_year,
            "processed": 0,
            "retained": 0,
            "expired": 0,
            "expired_player_ids": [],
        }

    updated_players: Dict[str, Dict[str, object]] = {}
    expired_ids: list[str] = []
    option_exercised = 0
    option_declined = 0
    buyout_total = 0
    buyout_rows: list[tuple[str, int, str, int, str]] = []
    for raw_player_id, raw_contract in players.items():
        player_id = str(raw_player_id or "").strip()
        if not player_id:
            continue
        contract = _normalize_contract(raw_contract)
        remaining_years = int(contract.get("years_left", DEFAULT_CONTRACT_YEARS)) - 1
        if remaining_years <= 0:
            options = contract.get("options")
            option = options[0] if isinstance(options, list) and options else None
            if isinstance(option, Mapping) and _option_exercised(option):
                exercised = _contract_from_exercised_option(
                    contract,
                    option=option,
                    target_year=target_year,
                )
                updated_players[player_id] = exercised
                option_exercised += 1
                continue
            if isinstance(option, Mapping):
                option_declined += 1
                buyout = max(0, int(_safe_number(option.get("buyout", 0))))
                if buyout > 0:
                    buyout_total += buyout
                    team_id = str(contract.get("team_id") or "").strip()
                    buyout_rows.append(
                        (
                            team_id,
                            buyout,
                            player_id,
                            target_year,
                            f"Option buyout ({str(option.get('type') or 'team')})",
                        )
                    )
            expired_ids.append(player_id)
            continue

        contract["years_left"] = remaining_years
        contract["fa_year"] = target_year + remaining_years
        contract["incentives"] = _reset_incentives_for_new_year(contract.get("incentives"))
        updated_players[player_id] = contract

    payload["players"] = updated_players
    save_contracts_payload(payload, data_dir=data_dir)
    if buyout_rows:
        _append_finance_buyout_rows(data_dir=data_dir, rows=buyout_rows)
    release_summary = _release_players_from_rosters(
        expired_ids,
        data_dir=data_dir,
    )
    return {
        "season_year": target_year,
        "processed": len(updated_players) + len(expired_ids),
        "retained": len(updated_players),
        "expired": len(expired_ids),
        "expired_player_ids": expired_ids,
        "released_from_rosters": int(release_summary.get("released_count", 0)),
        "release_teams": list(release_summary.get("teams", [])),
        "option_exercised": option_exercised,
        "option_declined": option_declined,
        "buyout_total": buyout_total,
    }


def estimate_salary_for_player(player: object | None) -> int:
    """Estimate a default annual salary from core rating attributes."""

    if player is None:
        return DEFAULT_MIN_SALARY
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).strip().upper() == "P"

    if is_pitcher:
        values = [
            _safe_number(getattr(player, "arm", 0)),
            _safe_number(getattr(player, "control", 0)),
            _safe_number(getattr(player, "movement", 0)),
            _safe_number(getattr(player, "endurance", 0)),
        ]
    else:
        values = [
            _safe_number(getattr(player, "ch", 0)),
            _safe_number(getattr(player, "ph", 0)),
            _safe_number(getattr(player, "sp", 0)),
            _safe_number(getattr(player, "eye", 0)),
            _safe_number(getattr(player, "fa", 0)),
            _safe_number(getattr(player, "arm", 0)),
        ]
    values = [value for value in values if value > 0]
    if not values:
        return DEFAULT_MIN_SALARY
    overall = sum(values) / len(values)
    salary = DEFAULT_MIN_SALARY + max(0, int(round(overall)) - 40) * 35_000
    return max(DEFAULT_MIN_SALARY, min(MAX_ESTIMATED_SALARY, int(salary)))


def _contracts_path(*, data_dir: Path | str | None = None) -> Path:
    if data_dir is None:
        return get_data_dir() / "contracts.json"
    return Path(data_dir) / "contracts.json"


def _release_players_from_rosters(
    player_ids: list[str],
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Remove expired-contract players from roster CSV files."""

    player_set = {str(player_id or "").strip() for player_id in player_ids}
    player_set.discard("")
    if not player_set:
        return {"released_count": 0, "teams": []}

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    roster_dir = resolved_data_dir / "rosters"
    if not roster_dir.exists():
        return {"released_count": 0, "teams": []}

    released_count = 0
    teams: set[str] = set()
    transactions_path = resolved_data_dir / "transactions.csv"

    try:
        from services.transaction_log import record_transaction
    except Exception:
        record_transaction = None

    for roster_path in sorted(roster_dir.glob("*.csv")):
        team_id = roster_path.stem
        kept_rows: list[list[str]] = []
        removed_rows: list[tuple[str, str]] = []
        try:
            with roster_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    if len(row) < 2:
                        kept_rows.append(row)
                        continue
                    player_id = str(row[0] or "").strip()
                    level = str(row[1] or "").strip().upper()
                    if player_id in player_set:
                        removed_rows.append((player_id, level))
                        continue
                    kept_rows.append(row)
        except OSError:
            continue

        if not removed_rows:
            continue

        try:
            roster_path.chmod(0o644)
        except OSError:
            pass

        try:
            with roster_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerows(kept_rows)
        except OSError:
            continue

        teams.add(team_id)
        released_count += len(removed_rows)
        if callable(record_transaction):
            for player_id, level in removed_rows:
                try:
                    record_transaction(
                        action="contract_expired",
                        team_id=team_id,
                        player_id=player_id,
                        from_level=level,
                        to_level="FA",
                        details="Contract expired; released to free agency",
                        path=transactions_path,
                    )
                except Exception:
                    pass

    try:
        from utils.roster_loader import load_roster

        load_roster.cache_clear()
    except Exception:
        pass

    return {
        "released_count": released_count,
        "teams": sorted(teams),
    }


def _resolve_season_year(
    *,
    data_dir: Path | str | None = None,
    season_year: int | None = None,
) -> int:
    if season_year is not None:
        try:
            return int(season_year)
        except Exception:
            pass
    try:
        if data_dir is None:
            ctx = SeasonContext.load()
        else:
            ctx = SeasonContext.load(path=Path(data_dir) / "career_index.json")
        raw = (ctx.current or {}).get("league_year")
        if raw is not None:
            return int(raw)
    except Exception:
        pass
    return date.today().year


def _safe_number(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _normalize_option(raw: object) -> Dict[str, object]:
    payload = raw if isinstance(raw, Mapping) else {}
    option_type = str(payload.get("type") or "team").strip().lower()
    if option_type not in {"team", "player", "mutual", "vesting"}:
        option_type = "team"
    decision = str(payload.get("decision") or "pending").strip().lower()
    if decision in {"exercise", "exercised"}:
        decision = "exercised"
    elif decision in {"decline", "declined"}:
        decision = "declined"
    else:
        decision = "pending"
    salary = max(DEFAULT_MIN_SALARY, int(round(_safe_number(payload.get("salary", DEFAULT_MIN_SALARY)))))
    buyout = max(0, int(round(_safe_number(payload.get("buyout", 0)))))
    return {
        "type": option_type,
        "label": str(payload.get("label") or "").strip(),
        "salary": salary,
        "buyout": buyout,
        "decision": decision,
    }


def _normalize_options(raw: object) -> list[Dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [
        _normalize_option(item)
        for item in raw
        if isinstance(item, Mapping)
    ]


def _normalize_incentive(raw: object) -> Dict[str, object]:
    payload = raw if isinstance(raw, Mapping) else {}
    amount = max(0, int(round(_safe_number(payload.get("amount", 0)))))
    status = str(payload.get("status") or "pending").strip().lower()
    if status not in {"pending", "earned", "void", "guaranteed"}:
        status = "pending"
    if status == "earned" or status == "guaranteed":
        expected_payout = amount
        expected_probability = 1.0
    else:
        try:
            expected_probability = float(payload.get("expected_probability", 0.25))
        except Exception:
            expected_probability = 0.25
        expected_probability = max(0.0, min(1.0, expected_probability))
        expected_payout = max(
            0,
            int(round(_safe_number(payload.get("expected_payout", amount * expected_probability)))),
        )
    return {
        "label": str(payload.get("label") or "").strip(),
        "amount": amount,
        "status": status,
        "expected_probability": expected_probability,
        "expected_payout": expected_payout,
    }


def _normalize_incentives(raw: object) -> list[Dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [
        _normalize_incentive(item)
        for item in raw
        if isinstance(item, Mapping)
    ]


def _option_exercised(option: Mapping[str, object]) -> bool:
    decision = str(option.get("decision") or "").strip().lower()
    return decision in {"exercise", "exercised"}


def _contract_from_exercised_option(
    contract: Mapping[str, object],
    *,
    option: Mapping[str, object],
    target_year: int,
) -> Dict[str, object]:
    base = _normalize_contract(contract)
    remaining_options = [
        _normalize_option(item)
        for item in (base.get("options") or [])[1:]
        if isinstance(item, Mapping)
    ]
    base["years_left"] = 1
    base["annual_salary"] = max(
        DEFAULT_MIN_SALARY,
        int(round(_safe_number(option.get("salary", base.get("annual_salary", DEFAULT_MIN_SALARY))))),
    )
    base["fa_year"] = target_year + 1
    base["options"] = remaining_options
    base["incentives"] = _reset_incentives_for_new_year(base.get("incentives"))
    return base


def _reset_incentives_for_new_year(raw: object) -> list[Dict[str, object]]:
    incentives = _normalize_incentives(raw)
    reset: list[Dict[str, object]] = []
    for item in incentives:
        if str(item.get("status") or "").strip().lower() in {"earned", "void"}:
            item = dict(item)
            item["status"] = "pending"
            item["expected_payout"] = max(
                0,
                int(round(_safe_number(item.get("amount", 0)) * float(item.get("expected_probability", 0.25)))),
            )
        reset.append(item)
    return reset


def _append_finance_buyout_rows(
    *,
    data_dir: Path | str | None,
    rows: list[tuple[str, int, str, int, str]],
) -> None:
    if not rows:
        return
    for team_id, amount, player_id, season_year, detail in rows:
        post_contract_buyout(
            team_id=str(team_id or "").strip(),
            season_year=int(season_year),
            player_id=str(player_id or "").strip(),
            buyout_amount=int(amount),
            detail=str(detail or "").strip(),
            timestamp=_timestamp(),
            data_dir=data_dir,
        )


def _timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _normalize_contract(raw: object) -> Dict[str, object]:
    payload = raw if isinstance(raw, Mapping) else {}
    team_id = str(payload.get("team_id") or "").strip()
    years_left = max(1, int(_safe_number(payload.get("years_left", DEFAULT_CONTRACT_YEARS))))
    salary = max(
        DEFAULT_MIN_SALARY,
        int(round(_safe_number(payload.get("annual_salary", DEFAULT_MIN_SALARY)))),
    )
    service_time_days = max(0, int(_safe_number(payload.get("service_time_days", 0))))
    arb_eligible = bool(payload.get("arb_eligible", False))
    raw_fa_year = int(_safe_number(payload.get("fa_year", 0)))
    fa_year = raw_fa_year if raw_fa_year > 0 else (date.today().year + years_left)
    options = _normalize_options(payload.get("options"))
    incentives = _normalize_incentives(payload.get("incentives"))
    buyout_guarantee = max(0, int(round(_safe_number(payload.get("buyout_guarantee", 0)))))
    guaranteed = bool(payload.get("guaranteed", True))
    return {
        "team_id": team_id,
        "years_left": years_left,
        "annual_salary": salary,
        "service_time_days": service_time_days,
        "arb_eligible": arb_eligible,
        "fa_year": fa_year,
        "guaranteed": guaranteed,
        "buyout_guarantee": buyout_guarantee,
        "options": options,
        "incentives": incentives,
    }
