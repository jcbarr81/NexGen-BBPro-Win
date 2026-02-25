from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw

from utils.graphics_consistency import validate_assets, validate_image


def _manifest() -> dict:
    return {
        "default_profile": "retro_modern_v1",
        "profiles": {
            "retro_modern_v1": {
                "palette_tokens": ["#0A3161", "#C8102E", "#F6F4EF"],
                "style_anchor": "anchor",
                "negative_constraints": [],
                "shape_language": [],
                "lighting_rules": [],
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
                "min_transparent_ratio": 0.0,
                "palette_delta_max": 220.0,
                "phash_max_distance": 64,
                "edge_density_min": 0.0,
                "edge_density_max": 1.0,
            },
        },
        "golden_set": [],
    }


def test_validate_image_passes_basic_fixture(tmp_path):
    image_path = tmp_path / "logo.png"
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(10, 49, 97, 255))
    image.save(image_path)

    result = validate_image(image_path, category="logo", manifest=_manifest())
    assert result["status"] == "pass"


def test_validate_image_fails_on_dimension_mismatch(tmp_path):
    image_path = tmp_path / "logo.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(image_path)

    result = validate_image(image_path, category="logo", manifest=_manifest())
    assert result["status"] == "fail"
    assert any(item["code"] == "dimension_mismatch" for item in result["findings"])


def test_validate_assets_reports_palette_drift(tmp_path):
    image_path = tmp_path / "ui.png"
    Image.new("RGBA", (64, 64), (0, 255, 0, 255)).save(image_path)
    manifest = _manifest()
    manifest["validation"]["ui"]["palette_delta_max"] = 10.0
    manifest["validation"]["ui"]["min_transparent_ratio"] = 0.0

    report = validate_assets(
        [{"path": str(image_path), "category": "ui"}],
        manifest=manifest,
    )
    assert report["status"] == "fail"
    assert report["error_count"] > 0

