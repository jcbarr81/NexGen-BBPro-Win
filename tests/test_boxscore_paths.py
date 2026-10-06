"""Box score links survive the league moving.

save_boxscore_html returned an absolute path and that string went into
schedule.csv and the playoff bracket: ``/work/data/leagues/<id>/data/...`` on
Cloud Run, ``C:/Users/...`` locally. The reader then refused anything outside
the current boxscores tree, so a league restored locally, cloned, or served
from a new mount lost every box score link. New links are league-relative;
old ones are re-rooted on their ``boxscores`` segment.
"""

import pytest
from fastapi import HTTPException

import api.routers.boxscore as B
import playbalance.simulation as S


@pytest.fixture
def league(tmp_path, monkeypatch):
    data = tmp_path / "leagues" / "alpha-test" / "data"
    target = data / "boxscores" / "season" / "2026-04-01_BAL_at_HOU.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html>box</html>", encoding="utf-8")
    monkeypatch.setattr(B, "get_data_dir", lambda: data)
    monkeypatch.setattr(S, "get_data_dir", lambda: data)
    return data, target.resolve()


@pytest.mark.parametrize(
    "stored",
    [
        "boxscores/season/2026-04-01_BAL_at_HOU.html",                      # current
        "season/2026-04-01_BAL_at_HOU.html",                                # boxscores-relative
        "/work/data/leagues/alpha-test/data/boxscores/season/2026-04-01_BAL_at_HOU.html",
        "/work/data/leagues/source-league/data/boxscores/season/2026-04-01_BAL_at_HOU.html",
        r"C:\Users\james\NexGen\data\boxscores\season\2026-04-01_BAL_at_HOU.html",
    ],
)
def test_every_stored_form_opens_this_leagues_file(league, stored):
    _, target = league
    assert B._safe_resolve(stored) == target


@pytest.mark.parametrize(
    "stored",
    [
        "/etc/passwd",
        r"C:\Windows\win.ini",
        "../players.csv",
        "boxscores/../../players.csv",
        "/work/data/leagues/x/data/boxscores/../../../etc/passwd",
        "boxscores",
        "",
    ],
)
def test_nothing_outside_the_boxscores_tree(league, stored):
    with pytest.raises(HTTPException) as err:
        B._safe_resolve(stored)
    assert err.value.status_code == 400


def test_new_links_are_league_relative(league):
    data, _ = league
    stored = S.save_boxscore_html("playoffs", "<html/>", "2026_WS_S1_G1_BAL_at_HOU")
    assert stored == "boxscores/playoffs/2026_WS_S1_G1_BAL_at_HOU.html"
    assert not stored.startswith(("/", "\\")) and ":" not in stored
    assert B._safe_resolve(stored) == (data / stored).resolve()
