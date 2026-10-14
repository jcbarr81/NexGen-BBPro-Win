"""The scale 2 file format: a players.csv a build before 8.0.0 refuses.

A file holding any scale 2 row names its height column ``height_in``
(``utils.rating_scale``). A 7.51.3 loader requires ``height`` on every row,
so it fails loudly on such a file instead of loading stretched ratings as
engine ratings and saving them back without their scale. Measured on a real
7.51.3 export: ``ValueError: Missing required field: height`` from both
``_read_players_from_csv`` and ``load_players_from_csv``. This build reads
both names, refuses a row an older build appended (blank ``height_in``),
and the working copy never pushes the older format over the newer.
"""

from __future__ import annotations

import csv
import shutil

import pytest

from api import working_copy
from services import draft_assignment
from tests import rating_scale_support as support
from utils.player_loader import _read_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.rating_scale import (
    SCALE2_HEIGHT_FIELD,
    engine_row,
    players_fieldnames,
    row_height,
    stretch_rows,
)

FIXTURE = support.FIXTURES["calibration_league"]


def _required_int_7_51_3(row, key):
    """``utils.player_loader._required_int`` exactly as 7.51.3 has it."""
    value = row.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required field: {key}")
    return int(value)


@pytest.fixture
def league(tmp_path):
    return support.copy_league(FIXTURE, tmp_path / "lg")


def _scale2_file(league, tmp_path):
    players = _read_players_from_csv(league / "players.csv")
    fields, rows = support.read_player_rows(league / "players.csv")
    stretched, _ = stretch_rows(rows, 2)
    path = tmp_path / "players.csv"
    from services.rating_scale_migration import _write_players

    _write_players(path, fields, stretched)
    return path, players


def test_the_writer_puts_a_scale_2_league_in_the_new_format(league, tmp_path):
    path, plain = _scale2_file(league, tmp_path)
    full = _read_players_from_csv(path)
    out = tmp_path / "saved.csv"
    save_players_to_csv(full, str(out))
    header = support.read_player_rows(out)[0]
    assert SCALE2_HEIGHT_FIELD in header and "height" not in header
    assert header[-1] == "rating_scale"
    # Heights survive, under the new name, and read back.
    again = {p.player_id: p for p in _read_players_from_csv(out)}
    for player in plain:
        assert again[player.player_id].height == player.height
    # A scale 1 league is written exactly as it always was.
    ref = tmp_path / "ref.csv"
    save_players_to_csv(plain, str(ref))
    assert "height_in" not in ref.read_text(encoding="utf-8").splitlines()[0]


def test_a_7_51_3_loader_cannot_read_the_new_format(league, tmp_path):
    path, _ = _scale2_file(league, tmp_path)
    with path.open(newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    with pytest.raises(ValueError, match="Missing required field: height"):
        _required_int_7_51_3(row, "height")
    # The old format, which it can read, is what the conversion replaces.
    with (league / "players.csv").open(newline="", encoding="utf-8") as fh:
        assert _required_int_7_51_3(next(csv.DictReader(fh)), "height") > 0


def test_a_row_appended_by_an_older_build_is_refused(league, tmp_path):
    path, _ = _scale2_file(league, tmp_path)
    fields, rows = support.read_player_rows(path)
    old = dict(rows[0], player_id="D20280001", height_in="", rating_scale="")
    support.write_player_rows(path, fields, rows + [old])
    with pytest.raises(ValueError, match="D20280001 was written by a build older than 8.0.0"):
        _read_players_from_csv(path)


def test_the_engine_reads_the_height_under_either_name():
    row = {"player_id": "X", "is_pitcher": "0", "height_in": "75", "ch": "50"}
    assert engine_row(row)["height"] == "75"
    assert engine_row(dict(row, rating_scale="2"))["height"] == "75"
    plain = {"player_id": "X", "is_pitcher": "0", "height": "70"}
    assert engine_row(plain) is plain  # a scale 1 file: untouched, same object
    assert row_height(row) == "75" and row_height(plain) == "70"


def test_the_header_helper():
    fields = ["player_id", "height", "weight", "ch"]
    assert players_fieldnames(fields, scale2=True) == [
        "player_id", "height_in", "weight", "ch", "rating_scale"
    ]
    assert players_fieldnames(
        ["player_id", "height_in", "rating_scale"], scale2=False
    ) == ["player_id", "height", "rating_scale"]


def test_a_draft_pick_goes_in_under_the_files_height_name(league, tmp_path, monkeypatch):
    path, _ = _scale2_file(league, tmp_path)
    monkeypatch.setattr(draft_assignment, "_players_csv_path", lambda: path)
    pool_row = {
        "player_id": "D20280002", "first_name": "New", "last_name": "Pick",
        "birthdate": "2008-01-01", "bats": "R", "throws": "R",
        "primary_position": "SS", "is_pitcher": "False", "height": "73",
        "weight": "190", "ch": "40", "ph": "40", "eye": "45", "rating_scale": "",
    }
    draft_assignment._append_players([draft_assignment._default_row_from_pool(pool_row)])
    players = {p.player_id: p for p in _read_players_from_csv(path)}
    pick = players["D20280002"]
    assert pick.height == 73 and pick.rating_scale == 2  # stretched on the way in


def test_a_scale_2_pick_into_an_old_format_marked_file_upgrades_it(
    league, tmp_path, monkeypatch
):
    twin = tmp_path / "twin"
    support.write_stretched_twin(league, twin)  # scale 2 rows, ``height`` header
    path = twin / "players.csv"
    assert "height" in support.read_player_rows(path)[0]
    monkeypatch.setattr(draft_assignment, "_players_csv_path", lambda: path)
    pool_row = {
        "player_id": "D20280003", "first_name": "A", "last_name": "B",
        "birthdate": "2008-01-01", "bats": "R", "throws": "R",
        "primary_position": "SS", "is_pitcher": "False", "height": "71",
        "weight": "190", "ch": "80", "ph": "60", "eye": "60", "rating_scale": "2",
    }
    draft_assignment._append_players([draft_assignment._default_row_from_pool(pool_row)])
    header = support.read_player_rows(path)[0]
    assert SCALE2_HEIGHT_FIELD in header and "height" not in header
    players = {p.player_id: p for p in _read_players_from_csv(path)}
    assert players["D20280003"].height == 71
    assert len(players) == len(support.read_player_rows(league / "players.csv")[1]) + 1


def test_the_working_copy_never_pushes_the_old_format_over_the_new(league, tmp_path):
    new, _ = _scale2_file(league, tmp_path)
    old = league / "players.csv"
    remote = tmp_path / "remote" / "players.csv"
    remote.parent.mkdir()
    shutil.copy2(new, remote)
    assert working_copy._copy_one((old, remote)) == 1  # handled, not copied
    assert remote.read_bytes() == new.read_bytes()
    # The new format over the old, and the new over the new, go through.
    shutil.copy2(old, remote)
    assert working_copy._copy_one((new, remote)) == 1
    assert remote.read_bytes() == new.read_bytes()
    assert working_copy._copy_one((new, remote)) == 1
    # Other files are not looked at.
    other = tmp_path / "remote" / "teams.csv"
    shutil.copy2(league / "teams.csv", other)
    assert working_copy._copy_one((league / "teams.csv", other)) == 1
