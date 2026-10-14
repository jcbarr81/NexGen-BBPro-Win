"""8.0.0 integration: the switch (r8-switch), development (r8-develop) and
display (r8-display) branches working together.

* The rollover runs its steps in the decided order -- archive, contracts,
  finances, the MOVE to rating scale 2, DEVELOPMENT of the scale 2 players,
  aging (paused for scale 1), retirements, promotions, the Hall of Fame,
  the reset -- so a league's first offseason on the new scale is developed.
* Every writer of ``players.csv`` holds the players-file lock
  (``utils.players_file_lock``) AND reports its write to the display
  caches (``utils.players_file_writes``).
"""

from __future__ import annotations

import json
import re

import pytest

from services import league_rating_centers as centers
from services import league_rollover
from tests.r8_switch_support import (
    CALIBRATION,
    CALIBRATION_LEAGUE,
    LEAGUE,
    REPO,
    SWITCH,
    _clear,
    game_tuning,
    make_league,
    news,
    read_rows,
    scale_log,
    stored_generation,
    switch_on,
    write_schedule,
)
from utils.rating_scale import players_file_rating_scale


@pytest.fixture(params=["calibration", "league"])
def scratch(request, tmp_path, monkeypatch):
    """A scratch league from the calibration fixture (no potentials: its
    players can only decline) or the league fixture (potentials: young
    players grow), active, the switch OFF."""
    from utils import path_utils

    source = CALIBRATION if request.param == "calibration" else CALIBRATION_LEAGUE
    monkeypatch.delenv(SWITCH, raising=False)
    data = make_league(tmp_path, monkeypatch, source=source)
    _clear()
    yield request.param, data
    _clear()
    path_utils._REQUEST_LEAGUE.set(None)
    path_utils._DATA_DIR_CACHE.clear()


def _full_rollover(year):
    from playbalance.season_context import SeasonContext

    ctx = SeasonContext.load()
    ctx.ensure_league(name="Scratch", league_id=LEAGUE)
    ctx.ensure_current_season(league_year=year)
    return league_rollover.LeagueRolloverService(ctx).archive_season(force=True)


def _wrap(monkeypatch, owner, name, order, label, probe=None):
    real = getattr(owner, name)

    def wrapper(*args, **kwargs):
        order.append((label, probe() if probe else None))
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, wrapper)


def test_the_switch_on_rollover_moves_then_develops_the_league(scratch, monkeypatch):
    import services.hall_of_fame as hall_of_fame
    import services.player_retirement as player_retirement
    import services.prospect_promotion as prospect_promotion

    fixture, data = scratch
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")  # a legacy season under way
    switch_on(monkeypatch)
    order = []
    scale = lambda: players_file_rating_scale(data / "players.csv")  # noqa: E731
    service = league_rollover.LeagueRolloverService
    _wrap(monkeypatch, league_rollover, "rollover_contracts_for_new_season", order, "contracts", scale)
    _wrap(monkeypatch, league_rollover, "run_offseason_financial_rollover", order, "finance", scale)
    _wrap(monkeypatch, service, "_move_to_full_rating_scale", order, "move", scale)
    _wrap(monkeypatch, service, "_apply_yearly_development", order, "development", scale)
    _wrap(monkeypatch, service, "_apply_yearly_aging", order, "aging", scale)
    _wrap(monkeypatch, player_retirement, "run_yearly_retirements", order, "retirements", scale)
    _wrap(monkeypatch, prospect_promotion, "run_yearly_promotions", order, "promotions", scale)
    _wrap(monkeypatch, hall_of_fame, "update_hall_of_fame", order, "hall_of_fame", scale)
    _wrap(monkeypatch, service, "_reset_active_state", order, "reset", scale)

    result = _full_rollover(2026)

    assert [label for label, _ in order] == [
        "contracts", "finance", "move", "development", "aging",
        "retirements", "promotions", "hall_of_fame", "reset",
    ]
    # Scale 1 until the move; scale 2 for every step after it.
    assert [s for _, s in order[:3]] == [1, 1, 1]
    assert all(s == 2 for _, s in order[3:])
    assert result.artifacts.get("rating_scale_move") == "converted"
    assert "development_error" not in result.artifacts
    # The same rollover developed the converted players.
    developed = json.loads(result.artifacts["development"])
    assert developed["season"] == 2027 and developed["players"] > 0
    assert developed["declined"] > 0
    if fixture == "league":
        assert developed["improved"] > 0  # young players with room to grow
    record = json.loads((data / "development_last.json").read_text(encoding="utf-8"))
    assert str(record.get("season")) == "2027"
    # The developed file is still all scale 2 in the scale 2 format.
    fields, rows = read_rows(data / "players.csv")
    assert "height_in" in fields and {r["rating_scale"] for r in rows} == {"2"}
    # One conversion, one announcement; the next season is generation 6.
    centers.clear_rating_center_cache()
    write_schedule(data, 2027)
    game_tuning(monkeypatch, "2027-04-01")
    assert stored_generation(data, 2027) == 6
    assert [e["event"] for e in scale_log(data)["events"]] == ["converted"]
    assert news(data).count("full 1-99 scale") == 1


