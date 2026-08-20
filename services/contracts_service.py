"""Contract lifecycle helpers for basic payroll/finance workflows."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Dict, Mapping

from playbalance.season_context import SeasonContext
from services.finance_ledger import post_contract_buyout
from services.prospect_event_log import record_option_decision_event
from services.team_auto_reassign_settings import auto_reassign_team_if_enabled
from utils.path_utils import get_data_dir
from utils.roster_io import read_roster_csv
from utils.roster_loader import save_roster

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
    "backfill_missing_contracts_from_rosters",
    "seed_inaugural_contracts_from_rosters",
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
    signing_bonus: int = 0,
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
        "signing_bonus": max(0, int(round(_safe_number(signing_bonus)))),
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
    signing_bonus: int = 0,
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
        signing_bonus=signing_bonus,
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
    try:
        record_option_decision_event(
            team_id=str(contract.get("team_id") or "").strip(),
            player_id=pid,
            decision=str(updated.get("decision") or "pending"),
            option_type=str(updated.get("type") or "").strip(),
            option_index=option_index,
            actor="user",
            trigger="manual_option_decision",
            details={"source": "contracts_service"},
            data_dir=data_dir,
        )
    except Exception:
        pass
    return _normalize_contract(contract)


def renew_pre_arb_salary(
    player_id: str,
    *,
    annual_salary: int,
    data_dir: Path | str | None = None,
) -> Dict[str, object]:
    """Renew a PRE-ARB player's salary for the coming year.

    Pre-arbitration players have no negotiating leverage — the team simply sets
    (renews) their salary. Applies only to players below arbitration eligibility
    (``service_time_days`` under the ~3-year pre-arb window and not
    ``arb_eligible``). Salary is floored at the league minimum. Returns
    ``{"renewed": bool, "message": str, ...}``.
    """

    pre_arb_service_days = 3 * 162
    pid = str(player_id or "").strip()
    if not pid:
        return {"renewed": False, "message": "player_id is required."}
    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        return {"renewed": False, "message": "No contracts found."}
    raw = players.get(pid)
    if not isinstance(raw, Mapping):
        return {"renewed": False, "message": "No contract for this player."}
    contract = _normalize_contract(raw)
    service_days = int(contract.get("service_time_days") or 0)
    if bool(contract.get("arb_eligible")) or service_days >= pre_arb_service_days:
        return {
            "renewed": False,
            "message": "Renewal applies only to pre-arbitration players.",
        }
    new_salary = max(DEFAULT_MIN_SALARY, int(round(float(annual_salary))))
    contract["annual_salary"] = new_salary
    players[pid] = contract
    save_contracts_payload(payload, data_dir=data_dir)
    return {
        "renewed": True,
        "player_id": pid,
        "annual_salary": new_salary,
        "team_id": str(contract.get("team_id") or "").strip(),
        "message": "Contract renewed.",
    }


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
                try:
                    record_option_decision_event(
                        team_id=str(contract.get("team_id") or "").strip(),
                        player_id=player_id,
                        decision="exercised",
                        option_type=str(option.get("type") or "").strip(),
                        option_index=0,
                        actor="system",
                        trigger="season_rollover",
                        details={"season_year": target_year},
                        data_dir=data_dir,
                    )
                except Exception:
                    pass
                continue
            if isinstance(option, Mapping):
                option_declined += 1
                buyout = max(0, int(_safe_number(option.get("buyout", 0))))
                try:
                    record_option_decision_event(
                        team_id=str(contract.get("team_id") or "").strip(),
                        player_id=player_id,
                        decision="declined",
                        option_type=str(option.get("type") or "").strip(),
                        option_index=0,
                        actor="system",
                        trigger="season_rollover",
                        details={"season_year": target_year, "buyout": buyout},
                        data_dir=data_dir,
                    )
                except Exception:
                    pass
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


def seed_inaugural_contracts_from_rosters(
    *,
    data_dir: Path | str | None = None,
    season_year: int | None = None,
    force: bool = False,
) -> Dict[str, object]:
    """Seed default contracts for rostered players missing contract rows.

    By default this only runs during a league's inaugural season so finance
    enablement in year one creates a usable baseline payroll state without
    inventing service-time history for established saves.
    """

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    resolved_year = _resolve_season_year(data_dir=resolved_data_dir, season_year=season_year)
    summary = _base_seed_summary(resolved_year=resolved_year, mode="inaugural")
    if not force and not _is_inaugural_season(data_dir=resolved_data_dir):
        summary["skipped_non_inaugural"] = True
        return summary

    return _seed_missing_contracts_from_rosters(
        data_dir=resolved_data_dir,
        resolved_year=resolved_year,
        summary=summary,
        contract_builder=lambda team_id, player_id, player: _build_seed_contract(
            team_id=team_id,
            player_id=player_id,
            player=player,
            season_year=resolved_year,
        ),
    )


def backfill_missing_contracts_from_rosters(
    *,
    data_dir: Path | str | None = None,
    season_year: int | None = None,
    force: bool = False,
) -> Dict[str, object]:
    """Generate missing contracts for established leagues when finance is enabled."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    resolved_year = _resolve_season_year(data_dir=resolved_data_dir, season_year=season_year)
    summary = _base_seed_summary(resolved_year=resolved_year, mode="mid_league")
    if not force and _is_inaugural_season(data_dir=resolved_data_dir):
        summary["skipped_inaugural"] = True
        return summary

    completed_seasons = _completed_league_seasons(data_dir=resolved_data_dir)
    return _seed_missing_contracts_from_rosters(
        data_dir=resolved_data_dir,
        resolved_year=resolved_year,
        summary=summary,
        contract_builder=lambda team_id, player_id, player: _build_backfill_contract(
            team_id=team_id,
            player_id=player_id,
            player=player,
            season_year=resolved_year,
            completed_seasons=completed_seasons,
        ),
    )


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
        removed_rows: list[tuple[str, str]] = []
        try:
            roster = read_roster_csv(roster_path, team_id)
        except Exception:
            continue

        def _remove_from(group_name: str, fallback_level: str) -> None:
            group = getattr(roster, group_name, [])
            kept: list[str] = []
            for pid in group:
                if pid in player_set:
                    level = fallback_level
                    if group_name == "dl":
                        tier = (roster.dl_tiers or {}).get(pid, "dl15")
                        level = "DL45" if str(tier).lower() == "dl45" else "DL15"
                        roster.dl_tiers.pop(pid, None)
                    removed_rows.append((pid, level))
                else:
                    kept.append(pid)
            setattr(roster, group_name, kept)

        _remove_from("act", "ACT")
        _remove_from("aaa", "AAA")
        _remove_from("low", "LOW")
        _remove_from("dl", "DL15")
        _remove_from("ir", "IR")

        if not removed_rows:
            continue

        try:
            save_roster(team_id, roster, roster_dir=roster_dir)
        except Exception:
            continue
        try:
            auto_reassign_team_if_enabled(
                team_id,
                players_file=resolved_data_dir / "players.csv",
                roster_dir=roster_dir,
                data_dir=resolved_data_dir,
            )
        except Exception:
            pass

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


