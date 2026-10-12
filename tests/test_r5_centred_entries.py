"""Release 5 (``centred_ratings``): a season is never played half-shifted.

A generation 5 season reads seven league centres (hitter Contact, Eye and
Power over the lineup regulars; pitcher control, movement, pitch grade and
arm weighted by workload). An entry in ``rating_centers.json`` that holds
only some of them, or holds them on an older definition, used to be left
alone for the whole season: hitters shifted by every-ACT-hitter means,
pitchers not shifted at all, the models comparing both against 50 (league
fixture, one season: 3.79 runs a game and 25.6% strikeouts against 4.56
and 23.2%).

Three ways an entry gets into that state, each tested here against the
file 7.50.3 REALLY writes (``tests.r5_flip_support.centres_as_7_50_3``):

1. it was created by an earlier build of this release;
2. deploy overlap: this build records the season's generation, then a
   stale 7.50.3 instance plays a game and merges its own centres into the
   entry (keeping the generation);
3. no ACT pitcher resolved when it was created, so the pitcher centres
   came later.

The entry now says which definition its Release 5 centres have
(``centers_version``); a generation 5 entry that does not is recomputed
and reported, even mid-season. A legacy season's entry is never touched.

Also here: a game with no date fixes no centres, and the live game path
(``playbalance.game_runner``) on generation 5 is invariant to a
league-wide shift of the ratings.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import tests.test_r5_live_path as live
from physics_sim.centred_ratings import (
    CENTRED_RATING_KEYS,
    RatingCenterMissing,
    require_rating_centers,
)
from physics_sim.config import load_tuning
from physics_sim.engine_generation import (
    CURRENT_ENGINE_GENERATION,
    LEGACY_ENGINE_GENERATION,
)
from physics_sim.models import PITCH_KEYS
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    KEYS_7_50_3,
    NEW_SEASON_ENGINE_ENV,
    centres_as_7_50_3,
    game_tuning,
    league,
    stored_generation,
    write_schedule,
)
from utils.roster_rules import counts_as_pitcher

REPO = Path(__file__).resolve().parents[1]
RELATIVE = set(centers.RELATIVE_CENTER_KEYS)
MARKER = centers.CENTERS_VERSION_KEY
OPENING_DAY = "2027-04-01"
SHOUT = "[engine-generation]"


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
    """Write a season entry the way every build has (sorted, indent 2)."""
    payload = {"version": 1, "seasons": {str(season): entry}}
    _path(data).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _path(data).read_bytes()


def _assert_whole(data: Path, tuning: dict) -> None:
    """The game got every Release 5 centre, on the current definition, and
    the entry says so."""
    now = centers.active_rating_centers(data)
    assert RELATIVE == CENTRED_RATING_KEYS
    assert {key: tuning[key] for key in RELATIVE} == {key: now[key] for key in RELATIVE}
    require_rating_centers(load_tuning(tuning))
    entry = _entry(data)
    assert entry[MARKER] == centers.CENTERS_VERSION == 2
    assert entry["engine_generation"] == CURRENT_ENGINE_GENERATION
    assert {key: entry[key] for key in RELATIVE} == {key: now[key] for key in RELATIVE}


# --- the three ways in -----------------------------------------------------------


def test_the_7_50_3_entry_is_the_literal_one():
    # What the deployed code writes on the calibration fixture: sixteen
    # keys, Contact and Eye over every ACT hitter (the regulars': 50.28,
    # 50.33), no Power centre, no usage centre, no generation, no marker.
    old = centres_as_7_50_3(REPO / "data" / "calibration")
    assert tuple(old) == KEYS_7_50_3 and len(old) == 16
    assert (old["hitter_contact_center"], old["hitter_eye_center"]) == (48.81, 48.41)
    assert not set(old) & (
        {"hitter_power_center", "engine_generation", MARKER}
        | set(centers.PITCHER_USAGE_CENTER_KEYS)
    )
    now = centers.active_rating_centers(REPO / "data" / "calibration")
    assert {k: now[k] for k in KEYS_7_50_3 if k not in RELATIVE} == {
        k: v for k, v in old.items() if k not in RELATIVE
    }


def test_a_new_generation_5_entry_is_marked_and_whole(league, monkeypatch, capsys):
    write_schedule(league, 2027)
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    _assert_whole(league, tuning)
    # The ordinary path reports nothing: the generation is recorded first
    # (an entry with no centres yet), then the centres are added.
    assert SHOUT not in capsys.readouterr().out
    before = _path(league).read_bytes()
    centers.clear_rating_center_cache()
    assert game_tuning(monkeypatch, "2027-04-02") == tuning
    assert _path(league).read_bytes() == before
    assert SHOUT not in capsys.readouterr().out


@pytest.mark.parametrize("played", [0, 3], ids=["opening day", "mid-season"])
def test_an_entry_from_an_earlier_build_of_this_release_is_recomputed(
    league, monkeypatch, capsys, played
):
    """Way 1. The first build of this release wrote the regulars' Contact
    and Eye and a Power centre, and no usage centres: the pitchers would
    read unshifted against 50 for the whole season. Recomputed even when
    the season has started -- its centres move once, which is better than
    playing it half-shifted to the end."""
    write_schedule(league, 2027, played=played)
    now = centers.active_rating_centers(league)
    earlier = {key: now[key] for key in KEYS_7_50_3}
    earlier.update(
        # Values today's rosters would not reproduce, so a recompute shows.
        hitter_contact_center=47.0, hitter_eye_center=46.0, hitter_power_center=45.0,
        engine_generation=CURRENT_ENGINE_GENERATION,
    )
    _write_entry(league, earlier)
    tuning = game_tuning(monkeypatch, "2027-04-04")
    _assert_whole(league, tuning)
    assert tuning["hitter_contact_center"] == now["hitter_contact_center"] != 47.0
    # Everything else in the entry is as it was.
    entry = _entry(league)
    assert {k: entry[k] for k in KEYS_7_50_3 if k not in RELATIVE} == {
        k: earlier[k] for k in KEYS_7_50_3 if k not in RELATIVE
    }
    out = capsys.readouterr().out
    assert out.count(SHOUT) == 1 and "not fixed by this build" in out
    # Once: the entry is marked, and the next game reads it as stored.
    before = _path(league).read_bytes()
    centers.clear_rating_center_cache()
    assert game_tuning(monkeypatch, "2027-04-05") == tuning
    assert _path(league).read_bytes() == before
    assert SHOUT not in capsys.readouterr().out


def test_deploy_overlap_with_a_stale_7_50_3_instance_is_recomputed(
    league, monkeypatch, capsys
):
    """Way 2. This build records the season's generation; a 7.50.3 instance
    still running then plays a game and writes ``{**entry, **computed}``:
    its own sixteen centres over an entry that keeps the generation."""
    write_schedule(league, 2027)
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    recorded = _entry(league)
    assert recorded == {"engine_generation": CURRENT_ENGINE_GENERATION}
    merged = {**recorded, **centres_as_7_50_3(league)}  # what 7.50.3 does
    _write_entry(league, merged)
    assert merged["hitter_contact_center"] == 48.81

    # The half-shifted game this used to be: hitters on every-ACT-hitter
    # means, no usage centre delivered at all.
    assert not set(centers.PITCHER_USAGE_CENTER_KEYS) & set(merged)

    centers.clear_rating_center_cache()
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    _assert_whole(league, tuning)
    assert tuning["hitter_contact_center"] == 50.28
    assert capsys.readouterr().out.count(SHOUT) == 1
    # The plain centres 7.50.3 wrote are the same definitions: kept.
    entry = _entry(league)
    assert {k: entry[k] for k in KEYS_7_50_3 if k not in RELATIVE} == {
        k: merged[k] for k in KEYS_7_50_3 if k not in RELATIVE
    }


def test_centres_that_could_not_be_computed_at_first_are_added(
    league, monkeypatch, capsys
):
    """Way 3. No ACT pitcher resolved when the entry was created (their
    rows were missing from players.csv). The plain pitcher centres were
    added when they turned up; the usage centres never were."""
    write_schedule(league, 2027)
    players = league / "players.csv"
    whole = players.read_text(encoding="utf-8")
    with players.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        hitters = [row for row in reader if not counts_as_pitcher(row)]
    with players.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(hitters)

    first = centers.get_rating_center_overrides()
    assert first["hitter_contact_center"] == 50.28
    assert not [key for key in first if key.startswith("pitcher_")]
    assert _entry(league)[MARKER] == 2
    # A game cannot be played on it: the pitchers' centres are not there.
    with pytest.raises(RatingCenterMissing, match="pitcher_arm_usage_center"):
        require_rating_centers(load_tuning(game_tuning(monkeypatch, OPENING_DAY)))
    assert SHOUT not in capsys.readouterr().out

    players.write_text(whole, encoding="utf-8")
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    _assert_whole(league, tuning)
    # The hitter centres fixed at first are not recomputed.
    assert {k: tuning[k] for k in first} == first
    out = capsys.readouterr().out
    assert out.count(SHOUT) == 1 and "incomplete" in out


def test_a_read_only_caller_gets_the_repaired_centres_and_writes_nothing(
    league, capsys
):
    write_schedule(league, 2027)
    stale = {**centres_as_7_50_3(league), "engine_generation": 5}
    before = _write_entry(league, stale)
    now = centers.active_rating_centers(league)
    for _ in range(2):  # a page load, a watched game: nothing is cached
        found = centers.get_rating_center_overrides(store=False)
        assert {key: found[key] for key in RELATIVE} == {
            key: now[key] for key in RELATIVE
        }
        assert _path(league).read_bytes() == before
    assert capsys.readouterr().out.count(SHOUT) == 1  # once per process
    # A request for a centre that is not one of the seven repairs nothing.
    centers.clear_rating_center_cache()
    assert centers.league_hitter_speed_center() == stale["hitter_speed_center"]
    assert _path(league).read_bytes() == before


# --- a legacy season is left exactly as it is ---------------------------------------


def test_a_legacy_season_s_7_50_3_entry_keeps_its_bytes(league, monkeypatch, capsys):
    write_schedule(league, 2026, played=3)
    old = centres_as_7_50_3(league)
    before = _write_entry(league, old, season=2026)
    for date in (None, "2026-04-04", "2026-04-05"):
        tuning = game_tuning(monkeypatch, date)
        assert {key: tuning[key] for key in KEYS_7_50_3} == old
        assert not (RELATIVE - set(KEYS_7_50_3)) & set(tuning)
        assert tuning.get("centred_ratings") is None
        centers.clear_rating_center_cache()
    assert _path(league).read_bytes() == before
    assert stored_generation(league, 2026) is None
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    assert SHOUT not in capsys.readouterr().out
    # The legacy engine asks for no centre it was not given.
    require_rating_centers(load_tuning(tuning))


def test_a_new_legacy_season_s_entry_carries_no_marker(league, monkeypatch):
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY_ENGINE_GENERATION))
    write_schedule(league, 2027)
    game_tuning(monkeypatch, OPENING_DAY)
    entry = _entry(league)
    assert MARKER not in entry and "engine_generation" not in entry
    assert entry == centers.active_rating_centers(league)


# --- a game with no date fixes no centres -------------------------------------------


def test_an_exhibition_does_not_fix_the_seasons_centres(league, monkeypatch):
    """An admin exhibition in the preseason, before the clubs' lineups are
    saved, used to pin the whole season's hitter centres to that day's
    nine-best stand-ins."""
    write_schedule(league, 2027)
    saved = league / "lineups"
    shutil.move(str(saved), str(league / "lineups.later"))
    exhibition = game_tuning(monkeypatch)  # no date
    assert exhibition["centred_ratings"] == 1
    require_rating_centers(load_tuning(exhibition))
    # The season's generation is on record; none of its centres is.
    entry = _entry(league)
    assert entry == {"engine_generation": CURRENT_ENGINE_GENERATION}
    shutil.move(str(league / "lineups.later"), str(saved))

    opening = game_tuning(monkeypatch, OPENING_DAY)
    # The regulars in the saved lineups, not the stand-ins.
    assert opening["hitter_contact_center"] == 50.28
    assert exhibition["hitter_contact_center"] != 50.28
    _assert_whole(league, opening)
    # An exhibition later in the season reads the stored centres.
    shutil.rmtree(saved)
    centers.clear_rating_center_cache()
    later = game_tuning(monkeypatch)
    assert {k: later[k] for k in RELATIVE} == {k: opening[k] for k in RELATIVE}


# --- the live game path, generation 5 -----------------------------------------------

HITTER_COLUMNS = ("ch", "ph", "eye")
PITCHER_COLUMNS = ("control", "movement", "arm") + tuple(PITCH_KEYS)
HITTER_CENTRES = (
    "hitter_contact_center", "hitter_power_center", "hitter_eye_center",
)
PITCHER_CENTRES = tuple(centers.PITCHER_USAGE_CENTER_KEYS) + (
    "pitcher_control_center", "pitcher_movement_center", "pitcher_arm_center",
    "pitcher_grade_center",
)


def _live_league(root: Path, *, hitters: float = 0.0, pitchers: float = 0.0) -> Path:
    """The live-path scratch league (the league fixture, saved lineups) with
    a constant added to every hitter's Contact, Power and Eye and to every
    pitcher's control, movement, arm and pitch grades, and a schedule for
    the season the games are in."""
    data = live.build_league(root, REPO, lineups=True)
    path = data / "players.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        if counts_as_pitcher(row):
            columns, delta = PITCHER_COLUMNS, pitchers
        else:
            columns, delta = HITTER_COLUMNS, hitters
        for column in columns:
            raw = (row.get(column) or "").strip()
            if delta and raw and float(raw) > 0.0:
                # The league's player loader reads whole numbers only.
                row[column] = str(int(float(raw) + delta))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    lines = ["date,home,away,result,played,boxscore"]
    lines += [f"{date},{home},{away},,," for date, home, away, _seed in live.GAMES]
    (data / "schedule.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def _play_live(root: Path, data: Path) -> list[dict]:
    """``live.GAMES`` through ``game_runner.simulate_game_scores`` on the
    engine the league's new season gets (generation 5)."""
    import physics_sim.engine as engine
    from playbalance import game_runner
    from utils import path_utils

    names = ("NEXGEN_DATA_ROOT", "NEXGEN_ACTIVE_LEAGUE", NEW_SEASON_ENGINE_ENV)
    saved_env = {name: os.environ.get(name) for name in names}
    os.environ["NEXGEN_DATA_ROOT"] = str(root)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
    os.environ.pop(NEW_SEASON_ENGINE_ENV, None)
    live._fresh_process_state()
    centers.clear_rating_center_cache()
    token = path_utils.set_request_league(live.LEAGUE)
    real_game = engine.simulate_game
    games: list[dict] = []

    def game(**kwargs):
        result = real_game(**kwargs)
        games.append(
            {
                "tuning": dict(kwargs["tuning_overrides"] or {}),
                "lineups": [
                    [p.player_id for p in kwargs[side]]
                    for side in ("away_lineup", "home_lineup")
                ],
                "played": {
                    "pitch_log": result.pitch_log,
                    "totals": result.totals,
                    "meta": result.metadata,
                },
            }
        )
        return result

    engine.simulate_game = game
    try:
        assert path_utils.get_data_dir().resolve() == data.resolve()
        for date, home, away, seed in live.GAMES:
            home_runs, away_runs, _html, _meta = game_runner.simulate_game_scores(
                home, away, seed=seed, game_date=date, engine="physics"
            )
            games[-1]["score"] = (home_runs, away_runs)
    finally:
        engine.simulate_game = real_game
        path_utils.reset_request_league(token)
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        live._fresh_process_state()
    return games


