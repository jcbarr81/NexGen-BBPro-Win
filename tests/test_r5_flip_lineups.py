"""Release 5 switch-on: where the lineup auto-fill gets its tuning.

Two findings of the platoon review, fixed with the tuning assembly:

(a) The auto-fill took its tuning from the ACTIVE league's stored file, not
    from the game or the players file it was given: a game simulated with a
    tuning profile rebuilt a broken lineup with the profile OFF, and an
    auto-fill on explicit fixture paths changed with whatever a scratch
    active league had stored. A caller that has the game's tuning now
    passes it, and ``platoon_tuning`` reads the league of the data dir it
    is handed.
(b) Reading the overrides file ran the one-time slider migration and WROTE
    the file from a lineup action. A lineup read never writes a tuning
    file; a conversion it needs is applied in memory.
"""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

import pytest

import physics_sim.engine as engine
import services.physics_tuning_settings as S
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    CALIBRATION,
    NEW_SEASON_ENGINE_ENV,
    league,
    team_ids,
    write_schedule,
)
from utils import lineup_autofill
from utils.lineup_autofill import auto_fill_lineup_for_team, platoon_tuning

REPO = Path(__file__).resolve().parents[1]
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"
# Overrides that turn the platoon terms on and would re-rank hitters.
PLATOON_ON = {
    "platoon_vl_center_enabled": 1.0,
    "handedness_balance_strength": 1.0,
    "handedness_rhb_scale": 0.2,
    "platoon_power_after_knee": 1.0,
}


def _paths(base: Path, lineup_dir: Path | None = None) -> dict:
    return {
        "players_file": str(base / "players.csv"),
        "roster_dir": str(base / "rosters"),
        "lineup_dir": str(lineup_dir or base / "lineups"),
    }


def _fixture_copy(tmp_path: Path) -> Path:
    """data/calibration copied where a test may break and rebuild lineups."""
    from tests.r5_flip_support import copy_fixture

    return copy_fixture(CALIBRATION, tmp_path / "fixture")


def _store(data: Path, overrides: dict) -> str:
    path = data / S.TUNING_OVERRIDES_FILENAME
    path.write_text(json.dumps(overrides), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _spy_on_fill(monkeypatch) -> list:
    calls: list = []
    real = engine.auto_fill_lineup_for_team

    def spy(team_id, **kwargs):
        calls.append(kwargs)
        return real(team_id, **kwargs)

    monkeypatch.setattr(engine, "auto_fill_lineup_for_team", spy)
    return calls


# --- (a) the game's tuning, or the league of the data dir -------------------------


def test_a_game_rebuilds_a_broken_lineup_with_its_own_tuning(
    league, tmp_path, monkeypatch
):
    """The reviewer's reproduction: a profile on, a lineup missing."""
    _store(league, {"hr_scale": 1.2})  # the active league: none of the game's
    fixture = _fixture_copy(tmp_path)
    for hand in ("lhp", "rhp"):
        (fixture / "lineups" / f"CAL01_vs_{hand}.csv").unlink()
    calls = _spy_on_fill(monkeypatch)
    # A generation 5 game is handed its league's centres (it refuses to
    # play league-relative ratings without them).
    game_overrides = {
        **engine_profile(5),
        **centers.active_rating_centers(fixture),
        "hitter_vl_center_l": 61.0,
    }
    engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02",
        players_path=fixture / "players.csv", base_dir=fixture, seed=3,
        tuning_overrides=game_overrides,
    )
    assert len(calls) == 1
    tuning = calls[0]["tuning"]
    assert tuning.values == load_tuning(game_overrides).values
    assert tuning.get("platoon_vl_center_enabled") == 1.0
    assert tuning.get("hitter_vl_center_l") == 61.0
    # The game's own value (the profile's, or the default), not the league's.
    assert tuning.get("hr_scale") == engine_profile(5).get(
        "hr_scale", DEFAULT_TUNING["hr_scale"]
    )
    assert tuning.get("hr_scale") != 1.2
    assert (fixture / "lineups" / "CAL01_vs_rhp.csv").exists()


def test_a_game_on_the_defaults_fills_with_the_defaults(league, tmp_path, monkeypatch):
    """No overrides passed means the game is played on DEFAULT_TUNING, so
    that is what a lineup rebuilt for it is scored with -- whatever the
    active league has stored."""
    _store(league, PLATOON_ON)
    fixture = _fixture_copy(tmp_path)
    (fixture / "lineups" / "CAL02_vs_lhp.csv").unlink()
    (fixture / "lineups" / "CAL02_vs_rhp.csv").unlink()
    calls = _spy_on_fill(monkeypatch)
    engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02",
        players_path=fixture / "players.csv", base_dir=fixture, seed=3,
    )
    assert len(calls) == 1
    assert calls[0]["tuning"].values == load_tuning().values


