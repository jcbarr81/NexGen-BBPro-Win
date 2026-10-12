"""Release 5 switch-on: the engine generation of a league season.

Owner decision 12: the new engine must not reach a league in the middle of
a season. Each league stays on today's engine until its own next season
begins; a brand-new league starts on the new one; nothing changes for an
existing league at deploy.

These run the live path in a scratch league (tests/r5_flip_support.py):
the tuning ``playbalance.game_runner`` hands the engine is captured with
every league getter real.
"""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from physics_sim.config import load_tuning
from physics_sim.engine_generation import (
    CURRENT_ENGINE_GENERATION,
    LEGACY_ENGINE_GENERATION,
    engine_profile,
)
from services import league_rating_centers as centers
from services import physics_tuning_settings as settings
from services.injury_settings import get_injury_tuning_overrides
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    ADMIN,
    NEW_SEASON_ENGINE_ENV,
    game_tuning,
    league,
    play_days,
    roll_over,
    stored_generation,
    team_ids,
    write_schedule,
)

PROFILE = engine_profile(CURRENT_ENGINE_GENERATION)
# What a commissioner had stored before the deploy.
STORED = {"foul_rate": 0.4, "hr_scale": 1.1, "walk_scale": 1.0}


def _write_stored_overrides(data, values=STORED) -> str:
    """The overrides file as today's code writes it; returns its text."""
    path = data / settings.TUNING_OVERRIDES_FILENAME
    payload = {**values, settings.STEAL_FREQ_REBASE_MARKER: True}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _write_centres_as_today(data, season) -> str:
    """``rating_centers.json`` as the code deployed today leaves it after a
    season's first game: every centre, no generation. Returns its text."""
    path = data / centers.RATING_CENTERS_FILENAME
    payload = {"version": 1, "seasons": {str(season): centers.active_rating_centers(data)}}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _tuning_as_today(data) -> dict:
    """The dict today's game runner builds: the stored overrides, the
    injury settings, the rating centres, the extra-innings rule."""
    expected = dict(sorted(STORED.items()))
    expected.update(get_injury_tuning_overrides())
    expected.update(centers.active_rating_centers(data))
    expected["extra_innings_runner"] = 1.0
    return expected


def _has_profile(tuning: dict) -> bool:
    return tuning.get("swing_model") == 1.0 and tuning.get("contact_model") == 1.0


def _news(data) -> str:
    path = data / "news_feed.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --- nothing changes at deploy ---------------------------------------------------


def test_a_season_in_progress_gets_exactly_todays_tuning(league, monkeypatch):
    write_schedule(league, 2026, played=3)
    overrides_text = _write_stored_overrides(league)
    centres_text = _write_centres_as_today(league, 2026)
    expected = _tuning_as_today(league)

    for _ in range(2):
        tuning = game_tuning(monkeypatch)
        assert tuning == expected
        assert list(tuning) == list(expected)  # same layers, same order
        assert load_tuning(tuning).values == load_tuning(expected).values
        assert not set(PROFILE) - set(STORED) & set(tuning)
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    # Neither file was touched: no generation written, no slider converted.
    assert (league / settings.TUNING_OVERRIDES_FILENAME).read_text() == overrides_text
    assert (league / centers.RATING_CENTERS_FILENAME).read_text() == centres_text
    assert stored_generation(league, 2026) is None
    assert _news(league) == ""


def test_a_league_mid_season_that_never_had_the_file_stays_legacy(league, monkeypatch):
    write_schedule(league, 2026, played=3)
    _write_stored_overrides(league)
    assert centers.league_engine_generation(store=False) == LEGACY_ENGINE_GENERATION
    assert not (league / centers.RATING_CENTERS_FILENAME).exists()
    assert game_tuning(monkeypatch) == _tuning_as_today(league)
    # Its first game since the deploy writes the season's entry as today's
    # code would: centres only. Legacy is the absence of a generation.
    stored = json.loads((league / centers.RATING_CENTERS_FILENAME).read_text())
    assert stored == {
        "version": 1, "seasons": {"2026": centers.active_rating_centers(league)},
    }
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION


