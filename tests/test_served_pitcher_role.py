"""Every page shows a pitcher's SP/RP the same way.

players.csv's ``role`` column is derived data written by the old
endurance-only classifier: on alpha-test 492 of 494 pitchers read "RP",
starters included. The roster page already ignored it (declared role first,
then endurance); Free Agency and the players list served it raw, so the same
starter showed as SP on one page and RP on another.
"""

from types import SimpleNamespace

from api.routers import free_agency, players


def _row(**over):
    row = {
        "player_id": "P1",
        "first_name": "Ace",
        "last_name": "Starter",
        "primary_position": "P",
        "is_pitcher": "1",
        "role": "RP",                      # the stale stored value
        "preferred_pitching_role": "SP",
        "endurance": "50",
    }
    row.update(over)
    return row


def test_players_list_shows_the_declared_starter_as_sp():
    assert players._row_to_summary(_row()).role == "SP"


def test_players_list_falls_back_to_endurance_when_nothing_is_declared():
    assert players._row_to_summary(_row(preferred_pitching_role="", endurance="70")).role == "SP"
    assert players._row_to_summary(_row(preferred_pitching_role="", endurance="40")).role == "RP"


def test_a_closer_is_a_reliever():
    assert players._row_to_summary(_row(preferred_pitching_role="CL")).role == "RP"


def test_hitters_keep_their_stored_value():
    row = _row(primary_position="SS", is_pitcher="0", role="", preferred_pitching_role="")
    assert players._row_to_summary(row).role == ""


def test_free_agency_shows_the_declared_starter_as_sp(monkeypatch):
    monkeypatch.setattr(free_agency, "compute_overall", lambda *a, **k: {
        "overall_raw": 0, "overall_display": 0, "overall_stars_text": "",
    })
    player = SimpleNamespace(**{**_row(), "is_pitcher": True})
    assert free_agency._summarize(player)["role"] == "SP"


# --- the profile, the bullpen card, the recovery tracker ---------------------


def _pitcher(**over):
    return SimpleNamespace(**{**_row(), "is_pitcher": True, **over})


def test_profile_shows_the_derived_role():
    from services.player_profile_view_model import _role_text

    assert _role_text(_pitcher(), True) == "SP"
    assert _role_text(_pitcher(preferred_pitching_role="CL"), True) == "RP"
    assert _role_text(SimpleNamespace(role="", primary_position="SS"), False) == ""


def test_bullpen_card_follows_the_staff_then_the_derived_role():
    from services.quick_metrics import _is_bullpen_pitcher

    starter = _pitcher()                                 # stored "RP", declared SP
    assert _is_bullpen_pitcher(starter) is False         # was True: whole rotation counted
    assert _is_bullpen_pitcher(starter, "MR1") is True   # the team uses him in relief
    assert _is_bullpen_pitcher(_pitcher(preferred_pitching_role="CL"), "SP3") is False


def test_tracker_fallback_role_is_derived_not_stored():
    from utils.pitcher_recovery import PitcherRecoveryTracker

    assert PitcherRecoveryTracker._assigned_role_for(_pitcher()) == "SP"
    assert PitcherRecoveryTracker._assigned_role_for(_pitcher(assigned_pitching_role="CL")) == "CL"
