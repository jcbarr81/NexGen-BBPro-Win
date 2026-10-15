"""Generation 7 for owners: the tutorial steps (shown to a generation 7
league only), the news item, the slider help.

Every payload a league below generation 7 gets is the one it got before
generation filtering existed (scale 1 is also pinned whole in
tests/test_rating_scale_display.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import ballflight_news
from services.physics_tuning_spec import _BALLFLIGHT_MODEL_SLIDERS
from services.tutorials import TUTORIALS, tutorial_catalog, tutorial_list

REPO = Path(__file__).resolve().parents[1]
GEN7_TITLES = {
    "Real ball flight",
    "Ballparks and fences",
    "Fielders run balls down; pop-ups and foul-outs",
    "Ground-ball and fly-ball pitchers",
    "Home Run Rate and Launch Angle sliders",
}


def _dump(payload) -> str:
    return json.dumps(payload, sort_keys=False)


@pytest.mark.parametrize("scale", [None, 1, 2])
@pytest.mark.parametrize("generation", [None, 4, 5, 6])
def test_below_generation_7_the_payload_is_byte_identical(scale, generation):
    assert _dump(tutorial_catalog(scale, generation)) == _dump(tutorial_catalog(scale))
    assert _dump(tutorial_list(scale, generation)) == _dump(tutorial_list(scale))


def test_the_steps_written_before_are_the_ones_a_league_below_7_sees():
    """What the catalog served before generation filtering: the rating
    scale rule alone, over every step that is not a generation 7 one."""
    for scale in (1, 2):
        expected = {
            t.tutorial_id: [
                {"title": s.title, "body_html": s.body_html}
                for s in t.steps
                if (s.rating_scale is None or s.rating_scale == scale)
                and s.min_generation is None
            ]
            for t in TUTORIALS
        }
        got = {k: v["steps"] for k, v in tutorial_catalog(scale, 6).items()}
        assert got == expected


def test_a_generation_7_league_sees_the_ball_flight_steps():
    six = tutorial_catalog(2, 6)["updated_engine"]["steps"]
    seven = tutorial_catalog(2, 7)["updated_engine"]["steps"]
    titles6 = [s["title"] for s in six]
    titles7 = [s["title"] for s in seven]
    assert not GEN7_TITLES & set(titles6)
    assert GEN7_TITLES <= set(titles7)
    assert len(titles7) == len(set(titles7))  # each step once
    # Power and doubles: generation 6's text replaced by the ball-flight one.
    power6 = {s["title"]: s["body_html"] for s in six}["Power and doubles"]
    power7 = {s["title"]: s["body_html"] for s in seven}["Power and doubles"]
    assert power6 != power7 and "where the ball lands" in power7
    # Everything else is generation 6's, in the same order.
    rest7 = [s for s in seven if s["title"] not in GEN7_TITLES | {"Power and doubles"}]
    rest6 = [s for s in six if s["title"] != "Power and doubles"]
    assert rest7 == rest6
    # Generation 7 needs scale 2: a scale 1 payload never shows them.
    assert _dump(tutorial_catalog(1, 7)) == _dump(tutorial_catalog(1))


def test_the_help_endpoint_reads_the_leagues_generation(monkeypatch):
    from api.routers import help as help_router

    monkeypatch.setattr(help_router, "_league_rating_scale", lambda: 2)
    monkeypatch.setattr(help_router, "_league_generation", lambda: 7)
    titles = {
        s["title"]
        for t in help_router.tutorials()["tutorials"]
        for s in t["steps"]
    }
    assert GEN7_TITLES <= titles
    detail = help_router.tutorial_detail("updated_engine")
    assert GEN7_TITLES <= {s["title"] for s in detail["steps"]}
    monkeypatch.setattr(help_router, "_league_generation", lambda: 6)
    assert _dump(help_router.tutorials()["tutorials"]) == _dump(tutorial_list(2))
    monkeypatch.setattr(help_router, "_league_generation", lambda: None)
    assert _dump(help_router.tutorials()["tutorials"]) == _dump(tutorial_list(2))


def test_the_news_item_names_the_leagues_own_parks(tmp_path, monkeypatch):
    from physics_sim import ballflight
    from utils import park_utils

    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(REPO / "data"))
    ballflight.clear_fence_cache()
    # The calibration clubs: 30 named real parks, no park_id column.
    (tmp_path / "teams.csv").write_bytes(
        (REPO / "data" / "calibration" / "teams.csv").read_bytes()
    )
    text = ballflight_news.ballflight_switch_news(tmp_path, season="2027")
    assert text.startswith("Season 2027: the league now plays on the newest game engine")
    assert ballflight_news.BALLFLIGHT_ENGINE_TEXT in text
    assert "All 30 of the league's clubs play in real major-league parks" in text
    assert "American Family Field" in text and "and others" in text
    assert "Home Run Rate and Launch Angle" in text
    # A league whose clubs chose no park (park_id empty): the average park.
    (tmp_path / "teams.csv").write_text(
        "team_id,name,stadium,park_id\nA,A,Fenway Park,\nB,B,Royals Stadium,\n",
        encoding="utf-8",
    )
    sentence = ballflight_news.league_parks_sentence(tmp_path)
    assert sentence.startswith("None of the league's 2 clubs")
    # One real, one not.
    (tmp_path / "teams.csv").write_text(
        "team_id,name,stadium\nA,A,Fenway Park\nB,B,Nowhere Field\n",
        encoding="utf-8",
    )
    sentence = ballflight_news.league_parks_sentence(tmp_path)
    assert sentence.startswith("1 of the league's 2 clubs") and "Fenway Park" in sentence
    # No teams file: no sentence, the item still reads.
    (tmp_path / "teams.csv").unlink()
    assert ballflight_news.league_parks_sentence(tmp_path) == ""
    assert ballflight_news.ballflight_switch_news(tmp_path)


def test_the_slider_help_quotes_the_measured_sizes():
    hr = _BALLFLIGHT_MODEL_SLIDERS["hr_scale"].description
    la = _BALLFLIGHT_MODEL_SLIDERS["launch_angle_base"].description
    assert "about 1% more home runs" in hr and "reset to 1.00" in hr
    assert "about 5% more home runs" in la and "reset to 12.1" in la
