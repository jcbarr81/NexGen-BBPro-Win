from __future__ import annotations

import json
from pathlib import Path

from scripts import build_ui_handoff


def _write_manifest(path: Path) -> None:
    payload = {
        "manifest_version": "1.0",
        "default_profile": "retro_modern_v1",
        "openai": {
            "model": "gpt-image-1",
            "size": "1024x1024",
            "background": "transparent",
            "max_retries": 1,
        },
        "profiles": {
            "retro_modern_v1": {
                "style_anchor": "anchor",
                "negative_constraints": ["a"],
                "palette_tokens": ["#0A3161"],
                "shape_language": ["shape"],
                "lighting_rules": ["light"],
            }
        },
        "validation": {
            "logo": {
                "width": 1024,
                "height": 1024,
                "require_alpha": True,
                "min_transparent_ratio": 0.1,
                "palette_delta_max": 200,
                "phash_max_distance": 64,
                "edge_density_min": 0.0,
                "edge_density_max": 1.0,
            },
            "ui": {
                "width": 1024,
                "height": 1024,
                "require_alpha": True,
                "min_transparent_ratio": 0.1,
                "palette_delta_max": 200,
                "phash_max_distance": 64,
                "edge_density_min": 0.0,
                "edge_density_max": 1.0,
            },
        },
        "golden_set": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_ui_handoff_exports_bundles(tmp_path, monkeypatch):
    root = tmp_path
    ui_dir = root / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    source = "\n".join(
        [
            "from PyQt6.QtWidgets import QDialog, QWidget",
            "",
            "class MyDialog(QDialog):",
            "    def __init__(self):",
            "        super().__init__()",
            "",
            "class Utility:",
            "    pass",
            "",
            "class ChildWidget(QWidget):",
            "    pass",
            "",
        ]
    )
    (ui_dir / "demo.py").write_text(source, encoding="utf-8")

    manifest = root / "manifest.json"
    _write_manifest(manifest)

    out_dir = root / "reports" / "ui_handoff"
    monkeypatch.setattr(build_ui_handoff, "ROOT", root)
    monkeypatch.setattr(build_ui_handoff, "UI_DIR", ui_dir)

    exit_code = build_ui_handoff.main(
        [
            "--manifest",
            str(manifest),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    bundles = sorted([path for path in out_dir.iterdir() if path.is_dir()])
    assert len(bundles) == 2

    metadata = json.loads((bundles[0] / "metadata.json").read_text(encoding="utf-8"))
    assert "line_start" in metadata
    assert "line_end" in metadata
    assert metadata["developer_only"] is True
    assert (bundles[0] / "prompt.md").exists()
    assert (bundles[0] / "source.py").exists()
    assert (out_dir / "index.json").exists()


def test_build_ui_handoff_screen_filter(tmp_path, monkeypatch):
    root = tmp_path
    ui_dir = root / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "demo.py").write_text(
        "\n".join(
            [
                "from PyQt6.QtWidgets import QDialog",
                "class AlphaDialog(QDialog):",
                "    pass",
                "class BetaDialog(QDialog):",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    manifest = root / "manifest.json"
    _write_manifest(manifest)
    out_dir = root / "reports" / "ui_handoff"

    monkeypatch.setattr(build_ui_handoff, "ROOT", root)
    monkeypatch.setattr(build_ui_handoff, "UI_DIR", ui_dir)

    exit_code = build_ui_handoff.main(
        [
            "--manifest",
            str(manifest),
            "--out-dir",
            str(out_dir),
            "--screen",
            "alpha",
        ]
    )

    assert exit_code == 0
    bundles = [path for path in out_dir.iterdir() if path.is_dir()]
    assert len(bundles) == 1
    assert "alpha" in bundles[0].name


def test_build_ui_handoff_handles_utf8_bom_files(tmp_path, monkeypatch):
    root = tmp_path
    ui_dir = root / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    source = "\n".join(
        [
            "from PyQt6.QtWidgets import QDialog",
            "class TradeDialog(QDialog):",
            "    pass",
            "",
        ]
    )
    (ui_dir / "trade_dialog.py").write_text(source, encoding="utf-8-sig")

    manifest = root / "manifest.json"
    _write_manifest(manifest)
    out_dir = root / "reports" / "ui_handoff"

    monkeypatch.setattr(build_ui_handoff, "ROOT", root)
    monkeypatch.setattr(build_ui_handoff, "UI_DIR", ui_dir)

    exit_code = build_ui_handoff.main(
        [
            "--manifest",
            str(manifest),
            "--out-dir",
            str(out_dir),
            "--screen",
            "trade_dialog",
        ]
    )

    assert exit_code == 0
    bundles = [path for path in out_dir.iterdir() if path.is_dir()]
    assert len(bundles) == 1
    assert "trade" in bundles[0].name
