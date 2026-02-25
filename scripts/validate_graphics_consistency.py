#!/usr/bin/env python3
"""Validate developer-generated graphics consistency against style rules."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.graphics_consistency import validate_assets, write_report
from utils.graphics_style import get_profile, load_manifest


DEFAULT_JSON_OUT = ROOT / "reports" / "graphics_validation" / "graphics_consistency_validation.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate generated graphics consistency against manifest thresholds.",
    )
    parser.add_argument(
        "--manifest",
        default="config/graphics_style_manifest.json",
        help="Path to graphics style manifest.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional style profile id (defaults to manifest default_profile).",
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing generated graphics files.",
    )
    parser.add_argument(
        "--json-out",
        default=str(DEFAULT_JSON_OUT),
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when validation status is fail.",
    )
    return parser


def _categorize(path: Path) -> str | None:
    parts = {part.lower() for part in path.parts}
    if "logos" in parts:
        return "logo"
    if "ui" in parts:
        return "ui"
    # Fallback naming conventions.
    name = path.stem.lower()
    if name.startswith("logo_"):
        return "logo"
    if name.startswith("ui_"):
        return "ui"
    return None


def _collect_assets(input_dir: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for path in sorted(input_dir.rglob("*.png")):
        category = _categorize(path)
        if category is None:
            continue
        assets.append(
            {
                "path": str(path),
                "category": category,
                "asset_id": path.stem,
            }
        )
    return assets


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    selected_profile, _ = get_profile(manifest, args.profile)

    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = ROOT / input_dir
    if not input_dir.exists():
        raise SystemExit(f"Input directory not found: {input_dir}")

    assets = _collect_assets(input_dir)
    report = validate_assets(
        assets,
        manifest=manifest,
        profile_id=selected_profile,
    )
    report["profile"] = selected_profile
    report["input_dir"] = str(input_dir)
    report["developer_only"] = True

    json_out = Path(args.json_out)
    if not json_out.is_absolute():
        json_out = ROOT / json_out
    write_report(report, json_out)
    print(f"Validation status: {report['status']} (errors: {report['error_count']})")
    print(f"Report written: {json_out}")

    if args.strict and report["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