@pytest.mark.parametrize("evidence", ["schedule", "cursor", "standings"])
def test_any_trace_of_a_played_game_keeps_a_season_legacy(league, evidence):
    """A schedule regenerated mid-season has no played rows, a results reset
    clears them too; the cursor and the standings still say games happened."""
    teams = team_ids(league)
    write_schedule(league, 2026, played=0)
    if evidence == "schedule":
        write_schedule(league, 2026, played=1)
        (league / "season_progress.json").write_text(json.dumps({"sim_index": 0}))
        (league / "standings.json").write_text("{}")
    elif evidence == "cursor":
        (league / "season_progress.json").write_text(json.dumps({"sim_index": 40}))
    else:
        (league / "standings.json").write_text(
            json.dumps({teams[0]: {"wins": 0, "losses": 1}})
        )
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    assert stored_generation(league, 2026) == "no entry"  # nothing to write


def test_a_legacy_season_survives_regeneration_and_resets(league, monkeypatch):
    from api.routers import admin_league

    write_schedule(league, 2026, played=3)
    _write_stored_overrides(league)
    _write_centres_as_today(league, 2026)
    expected = _tuning_as_today(league)

    asyncio.run(admin_league.regenerate_schedule({"template_id": "mlb_162"}, ADMIN))
    year = (league / "schedule.csv").read_text().splitlines()[1][:4]
    # Whatever year the schedule came back with, the league is still legacy:
    # its entry says so, or the cursor and the standings do.
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    admin_league.reset_results(ADMIN)
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    if year == "2026":
        # Reset to Opening Day rewinds the season; its entry keeps the engine.
        admin_league.reset_to_opening_day({}, ADMIN)
        assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
        assert game_tuning(monkeypatch) == expected
    assert stored_generation(league, 2026) is None


# --- the switch at a league's own rollover ------------------------------------


def test_a_league_moves_to_the_new_engine_at_its_rollover(league, monkeypatch):
    from api.routers import admin_league

    write_schedule(league, 2026, played=6)
    _write_stored_overrides(league)
    _write_centres_as_today(league, 2026)
    assert not _has_profile(game_tuning(monkeypatch))

    roll_over(league, 2026)
    # Offseason: no schedule, so no season to fix; the next one will be 5.
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    assert stored_generation(league, 2027) == "no entry"
    assert _news(league).count(centers.ENGINE_SWITCH_NEWS) == 0

    write_schedule(league, 2027)
    # A page load or a lineup read in the preseason fixes nothing.
    assert centers.league_engine_generation(store=False) == CURRENT_ENGINE_GENERATION
    assert stored_generation(league, 2027) == "no entry"

    tuning = game_tuning(monkeypatch)
    converted = settings.convert_slider_overrides(STORED)
    assert "walk_scale" not in converted and converted["swing_walk_scale"] > 1.0
    # Defaults, then the profile, then the stored overrides, then centres.
    expected = dict(PROFILE)
    expected.update(converted)
    expected.update(get_injury_tuning_overrides())
    expected.update(centers.active_rating_centers(league))
    expected["extra_innings_runner"] = 1.0
    assert tuning == expected
    assert _has_profile(tuning)
    # A stored commissioner override still wins over the profile.
    assert PROFILE["foul_rate"] != 0.4 and tuning["foul_rate"] == 0.4
    assert tuning["hr_scale"] == 1.1
    assert stored_generation(league, 2027) == CURRENT_ENGINE_GENERATION
    assert stored_generation(league, 2026) is None  # last season stays legacy

    # Fixed for the season: games, a regenerated schedule, a results reset
    # and a reset to Opening Day leave it where it is.
    play_days(league, 2)
    assert _has_profile(game_tuning(monkeypatch))
    asyncio.run(admin_league.regenerate_schedule({"template_id": "mlb_162"}, ADMIN))
    assert (league / "schedule.csv").read_text().splitlines()[1].startswith("2027")
    assert _has_profile(game_tuning(monkeypatch))
    admin_league.reset_results(ADMIN)
    assert _has_profile(game_tuning(monkeypatch))
    admin_league.reset_to_opening_day({}, ADMIN)
    assert _has_profile(game_tuning(monkeypatch))
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    assert stored_generation(league, 2027) == CURRENT_ENGINE_GENERATION

    # The league was told once, in plain language.
    news = _news(league)
    assert news.count(centers.ENGINE_SWITCH_NEWS) == 1
    assert "updated game engine" in centers.ENGINE_SWITCH_NEWS
    for word in ("Strikeouts", "walks", "contact", "home teams", "intentional walks"):
        assert word in centers.ENGINE_SWITCH_NEWS

    # The season after: still the new engine, and no second announcement.
    roll_over(league, 2027)
    write_schedule(league, 2028)
    assert _has_profile(game_tuning(monkeypatch))
    assert stored_generation(league, 2028) == CURRENT_ENGINE_GENERATION
    assert _news(league).count(centers.ENGINE_SWITCH_NEWS) == 1


