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


def test_a_mixed_list_is_written_row_by_row_with_a_warning(
    league, twin, tmp_path, caplog
):
    """One stray row must not stop every save in a league: each row is
    written on its own scale and reads back correctly."""

    plain = _read_players_from_csv(league / "players.csv")
    full = _read_players_from_csv(twin / "players.csv")
    target = tmp_path / "players.csv"
    mixed = full[:-3] + plain[-3:]
    with caplog.at_level("WARNING", logger="utils.player_writer"):
        save_players_to_csv(mixed, str(target))
    assert "mixed rating scales" in caplog.text
    assert all(p.player_id in caplog.text for p in plain[-3:])
    _f, rows = support.read_player_rows(target)
    assert [row["rating_scale"] for row in rows[-4:]] == ["2", "1", "1", "1"]
    assert rating_scale.players_file_rating_scale(target) == rating_scale.MIXED_RATING_SCALES
    again = _read_players_from_csv(target)
    for before, after in zip(mixed, again):
        assert after.rating_scale == before.rating_scale
        for key in ("ch", "ph", "eye", "arm", "control", "movement", "fa"):
            assert rating_scale.engine_rating(
                after, key, None
            ) == rating_scale.engine_rating(before, key, None)


def test_the_reviewers_mixed_file_still_saves(league, tmp_path):
    """Ten stretched rows in a scale 1 league (review test, ported)."""

    fields, rows = support.read_player_rows(league / "players.csv")
    twin, _ = rating_scale.stretch_rows(rows[:10], 2)
    mixed = twin + [dict(r, rating_scale="") for r in rows[10:]]
    support.write_player_rows(tmp_path / "players.csv", fields + ["rating_scale"], mixed)
    players = _read_players_from_csv(tmp_path / "players.csv")
    save_players_to_csv(players, str(tmp_path / "out.csv"))
    assert rating_scale.players_file_rating_scales(tmp_path / "out.csv") == {
        2: 10, 1: len(rows) - 10,
    }


# --- the loader's fallbacks on a stretched file (review findings) ----------

FALLBACK_HEADER = (
    "player_id,first_name,last_name,birthdate,height,weight,bats,"
    "primary_position,is_pitcher,ch,ph,sp,eye,gf,pl,vl,sc,fa,arm,endurance,"
    "control,movement,hold_runner,fb,cu,cb,sl,si,scb,kn,pot_ch,pot_eye,pot_arm"
).split(",")


def _fallback_rows(contact, fastball, arm):
    hitter = dict.fromkeys(FALLBACK_HEADER, "")
    hitter.update(
        player_id="H", first_name="A", last_name="B", birthdate="2000-01-01",
        height="72", weight="190", bats="R", primary_position="SS",
        is_pitcher="0", ch=contact, ph="50", sp="50", eye="", gf="50",
        pl="50", vl="50", sc="50", fa="50", arm="50", pot_ch="66", pot_eye="66",
    )
    pitcher = dict.fromkeys(FALLBACK_HEADER, "")
    pitcher.update(
        player_id="P", first_name="C", last_name="D", birthdate="2000-01-01",
        height="74", weight="200", bats="R", primary_position="P",
        is_pitcher="1", gf="50", endurance="60", control="50", movement="56",
        hold_runner="50", fb=fastball, cu="0", cb="0", sl="0", si="0",
        scb="0", kn="0", arm=arm, pot_arm="0",
    )
    return [hitter, pitcher]


def _fallback_pair(tmp_path, contact, fastball, arm):
    one = tmp_path / "s1.csv"
    support.write_player_rows(one, FALLBACK_HEADER, _fallback_rows(contact, fastball, arm))
    clips = support.stretch_players_file(one, tmp_path / "s2.csv")
    return clips, {
        name: {p.player_id: p for p in _read_players_from_csv(tmp_path / f"{name}.csv")}
        for name in ("s1", "s2")
    }


def _engine_reads(path):
    from physics_sim.models import BatterRatings, PitcherRatings

    with path.open(newline="", encoding="utf-8") as fh:
        rows = {row["player_id"]: row for row in csv.DictReader(fh)}
    return BatterRatings.from_row(rows["H"]).eye, PitcherRatings.from_row(rows["P"]).arm


