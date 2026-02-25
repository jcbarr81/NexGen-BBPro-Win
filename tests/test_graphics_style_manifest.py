from __future__ import annotations

import json

import pytest

from utils import graphics_style


def test_load_manifest_default_file():
    manifest = graphics_style.load_manifest()
    assert manifest["manifest_version"]
    assert "retro_modern_v1" in manifest["profiles"]
    assert manifest["default_profile"] == "retro_modern_v1"


def test_load_manifest_requires_keys(tmp_path):
    broken = {
        "manifest_version": "1.0",
        "default_profile": "retro_modern_v1",
    }
    manifest_path = tmp_path / "broken.json"
    manifest_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        graphics_style.load_manifest(manifest_path)
    assert "missing required keys" in str(exc.value)


def test_prompt_fingerprint_stable():
    text = "alpha beta gamma"
    assert graphics_style.prompt_fingerprint(text) == graphics_style.prompt_fingerprint(text)

