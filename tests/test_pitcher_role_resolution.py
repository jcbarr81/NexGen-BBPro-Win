"""A declared pitching role outranks the endurance heuristic.

Reported by an owner: "43 games into the season and I am only showing 2 guys
with Starts as SPs". The starts had happened — the pitchers who made them were
not being classified as starters.

``get_role`` derived SP/RP from endurance alone (> 55). In the live alpha-test
league every pitcher sits at 48-54, so NOT ONE of its 460 arms classified as a
starter, and every consumer behaved as though the league had no starting
pitchers: the rotation builder put everyone in the reliever bucket,
``roster_auto_assign`` computed an empty starters list, pitching auto-fill
could not seed a rotation, and the stats split showed no SPs.

Endurance is not merely wrong on compressed data — it under-produces starters
on healthy data too: on the calibration seed only 83 of 390 pitchers clear the
bar, while a 20-team league needs 100.
"""

import pytest

from utils.pitcher_role import (
    ENDURANCE_THRESHOLD,
    get_role,
    role_from_endurance,
    role_from_preferred,
)


class _P:
    def __init__(self, **kw):
        self.primary_position = kw.pop("primary_position", "P")
        for k, v in kw.items():
            setattr(self, k, v)


# --- the reported bug -------------------------------------------------------


def test_a_declared_starter_is_a_starter_despite_low_endurance():
    """The alpha-test shape: position "P", endurance below the bar, but the
    pitcher is declared a starter."""
    p = _P(preferred_pitching_role="SP", endurance=50)
    assert get_role(p) == "SP"


def test_a_compressed_league_still_produces_starters():
    """Every pitcher bunched under the threshold used to yield zero SPs."""
    squad = [_P(preferred_pitching_role="SP", endurance=e) for e in range(48, 55)]
    squad += [_P(preferred_pitching_role="RP", endurance=e) for e in range(48, 55)]
    roles = [get_role(p) for p in squad]
    assert roles.count("SP") == 7
    assert roles.count("RP") == 7


# --- precedence -------------------------------------------------------------


def test_explicit_position_still_wins():
    """primary_position is the most explicit signal of all."""
    assert get_role(_P(primary_position="SP", preferred_pitching_role="CL")) == "SP"
    assert get_role(_P(primary_position="RP", preferred_pitching_role="SP")) == "RP"


def test_endurance_is_the_fallback_when_nothing_is_declared():
    assert get_role(_P(endurance=ENDURANCE_THRESHOLD + 10)) == "SP"
    assert get_role(_P(endurance=ENDURANCE_THRESHOLD - 10)) == "RP"


def test_stored_role_is_the_last_resort():
    assert get_role(_P(endurance=None, role="SP")) == "SP"


def test_a_non_pitcher_position_returns_nothing():
    assert get_role(_P(primary_position="CF", preferred_pitching_role="SP")) == ""


# --- mapping declared roles onto the split ----------------------------------


@pytest.mark.parametrize("token", ["SP", "SP1", "SP5", "sp3", " SP ", "starter"])
def test_starter_tokens(token):
    assert role_from_preferred(token) == "SP"


@pytest.mark.parametrize("token", ["RP", "CL", "SU", "LR", "MR", "MR2", "closer"])
def test_relief_tokens(token):
    """The staff editor's granular slots all collapse to RP for the split."""
    assert role_from_preferred(token) == "RP"


@pytest.mark.parametrize("token", ["", None, "   ", "banana"])
def test_unrecognised_declarations_fall_through(token):
    """An unknown token must not be guessed at — the caller falls back to
    endurance instead."""
    assert role_from_preferred(token) == ""
    assert get_role(_P(preferred_pitching_role=token, endurance=90)) == "SP"


def test_endurance_helper_is_unchanged():
    assert role_from_endurance(ENDURANCE_THRESHOLD + 1) == "SP"
    assert role_from_endurance(ENDURANCE_THRESHOLD) == "RP"
    assert role_from_endurance("nonsense") == ""


# --- the consumers that were silently broken --------------------------------


def test_the_rotation_builder_finds_starters():
    """_build_rotation put everyone in the reliever bucket when get_role said
    RP for the entire league."""
    from utils.pitcher_recovery import PitcherRecoveryTracker

    squad = [
        _P(player_id=f"P{i}", preferred_pitching_role="SP", endurance=50 + i)
        for i in range(5)
    ] + [
        _P(player_id=f"R{i}", preferred_pitching_role="RP", endurance=50)
        for i in range(6)
    ]
    rotation = PitcherRecoveryTracker._build_rotation(
        PitcherRecoveryTracker.__new__(PitcherRecoveryTracker), squad
    )
    assert len(rotation) == 5
    # Declared starters, best endurance first.
    assert rotation[0] == "P4"
    assert all(pid.startswith("P") for pid in rotation)


def test_auto_assign_sees_starters():
    """roster_auto_assign filtered on get_role(p) == 'SP', which was never true."""
    import inspect

    from services import roster_auto_assign

    src = inspect.getsource(roster_auto_assign)
    assert 'get_role(p) == "SP"' in src or "get_role(p) == 'SP'" in src
    squad = [_P(preferred_pitching_role="SP", endurance=50) for _ in range(5)]
    assert [p for p in squad if get_role(p) == "SP"] == squad
