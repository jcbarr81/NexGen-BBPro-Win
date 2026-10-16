"""Generation 7's operations switch (``NEXGEN_GENERATION7``), read only with
the 8.0.0 switch on: a league moves to the ball-flight engine at the start of
its next season, the way 8.0.0 moves it to generation 6.

A league on rating scale 1 is converted first and lands on generation 7 (one
move, one news item); a league on scale 2 already simply starts its next
season on 7 (its own news item). The 8.0.0 refusal and the hold
(``NEXGEN_NEW_SEASON_ENGINE``; 6 stops moves to 7) still apply. Every league
is a scratch copy of the calibration fixture under ``tmp_path``.
"""

from __future__ import annotations

import json

import pytest

from physics_sim.engine_generation import (
    BALLFLIGHT_ENGINE_GENERATION,
    engine_profile,
    known_engine_generations,
)
from services import league_rating_centers as centers
from services import rating_scale_migration as migration
from services.ballflight_news import BALLFLIGHT_ENGINE_TEXT
from services.physics_tuning_settings import (
    BALLFLIGHT_SLIDER_REBASE_MARKER,
    PRE_GENERATION_7_MARKER,
)
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    archive_a_season,
    clip_an_active_player,
    game_tuning,
    news,
    read_rows,
    roll_over,
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
    GENERATION7_SWITCH_ENV,
    generated_rating_scale,
    generation7_switch_on,
    players_file_rating_scale,
    stretch_row,
)

GEN7_KEYS = centers.GENERATION_CENTER_KEYS[7]
LEAD = "with real ball flight"


def _both_on(monkeypatch) -> None:
    monkeypatch.setenv(GENERATION7_SWITCH_ENV, "1")
    switch_on(monkeypatch)


def _first_game(monkeypatch, year: int = 2026) -> dict:
    return game_tuning(monkeypatch, f"{year}-04-01")


def _on_scale_2(data) -> None:
    """As a league created on scale 2 (or moved by 8.0.0) is written."""
    fields, rows = read_rows(data / "players.csv")
    migration._write_players(
        data / "players.csv", fields, [stretch_row(r, 2)[0] for r in rows]
    )


def _stored_entry(data, year):
    return json.loads((data / "rating_centers.json").read_text())["seasons"][str(year)]


# --- off: nothing changes ------------------------------------------------------


def test_off_no_league_can_get_generation_7(scratch, monkeypatch):
    switch_off(monkeypatch)
    monkeypatch.setenv(GENERATION7_SWITCH_ENV, "1")  # alone: nothing
    assert not generation7_switch_on()
    assert BALLFLIGHT_ENGINE_GENERATION not in known_engine_generations()
    with pytest.raises(ValueError):
        engine_profile(7)
    monkeypatch.delenv(GENERATION7_SWITCH_ENV)
    switch_on(monkeypatch)  # 8.0.0 alone: generation 6, as shipped
    assert known_engine_generations() == (4, 5, 6)
    write_schedule(scratch, 2026)
    tuning = _first_game(monkeypatch)
    assert stored_generation(scratch, 2026) == 6
    assert not any(key in _stored_entry(scratch, 2026) for key in GEN7_KEYS)
    assert not any(key in tuning for key in GEN7_KEYS)
    assert LEAD not in news(scratch)
    (event,) = [e for e in scale_log(scratch)["events"] if e["event"] == "converted"]
    assert event["engine_generation"] == 6


# --- on -------------------------------------------------------------------------


def test_a_scale_1_league_is_converted_and_lands_on_generation_7(scratch, monkeypatch):
    data = scratch
    archive_a_season(data)
    _both_on(monkeypatch)
    assert known_engine_generations() == (4, 5, 6, 7)
    write_schedule(data, 2026)
    assert centers.league_engine_generation(store=False) == 7
    tuning = _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 7
    assert witness(data) == ("2026", 7)
    for key, value in engine_profile(7).items():
        assert tuning[key] == value, key
    # Generation 7's centres: stored for the season and delivered.
    entry = _stored_entry(data, 2026)
    for key in GEN7_KEYS:
        assert key in entry and tuning[key] == entry[key], key
    assert players_file_rating_scale(data / "players.csv") == FULL_RATING_SCALE
    (event,) = [e for e in scale_log(data)["events"] if e["event"] == "converted"]
    assert event["engine_generation"] == 7
    # One move, one item: the engine-and-scale item carries the ball flight.
    feed = news(data)
    assert feed.count("full 1-99 scale") == 1
    assert feed.count(BALLFLIGHT_ENGINE_TEXT) == 1
    assert LEAD not in feed  # no second, ball-flight-only item
    assert centers.ENGINE_SWITCH_NEWS not in feed
    # The league's own parks (the calibration clubs play in real ones).
    assert "real major-league parks" in feed