def test_a_schedule_regenerated_with_another_year_does_not_change_engines(
    league, monkeypatch
):
    """The season key is the schedule's year. If a mid-season regeneration
    moves it, the season keeps the engine it has been playing on."""
    write_schedule(league, 2027)
    assert _has_profile(game_tuning(monkeypatch))
    play_days(league, 3)
    write_schedule(league, 2026, played=0)  # another year, no played rows
    (league / "season_progress.json").write_text(json.dumps({"sim_index": 3}))
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    assert _has_profile(game_tuning(monkeypatch))


# --- new leagues ------------------------------------------------------------------


def test_a_new_league_starts_on_the_new_engine_without_an_announcement(
    league, monkeypatch
):
    # Being created: no schedule yet.
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    write_schedule(league, 2026)
    tuning = game_tuning(monkeypatch)
    assert _has_profile(tuning)
    for key, value in PROFILE.items():
        assert tuning[key] == value, key
    assert stored_generation(league, 2026) == CURRENT_ENGINE_GENERATION
    play_days(league, 4)
    assert _has_profile(game_tuning(monkeypatch))
    assert centers.ENGINE_SWITCH_NEWS not in _news(league)


def test_the_operations_switch_holds_new_seasons_on_the_legacy_engine(
    league, monkeypatch
):
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, str(LEGACY_ENGINE_GENERATION))
    write_schedule(league, 2026)
    assert not _has_profile(game_tuning(monkeypatch))
    assert stored_generation(league, 2026) is None
    # Lifting it later does not move a season that has an entry.
    monkeypatch.delenv(NEW_SEASON_ENGINE_ENV)
    centers.clear_rating_center_cache()
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    # A value that is not a generation is ignored.
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, "banana")
    assert centers._configured_new_season_generation() == CURRENT_ENGINE_GENERATION


def test_a_season_is_never_started_on_a_generation_without_a_profile(
    league, monkeypatch
):
    import physics_sim.engine_generation as generations

    monkeypatch.setattr(generations, "ENGINE_PROFILE_DIR", league / "nowhere")
    write_schedule(league, 2026)
    assert centers.league_engine_generation() == LEGACY_ENGINE_GENERATION
    assert not _has_profile(game_tuning(monkeypatch))


def test_a_season_on_the_new_engine_is_never_played_on_the_old_one(
    league, monkeypatch
):
    import physics_sim.engine_generation as generations

    write_schedule(league, 2026)
    assert _has_profile(game_tuning(monkeypatch))
    monkeypatch.setattr(generations, "ENGINE_PROFILE_DIR", league / "nowhere")
    with pytest.raises(ValueError, match="engine profile"):
        game_tuning(monkeypatch)


# --- copies, backups, lost and broken files ---------------------------------------


def test_a_copied_league_keeps_its_season_s_engine(league, monkeypatch, tmp_path):
    write_schedule(league, 2026)
    game_tuning(monkeypatch)
    play_days(league, 2)
    new_copy = tmp_path / "copy_new"
    shutil.copytree(league, new_copy)
    # Read by its own files, without being the active league.
    assert centers.league_engine_generation(new_copy) == CURRENT_ENGINE_GENERATION

    legacy = tmp_path / "copy_legacy"
    shutil.copytree(league, legacy)
    (legacy / centers.RATING_CENTERS_FILENAME).unlink()
    assert centers.league_engine_generation(legacy) == LEGACY_ENGINE_GENERATION


def test_a_backup_restores_the_engine_with_the_league(league, monkeypatch):
    from services import league_snapshot

    write_schedule(league, 2026)
    game_tuning(monkeypatch)
    play_days(league, 2)
    backup = league_snapshot.create_backup_snapshot()
    assert backup["status"] == "success"

    (league / centers.RATING_CENTERS_FILENAME).unlink()
    centers.clear_rating_center_cache()
    # The file is gone mid-season: nothing says the season was on 5.
    assert centers.league_engine_generation(store=False) == LEGACY_ENGINE_GENERATION
    from pathlib import Path

    restored = league_snapshot.import_league_snapshot(
        Path(backup["path"]), require_league_match=False
    )
    assert restored["status"] == "success"
    centers.clear_rating_center_cache()
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    assert _has_profile(game_tuning(monkeypatch))


