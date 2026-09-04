"""The box score template must be inside the deployed image.

Root cause of "I can't find box scores": ``render_boxscore_html`` reads
``espn_boxscore_template.html``, which lived only in ``samples/`` — a directory
excluded by BOTH .dockerignore and .gcloudignore. In the cloud the template was
therefore always missing, the renderer returned "" by design ("degrade
gracefully"), and every save site skipped silently. A full season of played
games produced not one box score, and nothing anywhere said why.

A negation re-include in .dockerignore is not a fix: Cloud Build's builder does
not honour re-including under an excluded directory (there is already a note
about this in .dockerignore, for /images). The template has to live somewhere
that ships — so these tests assert exactly that, rather than trusting it.
"""

from pathlib import Path

import pytest

from playbalance.simulation import (
    _boxscore_template_paths,
    _load_boxscore_template,
    render_boxscore_html,
)

REPO = Path(__file__).resolve().parent.parent


def test_the_template_resolves():
    template = _load_boxscore_template()
    assert template, "no box score template found on any candidate path"
    assert "<" in template


def test_the_packaged_copy_exists():
    """Not just resolvable on this machine — present where the image will look."""
    packaged = REPO / "playbalance" / "templates" / "espn_boxscore_template.html"
    assert packaged.exists(), f"{packaged} is missing; the deployed image has no template"


def _ignored_top_level_dirs(name: str) -> set:
    path = REPO / name
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if line.startswith("/") and line.endswith("/"):
            out.add(line.strip("/").split("/")[0])
    return out


@pytest.mark.parametrize("ignore_file", (".dockerignore", ".gcloudignore"))
def test_the_template_is_not_under_an_excluded_directory(ignore_file):
    """The regression guard: moving the template back under an ignored path
    (or newly ignoring the one it lives in) breaks production silently."""
    packaged = REPO / "playbalance" / "templates" / "espn_boxscore_template.html"
    top = packaged.relative_to(REPO).parts[0]
    excluded = _ignored_top_level_dirs(ignore_file)
    assert top not in excluded, (
        f"{ignore_file} excludes /{top}/, so the box score template would not "
        "reach the deployed image and every box score would silently vanish."
    )


def test_samples_is_still_excluded_so_the_fallback_cannot_be_relied_on():
    """Documents WHY the template moved: samples/ does not ship."""
    excluded = _ignored_top_level_dirs(".dockerignore")
    assert "samples" in excluded


def test_rendering_produces_real_html():
    """The production symptom was an empty string coming out of here."""
    from playbalance.simulation import generate_boxscore
    from tests.test_boxscore_html_save import _simulate_simple_game

    home, away = _simulate_simple_game()
    box = generate_boxscore(home, away)
    html = render_boxscore_html(box, home_name="Home", away_name="Away")

    assert html, "renderer returned an empty string — the exact production symptom"
    assert len(html) > 500
    assert "Home" in html and "Away" in html


def test_candidate_paths_prefer_the_packaged_copy():
    first = _boxscore_template_paths()[0]
    assert first.parts[-3:] == ("playbalance", "templates", "espn_boxscore_template.html")
