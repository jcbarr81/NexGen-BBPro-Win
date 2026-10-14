"""8.0.0: with the switch on, a league moves to rating scale 2 at its
ROLLOVER (``services.league_rollover``), before the offseason's development
step, and its next season starts on generation 6; a league that reaches a
new season without a rollover still moves at that season's first game."""

from __future__ import annotations

from services import league_rating_centers as centers
from services import league_rollover
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    LEAGUE,
    archive_a_season,
    clip_an_active_player,
    game_tuning,
    news,
    scale_log,
    scratch,
    stored_generation,
    switch_on,
    write_schedule,
)
from utils.rating_scale import players_file_rating_scale


def _full_rollover(data, year):
    """The product's whole rollover of season ``year`` (archive, contracts,
    finances, the move, aging, retirements, promotions, reset)."""
    from playbalance.season_context import SeasonContext

    ctx = SeasonContext.load()
    ctx.ensure_league(name="Scratch", league_id=LEAGUE)
    ctx.ensure_current_season(league_year=year)
    return league_rollover.LeagueRolloverService(ctx).archive_season(force=True)


def test_the_rollover_moves_the_league_before_the_offseason_steps(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")  # a legacy season under way
    switch_on(monkeypatch)
    order = []
    real_move = league_rollover.LeagueRolloverService._move_to_full_rating_scale
    real_aging = league_rollover.LeagueRolloverService._apply_yearly_aging

    def move(self, year):
        order.append(("move", year))
        return real_move(self, year)

    def aging(self):
        order.append(("aging", players_file_rating_scale(data / "players.csv")))
        return real_aging(self)

    monkeypatch.setattr(league_rollover.LeagueRolloverService, "_move_to_full_rating_scale", move)
    monkeypatch.setattr(league_rollover.LeagueRolloverService, "_apply_yearly_aging", aging)
    result = _full_rollover(data, 2026)
    assert result.artifacts.get("rating_scale_move") == "converted"
    # The move ran first, and the players were on scale 2 for every later
    # offseason step (r8-develop puts its development step at this point).
    assert order[0] == ("move", 2027) and order[1] == ("aging", 2)
    assert (data / "players.scale1.2027.csv").read_bytes() == original
    (event,) = scale_log(data)["events"]
    assert event["event"] == "converted" and event["season"] == "2027"
    assert "full 1-99 scale" in news(data)
    # The next season starts on generation 6 and nothing converts again.
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    game_tuning(monkeypatch, "2027-04-01")
    assert stored_generation(data, 2027) == 6
    assert [e["event"] for e in scale_log(data)["events"]] == ["converted"]
    assert news(data).count("full 1-99 scale") == 1


def test_a_refusal_at_the_rollover_is_told_once(scratch, monkeypatch):
    data = scratch
    clip_an_active_player(data)
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")
    switch_on(monkeypatch)
    assert centers.move_league_at_rollover(data, 2027) == "refused"
    archive_a_season(data)
    # (The rollover rebuilds season_progress.json: no witness.)
    (data / "season_progress.json").unlink()
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    game_tuning(monkeypatch, "2027-04-01")
    assert stored_generation(data, 2027) == 5
    refused = [e for e in scale_log(data)["events"] if e["event"] == "refused"]
    assert len(refused) == 1 and refused[0]["season"] == "2027"
    assert news(data).count("[commissioner]") == 1


def test_off_or_held_the_rollover_does_nothing(scratch, monkeypatch):
    data = scratch
    original = (data / "players.csv").read_bytes()
    assert centers.move_league_at_rollover(data, 2027) is None  # switch off
    switch_on(monkeypatch)
    monkeypatch.setenv(centers.NEW_SEASON_ENGINE_ENV, "5")
    assert centers.move_league_at_rollover(data, 2027) is None
    assert (data / "players.csv").read_bytes() == original
    assert not (data / "rating_scale.json").exists()
