from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
FORBIDDEN_TOKENS = (
    "utils.graphics_style",
    "utils.graphics_consistency",
    "scripts.generate_consistent_graphics",
    "scripts.build_ui_handoff",
)


def test_runtime_ui_does_not_import_dev_graphics_pipeline():
    offenders: list[str] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path}: {token}")
    assert offenders == []

