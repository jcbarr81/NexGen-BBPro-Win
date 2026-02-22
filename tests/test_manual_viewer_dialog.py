from __future__ import annotations

from pathlib import Path


def test_import_manual_viewer_dialog_headless():
    from ui.manual_viewer_dialog import ManualViewerDialog  # noqa: F401

    assert ManualViewerDialog is not None


def test_load_manual_html_reads_expected_file(monkeypatch, tmp_path):
    from ui import manual_viewer_dialog as manuals

    manuals_dir = tmp_path / "docs" / "manuals"
    manuals_dir.mkdir(parents=True, exist_ok=True)
    target = manuals_dir / "game_manual.html"
    target.write_text("<h1>Manual OK</h1>", encoding="utf-8")

    monkeypatch.setattr(manuals, "get_base_dir", lambda: Path(tmp_path))
    html = manuals.load_manual_html(manuals.DOC_GAME_MANUAL)
    assert "Manual OK" in html


def test_load_manual_html_returns_missing_message(monkeypatch, tmp_path):
    from ui import manual_viewer_dialog as manuals

    monkeypatch.setattr(manuals, "get_base_dir", lambda: Path(tmp_path))
    html = manuals.load_manual_html(manuals.DOC_FINANCE_MANUAL)
    assert "missing from the current installation" in html

