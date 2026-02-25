from __future__ import annotations

from pathlib import Path

import scripts.validate_help_surface as validate_help_surface


def _prepare_surface_files(tmp_path: Path, *, guide_extra: str = "") -> dict[str, Path]:
    owner_ui = tmp_path / "owner_dashboard.py"
    owner_ui.write_text(
        "\n".join(
            [
                'QAction("Complete Game Manual", self)',
                'QAction("Finance System Manual", self)',
            ]
        ),
        encoding="utf-8",
    )

    admin_ui = tmp_path / "_admin_dashboard_legacy.py"
    admin_ui.write_text(
        "\n".join(
            [
                *[f'"{label}"' for label in validate_help_surface.ADMIN_WORKFLOW_LABELS],
                *[f'"{label}"' for label in validate_help_surface.ADMIN_ASSET_LABELS],
                *[f'"{label}"' for label in validate_help_surface.MANUAL_LABELS],
            ]
        ),
        encoding="utf-8",
    )

    guide = tmp_path / "owner_admin_guide.md"
    guide.write_text(
        "\n".join(
            [
                "Tutorials -> Commissioner Workflows",
                "Tutorials -> Asset Guides",
                "Tutorials -> Reference Manuals",
                "first launch",
                "ZIP bundle",
                *validate_help_surface.ADMIN_WORKFLOW_LABELS,
                *validate_help_surface.ADMIN_ASSET_LABELS,
                *validate_help_surface.MANUAL_LABELS,
                guide_extra,
            ]
        ),
        encoding="utf-8",
    )

    game_manual = tmp_path / "game_manual.html"
    game_manual.write_text(
        "NexGen-BBPro Complete Game Manual",
        encoding="utf-8",
    )

    finance_manual = tmp_path / "finance_system_manual.html"
    finance_manual.write_text(
        "NexGen-BBPro Finance System Manual",
        encoding="utf-8",
    )

    checklist = tmp_path / "post_installer_ui_checklist.md"
    checklist.write_text(
        "\n".join(
            [
                "Confirm updated tutorials are visible from Tutorials menu.",
                "Confirm owner/admin guide links/content match current navigation labels.",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "owner_ui": owner_ui,
        "admin_ui": admin_ui,
        "guide": guide,
        "game_manual": game_manual,
        "finance_manual": finance_manual,
        "checklist": checklist,
    }


def _patch_paths(monkeypatch, paths: dict[str, Path]) -> None:
    monkeypatch.setattr(validate_help_surface, "OWNER_DASHBOARD", paths["owner_ui"])
    monkeypatch.setattr(validate_help_surface, "ADMIN_DASHBOARD", paths["admin_ui"])
    monkeypatch.setattr(validate_help_surface, "OWNER_ADMIN_GUIDE", paths["guide"])
    monkeypatch.setattr(validate_help_surface, "GAME_MANUAL", paths["game_manual"])
    monkeypatch.setattr(validate_help_surface, "FINANCE_MANUAL", paths["finance_manual"])
    monkeypatch.setattr(
        validate_help_surface,
        "POST_INSTALL_CHECKLIST",
        paths["checklist"],
    )


def test_validate_help_surface_passes_with_consistent_content(monkeypatch, tmp_path):
    paths = _prepare_surface_files(tmp_path)
    _patch_paths(monkeypatch, paths)
    report = validate_help_surface.run_validation()
    assert report["status"] == "pass"
    assert report["error_count"] == 0


def test_validate_help_surface_flags_stale_json_bundle_wording(monkeypatch, tmp_path):
    paths = _prepare_surface_files(tmp_path, guide_extra="JSON bundle")
    _patch_paths(monkeypatch, paths)
    report = validate_help_surface.run_validation()
    assert report["status"] == "fail"
    codes = {finding["code"] for finding in report["findings"]}
    assert "stale_json_bundle_wording_in_docs" in codes