def test_auto_fill_on_fixture_paths_ignores_the_active_league(league, tmp_path):
    """The second reproduction: explicit fixture paths, a scratch active
    league with overrides stored. The club is the platoon tests' own: read
    with the centred ``vl`` its right-handed first baseman (A) starts
    against a left-hander, on the defaults the left-handed one (B)."""
    from tests.test_r5_platoon import _club, _first_baseman, _row, _write_league

    rows = _club(tilt_left=12, tilt_right=-12)
    rows += [_row(f"XL{i}", "LF", bats="L", vl=62, ch=30, ph=30) for i in range(8)]
    rows += [_row(f"XR{i}", "RF", bats="R", vl=38, ch=30, ph=30) for i in range(6)]
    fixture = tmp_path / "fixture"
    paths = _write_league(fixture, rows)
    assert platoon_tuning(fixture).values == load_tuning().values
    assert _first_baseman(paths) == "B"
    # The switch that would change the answer, where the bug used to read it.
    centred = {"platoon_vl_center_enabled": 1.0}
    assert _first_baseman(
        paths, tuning=load_tuning({**centred, **centers.active_rating_centers(fixture)})
    ) == "A"

    write_schedule(league, 2027)  # the active league: generation 5 ...
    _store(league, {**centred, "handedness_rhb_scale": 0.2})  # ... and overrides
    assert centers.league_engine_generation(store=False) == 5
    assert platoon_tuning().get("handedness_rhb_scale") == 0.2  # the league's own
    assert platoon_tuning().get("platoon_vl_center_enabled") == 1.0
    # The fixture is read as what it is: no league, the engine defaults.
    assert platoon_tuning(fixture).values == load_tuning().values
    assert _first_baseman(paths) == "B"
    assert not (fixture / S.TUNING_OVERRIDES_FILENAME).exists()
    # Its OWN stored overrides are what decide for it.
    _store(fixture, centred)
    assert _first_baseman(paths) == "A"


def test_default_tuning_lineups_are_what_they_were(tmp_path, monkeypatch):
    """With default tuning the chosen lineups do not move: resolving the
    league of a fixture gives exactly the engine defaults, for every club,
    pitcher hand and strategy profile -- while the ACTIVE league (a twin of
    the fixture, so the roster loader knows its players) is on generation 5
    with platoon overrides stored."""
    from services.team_strategy_profiles import STRATEGY_PROFILES
    from tests.r5_flip_support import copy_fixture, make_league
    from utils import path_utils

    active = make_league(tmp_path, monkeypatch, source=CALIBRATION_LEAGUE)
    try:
        write_schedule(active, 2027)
        _store(active, PLATOON_ON)
        assert platoon_tuning().get("handedness_rhb_scale") == 0.2
        fixture = copy_fixture(CALIBRATION_LEAGUE, tmp_path / "fixture_league")
        teams = team_ids(fixture)[:16]
        assert len(teams) == 16
        assert platoon_tuning(fixture).values == load_tuning().values
        explicit = load_tuning()
        compared = differs_when_on = 0
        switched_on = load_tuning(
            {**PLATOON_ON, **centers.active_rating_centers(fixture)}
        )
        for team in teams:
            for profile in STRATEGY_PROFILES:
                for vs in ("lhp", "rhp", None):
                    kwargs = dict(
                        vs=vs, persist=False, strategy_profile=profile,
                        **_paths(fixture, tmp_path / "unused"),
                    )
                    lineup_autofill.load_roster.cache_clear()
                    resolved = auto_fill_lineup_for_team(team, **kwargs)
                    assert len(resolved) == 9
                    assert resolved == auto_fill_lineup_for_team(
                        team, tuning=explicit, **kwargs
                    ), (team, profile, vs)
                    differs_when_on += resolved != auto_fill_lineup_for_team(
                        team, tuning=switched_on, **kwargs
                    )
                    compared += 1
        assert compared == 16 * len(STRATEGY_PROFILES) * 3
        # The comparison has teeth: the active league's stored tuning would
        # have changed some of these lineups had it been read.
        assert differs_when_on > 0
    finally:
        path_utils._REQUEST_LEAGUE.set(None)
        path_utils._DATA_DIR_CACHE.clear()


def test_platoon_tuning_reads_the_league_it_is_handed(league, tmp_path, monkeypatch):
    other = tmp_path / "other_league"
    shutil.copytree(league, other)
    write_schedule(other, 2030)
    _store(other, {"hr_scale": 1.3})
    # The other league's season is on generation 5 (recorded in ITS file) ...
    assert centers.league_engine_generation(other) == 5
    # ... while the active one is a legacy season.
    write_schedule(league, 2026, played=3)
    _store(league, {"hr_scale": 0.8})
    assert centers.league_engine_generation() == 4

    handed = platoon_tuning(other)
    assert handed.get("hr_scale") == 1.3
    assert handed.get("platoon_vl_center_enabled") == 1.0  # its profile
    # Its platoon terms are on, so its own rating centres were read too.
    assert handed.get("hitter_bats_share_r") == centers.active_rating_centers(other)[
        "hitter_bats_share_r"
    ]
    active = platoon_tuning()
    assert active.get("hr_scale") == 0.8
    assert active.get("platoon_vl_center_enabled") == 0.0
    assert platoon_tuning(league).values == active.values