def test_a_league_on_generation_6_moves_to_7_at_its_next_season(scratch, monkeypatch):
    data = scratch
    switch_on(monkeypatch)  # 8.0.0 only: the 2026 season on generation 6
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    (data / "physics_tuning_overrides.json").write_text(
        json.dumps({"hr_scale": 0.95, "launch_angle_base": 14.0}), encoding="utf-8"
    )
    # Switched on mid-season: the season under way stays on 6.
    _both_on(monkeypatch)
    write_schedule(data, 2026, played=2)
    assert _first_game(monkeypatch)["hr_scale"] == pytest.approx(0.95)
    assert stored_generation(data, 2026) == 6
    events = list(scale_log(data)["events"])
    roll_over(data, 2026)
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    tuning = _first_game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 7
    # No second conversion; its own news item, once, and recorded.
    after = scale_log(data)["events"]
    assert after[: len(events)] == events
    assert [e["event"] for e in after[len(events):]] == [
        migration.BALLFLIGHT_ANNOUNCED_EVENT
    ]
    feed = news(data)
    assert feed.count(LEAD) == 1 and feed.count(BALLFLIGHT_ENGINE_TEXT) == 1
    _first_game(monkeypatch, 2027)
    assert news(data).count(LEAD) == 1
    # The sliders on their generation 7 meaning: back at neutral, the old
    # values kept in the marker.
    assert tuning["hr_scale"] == pytest.approx(1.0)
    assert tuning["launch_angle_base"] == pytest.approx(12.1)
    stored = json.loads((data / "physics_tuning_overrides.json").read_text())
    assert stored[PRE_GENERATION_7_MARKER] == {"hr_scale": 0.95, "launch_angle_base": 14.0}
    assert stored[BALLFLIGHT_SLIDER_REBASE_MARKER] is True
    for key in GEN7_KEYS:
        assert key in _stored_entry(data, 2027) and key in tuning
        assert key not in _stored_entry(data, 2026)


def _rolled_over_onto_7(data, monkeypatch, *, sliders=None):
    """A legacy season under way, both switches on, the rollover's move (a
    scale 1 league converted for its next season, offered 7)."""
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")
    _both_on(monkeypatch)
    if sliders:
        (data / "physics_tuning_overrides.json").write_text(
            json.dumps(sliders), encoding="utf-8"
        )
    assert centers.move_league_at_rollover(data, 2027) == "converted"
    (event,) = scale_log(data)["events"]
    assert event["engine_generation"] == 7 and event["season"] == "2027"
    # Told about the scale now; about ball flight only when 2027 is
    # recorded on 7 (review fix 1).
    assert "full 1-99 scale" in news(data)
    assert BALLFLIGHT_ENGINE_TEXT not in news(data)
    assert migration.BALLFLIGHT_TOLD_KEY not in event
    archive_a_season(data)
    (data / "season_progress.json").unlink()  # the rollover rebuilds it
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)


def test_the_rollover_converts_and_the_first_game_tells_ball_flight_once(
    scratch, monkeypatch
):
    data = scratch
    sliders = {"hr_scale": 0.95}
    _rolled_over_onto_7(data, monkeypatch, sliders=sliders)
    tuning = _first_game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 7
    feed = news(data)
    assert feed.count("full 1-99 scale") == 1
    assert feed.count(BALLFLIGHT_ENGINE_TEXT) == 1 and feed.count(LEAD) == 1
    assert tuning["hr_scale"] == pytest.approx(1.0)
    stored = json.loads((data / "physics_tuning_overrides.json").read_text())
    assert stored[PRE_GENERATION_7_MARKER] == sliders
    _first_game(monkeypatch, 2027)
    assert news(data).count(LEAD) == 1


