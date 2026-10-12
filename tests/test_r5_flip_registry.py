"""Release 5 switch-on: the engine profile registry and the harness option.

The switched-on values of an engine generation live in ONE plain data file
in the package the backend image ships (``physics_sim/profiles/``), not in
``scripts/`` or ``data/``: an earlier bug in this project (box scores,
7.45.x) came from a file living in a folder the image excluded.
``scripts/kpi_profiles/r5.json`` is the harness-facing copy of generation 5
and must not drift from it.
"""

from __future__ import annotations

import fnmatch
import json
import math
from pathlib import Path

import pytest

import physics_sim.engine_generation as generations
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "physics_sim" / "profiles" / "engine_5.json"
HARNESS_COPY = REPO / "scripts" / "kpi_profiles" / "r5.json"
WORKFLOW = REPO / ".github" / "workflows" / "physics_sim_kpi.yml"
# The switches of the four Release 5 areas: on in the profile, off by default.
SWITCHES = (
    "swing_model", "command_model", "umpire_model", "hbp_model", "ibb_model",
    "contact_model", "platoon_power_after_knee", "platoon_vl_center_enabled",
    "pitch_objective_fbo_requires_risp",
)


# --- one file, in the package, shipped -------------------------------------------


def test_the_registry_is_one_plain_file_in_the_package():
    assert generations.engine_profile_path(5) == REGISTRY
    assert REGISTRY.exists()
    assert generations.known_engine_generations() == (4, 5)
    assert generations.LEGACY_ENGINE_GENERATION == 4
    assert generations.CURRENT_ENGINE_GENERATION == 5
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(payload, dict) and payload
    # Plain data a person can overwrite: knob -> number, or a table of them.
    for key, value in payload.items():
        assert key in DEFAULT_TUNING, key
        if isinstance(value, dict):
            assert isinstance(DEFAULT_TUNING[key], dict), key
        else:
            assert isinstance(value, (int, float)) and math.isfinite(value), key


def _ignore_patterns(name: str) -> list[str]:
    path = REPO / name
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith(("#", "!"))
    ]


@pytest.mark.parametrize("ignore_file", (".dockerignore", ".gcloudignore"))
def test_the_image_ships_the_registry(ignore_file):
    """``COPY . .`` minus the ignore file is the image. No pattern may match
    the registry, its folder or the module that reads it."""
    patterns = _ignore_patterns(ignore_file)
    for shipped in (REGISTRY, REPO / "physics_sim" / "engine_generation.py"):
        relative = shipped.relative_to(REPO).as_posix()
        parts = relative.split("/")
        for pattern in patterns:
            anchored = pattern.startswith("/")
            body = pattern.strip("/")
            if pattern.endswith("/"):  # a directory
                prefixes = ["/".join(parts[:i]) for i in range(1, len(parts))]
                names = prefixes if anchored else prefixes + parts[:-1]
                assert not any(fnmatch.fnmatch(name, body) for name in names), (
                    f"{ignore_file} pattern {pattern!r} excludes {relative}"
                )
            else:
                names = [relative] if anchored else [relative, parts[-1]]
                assert not any(fnmatch.fnmatch(name, body) for name in names), (
                    f"{ignore_file} pattern {pattern!r} excludes {relative}"
                )


def test_the_dockerfile_copies_the_application_tree():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "\nCOPY . .\n" in dockerfile
    # data/ does NOT ship, which is why the registry is not kept there.
    assert "/data/" in _ignore_patterns(".dockerignore")


def test_the_harness_copy_is_the_registry():
    """The lead retunes the registry; this fails until r5.json is copied
    from it (or the other way round)."""
    registry = REGISTRY.read_bytes().replace(b"\r\n", b"\n")
    copy = HARNESS_COPY.read_bytes().replace(b"\r\n", b"\n")
    assert copy == registry, (
        "scripts/kpi_profiles/r5.json and physics_sim/profiles/engine_5.json "
        "have diverged; they must be the same file"
    )
    assert kpis.load_tuning_overrides_file(HARNESS_COPY) == generations.engine_profile(5)


# --- what a profile is ------------------------------------------------------------


