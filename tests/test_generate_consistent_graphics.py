from __future__ import annotations

import base64
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw

from scripts import generate_consistent_graphics


def _fake_b64_png(size: int = 64) -> str:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, size - 8, size - 8), fill=(10, 49, 97, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _write_manifest(path, *, width: int = 64, height: int = 64) -> None:
    payload = {
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
                "width": width,
                "height": height,
                "require_alpha": True,
                "min_transparent_ratio": 0.05,
                "palette_delta_max": 220.0,
                "phash_max_distance": 64,
                "edge_density_min": 0.0,
                "edge_density_max": 1.0,
            },
            "ui": {
                "width": width,
                "height": height,
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
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_generate_consistent_graphics_logo_mode_writes_reports(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest)

    class DummyImages:
        def generate(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(b64_json=_fake_b64_png(64))])

    monkeypatch.setattr(
        generate_consistent_graphics,
        "client",
        SimpleNamespace(images=DummyImages()),
    )
    monkeypatch.setattr(
        generate_consistent_graphics,
        "load_teams",
        lambda _: [
            SimpleNamespace(
                team_id="TST",
                city="Testville",
                name="Testers",
                primary_color="#0A3161",
                secondary_color="#C8102E",
            )
        ],
    )

    out_dir = tmp_path / "run"
    exit_code = generate_consistent_graphics.main(
        [
            "--manifest",
            str(manifest),
            "--mode",
            "logos",
            "--out-dir",
            str(out_dir),
            "--strict",
        ]
    )
    assert exit_code == 0
    assert (out_dir / "logos" / "tst.png").exists()
    assert (out_dir / "validation.json").exists()
    assert (out_dir / "run_manifest.json").exists()
    assert (out_dir / "prompts.jsonl").exists()


def test_generate_consistent_graphics_strict_fails_on_validation_error(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, width=128, height=128)

    class DummyImages:
        def generate(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(b64_json=_fake_b64_png(64))])

    monkeypatch.setattr(
        generate_consistent_graphics,
        "client",
        SimpleNamespace(images=DummyImages()),
    )
    monkeypatch.setattr(
        generate_consistent_graphics,
        "load_teams",
        lambda _: [
            SimpleNamespace(
                team_id="TST",
                city="Testville",
                name="Testers",
                primary_color="#0A3161",
                secondary_color="#C8102E",
            )
        ],
    )

    out_dir = tmp_path / "run_fail"
    exit_code = generate_consistent_graphics.main(
        [
            "--manifest",
            str(manifest),
            "--mode",
            "logos",
            "--out-dir",
            str(out_dir),
            "--strict",
        ]
    )
    assert exit_code == 1