def _base_seed_summary(*, resolved_year: int, mode: str) -> Dict[str, object]:
    return {
        "season_year": resolved_year,
        "mode": mode,
        "seeded": 0,
        "teams": [],
        "skipped_non_inaugural": False,
        "skipped_inaugural": False,
        "inferred_service_time_days": 0,
        "arb_eligible_seeded": 0,
        "term_breakdown": {
            "1y": 0,
            "2y": 0,
            "3y": 0,
            "4y_plus": 0,
        },
    }


def _seed_missing_contracts_from_rosters(
    *,
    data_dir: Path,
    resolved_year: int,
    summary: Dict[str, object],
    contract_builder,
) -> Dict[str, object]:
    team_ids = _load_team_ids_for_contracts(data_dir)
    roster_dir = data_dir / "rosters"
    if not team_ids or not roster_dir.exists():
        return summary

    payload = load_contracts_payload(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, dict):
        players = {}
        payload["players"] = players

    players_by_id = _load_players_by_id_for_contracts(data_dir)
    seeded_teams: set[str] = set()
    for team_id in team_ids:
        roster_path = roster_dir / f"{team_id}.csv"
        if not roster_path.exists():
            continue
        try:
            roster = read_roster_csv(roster_path, team_id)
        except Exception:
            continue
        for player_id in _roster_player_ids(roster):
            if player_id in players:
                continue
            player = players_by_id.get(player_id)
            contract, metadata = contract_builder(team_id, player_id, player)
            players[player_id] = contract
            summary["seeded"] = int(summary.get("seeded", 0) or 0) + 1
            summary["inferred_service_time_days"] = int(
                summary.get("inferred_service_time_days", 0) or 0
            ) + int(metadata.get("service_time_days", 0) or 0)
            if bool(metadata.get("arb_eligible")):
                summary["arb_eligible_seeded"] = int(
                    summary.get("arb_eligible_seeded", 0) or 0
                ) + 1
            term_breakdown = summary.get("term_breakdown")
            if isinstance(term_breakdown, dict):
                years_left = int(metadata.get("years_left", DEFAULT_CONTRACT_YEARS) or 0)
                if years_left >= 4:
                    term_breakdown["4y_plus"] = int(term_breakdown.get("4y_plus", 0) or 0) + 1
                elif years_left >= 1:
                    bucket = f"{years_left}y"
                    term_breakdown[bucket] = int(term_breakdown.get(bucket, 0) or 0) + 1
            seeded_teams.add(team_id)

    if int(summary.get("seeded", 0) or 0) > 0:
        save_contracts_payload(payload, data_dir=data_dir)
    summary["teams"] = sorted(seeded_teams)
    return summary


