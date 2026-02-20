from __future__ import annotations

from pathlib import Path

import scripts.archive_ui_checklist as archive_ui_checklist


def test_archive_ui_checklist_writes_artifact(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Checklist\n\n- [ ] Item\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    exit_code = archive_ui_checklist.main(
        [
            "--version",
            "5.0.74",
            "--result",
            "pass",
            "--tester",
            "QA",
            "--source",
            str(source),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    files = list(out_dir.glob("ui_installer_checklist_v5.0.74_*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Checklist Result: PASS" in text
    assert "Tester: QA" in text
    assert "# Checklist" in text


def test_archive_ui_checklist_requires_source(tmp_path):
    missing = tmp_path / "missing.md"
    try:
        archive_ui_checklist.main(
            [
                "--version",
                "5.0.74",
                "--source",
                str(missing),
            ]
        )
    except SystemExit as exc:
        assert "Checklist source not found" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