def test_legacy_has_no_profile_and_the_defaults_did_not_move():
    assert generations.engine_profile(4) == {}
    assert generations.engine_profile(None) == {}
    assert generations.engine_profile("junk") == {}
    assert generations.engine_profile(1) == {}
    # The switch-on is the profile, not a change of DEFAULT_TUNING.
    for key in SWITCHES:
        assert DEFAULT_TUNING[key] == 0.0, key
    assert DEFAULT_TUNING["home_field_edge"] == 0.0
    assert DEFAULT_TUNING["reliever_fresh_bonus"] == 0.0
    assert generations.engine_defaults(4) == {
        key: float(value)
        for key, value in DEFAULT_TUNING.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def test_generation_5_switches_on_all_four_areas():
    profile = generations.engine_profile(5)
    for key in SWITCHES:
        assert profile[key] == 1.0, key
    assert profile["home_field_edge"] > 0.0
    assert profile["reliever_fresh_bonus"] > 0.0
    assert profile["tto_pass2_weight"] > 0.0
    assert profile["handedness_balance_strength"] == 1.0  # owner decision 5
    assert profile["foul_territory_scale"] == 0.0  # owner decision 8
    tuning = load_tuning(profile)
    for key, value in profile.items():
        assert tuning.values[key] == value, key
    defaults = generations.engine_defaults(5)
    assert defaults["swing_model"] == 1.0
    # A knob the profile leaves alone keeps the engine default; one it
    # sets (the run level is retuned for the new models) reads the profile.
    assert defaults["offense_scale"] == DEFAULT_TUNING["offense_scale"]
    assert defaults["hr_scale"] == profile.get("hr_scale", DEFAULT_TUNING["hr_scale"])


def test_a_table_knob_comes_back_whole():
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    tables = {k: v for k, v in raw.items() if isinstance(v, dict)}
    profile = generations.engine_profile(5)
    for key, entries in tables.items():
        assert set(profile[key]) == set(DEFAULT_TUNING[key]), key
        for name, value in entries.items():
            assert profile[key][name] == value
    # A caller may change what it gets without poisoning the next reader.
    profile["swing_model"] = 99.0
    for table in (v for v in profile.values() if isinstance(v, dict)):
        table.clear()
    assert generations.engine_profile(5)["swing_model"] == 1.0
    for key in tables:
        assert generations.engine_profile(5)[key]
    assert DEFAULT_TUNING["count_foul_scale"]["0-2"] == 1.2  # defaults untouched


@pytest.mark.parametrize(
    "content, message",
    [
        ('{"no_such_knob": 1}', "unknown tuning key"),
        ('{"swing_model": "on"}', "finite number"),
        ('{"swing_model": NaN}', "finite number"),
        ('{"count_foul_scale": 1.0}', "takes an object"),
        ('{"count_foul_scale": {"9-9": 1.0}}', "unknown entry"),
        ('{"count_foul_scale": {"0-2": Infinity}}', "finite number"),
        ("[1, 2]", "expected a JSON object"),
        ("{ not json", "cannot read JSON"),
    ],
)
def test_a_bad_profile_is_refused_loudly(tmp_path, content, message):
    path = tmp_path / "engine_5.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        generations.load_engine_profile_file(path)


def test_a_missing_or_unknown_profile_raises(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="unknown engine generation"):
        generations.engine_profile(6)
    monkeypatch.setattr(generations, "ENGINE_PROFILE_DIR", tmp_path)
    with pytest.raises(ValueError, match="missing"):
        generations.engine_profile(5)
    # The file is read again when it changes (a retune needs no restart).
    (tmp_path / "engine_5.json").write_text('{"swing_model": 1}', encoding="utf-8")
    assert generations.engine_profile(5) == {"swing_model": 1.0}
    (tmp_path / "engine_5.json").write_text(
        '{"swing_model": 1, "contact_model": 1}', encoding="utf-8"
    )
    assert generations.engine_profile(5) == {"swing_model": 1.0, "contact_model": 1.0}


# --- the harness: --engine N ------------------------------------------------------


def test_engine_5_equals_the_r5_overrides_file():
    by_engine = kpis.resolve_run_overrides(engine=5)
    by_file = kpis.resolve_run_overrides(overrides_path=HARNESS_COPY)
    assert by_engine == by_file
    assert list(by_engine) == list(by_file)
    assert load_tuning(by_engine).values == load_tuning(by_file).values


def test_the_default_run_is_the_legacy_engine():
    assert kpis.resolve_run_overrides() is None
    assert kpis.resolve_run_overrides(engine=4) is None
    assert kpis.resolve_run_overrides(disable_park_factors=True) == {
        "park_factor_scale": 0.0
    }


def test_tuning_overrides_stay_on_top_of_the_engine_profile(tmp_path):
    profile = generations.engine_profile(5)
    retune = tmp_path / "retune.json"
    retune.write_text(
        json.dumps({"home_field_edge": 0.5, "hr_scale": 1.0, "count_foul_scale": {"0-2": 1.1}}),
        encoding="utf-8",
    )
    merged = kpis.resolve_run_overrides(engine=5, overrides_path=retune)
    assert merged["home_field_edge"] == 0.5 != profile["home_field_edge"]
    assert merged["hr_scale"] == 1.0
    assert merged["swing_model"] == 1.0
    # A partial table goes over the PROFILE's table, not the default one.
    assert merged["count_foul_scale"] == {**profile["count_foul_scale"], "0-2": 1.1}
    assert profile["count_foul_scale"]["1-2"] != DEFAULT_TUNING["count_foul_scale"]["1-2"]
    # Without --engine the same file merges over the defaults, as before.
    alone = kpis.resolve_run_overrides(overrides_path=retune)
    assert alone["count_foul_scale"] == {**DEFAULT_TUNING["count_foul_scale"], "0-2": 1.1}
    assert "swing_model" not in alone
    with pytest.raises(ValueError, match="unknown tuning key"):
        bad = tmp_path / "bad.json"
        bad.write_text('{"nope": 1}', encoding="utf-8")
        kpis.resolve_run_overrides(engine=5, overrides_path=bad)


def test_the_command_line_takes_engine(monkeypatch, capsys):
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "7"])
    with pytest.raises(SystemExit):
        kpis.main()
    assert "--engine" in capsys.readouterr().err
    captured = {}

    def fake_run_sim(games, seed, players_path, tuning_overrides, base_dir, **kwargs):
        captured["overrides"] = tuning_overrides
        raise KeyboardInterrupt

    monkeypatch.setattr(kpis, "run_sim", fake_run_sim)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "5"])
    with pytest.raises(KeyboardInterrupt):
        kpis.main()
    assert captured["overrides"] == generations.engine_profile(5)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis"])
    with pytest.raises(KeyboardInterrupt):
        kpis.main()
    assert captured["overrides"] is None