def test_development_holds_the_lock_and_tells_the_display_caches(tmp_path, monkeypatch):
    from services import offseason_development as od
    from tests import rating_scale_support as support
    from utils.players_file_writes import players_file_write_count

    league = support.copy_league(support.FIXTURES["calibration_league"], tmp_path / "lg")
    fields, rows = support.read_player_rows(league / "players.csv")
    support.write_player_rows(league / "players.csv", fields, rows[:150])
    twin = tmp_path / "twin"
    support.write_stretched_twin(league, twin)
    path = twin / "players.csv"

    held = []
    real_lock = od.players_file_lock

    def lock(target, *args, **kwargs):
        held.append(str(target))
        return real_lock(target, *args, **kwargs)

    monkeypatch.setattr(od, "players_file_lock", lock)
    from services import training_history

    monkeypatch.setattr(training_history, "_reports_dir", lambda: tmp_path / "reports")
    monkeypatch.setattr(training_history, "_resolve_season_id", lambda: "test-2027")
    before = players_file_write_count(path)
    summary = od.run_offseason_development(season_year=2027, data_dir=twin)
    assert summary and summary["players"] > 0
    assert held == [str(path)]
    assert players_file_write_count(path) == before + 1


# Writers of players.csv: each holds the players-file lock and reports its
# write to the display caches. (path, why it is exempt from one of the two)
_LOCK_ONLY = {
    # Reads, merges and writes through save_players, which reports.
    "services/players_repository.py": "writes through save_players",
}
_COUNT_ONLY = {
    # The push copies the league's file to the remote mirror (no reader of
    # that path caches a display); the startup pull runs before the app
    # serves. The retried pull of a local players.csv takes the lock.
}
_DEFINITIONS = {"utils/players_file_lock.py", "utils/players_file_writes.py"}


def test_every_players_file_writer_locks_and_counts():
    lockers, counters = set(), set()
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("tests/", ".venv", "build/", "dist/")) or "/." in rel:
            continue
        if rel in _DEFINITIONS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bplayers_file_lock\(", text):
            lockers.add(rel)
        if re.search(r"\bnote_players_file_written\(", text):
            counters.add(rel)
    assert lockers - counters == set(_LOCK_ONLY), lockers - counters
    assert counters - lockers == set(_COUNT_ONLY), counters - lockers
    # The writers this release added or touched are on both lists.
    for rel in (
        "utils/player_writer.py",
        "services/draft_assignment.py",
        "services/rating_scale_migration.py",
        "services/offseason_development.py",
        "scripts/repair_injury_list_dates.py",
        "api/working_copy.py",
    ):
        assert rel in lockers and rel in counters, rel


def test_a_moved_league_reads_the_8_0_0_tutorial_on_its_own_scale():
    """Scale 2 (a league that moved with 8.0.0) sees the 8.0.0 steps and
    the three rating examples on the full scale, each step once; scale 1
    sees none of it (its whole payload is pinned in
    tests/test_rating_scale_display.py)."""
    from services.tutorials import tutorial_catalog

    def steps(scale):
        return tutorial_catalog(scale)["updated_engine"]["steps"]

    new = {
        "The 8.0.0 update: what your league got",
        "Ratings on the full 1 to 99 scale",
        "Pitching: stuff, Arm, Control and tired arms",
        "Power and doubles",
        "Fielding by position, out of position, errors",
        "Player development",
    }
    one, two = steps(1), steps(2)
    titles_two = [s["title"] for s in two]
    assert new <= set(titles_two) and not new & {s["title"] for s in one}
    assert len(titles_two) == len(set(titles_two))
    by_title = {s["title"]: s["body_html"] for s in two}
    one_by_title = {s["title"]: s["body_html"] for s in one}
    for title in ("Contact", "Eye and Control", "Catcher fielding and the strike zone"):
        assert by_title[title] != one_by_title[title], title
    assert "A 95 Contact hitter" in by_title["Contact"]
    assert "An 80 Contact hitter strikes out about 4%" in one_by_title["Contact"]
    assert "earlier scale" not in "".join(by_title.values())
