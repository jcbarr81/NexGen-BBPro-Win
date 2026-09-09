"""A starter is rested like a starter, even when players.csv disagrees.

Every pitcher in the live alpha-test league is stored with ``role = "RP"`` —
100 of 100 rotation members included. That is stale output of the endurance-only
role classifier fixed in 7.38.0, and the recovery tracker was still consuming
it: ``_role_key`` rounds an unrecognised "RP" to "MR", so a rotation starter was
being seeded with middle-reliever pitch budgets and recovery.

The owner's own staff file (``{team}_pitching.csv``) says who starts. It is the
authority, so the tracker consults it before falling back to the derived value.
"""

import csv

import pytest

from utils.pitcher_recovery import PitcherRecoveryTracker


class _Pitcher:
    is_pitcher = True

    def __init__(self, pid, endurance=52, role="RP"):
        self.player_id = pid
        self.endurance = endurance
        self.role = role
        self.primary_position = "P"


@pytest.fixture
def staffed(tmp_path):
    """A team whose owner named a five-man rotation, on a league whose
    players.csv calls every one of them a reliever."""
    rosters = tmp_path / "rosters"
    rosters.mkdir()
    with (rosters / "CHI_pitching.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for pid, role in [
            ("P1", "SP1"), ("P2", "SP2"), ("P3", "SP3"), ("P4", "SP4"), ("P5", "SP5"),
            ("P6", "CL"), ("P7", "MR1"),
        ]:
            writer.writerow([pid, role])
    return tmp_path, rosters


def _roles(tracker, staffed):
    tmp_path, rosters = staffed
    pitchers = [_Pitcher(f"P{i}") for i in range(1, 8)]
    entry = tracker._build_team_entry(
        pitchers,
        ["P1", "P2", "P3", "P4", "P5"],
        tracker._load_staff_roles("CHI", rosters),
    )
    return {pid: st.get("last_role") for pid, st in entry["pitchers"].items()}


def test_the_staff_file_is_read_as_pid_to_role(staffed):
    tmp_path, rosters = staffed
    tracker = PitcherRecoveryTracker(tmp_path / "recovery.json")
    roles = tracker._load_staff_roles("CHI", rosters)
    assert roles["P1"] == "SP1"
    assert roles["P6"] == "CL"


def test_a_missing_staff_file_is_empty_not_an_error(tmp_path):
    tracker = PitcherRecoveryTracker(tmp_path / "recovery.json")
    assert tracker._load_staff_roles("NOPE", tmp_path) == {}


def test_a_rotation_starter_is_not_treated_as_a_reliever(staffed):
    """The regression itself: role="RP" used to round to "MR"."""
    tmp_path, _ = staffed
    tracker = PitcherRecoveryTracker(tmp_path / "recovery.json")
    roles = _roles(tracker, staffed)
    assert [roles[f"P{i}"] for i in range(1, 6)] == ["SP"] * 5


def test_relievers_keep_their_own_staff_role(staffed):
    """The fix must not make everyone a starter."""
    tmp_path, _ = staffed
    tracker = PitcherRecoveryTracker(tmp_path / "recovery.json")
    roles = _roles(tracker, staffed)
    assert roles["P6"] == "CL"
    assert roles["P7"] == "MR"


def test_a_starter_earns_starter_rest_not_the_flat_reliever_table(staffed):
    """Why it matters: the reliever table returns 4 days for ANY pitch count,
    so a 100-pitch start would come back a day early."""
    from utils.pitcher_recovery import _rest_days

    assert _rest_days(94, "SP") == 5
    assert _rest_days(104, "SP") == 6
    assert _rest_days(104, "MR") == 4


def test_an_unstaffed_pitcher_still_falls_back_to_the_derived_role(tmp_path):
    tracker = PitcherRecoveryTracker(tmp_path / "recovery.json")
    status = tracker._initial_status(_Pitcher("PX", endurance=52, role=""), None)
    assert status.last_role in {"SP", "MR", "CL", "SU", "LR"}
