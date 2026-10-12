"""Release 5 switch-on: the review findings on the per-league mechanism.

The owner's rule is that a league never changes engine in the middle of a
season, in either direction. Each finding here was a way it could:

1. the season's generation lived in one file, and a lost, truncated or
   stale ``rating_centers.json`` (or a working-copy pull that failed for
   that one file) read as "legacy" and was then written back that way;
2. read-only paths converted the stored sliders on disk before the
   season's generation was fixed, and nothing converted them back;
3. an entry already stored for a season key always won;
4. any error while reading the generation was answered with "legacy";
5. the Tuning page promised a switch that the operations hold prevents, and
   the create-league wizard swallowed rule-preset errors.

Scratch leagues only (tests/r5_flip_support.py).
"""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest
from fastapi import HTTPException

import api.routers.tuning as T
import api.working_copy as wc
import services.physics_tuning_settings as S
from physics_sim.config import load_tuning
from physics_sim.engine_generation import (
    CURRENT_ENGINE_GENERATION,
    LEGACY_ENGINE_GENERATION,
)
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    ADMIN,
    CALIBRATION,
    LEAGUE,
    NEW_SEASON_ENGINE_ENV,
    centres_as_7_50_3,
    drop_witness,
    game_tuning,
    league,
    play_days,
    roll_over,
    stored_generation,
    witness,
    write_schedule,
)

NEW, LEGACY = CURRENT_ENGINE_GENERATION, LEGACY_ENGINE_GENERATION
LEGACY_SLIDERS = {"walk_scale": 1.0, "k_scale": 0.55}
OPENING_DAY = "2027-04-01"
MID_SEASON = "2027-04-04"


def _has_profile(tuning: dict) -> bool:
    return tuning.get("swing_model") == 1.0 and tuning.get("contact_model") == 1.0


def _centres_path(data):
    return data / centers.RATING_CENTERS_FILENAME


def _overrides_path(data):
    return data / S.TUNING_OVERRIDES_FILENAME


