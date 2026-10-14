"""Release 6a (tooling): engine generation 6 exists for the KPI harness only.

Generation 6 is being built. Its profile is in the package next to
generation 5's, starts as generation 5's values exactly and can be run with
``--engine 6``; ``scripts/kpi_profiles/r6.json`` is the harness-facing copy.
No league season may be given it yet: the league side goes on reading
``known_engine_generations()``, which does not hold it, so a new season
still starts on generation 5 whatever the operations switch says.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import physics_sim.engine_generation as generations
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    NEW_SEASON_ENGINE_ENV,
    game_tuning,
    league,
    stored_generation,
    write_schedule,
)

REPO = Path(__file__).resolve().parents[1]
REGISTRY_5 = REPO / "physics_sim" / "profiles" / "engine_5.json"
REGISTRY_6 = REPO / "physics_sim" / "profiles" / "engine_6.json"
HARNESS_COPY = REPO / "scripts" / "kpi_profiles" / "r6.json"


def _text(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


# --- the profile ------------------------------------------------------------------


def test_generation_6_has_a_profile_in_the_package():
    assert generations.engine_profile_path(6) == REGISTRY_6
    assert REGISTRY_6.exists()
    assert generations.DEVELOPMENT_ENGINE_GENERATIONS == (6,)
    assert generations.harness_engine_generations() == (4, 5, 6)
    payload = json.loads(REGISTRY_6.read_text(encoding="utf-8"))
    assert isinstance(payload, dict) and payload
    # TuningConfig.from_overrides drops an unregistered key without a word.
    assert not [key for key in payload if key not in DEFAULT_TUNING]


def test_the_harness_copy_is_the_registry():
    """A retune of one must be copied to the other."""
    assert _text(HARNESS_COPY) == _text(REGISTRY_6), (
        "scripts/kpi_profiles/r6.json and physics_sim/profiles/engine_6.json "
        "have diverged; they must be the same file"
    )
    assert kpis.load_tuning_overrides_file(HARNESS_COPY) == generations.engine_profile(
        6, development=True
    )


def test_generation_6_starts_as_generation_5():
    """Until the Release 6 build switches something on. When this fails
    because generation 6 moved on purpose, replace it with the test of what
    generation 6 switches on; generation 5 itself must not have moved."""
    profile_6 = generations.engine_profile(6, development=True)
    profile_5 = generations.engine_profile(5)
    assert profile_6 == profile_5
    assert list(profile_6) == list(profile_5)
    assert load_tuning(profile_6).values == load_tuning(profile_5).values
    assert generations.engine_defaults(6, development=True) == (
        generations.engine_defaults(5)
    )
    # The profile file is plain data and may be reformatted; its values may not.
    assert json.loads(_text(REGISTRY_6)) == json.loads(_text(REGISTRY_5))


def test_a_caller_cannot_poison_the_generation_6_profile():
    profile = generations.engine_profile(6, development=True)
    profile["swing_model"] = 99.0
    for table in (v for v in profile.values() if isinstance(v, dict)):
        table.clear()
    again = generations.engine_profile(6, development=True)
    assert again["swing_model"] == 1.0
    assert again == generations.engine_profile(5)


# --- the harness: --engine 6 ------------------------------------------------------


def test_engine_6_equals_the_r6_overrides_file_and_engine_5():
    by_engine = kpis.resolve_run_overrides(engine=6)
    by_file = kpis.resolve_run_overrides(overrides_path=HARNESS_COPY)
    assert by_engine == by_file
    assert list(by_engine) == list(by_file)
    assert by_engine == kpis.resolve_run_overrides(engine=5)
    assert load_tuning(by_engine).values == load_tuning(by_file).values


def test_the_command_line_takes_engine_6(monkeypatch, capsys):
    captured = {}

    def fake_run_sim(games, seed, players_path, tuning_overrides, base_dir, **kwargs):
        captured["overrides"] = tuning_overrides
        raise KeyboardInterrupt

    monkeypatch.setattr(kpis, "run_sim", fake_run_sim)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "6"])
    with pytest.raises(KeyboardInterrupt):
        kpis.main()
    assert captured["overrides"] == generations.engine_profile(5)
    # A generation nobody is building is still refused.
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "7"])
    with pytest.raises(SystemExit):
        kpis.main()
    assert "--engine" in capsys.readouterr().err


def test_tuning_overrides_stay_on_top_of_the_generation_6_profile(tmp_path):
    retune = tmp_path / "retune.json"
    retune.write_text(
        json.dumps({"hr_scale": 1.0, "count_foul_scale": {"0-2": 1.1}}),
        encoding="utf-8",
    )
    profile = generations.engine_profile(6, development=True)
    merged = kpis.resolve_run_overrides(engine=6, overrides_path=retune)
    assert merged["hr_scale"] == 1.0 != profile["hr_scale"]
    assert merged["swing_model"] == 1.0
    assert merged["count_foul_scale"] == {**profile["count_foul_scale"], "0-2": 1.1}


def test_generation_6_is_gated_as_generation_5_for_now():
    assert kpis.ENGINE_GATES[6] == kpis.ENGINE_GATES[5]
    assert kpis.engine_gates_for(6) == kpis.engine_gates_for(5)
    assert kpis.engine_gates_for(6, grid=True) == kpis.engine_gates_for(5, grid=True)
    # A copy, so the Release 6 build can move its gates without moving 5's.
    snapshot = copy.deepcopy(kpis.ENGINE_GATES[5])
    kpis.ENGINE_GATES[6]["tolerances"]["platoon_gap_woba"] = 99.0
    kpis.ENGINE_GATES[6]["drop"].append("nothing")
    try:
        assert kpis.ENGINE_GATES[5] == snapshot
    finally:
        kpis.ENGINE_GATES[6] = copy.deepcopy(snapshot)


# --- no league is handed generation 6 ---------------------------------------------


def test_the_league_side_does_not_know_generation_6():
    assert generations.known_engine_generations() == (4, 5)
    assert generations.CURRENT_ENGINE_GENERATION == 5
    assert 6 not in generations.known_engine_generations()
    # Without the harness's flag the profile is not handed out at all:
    # every league path (game runner, watch-a-game, league_tuning, the
    # tuning API's defaults) calls it this way.
    with pytest.raises(ValueError, match="unknown engine generation 6"):
        generations.engine_profile(6)
    with pytest.raises(ValueError, match="unknown engine generation 6"):
        generations.engine_defaults(6)
    with pytest.raises(ValueError, match="unknown engine generation 7"):
        generations.engine_profile(7, development=True)


def test_a_new_season_still_starts_on_generation_5(league, monkeypatch):
    # Being created, then with a schedule and no game played.
    assert centers._new_season_generation(league) == 5
    assert centers.league_engine_generation() == 5
    write_schedule(league, 2026)
    assert centers._new_season_generation(league) == 5
    assert centers._new_season_generation(league, {}) == 5
    assert centers.league_engine_generation(store=False) == 5
    tuning = game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(league, 2026) == 5
    assert centers.recorded_league_engine_generation() == 5
    # The season's game tuning is generation 5's profile (6 equals it today,
    # so the number on record is what tells them apart).
    for key, value in generations.engine_profile(5).items():
        assert tuning[key] == value, key


@pytest.mark.parametrize("asked", ["6", "7", "banana"])
def test_the_operations_switch_cannot_ask_for_generation_6(
    league, monkeypatch, asked
):
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, asked)
    assert centers._configured_new_season_generation() == 5
    assert centers._new_season_generation(league) == 5
    write_schedule(league, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(league, 2026) == 5


def test_a_stored_generation_6_is_not_carried_into_another_season(league):
    """A season under way with no entry keeps the newest stored season's
    generation only if it is one a league can be on."""
    seasons = {"2025": {centers.ENGINE_GENERATION_KEY: 6}}
    assert centers._newest_stored_generation(seasons) == 4
    seasons = {"2025": {centers.ENGINE_GENERATION_KEY: 5}}
    assert centers._newest_stored_generation(seasons) == 5


def test_a_season_recorded_on_generation_6_fails_rather_than_plays(league):
    """Nothing writes such a record; if one appeared (a hand edit, a file
    from a development build), a game must not be played on a guess."""
    from services.league_tuning import league_tuning_overrides

    with pytest.raises(ValueError, match="unknown engine generation 6"):
        league_tuning_overrides(generation=6)
    assert league_tuning_overrides(generation=5, store=False)["swing_model"] == 1.0
