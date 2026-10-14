"""alpha-test's re-spread (owner decision 15), a separate optional step of
the move: each BUNCHED rating mapped by rank onto a normal league's spread,
in engine points, before the stretch, keeping each rating's ACT mean.

The flat fixture (``data/calibration_flat``) is bunched exactly as alpha-test
is (the same twelve ratings are picked) and stands in for it here.
"""

from __future__ import annotations

import json
import shutil
import statistics

import pytest

from services import rating_scale_migration as migration
from tests import rating_scale_support as support
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    CALIBRATION_LEAGUE,
    archive_a_season,
    game_tuning,
    news,
    read_rows,
    scale_log,
    scratch,
    stored_generation,
    switch_on,
    write_schedule,
)
from utils.rating_scale import engine_row, stretch_row

FLAT = support.FIXTURES["calibration_flat"]
TWELVE = {
    ("hitter", "eye"), ("hitter", "fa"), ("hitter", "arm"), ("hitter", "gf"),
    ("hitter", "pl"), ("pitcher", "control"), ("pitcher", "movement"),
    ("pitcher", "arm"), ("pitcher", "endurance"), ("pitcher", "hold_runner"),
    ("pitcher", "fa"), ("pitcher", "gf"),
}


def _respread(base):
    rows = read_rows(base / "players.csv")[1]
    active = migration._active_ids(base)
    rotation = migration._rotation_ids(base)
    return rows, active, rotation, migration.respread_rows(
        rows, active_ids=active, rotation_ids=rotation
    )


@pytest.fixture(scope="module")
def flat():
    return _respread(FLAT)


def test_the_reference_is_the_league_fixtures_spread():
    stored = migration.load_respread_reference()
    assert stored == migration.build_respread_reference(CALIBRATION_LEAGUE)
    assert (
        migration.RESPREAD_REFERENCE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        == migration.format_respread_reference(stored)
    )


def test_the_measured_rule_picks_the_bunched_ratings(flat):
    _rows, _active, _rotation, result = flat
    assert {(r.group, r.key) for r in result.moved} == TWELVE
    for rating in result.ratings:
        ratio = rating.league_sd / rating.reference_sd
        assert rating.bunched == (ratio < migration.BUNCHED_SD_RATIO)
    # A league as the product creates one has nothing bunched.
    for base in (CALIBRATION_LEAGUE, support.FIXTURES["calibration"]):
        assert _respread(base)[3].moved == []


def _pairs(rows, new_rows, group, key, active=None):
    out = []
    for old, new in zip(rows, new_rows):
        if migration._group(old) != group:
            continue
        o, n = migration._value(old, key), migration._value(new, key)
        if o is None:
            continue
        if active is not None and old["player_id"] not in active:
            continue
        out.append((old, o, n))
    return out


def test_every_players_place_is_kept(flat):
    rows, _active, rotation, result = flat
    for rating in result.moved:
        pairs = _pairs(rows, result.rows, rating.group, rating.key)
        groups = [pairs]
        if rating.key == "endurance":
            # Starters are ranked above every other arm: order is kept
            # within each.
            groups = [
                [p for p in pairs if p[0]["player_id"] in rotation],
                [p for p in pairs if p[0]["player_id"] not in rotation],
            ]
        for members in groups:
            ordered = sorted(members, key=lambda p: p[1])
            for (_, o1, n1), (_, o2, n2) in zip(ordered, ordered[1:]):
                if o2 > o1:
                    assert n2 >= n1, (rating.key, o1, o2, n1, n2)
        if rating.key == "endurance":
            # Every rotation starter sits at or above every other arm.
            assert min(p[2] for p in groups[0]) >= max(p[2] for p in groups[1])
        assert all(1 <= p[2] <= 99 and p[2] == int(p[2]) for p in pairs)


def test_ties_are_broken_by_pitch_grades_then_a_seeded_draw(flat):
    rows, active, _rotation, result = flat
    pairs = _pairs(rows, result.rows, "pitcher", "movement")
    tied = [p for p in pairs if p[1] == pairs[0][1]]
    assert len(tied) > 100  # movement is one value for most of the league
    for (r1, _o1, n1), (r2, _o2, n2) in zip(tied, tied[1:]):
        g1, g2 = migration._pitch_grade_mean(r1), migration._pitch_grade_mean(r2)
        if g1 > g2:
            assert n1 >= n2
        elif g2 > g1:
            assert n2 >= n1
    # The draw is fixed: the same players in any order get the same values.
    reversed_rows = list(reversed(rows))
    again = migration.respread_rows(
        reversed_rows, active_ids=active, rotation_ids=migration._rotation_ids(FLAT)
    )
    first = {r["player_id"]: r for r in result.rows}
    for row in again.rows:
        assert row == first[row["player_id"]]