def _stored(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _knobs(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def _write_overrides(data, values=LEGACY_SLIDERS) -> str:
    """An overrides file as today's code stores it; returns its text."""
    payload = {**values, S.STEAL_FREQ_REBASE_MARKER: True}
    path = _overrides_path(data)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _legacy_centres_file(data, season) -> str:
    """``rating_centers.json`` as the code deployed today (7.50.3) leaves
    it: the season's sixteen centres, Contact and Eye over every ACT hitter,
    and no generation (``centres_as_7_50_3``). Returns its text."""
    seasons = {str(season): centres_as_7_50_3(data)}
    path = _centres_path(data)
    path.write_text(_centres_json(seasons), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _centres_json(seasons: dict) -> str:
    return json.dumps({"version": 1, "seasons": seasons}, indent=2, sort_keys=True)


def _season_on_5(data, monkeypatch, *, year=2027, days=3) -> None:
    """A season started on generation 5 with ``days`` days played."""
    write_schedule(data, year)
    assert _has_profile(game_tuning(monkeypatch, f"{year}-04-01"))
    play_days(data, days)
    assert stored_generation(data, year) == NEW
    assert witness(data) == (str(year), NEW)


def _new_process() -> None:
    """Forget what this process learned, as a new instance would."""
    from utils import file_cache

    centers.clear_rating_center_cache()
    file_cache.invalidate()


# --- 1: the generation is written down twice ------------------------------------


def test_a_generation_is_written_down_in_two_files(league, monkeypatch):
    _season_on_5(league, monkeypatch)
    progress = _stored(league / "season_progress.json")
    assert progress["engine_generation"] == {"season": "2027", "generation": NEW}
    # The rest of the file is what it was: one key was added.
    assert progress["sim_index"] == 3
    assert progress["preseason_done"] == {"schedule": True}
    assert centers.recorded_league_engine_generation() == NEW


def test_a_legacy_league_gets_no_witness_and_no_file_changes(league, monkeypatch):
    """Legacy is the absence of both records for a league that never
    switched: a game changes neither file."""
    write_schedule(league, 2026, played=3)
    centres_text = _legacy_centres_file(league, 2026)
    overrides_text = _write_overrides(league)
    progress_text = (league / "season_progress.json").read_text()
    for date in (None, "2026-04-04", "2026-04-04"):
        assert not _has_profile(game_tuning(monkeypatch, date))
    assert T.get_tuning(ADMIN)["engine"]["generation"] == LEGACY
    assert (league / "season_progress.json").read_text() == progress_text
    assert _centres_path(league).read_text() == centres_text
    assert _overrides_path(league).read_text() == overrides_text
    assert witness(league) is None
    assert centers.recorded_league_engine_generation() is None


@pytest.mark.parametrize("fault", ["deleted", "stale", "entry_without_generation"])
def test_a_lost_entry_does_not_put_the_season_on_the_legacy_engine(
    league, monkeypatch, fault, caplog
):
    """The file deleted mid-season, a stale copy holding only last season's
    entry, an entry rebuilt without its generation: each read as legacy, and
    the centres writer then stored the season's entry WITHOUT a generation."""
    write_schedule(league, 2026, played=6)
    last_season = _legacy_centres_file(league, 2026)
    roll_over(league, 2026)
    _season_on_5(league, monkeypatch)
    path = _centres_path(league)
    if fault == "deleted":
        path.unlink()
    elif fault == "stale":
        path.write_text(last_season, encoding="utf-8")
    else:
        payload = _stored(path)
        del payload["seasons"]["2027"]["engine_generation"]
        path.write_text(json.dumps(payload), encoding="utf-8")
    _new_process()

    # A page load reads the right engine and repairs nothing.
    before = path.read_text() if path.exists() else None
    assert centers.league_engine_generation(store=False) == NEW
    assert T.get_tuning(ADMIN)["engine"]["generation"] == NEW
    assert (path.read_text() if path.exists() else None) == before

    with caplog.at_level("ERROR", logger=centers.__name__):
        assert _has_profile(game_tuning(monkeypatch, MID_SEASON))
    assert "no engine generation in rating_centers.json" in caplog.text
    # The game wrote the entry back WITH its generation.
    assert stored_generation(league, 2027) == NEW
    assert witness(league) == ("2027", NEW)
    _new_process()
    assert _has_profile(game_tuning(monkeypatch, MID_SEASON))


@pytest.mark.parametrize("content", ["", "{ not json", "[]"])
def test_an_unreadable_file_is_neither_believed_nor_overwritten(
    league, monkeypatch, content, caplog
):
    """A 0-byte or broken file on a fresh process read as legacy, and the
    centres writer (unlike the generation reader) replaced it."""
    _season_on_5(league, monkeypatch)
    path = _centres_path(league)
    path.write_text(content, encoding="utf-8")
    _new_process()
    with caplog.at_level("ERROR", logger=centers.__name__):
        for _ in range(2):
            tuning = game_tuning(monkeypatch, MID_SEASON)
            assert _has_profile(tuning)
            # The centres are worked out for the game, and not stored.
            assert tuning["hitter_speed_center"] == (
                centers.active_rating_centers(league)["hitter_speed_center"]
            )
    assert path.read_text(encoding="utf-8") == content
    assert "cannot be read" in caplog.text
    assert centers.league_engine_generation(store=False) == NEW
    # Deleting the broken file lets the season's entry be rebuilt, on 5.
    path.unlink()
    assert _has_profile(game_tuning(monkeypatch, MID_SEASON))
    assert stored_generation(league, 2027) == NEW


def test_an_unreadable_file_is_left_alone_for_a_legacy_league_too(league, monkeypatch):
    write_schedule(league, 2026, played=3)
    path = _centres_path(league)
    path.write_text("", encoding="utf-8")
    assert not _has_profile(game_tuning(monkeypatch, "2026-04-04"))
    assert path.read_text(encoding="utf-8") == ""
    assert witness(league) is None


def test_the_witness_survives_every_rewrite_of_the_same_season(league, monkeypatch):
    from api.routers import admin_league

    _season_on_5(league, monkeypatch)
    asyncio.run(admin_league.regenerate_schedule({"template_id": "mlb_162"}, ADMIN))
    assert witness(league) == ("2027", NEW)
    admin_league.reset_results(ADMIN)
    assert witness(league) == ("2027", NEW)
    # Reset to Opening Day rebuilds season_progress.json from nothing.
    admin_league.reset_to_opening_day({}, ADMIN)
    progress = _stored(league / "season_progress.json")
    assert progress["sim_index"] == 0 and progress["playoffs_done"] is False
    assert witness(league) == ("2027", NEW)
    # So the season is still on 5 if the other record is lost after it,
    # even with new seasons held on the legacy engine -- whatever year the
    # regenerated schedule carries.
    year = (league / "schedule.csv").read_text().splitlines()[1][:4]
    _centres_path(league).unlink()
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    _new_process()
    assert _has_profile(game_tuning(monkeypatch, f"{year}-04-01"))
    assert stored_generation(league, year) == NEW
    assert witness(league) == (year, NEW)


def test_the_witness_does_not_carry_into_the_next_season(league, monkeypatch):
    _season_on_5(league, monkeypatch, days=6)
    roll_over(league, 2027)
    # The rollover rebuilt the file: the finished season's witness is gone.
    assert "engine_generation" not in _stored(league / "season_progress.json")
    assert witness(league) is None
    # So the next season is given its own generation: legacy, under the hold.
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    write_schedule(league, 2028)
    assert not _has_profile(game_tuning(monkeypatch, "2028-04-01"))
    # The file records generations now, so the legacy season is written out
    # in both places and can not inherit last season's 5 ...
    assert stored_generation(league, 2028) == LEGACY
    assert witness(league) == ("2028", LEGACY)
    play_days(league, 3)
    # ... not even from a stale file whose newest season is that 5.
    payload = _stored(_centres_path(league))
    del payload["seasons"]["2028"]
    _centres_path(league).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.delenv(NEW_SEASON_ENGINE_ENV)
    _new_process()
    assert not _has_profile(game_tuning(monkeypatch, "2028-04-04"))
    assert stored_generation(league, 2028) == LEGACY


def test_the_higher_generation_wins_when_the_records_disagree(
    league, monkeypatch, caplog
):
    """Not a silent guess: the higher one is played, the fault is logged and
    both records are put right."""
    _season_on_5(league, monkeypatch)
    payload = _stored(_centres_path(league))
    centres = {
        k: v for k, v in payload["seasons"]["2027"].items() if k != "engine_generation"
    }
    payload["seasons"]["2027"]["engine_generation"] = LEGACY
    _centres_path(league).write_text(json.dumps(payload), encoding="utf-8")
    _new_process()
    with caplog.at_level("ERROR", logger=centers.__name__):
        assert _has_profile(game_tuning(monkeypatch, MID_SEASON))
    assert "two engine generations on record" in caplog.text
    assert stored_generation(league, 2027) == NEW
    # The repair kept the season's stored centres.
    repaired = _stored(_centres_path(league))["seasons"]["2027"]
    assert {k: v for k, v in repaired.items() if k != "engine_generation"} == centres

    # The other way round: the witness is the lower one.
    progress = _stored(league / "season_progress.json")
    progress["engine_generation"]["generation"] = LEGACY
    (league / "season_progress.json").write_text(json.dumps(progress))
    _new_process()
    assert _has_profile(game_tuning(monkeypatch, MID_SEASON))
    assert witness(league) == ("2027", NEW)


def test_converted_sliders_are_the_last_evidence_of_a_generation_5_season(
    league, monkeypatch, caplog
):
    """Both records lost. The overrides file was converted by a season game
    of a generation 5 season, and says so."""
    _write_overrides(league)
    _season_on_5(league, monkeypatch)
    assert _stored(_overrides_path(league))[S.SWING_SLIDER_REBASE_MARKER] is True
    _centres_path(league).unlink()
    drop_witness(league)
    _new_process()
    with caplog.at_level("ERROR", logger=centers.__name__):
        assert _has_profile(game_tuning(monkeypatch, MID_SEASON))
    assert "no engine generation on record" in caplog.text
    assert stored_generation(league, 2027) == NEW
    assert witness(league) == ("2027", NEW)


def test_a_missing_schedule_does_not_lose_the_season_s_engine(league, monkeypatch):
    _season_on_5(league, monkeypatch)
    (league / "schedule.csv").unlink()
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    _new_process()
    assert centers.league_engine_generation(store=False) == NEW


def test_the_season_progress_file_is_never_rebuilt_around_the_witness(
    league, monkeypatch
):
    """An unparseable season_progress.json holds the schedule cursor: the
    witness is not written into a file that would be replaced by it."""
    write_schedule(league, 2027)
    (league / "season_progress.json").write_text("{ not json", encoding="utf-8")
    assert _has_profile(game_tuning(monkeypatch, OPENING_DAY))
    assert (league / "season_progress.json").read_text(encoding="utf-8") == "{ not json"
    assert stored_generation(league, 2027) == NEW


# --- 1: the working copy -----------------------------------------------------------


def _sync(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote", tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    monkeypatch.setenv("NEXGEN_WORKING_COPY", "1")
    monkeypatch.setenv("NEXGEN_SYNC_REMOTE", str(remote))
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(local))
    monkeypatch.setattr(wc, "_synced", {})
    monkeypatch.setattr(wc, "_busy", {})
    monkeypatch.setattr(wc, "_pull_failed", set())
    return remote, local


REL = "leagues/alpha/data/rating_centers.json"
GOOD = {"2026": {"hitter_speed_center": 50.1},
        "2027": {"engine_generation": 5, "hitter_speed_center": 51.2}}


@pytest.mark.parametrize(
    "local_text",
    [
        _centres_json({"2026": GOOD["2026"], "2027": {"hitter_speed_center": 49.9}}),
        _centres_json({"2027": {"engine_generation": 4, "hitter_speed_center": 49.9}}),
        "",  # truncated
        "{ not json",
    ],
    ids=["no_generation", "lower_generation", "empty", "broken"],
)
def test_a_copy_that_lost_the_generation_never_replaces_one_that_has_it(
    tmp_path, monkeypatch, local_text
):
    remote, local = _sync(tmp_path, monkeypatch)
    (remote / REL).parent.mkdir(parents=True)
    (remote / REL).write_text(_centres_json(GOOD), encoding="utf-8")
    wc.bulk_pull()
    (local / REL).write_text(local_text, encoding="utf-8")
    wc.push_changes()
    assert (remote / REL).read_text(encoding="utf-8") == _centres_json(GOOD)
    # Once the local copy has the generation again it is pushed as usual.
    fixed = {**GOOD, "2027": {**GOOD["2027"], "pitcher_arm_center": 52.0}}
    (local / REL).write_text(_centres_json(fixed), encoding="utf-8")
    wc.push_changes()
    assert (remote / REL).read_text(encoding="utf-8") == _centres_json(fixed)


def test_ordinary_updates_of_the_file_are_pushed(tmp_path, monkeypatch):
    remote, local = _sync(tmp_path, monkeypatch)
    (remote / REL).parent.mkdir(parents=True)
    legacy = {"2026": {"hitter_speed_center": 50.1}}
    (remote / REL).write_text(_centres_json(legacy), encoding="utf-8")
    wc.bulk_pull()
    steps = [
        # A legacy league gains a centre: no generation anywhere.
        {"2026": {"hitter_speed_center": 50.1, "pitcher_arm_center": 51.0}},
        # Its next season starts on generation 5.
        {**legacy, "2027": {"engine_generation": 5}},
        {**legacy, "2027": {"engine_generation": 5, "hitter_speed_center": 51.2}},
        # Seasons later the oldest entries have been trimmed from the file.
        {str(year): {"engine_generation": 5} for year in range(2028, 2033)},
        # The league is restored from a backup taken before those seasons.
        legacy,
    ]
    for seasons in steps:
        (local / REL).write_text(_centres_json(seasons), encoding="utf-8")
        wc.push_changes()
        assert (remote / REL).read_text(encoding="utf-8") == _centres_json(seasons)


def test_the_guard_holds_in_the_pull_direction_too(tmp_path, monkeypatch):
    remote, local = _sync(tmp_path, monkeypatch)
    (remote / REL).parent.mkdir(parents=True)
    (remote / REL).write_text(
        _centres_json({"2027": {"hitter_speed_center": 49.9}}), encoding="utf-8"
    )
    (local / REL).parent.mkdir(parents=True)
    (local / REL).write_text(_centres_json(GOOD), encoding="utf-8")
    wc.bulk_pull()
    assert (local / REL).read_text(encoding="utf-8") == _centres_json(GOOD)


def _fail_copies_of(monkeypatch, name, source_root):
    """Make every copy of ``name`` out of ``source_root`` fail."""
    real = shutil.copy2

    def flaky(src, dst, *args, **kwargs):
        from pathlib import Path

        if Path(src).name == name and Path(src).is_relative_to(source_root):
            raise OSError("FUSE hiccup")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", flaky)
    return real


def test_a_failed_pull_is_never_followed_by_a_push_of_a_rebuilt_file(
    tmp_path, monkeypatch
):
    remote, local = _sync(tmp_path, monkeypatch)
    (remote / REL).parent.mkdir(parents=True)
    (remote / REL).write_text(_centres_json(GOOD), encoding="utf-8")
    (remote / "leagues/alpha/data/teams.csv").write_text("teams", encoding="utf-8")
    real = _fail_copies_of(monkeypatch, "rating_centers.json", remote)
    wc.bulk_pull()
    assert not (local / REL).exists()
    assert wc._pull_failed == {REL}

    # The app rebuilds the file from today's rosters -- with the generation
    # (it has a second record of it) and other centres.
    rebuilt = _centres_json(
        {"2027": {"engine_generation": 5, "hitter_speed_center": 47.0}}
    )
    (local / REL).write_text(rebuilt, encoding="utf-8")
    # While the remote copy still can not be read, nothing is pushed.
    wc.push_changes()
    assert (remote / REL).read_text(encoding="utf-8") == _centres_json(GOOD)
    assert (local / REL).read_text(encoding="utf-8") == rebuilt
    assert wc._pull_failed == {REL}

    # When it can, the pull is retried and the REMOTE copy replaces the
    # rebuilt one, rather than the other way round.
    monkeypatch.setattr(shutil, "copy2", real)
    wc.push_changes()
    assert (remote / REL).read_text(encoding="utf-8") == _centres_json(GOOD)
    assert (local / REL).read_text(encoding="utf-8") == _centres_json(GOOD)
    assert wc._pull_failed == set()
    # From here on the file syncs like any other.
    newer = {**GOOD, "2027": {**GOOD["2027"], "pitcher_arm_center": 52.0}}
    (local / REL).write_text(_centres_json(newer), encoding="utf-8")
    wc.push_changes()
    assert (remote / REL).read_text(encoding="utf-8") == _centres_json(newer)


def test_a_pull_that_fails_once_is_retried_at_startup(tmp_path, monkeypatch):
    remote, local = _sync(tmp_path, monkeypatch)
    (remote / REL).parent.mkdir(parents=True)
    (remote / REL).write_text(_centres_json(GOOD), encoding="utf-8")
    real = shutil.copy2
    failures = []

    def fails_once(src, dst, *args, **kwargs):
        if str(src).endswith("rating_centers.json") and not failures:
            failures.append(src)
            raise OSError("FUSE hiccup")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", fails_once)
    wc.bulk_pull()
    assert failures and wc._pull_failed == set()
    assert (local / REL).read_text(encoding="utf-8") == _centres_json(GOOD)


def test_a_new_instance_whose_pull_fails_plays_on_and_keeps_the_remote_file(
    league, monkeypatch, tmp_path
):
    """The reviewer's sequence with the real working copy: a new instance
    pulls every file but rating_centers.json, plays a game and pushes."""
    from utils import path_utils

    _season_on_5(league, monkeypatch)
    # Make the season's stored centre one today's rosters would not give.
    stored = _stored(_centres_path(league))
    stored["seasons"]["2027"]["hitter_speed_center"] = 12.34
    _centres_path(league).write_text(_centres_json(stored["seasons"]), encoding="utf-8")
    remote, local = tmp_path / "bucket", tmp_path / "instance2"
    shutil.copytree(tmp_path / "root", remote)
    remote_file = remote / "leagues" / LEAGUE / "data" / centers.RATING_CENTERS_FILENAME
    remote_text = remote_file.read_text(encoding="utf-8")

    monkeypatch.setenv("NEXGEN_WORKING_COPY", "1")
    monkeypatch.setenv("NEXGEN_SYNC_REMOTE", str(remote))
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(local))
    monkeypatch.setattr(wc, "_synced", {})
    monkeypatch.setattr(wc, "_pull_failed", set())
    real = _fail_copies_of(monkeypatch, centers.RATING_CENTERS_FILENAME, remote)
    wc.bulk_pull()
    monkeypatch.setattr(shutil, "copy2", real)
    path_utils._DATA_DIR_CACHE.clear()
    path_utils.set_request_league(LEAGUE)
    _new_process()
    data = path_utils.get_data_dir()
    assert data.resolve() == (local / "leagues" / LEAGUE / "data").resolve()
    assert not _centres_path(data).exists()

    # The game is played on the season's engine, from the witness.
    assert _has_profile(game_tuning(monkeypatch, MID_SEASON))
    assert stored_generation(data, 2027) == NEW
    wc.push_changes(LEAGUE)
    # The remote file is what it was -- generation and centres -- and the
    # instance now reads the season's stored centre again.
    assert remote_file.read_text(encoding="utf-8") == remote_text
    assert _centres_path(data).read_text(encoding="utf-8") == remote_text
    assert game_tuning(monkeypatch, MID_SEASON)["hitter_speed_center"] == 12.34


# --- 2: sliders are converted on disk only once the season is fixed ------------------


def test_read_only_readers_convert_in_memory_only(league, monkeypatch):
    """The Tuning page, a watched game, an exhibition, the fatigue replay,
    the lineup auto-fill and the values helper, in a preseason that will be
    generation 5: every one reads converted sliders, none rewrites the file."""
    from api.ws import sim as ws_sim
    from services.league_tuning import league_tuning, league_tuning_overrides
    from utils.lineup_autofill import platoon_tuning

    write_schedule(league, 2027)
    before = _write_overrides(league)
    converted = S.convert_slider_overrides(LEGACY_SLIDERS)
    assert set(converted) == {"swing_walk_scale", "contact_strikeout_scale"}

    def unchanged():
        return _overrides_path(league).read_text(encoding="utf-8") == before

    view = T.get_tuning(ADMIN)
    assert view["engine"]["generation"] == NEW and view["overrides"] == converted
    assert unchanged()
    watched = ws_sim._league_tuning_overrides()
    assert {k: watched[k] for k in converted} == converted
    assert "walk_scale" not in watched
    assert unchanged()
    replay = league_tuning_overrides(store=False)
    assert {k: replay[k] for k in converted} == converted
    assert unchanged()
    walk = converted["swing_walk_scale"]
    assert league_tuning().get("swing_walk_scale") == walk
    assert platoon_tuning(league).get("swing_walk_scale") == walk
    assert S.load_physics_tuning_values(NEW)["swing_walk_scale"] == walk
    assert unchanged()
    # None of them fixed the season either.
    assert stored_generation(league, 2027) == "no entry" and witness(league) is None
    # An exhibition (a game with no date) reads them converted, too.
    exhibition = game_tuning(monkeypatch)
    assert {k: exhibition[k] for k in converted} == converted
    assert unchanged()


def test_opening_a_page_before_the_hold_does_not_lose_the_commissioner_s_sliders(
    league, monkeypatch
):
    """The reported sequence: a legacy league in the offseason, the Tuning
    page is opened, then new seasons are held on the legacy engine and
    opening day comes. The page load had rewritten the file to the new
    keys, and the legacy game then played without the two settings."""
    write_schedule(league, 2026, played=6)
    _legacy_centres_file(league, 2026)
    before = _write_overrides(league)
    roll_over(league, 2026)
    view = T.get_tuning(ADMIN)
    assert view["engine"]["generation"] == NEW
    assert _overrides_path(league).read_text(encoding="utf-8") == before

    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    write_schedule(league, 2027)
    _new_process()
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    assert not _has_profile(tuning)
    assert {k: tuning[k] for k in LEGACY_SLIDERS} == LEGACY_SLIDERS
    assert "swing_walk_scale" not in tuning
    assert _overrides_path(league).read_text(encoding="utf-8") == before


def test_the_first_season_game_converts_the_file(league, monkeypatch):
    from playbalance import parallel_day

    write_schedule(league, 2027)
    before = _write_overrides(league)
    # A parallel-day worker never writes: its parent converts before the
    # fan-out.
    journal = parallel_day.GameJournal(engine_generation=NEW)
    with parallel_day.journal_capture(journal):
        assert _has_profile(game_tuning(monkeypatch, OPENING_DAY))
    assert _overrides_path(league).read_text(encoding="utf-8") == before

    tuning = game_tuning(monkeypatch, OPENING_DAY)
    converted = S.convert_slider_overrides(LEGACY_SLIDERS)
    assert {k: tuning[k] for k in converted} == converted
    stored = _stored(_overrides_path(league))
    assert _knobs(stored) == converted
    assert stored[S.LEGACY_SLIDERS_MARKER] == LEGACY_SLIDERS
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    text = _overrides_path(league).read_text(encoding="utf-8")
    game_tuning(monkeypatch, OPENING_DAY)
    assert _overrides_path(league).read_text(encoding="utf-8") == text


def test_the_parallel_day_parent_converts_only_a_fixed_season():
    import inspect

    from playbalance import season_simulator

    source = inspect.getsource(season_simulator)
    fixed = source.index("engine_generation = get_league_engine_generation()")
    load = source.index("get_physics_tuning_overrides(", fixed)
    fan_out = source.index("parallel_day.build_payload(")
    assert fixed < load < fan_out
    assert (
        "convert=recorded_league_engine_generation() == engine_generation"
        in source[load:fan_out]
    )


def test_a_save_marks_the_file_only_when_the_season_is_fixed(league, monkeypatch):
    def page_save(changes):
        view = T.get_tuning(ADMIN)
        draft = {**view["defaults"], **view["overrides"], **changes}
        diff = {
            k: float(v) for k, v in draft.items()
            if abs(float(v) - float(view["defaults"].get(k, 0.0))) > 1e-9
        }
        return T.save_tuning({"overrides": diff}, ADMIN)

    # The offseason: the page shows generation 5's sliders, nothing is fixed.
    _write_overrides(league)
    converted = S.convert_slider_overrides(LEGACY_SLIDERS)
    view = page_save({"hr_scale": 1.2})
    assert view["engine"]["generation"] == NEW
    assert view["overrides"] == {**converted, "hr_scale": 1.2}
    stored = _stored(_overrides_path(league))
    assert _knobs(stored) == {**converted, "hr_scale": 1.2}
    # The legacy values the page's conversions replaced are kept ...
    assert stored[S.LEGACY_SLIDERS_MARKER] == LEGACY_SLIDERS
    # ... and the file is not marked: no season is on generation 5 yet.
    assert S.SWING_SLIDER_REBASE_MARKER not in stored
    assert centers.recorded_league_engine_generation() is None

    # With a schedule a save fixes the season, and marks the file.
    write_schedule(league, 2027)
    page_save({"hr_scale": 1.25})
    assert stored_generation(league, 2027) == NEW and witness(league) == ("2027", NEW)
    assert _stored(_overrides_path(league))[S.SWING_SLIDER_REBASE_MARKER] is True


def test_an_offseason_save_then_the_hold_plays_the_legacy_settings(
    league, monkeypatch
):
    """Sliders saved from the generation 5 page while nothing was fixed; the
    next season is then held on the legacy engine."""
    _write_overrides(league)
    view = T.get_tuning(ADMIN)
    draft = {**view["defaults"], **view["overrides"], "hr_scale": 1.2}
    T.save_tuning(
        {"overrides": {
            k: float(v) for k, v in draft.items()
            if abs(float(v) - float(view["defaults"].get(k, 0.0))) > 1e-9
        }},
        ADMIN,
    )
    assert "walk_scale" not in _knobs(_stored(_overrides_path(league)))

    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    write_schedule(league, 2027)
    _new_process()
    before = _overrides_path(league).read_text(encoding="utf-8")
    tuning = game_tuning(monkeypatch, OPENING_DAY)
    assert not _has_profile(tuning)
    # Exactly the two settings he had, the other one he saved, and no
    # generation 5 key.
    assert {k: tuning[k] for k in LEGACY_SLIDERS} == LEGACY_SLIDERS
    assert tuning["hr_scale"] == 1.2
    assert not {"swing_walk_scale", "contact_strikeout_scale"} & set(tuning)
    assert _overrides_path(league).read_text(encoding="utf-8") == before
    assert T.get_tuning(ADMIN)["overrides"] == {**LEGACY_SLIDERS, "hr_scale": 1.2}


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    monkeypatch.setattr(S, "TUNING_OVERRIDES_PATH", path)
    return path


FULL_LEGACY = {
    "walk_scale": 1.0, "zone_swing_scale": 0.8, "two_strike_zone_protect": 0.8,
    "k_scale": 0.6, "contact_prob_scale": 0.9, "hr_scale": 1.1,
}


def test_a_converted_file_loaded_as_legacy_gives_the_legacy_values_back(
    overrides_file,
):
    """The hold, or a season put back on the old engine: the commissioner's
    legacy settings were dropped (the legacy engine does not read the new
    keys). They come back from the values the conversion kept."""
    overrides_file.write_text(
        json.dumps({**FULL_LEGACY, S.STEAL_FREQ_REBASE_MARKER: True})
    )
    converted = S.load_physics_tuning_overrides(NEW, convert=True)
    assert not set(S.LEGACY_SLIDER_KEYS) & set(converted)
    text = overrides_file.read_text()
    assert S.load_physics_tuning_overrides(LEGACY) == FULL_LEGACY
    assert S.load_physics_tuning_values(LEGACY)["walk_scale"] == 1.0
    assert overrides_file.read_text() == text  # in memory only
    assert load_tuning(S.load_physics_tuning_overrides(LEGACY)).get("k_scale") == 0.6
    # And generation 5 still reads the converted values.
    assert S.load_physics_tuning_overrides(NEW) == converted


def test_a_slider_changed_on_generation_5_is_carried_back_not_the_stale_value(
    overrides_file,
):
    overrides_file.write_text(json.dumps({"walk_scale": 1.0, "k_scale": 0.6}))
    converted = S.load_physics_tuning_overrides(NEW, convert=True)
    # Walk Rate is moved on the generation 5 page; Strikeout Rate is set
    # back to 1.0 (so it is no longer stored).
    assert converted["swing_walk_scale"] > 1.0
    assert converted["contact_strikeout_scale"] > 1.0
    S.save_physics_tuning_overrides({"swing_walk_scale": 0.9}, NEW)
    legacy = S.load_physics_tuning_overrides(LEGACY)
    # Walk Rate 0.9 on the new scale is a legacy walk_scale under its 0.83
    # default -- not the 1.0 that was converted at the switch. (To the
    # legacy slider's 0.01 step, so it converts back to within a step.)
    assert set(legacy) == {"walk_scale"}
    assert 0.6 <= legacy["walk_scale"] < 0.83
    assert S.convert_slider_overrides(legacy)["swing_walk_scale"] == pytest.approx(
        0.9, abs=0.025
    )
    # Strikeout Rate at 1.0 is the legacy default: the old 0.6 stays gone.
    assert "k_scale" not in legacy


def test_generation_5_sliders_with_no_legacy_past_are_converted_back(overrides_file):
    """A league created on generation 5 whose next season is held legacy."""
    S.save_physics_tuning_overrides(
        {"swing_walk_scale": 1.1, "contact_strikeout_scale": 0.9, "hr_scale": 1.05}, NEW
    )
    legacy = S.load_physics_tuning_overrides(LEGACY)
    assert set(legacy) == {"walk_scale", "k_scale", "hr_scale"}
    # Each to its legacy slider's 0.01 step, which is coarser than the new
    # sliders' (a step of the old Strikeout Rate is about 3% of the new one).
    back = S.convert_slider_overrides(legacy)
    assert back["swing_walk_scale"] == pytest.approx(1.1, abs=0.025)
    assert back["contact_strikeout_scale"] == pytest.approx(0.9, abs=0.035)
    assert legacy["walk_scale"] > 0.83 and legacy["k_scale"] < 0.51


def test_a_legacy_save_puts_a_converted_file_back_on_the_legacy_scales(
    overrides_file,
):
    overrides_file.write_text(json.dumps({"walk_scale": 1.0, "hr_scale": 1.1}))
    S.load_physics_tuning_overrides(NEW, convert=True)
    # The legacy page loads the restored values and saves a change.
    view = S.load_physics_tuning_overrides(LEGACY)
    assert view == {"walk_scale": 1.0, "hr_scale": 1.1}
    S.save_physics_tuning_overrides({**view, "walk_scale": 0.9}, LEGACY)
    stored = json.loads(overrides_file.read_text())
    assert stored == {
        "walk_scale": 0.9, "hr_scale": 1.1, S.STEAL_FREQ_REBASE_MARKER: True,
    }
    # Setting the legacy slider back to its default is not undone by a
    # value kept from the conversion.
    S.save_physics_tuning_overrides({"hr_scale": 1.1}, LEGACY)
    assert S.load_physics_tuning_overrides(LEGACY) == {"hr_scale": 1.1}
    # Back on generation 5 the legacy value saved last is what converts.
    S.save_physics_tuning_overrides({"walk_scale": 0.9, "hr_scale": 1.1}, LEGACY)
    assert S.load_physics_tuning_overrides(NEW) == S.convert_slider_overrides(
        {"walk_scale": 0.9, "hr_scale": 1.1}
    )


def test_a_file_that_was_never_converted_is_read_as_it_is(overrides_file):
    """Every league that has not switched: the legacy load returns the
    stored knobs untouched, in their stored order."""
    stored = {"k_scale": 0.55, "foul_rate": 0.4, "walk_scale": 1.0, "hr_scale": 1.1}
    overrides_file.write_text(json.dumps({**stored, S.STEAL_FREQ_REBASE_MARKER: True}))
    before = overrides_file.read_text()
    loaded = S.load_physics_tuning_overrides(LEGACY)
    assert loaded == stored and list(loaded) == list(stored)
    assert overrides_file.read_text() == before


# --- 3: an entry already stored for the season key ------------------------------------


def test_a_generation_5_season_moved_onto_a_year_with_a_legacy_entry_stays_on_5(
    league, monkeypatch
):
    """The schedule is regenerated into a year the file already has an
    entry for, written when that year was played on the legacy engine."""
    write_schedule(league, 2026, played=6)
    _legacy_centres_file(league, 2026)
    roll_over(league, 2026)
    _season_on_5(league, monkeypatch)
    standings = (league / "standings.json").read_text()
    write_schedule(league, 2026, played=0)  # no played rows, another year
    progress = _stored(league / "season_progress.json")
    progress["sim_index"] = 3  # the cursor and the standings still say 3 days
    (league / "season_progress.json").write_text(json.dumps(progress))
    (league / "standings.json").write_text(standings)
    assert stored_generation(league, 2026) is None  # the old legacy entry
    _new_process()

    assert centers.league_engine_generation(store=False) == NEW
    assert _has_profile(game_tuning(monkeypatch, "2026-04-04"))
    assert stored_generation(league, 2026) == NEW
    assert witness(league) == ("2026", NEW)
    # Rewound to Opening Day as well, it is still the same season.
    from api.routers import admin_league

    admin_league.reset_to_opening_day({}, ADMIN)
    _new_process()
    assert _has_profile(game_tuning(monkeypatch, "2026-04-01"))


# --- 4: a fault is not answered with "legacy" ---------------------------------------


def _break_the_lookup(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("transient fault")

    monkeypatch.setattr(centers, "_season_verdict", boom)


def test_a_fault_reading_the_generation_raises(league, monkeypatch):
    _season_on_5(league, monkeypatch)
    _break_the_lookup(monkeypatch)
    for store in (True, False):
        with pytest.raises(RuntimeError, match="transient fault"):
            centers.get_league_engine_generation(store=store)
    # A game fails rather than play the wrong engine.
    with pytest.raises(RuntimeError, match="transient fault"):
        game_tuning(monkeypatch, MID_SEASON)


def test_nothing_to_read_is_still_legacy_without_raising(tmp_path, league):
    # A fixture, an empty folder, a folder that does not exist.
    assert centers.league_engine_generation(CALIBRATION) == LEGACY
    assert centers.league_engine_generation(tmp_path / "empty") == LEGACY
    # The active league with no schedule and no files: the next season's.
    assert centers.get_league_engine_generation(store=False) == NEW
    assert centers.recorded_league_engine_generation() is None


def test_each_reader_s_answer_to_a_fault(league, monkeypatch):
    from api.ws import sim as ws_sim
    from playbalance import usage_store
    from services.league_tuning import league_tuning_overrides
    from utils.lineup_autofill import platoon_tuning

    _write_overrides(league, {"hr_scale": 1.1})
    _season_on_5(league, monkeypatch)
    text = _overrides_path(league).read_text(encoding="utf-8")
    _break_the_lookup(monkeypatch)

    # The Tuning page: an error the page shows, and no save or reset.
    for call in (
        lambda: T.get_tuning(ADMIN),
        lambda: T.save_tuning({"overrides": {"hr_scale": 1.3}}, ADMIN),
        lambda: T.reset_tuning(ADMIN),
    ):
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 500
        assert caught.value.detail == T.ENGINE_LOOKUP_FAILED
    assert _overrides_path(league).read_text(encoding="utf-8") == text
    # Watch-a-game: raises into the socket's "Simulation failed" message.
    with pytest.raises(RuntimeError):
        ws_sim._league_tuning_overrides()
    with pytest.raises(RuntimeError):
        league_tuning_overrides(store=False)
    # A lineup action and the rest-state replay carry on, on the defaults.
    assert platoon_tuning().get("swing_model") == 0.0
    assert "logger.exception" in __import__("inspect").getsource(
        usage_store._bootstrap_from_tracker
    )


# --- 5: messages ---------------------------------------------------------------------


def test_the_legacy_message_tells_the_truth_under_the_hold(league, monkeypatch):
    write_schedule(league, 2026, played=3)
    assert T.get_tuning(ADMIN)["engine"]["message"] == T.ENGINE_MESSAGE_LEGACY
    assert "moves to the new game engine" in T.ENGINE_MESSAGE_LEGACY
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    message = T.get_tuning(ADMIN)["engine"]["message"]
    assert message == T.ENGINE_MESSAGE_LEGACY_HELD
    assert "moves" not in message and "next season" not in message
    assert centers.new_seasons_held_on_legacy()


def test_a_generation_5_league_s_message_does_not_change_under_the_hold(
    league, monkeypatch
):
    _season_on_5(league, monkeypatch)
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY))
    assert T.get_tuning(ADMIN)["engine"]["message"] == T.ENGINE_MESSAGE_CURRENT


def _create_payload(league_id: str, preset: str = "") -> dict:
    return {
        "display_name": f"Scratch {league_id}",
        "league_id": league_id,
        "rule_preset_id": preset,
        "divisions": {
            "East": [{"city": f"City{i}", "name": f"Club{i}"} for i in range(6)]
        },
    }


def test_the_wizard_reports_a_rule_preset_that_failed(league, monkeypatch):
    """The league is still created; the failure used to vanish."""
    from api.routers import league_create
    from services import league_registry

    def broken(_preset_id):
        raise ValueError("hr_scale must be a finite number, got 'lots'")

    monkeypatch.setattr(league_create, "apply_rule_preset", broken)
    result = league_create._build_league(_create_payload("presetfail", "high_offense"))
    assert result["league_id"] == "presetfail"
    assert len(result["warnings"]) == 1
    assert "high_offense" in result["warnings"][0]
    assert "hr_scale must be a finite number" in result["warnings"][0]
    data_dir = league_registry.get_league_data_dir("presetfail", create=False)
    assert (data_dir / "teams.csv").exists() and (data_dir / "schedule.csv").exists()


def test_the_wizard_reports_an_unknown_preset_and_nothing_when_all_is_well(
    league, monkeypatch
):
    from api.routers import league_create

    unknown = league_create._build_league(_create_payload("nopreset", "no_such_preset"))
    assert len(unknown["warnings"]) == 1 and "not found" in unknown["warnings"][0]
    fine = league_create._build_league(_create_payload("goodpreset", "high_offense"))
    assert fine["warnings"] == []
