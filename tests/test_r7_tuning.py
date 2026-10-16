"""Release 6b: a league's saved tuning and generation 7.

* Every key Release 6b registered (``physics_sim.config.RELEASE_6B_KEYS``)
  means nothing to a league season on generation 4, 5 or 6: a stored one
  is not read and a save does not keep it (the independent review's
  probe, test_review_r7_override_leak.py). Without that, an admin save or a
  hand-edited file played part of generation 7 on a live league -- and
  ``batted_ball_model`` + ``spray_model`` on a generation 6 season made
  every game raise ``RatingCenterMissing``.
* From generation 7 its switches are the generation's
  (``RELEASE_6B_SWITCH_KEYS``); its sizes are ordinary knobs.
* Home Run Rate (``hr_scale``) and Launch Angle Base (``launch_angle_base``)
  mean something else on generation 7 (carry, the kernel's launch angle), so
  a value stored before is set aside, kept under ``PRE_GENERATION_7_MARKER``
  and given back to an earlier generation, with the timing of generation
  6's Velocity Scale conversion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physics_sim import ballflight
from physics_sim.config import (
    DEFAULT_TUNING,
    RELEASE_6B_KEYS,
    RELEASE_6B_SWITCH_KEYS,
    load_tuning,
)
from physics_sim import physics
from physics_sim.engine_generation import engine_profile
from services import physics_tuning_settings as S
from services.league_tuning import league_tuning_overrides
from utils.rating_scale import GENERATION6_SWITCH_ENV
from services.physics_tuning_spec import (
    _BALLFLIGHT_MODEL_SLIDERS,
    _TUNING_SECTIONS,
    tuning_sections,
)

GEN7_SWITCHES = ("carry_model", "batted_ball_model", "fielding_play_model",
                 "foul_out_model", "spray_model", "pitcher_gb_launch_scale")


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stored(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- the review's probe -------------------------------------------------------------


@pytest.mark.parametrize("generation", [4, 5, 6])
def test_a_stored_generation_7_switch_is_not_read(tmp_path, monkeypatch, generation):
    # Generation 6 is a generation a season can be on only with the 8.0.0
    # switch on (as it is in production).
    monkeypatch.setenv(GENERATION6_SWITCH_ENV, "1")
    (tmp_path / S.TUNING_OVERRIDES_FILENAME).write_text(
        json.dumps({key: 1.0 for key in GEN7_SWITCHES}), encoding="utf-8")
    got = league_tuning_overrides(tmp_path, generation=generation, migrate=False)
    assert not set(GEN7_SWITCHES) & set(got)


@pytest.mark.parametrize("generation", [4, 5, 6])
def test_a_save_does_not_keep_one(tmp_path, generation):
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    S.save_physics_tuning_overrides({"fielding_play_model": 1.0}, generation, path=path)
    stored = json.loads(path.read_text()) if path.exists() else {}
    assert "fielding_play_model" not in stored


# --- which keys --------------------------------------------------------------------


def test_the_release_6b_keys_are_the_ball_flight_block():
    assert RELEASE_6B_KEYS[0] == "carry_model"
    assert set(RELEASE_6B_SWITCH_KEYS) == set(GEN7_SWITCHES)
    assert set(RELEASE_6B_SWITCH_KEYS) <= set(RELEASE_6B_KEYS)
    for key in DEFAULT_TUNING:
        if key.startswith("bb6_") or key.startswith("foul_out_") or key in GEN7_SWITCHES:
            assert key in RELEASE_6B_KEYS, key
    # The two sliders are older keys every generation stores.
    assert "hr_scale" not in RELEASE_6B_KEYS
    assert "launch_angle_base" not in RELEASE_6B_KEYS


@pytest.mark.parametrize("generation", [4, 5, 6])
def test_no_release_6b_number_reaches_an_earlier_generation(tmp_path, generation):
    numbers = {
        key: 1.0 for key in RELEASE_6B_KEYS
        if isinstance(DEFAULT_TUNING[key], (int, float))
    }
    path = _write(tmp_path, {**numbers, "babip_scale": 0.95})
    loaded = S.load_physics_tuning_overrides(generation, path=path)
    assert loaded == {"babip_scale": 0.95}


def test_generation_7_owns_its_switches_and_keeps_its_sizes_ordinary(tmp_path):
    path = _write(tmp_path, {"carry_model": 0.0, "fielding_play_model": 0.0,
                             "bb6_carry_scale": 0.9, "foul_out_rate": 0.02})
    loaded = S.load_physics_tuning_overrides(7, path=path)
    assert loaded == {"bb6_carry_scale": 0.9, "foul_out_rate": 0.02}
    S.save_physics_tuning_overrides({"spray_model": 0.0, "bb6_carry_scale": 0.92}, 7,
                                    path=path)
    stored = _stored(path)
    assert "spray_model" not in stored and stored["bb6_carry_scale"] == 0.92


# --- the two sliders ------------------------------------------------------------------


def test_the_sliders_are_set_aside_until_a_generation_7_game(tmp_path):
    payload = {"hr_scale": 0.95, "launch_angle_base": 14.0, "babip_scale": 0.97}
    path = _write(tmp_path, payload)
    before = path.read_text(encoding="utf-8")
    # Converted in memory, the file untouched.
    assert S.load_physics_tuning_overrides(7, path=path) == {"babip_scale": 0.97}
    assert path.read_text(encoding="utf-8") == before
    # The earlier generations read them as before.
    for generation in (4, 5, 6):
        assert S.load_physics_tuning_overrides(generation, path=path) == payload
    # A generation 7 game converts the file, once.
    assert S.load_physics_tuning_overrides(7, path=path, convert=True) == {
        "babip_scale": 0.97
    }
    stored = _stored(path)
    assert stored[S.PRE_GENERATION_7_MARKER] == {"hr_scale": 0.95, "launch_angle_base": 14.0}
    assert stored[S.BALLFLIGHT_SLIDER_REBASE_MARKER] is True
    assert "hr_scale" not in stored and "launch_angle_base" not in stored
    # A value set on generation 7 is on the new meaning and is kept.
    S.save_physics_tuning_overrides({"babip_scale": 0.97, "hr_scale": 1.05}, 7, path=path)
    assert S.load_physics_tuning_overrides(7, path=path) == {
        "babip_scale": 0.97, "hr_scale": 1.05,
    }
    assert _stored(path)[S.PRE_GENERATION_7_MARKER]["hr_scale"] == 0.95


def test_an_earlier_generation_gets_its_sliders_back(tmp_path):
    path = _write(tmp_path, {"hr_scale": 0.95, "launch_angle_base": 14.0})
    S.load_physics_tuning_overrides(7, path=path, convert=True)
    for generation in (4, 5, 6):
        assert S.load_physics_tuning_overrides(generation, path=path) == {
            "hr_scale": 0.95, "launch_angle_base": 14.0,
        }
    S.load_physics_tuning_overrides(6, path=path, convert=True)
    stored = _stored(path)
    assert stored["hr_scale"] == 0.95 and stored["launch_angle_base"] == 14.0
    assert S.PRE_GENERATION_7_MARKER not in stored
    assert S.BALLFLIGHT_SLIDER_REBASE_MARKER not in stored


def test_a_setting_made_on_7_never_reaches_an_earlier_generation(tmp_path):
    """Round 5: Home Run Rate and Launch Angle Base set on generation 7 mean
    carry and launch angle; read on generation 6 they would mean something
    else (generation 6's Home Run Rate is steep: 1.08 against its .92 gave
    about 2.5 HR and 6.4 runs a team-game). Back below 7 the value kept from
    before 7 returns, else the generation's own default."""
    path = _write(tmp_path, {"hr_scale": 0.95, "launch_angle_base": 14.0})
    S.load_physics_tuning_overrides(7, path=path, convert=True)
    S.save_physics_tuning_overrides(
        {"hr_scale": 1.08, "launch_angle_base": 13.0, "babip_scale": 0.97}, 7, path=path
    )
    assert S.load_physics_tuning_overrides(7, path=path) == {
        "hr_scale": 1.08, "launch_angle_base": 13.0, "babip_scale": 0.97,
    }
    for generation in (4, 5, 6):
        assert S.load_physics_tuning_overrides(generation, path=path) == {
            "hr_scale": 0.95, "launch_angle_base": 14.0, "babip_scale": 0.97,
        }
    # Nothing kept from before 7: the earlier generation's defaults.
    other = tmp_path / "other"
    other.mkdir()
    path2 = _write(other, {"babip_scale": 0.97})
    S.load_physics_tuning_overrides(7, path=path2, convert=True)
    S.save_physics_tuning_overrides({"babip_scale": 0.97, "hr_scale": 1.08}, 7, path=path2)
    assert S.load_physics_tuning_overrides(6, path=path2) == {"babip_scale": 0.97}
    # A generation 6 game writes the file back on generation 6's meaning.
    S.load_physics_tuning_overrides(6, path=path2, convert=True)
    stored = _stored(path2)
    assert "hr_scale" not in stored and S.BALLFLIGHT_SLIDER_REBASE_MARKER not in stored
    # A setting made on generation 6 afterwards is read as set.
    S.save_physics_tuning_overrides({"babip_scale": 0.97, "hr_scale": 0.93}, 6, path=path2)
    assert S.load_physics_tuning_overrides(6, path=path2) == {
        "babip_scale": 0.97, "hr_scale": 0.93,
    }


