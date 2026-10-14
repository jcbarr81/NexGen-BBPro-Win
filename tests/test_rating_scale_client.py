"""The client's reading of ratings does not depend on the rating scale.

The renderer has no unit-test runner; these read its source. On a rating
scale 2 league the server sends stored ratings and the stretched overall,
on scale 1 the percentile blend, and the client colours both with one set
of bands (``desktop/src/lib/rating-tone.ts``), so it never needs to know
the scale. The SP/RP tabs use the server's role, never the shown endurance.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "desktop" / "src"
PAGES = ("RosterPage.tsx", "FreeAgencyPage.tsx", "PlayersBrowserPage.tsx", "PitchersPage.tsx")


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_one_set_of_bands():
    tone = _read("lib/rating-tone.ts")
    assert "elite: 85" in tone and "good: 70" in tone and "average: 50" in tone


@pytest.mark.parametrize("page", PAGES)
def test_every_page_colours_with_the_shared_bands(page):
    text = _read(f"pages/{page}")
    assert 'from "@/lib/rating-tone"' in text
    # No page draws its own thresholds any more (PlayersBrowserPage used
    # 90 / 75 / 60 for the overall).
    assert not re.search(r"(?:value|display|n)\s*>=\s*(?:90|85|75|70|60|50)\b", text)


def test_the_pitcher_tabs_use_the_servers_role():
    text = _read("pages/PitchersPage.tsx")
    body = text[text.index("function pitcherRole"):]
    body = body[: body.index("\n}\n") if "\n}\n" in body else body.index("\r\n}\r\n")]
    assert "endurance" not in body
    assert "p.role" in body
