"""The ``rating_scale`` column: every reader and writer of player rows.

Each row of ``players.csv`` says which rating scale it is stored on (blank
or no column: scale 1). These tests pin that

* a scale 1 league loads, saves and round-trips byte for byte as it did
  before the column existed, and never gains the column;
* a scale 2 league keeps the column, on every row, through every writer;
* nothing can put rows of two scales in one file, or drop the marker from a
  stretched row (which would play a stretched rating as an engine rating).
"""

from __future__ import annotations

import csv
import hashlib
import json

import pytest

from tests import rating_scale_support as support
from utils import rating_scale
from utils.player_loader import _read_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.rating_scale import MixedRatingScaleError

# The header save_players_to_csv has written since 6.10.12, in its order.
SCALE_1_HEADER = (
    "player_id,first_name,last_name,birthdate,height,weight,ethnicity,"
    "skin_tone,hair_color,facial_hair,bats,throws,primary_position,"
    "other_positions,is_pitcher,role,preferred_pitching_role,ch,ph,sp,eye,gf,"
    "pl,vl,sc,fa,arm,endurance,control,movement,hold_runner,fb,cu,cb,sl,si,"
    "scb,kn,pot_ch,pot_ph,pot_sp,pot_eye,pot_gf,pot_pl,pot_vl,pot_sc,pot_fa,"
    "pot_arm,pot_control,pot_movement,pot_endurance,pot_hold_runner,pot_fb,"
    "pot_cu,pot_cb,pot_sl,pot_si,pot_scb,pot_kn,injured,injury_description,"
    "return_date,ready,injury_list,injury_start_date,injury_minimum_days,"
    "injury_eligible_date,injury_rehab_assignment,injury_rehab_days,"
    "durability,pitcher_archetype,hitter_archetype"
)
# sha256 of save(load(fixture)) computed with the 7.51.3 loader and writer
# (before the column existed) and equal on this branch. RE-PIN only when the
# fixture's players.csv changes.
SAVED_AS_7_51_3 = {
    "calibration_league": "2b14a71699b61eda4c6805dd487cad6d5e8436afb0c27715bf04ca3c35e9f78e",
    "calibration_flat": "cc130615cb127d188c778faa462ae6bd390ec53a2e67ffe0a5d55030ba4ffa94",
}


@pytest.fixture()
def league(tmp_path):
    return support.copy_league(support.FIXTURES["calibration_league"], tmp_path / "plain")


@pytest.fixture()
def twin(league, tmp_path):
    support.write_stretched_twin(league, tmp_path / "twin")
    return tmp_path / "twin"


def _header(path) -> str:
    with path.open(newline="", encoding="utf-8") as fh:
        return fh.readline().rstrip("\r\n")


# --- the one writer --------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SAVED_AS_7_51_3))
def test_a_scale_1_league_saves_exactly_as_before(tmp_path, name):
    source = support.copy_league(support.FIXTURES[name], tmp_path / "league")
    players = _read_players_from_csv(source / "players.csv")
    assert {p.rating_scale for p in players} == {1}
    out = tmp_path / "saved.csv"
    save_players_to_csv(players, str(out))
    assert _header(out) == SCALE_1_HEADER
    assert "rating_scale" not in out.read_text(encoding="utf-8")
    assert hashlib.sha256(out.read_bytes()).hexdigest() == SAVED_AS_7_51_3[name]
    # ... and it is a fixed point: load and save again, same bytes.
    again = tmp_path / "again.csv"
    save_players_to_csv(_read_players_from_csv(out), str(again))
    assert again.read_bytes() == out.read_bytes()


