"""Release 3 staff-slot constants and the relief-role normaliser."""

import pytest

from utils.staff_roles import (
    OPTIONAL_PITCHING_ROLES,
    REQUIRED_PITCHING_ROLES,
    STAFF_ROLES,
    canonical_relief_role,
)


def test_required_roles_are_the_eleven_staff_slots():
    assert REQUIRED_PITCHING_ROLES == (
        "SP1", "SP2", "SP3", "SP4", "SP5", "LR", "MR1", "MR2", "MR3", "SU", "CL",
    )
    assert len(set(REQUIRED_PITCHING_ROLES)) == 11


def test_optional_roles_follow_the_required_ones():
    assert OPTIONAL_PITCHING_ROLES == ("MR4", "MR5")
    assert STAFF_ROLES == REQUIRED_PITCHING_ROLES + OPTIONAL_PITCHING_ROLES
    assert not set(OPTIONAL_PITCHING_ROLES) & set(REQUIRED_PITCHING_ROLES)


def test_required_roles_match_roster_validation():
    # roster_validation keeps its own copy until item C switches it over.
    from services.roster_validation import PITCHING_ROLES

    assert tuple(PITCHING_ROLES) == REQUIRED_PITCHING_ROLES


@pytest.mark.parametrize("role", ["SP", "SP1", "SP2", "SP3", "SP4", "SP5", "SP6", "SP12"])
def test_starter_labels_are_kept(role):
    assert canonical_relief_role(role) == role


@pytest.mark.parametrize("role", ["CL", "SU", "LR", "MR"])
def test_named_relief_roles_are_kept(role):
    assert canonical_relief_role(role) == role


@pytest.mark.parametrize(
    "role",
    ["MR1", "MR2", "MR3", "MR4", "MR5", "MR12", "RP", "R", "P", "", None,
     "XYZ", "CLOSER", "STARTER", "SPX", "LR2"],
)
def test_everything_else_is_a_middle_reliever(role):
    assert canonical_relief_role(role) == "MR"


def test_case_and_whitespace_are_ignored():
    assert canonical_relief_role(" cl ") == "CL"
    assert canonical_relief_role("sp3") == "SP3"
    assert canonical_relief_role(" mr4\t") == "MR"


def test_every_staff_slot_normalises_to_a_usage_role():
    usage_roles = {"CL", "SU", "LR", "MR"}
    for role in STAFF_ROLES:
        canonical = canonical_relief_role(role)
        if role.startswith("SP"):
            assert canonical == role
        else:
            assert canonical in usage_roles