def _seed_contract_years(
    player: object | None,
    player_id: str,
    *,
    season_year: int,
    annual_salary: int,
) -> int:
    """Pick an inaugural contract length so a brand-new league does NOT open with
    the entire roster expiring after year one.

    Length TRENDS with age (younger players, entering their prime, sign longer)
    and quality (stars longer, fringe shorter, using the rating-derived salary as
    the quality proxy), then a per-player jitter of +/-2 widens the spread so the
    trend is a tendency rather than a lock — some veterans land multi-year deals
    and some youngsters land short ones. The jitter is DETERMINISTIC (a stable
    hash of the player id), so re-seeding the same league is idempotent and there
    is no reliance on global RNG. Result is clamped to 1..6 years, which staggers
    free agency across roughly the next six seasons.
    """

    age = _player_age(player, season_year=season_year)
    if age is None:
        base = 3
    elif age <= 23:
        base = 5
    elif age <= 26:
        base = 4
    elif age <= 29:
        base = 3
    elif age <= 32:
        base = 2
    else:
        base = 1

    # Quality nudge. estimate_salary_for_player encodes an "overall" as
    # DEFAULT_MIN_SALARY + (overall - 40) * 35_000, so these thresholds map to
    # roughly overall >= 70 (star) and overall <= 48 (fringe).
    if annual_salary >= DEFAULT_MIN_SALARY + 30 * 35_000:
        base += 1
    elif annual_salary <= DEFAULT_MIN_SALARY + 8 * 35_000:
        base -= 1

    # Deterministic jitter in [-2, +2] from a stable hash of the player id.
    digest = hashlib.md5(str(player_id).encode("utf-8")).hexdigest()
    jitter = (int(digest[:8], 16) % 5) - 2

    return max(1, min(6, base + jitter))


