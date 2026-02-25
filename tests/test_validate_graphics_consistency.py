from __future__ import annotations

import json

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw

from scripts import validate_graphics_consistency


def _write_manifest(path) -> None:
    path.write_text(
        json.dumps(
            {
                "manifest_version": "1.0",
                "default_profile": "retro_modern_v1",
                "openai": {
                    "model": "gpt-image-1",
                    "size": "64x64",
                    "background": "transparent",
                    "max_retries": 1,
                },
                "profiles": {
                    "retro_modern_v1": {
                        "style_anchor": "anchor",
                        "negative_constraints": ["none"],
                        "palette_tokens": ["#0A3161", "#C8102E", "#F6F4EF"],
                        "shape_language": ["badge"],
                        "lighting_rules": ["soft"],
                    }
                },
                "validation": {
                    "logo": {
                        "width": 64,
                        "height": 64,
                        "require_alpha": True,
                        "min_transparent_ratio": 0.05,
                        "palette_delta_max": 220.0,
                        "phash_max_distance": 64,
                        "edge_density_min": 0.0,
                        "edge_density_max": 1.0,
                    },
                    "ui": {
                        "width": 64,
                        "height": 64,
                        "require_alpha": True,
                        "min_transparent_ratio": 0.05,
                        "palette_delta_max": 220.0,
                        "phash_max_distance": 64,
                        "edge_density_min": 0.0,
                        "edge_density_max": 1.0,
                    },
                },
                "golden_set": [],
            }
        ),
        encoding="utf-8",
    )


def test_validate_graphics_consistency_strict_pass(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest)

    run_dir = tmp_path / "run"
    (run_dir / "logos").mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(10, 49, 97, 255))
    image.save(run_dir / "logos" / "logo_tst.png")

    out_file = tmp_path / "report.json"
    exit_code = validate_graphics_consistency.main(
        [
            "--manifest",
            str(manifest),
            "--input-dir",
            str(run_dir),
            "--json-out",
            str(out_file),
            "--strict",
        ]
    )
    assert exit_code == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
