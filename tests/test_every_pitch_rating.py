"""8.10.0 (#69): every pitch rating reaches the tables that can show it.

ksubarton: "Need to be able to edit/change the columns on home roster/free
agency pages to see all pitches." The free-agent list sent only the
fastball; the Players browser sent no pitch at all (its FB column read "—"
for every pitcher); the profile called the changeup "Curve" and the sinker
"Splitter" and left out the curveball and screwball. The client's column
picker can now show any of them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests import rating_display_support as rds
from tests.test_rating_scale_display import _league, _serve

PITCHES = ("fb", "sl", "cu", "cb", "si", "scb", "kn")


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    root = tmp_path_factory.mktemp("pitches")
    data, payloads = _serve(root, 1)
    return root, data, payloads


def test_the_players_browser_sends_every_pitch(served):
    _root, _data, payloads = served
    pitchers = [p for p in payloads["players/browse"]["players"] if p["is_pitcher"]]
    assert pitchers
    for p in pitchers:
        assert set(PITCHES) <= set(p["ratings"]), p["player_id"]


def test_the_free_agent_summary_sends_every_pitch(served):
    from api.routers import free_agency
    from utils.player_loader import load_players_from_csv

    root, data, _payloads = served
    with _league(root):
        pitcher = next(
            p for p in load_players_from_csv(str(data / "players.csv"))
            if getattr(p, "is_pitcher", False)
        )
        summary = free_agency._summarize(pitcher)
    assert set(PITCHES) <= set(summary["ratings"])
    assert {"control", "movement", "endurance"} <= set(summary["ratings"])


def test_the_profile_names_every_pitch_he_throws(monkeypatch):
    from services import player_profile_view_model as vm

    monkeypatch.setattr(vm, "_display_rating", lambda player, key, **_k: str(key))
    pitcher = SimpleNamespace(
        control=50, movement=50, endurance=50, hold_runner=50, fa=50, arm=50,
        fb=60, sl=0, cu=55, cb=48, si=52, scb=41, kn=0,
    )
    rows = dict(vm._overview_ratings(pitcher, is_pitcher=True))
    # Named as the rest of the game names them; a 0 is a pitch he doesn't throw.
    assert rows["Fastball"] == "fb"
    assert rows["Changeup"] == "cu"
    assert rows["Curveball"] == "cb"
    assert rows["Sinker"] == "si"
    assert rows["Screwball"] == "scb"
    assert "Slider" not in rows and "Knuckleball" not in rows
    assert "Curve" not in rows and "Splitter" not in rows
