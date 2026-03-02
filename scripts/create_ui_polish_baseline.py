#!/usr/bin/env python3
"""Create a UI polish baseline checklist bundle for core screens."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
DEFAULT_OUT_DIR = ROOT / "reports" / "ui_polish_baselines"
RUBRIC_PATH = ROOT / "docs" / "ui_polish_rubric.md"

DEFAULT_SCREENS = (
    {
        "id": "lineups",
        "title": "Lineups",
        "class_name": "LineupEditor",
        "source_path": "ui/lineup_editor.py",
    },
    {
        "id": "pitching",
        "title": "Pitching Staff",
        "class_name": "PitchingEditor",
        "source_path": "ui/pitching_editor.py",
    },
    {
        "id": "trades",
        "title": "Trades",
        "class_name": "TradeDialog",
        "source_path": "ui/trade_dialog.py",
    },
    {
        "id": "standings",
        "title": "Standings",
        "class_name": "StandingsWindow",
        "source_path": "ui/standings_window.py",
    },
    {
        "id": "schedule",
        "title": "Schedule",
        "class_name": "ScheduleWindow",
        "source_path": "ui/schedule_window.py",
    },
)

CRITERIA = (
    "Layout density and spacing",
    "Typography and readability",
    "Action clarity and button hierarchy",
    "Visual consistency with theme",
    "State/feedback clarity (loading, empty, errors)",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a baseline UI polish checklist artifact.",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Version marker for this baseline. Defaults to VERSION file.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for UI polish baseline bundles.",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="Optional run tag appended to output directory name.",
    )
    parser.add_argument(
        "--screen",
        action="append",
        default=[],
        help="Optional screen id filter (can be used multiple times).",
    )
    parser.add_argument(
        "--touch-placeholders",
        action="store_true",
        help="Create placeholder text files for screenshot paths.",
    )
    return parser


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _read_version(version_arg: str) -> str:
    token = str(version_arg or "").strip()
    if token:
        return token
    if not VERSION_FILE.exists():
        raise FileNotFoundError(f"VERSION file not found: {VERSION_FILE}")
    file_version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not file_version:
        raise ValueError("VERSION file is empty.")
    return file_version


def _select_screens(filters: list[str]) -> list[dict[str, str]]:
    selected = list(DEFAULT_SCREENS)
    tokens = [str(item or "").strip().lower() for item in filters if str(item or "").strip()]
    if not tokens:
        return selected

    id_map = {entry["id"]: entry for entry in DEFAULT_SCREENS}
    unknown = [token for token in tokens if token not in id_map]
    if unknown:
        allowed = ", ".join(sorted(id_map))
        raise ValueError(
            "Unknown --screen value(s): "
            + ", ".join(unknown)
            + f". Allowed values: {allowed}"
        )
    return [id_map[token] for token in tokens]


def _write_checklist(
    path: Path,
    *,
    version: str,
    created_utc: str,
    run_id: str,
    screens: list[dict[str, str]],
) -> None:
    lines: list[str] = [
        f"# UI Polish Baseline Checklist - v{version}",
        f"Run ID: {run_id}",
        f"Generated UTC: {created_utc}",
        "Checklist Result: PENDING",
        "",
        f"Rubric: `{RUBRIC_PATH.relative_to(ROOT).as_posix()}`",
        "",
        "Scoring: 1 (poor) to 5 (ship-ready).",
        "",
    ]
    for screen in screens:
        screen_id = screen["id"]
        lines.extend(
            [
                f"## {screen['title']} (`{screen_id}`)",
                f"Class: `{screen['class_name']}`",
                f"Source: `{screen['source_path']}`",
                f"Screenshot path: `screens/{screen_id}.png`",
                "",
                "| Criteria | Score (1-5) | Notes |",
                "|---|---:|---|",
            ]
        )
        for criterion in CRITERIA:
            lines.append(f"| {criterion} |  |  |")
        lines.extend(["", "Summary notes:", "- ", "", "---", ""])

    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    version = _read_version(args.version)
    screens = _select_screens(args.screen)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    tag = _slug(str(args.tag or ""))
    run_id = f"ui_polish_baseline_v{version}_{timestamp}"
    if tag:
        run_id = f"{run_id}_{tag}"

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    run_dir = out_dir / run_id
    screens_dir = run_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)

    created_utc = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    checklist_path = run_dir / "checklist.md"
    _write_checklist(
        checklist_path,
        version=version,
        created_utc=created_utc,
        run_id=run_id,
        screens=screens,
    )

    if args.touch_placeholders:
        for screen in screens:
            placeholder = screens_dir / f"{screen['id']}.placeholder.txt"
            placeholder.write_text(
                "Capture screenshot and save as "
                f"'{screen['id']}.png' in this directory.\n",
                encoding="utf-8",
            )

    payload = {
        "status": "pending",
        "version": version,
        "run_id": run_id,
        "created_utc": created_utc,
        "rubric_path": RUBRIC_PATH.relative_to(ROOT).as_posix(),
        "checklist_path": checklist_path.relative_to(ROOT).as_posix(),
        "screens": screens,
    }
    (run_dir / "index.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote UI polish baseline bundle: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