def test_a_hold_set_after_the_rollover_leaves_nothing_claimed(scratch, monkeypatch):
    """Review fix 1: the operator's safe stop (NEXGEN_NEW_SEASON_ENGINE=6)
    set between the rollover and the first game. The season is recorded on
    6, the league is told nothing about ball flight, and its sliders keep
    their generation 6 meaning."""
    data = scratch
    sliders = {"hr_scale": 0.95}
    _rolled_over_onto_7(data, monkeypatch, sliders=sliders)
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "6")
    tuning = _first_game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 6
    assert BALLFLIGHT_ENGINE_TEXT not in news(data) and LEAD not in news(data)
    assert tuning["hr_scale"] == pytest.approx(0.95)
    stored = json.loads((data / "physics_tuning_overrides.json").read_text())
    assert PRE_GENERATION_7_MARKER not in stored
    assert BALLFLIGHT_SLIDER_REBASE_MARKER not in stored
    assert not migration.ballflight_told(data)


def test_a_league_rolled_back_and_converted_again_onto_7_is_told(scratch, monkeypatch):
    """Review fix 2: moved to 6, rolled back, the hold lifted with
    generation 7 switched on. The re-conversion posts only its short item,
    so the league gets the ball-flight item on its own -- once."""
    data = scratch
    archive_a_season(data)
    switch_on(monkeypatch)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    migration.rollback_league(data, mode="inverse")
    roll_over(data, 2026)
    _both_on(monkeypatch)
    log = scale_log(data)
    log.pop("hold")
    (data / "rating_scale.json").write_text(json.dumps(log), encoding="utf-8")
    migration.clear_caches()
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    _first_game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 7
    feed = news(data)
    assert feed.count("re-converted to the full 1-99 scale") == 1
    assert feed.count(BALLFLIGHT_ENGINE_TEXT) == 1 and feed.count(LEAD) == 1
    assert migration.ballflight_told(data)
    _first_game(monkeypatch, 2027)
    assert news(data).count(LEAD) == 1


def test_a_stale_copy_on_a_generation_7_season_is_repaired_and_logged_as_7(
    scratch, monkeypatch, capsys
):
    """Review fix 4: the repair names the season's own generation."""
    data = scratch
    stale = (data / "players.csv").read_bytes()  # scale 1, as a stale copy
    _both_on(monkeypatch)
    _on_scale_2(data)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 7
    (data / "players.csv").write_bytes(stale)
    migration.clear_caches()
    centers.clear_rating_center_cache()
    capsys.readouterr()
    _first_game(monkeypatch)
    assert players_file_rating_scale(data / "players.csv") == FULL_RATING_SCALE
    (event,) = [e for e in scale_log(data)["events"] if e["event"] == "repaired"]
    assert event["engine_generation"] == 7
    out = capsys.readouterr().out
    assert "of a generation 7 league" in out and "generation 6 league" not in out
    assert LEAD not in news(data)  # a new league: nothing to be told


def test_the_rollback_tool_and_the_runbook_name_generation_7():
    from pathlib import Path

    from scripts import rating_scale_rollback

    assert "generation 7" in rating_scale_rollback.__doc__
    runbook = (Path(__file__).resolve().parents[1] / "docs" / "generation7_switch_runbook.md")
    text = runbook.read_text(encoding="utf-8")
    assert "recorded on generation 7" in text and "NEXGEN_NEW_SEASON_ENGINE=6" in text


