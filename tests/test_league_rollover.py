from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
import importlib

import pytest


MODULE_MAP = {
    "season_context": "playbalance.season_context",
    "rollover": "services.league_rollover",
    "player_loader": "utils.player_loader",
    "team_loader": "utils.team_loader",
    "stats_persistence": "utils.stats_persistence",
    "transaction_log": "services.transaction_log",
}


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Patch base directory and reload rollover-related modules against a temp tree."""

    from utils import path_utils

    monkeypatch.setattr(path_utils, "get_base_dir", lambda: tmp_path)

    modules = {}
    for alias, name in MODULE_MAP.items():
        if name in sys.modules:
            modules[alias] = importlib.reload(sys.modules[name])
        else:
            modules[alias] = importlib.import_module(name)

    yield SimpleNamespace(base=tmp_path, modules=modules, **modules)

    for name in MODULE_MAP.values():
        sys.modules.pop(name, None)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _simple_schedule(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,home,away,result,played,boxscore\n2025-04-01,T1,T2,,0,\n",
        encoding="utf-8",
    )


def _transactions_file(path: Path):
    headers = [
        "timestamp",
        "season_date",
        "team_id",
        "player_id",
        "player_name",
        "action",
        "from_level",
        "to_level",
        "counterparty",
        "details",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(",".join(headers) + "\n")
        fh.write("2025-08-01 12:00:00,2025-08-01,T1,BAT1,Slugger Callup,callup,AAA,ACT,,\n")


def test_season_context_archive(sandbox):
    ctx_mod = sandbox.season_context
    ctx = ctx_mod.SeasonContext.load()
    ctx.ensure_league(name="Test League", league_id="test")
    current = ctx.ensure_current_season(league_year=2025, started_on="2025-04-01")
    assert current["season_id"] == "test-2025"

    next_desc = ctx.archive_current_season(
        artifacts={"stats": "data/careers/test-2025/stats.json"}, ended_on="2025-10-10"
    )
    assert ctx.has_archived_season("test-2025")
    assert next_desc["season_id"] == "test-2026"

    stored = json.loads((sandbox.base / "data" / "career_index.json").read_text(encoding="utf-8"))
    assert stored["current"]["season_id"] == "test-2026"
    assert stored["seasons"][-1]["season_id"] == "test-2025"


def test_league_rollover_archives_and_resets(sandbox, monkeypatch):
    base = sandbox.base
    data_dir = base / "data"
    (data_dir / "season_history").mkdir(parents=True, exist_ok=True)
    _write_json(
        data_dir / "season_stats.json",
        {
            "players": {
                "BAT1": {"pa": 100, "ab": 80, "h": 28, "ops": 0.950},
                "PIT1": {"ip": 180, "era": 3.25, "pa": 10, "ab": 8, "h": 1},
            },
            "teams": {"T1": {"g": 162, "w": 98, "l": 64}},
            "history": [],
        },
    )
    _write_json(data_dir / "standings.json", {"T1": {"wins": 98, "losses": 64}})
    _write_json(data_dir / "season_progress.json", {"sim_index": 162})
    _write_json(
        data_dir / "season_history" / "2025-10-10.json",
        {"players": {"BAT1": {"pa": 100}}, "teams": {"T1": {"w": 98}}, "date": "2025-10-10"},
    )
    _transactions_file(data_dir / "transactions.csv")
    _simple_schedule(data_dir / "schedule.csv")
    _write_json(data_dir / "playoffs_2025.json", {"champion": "T1", "runner_up": "T2"})
    (data_dir / "champions.csv").write_text(
        "year,champion,runner_up,series_result\n2025,T1,T2,4-2\n",
        encoding="utf-8",
    )
    _write_json(data_dir / "pitcher_recovery.json", {"last_reset": "2025-10-10"})
    _write_json(data_dir / "draft_pool_2025.json", {"players": []})
    (data_dir / "draft_results_2025.csv").write_text(
        "round,pick,player\n1,1,BAT1\n",
        encoding="utf-8",
    )
    _write_json(data_dir / "draft_state_2025.json", {"status": "complete"})
    _write_json(
        data_dir / "league_financial_settings.json",
        {
            "version": 1,
            "leagues": {
                "test": {
                    "enabled": True,
                    "preset": "standard",
                    "enforcement_mode": "warn",
                    "modules": {
                        "owner_revenue": "advanced",
                        "owner_market_model": "basic",
                        "owner_budgets": "advanced",
                        "owner_expenses": "advanced",
                        "gm_contracts": "advanced",
                        "gm_payroll_rules": "basic",
                        "gm_arbitration": "basic",
                        "gm_free_agency": "advanced",
                        "gm_roster_cost_enforcement": "warn",
                        "gm_finance_ai": "advanced",
                    },
                }
            },
        },
    )
    _write_json(
        data_dir / "team_financials.json",
        {
            "version": 1,
            "season_year": 2025,
            "teams": {
                "T1": {
                    "cash_on_hand": 1_500_000,
                    "debt": 0,
                    "revenue": {
                        "tickets": 100_000,
                        "concessions": 20_000,
                        "media": 15_000,
                        "sponsorship": 10_000,
                    },
                    "expenses": {
                        "payroll": 80_000,
                        "training": 5_000,
                        "scouting": 4_000,
                        "facilities": 3_000,
                        "operations": 6_000,
                    },
                    "budgets": {
                        "training": 1_000,
                        "scouting": 1_000,
                        "development": 1_000,
                        "facilities": 1_000,
                    },
                }
            },
        },
    )
    _write_json(
        data_dir / "contracts.json",
        {
            "version": 1,
            "players": {
                "BAT1": {
                    "team_id": "T1",
                    "years_left": 2,
                    "annual_salary": 8_000_000,
                    "fa_year": 2027,
                },
                "PIT1": {
                    "team_id": "T1",
                    "years_left": 1,
                    "annual_salary": 4_000_000,
                    "fa_year": 2026,
                },
            },
        },
    )

    roster_dir = data_dir / "rosters"
    roster_dir.mkdir(parents=True, exist_ok=True)
    roster_file = roster_dir / "T1.csv"
    roster_file.write_text(
        "player_id,level\nBAT1,ACT\nPIT1,AAA\n",
        encoding="utf-8",
    )
    try:
        roster_file.chmod(0o444)
    except PermissionError:
        pass

    ctx_mod = sandbox.season_context
    ctx = ctx_mod.SeasonContext.load()
    ctx.ensure_league(name="Test League", league_id="test")
    ctx.ensure_current_season(league_year=2025, started_on="2025-04-01")

    rollover_mod = sandbox.rollover

    monkeypatch.setattr(
        rollover_mod,
        "load_players_from_csv",
        lambda _path: [
            SimpleNamespace(player_id="BAT1", first_name="Slug", last_name="Gerr"),
            SimpleNamespace(player_id="PIT1", first_name="Ace", last_name="Pitch"),
        ],
    )

    class _StubAwards:
        def __init__(self, players, batting, pitching, **_kwargs):
            self.players = players

        def select_award_winners(self):
            return {
                "MVP": SimpleNamespace(
                    player=SimpleNamespace(player_id="BAT1", first_name="Slug", last_name="Gerr"),
                    metric=0.95,
                ),
                "CY_YOUNG": SimpleNamespace(
                    player=SimpleNamespace(player_id="PIT1", first_name="Ace", last_name="Pitch"),
                    metric=3.25,
                ),
            }

    monkeypatch.setattr(rollover_mod, "AwardsManager", _StubAwards)
    monkeypatch.setattr(rollover_mod, "reset_transaction_cache", lambda: None)

    service = rollover_mod.LeagueRolloverService()
    result = service.archive_season()

    assert result.status == "archived"
    assert result.season_id == "test-2025"
    assert result.contract_rollover is not None
    assert result.contract_rollover.get("retained") == 1
    assert result.contract_rollover.get("expired") == 1
    assert result.contract_rollover.get("released_from_rosters") == 1
    assert result.finance_rollover is not None
    assert result.finance_rollover.get("next_season_year") == 2026

    archive_dir = data_dir / "careers" / "test-2025"
    assert (archive_dir / "stats.json").exists()
    assert (archive_dir / "standings.json").exists()
    assert (archive_dir / "history").is_dir()
    assert (archive_dir / "awards.json").exists()
    assert (archive_dir / "metadata.json").exists()

    stats_after = json.loads((data_dir / "season_stats.json").read_text(encoding="utf-8"))
    assert stats_after == {"players": {}, "teams": {}, "history": []}

    standings_after = json.loads((data_dir / "standings.json").read_text(encoding="utf-8"))
    assert standings_after == {}

    assert not (data_dir / "schedule.csv").exists()
    assert not (data_dir / "playoffs_2025.json").exists()
    assert not (data_dir / "pitcher_recovery.json").exists()

    tx_lines = (data_dir / "transactions.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(tx_lines) == 1  # header only

    ctx_reloaded = ctx_mod.SeasonContext.load()
    assert ctx_reloaded.current.get("league_year") == 2026
    assert ctx_reloaded.current.get("season_id") == "test-2026"

    career_players = json.loads((data_dir / "careers" / "career_players.json").read_text(encoding="utf-8"))
    assert "BAT1" in career_players["players"]
    assert career_players["players"]["BAT1"]["seasons"]["test-2025"]["pa"] == 100

    career_teams = json.loads((data_dir / "careers" / "career_teams.json").read_text(encoding="utf-8"))
    assert "T1" in career_teams["teams"]
    assert career_teams["teams"]["T1"]["totals"]["w"] == 98

    assert (roster_dir / "T1.csv").stat().st_mode & 0o200  # writable bit set

    contracts_after = json.loads((data_dir / "contracts.json").read_text(encoding="utf-8"))
    assert "BAT1" in contracts_after["players"]
    assert contracts_after["players"]["BAT1"]["years_left"] == 1
    assert contracts_after["players"]["BAT1"]["fa_year"] == 2027
    assert "PIT1" not in contracts_after["players"]
    roster_rows = (roster_dir / "T1.csv").read_text(encoding="utf-8")
    assert "PIT1" not in roster_rows
    finance_snapshot = data_dir / "finance_snapshots" / "2025.json"
    assert finance_snapshot.exists()
    financials_after = json.loads((data_dir / "team_financials.json").read_text(encoding="utf-8"))
    assert financials_after["season_year"] == 2026
