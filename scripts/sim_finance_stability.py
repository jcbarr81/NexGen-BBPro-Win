from __future__ import annotations

"""Run multi-season finance stability simulation and emit diagnostics."""

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.finance_stability import (  # noqa: E402
    DEFAULT_STABILITY_GUARDRAILS,
    run_finance_stability_simulation,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run finance stability simulation.")
    parser.add_argument("--seasons", type=int, default=8, help="Number of seasons to simulate.")
    parser.add_argument("--data-dir", type=Path, help="League data directory (defaults to active league).")
    parser.add_argument("--league-id", type=str, help="Optional league id for settings persistence.")
    parser.add_argument(
        "--preset",
        type=str,
        default="standard",
        help="Finance preset to apply before simulation (off/simple/standard/mlb_like/custom).",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic CPU FA bidding.")
    parser.add_argument("--max-fa-rounds", type=int, help="Optional cap on FA rounds per season.")
    parser.add_argument(
        "--warmup-seasons",
        type=int,
        default=0,
        help="Drop the first N seasons from guardrail evaluation to ignore cold-start transients.",
    )
    parser.add_argument("--json-out", type=Path, help="Optional path to write full JSON results.")
    parser.add_argument("--csv-out", type=Path, help="Optional path to write season metrics CSV.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero exit code if guardrails fail.",
    )
    parser.add_argument(
        "--max-distressed-debt-ratio",
        type=float,
        default=DEFAULT_STABILITY_GUARDRAILS["max_distressed_debt_ratio"],
    )
    parser.add_argument(
        "--max-negative-cash-ratio",
        type=float,
        default=DEFAULT_STABILITY_GUARDRAILS["max_negative_cash_ratio"],
    )
    parser.add_argument(
        "--max-unsigned-ratio",
        type=float,
        default=DEFAULT_STABILITY_GUARDRAILS["max_unsigned_ratio"],
    )
    parser.add_argument(
        "--max-payroll-spread-ratio",
        type=float,
        default=DEFAULT_STABILITY_GUARDRAILS["max_payroll_spread_ratio"],
    )
    parser.add_argument(
        "--min-star-retention-rate",
        type=float,
        default=DEFAULT_STABILITY_GUARDRAILS["min_star_retention_rate"],
    )
    return parser


def _write_csv(path: Path, rows: list[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    thresholds = {
        "max_distressed_debt_ratio": float(args.max_distressed_debt_ratio),
        "max_negative_cash_ratio": float(args.max_negative_cash_ratio),
        "max_unsigned_ratio": float(args.max_unsigned_ratio),
        "max_payroll_spread_ratio": float(args.max_payroll_spread_ratio),
        "min_star_retention_rate": float(args.min_star_retention_rate),
    }
    result = run_finance_stability_simulation(
        seasons=max(0, int(args.seasons)),
        data_dir=args.data_dir,
        league_id=args.league_id,
        preset=args.preset,
        seed=args.seed,
        max_fa_rounds=args.max_fa_rounds,
        guardrails=thresholds,
        warmup_seasons=max(0, int(args.warmup_seasons)),
    )
    season_metrics = list(result.get("season_metrics", []) or [])
    guardrails = result.get("guardrails", {})
    checks = guardrails.get("checks", []) if isinstance(guardrails, dict) else []
    passed = bool(guardrails.get("passed", False)) if isinstance(guardrails, dict) else False

    print("Finance Stability Simulation")
    print(f"League: {result.get('league_id')}")
    print(f"Seasons Run: {result.get('seasons_run')}")
    print(f"Preset: {result.get('preset')}")
    print("")
    for check in checks:
        if not isinstance(check, dict):
            continue
        state = "PASS" if bool(check.get("passed")) else "FAIL"
        print(
            f"[{state}] {check.get('name')}: {check.get('value')} "
            f"{check.get('comparator')} {check.get('threshold')}"
        )
    print("")
    print(f"Guardrails: {'PASS' if passed else 'FAIL'}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Wrote JSON: {args.json_out}")
    if args.csv_out:
        _write_csv(args.csv_out, season_metrics)
        print(f"Wrote CSV: {args.csv_out}")
    if args.strict and not passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
