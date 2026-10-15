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
    # No second conversion; its own news item, once.
    assert scale_log(data)["events"] == events
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


def test_the_rollover_converts_onto_generation_7_and_tells_once(scratch, monkeypatch):
    data = scratch
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")  # a legacy season under way
    _both_on(monkeypatch)
    assert centers.move_league_at_rollover(data, 2027) == "converted"
    (event,) = scale_log(data)["events"]
    assert event["engine_generation"] == 7 and event["season"] == "2027"
    archive_a_season(data)
    (data / "season_progress.json").unlink()  # the rollover rebuilds it
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    _first_game(monkeypatch, 2027)
    assert stored_generation(data, 2027) == 7
    feed = news(data)
    assert feed.count(BALLFLIGHT_ENGINE_TEXT) == 1 and LEAD not in feed


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
