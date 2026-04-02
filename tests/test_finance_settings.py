from __future__ import annotations

import importlib
import json
from pathlib import Path

from services.finance_settings import (
    DEFAULT_FINANCE_AI_TUNING,
    FINANCIAL_TRANSACTIONS_HEADER,
    ENFORCEMENT_BLOCK,
    LEVEL_MLB_LIKE,
    PRESET_CUSTOM,
    PRESET_MLB_LIKE,
    PRESET_SIMPLE,
    apply_financial_preset,
    build_finance_enforcement_tooltip,
    build_finance_module_tooltip,
    ensure_financial_defaults,
    ensure_financial_defaults_for_all_leagues,
    load_financial_settings,
    update_financial_settings,
)


def test_load_defaults_when_settings_file_missing(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    settings = load_financial_settings(path=path, league_id="alpha")

    assert settings.enabled is False
    assert settings.preset == "off"
    assert settings.module_enabled("owner_revenue") is False
    assert settings.finance_ai_tuning["star_talent_threshold"] == DEFAULT_FINANCE_AI_TUNING["star_talent_threshold"]


def test_apply_simple_preset(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    settings = apply_financial_preset(PRESET_SIMPLE, path=path, league_id="alpha")

    assert settings.enabled is True
    assert settings.preset == PRESET_SIMPLE
    assert settings.module_level("owner_revenue") == "basic"
    assert settings.module_level("gm_arbitration") == "off"


def test_build_finance_module_tooltip_lists_available_levels():
    tooltip = build_finance_module_tooltip("gm_contracts")

    assert "player contracts" in tooltip.lower()
    assert "Levels:" in tooltip
    assert "- Off:" in tooltip
    assert "- Basic:" in tooltip
    assert "- Advanced:" in tooltip


def test_build_finance_enforcement_tooltip_lists_modes():
    tooltip = build_finance_enforcement_tooltip()

    assert "overall finance system" in tooltip.lower()
    assert f"- Warn:" in tooltip
    assert f"- Block:" in tooltip


def test_apply_simple_preset_seeds_inaugural_contracts(tmp_path):
    data_dir = tmp_path / "league-data"
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "career_index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "league": {"id": "alpha"},
                "current": {"league_year": 2032, "sequence": 1},
                "seasons": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (roster_dir / "AAA.csv").write_text("P100,ACT\n", encoding="utf-8")

    apply_financial_preset(
        PRESET_SIMPLE,
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert "P100" in contracts.get("players", {})


def test_update_financial_settings_backfills_established_league_contracts(tmp_path):
    data_dir = tmp_path / "league-data"
    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        (
            "player_id,first_name,last_name,birthdate,height,weight,ethnicity,skin_tone,"
            "hair_color,facial_hair,bats,primary_position,other_positions,gf,injured,"
            "injury_description,return_date,injury_list,injury_start_date,"
            "injury_minimum_days,injury_eligible_date,injury_rehab_assignment,"
            "injury_rehab_days,durability,is_pitcher,ch,ph,sp,eye,pl,vl,sc,fa,arm\n"
            "P100,Casey,Bat,2004-06-15,73,195,,,,,R,CF,,50,false,,,,,,,,0,55,false,72,70,64,68,60,61,59,58,57\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "career_index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "league": {"id": "alpha"},
                "current": {"league_year": 2032, "sequence": 3},
                "seasons": [{"season_id": "alpha-2030"}, {"season_id": "alpha-2031"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (roster_dir / "AAA.csv").write_text("P100,ACT\n", encoding="utf-8")

    ensure_financial_defaults(data_dir=data_dir, league_id="alpha")
    updated = update_financial_settings(
        enabled=True,
        preset=PRESET_CUSTOM,
        enforcement_mode="warn",
        modules={"gm_contracts": "advanced"},
        path=data_dir / "league_financial_settings.json",
        league_id="alpha",
    )

    contracts = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert "P100" in contracts.get("players", {})
    assert updated.contract_backfill_summary["mode"] == "mid_league"
    assert updated.contract_backfill_summary["seeded"] == 1


def test_apply_mlb_like_preset_and_reload(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    apply_financial_preset(PRESET_MLB_LIKE, path=path, league_id="alpha")
    reloaded = load_financial_settings(path=path, league_id="alpha")

    assert reloaded.enabled is True
    assert reloaded.preset == PRESET_MLB_LIKE
    assert reloaded.module_level("gm_payroll_rules") == LEVEL_MLB_LIKE
    assert reloaded.module_level("gm_roster_cost_enforcement") == ENFORCEMENT_BLOCK


def test_update_custom_modules_normalizes_invalid_values(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    apply_financial_preset(PRESET_SIMPLE, path=path, league_id="alpha")

    updated = update_financial_settings(
        league_id="alpha",
        path=path,
        modules={
            "owner_revenue": "advanced",
            "owner_market_model": "INVALID",
            "gm_roster_cost_enforcement": "block",
        },
    )

    assert updated.preset == PRESET_CUSTOM
    assert updated.module_level("owner_revenue") == "advanced"
    assert updated.module_level("owner_market_model") == "off"
    assert updated.module_level("gm_roster_cost_enforcement") == "block"


def test_disable_financial_system_forces_all_modules_off(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    apply_financial_preset(PRESET_MLB_LIKE, path=path, league_id="alpha")

    disabled = update_financial_settings(
        league_id="alpha",
        path=path,
        enabled=False,
    )

    assert disabled.enabled is False
    assert disabled.preset == "off"
    for module, level in disabled.modules.items():
        if module == "gm_roster_cost_enforcement":
            assert level == "off"
        else:
            assert level == "off"


def test_settings_are_stored_per_league(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    apply_financial_preset(PRESET_SIMPLE, path=path, league_id="alpha")
    apply_financial_preset(PRESET_MLB_LIKE, path=path, league_id="beta")

    alpha = load_financial_settings(path=path, league_id="alpha")
    beta = load_financial_settings(path=path, league_id="beta")

    assert alpha.preset == PRESET_SIMPLE
    assert beta.preset == PRESET_MLB_LIKE

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert set(payload.get("leagues", {}).keys()) == {"alpha", "beta"}


def test_ensure_defaults_keeps_single_existing_league_key(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    ensure_financial_defaults(data_dir=data_dir)

    payload = json.loads((data_dir / "league_financial_settings.json").read_text(encoding="utf-8"))
    assert set(payload.get("leagues", {}).keys()) == {"test"}

    loaded = load_financial_settings(path=data_dir / "league_financial_settings.json")
    assert loaded.league_id == "test"


def test_ensure_financial_defaults_seeds_baseline_files(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
            "BBB,Bruins,Beta,BBB,East,Beta Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "career_index.json").write_text(
        json.dumps({"version": 1, "league": {"id": "alpha"}, "current": {"league_year": 2032}}, indent=2),
        encoding="utf-8",
    )

    paths = ensure_financial_defaults(data_dir=data_dir, league_id="alpha")

    assert paths["settings"].exists()
    assert paths["team_financials"].exists()
    assert paths["contracts"].exists()
    assert paths["transactions"].exists()

    settings = load_financial_settings(path=paths["settings"], league_id="alpha")
    assert settings.enabled is False
    assert settings.preset == "off"

    team_financials = json.loads(paths["team_financials"].read_text(encoding="utf-8"))
    assert team_financials.get("season_year") == 2032
    assert set(team_financials.get("teams", {}).keys()) == {"AAA", "BBB"}

    contracts = json.loads(paths["contracts"].read_text(encoding="utf-8"))
    assert contracts.get("players") == {}

    header = paths["transactions"].read_text(encoding="utf-8").strip()
    assert header.split(",") == list(FINANCIAL_TRANSACTIONS_HEADER)


def test_ensure_financial_defaults_preserves_existing_contracts_and_ledger(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            "AAA,Alphas,Alpha,AAA,East,Alpha Park,#111111,#222222,\n"
            "BBB,Bruins,Beta,BBB,East,Beta Park,#111111,#222222,\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "team_financials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "season_year": 2030,
                "teams": {
                    "AAA": {
                        "cash_on_hand": 1234,
                        "debt": 0,
                        "revenue": {"tickets": 10, "concessions": 0, "media": 0, "sponsorship": 0},
                        "expenses": {"payroll": 0, "training": 0, "scouting": 0, "facilities": 0, "operations": 0},
                        "budgets": {"training": 0, "scouting": 0, "development": 0, "facilities": 0},
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "contracts.json").write_text(
        json.dumps(
            {"version": 1, "players": {"P1": {"team_id": "AAA", "annual_salary": 1_000_000}}},
            indent=2,
        ),
        encoding="utf-8",
    )
    existing_ledger = (
        "timestamp,season_year,team_id,category,amount,memo\n"
        "2026-01-01T00:00:00Z,2026,AAA,tickets,1000,seed\n"
    )
    (data_dir / "financial_transactions.csv").write_text(existing_ledger, encoding="utf-8")

    paths = ensure_financial_defaults(data_dir=data_dir, league_id="alpha")

    team_financials = json.loads(paths["team_financials"].read_text(encoding="utf-8"))
    assert team_financials["teams"]["AAA"]["cash_on_hand"] == 1234
    assert "BBB" in team_financials["teams"]

    contracts = json.loads(paths["contracts"].read_text(encoding="utf-8"))
    assert "P1" in contracts.get("players", {})

    assert paths["transactions"].read_text(encoding="utf-8") == existing_ledger


def test_ensure_financial_defaults_for_all_leagues(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    import utils.path_utils as path_utils
    import services.league_registry as league_registry
    import services.finance_settings as finance_settings

    importlib.reload(path_utils)
    path_utils._DATA_DIR = None
    importlib.reload(league_registry)
    finance_settings = importlib.reload(finance_settings)

    league_registry.register_league("alpha", display_name="Alpha")
    league_registry.register_league("beta", display_name="Beta")
    for league_id in ("alpha", "beta"):
        league_data = league_registry.get_league_data_dir(league_id, create=True)
        (league_data / "teams.csv").write_text(
            (
                "team_id,name,city,abbreviation,division,stadium,primary_color,"
                "secondary_color,owner_id\n"
                f"{league_id[:3].upper()},Team,{league_id},ABR,East,Park,#111111,#222222,\n"
            ),
            encoding="utf-8",
        )

    results = finance_settings.ensure_financial_defaults_for_all_leagues()

    assert set(results.keys()) == {"alpha", "beta"}
    for league_id in ("alpha", "beta"):
        league_data = league_registry.get_league_data_dir(league_id, create=False)
        assert (league_data / "league_financial_settings.json").exists()
        assert (league_data / "team_financials.json").exists()
        assert (league_data / "contracts.json").exists()
        assert (league_data / "financial_transactions.csv").exists()


def test_update_finance_ai_tuning_persists_and_normalizes(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    apply_financial_preset(PRESET_SIMPLE, path=path, league_id="alpha")

    updated = update_financial_settings(
        league_id="alpha",
        path=path,
        finance_ai_tuning={
            "star_talent_threshold": 82,
            "high_cost_salary_share": 0.23,
            "max_raise_pct": 1.75,  # should clamp
            "fa_cautious_avoid_salary": 15_500_000,
            "unknown_key": 999,
        },
    )

    assert updated.finance_ai_tuning["star_talent_threshold"] == 82
    assert updated.finance_ai_tuning["high_cost_salary_share"] == 0.23
    assert updated.finance_ai_tuning["max_raise_pct"] == 1.0
    assert updated.finance_ai_tuning["fa_cautious_avoid_salary"] == 15_500_000


def test_update_finance_ai_tuning_normalizes_commitment_keys(tmp_path):
    path = tmp_path / "league_financial_settings.json"
    apply_financial_preset(PRESET_SIMPLE, path=path, league_id="alpha")

    updated = update_financial_settings(
        league_id="alpha",
        path=path,
        finance_ai_tuning={
            "commitment_pressure_ratio": 3.5,
            "commitment_relief_ratio": -1.0,
            "commitment_pressure_penalty": 90_000_000,
            "commitment_relief_bonus": -50_000_000,
            "future_year_commitment_ratio_limit": 5.0,
            "future_year_hard_commitment_ratio_limit": 0.1,
        },
    )

    assert updated.finance_ai_tuning["commitment_pressure_ratio"] == 1.6
    assert updated.finance_ai_tuning["commitment_relief_ratio"] == 0.2
    assert updated.finance_ai_tuning["commitment_pressure_penalty"] == 60_000_000
    assert updated.finance_ai_tuning["commitment_relief_bonus"] == 0
    assert updated.finance_ai_tuning["future_year_commitment_ratio_limit"] == 1.8
    assert updated.finance_ai_tuning["future_year_hard_commitment_ratio_limit"] == 0.9