def test_an_unreadable_file_decides_nothing(league, monkeypatch):
    write_schedule(league, 2026)
    game_tuning(monkeypatch)
    play_days(league, 2)
    path = league / centers.RATING_CENTERS_FILENAME
    path.write_text("{ not json", encoding="utf-8")
    # This process already knows the season's engine; the broken file is
    # neither believed nor overwritten.
    assert centers.league_engine_generation() == CURRENT_ENGINE_GENERATION
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_fixtures_and_folders_without_a_season_are_legacy(tmp_path):
    from tests.r5_flip_support import CALIBRATION

    assert centers.league_engine_generation(CALIBRATION) == LEGACY_ENGINE_GENERATION
    assert centers.league_engine_generation(tmp_path) == LEGACY_ENGINE_GENERATION
    assert not (CALIBRATION / centers.RATING_CENTERS_FILENAME).exists()


# --- every path that plays or describes a league game ----------------------------


def test_a_parallel_worker_plays_the_generation_its_parent_fixed(league, monkeypatch):
    from playbalance import parallel_day

    payload = parallel_day.build_payload(
        home="H", away="A", seed=1, date="2026-04-01", home_starter=None,
        away_starter=None, data_root="root", league_id="x", usage_in={},
        engine_generation=CURRENT_ENGINE_GENERATION,
    )
    assert payload["engine_generation"] == CURRENT_ENGINE_GENERATION
    assert parallel_day.build_payload(
        home="H", away="A", seed=1, date="d", home_starter=None, away_starter=None,
        data_root="root", league_id=None, usage_in={},
    )["engine_generation"] is None
    assert parallel_day.GameJournal().engine_generation is None

    # A legacy league; the journal's generation is used, nothing looked up.
    write_schedule(league, 2026, played=3)
    monkeypatch.setattr(
        "playbalance.game_runner.get_league_engine_generation",
        lambda **_k: pytest.fail("a worker must not look the generation up"),
    )
    journal = parallel_day.GameJournal(engine_generation=CURRENT_ENGINE_GENERATION)
    with parallel_day.journal_capture(journal):
        assert _has_profile(game_tuning(monkeypatch))


def test_the_parent_fixes_the_generation_before_the_fan_out():
    import inspect

    from playbalance import season_simulator

    source = inspect.getsource(season_simulator)
    fixed = source.index("engine_generation = get_league_engine_generation()")
    fan_out = source.index("parallel_day.build_payload(")
    assert fixed < fan_out
    assert "engine_generation=engine_generation," in source[fan_out:]


def test_watch_a_game_plays_the_league_s_engine_and_fixes_nothing(league):
    from api.ws import sim as ws_sim

    write_schedule(league, 2026)
    tuning = ws_sim._league_tuning_overrides()
    assert _has_profile(tuning)
    assert not (league / centers.RATING_CENTERS_FILENAME).exists()

    write_schedule(league, 2026, played=3)  # a legacy season instead
    centers.clear_rating_center_cache()
    _write_stored_overrides(league)
    legacy = ws_sim._league_tuning_overrides()
    expected = dict(sorted(STORED.items()))
    expected.update(get_injury_tuning_overrides())
    expected.update(centers.active_rating_centers(league))
    assert legacy == expected


def test_the_one_assembly_function_layers_profile_then_overrides(league):
    from services.league_tuning import league_tuning, league_tuning_overrides

    write_schedule(league, 2026)
    _write_stored_overrides(league, {"foul_rate": 0.4, "hr_scale": 1.1})
    assembled = league_tuning_overrides(store=False)
    assert assembled == {**PROFILE, "foul_rate": 0.4, "hr_scale": 1.1}
    assert stored_generation(league, 2026) == "no entry"
    whole = league_tuning()
    assert whole.get("swing_model") == 1.0 and whole.get("foul_rate") == 0.4
    centre = centers.active_rating_centers(league)["hitter_contact_center"]
    assert whole.get("hitter_contact_center") == centre
    # Legacy: exactly the stored overrides, as before generations existed.
    assert league_tuning_overrides(generation=LEGACY_ENGINE_GENERATION) == {
        "foul_rate": 0.4, "hr_scale": 1.1,
    }
