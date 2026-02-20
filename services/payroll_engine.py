"""Basic payroll helpers for finance projections and reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping

from services.contracts_service import contract_payroll_value, load_contracts_payload
from utils.path_utils import get_data_dir

__all__ = [
    "MONTHS_PER_YEAR",
    "load_contracts",
    "calculate_annual_payroll_totals",
    "calculate_monthly_payroll_totals",
]

MONTHS_PER_YEAR = 12


def load_contracts(*, data_dir: Path | str | None = None) -> Dict[str, object]:
    """Load ``contracts.json`` from the provided league data directory."""

    return load_contracts_payload(data_dir=data_dir)


def calculate_annual_payroll_totals(
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, int]:
    """Return annual payroll totals keyed by team id."""

    payload = load_contracts(data_dir=data_dir)
    players = payload.get("players")
    if not isinstance(players, Mapping):
        return {}
    totals: Dict[str, int] = {}
    for contract in players.values():
        if not isinstance(contract, Mapping):
            continue
        team_id = str(contract.get("team_id") or "").strip()
        if not team_id:
            continue
        try:
            salary = int(contract_payroll_value(contract))
        except Exception:
            salary = 0
        if salary <= 0:
            continue
        totals[team_id] = totals.get(team_id, 0) + salary
    return totals


def calculate_monthly_payroll_totals(
    *,
    data_dir: Path | str | None = None,
) -> Dict[str, int]:
    """Return monthly payroll totals keyed by team id."""

    annual = calculate_annual_payroll_totals(data_dir=data_dir)
    return {
        team_id: int(round(total / MONTHS_PER_YEAR))
        for team_id, total in annual.items()
    }
