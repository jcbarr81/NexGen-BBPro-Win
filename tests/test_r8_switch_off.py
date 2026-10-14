"""8.0.0 switch OFF (this branch's default): nothing changes anywhere.

No league is given generation 6, none is converted to rating scale 2, a new
league is generated on scale 1, and every file a season start writes is
what 7.51 writes. The switch is ``utils.rating_scale.GENERATION6_SWITCH_ENV``.
"""

from __future__ import annotations

import pytest

import physics_sim.engine_generation as generations
from services import league_rating_centers as centers
from services import rating_scale_migration as migration
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    SWITCH,
    archive_a_season,
    game_tuning,
    news,
    read_rows,
    scratch,
    stored_generation,
    switch_off,
    switch_on,
    write_schedule,
)
from utils import rating_scale


def test_the_switch_is_off_unless_the_environment_says_on(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    assert not rating_scale.generation6_switch_on()
    for value in ("", "0", "off", "false", "2", "banana"):
        monkeypatch.setenv(SWITCH, value)
        assert not rating_scale.generation6_switch_on(), value
    for value in ("1", "on", "ON", "true", "yes", " 1 "):
        monkeypatch.setenv(SWITCH, value)
        assert rating_scale.generation6_switch_on(), value


def test_off_the_league_side_does_not_know_generation_6(monkeypatch):
    switch_off(monkeypatch)
    assert generations.known_engine_generations() == (4, 5)
    assert generations.harness_engine_generations() == (4, 5, 6)
    assert generations.CURRENT_ENGINE_GENERATION == 5
    with pytest.raises(ValueError, match="unknown engine generation 6"):
        generations.engine_profile(6)
    assert rating_scale.generated_rating_scale() == 1
    # On, generation 6 is a generation a season may be played on.
    switch_on(monkeypatch)
    assert generations.known_engine_generations() == (4, 5, 6)
    assert generations.harness_engine_generations() == (4, 5, 6)
    assert generations.engine_profile(6) == generations.engine_profile(6, development=True)


def test_off_a_new_season_starts_on_generation_5_and_nothing_is_converted(
    scratch, monkeypatch
):
    data = scratch
    archive_a_season(data)
    original = (data / "players.csv").read_bytes()
    # Even a league listed for the re-spread is not touched.
    monkeypatch.setenv(migration.RESPREAD_LEAGUES_ENV, "r5flip")
    assert centers._new_season_generation(data) == 5
    assert centers._configured_new_season_generation() == 5
    write_schedule(data, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    assert not (data / "rating_scale.json").exists()
    assert not list(data.glob("players.scale1.*"))
    # The 7.51 news item, and only it.
    assert news(data).count(centers.ENGINE_SWITCH_NEWS) == 1
    assert "full 1-99 scale" not in news(data)


def test_off_the_operations_hold_cannot_ask_for_generation_6(scratch, monkeypatch):
    data = scratch
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "6")
    assert centers._configured_new_season_generation() == 5
    write_schedule(data, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(data, 2026) == 5


def test_off_a_league_already_on_scale_2_plays_generation_5(scratch, monkeypatch):
    """Turned off after a league was created on scale 2: its next season is
    not moved anywhere; scale 2 plays correctly on generation 5."""
    data = scratch
    fields, rows = read_rows(data / "players.csv")
    migration._write_players(
        data / "players.csv", fields, [rating_scale.stretch_row(r, 2)[0] for r in rows]
    )
    converted = (data / "players.csv").read_bytes()
    write_schedule(data, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == converted


def test_off_the_conversion_hooks_are_never_reached(scratch, monkeypatch):
    data = scratch

    def boom(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("conversion reached with the switch off")

    for name in ("convert_league", "repair_league", "move_blocker", "post_refusal"):
        monkeypatch.setattr(migration, name, boom)
    write_schedule(data, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    game_tuning(monkeypatch, "2026-04-02")
    assert centers.league_engine_generation(store=False) == 5
