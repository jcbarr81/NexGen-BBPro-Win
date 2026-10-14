"""8.0.0 switch ON: a league moves to engine generation 6 and rating scale 2
at the start of its next season, as one step that cannot half-happen.

``services.rating_scale_migration`` and ``services.league_rating_centers``
(``_settle_scale_move``). Every league here is a scratch copy of the
calibration fixture under ``tmp_path``.
"""

from __future__ import annotations

import json
import shutil

import pytest

from physics_sim.engine_generation import engine_profile
from services import league_rating_centers as centers
from services import rating_scale_migration as migration
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    archive_a_season,
    clip_an_active_player,
    game_tuning,
    header,
    news,
    read_rows,
    scale_log,
    scratch,
    stored_generation,
    switch_off,
    switch_on,
    witness,
    write_schedule,
)
from utils.rating_scale import (
    FULL_RATING_SCALE,
    SCALE2_HEIGHT_FIELD,
    engine_row,
    players_file_rating_scale,
    stretch_row,
)


def _first_game(monkeypatch, year: int = 2026) -> dict:
    """The tuning of the season's first game (it fixes the season)."""
    return game_tuning(monkeypatch, f"{year}-04-01")


def _engine_rows(path):
    return {r["player_id"]: dict(engine_row(r)) for r in read_rows(path)[1]}


# --- the whole move ------------------------------------------------------------


def test_the_next_season_moves_to_generation_6_and_scale_2(scratch, monkeypatch, tmp_path):
    data = scratch
    original = (data / "players.csv").read_bytes()
    # The same league, never converted, for the centres comparison.
    twin = tmp_path / "twin"
    shutil.copytree(data, twin)
    archive_a_season(data)
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    # Before the season starts it is offered generation 6, nothing written.
    assert centers.league_engine_generation(store=False) == 6
    assert (data / "players.csv").read_bytes() == original

    tuning = _first_game(monkeypatch)

    # The season's engine generation, written down twice.
    assert stored_generation(data, 2026) == 6
    assert witness(data) == ("2026", 6)
    for key, value in engine_profile(6).items():
        assert tuning[key] == value, key
    # The players file: every row on scale 2, in the scale 2 format.
    path = data / "players.csv"
    assert players_file_rating_scale(path) == FULL_RATING_SCALE
    assert SCALE2_HEIGHT_FIELD in header(path) and "height" not in header(path)
    # ... with the same players, each the stretch of his old row.
    before = read_rows(twin / "players.csv")[1]
    after = {r["player_id"]: r for r in read_rows(path)[1]}
    assert [r["player_id"] for r in before] == list(after)
    for row in before[:50]:
        expected = stretch_row(row, 2)[0]
        got = after[row["player_id"]]
        for key in ("ch", "ph", "eye", "control", "movement", "arm", "fa", "sp"):
            assert got[key] == expected[key], (row["player_id"], key)
        assert got[SCALE2_HEIGHT_FIELD] == row["height"]
    # Read on the engine scale it is the old league exactly.
    old, new = _engine_rows(twin / "players.csv"), _engine_rows(path)
    for pid, row in old.items():
        for key in ("ch", "ph", "eye", "control", "movement", "arm", "fa"):
            if row.get(key) not in ("", None):
                assert float(new[pid][key]) == float(row[key]), (pid, key)
    # The backup is the original file, byte for byte.
    assert (data / "players.scale1.2026.csv").read_bytes() == original
    # The log and the news.
    log = scale_log(data)
    (event,) = [e for e in log["events"] if e["event"] == "converted"]
    assert event["season"] == "2026" and event["engine_generation"] == 6
    assert event["players"] == event["players_converted"] == len(before)
    assert event["backup"] == "players.scale1.2026.csv"
    assert "respread" not in event
    feed = news(data)
    assert "full 1-99 scale" in feed and "updated game engine" in feed
    # The generation 5 item is not posted on top of it.
    assert centers.ENGINE_SWITCH_NEWS not in feed


