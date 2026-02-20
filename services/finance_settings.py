"""Persistence helpers for league financial system settings."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
from typing import Dict, Mapping, MutableMapping

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir

__all__ = [
    "FinancialSettings",
    "VERSION",
    "DEFAULT_PRESET",
    "DEFAULT_ENABLED",
    "DEFAULT_ENFORCEMENT_MODE",
    "DEFAULT_FINANCE_AI_TUNING",
    "MODULE_LEVELS",
    "PRESET_PROFILES",
    "load_financial_settings",
    "save_financial_settings",
    "update_financial_settings",
    "apply_financial_preset",
    "ensure_financial_defaults",
    "ensure_financial_defaults_for_all_leagues",
]

VERSION = 1

LEVEL_OFF = "off"
LEVEL_BASIC = "basic"
LEVEL_ADVANCED = "advanced"
LEVEL_MLB_LIKE = "mlb_like"
ENFORCEMENT_OFF = "off"
ENFORCEMENT_WARN = "warn"
ENFORCEMENT_BLOCK = "block"

MODULE_LEVELS: Dict[str, tuple[str, ...]] = {
    "owner_revenue": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "owner_market_model": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "owner_budgets": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "owner_expenses": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "gm_contracts": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "gm_payroll_rules": (LEVEL_OFF, LEVEL_BASIC, LEVEL_MLB_LIKE),
    "gm_arbitration": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "gm_free_agency": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
    "gm_roster_cost_enforcement": (ENFORCEMENT_OFF, ENFORCEMENT_WARN, ENFORCEMENT_BLOCK),
    "gm_finance_ai": (LEVEL_OFF, LEVEL_BASIC, LEVEL_ADVANCED),
}

PRESET_OFF = "off"
PRESET_SIMPLE = "simple"
PRESET_STANDARD = "standard"
PRESET_MLB_LIKE = "mlb_like"
PRESET_CUSTOM = "custom"

DEFAULT_PRESET = PRESET_OFF
DEFAULT_ENABLED = False
DEFAULT_ENFORCEMENT_MODE = ENFORCEMENT_WARN
DEFAULT_FINANCE_AI_TUNING: Dict[str, float | int] = {
    "star_talent_threshold": 76,
    "star_performance_threshold": 78,
    "underperformer_threshold": 45,
    "severe_underperformer_threshold": 38,
    "high_cost_salary_share": 0.18,
    "very_high_cost_salary_share": 0.28,
    "high_cost_salary": 12_000_000,
    "very_high_cost_salary": 20_000_000,
    "max_raise_pct": 0.45,
    "fa_star_quality_threshold": 78,
    "fa_rebuild_avoid_salary": 16_000_000,
    "fa_cautious_avoid_salary": 12_000_000,
    "fa_hard_avoid_salary": 24_000_000,
    "commitment_pressure_ratio": 0.95,
    "commitment_relief_ratio": 0.68,
    "commitment_pressure_penalty": 18_000_000,
    "commitment_relief_bonus": 10_000_000,
    "future_year_commitment_ratio_limit": 1.08,
    "future_year_hard_commitment_ratio_limit": 1.20,
}
TEAM_FINANCIALS_VERSION = 1
CONTRACTS_VERSION = 1
TEAM_FINANCIALS_FILENAME = "team_financials.json"
CONTRACTS_FILENAME = "contracts.json"
FINANCIAL_TRANSACTIONS_FILENAME = "financial_transactions.csv"
FINANCIAL_TRANSACTIONS_HEADER = (
    "timestamp",
    "season_year",
    "team_id",
    "category",
    "amount",
    "memo",
)

_OFF_MODULES = {module: levels[0] for module, levels in MODULE_LEVELS.items()}

PRESET_PROFILES: Dict[str, Dict[str, object]] = {
    PRESET_OFF: {
        "enabled": False,
        "enforcement_mode": ENFORCEMENT_WARN,
        "modules": dict(_OFF_MODULES),
    },
    PRESET_SIMPLE: {
        "enabled": True,
        "enforcement_mode": ENFORCEMENT_WARN,
        "modules": {
            "owner_revenue": LEVEL_BASIC,
            "owner_market_model": LEVEL_OFF,
            "owner_budgets": LEVEL_BASIC,
            "owner_expenses": LEVEL_BASIC,
            "gm_contracts": LEVEL_BASIC,
            "gm_payroll_rules": LEVEL_BASIC,
            "gm_arbitration": LEVEL_OFF,
            "gm_free_agency": LEVEL_BASIC,
            "gm_roster_cost_enforcement": ENFORCEMENT_WARN,
            "gm_finance_ai": LEVEL_BASIC,
        },
    },
    PRESET_STANDARD: {
        "enabled": True,
        "enforcement_mode": ENFORCEMENT_WARN,
        "modules": {
            "owner_revenue": LEVEL_ADVANCED,
            "owner_market_model": LEVEL_BASIC,
            "owner_budgets": LEVEL_ADVANCED,
            "owner_expenses": LEVEL_ADVANCED,
            "gm_contracts": LEVEL_ADVANCED,
            "gm_payroll_rules": LEVEL_BASIC,
            "gm_arbitration": LEVEL_BASIC,
            "gm_free_agency": LEVEL_ADVANCED,
            "gm_roster_cost_enforcement": ENFORCEMENT_WARN,
            "gm_finance_ai": LEVEL_ADVANCED,
        },
    },
    PRESET_MLB_LIKE: {
        "enabled": True,
        "enforcement_mode": ENFORCEMENT_BLOCK,
        "modules": {
            "owner_revenue": LEVEL_ADVANCED,
            "owner_market_model": LEVEL_ADVANCED,
            "owner_budgets": LEVEL_ADVANCED,
            "owner_expenses": LEVEL_ADVANCED,
            "gm_contracts": LEVEL_ADVANCED,
            "gm_payroll_rules": LEVEL_MLB_LIKE,
            "gm_arbitration": LEVEL_ADVANCED,
            "gm_free_agency": LEVEL_ADVANCED,
            "gm_roster_cost_enforcement": ENFORCEMENT_BLOCK,
            "gm_finance_ai": LEVEL_ADVANCED,
        },
    },
}


@dataclass
class FinancialSettings:
    league_id: str
    enabled: bool = DEFAULT_ENABLED
    preset: str = DEFAULT_PRESET
    enforcement_mode: str = DEFAULT_ENFORCEMENT_MODE
    modules: Dict[str, str] = field(default_factory=lambda: dict(_OFF_MODULES))
    finance_ai_tuning: Dict[str, float | int] = field(
        default_factory=lambda: dict(DEFAULT_FINANCE_AI_TUNING)
    )

    def normalized(self) -> "FinancialSettings":
        resolved_modules = _normalize_modules(self.modules)
        resolved_tuning = _normalize_finance_ai_tuning(self.finance_ai_tuning)
        if not self.enabled:
            resolved_modules = dict(_OFF_MODULES)
            return FinancialSettings(
                league_id=_normalize_league_id(self.league_id),
                enabled=False,
                preset=PRESET_OFF,
                enforcement_mode=_normalize_enforcement(self.enforcement_mode),
                modules=resolved_modules,
                finance_ai_tuning=resolved_tuning,
            )
        return FinancialSettings(
            league_id=_normalize_league_id(self.league_id),
            enabled=True,
            preset=_normalize_preset(self.preset),
            enforcement_mode=_normalize_enforcement(self.enforcement_mode),
            modules=resolved_modules,
            finance_ai_tuning=resolved_tuning,
        )

    def module_level(self, module: str) -> str:
        return self.modules.get(module, LEVEL_OFF)

    def module_enabled(self, module: str) -> bool:
        level = self.module_level(module)
        if module == "gm_roster_cost_enforcement":
            return level != ENFORCEMENT_OFF
        return level != LEVEL_OFF


def load_financial_settings(
    path: Path | str | None = None,
    *,
    league_id: str | None = None,
) -> FinancialSettings:
    payload = _load_payload(path=path)
    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    leagues = payload.setdefault("leagues", {})
    data = leagues.get(resolved_league_id, {})
    fallback_league_id = ""
    if not data and len(leagues) == 1:
        only_league_id, only_data = next(iter(leagues.items()))
        data = only_data
        fallback_league_id = _normalize_league_id(only_league_id)
    if not isinstance(data, dict):
        data = {}
    if fallback_league_id:
        resolved_league_id = fallback_league_id
    settings = FinancialSettings(
        league_id=resolved_league_id,
        enabled=bool(data.get("enabled", DEFAULT_ENABLED)),
        preset=_normalize_preset(data.get("preset", DEFAULT_PRESET)),
        enforcement_mode=_normalize_enforcement(
            data.get("enforcement_mode", DEFAULT_ENFORCEMENT_MODE)
        ),
        modules=_normalize_modules(data.get("modules")),
        finance_ai_tuning=_normalize_finance_ai_tuning(data.get("finance_ai_tuning")),
    )
    return settings.normalized()


def save_financial_settings(
    settings: FinancialSettings,
    path: Path | str | None = None,
    *,
    league_id: str | None = None,
) -> None:
    payload = _load_payload(path=path)
    leagues = payload.setdefault("leagues", {})
    normalized = settings.normalized()
    target_league_id = _normalize_league_id(league_id) or normalized.league_id
    leagues[target_league_id] = {
        "enabled": normalized.enabled,
        "preset": normalized.preset,
        "enforcement_mode": normalized.enforcement_mode,
        "modules": dict(normalized.modules),
        "finance_ai_tuning": dict(normalized.finance_ai_tuning),
    }
    payload["version"] = VERSION
    _write_payload(payload, path=path)


def apply_financial_preset(
    preset: str,
    *,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> FinancialSettings:
    token = _normalize_preset(preset)
    profile = PRESET_PROFILES.get(token)
    if profile is None:
        token = PRESET_CUSTOM
        profile = PRESET_PROFILES[PRESET_OFF]

    resolved_league_id = _normalize_league_id(league_id) or _resolve_league_id()
    existing = load_financial_settings(path=path, league_id=resolved_league_id)
    settings = FinancialSettings(
        league_id=resolved_league_id,
        enabled=bool(profile.get("enabled", DEFAULT_ENABLED)),
        preset=token,
        enforcement_mode=_normalize_enforcement(
            profile.get("enforcement_mode", DEFAULT_ENFORCEMENT_MODE)
        ),
        modules=_normalize_modules(profile.get("modules")),
        finance_ai_tuning=dict(existing.finance_ai_tuning),
    )
    save_financial_settings(settings, path=path, league_id=resolved_league_id)
    return settings.normalized()


def update_financial_settings(
    *,
    enabled: bool | None = None,
    preset: str | None = None,
    enforcement_mode: str | None = None,
    modules: Mapping[str, str] | None = None,
    finance_ai_tuning: Mapping[str, object] | None = None,
    path: Path | str | None = None,
    league_id: str | None = None,
) -> FinancialSettings:
    settings = load_financial_settings(path=path, league_id=league_id)

    if preset is not None and _normalize_preset(preset) != PRESET_CUSTOM:
        return apply_financial_preset(preset, path=path, league_id=league_id)

    if enabled is not None:
        settings.enabled = bool(enabled)
    if preset is not None:
        settings.preset = _normalize_preset(preset)
    if enforcement_mode is not None:
        settings.enforcement_mode = _normalize_enforcement(enforcement_mode)
    if modules:
        merged = dict(settings.modules)
        for module, value in modules.items():
            if module in MODULE_LEVELS:
                merged[module] = _normalize_module_level(module, value)
        settings.modules = merged
        settings.preset = PRESET_CUSTOM
    if finance_ai_tuning is not None:
        merged_tuning = dict(settings.finance_ai_tuning)
        for key, value in finance_ai_tuning.items():
            if key in DEFAULT_FINANCE_AI_TUNING:
                merged_tuning[key] = value
        settings.finance_ai_tuning = _normalize_finance_ai_tuning(merged_tuning)
        settings.preset = PRESET_CUSTOM

    save_financial_settings(settings, path=path, league_id=league_id)
    return settings.normalized()


def ensure_financial_defaults(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    season_year: int | None = None,
) -> Dict[str, Path]:
    """Ensure baseline financial files exist for a league data directory."""

    resolved_data_dir = Path(data_dir) if data_dir is not None else get_data_dir()
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings_path = resolved_data_dir / "league_financial_settings.json"
    contracts_path = resolved_data_dir / CONTRACTS_FILENAME
    team_financials_path = resolved_data_dir / TEAM_FINANCIALS_FILENAME
    transactions_path = resolved_data_dir / FINANCIAL_TRANSACTIONS_FILENAME

    settings = load_financial_settings(path=settings_path, league_id=league_id)
    save_financial_settings(settings, path=settings_path, league_id=settings.league_id)

    _ensure_team_financials_file(
        team_financials_path,
        data_dir=resolved_data_dir,
        season_year=season_year,
    )
    _ensure_contracts_file(contracts_path)
    _ensure_financial_transactions_file(transactions_path)
    return {
        "settings": settings_path,
        "team_financials": team_financials_path,
        "contracts": contracts_path,
        "transactions": transactions_path,
    }


def ensure_financial_defaults_for_all_leagues() -> Dict[str, Dict[str, Path]]:
    """Seed baseline financial files across all known leagues."""

    results: Dict[str, Dict[str, Path]] = {}
    try:
        from services import league_registry

        for record in league_registry.list_leagues():
            data_dir = league_registry.get_league_data_dir(record.id, create=True)
            results[record.id] = ensure_financial_defaults(
                data_dir=data_dir,
                league_id=record.id,
            )
    except Exception:
        # Fall back to active data-dir seeding when registry is unavailable.
        pass

    if results:
        return results

    seeded = ensure_financial_defaults()
    settings = load_financial_settings(path=seeded["settings"])
    results[settings.league_id] = seeded
    return results


def _normalize_league_id(value: object) -> str:
    text = str(value or "").strip()
    return text or "league"


def _normalize_preset(value: object) -> str:
    token = str(value or DEFAULT_PRESET).strip().lower()
    if token in {PRESET_OFF, PRESET_SIMPLE, PRESET_STANDARD, PRESET_MLB_LIKE, PRESET_CUSTOM}:
        return token
    return PRESET_CUSTOM


def _normalize_enforcement(value: object) -> str:
    token = str(value or DEFAULT_ENFORCEMENT_MODE).strip().lower()
    if token in {ENFORCEMENT_OFF, ENFORCEMENT_WARN, ENFORCEMENT_BLOCK}:
        return token
    return DEFAULT_ENFORCEMENT_MODE


def _normalize_module_level(module: str, value: object) -> str:
    allowed = MODULE_LEVELS.get(module)
    if not allowed:
        return LEVEL_OFF
    token = str(value or "").strip().lower()
    if token in allowed:
        return token
    return allowed[0]


def _normalize_modules(raw: object) -> Dict[str, str]:
    normalized = dict(_OFF_MODULES)
    if not isinstance(raw, Mapping):
        return normalized
    for module in MODULE_LEVELS:
        if module in raw:
            normalized[module] = _normalize_module_level(module, raw[module])
    return normalized


def _normalize_finance_ai_tuning(raw: object) -> Dict[str, float | int]:
    tuning = dict(DEFAULT_FINANCE_AI_TUNING)
    if not isinstance(raw, Mapping):
        return tuning

    int_fields = {
        "star_talent_threshold": (35, 95),
        "star_performance_threshold": (35, 95),
        "underperformer_threshold": (20, 80),
        "severe_underperformer_threshold": (20, 80),
        "high_cost_salary": (1_000_000, 60_000_000),
        "very_high_cost_salary": (1_000_000, 80_000_000),
        "fa_star_quality_threshold": (35, 95),
        "fa_rebuild_avoid_salary": (1_000_000, 60_000_000),
        "fa_cautious_avoid_salary": (1_000_000, 60_000_000),
        "fa_hard_avoid_salary": (1_000_000, 80_000_000),
        "commitment_pressure_penalty": (0, 60_000_000),
        "commitment_relief_bonus": (0, 60_000_000),
    }
    float_fields = {
        "high_cost_salary_share": (0.05, 0.60),
        "very_high_cost_salary_share": (0.05, 0.80),
        "max_raise_pct": (0.05, 1.00),
        "commitment_pressure_ratio": (0.70, 1.60),
        "commitment_relief_ratio": (0.20, 1.20),
        "future_year_commitment_ratio_limit": (0.80, 1.80),
        "future_year_hard_commitment_ratio_limit": (0.90, 2.00),
    }
    for key, limits in int_fields.items():
        if key not in raw:
            continue
        lower, upper = limits
        try:
            value = int(round(float(raw.get(key))))
        except Exception:
            continue
        tuning[key] = max(lower, min(upper, value))
    for key, limits in float_fields.items():
        if key not in raw:
            continue
        lower, upper = limits
        try:
            value = float(raw.get(key))
        except Exception:
            continue
        tuning[key] = max(lower, min(upper, value))
    return tuning


def _resolve_league_id() -> str:
    try:
        ctx = SeasonContext.load()
        league_id = ctx.league_id
        if league_id:
            return league_id
        return ctx.ensure_league()
    except Exception:
        return "league"


def _settings_path(path: Path | str | None = None) -> Path:
    return Path(path) if path is not None else (get_data_dir() / "league_financial_settings.json")


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


def _read_json_mapping(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _resolve_season_year(*, data_dir: Path, season_year: int | None) -> int:
    if season_year is not None:
        try:
            return int(season_year)
        except Exception:
            pass
    try:
        ctx = SeasonContext.load(path=data_dir / "career_index.json")
        raw_year = (ctx.current or {}).get("league_year")
        if raw_year is not None:
            return int(raw_year)
    except Exception:
        pass
    return date.today().year


def _load_team_ids(data_dir: Path) -> list[str]:
    teams_path = data_dir / "teams.csv"
    if not teams_path.exists():
        return []
    team_ids: list[str] = []
    seen: set[str] = set()
    try:
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
        return []
    return team_ids


def _coerce_money(value: object) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _default_team_financial_entry() -> Dict[str, object]:
    return {
        "cash_on_hand": 0,
        "debt": 0,
        "revenue": {
            "tickets": 0,
            "concessions": 0,
            "media": 0,
            "sponsorship": 0,
        },
        "expenses": {
            "payroll": 0,
            "training": 0,
            "scouting": 0,
            "facilities": 0,
            "operations": 0,
        },
        "budgets": {
            "training": 0,
            "scouting": 0,
            "development": 0,
            "facilities": 0,
        },
    }


def _normalize_nested_money(
    payload: Mapping[str, object] | object,
    fields: tuple[str, ...],
) -> Dict[str, int]:
    source = payload if isinstance(payload, Mapping) else {}
    return {
        field: _coerce_money(source.get(field, 0))
        for field in fields
    }


def _normalize_team_financial_entry(raw: Mapping[str, object] | object) -> Dict[str, object]:
    entry = raw if isinstance(raw, Mapping) else {}
    return {
        "cash_on_hand": _coerce_money(entry.get("cash_on_hand", 0)),
        "debt": _coerce_money(entry.get("debt", 0)),
        "revenue": _normalize_nested_money(
            entry.get("revenue"),
            ("tickets", "concessions", "media", "sponsorship"),
        ),
        "expenses": _normalize_nested_money(
            entry.get("expenses"),
            ("payroll", "training", "scouting", "facilities", "operations"),
        ),
        "budgets": _normalize_nested_money(
            entry.get("budgets"),
            ("training", "scouting", "development", "facilities"),
        ),
    }


def _ensure_team_financials_file(
    path: Path,
    *,
    data_dir: Path,
    season_year: int | None = None,
) -> None:
    payload = _read_json_mapping(path)
    teams_payload = payload.get("teams")
    existing_teams = teams_payload if isinstance(teams_payload, Mapping) else {}
    resolved_year = _resolve_season_year(data_dir=data_dir, season_year=season_year)
    if season_year is None:
        try:
            existing_year = int(payload.get("season_year", resolved_year))
            if existing_year > 0:
                resolved_year = existing_year
        except Exception:
            pass

    normalized_teams: Dict[str, Dict[str, object]] = {}
    for team_id, entry in existing_teams.items():
        key = str(team_id).strip()
        if not key:
            continue
        normalized_teams[key] = _normalize_team_financial_entry(entry)

    for team_id in _load_team_ids(data_dir):
        normalized_teams.setdefault(team_id, _default_team_financial_entry())

    normalized_payload = {
        "version": TEAM_FINANCIALS_VERSION,
        "season_year": resolved_year,
        "teams": normalized_teams,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized_payload, indent=2), encoding="utf-8")


def _ensure_contracts_file(path: Path) -> None:
    payload = _read_json_mapping(path)
    players = payload.get("players")
    normalized_payload = {
        "version": CONTRACTS_VERSION,
        "players": players if isinstance(players, Mapping) else {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized_payload, indent=2), encoding="utf-8")


def _ensure_financial_transactions_file(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FINANCIAL_TRANSACTIONS_HEADER)