def test_a_blank_column_is_scale_1_and_is_not_written_back(league, tmp_path):
    fields, rows = support.read_player_rows(league / "players.csv")
    blank = tmp_path / "blank.csv"
    support.write_player_rows(
        blank, fields + ["rating_scale"], [dict(r, rating_scale="") for r in rows]
    )
    players = _read_players_from_csv(blank)
    assert {p.rating_scale for p in players} == {1}
    out, reference = tmp_path / "out.csv", tmp_path / "ref.csv"
    save_players_to_csv(players, str(out))
    save_players_to_csv(_read_players_from_csv(league / "players.csv"), str(reference))
    assert out.read_bytes() == reference.read_bytes()


def test_a_scale_2_league_keeps_the_column_on_every_row(twin, tmp_path):
    players = _read_players_from_csv(twin / "players.csv")
    assert {p.rating_scale for p in players} == {2}
    out = tmp_path / "saved.csv"
    save_players_to_csv(players, str(out))
    assert _header(out) == SCALE_1_HEADER + ",rating_scale"
    _fields, rows = support.read_player_rows(out)
    assert {row["rating_scale"] for row in rows} == {"2"}
    assert rating_scale.players_file_rating_scale(out) == 2
    again = tmp_path / "again.csv"
    save_players_to_csv(_read_players_from_csv(out), str(again))
    assert again.read_bytes() == out.read_bytes()


def test_objects_hold_the_stored_values(league, twin):
    plain = {p.player_id: p for p in _read_players_from_csv(league / "players.csv")}
    full = {p.player_id: p for p in _read_players_from_csv(twin / "players.csv")}
    _f, stored = support.read_player_rows(twin / "players.csv")
    moved = 0
    for row in stored:
        player, original = full[row["player_id"]], plain[row["player_id"]]
        keys = rating_scale.moved_rating_keys(2, pitcher=player.is_pitcher)
        for key in keys:
            assert getattr(player, key) == int(row[key])  # as stored
            assert rating_scale.engine_rating(player, key) == getattr(original, key)
            moved += getattr(player, key) != getattr(original, key)
        # A rating the scale does not move is the same number on both.
        for key in ("gf", "durability"):
            assert getattr(player, key) == getattr(original, key)
    assert moved > 3000


def test_the_writer_refuses_mixed_scales_and_leaves_the_file(league, twin, tmp_path):
    plain = _read_players_from_csv(league / "players.csv")
    full = _read_players_from_csv(twin / "players.csv")
    target = tmp_path / "players.csv"
    save_players_to_csv(full, str(target))
    before = target.read_bytes()
    with pytest.raises(MixedRatingScaleError):
        save_players_to_csv(full[:-1] + plain[-1:], str(target))
    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("players")) == [
        "players.csv"
    ]


def test_an_unknown_scale_does_not_load(league, tmp_path):
    fields, rows = support.read_player_rows(league / "players.csv")
    for bad in ("3", "x", "1.5"):
        path = tmp_path / f"bad_{bad}.csv"
        rows[5] = dict(rows[5], rating_scale=bad)
        support.write_player_rows(path, fields + ["rating_scale"], rows)
        with pytest.raises(ValueError, match="rating scale"):
            _read_players_from_csv(path)


