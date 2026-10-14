"""The rating scale is play-neutral: a league and its stretched twin play
the same baseball.

A twin (``tests/rating_scale_support.py``) is a fixture with every player
row re-expressed on rating scale 2. The engine reads ratings on its own
scale at the row boundary (``utils.rating_scale.engine_row``, called from
``physics_sim.models``, the rating centres and the KPI harness's readers),
so everything downstream must be identical, value for value:

* a KPI-harness season, on the legacy engine, on generation 5 and on the
  development generation 6 (its whole profile: the Release 6a pitching,
  power and fielding work, which read fielding and arm by position, the
  ground-ball centre and the manager's view of an arm), for each of the
  three fixtures;
* the rating centres;
* games through the LIVE path (``playbalance.game_runner``: the rotation
  tracker, saved lineups or the lineup auto-fill, stored tuning, the usage
  store), against the digests ``test_r5_live_path`` pins for the original.

With the un-stretch switched off the season is a different one, so none of
this can pass by reading nothing.

The season here is short (8 clubs, 28 games each) to keep the file near a
minute; the full 162-game comparison is run by hand before a release
(``docs/audits/2026-10-06-engine-ratings-audit/RATING_SCALE_DESIGN.md``,
section 2).
"""

from __future__ import annotations

import pytest

from tests import rating_scale_support as support
from tests import test_r5_live_path as live
from utils import rating_scale

TEAMS = 8
GAMES = 28
ENGINES = (None, 5, 6)


@pytest.fixture(scope="module")
def twins(tmp_path_factory):
    """name -> twin directory, each written once for the module."""

    root = tmp_path_factory.mktemp("twins")
    out = {}
    for name, fixture in support.FIXTURES.items():
        clips = support.write_stretched_twin(fixture, root / name)
        # An exact twin: no rating left 1-99 (a potential gap cut at 99 does
        # not reach the engine).
        assert [c for c in clips if c.kind == "rating"] == [], name
        out[name] = root / name
    return out


def test_a_twin_really_is_stretched(twins):
    for name, fixture in support.FIXTURES.items():
        _fields, original = support.read_player_rows(fixture / "players.csv")
        fields, twin = support.read_player_rows(twins[name] / "players.csv")
        assert fields[-1] == "rating_scale"
        assert {row["rating_scale"] for row in twin} == {"2"}
        assert [r["player_id"] for r in twin] == [r["player_id"] for r in original]
        moved = sum(
            1
            for before, after in zip(original, twin)
            for key in ("ch", "ph", "eye", "fa", "arm", "control", "movement")
            if before.get(key) != after.get(key)
        )
        # Most rated values change; only those sitting on a pivot do not.
        assert moved > 2 * len(original), (name, moved)


@pytest.mark.parametrize(
    "engine", ENGINES, ids=["legacy", "generation5", "generation6"]
)
@pytest.mark.parametrize("name", sorted(support.FIXTURES))
def test_the_season_is_identical_on_a_stretched_twin(twins, name, engine):
    original = support.season_values(
        support.run_season(
            support.FIXTURES[name], games=GAMES, engine=engine, teams=TEAMS
        )
    )
    twin = support.season_values(
        support.run_season(twins[name], games=GAMES, engine=engine, teams=TEAMS)
    )
    assert len(original) > 3000  # every block of the summary is compared
    assert support.differences(original, twin) == []


def test_generation_6_is_not_generation_5_here():
    """The control for the generation 6 case above: its season is another
    one, so its twin had the generation 6 readers to get right."""

    fixture = support.FIXTURES["calibration"]
    five = support.season_values(
        support.run_season(fixture, games=GAMES, engine=5, teams=TEAMS)
    )
    six = support.season_values(
        support.run_season(fixture, games=GAMES, engine=6, teams=TEAMS)
    )
    assert len(support.differences(five, six)) > 500
    # The fielding work's metrics are live on generation 6.
    assert six["report_only.metrics.oaa_per_8pt_ss"] is not None


@pytest.mark.parametrize("name", sorted(support.FIXTURES))
def test_the_rating_centres_are_identical(twins, name):
    from services import league_rating_centers as centers

    fixture, twin = support.FIXTURES[name], twins[name]
    stored = centers.active_rating_centers(fixture)
    assert stored and centers.active_rating_centers(twin) == stored
    unstored = centers.unstored_rating_centers(fixture)
    assert unstored and centers.unstored_rating_centers(twin) == unstored
    assert centers.active_hitter_mean_speed(twin) == centers.active_hitter_mean_speed(
        fixture
    )
    # The workload rows the harness's Power table builds its staff from.
    before = centers.active_pitcher_workloads(fixture)
    after = centers.active_pitcher_workloads(twin)
    assert [w for _row, w in before] == [w for _row, w in after]
    for (row, _), (twin_row, _) in zip(before, after):
        for key in ("control", "movement", "arm", "fb", "endurance"):
            assert float(twin_row[key] or 0) == float(row[key] or 0), key