def _build_seed_contract(
    *,
    team_id: str,
    player_id: str,
    player: object | None,
    season_year: int,
) -> tuple[Dict[str, object], Dict[str, object]]:
    annual_salary = estimate_salary_for_player(player)
    years_left = _seed_contract_years(
        player,
        player_id,
        season_year=season_year,
        annual_salary=annual_salary,
    )
    contract = {
        "team_id": team_id,
        "years_left": years_left,
        "annual_salary": annual_salary,
        "service_time_days": 0,
        "arb_eligible": False,
        "fa_year": season_year + years_left,
        "guaranteed": True,
        "buyout_guarantee": 0,
        "options": [],
        "incentives": [],
    }
    return contract, {
        "player_id": player_id,
        "service_time_days": 0,
        "arb_eligible": False,
        "years_left": years_left,
    }


def _build_backfill_contract(
    *,
    team_id: str,
    player_id: str,
    player: object | None,
    season_year: int,
    completed_seasons: int,
) -> tuple[Dict[str, object], Dict[str, object]]:
    service_time_days = _infer_service_time_days(
        player,
        completed_seasons=completed_seasons,
        season_year=season_year,
    )
    years_left = _infer_backfill_years_left(
        player,
        service_time_days=service_time_days,
        season_year=season_year,
    )
    arb_eligible = years_left <= 1 and service_time_days >= (3 * 172)
    contract = {
        "team_id": team_id,
        "years_left": years_left,
        "annual_salary": estimate_salary_for_player(player),
        "service_time_days": service_time_days,
        "arb_eligible": arb_eligible,
        "fa_year": season_year + years_left,
        "guaranteed": True,
        "buyout_guarantee": 0,
        "options": [],
        "incentives": [],
    }
    return contract, {
        "player_id": player_id,
        "service_time_days": service_time_days,
        "arb_eligible": arb_eligible,
        "years_left": years_left,
    }


def _completed_league_seasons(*, data_dir: Path | str | None = None) -> int:
    try:
        if data_dir is None:
            ctx = SeasonContext.load()
        else:
            ctx = SeasonContext.load(path=Path(data_dir) / "career_index.json")
    except Exception:
        return 0

    seasons_count = len(list(ctx.seasons or []))
    try:
        sequence = int((ctx.current or {}).get("sequence", 0) or 0)
    except Exception:
        sequence = 0
    return max(seasons_count, max(0, sequence - 1))


def _is_inaugural_season(*, data_dir: Path | str | None = None) -> bool:
    try:
        if data_dir is None:
            ctx = SeasonContext.load()
        else:
            ctx = SeasonContext.load(path=Path(data_dir) / "career_index.json")
    except Exception:
        return False

    try:
        sequence = int((ctx.current or {}).get("sequence", 0) or 0)
    except Exception:
        sequence = 0
    if sequence == 1:
        return True
    return len(list(ctx.seasons or [])) == 0 and sequence <= 1


def _load_team_ids_for_contracts(data_dir: Path) -> list[str]:
    teams_path = data_dir / "teams.csv"
    team_ids: list[str] = []
    seen: set[str] = set()
    if teams_path.exists():
        try:
            import csv

            with teams_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    team_id = str(
                        row.get("team_id")
                        or row.get("abbreviation")
                        or ""
                    ).strip()
                    if not team_id or team_id in seen:
                        continue
                    seen.add(team_id)
                    team_ids.append(team_id)
        except Exception:
            team_ids = []
    if team_ids:
        return team_ids

    roster_dir = data_dir / "rosters"
    if not roster_dir.exists():
        return []
    for path in sorted(roster_dir.glob("*.csv")):
        team_id = path.stem.strip()
        if (
            not team_id
            or team_id.endswith("_pitching")
            or team_id in seen
        ):
            continue
        seen.add(team_id)
        team_ids.append(team_id)
    return team_ids