def test_the_loaders_fallbacks_are_engine_rules(tmp_path):
    """A blank Eye reads as Contact and a pitcher's missing arm as his
    fastball: on a scale 2 row those are still statements about engine
    ratings."""

    header = SCALE_1_HEADER.split(",") + ["rating_scale"]
    hitter = dict.fromkeys(header, "")
    hitter.update(
        player_id="H1", first_name="A", last_name="B", birthdate="2000-01-01",
        height="72", weight="190", bats="R", primary_position="SS",
        is_pitcher="0", ch="68", ph="50", sp="50", eye="", gf="50", pl="50",
        vl="50", sc="50", fa="50", arm="50", rating_scale="2",
    )
    pitcher = dict.fromkeys(header, "")
    pitcher.update(
        player_id="P1", first_name="C", last_name="D", birthdate="2000-01-01",
        height="74", weight="200", bats="R", primary_position="P",
        is_pitcher="1", gf="50", endurance="60", control="50", movement="50",
        hold_runner="50", fb="70", cu="0", cb="0", sl="0", si="0", scb="0",
        kn="0", arm="", rating_scale="2",
    )
    path = tmp_path / "players.csv"
    support.write_player_rows(path, header, [hitter, pitcher])
    h, p = _read_players_from_csv(path)
    # Stored Contact 68 is engine 56; an Eye of engine 56 is stored 80.
    assert rating_scale.engine_rating(h, "ch") == 56
    assert h.eye == 80 and rating_scale.engine_rating(h, "eye") == 56
    # Fastball 70 (not moved) as an arm: engine 70, stored 50 + 2 * 14.
    assert p.arm == 78 and rating_scale.engine_rating(p, "arm") == 70
    # The same rows on scale 1 keep the plain copy.
    hitter["rating_scale"] = pitcher["rating_scale"] = ""
    support.write_player_rows(path, header, [hitter, pitcher])
    h, p = _read_players_from_csv(path)
    assert (h.eye, p.arm) == (68, 70)


# --- the repository (every save in the app goes through it) -----------------

def test_update_players_keeps_a_league_on_its_scale(twin, league):
    from services import players_repository as repo

    for directory, scale in ((league, 1), (twin, 2)):
        path = directory / "players.csv"
        players = repo.load_players(path)
        before = {p.player_id: p.ch if not p.is_pitcher else p.control for p in players}
        changed = players[3]
        changed.injured = True
        changed.injury_description = "test"
        repo.update_players([changed], path)
        assert rating_scale.players_file_rating_scale(path) == scale
        after = _read_players_from_csv(path)
        assert len(after) == len(players)
        assert {p.rating_scale for p in after} == {scale}
        assert {
            p.player_id: p.ch if not p.is_pitcher else p.control for p in after
        } == before
        assert [p for p in after if p.player_id == changed.player_id][0].injured
        repo.invalidate_players(path)


def test_a_scale_1_player_cannot_be_saved_into_a_scale_2_league(twin, league):
    from services import players_repository as repo

    path = twin / "players.csv"
    before = path.read_bytes()
    stranger = _read_players_from_csv(league / "players.csv")[0]
    stranger.player_id = "NEW1"
    with pytest.raises(MixedRatingScaleError):
        repo.update_players([stranger], path)
    assert path.read_bytes() == before
    repo.invalidate_players(path)


# --- the draft: pool files and the append to players.csv --------------------

def _prospects(scale):
    from playbalance import player_generator
    from playbalance.draft_pool import generate_draft_pool

    player_generator.reset_name_cache()
    return generate_draft_pool(2031, size=24, seed=11, rating_scale=scale)


def test_a_scale_1_draft_pool_is_written_without_the_field(tmp_path, monkeypatch):
    from playbalance import draft_pool

    monkeypatch.setattr(draft_pool, "_base_dir", lambda: tmp_path)
    pool = _prospects(1)
    assert {p.rating_scale for p in pool} == {1}
    draft_pool.save_draft_pool(2031, pool)
    saved = json.loads((tmp_path / "draft_pool_2031.json").read_text(encoding="utf-8"))
    assert len(saved) == 24 and all("rating_scale" not in p for p in saved)
    assert "rating_scale" not in _header(tmp_path / "draft_pool_2031.csv")
    assert saved[0]["player_id"] == "D20310001" and "pot_kn" in saved[0]


def test_a_scale_2_draft_pool_carries_the_field_in_both_files(tmp_path, monkeypatch):
    from playbalance import draft_pool

    monkeypatch.setattr(draft_pool, "_base_dir", lambda: tmp_path)
    pool = _prospects(2)
    assert {p.rating_scale for p in pool} == {2}
    draft_pool.save_draft_pool(2031, pool)
    saved = draft_pool.load_draft_pool(2031)
    assert {p["rating_scale"] for p in saved} == {2}
    with (tmp_path / "draft_pool_2031.csv").open(newline="", encoding="utf-8") as fh:
        assert {row["rating_scale"] for row in csv.DictReader(fh)} == {"2"}
    # A pool on two scales is refused before a file is opened.
    mixed = _prospects(1)[:3] + pool[:3]
    with pytest.raises(MixedRatingScaleError):
        draft_pool.save_draft_pool(2032, mixed)
    assert not (tmp_path / "draft_pool_2032.json").exists()