@pytest.mark.parametrize("arm", ["0", ""])
def test_fallbacks_inside_the_scale_are_identical_everywhere(tmp_path, arm):
    """Blank Eye, Contact 55; missing arm, fastball 70: both fit scale 2."""

    clips, players = _fallback_pair(tmp_path, "55", "70", arm)
    assert clips == []
    one, two = players["s1"], players["s2"]
    assert rating_scale.engine_rating(two["H"], "eye") == 55 == one["H"].eye
    # The gap over the filled Eye is kept (11 points, all of it under the
    # part development never closes, so the consumer view is the rating).
    assert two["H"].potential["eye"] - two["H"].eye == 11
    assert rating_scale.engine_potential(two["H"], "eye") == 55
    assert rating_scale.engine_potential(one["H"], "eye") == 66
    assert rating_scale.engine_rating(two["P"], "arm") == 70 == one["P"].arm
    # The engine reads the stretched file as the loader does ...
    assert _engine_reads(tmp_path / "s2.csv") == (55, 70)
    # ... and after one save of each, both play the same player.
    save_players_to_csv(list(one.values()), str(tmp_path / "s1b.csv"))
    save_players_to_csv(list(two.values()), str(tmp_path / "s2b.csv"))
    assert _engine_reads(tmp_path / "s1b.csv") == _engine_reads(tmp_path / "s2b.csv")


def test_fallbacks_outside_the_scale_are_reported_and_read_one_way(tmp_path):
    """Contact 62 (Eye 62 > 59.8) and fastball 85 (arm 85 > 80.5) cannot be
    stored on scale 2: the conversion says so, and the loader and the
    engine then agree on the value that was stored."""

    clips, players = _fallback_pair(tmp_path, "62", "85", "0")
    assert {(c.player_id, c.key, c.kind, c.source) for c in clips} == {
        ("H", "eye", "rating", "ch"),
        ("H", "pot_eye", "potential", ""),
        ("P", "arm", "rating", "fb"),
    }
    two = players["s2"]
    eye = rating_scale.engine_rating(two["H"], "eye")
    arm = rating_scale.engine_rating(two["P"], "arm")
    assert (eye, arm) == (pytest.approx(59.8), 80.5)
    # The potential is the stored 99 (no longer an engine 66 left behind).
    assert rating_scale.engine_potential(two["H"], "eye") == pytest.approx(59.8)
    assert _engine_reads(tmp_path / "s2.csv") == (pytest.approx(59.8), 80.5)
    save_players_to_csv(list(two.values()), str(tmp_path / "s2b.csv"))
    assert _engine_reads(tmp_path / "s2b.csv") == (pytest.approx(59.8), 80.5)


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


def test_a_scale_1_player_saved_into_a_scale_2_league_keeps_his_scale(
    twin, league, caplog
):
    from services import players_repository as repo

    path = twin / "players.csv"
    stranger = _read_players_from_csv(league / "players.csv")[0]
    stranger.player_id = "NEW1"
    with caplog.at_level("WARNING", logger="utils.player_writer"):
        repo.update_players([stranger], path)
    assert "NEW1" in caplog.text
    saved = {p.player_id: p for p in _read_players_from_csv(path)}
    assert saved["NEW1"].rating_scale == 1
    key = "control" if stranger.is_pitcher else "ch"
    # Read as the engine rating it is, not through the scale 2 map.
    assert getattr(saved["NEW1"], key) == getattr(stranger, key)
    assert rating_scale.engine_rating(saved["NEW1"], key) == getattr(stranger, key)
    assert {p.rating_scale for pid, p in saved.items() if pid != "NEW1"} == {2}
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
    # A pool on two scales (a bug) is written entry by entry, each on its
    # own scale, rather than lost.
    mixed = _prospects(1)[:3] + pool[:3]
    draft_pool.save_draft_pool(2032, mixed)
    saved = draft_pool.load_draft_pool(2032)
    assert [p["rating_scale"] for p in saved] == [1, 1, 1, 2, 2, 2]


def test_a_draft_class_takes_the_scale_of_the_league_it_is_for(
    league, twin, monkeypatch
):
    from playbalance import draft_pool, player_generator

    for directory, scale in ((league, 1), (twin, 2)):
        monkeypatch.setattr(draft_pool, "_base_dir", lambda d=directory: d)
        player_generator.reset_name_cache()
        pool = draft_pool.generate_draft_pool(2031, size=12, seed=3)
        assert {p.rating_scale for p in pool} == {scale}