def _load_players_by_id_for_contracts(data_dir: Path) -> Dict[str, object]:
    players_path = data_dir / "players.csv"
    if not players_path.exists():
        return {}
    try:
        from utils.player_loader import load_players_from_csv

        loaded = load_players_from_csv(players_path)
    except Exception:
        return {}
    return {
        str(getattr(player, "player_id", "") or "").strip(): player
        for player in loaded
        if str(getattr(player, "player_id", "") or "").strip()
    }


def _roster_player_ids(roster: object) -> list[str]:
    player_ids: list[str] = []
    seen: set[str] = set()
    for group_name in ("act", "aaa", "low", "dl", "ir"):
        for raw_player_id in getattr(roster, group_name, []) or []:
            player_id = str(raw_player_id or "").strip()
            if not player_id or player_id in seen:
                continue
            seen.add(player_id)
            player_ids.append(player_id)
    return player_ids


def _player_age(
    player: object | None,
    *,
    season_year: int | None = None,
) -> int | None:
    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if not birthdate:
        return None
    token = birthdate.split("T", 1)[0]
    try:
        born = datetime.strptime(token, "%Y-%m-%d").date()
    except Exception:
        return None
    reference_year = int(season_year) if season_year is not None else date.today().year
    age = reference_year - born.year
    if season_year is None and (date.today().month, date.today().day) < (born.month, born.day):
        age -= 1
    return max(0, age)


def _player_history_seasons(player: object | None) -> int:
    history = getattr(player, "career_history", None)
    if isinstance(history, Mapping):
        return len(history)
    return 0


def _infer_service_time_days(
    player: object | None,
    *,
    completed_seasons: int,
    season_year: int,
) -> int:
    if completed_seasons <= 0:
        return 0

    history_seasons = _player_history_seasons(player)
    if history_seasons > 0:
        return max(0, min(completed_seasons, history_seasons)) * 172

    age = _player_age(player, season_year=season_year)
    if age is None:
        return min(1, completed_seasons) * 172

    estimated_years = max(0, age - 22)
    if estimated_years <= 0 and age >= 24:
        estimated_years = 1
    return max(0, min(completed_seasons, estimated_years)) * 172


def _infer_backfill_years_left(
    player: object | None,
    *,
    service_time_days: int,
    season_year: int,
) -> int:
    age = _player_age(player, season_year=season_year)
    if age is None:
        return 1
    if age <= 24:
        return 3
    if age <= 29:
        return 2
    if service_time_days >= (3 * 172):
        return 1
    return 2


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
        clean_team = str(team_id or "").strip()
        post_contract_buyout(
            team_id=clean_team,
            season_year=int(season_year),
            player_id=str(player_id or "").strip(),
            buyout_amount=int(amount),
            detail=str(detail or "").strip(),
            timestamp=_timestamp(),
            data_dir=data_dir,
        )
        # Money actually moves: the buyout debits the team's cash. The ledger
        # row above already records it, so skip a duplicate ledger entry here.
        try:
            from services.owner_finance_engine import charge_team_one_time_cost

            charge_team_one_time_cost(
                clean_team,
                int(amount),
                expense_type="contract_buyout",
                memo=f"Option buyout: {str(player_id or '').strip()}",
                season_year=int(season_year),
                data_dir=data_dir,
                post_ledger=False,
            )
        except Exception:
            pass


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
    signing_bonus = max(0, int(round(_safe_number(payload.get("signing_bonus", 0)))))
    return {
        "team_id": team_id,
        "years_left": years_left,
        "annual_salary": salary,
        "service_time_days": service_time_days,
        "arb_eligible": arb_eligible,
        "fa_year": fa_year,
        "guaranteed": guaranteed,
        "buyout_guarantee": buyout_guarantee,
        "signing_bonus": signing_bonus,
        "options": options,
        "incentives": incentives,
    }