def test_the_r5_gate_set():
    gates = kpis.GATE_SETS["r5"]
    assert {"k_pct", "bb_pct", "ibb_per_pa"} <= set(gates)
    assert kpis.GATE_SET_TOLERANCES["r5"] == {"ibb_per_pa": 0.001}
    assert kpis.GATE_SET_EXTRAS_TARGETS["r5"] == {"ibb_per_pa": 0.0025}
    tolerances = kpis.strict_tolerances_for("r5")
    targets = kpis.strict_extras_targets_for("r5")
    assert tolerances["ibb_per_pa"] == 0.001 and targets["ibb_per_pa"] == 0.0025
    # Only under the set: the legacy engine never issues an intentional walk.
    assert "ibb_per_pa" not in kpis.strict_tolerances_for(None)
    assert "ibb_per_pa" not in kpis.strict_tolerances_for("running")
    for key in gates:  # a listed gate without a tolerance would always fail
        assert key in tolerances, key


def test_the_ci_step_for_generation_5_is_not_blocking():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["physics-sim-kpis"]["steps"]
    engine_steps = [s for s in steps if "--engine 5" in s.get("run", "")]
    assert len(engine_steps) == 1
    step = engine_steps[0]
    # Not blocking until it has passed on the CI runner (which may roll a
    # different season than the machine the profile was tuned on).
    assert step.get("continue-on-error") is True
    # The full strict set against generation 5's own references
    # (ENGINE_GATES), not a subset.
    assert "--gate-set" not in step["run"] and "--strict" in step["run"]
    assert "kpi_profiles" not in step["run"]
    # The blocking steps still run the legacy engine: no --engine at all.
    for other in steps:
        if other is not step and "physics_sim_season_kpis.py" in other.get("run", ""):
            assert "--engine" not in other["run"]


def test_generation_5_is_gated_against_its_own_references():
    """``--engine 5 --strict`` judges the new engine by what it is built to."""
    gates = kpis.engine_gates_for(5)
    # Statcast's chase rate, not the figure the old swing model was tuned to.
    assert gates["benchmarks"] == {"o_swing_pct": 0.286}
    # Times through the order on starters only; the all-pitcher gap is out.
    assert gates["drop"] == ["tto_ops_gap"]
    assert gates["extras_targets"]["tto_ops_gap_starters"] == 0.05
    # The platoon tolerance Release 3 widened is restored.
    assert gates["tolerances"]["platoon_gap_woba"] == 0.006
    assert kpis.strict_tolerances_for(None)["platoon_gap_woba"] == 0.009
    # Swing rate at each of the 12 counts, intentional walks, the home edge.
    swing = [k for k in gates["tolerances"] if k.startswith("swing_rate_")]
    assert len(swing) == 12 and all(gates["tolerances"][k] == 0.05 for k in swing)
    assert gates["extras_targets"]["ibb_per_pa"] == 0.0025
    assert "home_minus_away_woba" in gates["tolerances"]
    assert "home_wpct" not in gates["tolerances"]  # read pooled, never per season
    # Every promoted gate has both a target and a tolerance.
    assert set(gates["extras_targets"]) <= set(gates["tolerances"])
    # The grid gate only when the grid ran.
    assert "matchup_k_log5_max_abs_resid" not in gates["tolerances"]
    assert "matchup_k_log5_max_abs_resid" in kpis.engine_gates_for(5, grid=True)["tolerances"]
    # The legacy engine is gated exactly as before.
    assert kpis.engine_gates_for(None) == {
        "benchmarks": {}, "drop": [], "tolerances": {}, "extras_targets": {},
    }