def test_a_mixed_league_drafts_on_its_majority_scale(league, twin, tmp_path, monkeypatch):
    from playbalance import draft_pool, player_generator

    fields, plain = support.read_player_rows(league / "players.csv")
    _f, full = support.read_player_rows(twin / "players.csv")
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    support.write_player_rows(
        mixed / "players.csv",
        fields + ["rating_scale"],
        full[:-5] + [dict(r, rating_scale="") for r in plain[-5:]],
    )
    monkeypatch.setattr(draft_pool, "_base_dir", lambda: mixed)
    player_generator.reset_name_cache()
    pool = draft_pool.generate_draft_pool(2031, size=6, seed=3)
    assert {p.rating_scale for p in pool} == {2}
    # Split evenly, there is no league scale to pick: refused, and says why.
    half = len(full) // 2
    support.write_player_rows(
        mixed / "players.csv",
        fields + ["rating_scale"],
        full[:half] + [dict(r, rating_scale="") for r in plain[half : 2 * half]],
    )
    with pytest.raises(MixedRatingScaleError, match="split evenly"):
        draft_pool.generate_draft_pool(2031, size=6, seed=3)


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
    twin, monkeypatch, caplog
):
    assign, rows = _draft_setup(twin, monkeypatch, 1)
    path = twin / "players.csv"
    # One pick whose Eye sits below what scale 2 can store: logged.
    low = next(r for r in rows if r["is_pitcher"] == 0)
    low["eye"] = 25
    with caplog.at_level("WARNING", logger="services.draft_assignment"):
        assign._append_players(rows)
    assert f"draft pick {low['player_id']}: rating eye" in caplog.text
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
    with pytest.raises(MixedRatingScaleError, match="no rating_scale column"):
        assign._append_players(rows)
    assert path.read_bytes() == before


def test_a_scale_2_pick_keeps_his_marker_in_a_mixed_scale_1_league(
    league, tmp_path, monkeypatch, caplog
):
    """A league mostly on scale 1 whose file has the column (a stray scale
    2 row): the pick goes in on his own scale, never unmarked."""

    fields, rows = support.read_player_rows(league / "players.csv")
    stray, _ = rating_scale.stretch_row(rows[0], 2)
    support.write_player_rows(
        league / "players.csv",
        fields + ["rating_scale"],
        [stray] + [dict(r, rating_scale="") for r in rows[1:]],
    )
    assign, picks = _draft_setup(league, monkeypatch, 2)
    with caplog.at_level("WARNING", logger="services.draft_assignment"):
        assign._append_players(picks)
    assert "appended on his own scale" in caplog.text
    added = _read_players_from_csv(league / "players.csv")[-5:]
    assert {p.rating_scale for p in added} == {2}


def test_a_scale_2_pool_entry_missing_ratings_gets_scale_2_defaults(
    twin, monkeypatch
):
    """The defaults are ENGINE numbers: 50 means the engine's average, and a
    missing Eye is the player's Contact, on whatever scale the pool is."""

    from services import draft_assignment

    hitter = {
        "player_id": "D1", "is_pitcher": "0", "ch": "62", "ph": "95",
        "rating_scale": "2",
    }
    row = draft_assignment._default_row_from_pool(hitter)
    assert (row["fa"], row["arm"]) == (48, 48)  # engine 50 vs pivot 52
    assert (row["sp"], row["gf"]) == (50, 50)  # not moved
    assert row["eye"] == 70  # Contact 62 is engine 54, Eye 54 is stored 70
    assert rating_scale.engine_rating(row, "eye") == 54
    assert rating_scale.engine_rating(row, "fa") == 50
    pitcher = {"player_id": "D2", "is_pitcher": "1", "fb": "70", "rating_scale": "2"}
    row = draft_assignment._default_row_from_pool(pitcher)
    assert row["arm"] == 44 and rating_scale.engine_rating(row, "arm") == 50
    assert (row["control"], row["movement"]) == (0, 0)  # "no rating" stays 0
    # A scale 1 entry keeps the plain engine defaults, as before.
    row = draft_assignment._default_row_from_pool(dict(hitter, rating_scale=""))
    assert (row["fa"], row["arm"], row["eye"]) == (50, 50, 62)
