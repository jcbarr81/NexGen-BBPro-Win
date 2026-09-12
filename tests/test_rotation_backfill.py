"""A rotation hole is filled by someone who can actually start.

When an owner's SP1-SP5 lands on the injured list, someone else takes the slot,
and the tracker was choosing badly. On the live league SEA had a CLOSER in its
rotation while three starters sat on the active roster; CHA and FOR carried
middle relievers ahead of better starting arms.

Two causes, both fixed in 7.42.0:

* ``built`` was computed by reading ``.player_id`` off the entries of
  ``_build_rotation()``, which returns player id STRINGS. Every entry evaluated
  to ``""``, so the list was silently always empty -- the one role-aware source
  of candidates contributed nothing and raw active-roster order decided.
* A bad fill was self-perpetuating: holding the slot made it "existing", which
  outranked every better candidate, and it re-qualified again the next day.
"""

import pytest

from utils.pitcher_recovery import (
    ROTATION_SLOTS,
    _is_relief_role,
    _spot_start_rank,
    choose_rotation,
)


def pick(
    *,
    saved=(),
    existing=(),
    capable=(),
    staff=None,
    built=(),
    eligible=None,
):
    if eligible is None:
        eligible = sorted(
            {*saved, *existing, *built, *(pid for pid, _ in capable)}
        )
    return choose_rotation(
        saved_rotation=list(saved),
        existing_rotation=list(existing),
        starter_capable=list(capable),
        staff_roles=dict(staff or {}),
        built=list(built),
        eligible=list(eligible),
    )


# --- the owner's labels ----------------------------------------------------


def test_owner_relief_labels_are_recognised():
    assert _is_relief_role("CL") and _is_relief_role("SU")
    assert _is_relief_role("LR") and _is_relief_role("MR2")
    assert not _is_relief_role("SP3")
    assert not _is_relief_role(None), "an unassigned arm stays eligible"


def test_the_long_man_spot_starts_before_the_closer():
    assert _spot_start_rank("LR") < _spot_start_rank("MR1")
    assert _spot_start_rank("MR1") < _spot_start_rank("SU")
    assert _spot_start_rank("SU") < _spot_start_rank("CL")


# --- the regression --------------------------------------------------------


def test_an_available_starter_beats_the_closer():
    """SEA's bug: a closer held a rotation slot with starters sitting idle."""
    rotation = pick(
        saved=["s1", "s2", "s3", "s4"],          # SP5 is hurt, so only four
        existing=["s1", "s2", "s3", "s4", "cl"],  # the bad fill already in place
        capable=[("s1", 52), ("s2", 52), ("s3", 52), ("s4", 52), ("spare", 49)],
        staff={"s1": "SP1", "s2": "SP2", "s3": "SP3", "s4": "SP4", "cl": "CL"},
        eligible=["s1", "s2", "s3", "s4", "cl", "spare"],
    )
    assert "cl" not in rotation, "a closer must not hold a rotation slot"
    assert rotation == ["s1", "s2", "s3", "s4", "spare"]


def test_a_bad_fill_does_not_survive_the_next_day():
    """Holding the slot used to be enough to keep it, forever."""
    args = dict(
        saved=["s1", "s2", "s3", "s4"],
        capable=[("s1", 52), ("s2", 52), ("s3", 52), ("s4", 52), ("good", 51)],
        staff={"s1": "SP1", "s2": "SP2", "s3": "SP3", "s4": "SP4", "cl": "CL"},
        eligible=["s1", "s2", "s3", "s4", "cl", "good"],
    )
    first = pick(existing=["s1", "s2", "s3", "s4", "cl"], **args)
    assert "good" in first and "cl" not in first
    # And it stays put once corrected -- no churning back and forth.
    assert pick(existing=first, **args) == first


def test_an_incumbent_reliever_still_ranks_below_a_real_starter():
    """With too few arms to drop him, he must at least lose the better slot."""
    rotation = pick(
        saved=["s1"],
        existing=["s1", "cl"],
        capable=[("s1", 52), ("good", 51)],
        staff={"s1": "SP1", "cl": "CL"},
        eligible=["s1", "cl", "good"],
    )
    assert rotation.index("good") < rotation.index("cl")


def test_the_strongest_available_arm_is_chosen():
    rotation = pick(
        saved=["s1"],
        capable=[("s1", 52), ("weak", 44), ("strong", 51), ("mid", 48)],
        staff={"s1": "SP1"},
    )
    assert rotation[1:] == ["strong", "mid", "weak"]


# --- the owner still decides -----------------------------------------------


def test_the_owners_own_five_are_never_displaced():
    """Even when he has relief-type arms in his rotation and a better one out."""
    rotation = pick(
        saved=["s1", "cl", "mr", "s4", "s5"],
        capable=[("s1", 50), ("s4", 50), ("s5", 50), ("better", 54)],
        staff={"s1": "SP1", "cl": "SP2", "mr": "SP3", "s4": "SP4", "s5": "SP5"},
        eligible=["s1", "cl", "mr", "s4", "s5", "better"],
    )
    assert rotation == ["s1", "cl", "mr", "s4", "s5"]
    assert "better" not in rotation


# --- a thin staff ----------------------------------------------------------


def test_a_thin_staff_spot_starts_the_long_man_not_the_closer():
    """CHA's case: every SP-capable arm was labelled LR/SU/MR, so the fill had
    to come out of the bullpen. The long man is the right answer."""
    rotation = pick(
        saved=["s1", "s2", "s3", "s5"],
        capable=[("s1", 52), ("s2", 52), ("s3", 52), ("s5", 52),
                 ("longman", 50), ("closer", 51)],
        staff={"s1": "SP1", "s2": "SP2", "s3": "SP3", "s5": "SP5",
               "longman": "LR", "closer": "CL"},
        eligible=["s1", "s2", "s3", "s5", "longman", "closer"],
    )
    assert "longman" in rotation
    assert "closer" not in rotation


def test_a_slot_is_still_filled_when_only_relievers_are_left():
    """Never leave a hole -- somebody has to take the ball."""
    rotation = pick(
        saved=["s1"],
        capable=[("s1", 52)],
        staff={"s1": "SP1", "cl": "CL", "mr": "MR1"},
        built=["s1", "cl", "mr"],
        eligible=["s1", "cl", "mr"],
    )
    assert rotation[0] == "s1"
    assert set(rotation) == {"s1", "cl", "mr"}


# --- invariants ------------------------------------------------------------


def test_never_more_than_five():
    rotation = pick(
        capable=[(f"p{i}", 50 - i) for i in range(9)],
        staff={},
    )
    assert len(rotation) == ROTATION_SLOTS


def test_nobody_off_the_active_roster_can_be_chosen():
    """The whole point: the hurt pitcher must not keep starting."""
    rotation = pick(
        saved=["s1", "hurt"],
        existing=["s1", "hurt"],
        capable=[("s1", 52), ("hurt", 60), ("spare", 40)],
        staff={"s1": "SP1", "hurt": "SP2"},
        eligible=["s1", "spare"],
    )
    assert "hurt" not in rotation
    assert rotation == ["s1", "spare"]


def test_no_duplicates():
    rotation = pick(
        saved=["a", "a", "b"],
        existing=["b", "a"],
        capable=[("a", 52), ("b", 51), ("c", 50)],
        staff={},
    )
    assert len(rotation) == len(set(rotation))
