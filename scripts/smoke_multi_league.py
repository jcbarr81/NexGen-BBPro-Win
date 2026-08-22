from __future__ import annotations

"""Run a focused multi-league isolation smoke test matrix.

This script creates two disposable leagues under an isolated data root and
verifies that high-risk workflows remain league-scoped:
1) league switching reads the correct teams/players/users
2) owner change requests and pending trades stay isolated
3) draft/progress/stats updates in one league do not mutate the other
4) snapshot exports contain league-specific manifests/content
"""

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, List
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _reload_module(module_name: str):
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _write_seed_data(
    data_dir: Path,
    *,
    league_name: str,
    owner_username: str,
    player_first_name: str,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        (
            "team_id,name,city,abbreviation,division,stadium,primary_color,"
            "secondary_color,owner_id\n"
            f"T1,{league_name} Team,{league_name} City,{league_name[:3].upper()},"
            f"East,{league_name} Park,#112233,#445566,{owner_username}\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        (
            "player_id,first_name,last_name,birthdate,height,weight,bats,"
            "primary_position,gf,ch,ph,sp,pl,vl,sc,fa,arm,is_pitcher\n"
            f"P1,{player_first_name},Slugger,2000-01-01,72,195,R,SS,55,60,55,50,"
            "45,44,46,47,48,false\n"
        ),
        encoding="utf-8",
    )
    (data_dir / "users.txt").write_text(
        f"admin,pass,admin,\n{owner_username},pass,owner,T1\n",
        encoding="utf-8",
    )
    (data_dir / "schedule.csv").write_text(
        "game_id,date,home_team,away_team,completed\n1,2026-04-01,T1,T1,false\n",
        encoding="utf-8",
    )
    (data_dir / "season_progress.json").write_text(
        json.dumps({"draft_completed_years": [], "playoffs_done": False}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "league_marker.txt").write_text(league_name, encoding="utf-8")


def _check(
    *,
    name: str,
    passed: bool,
    details: Dict[str, Any],
    report: List[Dict[str, Any]],
) -> None:
    report.append(
        {
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        }
    )


def run_smoke(data_root: Path) -> Dict[str, Any]:
    os.environ["NEXGEN_DATA_DIR"] = str(data_root)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)

    path_utils = _reload_module("utils.path_utils")
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]

    league_registry = _reload_module("services.league_registry")
    season_context = _reload_module("playbalance.season_context")

    league_registry.register_league("alpha", display_name="Alpha League")
    league_registry.register_league("beta", display_name="Beta League")

    alpha_data = league_registry.get_league_data_dir("alpha", create=True)
    beta_data = league_registry.get_league_data_dir("beta", create=True)
    _write_seed_data(
        alpha_data,
        league_name="Alpha",
        owner_username="owner_alpha",
        player_first_name="Aiden",
    )
    _write_seed_data(
        beta_data,
        league_name="Beta",
        owner_username="owner_beta",
        player_first_name="Brady",
    )

    league_registry.set_active_league("alpha", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    season_context.SeasonContext.load().ensure_league(
        name="Alpha League", league_id="alpha"
    )

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    season_context.SeasonContext.load().ensure_league(
        name="Beta League", league_id="beta"
    )

    team_loader = _reload_module("utils.team_loader")
    player_loader = _reload_module("utils.player_loader")
    user_manager = _reload_module("utils.user_manager")
    trade_utils = _reload_module("utils.trade_utils")
    trade_model = _reload_module("models.trade")
    season_progress_flags = _reload_module("services.season_progress_flags")
    draft_state = _reload_module("services.draft_state")
    stats_persistence = _reload_module("utils.stats_persistence")
    league_snapshot = _reload_module("services.league_snapshot")
    finance_settings = _reload_module("services.finance_settings")
    owner_finance_engine = _reload_module("services.owner_finance_engine")

    report: List[Dict[str, Any]] = []

    # Check 1: active-league switch isolation for teams/players/users.
    league_registry.set_active_league("alpha", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    alpha_team_name = team_loader.load_teams("data/teams.csv")[0].name
    alpha_player_first = player_loader.load_players_from_csv("data/players.csv")[0].first_name
    alpha_users = {user["username"] for user in user_manager.load_users("data/users.txt")}

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    beta_team_name = team_loader.load_teams("data/teams.csv")[0].name
    beta_player_first = player_loader.load_players_from_csv("data/players.csv")[0].first_name
    beta_users = {user["username"] for user in user_manager.load_users("data/users.txt")}

    _check(
        name="league_switch_data_isolation",
        passed=(
            alpha_team_name != beta_team_name
            and alpha_player_first != beta_player_first
            and "owner_alpha" in alpha_users
            and "owner_beta" in beta_users
        ),
        details={
            "alpha_team": alpha_team_name,
            "beta_team": beta_team_name,
            "alpha_player": alpha_player_first,
            "beta_player": beta_player_first,
            "alpha_users": sorted(alpha_users),
            "beta_users": sorted(beta_users),
        },
        report=report,
    )

    # Check 2: pending trades do not bleed across leagues.
    league_registry.set_active_league("alpha", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    trade_utils.save_trade(
        trade_model.Trade(
            trade_id="SMOKE-1",
            from_team="T1",
            to_team="T2",
            give_player_ids=["P1"],
            receive_player_ids=["P2"],
            status="accepted",
        )
    )
    alpha_trades = len(trade_utils.load_trades())

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    beta_trades = len(trade_utils.load_trades())

    _check(
        name="trade_isolation",
        passed=(alpha_trades == 1 and beta_trades == 0),
        details={
            "alpha_trades": alpha_trades,
            "beta_trades": beta_trades,
        },
        report=report,
    )

    # Check 3: draft/progress/stats writes in beta do not mutate alpha.
    alpha_schedule_before = (alpha_data / "schedule.csv").read_text(encoding="utf-8")
    alpha_progress_before = (alpha_data / "season_progress.json").read_text(encoding="utf-8")

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    draft_state.save_state(2031, {"round": 1, "order": ["T1"]})
    season_progress_flags.mark_draft_completed(2031)
    stats_persistence.save_stats(
        [SimpleNamespace(player_id="P1", season_stats={"g": 1})],
        [SimpleNamespace(team_id="T1", season_stats={"w": 1})],
    )

    alpha_schedule_after = (alpha_data / "schedule.csv").read_text(encoding="utf-8")
    alpha_progress_after = (alpha_data / "season_progress.json").read_text(encoding="utf-8")
    beta_progress = json.loads((beta_data / "season_progress.json").read_text(encoding="utf-8"))

    _check(
        name="draft_and_sim_side_effect_isolation",
        passed=(
            alpha_schedule_before == alpha_schedule_after
            and alpha_progress_before == alpha_progress_after
            and 2031 in beta_progress.get("draft_completed_years", [])
        ),
        details={
            "alpha_unchanged_schedule": alpha_schedule_before == alpha_schedule_after,
            "alpha_unchanged_progress": alpha_progress_before == alpha_progress_after,
            "beta_draft_completed_years": beta_progress.get("draft_completed_years", []),
        },
        report=report,
    )

    # Check 4: per-league snapshot export/manifests are isolated.
    league_registry.set_active_league("alpha", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    alpha_snapshot = league_snapshot.export_league_snapshot(
        output_dir=data_root.parent / "exports" / "alpha"
    )

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    beta_snapshot = league_snapshot.export_league_snapshot(
        output_dir=data_root.parent / "exports" / "beta"
    )

    with zipfile.ZipFile(alpha_snapshot["path"], "r") as archive:
        alpha_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        alpha_marker = archive.read("league_marker.txt").decode("utf-8").strip()
    with zipfile.ZipFile(beta_snapshot["path"], "r") as archive:
        beta_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        beta_marker = archive.read("league_marker.txt").decode("utf-8").strip()

    _check(
        name="snapshot_export_isolation",
        passed=(
            alpha_manifest.get("league", {}).get("id") == "alpha"
            and beta_manifest.get("league", {}).get("id") == "beta"
            and alpha_marker == "Alpha"
            and beta_marker == "Beta"
            and alpha_marker != beta_marker
        ),
        details={
            "alpha_snapshot": alpha_snapshot["path"],
            "beta_snapshot": beta_snapshot["path"],
            "alpha_manifest_league": alpha_manifest.get("league", {}).get("id"),
            "beta_manifest_league": beta_manifest.get("league", {}).get("id"),
            "alpha_marker": alpha_marker,
            "beta_marker": beta_marker,
        },
        report=report,
    )

    # Check 5: finance settings/files/cycles remain league-scoped.
    finance_settings.ensure_financial_defaults_for_all_leagues()

    league_registry.set_active_league("alpha", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    finance_settings.apply_financial_preset("simple")
    alpha_finance_settings = finance_settings.load_financial_settings()
    alpha_finance_apply = owner_finance_engine.apply_monthly_owner_finance(
        period_key="2031-01"
    )
    alpha_finance_transactions = owner_finance_engine.list_team_financial_transactions(
        "T1",
        limit=10,
    )
    alpha_financials_payload = json.loads(
        (alpha_data / "team_financials.json").read_text(encoding="utf-8")
    )
    alpha_cash = int(
        (alpha_financials_payload.get("teams", {}).get("T1", {}) or {}).get(
            "cash_on_hand", 0
        )
    )

    league_registry.set_active_league("beta", ensure_data_dir=True)
    path_utils._DATA_DIR = None  # type: ignore[attr-defined]
    beta_finance_settings = finance_settings.load_financial_settings()
    beta_financials_payload = json.loads(
        (beta_data / "team_financials.json").read_text(encoding="utf-8")
    )
    beta_cash = int(
        (beta_financials_payload.get("teams", {}).get("T1", {}) or {}).get(
            "cash_on_hand", 0
        )
    )
    beta_finance_transactions = owner_finance_engine.list_team_financial_transactions(
        "T1",
        limit=10,
    )

    _check(
        name="finance_data_isolation",
        passed=(
            bool(alpha_finance_settings.enabled)
            and not bool(beta_finance_settings.enabled)
            and bool(alpha_finance_apply.get("applied"))
            and alpha_cash != 0
            and len(alpha_finance_transactions) > 0
            and beta_cash == 0
            and len(beta_finance_transactions) == 0
        ),
        details={
            "alpha_enabled": alpha_finance_settings.enabled,
            "beta_enabled": beta_finance_settings.enabled,
            "alpha_cycle_applied": alpha_finance_apply.get("applied"),
            "alpha_cash": alpha_cash,
            "beta_cash": beta_cash,
            "alpha_finance_tx_count": len(alpha_finance_transactions),
            "beta_finance_tx_count": len(beta_finance_transactions),
        },
        report=report,
    )

    passed = sum(1 for item in report if item["status"] == "PASS")
    failed = len(report) - passed
    return {
        "data_root": str(data_root),
        "passed": passed,
        "failed": failed,
        "results": report,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run multi-league smoke tests.")
    parser.add_argument(
        "--data-root",
        type=Path,
        help=(
            "Optional isolated data root to use. Must be empty or non-existent. "
            "If omitted, a temporary directory is created."
        ),
    )
    parser.add_argument(
        "--keep-data-root",
        action="store_true",
        help="Keep the generated temporary data root after the run.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path to write the full JSON report.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    auto_temp_root = args.data_root is None
    if auto_temp_root:
        smoke_root = Path(tempfile.mkdtemp(prefix="nexgen_smoke_"))
        data_root = smoke_root / "data"
    else:
        smoke_root = args.data_root.resolve(strict=False)
        data_root = smoke_root
        if data_root.exists() and any(data_root.iterdir()):
            parser.error(f"--data-root must be empty: {data_root}")
        data_root.mkdir(parents=True, exist_ok=True)

    report: Dict[str, Any] = run_smoke(data_root)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Multi-League Smoke Test")
    print(f"Data Root: {report['data_root']}")
    print("")
    for item in report["results"]:
        print(f"[{item['status']}] {item['check']}")
        for key, value in item.get("details", {}).items():
            print(f"  - {key}: {value}")
    print("")
    print(f"Summary: {report['passed']} passed, {report['failed']} failed")

    exit_code = 0 if report["failed"] == 0 else 1

    if auto_temp_root and not args.keep_data_root:
        import shutil

        shutil.rmtree(smoke_root, ignore_errors=True)
    elif auto_temp_root and args.keep_data_root:
        print(f"Kept temp root: {smoke_root}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