def test_the_default_game_state_scores_with_the_players_league(league, monkeypatch):
    from utils import lineup_loader

    seen = []
    real = lineup_autofill.platoon_tuning

    def spy(data_dir=None):
        seen.append(data_dir)
        return real(data_dir)

    monkeypatch.setattr(lineup_autofill, "platoon_tuning", spy)
    lineup_loader._build_default_lists(
        "CAL01", str(league / "players.csv"), str(league / "rosters")
    )
    assert [Path(p).resolve() for p in seen] == [league.resolve()]


def test_the_harness_and_the_fixture_generator_pass_their_tuning(monkeypatch):
    import scripts.generate_league_fixture as generator
    import scripts.physics_sim_season_kpis as kpis

    seen = {}
    monkeypatch.setattr(
        kpis, "auto_fill_lineup_for_team",
        lambda team_id, **kwargs: seen.update(kwargs),
    )
    marker = load_tuning({"hr_scale": 1.5})
    kpis._ensure_team_files(
        "NOPE", players_path=CALIBRATION / "players.csv",
        base_dir=Path("no_such_base"), tuning=marker,
    )
    assert seen["tuning"] is marker
    source = inspect.getsource(kpis.main)
    assert "tuning=fill_tuning" in source
    assert source.index("resolve_run_overrides(") < source.index("_ensure_team_files(")
    # The fixture is generated on the engine defaults, stated explicitly.
    source = inspect.getsource(generator)
    assert "fill_tuning = load_tuning()" in source
    assert "tuning=fill_tuning," in source


# --- (b) a lineup read never writes a tuning file ---------------------------------


def test_a_lineup_action_does_not_run_the_steal_migration(league):
    """The reported case: a pre-Release-4 file ``{"steal_freq_scale": 3.0}``
    was rewritten by an auto-fill alone."""
    write_schedule(league, 2026, played=3)
    path = league / S.TUNING_OVERRIDES_FILENAME
    before = _store(league, {"steal_freq_scale": 3.0})
    team = team_ids(league)[0]

    tuning = platoon_tuning()
    assert tuning.get("steal_freq_scale") == pytest.approx(1.0)  # in memory
    lineup_autofill.load_roster.cache_clear()
    lineup = auto_fill_lineup_for_team(team, persist=False, **_paths(league))
    assert len(lineup) == 9
    auto_fill_lineup_for_team(team, vs="lhp", **_paths(league))  # a saved one too
    assert path.read_text(encoding="utf-8") == before
    assert not (league / f"{S.TUNING_OVERRIDES_FILENAME}.lock").exists()
    assert not list(league.glob(f"{S.TUNING_OVERRIDES_FILENAME}.tmp.*"))

    # The same file IS migrated once something that plays games loads it.
    assert S.load_physics_tuning_overrides()["steal_freq_scale"] == pytest.approx(1.0)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {"steal_freq_scale": 1.0, S.STEAL_FREQ_REBASE_MARKER: True}


def test_a_lineup_action_does_not_run_the_slider_conversion(league):
    write_schedule(league, 2027)  # generation 5: legacy sliders are converted
    path = league / S.TUNING_OVERRIDES_FILENAME
    before = _store(league, {"walk_scale": 1.0, "k_scale": 0.6, "steal_freq_scale": 3.0})
    team = team_ids(league)[0]

    tuning = platoon_tuning()
    converted = S.convert_slider_overrides({"walk_scale": 1.0, "k_scale": 0.6})
    assert tuning.get("swing_walk_scale") == converted["swing_walk_scale"]
    assert tuning.get("contact_strikeout_scale") == converted["contact_strikeout_scale"]
    assert tuning.get("steal_freq_scale") == pytest.approx(1.0)
    assert tuning.get("swing_model") == 1.0
    lineup_autofill.load_roster.cache_clear()
    auto_fill_lineup_for_team(team, persist=False, **_paths(league))
    assert path.read_text(encoding="utf-8") == before
    # Nor does it fix the season's generation or its rating centres.
    assert not (league / centers.RATING_CENTERS_FILENAME).exists()


def test_a_read_without_migration_matches_the_migrating_read(tmp_path, monkeypatch):
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    monkeypatch.setattr(S, "TUNING_OVERRIDES_PATH", path)
    for generation in (4, 5):
        text = json.dumps({"steal_freq_scale": 4.5, "chase_scale": 0.9, "hr_scale": 1.1})
        path.write_text(text, encoding="utf-8")
        quiet = S.load_physics_tuning_overrides(generation, migrate=False)
        assert path.read_text(encoding="utf-8") == text
        assert S.get_physics_tuning_overrides(generation, migrate=False) == quiet
        assert S.load_physics_tuning_overrides(generation) == quiet
        assert path.read_text(encoding="utf-8") != text  # this one migrated it
