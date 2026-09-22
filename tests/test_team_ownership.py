"""Who controls a team — the question two files used to answer differently.

In the cloud the memberships bridge writes ownership to ``users.txt`` and
leaves the ``teams.csv`` ``owner_id`` column EMPTY for every team. A check that
reads only that column therefore reports a league full of real owners as
entirely CPU-run: in alpha-test, 7 human owners were being treated as bots, so
the CPU trade evaluator was answering offers addressed to people.
"""

import csv

import pytest

from services.team_ownership import human_owned_team_ids, is_cpu_owned, is_human_owned


def _league(tmp_path, users=(), teams=()):
    if users:
        with (tmp_path / "users.txt").open("w", encoding="utf-8") as fh:
            for username, role, team in users:
                fh.write(f"{username},hash,{role},{team}\n")
    if teams:
        # The full column set the team loader expects, so this exercises the
        # real loader rather than a shape only this test would accept.
        header = [
            "team_id", "name", "city", "abbreviation", "division", "stadium",
            "primary_color", "secondary_color", "owner_id",
        ]
        with (tmp_path / "teams.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for team_id, owner in teams:
                writer.writerow(
                    [team_id, team_id, "City", team_id, "East", "Park", "#000", "#fff", owner]
                )
    return tmp_path


def test_owners_come_from_users_txt(tmp_path):
    """The regression: teams.csv says nobody owns anything."""
    root = _league(
        tmp_path,
        users=[("uid1", "owner", "BAL"), ("uid2", "owner", "CHI")],
        teams=[("BAL", ""), ("CHI", ""), ("CHA", "")],
    )
    assert human_owned_team_ids(root) == {"BAL", "CHI"}
    assert is_human_owned("BAL", data_dir=root) is True
    assert is_cpu_owned("CHA", data_dir=root) is True


def test_the_commissioner_account_owns_no_team(tmp_path):
    root = _league(tmp_path, users=[("admin", "admin", ""), ("uid1", "owner", "BAL")])
    assert human_owned_team_ids(root) == {"BAL"}


def test_an_admin_row_with_a_team_is_still_not_an_owner(tmp_path):
    """Otherwise a commissioner browsing a team makes it 'human-owned'."""
    root = _league(tmp_path, users=[("admin", "admin", "BAL")])
    assert human_owned_team_ids(root) == set()


def test_team_ids_are_matched_regardless_of_case(tmp_path):
    root = _league(tmp_path, users=[("uid1", "owner", "bal")])
    assert is_human_owned("BAL", data_dir=root) is True
    assert is_human_owned("BaL", data_dir=root) is True


def test_teams_csv_is_the_fallback_for_a_local_league(tmp_path):
    """A single-tenant league never had a memberships bridge, so its owner
    column is the only record that exists."""
    root = _league(tmp_path, teams=[("BAL", "james"), ("CHA", "cpu"), ("ELP", "")])
    assert human_owned_team_ids(root) == {"BAL"}
    assert is_cpu_owned("CHA", data_dir=root) is True
    assert is_cpu_owned("ELP", data_dir=root) is True


def test_an_unknown_team_is_not_reported_as_cpu(tmp_path):
    """Callers use this to decide whether to act FOR a team; acting for one we
    cannot identify is the worse failure."""
    root = _league(tmp_path, users=[("uid1", "owner", "BAL")])
    assert is_cpu_owned("", data_dir=root) is False
    assert is_cpu_owned(None, data_dir=root) is False


def test_a_league_with_no_files_reports_nobody(tmp_path):
    assert human_owned_team_ids(tmp_path) == set()


def test_the_trade_evaluator_uses_the_same_answer(tmp_path):
    """The bug that mattered: offers to a human were auto-answered by the CPU.

    Both teams have an EMPTY owner_id, exactly as a cloud league does; only
    users.txt distinguishes them.
    """
    from services.cpu_trade_evaluator import is_cpu_owned_team

    root = _league(
        tmp_path,
        users=[("uid1", "owner", "BAL")],
        teams=[("BAL", ""), ("CHA", "")],
    )
    assert is_cpu_owned_team("BAL", data_dir=root) is False
    assert is_cpu_owned_team("CHA", data_dir=root) is True


def test_an_explicit_owner_in_teams_csv_still_wins(tmp_path):
    """A named owner is a person whatever users.txt says, so a local league
    and an in-memory teams map both keep working."""
    from services.cpu_trade_evaluator import is_cpu_owned_team

    root = _league(tmp_path, users=[("uid1", "owner", "BAL")], teams=[("ELP", "james")])
    assert is_cpu_owned_team("ELP", data_dir=root) is False


def test_an_unknown_team_is_never_auto_answered(tmp_path):
    """Unsure is not the same as CPU: acting for a team we cannot identify is
    the worse failure."""
    from services.cpu_trade_evaluator import is_cpu_owned_team

    root = _league(tmp_path, users=[("uid1", "owner", "BAL")], teams=[("BAL", "")])
    assert is_cpu_owned_team("NOPE", data_dir=root) is False
