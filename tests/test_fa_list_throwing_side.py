"""The free-agent list carries a player's throwing side (owner request, 8.12.2).

The list's hand column showed every player's batting side; owners pricing a
pitcher want to know the throwing arm, not whether the pitcher switch-hits.
The page now shows ``throws`` for pitchers and ``bats`` for hitters, so the
summary has to serve both.
"""

from types import SimpleNamespace

from api.routers import free_agency


def _summary(**over):
    player = SimpleNamespace(**{
        "player_id": "P1",
        "first_name": "Lefty",
        "last_name": "Arm",
        "primary_position": "P",
        "is_pitcher": True,
        "preferred_pitching_role": "SP",
        "endurance": "60",
        "bats": "S",
        "throws": "L",
        **over,
    })
    return free_agency._summarize(player)


def _flat_overall(monkeypatch):
    monkeypatch.setattr(free_agency, "compute_overall", lambda *a, **k: {
        "overall_raw": 0, "overall_display": 0, "overall_stars_text": "",
    })


def test_a_pitcher_summary_carries_both_sides(monkeypatch):
    _flat_overall(monkeypatch)
    summary = _summary()
    assert summary["throws"] == "L"
    assert summary["bats"] == "S"


def test_a_player_without_a_throwing_side_serves_an_empty_one(monkeypatch):
    _flat_overall(monkeypatch)
    summary = _summary(throws=None)
    assert summary["throws"] == ""
