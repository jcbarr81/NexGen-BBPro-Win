from __future__ import annotations

import json
from pathlib import Path

from scripts import create_ui_polish_baseline


def test_create_ui_polish_baseline_writes_bundle(tmp_path, monkeypatch):
    root = tmp_path
    out_dir = root / "reports" / "ui_polish_baselines"
    version_file = root / "VERSION"
    version_file.write_text("9.9.9\n", encoding="utf-8")

    monkeypatch.setattr(create_ui_polish_baseline, "ROOT", root)
    monkeypatch.setattr(create_ui_polish_baseline, "VERSION_FILE", version_file)
    monkeypatch.setattr(
        create_ui_polish_baseline,
        "RUBRIC_PATH",
        root / "docs" / "ui_polish_rubric.md",
    )

    code = create_ui_polish_baseline.main(
        [
            "--out-dir",
            str(out_dir),
            "--screen",
            "lineups",
            "--screen",
            "trades",
            "--touch-placeholders",
            "--tag",
            "smoke",
        ]
    )

    assert code == 0
    runs = [path for path in out_dir.iterdir() if path.is_dir()]
    assert len(runs) == 1
    run_dir = runs[0]

    checklist = run_dir / "checklist.md"
    index_file = run_dir / "index.json"
    assert checklist.exists()
    assert index_file.exists()
    assert (run_dir / "screens" / "lineups.placeholder.txt").exists()
    assert (run_dir / "screens" / "trades.placeholder.txt").exists()

    payload = json.loads(index_file.read_text(encoding="utf-8"))
    assert payload["version"] == "9.9.9"
    assert payload["status"] == "pending"
    assert [screen["id"] for screen in payload["screens"]] == ["lineups", "trades"]

    text = checklist.read_text(encoding="utf-8")
    assert "Checklist Result: PENDING" in text
    assert "## Lineups (`lineups`)" in text
    assert "## Trades (`trades`)" in text


def test_create_ui_polish_baseline_rejects_unknown_screen(tmp_path, monkeypatch):
    root = tmp_path
    out_dir = root / "reports" / "ui_polish_baselines"
    version_file = root / "VERSION"
    version_file.write_text("1.0.0\n", encoding="utf-8")

    monkeypatch.setattr(create_ui_polish_baseline, "ROOT", root)
    monkeypatch.setattr(create_ui_polish_baseline, "VERSION_FILE", version_file)

    try:
        create_ui_polish_baseline.main(
            [
                "--out-dir",
                str(out_dir),
                "--screen",
                "unknown",
            ]
        )
    except ValueError as exc:
        assert "Unknown --screen value" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown screen filter.")
