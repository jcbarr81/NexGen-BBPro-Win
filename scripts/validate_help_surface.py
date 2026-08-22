#!/usr/bin/env python3
"""Validate tutorial/manual/docs help-surface consistency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# The legacy PyQt owner/admin dashboards were retired with the desktop app; the
# help surface now lives in the React renderer + docs, so this linter validates
# the docs/manuals only.
OWNER_ADMIN_GUIDE = ROOT / "docs" / "owner_admin_guide.md"
GAME_MANUAL = ROOT / "docs" / "manuals" / "game_manual.html"
FINANCE_MANUAL = ROOT / "docs" / "manuals" / "finance_system_manual.html"
POST_INSTALL_CHECKLIST = ROOT / "docs" / "post_installer_ui_checklist.md"

DEFAULT_JSON_OUT = ROOT / "reports" / "release_validation" / "help_surface_validation.json"

ADMIN_WORKFLOW_LABELS = [
    "Admin Dashboard Overview",
    "League Setup & Manager",
    "User Management & Roles",
    "Season Progression Flow",
    "Trade & Review Queues",
    "Exports & Utilities",
]

ADMIN_ASSET_LABELS = [
    "Team Logo Tutorial",
    "Player Avatar Tutorial",
]

MANUAL_LABELS = [
    "Complete Game Manual",
    "Finance System Manual",
]


def _load_text(path: Path, findings: list[dict[str, Any]]) -> str:
    if not path.exists():
        findings.append(
            {
                "severity": "error",
                "code": "file_missing",
                "path": str(path),
                "message": f"Required file not found: {path}",
            }
        )
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        findings.append(
            {
                "severity": "error",
                "code": "file_unreadable",
                "path": str(path),
                "message": f"Unable to read file: {exc}",
            }
        )
        return ""


def _require_contains(
    *,
    text: str,
    token: str,
    path: Path,
    findings: list[dict[str, Any]],
    code: str,
) -> None:
    if token in text:
        return
    findings.append(
        {
            "severity": "error",
            "code": code,
            "path": str(path),
            "message": f"Missing expected text: {token}",
        }
    )


def _require_absent(
    *,
    text: str,
    token: str,
    path: Path,
    findings: list[dict[str, Any]],
    code: str,
) -> None:
    if token not in text:
        return
    findings.append(
        {
            "severity": "error",
            "code": code,
            "path": str(path),
            "message": f"Found stale text that should be removed: {token}",
        }
    )


def run_validation() -> dict[str, Any]:
    findings: list[dict[str, Any]] = []

    guide = _load_text(OWNER_ADMIN_GUIDE, findings)
    game_manual = _load_text(GAME_MANUAL, findings)
    finance_manual = _load_text(FINANCE_MANUAL, findings)
    checklist = _load_text(POST_INSTALL_CHECKLIST, findings)

    for label in ADMIN_WORKFLOW_LABELS:
        _require_contains(
            text=guide,
            token=label,
            path=OWNER_ADMIN_GUIDE,
            findings=findings,
            code="admin_workflow_missing_in_docs",
        )

    for label in ADMIN_ASSET_LABELS:
        _require_contains(
            text=guide,
            token=label,
            path=OWNER_ADMIN_GUIDE,
            findings=findings,
            code="admin_asset_tutorial_missing_in_docs",
        )

    for label in MANUAL_LABELS:
        _require_contains(
            text=guide,
            token=label,
            path=OWNER_ADMIN_GUIDE,
            findings=findings,
            code="manual_label_missing_in_docs",
        )

    _require_contains(
        text=guide,
        token="Tutorials -> Commissioner Workflows",
        path=OWNER_ADMIN_GUIDE,
        findings=findings,
        code="admin_tutorial_path_missing_in_docs",
    )
    _require_contains(
        text=guide,
        token="Tutorials -> Asset Guides",
        path=OWNER_ADMIN_GUIDE,
        findings=findings,
        code="admin_asset_path_missing_in_docs",
    )
    _require_contains(
        text=guide,
        token="Tutorials -> Reference Manuals",
        path=OWNER_ADMIN_GUIDE,
        findings=findings,
        code="manual_path_missing_in_docs",
    )
    _require_contains(
        text=guide,
        token="first launch",
        path=OWNER_ADMIN_GUIDE,
        findings=findings,
        code="admin_onboarding_note_missing_in_docs",
    )
    _require_contains(
        text=game_manual,
        token="NexGen-BBPro Complete Game Manual",
        path=GAME_MANUAL,
        findings=findings,
        code="game_manual_title_missing",
    )
    _require_contains(
        text=finance_manual,
        token="NexGen-BBPro Finance System Manual",
        path=FINANCE_MANUAL,
        findings=findings,
        code="finance_manual_title_missing",
    )

    _require_contains(
        text=checklist,
        token="Confirm updated tutorials are visible from Tutorials menu.",
        path=POST_INSTALL_CHECKLIST,
        findings=findings,
        code="tutorial_check_missing_in_ui_checklist",
    )
    _require_contains(
        text=checklist,
        token="Confirm owner/admin guide links/content match current navigation labels.",
        path=POST_INSTALL_CHECKLIST,
        findings=findings,
        code="owner_admin_guide_check_missing_in_ui_checklist",
    )

    errors = [item for item in findings if item.get("severity") == "error"]
    return {
        "status": "pass" if not errors else "fail",
        "error_count": len(errors),
        "findings": findings,
        "checked_files": [
            str(OWNER_ADMIN_GUIDE),
            str(GAME_MANUAL),
            str(FINANCE_MANUAL),
            str(POST_INSTALL_CHECKLIST),
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate tutorial/manual/docs surface consistency.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help="Write validation report JSON to this path.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    report = run_validation()

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote help-surface validation report: {out_path}")

    if report.get("status") == "pass":
        print("Help-surface validation passed.")
        return 0

    print(f"Help-surface validation failed ({report.get('error_count', 0)} errors).")
    for finding in report.get("findings", []):
        if finding.get("severity") != "error":
            continue
        print(f"- [{finding.get('code')}] {finding.get('path')}: {finding.get('message')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