def test_a_season_on_7_repaired_after_a_rollback_tells_a_league_never_told(
    scratch, monkeypatch
):
    """Review fix 2, the repair path: a season already recorded on 7 whose
    players were rolled back to scale 1, the hold then lifted: its next game
    converts again (the short item) and the league, never told, is told."""
    data = scratch
    archive_a_season(data)
    _both_on(monkeypatch)
    _on_scale_2(data)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 7
    assert news(data).count(LEAD) == 1  # told at the season's first record
    # As an operator's mistake would leave it: the told record lost.
    migration.rollback_league(data, mode="inverse", season="2026", allow_unrecorded=True)
    log = scale_log(data)
    log.pop("hold")
    log["events"] = [e for e in log["events"] if e.get("event") == "rolled_back"]
    (data / "rating_scale.json").write_text(json.dumps(log), encoding="utf-8")
    (data / "news_feed.txt").unlink()
    migration.clear_caches()
    centers.clear_rating_center_cache()
    _first_game(monkeypatch)
    assert players_file_rating_scale(data / "players.csv") == FULL_RATING_SCALE
    (moved,) = [e for e in scale_log(data)["events"] if e["event"] == "converted"]
    assert moved["engine_generation"] == 7  # the repair logs the season's engine
    feed = news(data)
    assert feed.count("re-converted to the full 1-99 scale") == 1
    assert feed.count(LEAD) == 1


def test_a_league_created_with_both_switches_on_starts_on_7(scratch, monkeypatch):
    data = scratch
    _both_on(monkeypatch)
    monkeypatch.delenv(centers.NEW_SEASON_ENGINE_ENV, raising=False)
    assert generated_rating_scale() == 2
    _on_scale_2(data)  # generated on scale 2, no season behind it
    write_schedule(data, 2026)
    tuning = _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 7
    assert all(key in tuning for key in GEN7_KEYS)
    assert not (data / "rating_scale.json").exists()
    assert news(data) == ""  # nothing to be told: it never played another


# --- the 8.0.0 rules still apply -----------------------------------------------


def test_the_hold_6_stops_moves_to_7(scratch, monkeypatch):
    data = scratch
    archive_a_season(data)
    _both_on(monkeypatch)
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "6")
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 6
    (event,) = [e for e in scale_log(data)["events"] if e["event"] == "converted"]
    assert event["engine_generation"] == 6
    assert BALLFLIGHT_ENGINE_TEXT not in news(data)
    assert centers.move_league_at_rollover(data, 2027) == "already"


def test_a_league_on_7_starts_its_next_season_on_6_under_the_hold(scratch, monkeypatch):
    """The runbook's hold: NEXGEN_NEW_SEASON_ENGINE=6 puts every NEXT season
    on generation 6 (scale 2 plays correctly on it); the season recorded
    on 7 keeps 7."""
    data = scratch
    _both_on(monkeypatch)
    _on_scale_2(data)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 7
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "6")
    centers.clear_rating_center_cache()
    assert _first_game(monkeypatch)["carry_model"] == 1.0  # 2026 stays on 7
    roll_over(data, 2026)
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    tuning = _first_game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 6
    assert tuning.get("carry_model", 0.0) == 0.0


def test_the_hold_5_moves_nobody(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    _both_on(monkeypatch)
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "5")
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    assert centers.move_league_at_rollover(data, 2027) is None


def test_a_league_that_would_clip_stays_on_5_and_is_told(scratch, monkeypatch):
    data = scratch
    pid = clip_an_active_player(data)
    original = (data / "players.csv").read_bytes()
    _both_on(monkeypatch)
    write_schedule(data, 2026)
    assert centers.league_engine_generation(store=False) == 5
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    assert pid in news(data) and "[commissioner]" in news(data)
    assert BALLFLIGHT_ENGINE_TEXT not in news(data)


def test_a_season_under_way_never_moves(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    _both_on(monkeypatch)
    write_schedule(data, 2026, played=2)
    _first_game(monkeypatch)
    assert centers.league_engine_generation() == 4
    assert (data / "players.csv").read_bytes() == original


def test_switching_7_off_breaks_a_league_on_7_loudly(scratch, monkeypatch):
    """The runbook's rule: a season recorded on generation 7 is never played
    on another engine; with the switch off its games fail."""
    data = scratch
    _both_on(monkeypatch)
    _on_scale_2(data)
    write_schedule(data, 2026)
    _first_game(monkeypatch)
    assert stored_generation(data, 2026) == 7
    monkeypatch.delenv(GENERATION7_SWITCH_ENV)
    centers.clear_rating_center_cache()
    with pytest.raises(Exception, match="unknown engine generation 7"):
        _first_game(monkeypatch)
