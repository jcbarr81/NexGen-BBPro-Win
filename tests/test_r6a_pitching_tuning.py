"""Release 6a, pitching: a league's saved tuning across the move to
generation 6.

* A legacy or generation 5 league's file loads and saves exactly as it did
  before this release (the review's probe, with main's results pinned):
  ``contact_logit_velo`` stays an ordinary knob there, and the keys this
  release registers are not read or kept, as when they were not registered.
* On generation 6 the keys that define the pitching group are the
  generation's, ``contact_logit_velo`` among them, and a value a league
  stored is kept in a marker, not lost.
* Velocity Scale means the opposite on generation 6, so a stored value is
  set aside (kept in the same marker) and the slider reads 1.0 -- in
  memory on every load, in the file only at a generation 6 season's game
  or a save, as Release 5 converted its sliders.
* The slider catalog of a generation 6 league, read through the
  generation's own defaults with this area's values folded in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import physics_sim.engine_generation as generations
from services import physics_tuning_settings as S
from services.physics_tuning_spec import (
    _TUNING_SECTIONS,
    _VELOCITY_MODEL_SLIDERS,
    tuning_sections_for_generation,
)

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_pitching.json"

# The review's probe (scratchpad r6/review/pitching/tuning_probe.py): two
# stored files, each loaded and then saved back as the editor posts it.
PROBE = {
    "g5_converted": {
        "_steal_freq_scale_rebased_r4": True, "_swing_sliders_rebased_r5": True,
        "_legacy_sliders_r5": {"walk_scale": 0.9, "k_scale": 0.55},
        "swing_walk_scale": 1.1, "contact_strikeout_scale": 1.05,
        "hr_scale": 0.95, "contact_logit_velo": 0.03, "velocity_scale": 1.02,
        "swing_pq_chase_logit": 0.02, "fatigue_control_points": 9.0,
    },
    "legacy_plain": {
        "_steal_freq_scale_rebased_r4": True, "walk_scale": 0.9, "k_scale": 0.55,
        "contact_logit_velo": 0.03, "velocity_scale": 1.02, "steal_freq_scale": 1.2,
    },
}
# What main (3abbbc251, before this release) returns for them: the
# review's probe_main.json.
MAIN = {
    "g5_converted/gen4": {
        "loaded": {"contact_logit_velo": 0.03, "hr_scale": 0.95, "k_scale": 0.52,
                   "velocity_scale": 1.02, "walk_scale": 0.91},
        "file_after_save": {"_steal_freq_scale_rebased_r4": True,
                            "contact_logit_velo": 0.03, "hr_scale": 0.95,
                            "k_scale": 0.52, "velocity_scale": 1.02,
                            "walk_scale": 0.91},
    },
    "g5_converted/gen5": {
        "loaded": {"contact_logit_velo": 0.03, "contact_strikeout_scale": 1.05,
                   "hr_scale": 0.95, "swing_walk_scale": 1.1,
                   "velocity_scale": 1.02},
        "file_after_save": {"_legacy_sliders_r5": {"k_scale": 0.55, "walk_scale": 0.9},
                            "_steal_freq_scale_rebased_r4": True,
                            "_swing_sliders_rebased_r5": True,
                            "contact_logit_velo": 0.03,
                            "contact_strikeout_scale": 1.05, "hr_scale": 0.95,
                            "swing_walk_scale": 1.1, "velocity_scale": 1.02},
    },
    "legacy_plain/gen4": {
        "loaded": {"contact_logit_velo": 0.03, "k_scale": 0.55,
                   "steal_freq_scale": 1.2, "velocity_scale": 1.02,
                   "walk_scale": 0.9},
        "file_after_save": {"_steal_freq_scale_rebased_r4": True,
                            "contact_logit_velo": 0.03, "k_scale": 0.55,
                            "steal_freq_scale": 1.2, "velocity_scale": 1.02,
                            "walk_scale": 0.9},
    },
    "legacy_plain/gen5": {
        "loaded": {"contact_logit_velo": 0.03, "contact_strikeout_scale": 1.17,
                   "steal_freq_scale": 1.2, "swing_walk_scale": 1.08,
                   "velocity_scale": 1.02},
        "file_after_save": {"_legacy_sliders_r5": {"k_scale": 0.55, "walk_scale": 0.9},
                            "_steal_freq_scale_rebased_r4": True,
                            "_swing_sliders_rebased_r5": True,
                            "contact_logit_velo": 0.03,
                            "contact_strikeout_scale": 1.17,
                            "steal_freq_scale": 1.2, "swing_walk_scale": 1.08,
                            "velocity_scale": 1.02},
    },
}


def _probe(tmp_path: Path, name: str, generation: int) -> dict:
    path = tmp_path / f"{name}_{generation}" / S.TUNING_OVERRIDES_FILENAME
    path.parent.mkdir()
    path.write_text(json.dumps(PROBE[name]), encoding="utf-8")
    loaded = S.load_physics_tuning_overrides(generation, path=path)
    S.save_physics_tuning_overrides(dict(loaded), generation, path=path)
    return {
        "loaded": loaded,
        "file_after_save": json.loads(path.read_text(encoding="utf-8")),
    }


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stored(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- legacy and generation 5: exactly as before the release ----------------------


@pytest.mark.parametrize("case", sorted(MAIN))
def test_a_legacy_or_generation_5_league_loads_and_saves_as_on_main(tmp_path, case):
    name, generation = case.split("/gen")
    assert _probe(tmp_path, name, int(generation)) == MAIN[case]


def test_contact_logit_velo_stays_an_ordinary_knob_before_generation_6(tmp_path):
    for generation in (4, 5):
        path = _write(tmp_path, {"contact_logit_velo": 0.03})
        assert S.load_physics_tuning_overrides(generation, path=path) == {
            "contact_logit_velo": 0.03
        }
        S.save_physics_tuning_overrides(
            {"contact_logit_velo": 0.04}, generation, path=path
        )
        assert _stored(path)["contact_logit_velo"] == 0.04
    # Not owned before generation 6, owned from it.
    assert "contact_logit_velo" not in S._owned_keys(5)
    assert "contact_logit_velo" in S._owned_keys(6)
    assert "contact_logit_velo" not in S.GENERATION_OWNED_KEYS


def test_this_release_s_keys_mean_nothing_to_an_earlier_generation(tmp_path):
    """As before the release, when they were not registered: not read, not
    kept by a save -- whether they define the group or size it."""
    posted = {key: 0.5 for key in S.R6A_PITCHING_KEYS}
    for generation in (4, 5):
        assert S._sanitize_overrides(posted, generation=generation) == {}
        path = _write(tmp_path, {**posted, "hr_scale": 0.95})
        assert S.load_physics_tuning_overrides(generation, path=path) == {
            "hr_scale": 0.95
        }
        S.save_physics_tuning_overrides(
            {**posted, "hr_scale": 0.95}, generation, path=path
        )
        assert {k: v for k, v in _stored(path).items() if not k.startswith("_")} == {
            "hr_scale": 0.95
        }


# --- generation 6 ----------------------------------------------------------------


def test_generation_6_owns_the_group_and_keeps_its_sizes_ordinary():
    sizes = {"fatigue_control_points": 2.0, "ev_velo_dev_weight": 0.12,
             "pitcher_score_weight_grade": 0.4, "hr_scale": 0.95}
    assert S._sanitize_overrides(sizes, generation=6) == sizes
    for key in S.R6A_PITCHING_GROUP_KEYS:
        assert key in S._owned_keys(6), key
        assert S._sanitize_overrides({key: 0.5}, generation=6) == {}, key
    # The chase slope is the group's from generation 6 (it acted by itself
    # under generation 5's swing model before the review's fix).
    assert "swing_pq_chase_logit" in S.R6A_PITCHING_GROUP_KEYS
    assert S._sanitize_overrides({"swing_pq_chase_logit": 0.01}, generation=6) == {}


def test_the_review_probe_on_generation_6(tmp_path):
    got = {name: _probe(tmp_path, name, 6) for name in PROBE}
    # The converted generation 5 file: the old Velocity Scale and the
    # contact velocity term are set aside and kept; the group keys are
    # dropped; the sizes and the other sliders are kept.
    g5 = got["g5_converted"]
    assert g5["loaded"] == {
        "contact_strikeout_scale": 1.05, "hr_scale": 0.95,
        "swing_walk_scale": 1.1, "fatigue_control_points": 9.0,
    }
    saved = g5["file_after_save"]
    assert saved[S.PRE_GENERATION_6_MARKER] == {
        "contact_logit_velo": 0.03, "velocity_scale": 1.02,
    }
    assert saved[S.VELOCITY_SLIDER_REBASE_MARKER] is True
    assert saved[S.LEGACY_SLIDERS_MARKER] == {"k_scale": 0.55, "walk_scale": 0.9}
    assert {k: v for k, v in saved.items() if not k.startswith("_")} == g5["loaded"]
    # The legacy file: converted for generation 5 as Release 5 does, and
    # the same two values kept.
    plain = got["legacy_plain"]
    assert "velocity_scale" not in plain["loaded"]
    assert "contact_logit_velo" not in plain["loaded"]
    assert plain["loaded"]["swing_walk_scale"] == 1.08
    assert plain["file_after_save"][S.PRE_GENERATION_6_MARKER] == {
        "contact_logit_velo": 0.03, "velocity_scale": 1.02,
    }


def test_velocity_is_converted_in_memory_until_a_generation_6_game(tmp_path):
    payload = {"velocity_scale": 1.05, "contact_logit_velo": 0.03, "hr_scale": 0.95}
    path = _write(tmp_path, payload)
    before = path.read_text(encoding="utf-8")
    # A page load, a watched game, an exhibition: converted, file untouched.
    assert S.load_physics_tuning_overrides(6, path=path) == {"hr_scale": 0.95}
    assert path.read_text(encoding="utf-8") == before
    # The same file is still the earlier generations' as it was.
    assert S.load_physics_tuning_overrides(5, path=path) == payload
    assert S.load_physics_tuning_overrides(4, path=path) == payload
    # A generation 6 season's game converts the file, once.
    assert S.load_physics_tuning_overrides(6, path=path, convert=True) == {
        "hr_scale": 0.95
    }
    stored = _stored(path)
    assert stored[S.PRE_GENERATION_6_MARKER] == {
        "velocity_scale": 1.05, "contact_logit_velo": 0.03,
    }
    assert stored[S.VELOCITY_SLIDER_REBASE_MARKER] is True
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    assert "velocity_scale" not in stored and "contact_logit_velo" not in stored
    converted = path.read_text(encoding="utf-8")
    assert S.load_physics_tuning_overrides(6, path=path, convert=True) == {
        "hr_scale": 0.95
    }
    assert path.read_text(encoding="utf-8") == converted
    # Now a Velocity Scale set on generation 6 is on the new meaning: kept.
    S.save_physics_tuning_overrides({"hr_scale": 0.95, "velocity_scale": 1.03}, 6,
                                    path=path)
    assert S.load_physics_tuning_overrides(6, path=path) == {
        "hr_scale": 0.95, "velocity_scale": 1.03,
    }
    assert _stored(path)[S.PRE_GENERATION_6_MARKER]["velocity_scale"] == 1.05


def test_a_commissioner_save_on_generation_6_converts_the_file(tmp_path):
    path = _write(tmp_path, {"velocity_scale": 1.05, "contact_logit_velo": 0.03,
                             "hr_scale": 0.95})
    # The page showed 1.0 for Velocity Scale; a posted contact_logit_velo
    # (owned) is not stored.
    S.save_physics_tuning_overrides({"hr_scale": 0.97, "contact_logit_velo": 0.09},
                                    6, path=path)
    stored = _stored(path)
    assert {k: v for k, v in stored.items() if not k.startswith("_")} == {
        "hr_scale": 0.97
    }
    assert stored[S.PRE_GENERATION_6_MARKER] == {
        "velocity_scale": 1.05, "contact_logit_velo": 0.03,
    }
    assert stored[S.VELOCITY_SLIDER_REBASE_MARKER] is True


def test_an_earlier_generation_gets_the_kept_values_back(tmp_path):
    path = _write(tmp_path, {"velocity_scale": 1.05, "contact_logit_velo": 0.03,
                             "hr_scale": 0.95})
    S.load_physics_tuning_overrides(6, path=path, convert=True)
    for generation in (4, 5):
        assert S.load_physics_tuning_overrides(generation, path=path) == {
            "velocity_scale": 1.05, "contact_logit_velo": 0.03, "hr_scale": 0.95,
        }
    # A generation 5 season's game writes them back into the file and drops
    # the generation 6 markers.
    S.load_physics_tuning_overrides(5, path=path, convert=True)
    stored = _stored(path)
    assert stored["velocity_scale"] == 1.05 and stored["contact_logit_velo"] == 0.03
    assert S.PRE_GENERATION_6_MARKER not in stored
    assert S.VELOCITY_SLIDER_REBASE_MARKER not in stored
    # A save on an earlier generation keeps what the page sent back, and no
    # generation 6 marker survives it.
    S.load_physics_tuning_overrides(6, path=path, convert=True)
    loaded = S.load_physics_tuning_overrides(5, path=path)
    S.save_physics_tuning_overrides(loaded, 5, path=path)
    stored = _stored(path)
    assert stored["velocity_scale"] == 1.05 and stored["contact_logit_velo"] == 0.03
    assert S.PRE_GENERATION_6_MARKER not in stored
    assert S.VELOCITY_SLIDER_REBASE_MARKER not in stored


# --- the slider catalog of a generation 6 league -----------------------------------


@pytest.fixture
def generation_6_switched_on(tmp_path, monkeypatch):
    """Generation 6 as the integration step will make it: its profile with
    this area's values folded in, and a generation a league can be on."""
    profile = json.loads(
        generations.engine_profile_path(6).read_text(encoding="utf-8")
    )
    profile.update(json.loads(PROFILE_PATH.read_text(encoding="utf-8")))
    folder = tmp_path / "profiles"
    folder.mkdir()
    for number in (5, 6):
        source = generations.engine_profile_path(number)
        payload = profile if number == 6 else json.loads(source.read_text())
        (folder / source.name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(generations, "ENGINE_PROFILE_DIR", folder)
    monkeypatch.setattr(generations, "known_engine_generations", lambda: (4, 5, 6))
    monkeypatch.setattr(generations, "DEVELOPMENT_ENGINE_GENERATIONS", ())
    yield profile


def test_a_generation_6_league_gets_the_new_velocity_slider(generation_6_switched_on):
    defaults = generations.engine_defaults(6)
    assert defaults["ev_velocity_model"] == 1.0
    sections = tuning_sections_for_generation(6)
    (spec,) = [s for _l, specs in sections for s in specs if s.key == "velocity_scale"]
    assert spec is _VELOCITY_MODEL_SLIDERS["velocity_scale"]
    assert "helps pitchers" in spec.description.lower()
    # Generation 5 and the legacy engine keep the old description.
    for generation in (4, 5):
        (old,) = [
            s for _l, specs in tuning_sections_for_generation(generation)
            for s in specs if s.key == "velocity_scale"
        ]
        assert old.description == "Pitch velocity scaling."
    # And the Release 5 swaps still apply on generation 6.
    keys = {s.key for _l, specs in sections for s in specs}
    assert {"swing_walk_scale", "contact_strikeout_scale"} <= keys
    assert len(sections) == len(_TUNING_SECTIONS)


def test_the_generation_6_defaults_are_the_profile_s(generation_6_switched_on):
    """What the tuning page reads as a generation 6 league's defaults."""
    defaults = S.load_physics_tuning_defaults(6)
    for key, value in generation_6_switched_on.items():
        if isinstance(value, (int, float)):
            assert defaults[key] == pytest.approx(float(value)), key
    # A generation 6 league's file never overrides the group.
    assert S._owned_keys(6) >= set(S.R6A_PITCHING_GROUP_KEYS)