def test_a_draft_class_takes_the_scale_of_the_league_it_is_for(
    league, twin, monkeypatch
):
    from playbalance import draft_pool, player_generator

    for directory, scale in ((league, 1), (twin, 2)):
        monkeypatch.setattr(draft_pool, "_base_dir", lambda d=directory: d)
        player_generator.reset_name_cache()
        pool = draft_pool.generate_draft_pool(2031, size=12, seed=3)
        assert {p.rating_scale for p in pool} == {scale}


def _draft_setup(directory, monkeypatch, scale):
    """A pool on ``scale`` saved in the league ``directory``; the picks'
    pool rows as the commit reads them."""

    from playbalance import draft_pool
    from services import draft_assignment

    monkeypatch.setattr(draft_pool, "_base_dir", lambda: directory)
    monkeypatch.setattr(draft_assignment, "_data_dir", lambda: directory)
    monkeypatch.setattr(draft_assignment, "reset_player_cache", lambda: None)
    draft_pool.save_draft_pool(2031, _prospects(scale))
    pool = draft_assignment._load_pool_map(2031)
    return draft_assignment, [
        draft_assignment._default_row_from_pool(row) for row in list(pool.values())[:5]
    ]


def test_picks_appended_to_a_scale_1_league_change_nothing_else(league, monkeypatch):
    assign, rows = _draft_setup(league, monkeypatch, 1)
    path = league / "players.csv"
    before = path.read_bytes()
    assign._append_players(rows)
    after = path.read_bytes()
    assert after.startswith(before) and "rating_scale" not in _header(path)
    players = _read_players_from_csv(path)
    assert {p.rating_scale for p in players} == {1}
    assert [p.player_id for p in players[-5:]] == [r["player_id"] for r in rows]


def test_picks_appended_to_a_scale_2_league_stay_on_scale_2(twin, monkeypatch):
    assign, rows = _draft_setup(twin, monkeypatch, 2)
    path = twin / "players.csv"
    assign._append_players(rows)
    assert rating_scale.players_file_rating_scale(path) == 2
    added = _read_players_from_csv(path)[-5:]
    for player, row in zip(added, rows):
        key = "control" if player.is_pitcher else "ch"
        assert getattr(player, key) == int(row[key])  # stored as the pool had it


def test_a_scale_1_pick_is_stretched_on_its_way_into_a_scale_2_league(
    twin, monkeypatch
):
    assign, rows = _draft_setup(twin, monkeypatch, 1)
    path = twin / "players.csv"
    assign._append_players(rows)
    assert rating_scale.players_file_rating_scale(path) == 2  # not a mixed file
    added = _read_players_from_csv(path)[-5:]
    for player, row in zip(added, rows):
        key = "control" if player.is_pitcher else "ch"
        expected = rating_scale.to_stored(key, row[key], 2, pitcher=player.is_pitcher)
        assert getattr(player, key) == expected
        # What the engine will read is the rating the pool gave him, unless
        # it sat below the scale's floor.
        if expected > 1:
            assert rating_scale.engine_rating(player, key) == row[key]


def test_a_scale_2_pick_never_lands_unmarked_in_a_scale_1_league(league, monkeypatch):
    assign, rows = _draft_setup(league, monkeypatch, 2)
    path = league / "players.csv"
    before = path.read_bytes()
    with pytest.raises(MixedRatingScaleError):
        assign._append_players(rows)
    assert path.read_bytes() == before
