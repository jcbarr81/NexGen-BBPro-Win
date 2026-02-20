#!/usr/bin/env python3
"""Run reusable finance release validation checks."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STABILITY_SCRIPT = ROOT / "scripts" / "sim_finance_stability.py"
SMOKE_MULTI_LEAGUE_SCRIPT = ROOT / "scripts" / "smoke_multi_league.py"
DEFAULT_TESTS = [
    "tests/test_finance_ledger.py",
    "tests/test_finance_ledger_usage.py",
    "tests/test_finance_budget_effects.py",
    "tests/test_finance_stability.py",
    "tests/test_finance_stability_dialog.py",
    "tests/test_finance_reporting.py",
    "tests/test_financial_settings_dialog.py",
    "tests/test_finance_ai.py",
    "tests/test_finance_settings.py",
    "tests/test_contracts_service.py",
    "tests/test_gm_finance_queue.py",
    "tests/test_owner_finance_engine.py",
    "tests/test_payroll_policy.py",
    "tests/test_aging_model.py",
    "tests/test_training_camp.py",
    "tests/test_player_development.py",
    "tests/test_free_agency.py",
    "tests/test_offseason_finance_flow.py",
    "tests/test_offseason_finance_dialog.py",
    "tests/test_owner_finance_page.py",
    "tests/test_archive_ui_checklist.py",
    "tests/test_smoke_multi_league.py",
    "tests/test_phase5_path_isolation.py",
    "tests/test_league_registry.py",
    "tests/test_season_context_paths.py",
    "tests/test_build_release.py",
]


def run_command(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("Running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate finance release quality gates.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip pytest checks.",
    )
    parser.add_argument(
        "--skip-stability",
        action="store_true",
        help="Skip finance stability simulation check.",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip multi-league finance isolation smoke check.",
    )
    parser.add_argument(
        "--seasons",
        type=int,
        default=8,
        help="Number of seasons for strict stability simulation.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for deterministic stability simulation.",
    )
    parser.add_argument(
        "--preset",
        default="standard",
        help="Finance preset used during stability simulation.",
    )
    parser.add_argument(
        "--max-fa-rounds",
        type=int,
        default=0,
        help="Optional cap for FA rounds (0 = auto).",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "reports" / "release_validation",
        help="Directory for stability JSON/CSV artifacts.",
    )
    parser.add_argument(
        "--python",
        help="Python interpreter to use (defaults to current interpreter).",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    python_exe = args.python or sys.executable
    report_dir = Path(args.report_dir)

    if not args.skip_tests:
        run_command([python_exe, "-m", "pytest", *DEFAULT_TESTS], cwd=ROOT)

    if not args.skip_smoke:
        report_dir.mkdir(parents=True, exist_ok=True)
        smoke_json_out = report_dir / "multi_league_smoke_release.json"
        run_command(
            [
                python_exe,
                str(SMOKE_MULTI_LEAGUE_SCRIPT),
                "--json-out",
                str(smoke_json_out),
            ],
            cwd=ROOT,
        )

    if not args.skip_stability:
        report_dir.mkdir(parents=True, exist_ok=True)
        json_out = report_dir / "finance_stability_release.json"
        csv_out = report_dir / "finance_stability_release.csv"
        cmd = [
            python_exe,
            str(STABILITY_SCRIPT),
            "--seasons",
            str(max(1, int(args.seasons))),
            "--seed",
            str(int(args.seed)),
            "--preset",
            str(args.preset),
            "--strict",
            "--json-out",
            str(json_out),
            "--csv-out",
            str(csv_out),
        ]
        if int(args.max_fa_rounds) > 0:
            cmd.extend(["--max-fa-rounds", str(int(args.max_fa_rounds))])
        run_command(cmd, cwd=ROOT)

    print("Finance release validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
