"""Release 6a (fielding): the fielder centres on the live path.

The engine's ``fielder_centred_ratings`` reads fifteen centres: the lineup
regulars' mean fielding and arm at each of the seven positions a batted
ball is fielded from, and the pitchers' fielding
(``services.league_rating_centers.FIELDER_CENTER_KEYS``). The KPI harness
has supplied them since the tooling step; this is how a LEAGUE game gets
them:

* a season on generation 6 holds them in its ``rating_centers.json`` entry,
  computed with the entry, frozen for the season and delivered with the
  rest of the game's tuning;
* a legacy or generation 5 season is never asked for them: nothing is
  computed, cached, delivered or written for it, its entry and its file
  keep their bytes, and no key a game of such a season requires is added.

No league can be given generation 6 yet (``physics_sim.engine_generation``),
so the generation 6 seasons here are either recorded by hand in a scratch
league's files or started with the development generation promoted for the
test.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import physics_sim.engine_generation as generations
from physics_sim import centred_ratings
from physics_sim.centred_ratings import (
    RatingCenterMissing,
    require_fielder_centers,
    require_rating_centers,
)
from physics_sim.config import DEFAULT_TUNING, load_tuning
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    NEW_SEASON_ENGINE_ENV,
    centres_as_7_50_3,
    game_tuning,
    league,
    stored_generation,
    witness,
    write_schedule,
)

REPO = Path(__file__).resolve().parents[1]
POSITIONS = ("1B", "2B", "3B", "SS", "LF", "CF", "RF")
FIELDER_KEYS = (
    tuple(f"fielder_fa_center_{p.lower()}" for p in POSITIONS)
    + tuple(f"fielder_arm_center_{p.lower()}" for p in POSITIONS)
    + ("fielder_fa_center_p",)
)
OPENING_DAY = "2027-04-01"


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _path(data: Path) -> Path:
    return data / centers.RATING_CENTERS_FILENAME


def _entry(data: Path, season=2027) -> dict:
    return json.loads(_path(data).read_text(encoding="utf-8"))["seasons"][str(season)]


def _write_entry(data: Path, entry: dict, season=2027) -> bytes:
    payload = {"version": 1, "seasons": {str(season): entry}}
    _path(data).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _path(data).read_bytes()


def _promote_generation_6(monkeypatch) -> None:
    """Make generation 6 the one a new season starts on, as the switch-on
    will (``CURRENT_ENGINE_GENERATION``), for this test only."""
    monkeypatch.setattr(generations, "CURRENT_ENGINE_GENERATION", 6)
    monkeypatch.setattr(generations, "DEVELOPMENT_ENGINE_GENERATIONS", ())
    monkeypatch.setattr(centers, "CURRENT_ENGINE_GENERATION", 6)


# --- what they are ------------------------------------------------------------------


def test_the_fifteen_keys_and_who_reads_them():
    assert centers.FIELDER_CENTER_KEYS == FIELDER_KEYS
    assert set(FIELDER_KEYS) == set(centred_ratings.FIELDER_CENTER_KEYS)
    assert centers.GENERATION_CENTER_KEYS == {6: FIELDER_KEYS}
    assert centers.PITCHER_FA_CENTER_KEY == "fielder_fa_center_p"
    for key in FIELDER_KEYS:
        assert DEFAULT_TUNING[key] == 50.0
    # They are not among the centres every league stores, and not one a
    # generation 5 game is refused without.
    assert not set(FIELDER_KEYS) & set(centers.RATING_CENTER_KEYS)
    assert not set(FIELDER_KEYS) & set(centers.RELATIVE_CENTER_KEYS)
    assert not set(FIELDER_KEYS) & centred_ratings.REQUIRED_CENTER_KEYS
    assert not set(FIELDER_KEYS) & centred_ratings.CENTRED_RATING_KEYS
    assert set(FIELDER_KEYS) <= set(centers.UNSTORED_CENTER_KEYS)


def test_the_values_are_the_harness_s(league):
    """One computation: what a league stores is what the KPI harness has
    been handing the engine."""
    live = centers.fielder_rating_centers(league)
    assert tuple(live) == FIELDER_KEYS
    harness = centers.unstored_rating_centers(league)
    assert {key: harness[key] for key in FIELDER_KEYS} == live
    assert live["fielder_fa_center_ss"] > live["fielder_fa_center_lf"] + 3.0
    assert 40.0 < live["fielder_fa_center_p"] < 60.0
    assert centers.fielder_rating_centers(league / "nowhere") == {}


def test_a_position_no_regular_plays_reads_the_mean_over_every_position(tmp_path):
    """The engine refuses a game on a centre that was not delivered, so a
    club that leaves a spot blank must not leave the league without one."""
    fields = ["player_id", "primary_position", "is_pitcher", "bats", "ch", "ph",
              "sp", "fa", "arm"]
    fas = {"C": 40, "1B": 44, "2B": 52, "3B": 50, "SS": 60, "LF": 46, "CF": 58}
    (tmp_path / "rosters").mkdir()
    with (tmp_path / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for pos, fa in fas.items():
            writer.writerow({
                "player_id": pos, "primary_position": pos, "is_pitcher": "0",
                "bats": "R", "ch": 50, "ph": 50, "sp": 50, "fa": fa, "arm": fa + 2,
            })
    with (tmp_path / "rosters" / "A.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows((pos, "ACT") for pos in fas)
    out = centers.fielder_rating_centers(tmp_path)
    fielders = [fa for pos, fa in fas.items() if pos != "C"]
    mean = round(sum(fielders) / len(fielders), 2)
    assert out["fielder_fa_center_ss"] == 60.0 and out["fielder_fa_center_cf"] == 58.0
    assert out["fielder_fa_center_rf"] == mean
    assert out["fielder_arm_center_rf"] == mean + 2
    # No pitcher, no pitcher centre -- and a league with no fielder at all
    # has none of them.
    assert "fielder_fa_center_p" not in out
    assert set(out) == set(FIELDER_KEYS) - {"fielder_fa_center_p"}


# --- a generation 5 season ----------------------------------------------------------


def test_a_generation_5_season_is_given_none_and_stores_none(league, monkeypatch):
    write_schedule(league, 2027)
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    assert tuning["swing_model"] == 1.0 and stored_generation(league, 2027) == 5
    assert not set(tuning) & set(FIELDER_KEYS)
    entry = _entry(league)
    # Exactly the entry 7.51.3 writes: the stored centres, the generation
    # and the Release 5 marker. No new key.
    assert set(entry) == set(centers.RATING_CENTER_KEYS) | {
        centers.ENGINE_GENERATION_KEY, centers.CENTERS_VERSION_KEY
    }
    before = _path(league).read_bytes()
    progress = (league / "season_progress.json").read_bytes()
    for store in (True, False):
        assert not set(centers.league_rating_centers(store=store)) & set(FIELDER_KEYS)
        assert not set(centers.get_rating_center_overrides(store=store)) & set(
            FIELDER_KEYS
        )
    centers.clear_rating_center_cache()
    again = game_tuning(monkeypatch, OPENING_DAY)
    assert again == tuning
    assert _path(league).read_bytes() == before
    assert (league / "season_progress.json").read_bytes() == progress
    # The game starts: nothing it requires is missing.
    require_rating_centers(load_tuning(tuning))
    require_fielder_centers(load_tuning(tuning))


def test_a_generation_5_season_is_not_asked_twice(league, monkeypatch):
    """Once the season is known not to read them, they are not looked for
    again: no file is read for them on the next game."""
    write_schedule(league, 2027)
    first = centers.league_rating_centers()
    reads = []
    real = centers._read_json

    def counting(path):
        reads.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(centers, "_read_json", counting)
    monkeypatch.setattr(
        centers, "fielder_rating_centers",
        lambda *a, **k: pytest.fail("worked out for a generation 5 season"),
    )
    assert centers.league_rating_centers() == first
    assert centers.get_rating_center_overrides() == first
    assert reads == []


def test_clearing_the_centre_caches_forgets_which_seasons_do_not_read_them(league):
    """The note that a season does not read the fielder centres is a cache
    like the centres themselves: it is dropped with them
    (``clear_rating_center_cache``, which the working copy calls when it
    pulls a ``rating_centers.json`` from the durable copy), so a file that
    now records generation 6 for the season is read again."""
    write_schedule(league, 2027, played=2)
    stored = centers.active_rating_centers(league)
    _write_entry(league, {
        **stored, centers.ENGINE_GENERATION_KEY: 5,
        centers.CENTERS_VERSION_KEY: centers.CENTERS_VERSION,
    })
    assert not set(centers.league_rating_centers()) & set(FIELDER_KEYS)
    assert centers._NOT_READ
    # The durable copy says generation 6 (both records).
    _write_entry(league, {
        **stored, centers.ENGINE_GENERATION_KEY: 6,
        centers.CENTERS_VERSION_KEY: centers.CENTERS_VERSION,
    })
    progress = json.loads((league / "season_progress.json").read_text())
    progress["engine_generation"] = {"season": "2027", "generation": 6}
    (league / "season_progress.json").write_text(json.dumps(progress))
    assert not set(centers.league_rating_centers()) & set(FIELDER_KEYS)  # cached
    centers.clear_rating_center_cache()
    assert not centers._NOT_READ
    assert set(FIELDER_KEYS) <= set(centers.league_rating_centers())


# --- a legacy season ----------------------------------------------------------------


def test_a_legacy_season_s_file_keeps_its_bytes(league, monkeypatch):
    """The league at deploy: its season is under way on the file 7.50.3
    wrote. Nothing is added, nothing rewritten, nothing delivered."""
    write_schedule(league, 2027, played=3)
    before = _write_entry(league, centres_as_7_50_3(league))
    stamp = _path(league).stat().st_mtime_ns
    tuning = game_tuning(monkeypatch, "2027-04-04")
    assert "swing_model" not in tuning
    assert not set(tuning) & set(FIELDER_KEYS)
    for store in (True, False):
        assert not set(centers.league_rating_centers(store=store)) & set(FIELDER_KEYS)
    centers.clear_rating_center_cache()
    game_tuning(monkeypatch, "2027-04-05")
    assert _path(league).read_bytes() == before
    assert _path(league).stat().st_mtime_ns == stamp
    assert stored_generation(league, 2027) is None and witness(league) is None
    require_fielder_centers(load_tuning(tuning))


def test_a_new_season_held_on_the_legacy_engine_stores_none(league, monkeypatch):
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, "4")
    write_schedule(league, 2027)
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    assert "swing_model" not in tuning and not set(tuning) & set(FIELDER_KEYS)
    entry = _entry(league)
    assert centers.ENGINE_GENERATION_KEY not in entry
    assert not set(entry) & set(FIELDER_KEYS)
    assert set(entry) <= set(centers.RATING_CENTER_KEYS)


def test_a_league_with_no_schedule_is_given_none(league):
    """An offseason, or a league being created: generation 5 is what its
    next season gets, so no fielder centre is worked out."""
    assert not set(centers.league_rating_centers()) & set(FIELDER_KEYS)
    assert not set(centers.league_rating_centers(store=False)) & set(FIELDER_KEYS)
    assert not _path(league).exists()


# --- a generation 6 season ----------------------------------------------------------


def test_a_season_started_on_generation_6_stores_and_delivers_them(
    league, monkeypatch
):
    _promote_generation_6(monkeypatch)
    write_schedule(league, 2027)
    expected = centers.fielder_rating_centers(league)
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    assert stored_generation(league, 2027) == 6 and witness(league) == ("2027", 6)
    assert {key: tuning[key] for key in FIELDER_KEYS} == expected
    entry = _entry(league)
    assert {key: entry[key] for key in FIELDER_KEYS} == expected
    assert entry[centers.CENTERS_VERSION_KEY] == centers.CENTERS_VERSION
    assert set(entry) == set(centers.RATING_CENTER_KEYS) | set(FIELDER_KEYS) | {
        centers.ENGINE_GENERATION_KEY, centers.CENTERS_VERSION_KEY
    }
    # The engine is told they were delivered, so a game with the fielding
    # switch on starts -- and does not without them.
    played = load_tuning({**tuning, "fielder_centred_ratings": 1.0})
    require_rating_centers(played)
    require_fielder_centers(played)
    short = {k: v for k, v in tuning.items() if k != "fielder_arm_center_cf"}
    with pytest.raises(RatingCenterMissing, match="fielder_arm_center_cf"):
        require_fielder_centers(load_tuning({**short, "fielder_centred_ratings": 1.0}))


def test_they_are_frozen_for_the_season(league, monkeypatch):
    """Fixed with the entry: a lineup move or a roster move later in the
    season does not move the centres a game reads."""
    _promote_generation_6(monkeypatch)
    write_schedule(league, 2027)
    first = centers.league_rating_centers()
    before = _path(league).read_bytes()
    # Every hitter's glove improves by ten and every lineup file is gone.
    players = league / "players.csv"
    with players.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields, rows = list(reader.fieldnames or []), list(reader)
    for row in rows:
        row["fa"] = str(float(row["fa"] or 50) + 10)
    with players.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    for path in (league / "lineups").glob("*.csv"):
        path.unlink()
    live = centers.fielder_rating_centers(league)
    assert live["fielder_fa_center_ss"] != first["fielder_fa_center_ss"]
    centers.clear_rating_center_cache()
    again = centers.league_rating_centers()
    assert again == first
    assert _path(league).read_bytes() == before


def test_a_generation_6_entry_that_lacks_them_gains_them(league):
    """Recorded on generation 6 with the other centres already in the
    entry: the fielder centres are added beside them and nothing else in
    the entry changes."""
    write_schedule(league, 2027, played=2)
    stored = centers.active_rating_centers(league)
    entry = {
        **stored, centers.ENGINE_GENERATION_KEY: 6,
        centers.CENTERS_VERSION_KEY: centers.CENTERS_VERSION,
    }
    _write_entry(league, entry)
    # A read that must fix nothing gets them and leaves the file alone.
    before = _path(league).read_bytes()
    peek = centers.league_rating_centers(store=False)
    assert {key: peek[key] for key in FIELDER_KEYS} == centers.fielder_rating_centers(
        league
    )
    assert _path(league).read_bytes() == before
    got = centers.league_rating_centers()
    assert {key: got[key] for key in FIELDER_KEYS} == centers.fielder_rating_centers(
        league
    )
    after = _entry(league)
    assert {key: after[key] for key in FIELDER_KEYS} == {
        key: got[key] for key in FIELDER_KEYS
    }
    assert {key: after[key] for key in entry} == entry
    assert witness(league) == ("2027", 6)
    # And then they are read back, not worked out again.
    stamp = _path(league).read_bytes()
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers() == got
    assert _path(league).read_bytes() == stamp


def test_the_witness_alone_says_generation_6(league):
    """The entry lost its generation (a stale copy of the file) but the
    season's other record has it: the higher generation is played, so its
    centres are read."""
    write_schedule(league, 2027, played=2)
    progress = json.loads((league / "season_progress.json").read_text())
    progress["engine_generation"] = {"season": "2027", "generation": 6}
    (league / "season_progress.json").write_text(json.dumps(progress))
    _write_entry(league, dict(centers.active_rating_centers(league)))
    got = centers.league_rating_centers()
    assert set(FIELDER_KEYS) <= set(got)
    assert stored_generation(league, 2027) == 6
    assert set(FIELDER_KEYS) <= set(_entry(league))


def test_live_games_on_generation_6_play_with_the_fielding_switches(
    tmp_path, monkeypatch
):
    """Six dated games through the product's own game path
    (``playbalance.game_runner``: the rotation tracker, the saved lineups,
    the rest state) in a league whose season starts on generation 6 with
    the fielding values laid over its profile. The engine refuses a game
    whose fielder centres were not delivered, so that the games are played
    at all is the live path supplying them."""
    from tests import test_r5_live_path as live
    from tests.test_r5_centred_entries import _live_league, _play_live

    profile = json.loads(generations.engine_profile_path(6).read_text("utf-8"))
    fielding = json.loads(
        (REPO / "scripts" / "kpi_profiles" / "r6_fielding.json").read_text("utf-8")
    )
    merged = tmp_path / "engine_6_fielding.json"
    merged.write_text(json.dumps({**profile, **fielding}), encoding="utf-8")
    real_path = generations.engine_profile_path
    monkeypatch.setattr(
        generations, "engine_profile_path",
        lambda generation: merged if int(generation) == 6 else real_path(generation),
    )
    _promote_generation_6(monkeypatch)

    data = _live_league(tmp_path / "league")
    games = _play_live(tmp_path / "league", data)
    assert len(games) == len(live.GAMES)
    entry = _entry(data, 2026)
    assert entry[centers.ENGINE_GENERATION_KEY] == 6
    assert set(FIELDER_KEYS) <= set(entry)
    sources = set()
    for game in games:
        tuning = game["tuning"]
        for switch in ("fielder_centred_ratings", "position_fit_model",
                       "spray_direction_model", "infield_band_model", "range_model"):
            assert tuning[switch] == 1, switch
        assert tuning["error_model"] == 2
        # Fixed on Opening Day: every game of the season reads the entry.
        assert {k: tuning[k] for k in FIELDER_KEYS} == {k: entry[k] for k in FIELDER_KEYS}
        require_fielder_centers(load_tuning(tuning))
        assert "fielding_chance_log" not in tuning  # the harness's, not a league's
        played = game["played"]
        assert played["totals"]["pa"] > 50
        for row in played["pitch_log"]:
            if row.get("error_on"):
                value = row["error_on"]
                sources.update(value if isinstance(value, list) else [value])
    # Whatever errors the six games had are of the kinds the engine knows
    # (the out type of a batted ball, or one of the throws and misplays).
    assert sources <= {
        "groundout", "flyout", "lineout", "advance", "tag_up", "steal", "of_hit",
        "relay", "pickoff",
    }


def test_generation_6_in_another_season_does_not_reach_this_one(league):
    """Only the season's own generation counts: a generation 5 season in a
    file that also holds a generation 6 season is given none."""
    write_schedule(league, 2027, played=2)
    stored = centers.active_rating_centers(league)
    payload = {
        "version": 1,
        "seasons": {
            "2026": {**stored, centers.ENGINE_GENERATION_KEY: 6,
                     **{key: 55.0 for key in FIELDER_KEYS}},
            "2027": {**stored, centers.ENGINE_GENERATION_KEY: 5,
                     centers.CENTERS_VERSION_KEY: centers.CENTERS_VERSION},
        },
    }
    _path(league).write_text(json.dumps(payload, indent=2, sort_keys=True))
    progress = json.loads((league / "season_progress.json").read_text())
    progress["engine_generation"] = {"season": "2027", "generation": 5}
    (league / "season_progress.json").write_text(json.dumps(progress))
    before = _path(league).read_bytes()
    assert not set(centers.league_rating_centers()) & set(FIELDER_KEYS)
    assert _path(league).read_bytes() == before
    # The generation 6 season's own are read from its entry.
    last = centers.league_rating_centers(season=2026)
    assert {last[key] for key in FIELDER_KEYS} == {55.0}
