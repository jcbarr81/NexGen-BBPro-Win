"""A player's team comes from the roster files, not from players.csv.

Reported: "I still don't see teams listed for players on the league leader
boards." The leaderboards read ``player.team_id``, but players.csv has no such
column — so it was always empty, and the client renders the team chip only
when one is present. The chip silently vanished with no error anywhere.
"""

import pytest

from services.team_lookup import player_team_index, team_for_player


@pytest.fixture
def league(tmp_path):
    rosters = tmp_path / "rosters"
    rosters.mkdir()
    (rosters / "CHI.csv").write_text(
        "P1,ACT\nP2,ACT\nP3,AAA\nP4,LOW\nP5,DL15\nP6,IR\n", encoding="utf-8"
    )
    (rosters / "BAL.csv").write_text("P7,ACT\nP8,AAA\n", encoding="utf-8")
    # Staff-role file: SP1/CL slots, NOT roster membership.
    (rosters / "CHI_pitching.csv").write_text("P1,SP1\nP2,CL\n", encoding="utf-8")
    return tmp_path


def test_every_level_counts(league):
    """A player in AAA, Low-A, or on the injured list still has a team."""
    idx = player_team_index(league)
    assert idx["P1"] == "CHI"   # ACT
    assert idx["P3"] == "CHI"   # AAA
    assert idx["P4"] == "CHI"   # LOW
    assert idx["P5"] == "CHI"   # injured list
    assert idx["P6"] == "CHI"   # 60-day
    assert idx["P7"] == "BAL"


def test_staff_files_do_not_become_teams(league):
    """`<team>_pitching.csv` sits beside the roster files; its stem would give
    a team id of "CHI_pitching"."""
    idx = player_team_index(league)
    assert "CHI_pitching" not in set(idx.values())
    assert set(idx.values()) == {"CHI", "BAL"}


def test_an_unrostered_player_has_no_team(league):
    assert team_for_player("P999", player_team_index(league)) == ""


def test_a_missing_roster_directory_is_survivable(tmp_path):
    """Degrade to no team rather than failing the leaderboard."""
    assert player_team_index(tmp_path) == {}
    assert team_for_player("P1", {}) == ""


def test_blank_and_short_rows_are_ignored(tmp_path):
    rosters = tmp_path / "rosters"
    rosters.mkdir()
    (rosters / "CHI.csv").write_text("\nP1,ACT\n\n,ACT\nP2,ACT\n", encoding="utf-8")
    idx = player_team_index(tmp_path)
    assert idx == {"P1": "CHI", "P2": "CHI"}


def test_the_leaderboard_label_uses_the_index():
    """The actual regression: an empty player.team_id must be filled from the
    roster mapping."""
    from api.routers.leaders import _player_label

    class _P:
        player_id = "P1"
        first_name = "A"
        last_name = "B"
        team_id = ""

    assert _player_label(_P()) ["team_id"] == ""
    assert _player_label(_P(), {"P1": "CHI"})["team_id"] == "CHI"


def test_an_explicit_team_on_the_player_still_wins():
    from api.routers.leaders import _player_label

    class _P:
        player_id = "P1"
        first_name = "A"
        last_name = "B"
        team_id = "BAL"

    assert _player_label(_P(), {"P1": "CHI"})["team_id"] == "BAL"
