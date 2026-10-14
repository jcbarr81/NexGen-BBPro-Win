"""Release 6a (tooling): engine generation 6 exists for the KPI harness only.

Generation 6 is being built. Its profile is in the package next to
generation 5's and can be run with ``--engine 6``;
``scripts/kpi_profiles/r6.json`` is the harness-facing copy. Since the
Release 6a integration it is generation 5's values with the three engine
areas' values laid over them (``scripts/kpi_profiles/r6_pitching.json``,
``r6_power.json``, ``r6_fielding.json``, kept for reference; no key is set
by two of them), then the joint retune's values over those
(``scripts/kpi_profiles/r6_retune.json``: the BABIP level, and the range
slopes re-fitted to it so a fielding point is worth the outs it was), and
it is gated as generation 5 plus the areas' gates.
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
AREA_PROFILES = tuple(
    REPO / "scripts" / "kpi_profiles" / f"r6_{area}.json"
    for area in ("pitching", "power", "fielding")
)
# The joint retune of the three areas together: it may set a key generation
# 5 or an area already set (in place), never a new one.
RETUNE_PROFILE = REPO / "scripts" / "kpi_profiles" / "r6_retune.json"


def _generation_5_and_the_areas() -> dict:
    """Generation 5's profile with each area's file, then the joint
    retune's, laid over it."""
    expected = json.loads(_text(REGISTRY_5))
    for path in AREA_PROFILES + (RETUNE_PROFILE,):
        expected.update(json.loads(_text(path)))
    return expected


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


def test_generation_6_is_generation_5_with_the_three_areas():
    """The integration's profile: generation 5's keys in their order (an
    area's retune replaces a value in place), then each area's own keys. No
    key is set by two areas, so the order the files are laid in does not
    matter."""
    areas = [json.loads(_text(path)) for path in AREA_PROFILES]
    for i, first in enumerate(areas):
        for second in areas[i + 1:]:
            assert not set(first) & set(second)
    payload = json.loads(_text(REGISTRY_6))
    assert payload == _generation_5_and_the_areas()
    profile_5 = json.loads(_text(REGISTRY_5))
    assert list(payload)[: len(profile_5)] == list(profile_5)
    # Every area's value is the generation's, and reaches the engine (a
    # registered key: TuningConfig.from_overrides drops any other).
    assert generations.engine_profile(6, development=True) == payload
    tuning = load_tuning(payload)
    retune = json.loads(_text(RETUNE_PROFILE))
    for area in areas + [retune]:
        for key, value in area.items():
            if key in retune and area is not retune:
                continue
            if not isinstance(value, dict):
                assert tuning.get(key) == pytest.approx(float(value)), key
    # The retune only re-values keys generation 5 or an area set.
    assert set(retune) <= set(profile_5).union(*areas)
    # Generation 5 itself is not touched by it.
    assert generations.engine_profile(5) == profile_5
    assert generations.engine_defaults(6, development=True) != (
        generations.engine_defaults(5)
    )


def test_a_caller_cannot_poison_the_generation_6_profile():
    profile = generations.engine_profile(6, development=True)
    profile["swing_model"] = 99.0
    for table in (v for v in profile.values() if isinstance(v, dict)):
        table.clear()
    again = generations.engine_profile(6, development=True)
    assert again["swing_model"] == 1.0
    assert again == _generation_5_and_the_areas()


# --- the harness: --engine 6 ------------------------------------------------------


def test_engine_6_equals_the_r6_overrides_file_and_the_areas_over_engine_5():
    by_engine = kpis.resolve_run_overrides(engine=6)
    by_file = kpis.resolve_run_overrides(overrides_path=HARNESS_COPY)
    assert by_engine == by_file
    assert list(by_engine) == list(by_file)
    assert load_tuning(by_engine).values == load_tuning(by_file).values
    # What each area ran during its build (--engine 6 over a copy of
    # generation 5, plus its file), all three at once, then the retune.
    by_areas = kpis.resolve_run_overrides(engine=5)
    for path in AREA_PROFILES + (RETUNE_PROFILE,):
        by_areas = {
            **by_areas, **kpis.load_tuning_overrides_file(path, base=by_areas)
        }
    assert load_tuning(by_engine).values == load_tuning(by_areas).values


def test_the_command_line_takes_engine_6(monkeypatch, capsys):
    captured = {}

    def fake_run_sim(games, seed, players_path, tuning_overrides, base_dir, **kwargs):
        captured["overrides"] = tuning_overrides
        raise KeyboardInterrupt

    monkeypatch.setattr(kpis, "run_sim", fake_run_sim)
    monkeypatch.setattr(kpis.sys, "argv", ["kpis", "--engine", "6"])
    with pytest.raises(KeyboardInterrupt):
        kpis.main()
    assert captured["overrides"] == generations.engine_profile(6, development=True)
    assert captured["overrides"] != generations.engine_profile(5)
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