def test_what_the_sliders_do_on_generation_7():
    profile = engine_profile(7, development=True)
    tuning = load_tuning(profile)
    # Neutral at the generation's defaults.
    assert tuning.get("hr_scale") == tuning.get("bb6_hr_slider_neutral") == 1.0
    assert ballflight.home_run_slider_factor(tuning) == 1.0
    raised = load_tuning({**profile, "hr_scale": 1.10})
    assert ballflight.home_run_slider_factor(raised) == pytest.approx(
        1.0 + 0.10 * profile["bb6_hr_slider_carry_share"]
    )
    assert ballflight.carry(100, 28, 0.0, raised)[0] > ballflight.carry(100, 28, 0.0, tuning)[0]
    # Launch Angle Base moves the kernel's angle degree for degree.
    import random

    def angle(t):
        random.seed(3)
        return physics._batted_ball_kernel(
            potential=90.0, timing_error=0.0, barrel_error=0.0, vertical_loc=0.0,
            batter={"gb_tendency": 50.0, "pull_tendency": 50.0},
            pitcher={"gb_tendency": 50.0}, pitch_type="sl", tuning=t,
        )[1]

    higher = load_tuning({**profile, "launch_angle_base": 14.1,
                          "hitter_gf_center": 50.0, "hitter_pull_center": 50.0,
                          "pitcher_gf_usage_center": 50.0})
    base = load_tuning({**profile, "hitter_gf_center": 50.0, "hitter_pull_center": 50.0,
                        "pitcher_gf_usage_center": 50.0})
    assert angle(higher) - angle(base) == pytest.approx(2.0, abs=1e-9)
    # Off (every earlier generation): neither slider touches the new model.
    assert ballflight.home_run_slider_factor(load_tuning({"hr_scale": 1.2})) == 1.0


def test_the_generation_7_slider_text():
    sections = tuning_sections(1.0, 1.0, 1.0, 1.0)
    specs = {s.key: s for _l, group in sections for s in group}
    for key in ("hr_scale", "launch_angle_base"):
        assert specs[key] is _BALLFLIGHT_MODEL_SLIDERS[key]
        assert "reset" in specs[key].description
    old = {s.key: s for _l, group in tuning_sections(1.0, 1.0, 1.0) for s in group}
    assert old["hr_scale"].description == "Home run outcome scaling."
    assert len(sections) == len(_TUNING_SECTIONS)
