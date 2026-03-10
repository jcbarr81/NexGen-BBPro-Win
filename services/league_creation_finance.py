"""League-creation finance setup helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from services.finance_settings import (
    PRESET_CUSTOM,
    PRESET_OFF,
    apply_financial_preset,
    ensure_financial_defaults,
    update_financial_settings,
)


def finance_summary_lines(config: Dict[str, object]) -> list[str]:
    preset = str(config.get("preset") or PRESET_OFF).strip().lower()
    enabled = bool(config.get("enabled", False))
    enforcement = str(config.get("enforcement_mode") or "warn").strip().lower()
    modules = config.get("modules")
    modules_map = modules if isinstance(modules, dict) else {}

    lines = [
        f"Finance preset: {preset}",
        f"Finance enabled: {'Yes' if enabled else 'No'}",
        f"Enforcement mode: {enforcement}",
    ]
    if preset == PRESET_CUSTOM:
        for module in (
            "owner_budgets",
            "gm_contracts",
            "gm_payroll_rules",
            "gm_arbitration",
            "gm_free_agency",
            "gm_roster_cost_enforcement",
        ):
            lines.append(f"{module}: {str(modules_map.get(module, 'off'))}")
    return lines


def apply_initial_finance_settings(
    config: Dict[str, object],
    *,
    data_dir: Path,
    league_id: str,
) -> None:
    settings_path = data_dir / "league_financial_settings.json"
    ensure_financial_defaults(data_dir=data_dir, league_id=league_id)

    preset = str(config.get("preset") or PRESET_OFF).strip().lower()
    if preset != PRESET_CUSTOM:
        apply_financial_preset(preset, path=settings_path, league_id=league_id)
        return

    modules = config.get("modules")
    modules_map = modules if isinstance(modules, dict) else {}
    update_financial_settings(
        enabled=bool(config.get("enabled", False)),
        preset=PRESET_CUSTOM,
        enforcement_mode=str(config.get("enforcement_mode") or "warn"),
        modules={str(k): str(v) for k, v in modules_map.items()},
        path=settings_path,
        league_id=league_id,
    )


__all__ = ["finance_summary_lines", "apply_initial_finance_settings"]