def test_without_the_unstretch_the_season_is_a_different_one(twins, monkeypatch):
    """The control: the same twin, read as if its rows were on scale 1."""

    import physics_sim.data_loader as data_loader
    import physics_sim.models as models
    from services import league_rating_centers as centers

    name = "calibration"
    original = support.season_values(
        support.run_season(support.FIXTURES[name], games=GAMES, teams=TEAMS)
    )
    monkeypatch.setattr(models, "engine_row", lambda row: row)
    monkeypatch.setattr(centers, "engine_row", lambda row: row)
    data_loader._load_players_by_id_cached.cache_clear()
    try:
        blind = support.season_values(
            support.run_season(twins[name], games=GAMES, teams=TEAMS)
        )
    finally:
        data_loader._load_players_by_id_cached.cache_clear()
    changed = support.differences(original, blind)
    assert len(changed) > 500
    # Stretched ratings played raw: a different run, strikeout and home-run
    # environment, not a rounding difference.
    for key, least in (
        ("metrics.runs_per_team_game", 0.05),
        ("metrics.k_pct", 0.005),
        ("metrics.hr_per_team_game", 0.05),
    ):
        assert abs(blind[key] - original[key]) > least, (key, blind[key])


def test_the_harness_readers_convert_too(twins, monkeypatch):
    """Engine and centres converted but the harness's own readers not: the
    games are the same, the rating-slope KPIs are not (design section 2)."""

    import scripts.kpi_extras as kpi_extras
    import scripts.physics_sim_season_kpis as kpis

    name = "calibration"
    original = support.season_values(
        support.run_season(support.FIXTURES[name], games=GAMES, teams=TEAMS)
    )

    def raw_rows(handle):
        import csv

        return csv.DictReader(handle)

    monkeypatch.setattr(kpis, "engine_rows", raw_rows)
    monkeypatch.setattr(kpi_extras, "engine_rows", raw_rows)
    half = support.season_values(
        support.run_season(twins[name], games=GAMES, teams=TEAMS)
    )
    changed = support.differences(original, half)
    assert changed, "the harness readers were not exercised"
    for key in (
        "metrics.runs_per_team_game",
        "metrics.k_pct",
        "metrics.hr_per_team_game",
    ):
        assert half[key] == original[key], key


# --- the live game path ----------------------------------------------------

def _twin_repo(tmp_path):
    """A stand-in repo root whose ``data/calibration_league`` is the twin:
    ``test_r5_live_path.build_league`` builds its scratch league from it."""

    repo = tmp_path / "twinrepo"
    clips = support.write_stretched_twin(
        support.FIXTURES["calibration_league"],
        repo / "data" / "calibration_league",
    )
    assert [c for c in clips if c.kind == "rating"] == []
    return repo


@pytest.mark.parametrize("mode,lineups", [("lineup_files", True), ("auto_fill", False)])
def test_live_games_are_identical_on_a_stretched_twin(tmp_path, mode, lineups):
    games = live.live_games(tmp_path / "league", _twin_repo(tmp_path), lineups=lineups)
    # The league these games were played in is on scale 2 ...
    data = tmp_path / "league" / "leagues" / live.LEAGUE / "data"
    assert rating_scale.players_file_rating_scale(data / "players.csv") == 2
    # ... and they are the games the original league plays: who started,
    # who batted where, every pitch, the score reported.
    assert live.game_digests(games) == live.PINNED[mode]


def test_live_tuning_and_centres_match_on_a_twin(tmp_path):
    original = live.live_games(tmp_path / "plain", lineups=True)
    twin = live.live_games(tmp_path / "twin", _twin_repo(tmp_path), lineups=True)
    assert [g["tuning_overrides"] for g in twin] == [
        g["tuning_overrides"] for g in original
    ]
    assert original[0]["tuning_overrides"]  # the centres were supplied


def test_live_games_differ_without_the_unstretch(tmp_path, monkeypatch):
    import physics_sim.data_loader as data_loader
    import physics_sim.models as models

    repo = _twin_repo(tmp_path)
    monkeypatch.setattr(models, "engine_row", lambda row: row)
    data_loader._load_players_by_id_cached.cache_clear()
    try:
        games = live.live_games(tmp_path / "league", repo, lineups=True)
    finally:
        data_loader._load_players_by_id_cached.cache_clear()
    assert live.game_digests(games) != live.PINNED["lineup_files"]