def test_the_active_means_are_kept_and_the_spread_is_the_references(flat):
    rows, active, _rotation, result = flat
    reference = migration.load_respread_reference()["ratings"]
    for rating in result.moved:
        pairs = _pairs(rows, result.rows, rating.group, rating.key, active)
        before = statistics.fmean(p[1] for p in pairs)
        after = statistics.fmean(p[2] for p in pairs)
        assert abs(after - before) <= 0.5, (rating.key, before, after)
        # The whole population is mapped onto the reference's whole
        # population, so the active rosters come out near (not exactly at)
        # the reference's active spread: a bunched league's regulars are
        # spread through its whole population, a normal league's sit at
        # the top of it (flat fixture: 0.8-1.35x; alpha-test 0.8-1.1x).
        ref_sd = reference[rating.group][rating.key]["act_sd"]
        assert 0.7 * ref_sd <= statistics.pstdev(p[2] for p in pairs) <= 1.4 * ref_sd
    # Ratings that were not bunched, and every other column, are untouched.
    moved = {r.key for r in result.moved}
    for old, new in zip(rows, result.rows):
        for key, value in old.items():
            base = key[4:] if key.startswith("pot_") else key
            if base not in moved:
                assert new[key] == value, key


def test_potentials_keep_their_gap(flat):
    rows, _active, _rotation, result = flat
    for old, new in list(zip(rows, result.rows))[:200]:
        for rating in result.moved:
            if migration._group(old) != rating.group:
                continue
            o, n = migration._value(old, rating.key), migration._value(new, rating.key)
            po = migration._value(old, f"pot_{rating.key}")
            if o is None or po is None:
                continue
            pn = migration._value(new, f"pot_{rating.key}")
            assert pn == min(99, n + max(0, po - o))


def test_the_move_respreads_before_the_stretch_and_logs_it_separately(
    scratch, monkeypatch
):
    data = scratch
    # The scratch league is the flat fixture here.
    for name in ("players.csv",):
        shutil.copy(FLAT / name, data / name)
    shutil.rmtree(data / "rosters")
    shutil.rmtree(data / "lineups")
    shutil.copytree(FLAT / "rosters", data / "rosters")
    shutil.copytree(FLAT / "lineups", data / "lineups")
    # Blank pitch grades read as 0 by the league loader.
    fields, rows = read_rows(data / "players.csv")
    for row in rows:
        for key in support.PITCH_KEYS:
            if row.get(key) == "":
                row[key] = "0"
    support.write_player_rows(data / "players.csv", fields, rows)
    expected = migration.respread_rows(
        rows,
        active_ids=migration._active_ids(data),
        rotation_ids=migration._rotation_ids(data),
    )
    archive_a_season(data)
    monkeypatch.setenv(migration.RESPREAD_LEAGUES_ENV, "other-league, r5flip")
    assert migration.respread_requested(data)
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(data, 2026) == 6
    got = {r["player_id"]: r for r in read_rows(data / "players.csv")[1]}
    for row in expected.rows[:300]:
        stretched = stretch_row(row, 2)[0]
        for key in ("eye", "fa", "arm", "control", "movement", "endurance", "ch"):
            assert got[row["player_id"]][key] == stretched[key], key
    (event,) = scale_log(data)["events"]
    spread = event["respread"]
    assert {(r["group"], r["key"]) for r in spread["ratings"]} == TWELVE
    assert spread["seed"] == migration.RESPREAD_SEED
    for item in spread["ratings"]:
        assert item["stored_range"] and item["stored_range_unspread"]
    # Two news items: the move, and the re-spread on its own.
    feed = news(data)
    assert "full 1-99 scale" in feed
    assert "r5flip's ratings were spread out" in feed
    assert "Stamina now follows each staff's rotation" in feed
    # The centres were computed from the re-spread league.
    stored = json.loads((data / "rating_centers.json").read_text())["seasons"]["2026"]
    after = {r["player_id"]: dict(engine_row(r)) for r in read_rows(data / "players.csv")[1]}
    from services.league_rating_centers import active_rating_centers

    assert stored["pitcher_control_center"] == active_rating_centers(data)["pitcher_control_center"]
    assert len(after) == len(rows)


def test_without_the_flag_nothing_is_respread(scratch, monkeypatch):
    data = scratch
    monkeypatch.delenv(migration.RESPREAD_LEAGUES_ENV, raising=False)
    assert not migration.respread_requested(data)
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    (event,) = scale_log(data)["events"]
    assert "respread" not in event
    assert "ratings were spread out" not in news(data)