def _played_digest(game: dict) -> str:
    blob = json.dumps(
        live._canon({k: game[k] for k in ("lineups", "played", "score")}),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def test_live_generation_5_games_are_invariant_to_a_league_wide_shift(tmp_path):
    """Six dated games through the product's own game path, on the centres
    the league computes for itself (two decimals, not chosen to be exact):
    the rotation tracker, the saved lineups, the rest state, the stored
    season entry. Every hitter 6 points better and every pitcher 4 worse
    is the same six games, to the last bit."""
    if os.environ.get("PYTHONHASHSEED") != "0":
        pytest.skip("the live path is reproducible only under PYTHONHASHSEED=0")
    plain_data = _live_league(tmp_path / "plain")
    plain = _play_live(tmp_path / "plain", plain_data)
    assert len(plain) == len(live.GAMES)
    entry = _entry(plain_data, 2026)
    assert entry["engine_generation"] == CURRENT_ENGINE_GENERATION
    assert entry[MARKER] == centers.CENTERS_VERSION
    for game in plain:
        assert game["tuning"]["centred_ratings"] == 1
        require_rating_centers(load_tuning(game["tuning"]))
        # Fixed on Opening Day: every game of the season reads the entry.
        assert {k: game["tuning"][k] for k in RELATIVE} == {
            k: entry[k] for k in RELATIVE
        }
    want = [_played_digest(game) for game in plain]
    assert len(set(want)) == len(live.GAMES)

    for name, hitters, pitchers in (("hit", 6.0, 0.0), ("both", 6.0, -4.0)):
        data = _live_league(tmp_path / name, hitters=hitters, pitchers=pitchers)
        moved = _play_live(tmp_path / name, data)
        shifted = _entry(data, 2026)
        for key in HITTER_CENTRES:
            assert shifted[key] == pytest.approx(entry[key] + hitters, abs=0.006)
        for key in PITCHER_CENTRES:
            assert shifted[key] == pytest.approx(entry[key] + pitchers, abs=0.006)
        assert [game["score"] for game in moved] == [game["score"] for game in plain]
        assert [_played_digest(game) for game in moved] == want, name