def test_the_centres_do_not_depend_on_the_order(scratch, monkeypatch, tmp_path):
    """Computed from engine values: the converted league's centres are the
    unconverted league's, key for key."""
    data = scratch
    twin = tmp_path / "twin"
    shutil.copytree(data, twin)
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    stored = json.loads((data / "rating_centers.json").read_text())["seasons"]["2026"]
    # The twin's centres, computed on scale 1, never converted.
    expected = centers.active_rating_centers(twin)
    expected.update(centers.generation_rating_centers(twin))
    for key, value in expected.items():
        if key in stored:
            assert stored[key] == value, key
    assert {k for k in expected if k in centers.RATING_CENTER_KEYS} <= set(stored)
    # And computing them again now, on scale 2, changes nothing.
    again = centers.active_rating_centers(data)
    again.update(centers.generation_rating_centers(data))
    assert again == expected


def test_the_move_is_idempotent(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    path = data / "players.csv"
    converted = path.read_bytes()
    log = scale_log(data)
    result = migration.convert_league(data, "2026")
    assert result.status == "already"
    assert migration.repair_league(data, "2026") is None
    _first_game(monkeypatch)
    assert path.read_bytes() == converted
    assert scale_log(data) == log
    assert stored_generation(data, 2026) == 6
    # Converting a scale 2 row again is the same row.
    for row in read_rows(path)[1][:20]:
        assert stretch_row(row, 2)[0] == row


# --- a crash between the steps --------------------------------------------------


class _Killed(BaseException):
    """A process dying mid-step: no ``except Exception`` catches it."""


def test_a_crash_before_the_players_are_written_leaves_nothing_moved(
    scratch, monkeypatch
):
    data = scratch
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    with monkeypatch.context() as patch:
        def die(*args, **kwargs):
            raise _Killed

        patch.setattr(migration, "_write_players", die)
        with pytest.raises(_Killed):
            _first_game(monkeypatch)
    # Scale 1, no generation anywhere (the backup may already be there).
    assert (data / "players.csv").read_bytes() == original
    assert stored_generation(data, 2026) == "no entry"
    assert witness(data) is None
    centers.clear_rating_center_cache()
    # The next attempt does the whole move.
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    assert players_file_rating_scale(data / "players.csv") == FULL_RATING_SCALE
    assert (data / "players.scale1.2026.csv").read_bytes() == original


def test_a_crash_after_the_players_are_written_is_finished_next_time(
    scratch, monkeypatch
):
    data = scratch
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    with monkeypatch.context() as patch:
        def die(*args, **kwargs):
            raise _Killed

        # Dies after the players file is replaced, before the log, the
        # season's entry and its witness.
        patch.setattr(migration, "_convert_pools", die)
        with pytest.raises(_Killed):
            _first_game(monkeypatch)
    converted = (data / "players.csv").read_bytes()
    assert players_file_rating_scale(data / "players.csv") == FULL_RATING_SCALE
    assert stored_generation(data, 2026) == "no entry"
    assert witness(data) is None
    # A league on scale 2 is offered generation 6 whatever else happens.
    centers.clear_rating_center_cache()
    assert centers.league_engine_generation(store=False) == 6
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    assert witness(data) == ("2026", 6)
    assert (data / "players.csv").read_bytes() == converted  # not converted twice
    assert (data / "players.scale1.2026.csv").read_bytes() == original
    (event,) = scale_log(data)["events"]
    assert event["event"] == "converted" and event["season"] == "2026"


def test_a_crash_after_the_generation_is_written_needs_nothing(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    with monkeypatch.context() as patch:
        real = centers._write_witness

        def die(*args, **kwargs):
            raise _Killed

        patch.setattr(centers, "_write_witness", die)
        with pytest.raises(_Killed):
            _first_game(monkeypatch)
        patch.setattr(centers, "_write_witness", real)
    assert stored_generation(data, 2026) == 6
    assert witness(data) is None
    centers.clear_rating_center_cache()
    _first_game(monkeypatch)
    assert witness(data) == ("2026", 6)  # repaired by the existing rule
    assert players_file_rating_scale(data / "players.csv") == FULL_RATING_SCALE


def test_a_failed_conversion_gives_generation_5_and_scale_1(scratch, monkeypatch):
    """An error (not a dying process) inside the conversion: the season must
    still start, on generation 5 with the league on scale 1."""
    data = scratch
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError("disk full")

        patch.setattr(migration, "_write_players", fail)
        _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    refused = [e for e in scale_log(data)["events"] if e["event"] == "refused"]
    assert refused and "disk full" in refused[0]["reason"]
    assert "[commissioner]" in news(data)


def test_a_players_file_that_loses_its_conversion_is_converted_again(
    scratch, monkeypatch
):
    """A stale scale 1 copy pushed back over a league already recorded on
    generation 6 (or a per-file sync that carried the generation and not the
    players): the next season game converts it; nothing is posted."""
    data = scratch
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    converted = (data / "players.csv").read_bytes()
    feed = news(data)
    shutil.copy(data / "players.scale1.2026.csv", data / "players.csv")
    assert players_file_rating_scale(data / "players.csv") == 1
    _first_game(monkeypatch)
    assert (data / "players.csv").read_bytes() == converted
    assert news(data) == feed
    events = [e["event"] for e in scale_log(data)["events"]]
    assert events == ["converted", "repaired"]


# --- who does not move ----------------------------------------------------------


def test_a_league_mid_season_never_converts(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    write_schedule(data, 2026, played=2)  # games played, nothing recorded
    _first_game(monkeypatch)
    # An entry with no generation: legacy, as at deploy.
    assert stored_generation(data, 2026) is None
    assert centers.league_engine_generation() == 4
    assert (data / "players.csv").read_bytes() == original
    assert not (data / "rating_scale.json").exists()


def test_a_season_fixed_on_generation_5_is_not_moved(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    write_schedule(data, 2026)
    _first_game(monkeypatch)  # switch off: generation 5
    assert stored_generation(data, 2026) == 5
    switch_on(monkeypatch)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original


def test_a_league_that_would_clip_stays_and_the_commissioner_is_told(
    scratch, monkeypatch
):
    data = scratch
    pid = clip_an_active_player(data)
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    assert centers.league_engine_generation(store=False) == 5
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    (event,) = scale_log(data)["events"]
    assert event["event"] == "refused" and pid in event["reason"]
    assert "would not fit the full 1-99 scale" in event["reason"]
    assert pid in news(data) and "[commissioner]" in news(data)


def test_new_seasons_can_be_held_on_generation_5(scratch, monkeypatch):
    """The operations hold still works with the switch on: no move."""
    data = scratch
    original = (data / "players.csv").read_bytes()
    switch_on(monkeypatch)
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "5")
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original


# --- a league created on scale 2 ------------------------------------------------


def test_a_league_already_on_scale_2_starts_on_generation_6_unconverted(
    scratch, monkeypatch
):
    data = scratch
    fields, rows = read_rows(data / "players.csv")
    # As a league created with the switch on is written: scale 2, its format.
    migration._write_players(
        data / "players.csv", fields, [stretch_row(r, 2)[0] for r in rows]
    )
    assert SCALE2_HEIGHT_FIELD in header(data / "players.csv")
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    assert not (data / "rating_scale.json").exists()
    assert not list(data.glob("players.scale1.*"))
    assert news(data) == ""


def test_new_leagues_are_generated_on_scale_2(monkeypatch):
    from utils import rating_scale

    switch_off(monkeypatch)
    assert rating_scale.generated_rating_scale() == 1
    switch_on(monkeypatch)
    assert rating_scale.generated_rating_scale() == 2
    assert rating_scale.GENERATED_RATING_SCALE == 1


def test_a_scale_2_file_in_the_older_format_is_rewritten_in_the_new_one(
    scratch, monkeypatch
):
    """Rows on scale 2 under a ``height`` header (no build writes one now)
    are put in the format older builds refuse; no player value changes."""
    data = scratch
    from tests import rating_scale_support as support

    support.stretch_players_file(data / "players.csv", data / "players.csv.tmp")
    (data / "players.csv.tmp").replace(data / "players.csv")
    before = _engine_rows(data / "players.csv")
    assert "height" in header(data / "players.csv")
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    assert SCALE2_HEIGHT_FIELD in header(data / "players.csv")
    after = _engine_rows(data / "players.csv")
    for pid, row in before.items():
        row.pop("height_in", None)
        after[pid].pop("height_in", None)
        assert after[pid] == row, pid
    assert [e["event"] for e in scale_log(data)["events"]] == ["reformatted"]
    assert news(data) == ""