# The Release 6a integration's generation 6 gates beyond generation 5's
# (target, band) -- the three areas' proposals.
R6_EXTRAS = {
    "starter_fb_velo_drop_91_105": (1.5, 0.5),
    "pitcher_k_std_beta_grade": (0.50, 0.15),
    "pitcher_fip_per10_arm": (-0.20, 0.15),
    "bb_pct_per10_control": (-1.35, 0.25),
    "tto_pass2_woba_delta_batter_adj": (0.011, 0.007),
    "pitcher_hitter_hr_true_sd_ratio": (0.40, 0.25),
    "e_per_team_game": (0.53, 0.05),
    "oaa_per_8pt_1b": (4.2, 0.7),
    "oaa_per_8pt_2b": (6.2, 0.8),
    "oaa_per_8pt_3b": (6.1, 0.8),
    "oaa_per_8pt_ss": (6.9, 0.8),
    "oaa_per_8pt_lf": (5.7, 0.8),
    "oaa_per_8pt_cf": (6.9, 0.8),
    "oaa_per_8pt_rf": (5.4, 0.8),
    "range_level_shift": (0.0, 0.001),
    "gb_play_share_3b": (0.206, 0.02),
    "gb_play_share_ss": (0.297, 0.02),
    "gb_play_share_p": (0.072, 0.02),
    "gb_play_share_2b": (0.280, 0.02),
    "gb_play_share_1b": (0.145, 0.02),
    "of_putout_share_cf": (0.416, 0.025),
    "r_pull_rating_pull_angle_rhb": (0.90, 0.10),
    "r_pull_rating_pull_angle_lhb": (0.90, 0.10),
}
R6_GRID = {
    "matchup_k_log5_inner_max_abs_resid": (0.0, 0.02),
    "matchup_hr_log5_max_abs_resid_logit": (0.0, 0.3),
    "power_hr600_p30": (7.0, 3.0),
    "power_hr600_p40": (7.0, 3.0),
}


def test_generation_6_is_gated_as_generation_5_plus_the_areas():
    five, six = kpis.ENGINE_GATES[5], kpis.ENGINE_GATES[6]
    assert six["benchmarks"] == {**five["benchmarks"], "corr_hr_power": 0.825}
    assert six["drop"] == five["drop"] + ["qualified_hr30_count"]
    assert six["tolerances"] == {
        **five["tolerances"],
        "corr_hr_power": 0.175,  # .65 to 1.00
        "doubles_per_team_game": 0.10,
        **{key: band for key, (_target, band) in R6_EXTRAS.items()},
    }
    assert six["extras_targets"] == {
        **five["extras_targets"],
        **{key: target for key, (target, _band) in R6_EXTRAS.items()},
    }
    assert six["grid_tolerances"] == {
        **five["grid_tolerances"],
        **{key: band for key, (_target, band) in R6_GRID.items()},
    }
    assert six["grid_extras_targets"] == {
        **five["grid_extras_targets"],
        **{key: target for key, (target, _band) in R6_GRID.items()},
    }
    # Pooled over seeds: report-only, never read by a single run.
    assert six["pooled"] == {
        "hr_power_bottom_quintile_ratio": (0.375, 0.375),  # at most .75
        "qualified_hr30_count": (20.0, 8.0),
    }
    assert "pooled" not in kpis.engine_gates_for(6, grid=True)
    # (A promoted metric the harness did not compute fails --strict as "not
    # computed": _promote_extras_metrics.)
    # A gate set's keys and the legacy engine's are untouched.
    assert kpis.engine_gates_for(None)["tolerances"] == {}
    assert kpis.ENGINE_GATES[5]["benchmarks"] == {"o_swing_pct": 0.286}
    # Separate objects, so moving 6's gates cannot move 5's.
    snapshot = copy.deepcopy(kpis.ENGINE_GATES[5])
    saved = copy.deepcopy(six)
    six["tolerances"]["platoon_gap_woba"] = 99.0
    six["drop"].append("nothing")
    try:
        assert kpis.ENGINE_GATES[5] == snapshot
    finally:
        kpis.ENGINE_GATES[6] = saved


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
    # The season's game tuning is generation 5's profile, not 6's.
    for key, value in generations.engine_profile(5).items():
        assert tuning[key] == value, key
    assert tuning.get("range_model", 0.0) == 0.0
    assert tuning.get("power_curve_model", 0.0) == 0.0
    assert tuning.get("fatigue_model", 0.0) == 0.0


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
