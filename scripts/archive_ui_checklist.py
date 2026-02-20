#!/usr/bin/env python3
"""Archive a manual UI/installer checklist artifact for a release."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "post_installer_ui_checklist.md"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "release_validation" / "checklists"
RESULT_TOKENS = {"pass", "fail", "pending"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive manual UI/installer checklist for release artifacts."
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version this checklist applies to (for example 5.0.74).",
    )
    parser.add_argument(
        "--result",
        default="pending",
        help="Checklist result: pass, fail, or pending (default: pending).",
    )
    parser.add_argument(
        "--tester",
        default="",
        help="Optional tester/operator name.",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional short notes for this checklist run.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Source checklist markdown path.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for archived checklist artifacts.",
    )
    return parser


def _normalize_result(value: str) -> str:
    token = str(value or "").strip().lower()
    if token not in RESULT_TOKENS:
        token = "pending"
    return token


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    version = str(args.version or "").strip()
    if not version:
        raise SystemExit("Version is required.")
    result = _normalize_result(args.result)
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Checklist source not found: {source}")

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ui_installer_checklist_v{version}_{stamp}.md"

    body = source.read_text(encoding="utf-8")
    lines = [
        f"# UI/Installer Checklist Archive - v{version}",
        f"Generated UTC: {datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"Checklist Result: {result.upper()}",
        f"Tester: {str(args.tester or '').strip() or '--'}",
        f"Notes: {str(args.notes or '').strip() or '--'}",
        "",
        f"Source Checklist: `{source.relative_to(ROOT) if source.is_relative_to(ROOT) else source}`",
        "",
        "---",
        "",
        body.rstrip(),
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote checklist artifact: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
