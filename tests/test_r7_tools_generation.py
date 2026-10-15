"""Release 6b (the ball-flight step): engine generation 7 is the harness's.

Generation 7 is a DEVELOPMENT generation, introduced the way generation 6
was: its profile is in the package (``physics_sim/profiles/engine_7.json``)
and runs with ``--engine 7``; ``scripts/kpi_profiles/r7.json`` is the
harness-facing copy. It is generation 6's profile with each build stage's
values laid over it in order (``R7_STAGE_PROFILES``, kept so every value
can be traced to the stage that set it). No league season can be given it,
whatever the 8.0.0 operations switch says: the league side reads
``known_engine_generations()``, which never holds 7.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import physics_sim.engine_generation as generations
import scripts.build_engine7_profile as builder
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
from utils.rating_scale import GENERATION6_SWITCH_ENV

REPO = Path(__file__).resolve().parents[1]
REGISTRY_6 = REPO / "physics_sim" / "profiles" / "engine_6.json"
REGISTRY_7 = REPO / "physics_sim" / "profiles" / "engine_7.json"
HARNESS_COPY = REPO / "scripts" / "kpi_profiles" / "r7.json"
# The build stages of generation 7, in the order they are laid over
# generation 6 (a later stage may re-value an earlier stage's key):
# scripts/build_engine7_profile.py.
R7_STAGE_PROFILES = tuple(builder.stage_path(stage) for stage in builder.R7_STAGES)


def _text(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _generation_6_and_the_stages() -> dict:
    return builder.build()


# --- the profile ------------------------------------------------------------------


def test_generation_7_has_a_profile_in_the_package():
    assert generations.engine_profile_path(7) == REGISTRY_7
    assert REGISTRY_7.exists()
    assert 7 in generations.DEVELOPMENT_ENGINE_GENERATIONS
    assert 7 in generations.harness_engine_generations()
    payload = json.loads(REGISTRY_7.read_text(encoding="utf-8"))
    assert isinstance(payload, dict) and payload
    assert not [key for key in payload if key not in DEFAULT_TUNING]


def test_the_harness_copy_is_the_registry():
    assert _text(HARNESS_COPY) == _text(REGISTRY_7), (
        "scripts/kpi_profiles/r7.json and physics_sim/profiles/engine_7.json "
        "have diverged; they must be the same file"
    )
    assert kpis.load_tuning_overrides_file(HARNESS_COPY) == generations.engine_profile(
        7, development=True
    )


def test_generation_7_is_generation_6_with_the_stages():
    payload = json.loads(_text(REGISTRY_7))
    assert payload == _generation_6_and_the_stages()
    assert _text(REGISTRY_7).decode("utf-8") == builder.render(builder.build())
    profile_6 = json.loads(_text(REGISTRY_6))
    # Generation 6's keys keep their order (a stage re-values in place).
    assert list(payload)[: len(profile_6)] == list(profile_6)
    tuning = load_tuning(payload)
    for key, value in payload.items():
        if not isinstance(value, dict):
            assert tuning.get(key) == pytest.approx(float(value)), key
    # Every stage file is registered and read whole.
    for path in R7_STAGE_PROFILES:
        stage = json.loads(_text(path))
        assert stage and not [key for key in stage if key not in DEFAULT_TUNING]
    # Generation 6 itself is not touched by any of them.
    assert generations.engine_profile(6, development=True) == profile_6


def test_a_caller_cannot_poison_the_generation_7_profile():
    profile = generations.engine_profile(7, development=True)
    profile["swing_model"] = 99.0
    for table in (v for v in profile.values() if isinstance(v, dict)):
        table.clear()
    again = generations.engine_profile(7, development=True)
    assert again["swing_model"] == 1.0
    assert again == _generation_6_and_the_stages()


# --- the harness: --engine 7 ------------------------------------------------------


def test_engine_7_equals_the_r7_overrides_file():
    by_engine = kpis.resolve_run_overrides(engine=7)
    by_file = kpis.resolve_run_overrides(overrides_path=HARNESS_COPY)
    assert by_engine == by_file
    assert list(by_engine) == list(by_file)
    assert load_tuning(by_engine).values == load_tuning(by_file).values
    # The same as generation 6 with each stage's file laid on in order.
    by_stages = kpis.resolve_run_overrides(engine=6)
    for path in R7_STAGE_PROFILES:
        by_stages = {
            **by_stages, **kpis.load_tuning_overrides_file(path, base=by_stages)
        }
    assert load_tuning(by_engine).values == load_tuning(by_stages).values


def test_the_command_line_takes_engine_7(monkeypatch, capsys):
    captured = {}

    def fake_run_sim(games, seed, players_path, tuning_overrides, base_dir, **kwargs):
        captured["overrides"] = tuning_overrides
        raise KeyboardInterrupt

    monkeypatch.setattr(kpis, "run_sim", fake_run_sim)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "7"])
    with pytest.raises(KeyboardInterrupt):
        kpis.main()
    assert captured["overrides"] == generations.engine_profile(7, development=True)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "8"])
    with pytest.raises(SystemExit):
        kpis.main()
    assert "--engine" in capsys.readouterr().err


def test_generation_7_starts_with_generation_6s_gates():
    seven, six = kpis.ENGINE_GATES[7], kpis.ENGINE_GATES[6]
    for part in ("benchmarks", "drop", "pooled"):
        assert seven[part] == six[part], part
    # Separate objects: moving 7's gates cannot move 6's.
    saved_6 = copy.deepcopy(six)
    saved_7 = copy.deepcopy(seven)
    seven["tolerances"]["platoon_gap_woba"] = 99.0
    seven["drop"].append("nothing")
    try:
        assert kpis.ENGINE_GATES[6] == saved_6
    finally:
        kpis.ENGINE_GATES[7] = saved_7
    assert kpis.engine_gates_for(7)["benchmarks"] == kpis.engine_gates_for(6)["benchmarks"]


# --- no league is handed generation 7 ---------------------------------------------


@pytest.mark.parametrize("switch", ["", "1"])
def test_the_league_side_never_knows_generation_7(monkeypatch, switch):
    monkeypatch.setenv(GENERATION6_SWITCH_ENV, switch)
    assert 7 not in generations.known_engine_generations()
    assert generations.CURRENT_ENGINE_GENERATION == 5
    with pytest.raises(ValueError, match="unknown engine generation 7"):
        generations.engine_profile(7)
    with pytest.raises(ValueError, match="unknown engine generation 7"):
        generations.engine_defaults(7)


@pytest.mark.parametrize("asked", ["7", "8"])
def test_the_operations_switch_cannot_ask_for_generation_7(league, monkeypatch, asked):
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, asked)
    assert centers._configured_new_season_generation() == 5
    write_schedule(league, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert stored_generation(league, 2026) == 5


def test_a_stored_generation_7_is_not_carried_into_another_season():
    seasons = {"2025": {centers.ENGINE_GENERATION_KEY: 7}}
    assert centers._newest_stored_generation(seasons) == 4


def test_a_season_recorded_on_generation_7_fails_rather_than_plays(league):
    from services.league_tuning import league_tuning_overrides

    with pytest.raises(ValueError, match="unknown engine generation 7"):
        league_tuning_overrides(generation=7)
