"""Release 6a integration: one rule for the three engine areas' keys in a
league's saved tuning.

The pitching work made a key's ownership depend on the league's
generation (``services.physics_tuning_settings._owned_keys``). At
integration the power and fielding keys follow the same rule:

* every key Release 6a registered (``R6A_KEYS``: the 63 keys
  ``DEFAULT_TUNING`` gained) means nothing to a legacy or generation 5
  league's file -- not read, not kept by a save -- exactly as before it was
  registered;
* from generation 6 the keys that switch or define an area's model are the
  generation's (``R6A_GENERATION_6_GROUP_KEYS``: the pitching group, power's
  six, fielding's seven switches); the sizes (slopes, band edges, error
  rates, fatigue points, manager weights) are ordinary knobs there.

The review's probe (a legacy or generation 5 league storing
``contact_logit_velo``) still gives main's output exactly with the power and
fielding keys added to the stored files.
"""

from __future__ import annotations

import json

import pytest

from physics_sim.config import DEFAULT_TUNING
from services import physics_tuning_settings as S
from tests.test_r6a_pitching_tuning import MAIN, PROBE

POWER_SWITCHES = (
    "power_curve_model",
    "bat_speed_power_table",
    "double_gap_power_weight",
    "double_line_drive_scale",
    "double_line_drive_span",
    "contact_logit_power",
)
FIELDING_SWITCHES = (
    "fielder_centred_ratings",
    "position_fit_model",
    "spray_direction_model",
    "infield_band_model",
    "range_model",
    "error_model",
    "fielding_chance_log",
)
# What a league could have stored for the other two areas (their profile
# values, a table among them).
OTHER_AREAS = {
    "power_curve_model": 1.0,
    "bat_speed_power_table": {"50": 1.0},
    "double_gap_power_weight": 0.25,
    "double_line_drive_scale": 0.07,
    "double_line_drive_span": 8.0,
    "contact_logit_power": 0.03,
    "fielder_centred_ratings": 1.0,
    "position_fit_model": 1.0,
    "spray_direction_model": 1.0,
    "infield_band_model": 1.0,
    "range_model": 1.0,
    "error_model": 2.0,
    "fielding_chance_log": 1.0,
    "range_logit_slope_ss": 0.005,
    "error_base_ss": 0.04,
    "infield_band_ss_min_deg": 0.0,
    "fielder_fa_center_p": 47.0,
}


def test_the_switch_lists():
    assert S.R6A_POWER_KEYS == POWER_SWITCHES
    assert S.R6A_FIELDING_SWITCH_KEYS == FIELDING_SWITCHES
    assert set(FIELDING_SWITCHES) <= set(S.R6A_FIELDING_KEYS)
    assert set(S.R6A_GENERATION_6_GROUP_KEYS) == (
        set(S.R6A_PITCHING_GROUP_KEYS) | set(POWER_SWITCHES) | set(FIELDING_SWITCHES)
    )
    keys = S.R6A_KEYS
    assert len(keys) == len(set(keys)) == 63
    assert all(key in DEFAULT_TUNING for key in keys)
    # Not owned on every generation: the generation decides.
    assert not set(keys) & set(S.GENERATION_OWNED_KEYS)


@pytest.mark.parametrize("generation", [4, 5])
def test_no_release_6a_key_means_anything_before_generation_6(tmp_path, generation):
    posted = {key: OTHER_AREAS.get(key, 0.5) for key in S.R6A_KEYS}
    assert S._sanitize_overrides(posted, generation=generation) == {}
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    path.write_text(json.dumps({**posted, "hr_scale": 0.95}), encoding="utf-8")
    assert S.load_physics_tuning_overrides(generation, path=path) == {"hr_scale": 0.95}
    S.save_physics_tuning_overrides({**posted, "hr_scale": 0.95}, generation, path=path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert {k: v for k, v in stored.items() if not k.startswith("_")} == {
        "hr_scale": 0.95
    }


def test_generation_6_owns_the_switches_and_keeps_the_sizes_ordinary():
    for key in POWER_SWITCHES + FIELDING_SWITCHES:
        assert key in S._owned_keys(6), key
        assert S._sanitize_overrides({key: 1.0}, generation=6) == {}, key
    sizes = {
        "range_logit_slope_ss": 0.005, "error_base_ss": 0.04,
        "infield_band_ss_min_deg": 0.5, "fatigue_control_points": 2.0,
        "hr_scale": 0.95,
    }
    assert S._sanitize_overrides(sizes, generation=6) == sizes
    assert S._sanitize_overrides(sizes, strict=True, generation=6) == sizes


@pytest.mark.parametrize("case", sorted(MAIN))
def test_the_review_probe_with_every_area_s_keys_gives_main_s_output(tmp_path, case):
    """The probe's stored files with the power and fielding keys added:
    loaded and saved back on the legacy engine or generation 5, the result
    is still main's (3abbbc251) for the probe files alone."""
    name, generation = case.split("/gen")
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    path.write_text(json.dumps({**PROBE[name], **OTHER_AREAS}), encoding="utf-8")
    loaded = S.load_physics_tuning_overrides(int(generation), path=path)
    S.save_physics_tuning_overrides(dict(loaded), int(generation), path=path)
    got = {
        "loaded": loaded,
        "file_after_save": json.loads(path.read_text(encoding="utf-8")),
    }
    assert got == MAIN[case]


def test_a_preset_multiplier_reaches_no_switch():
    """On the generations a league can be on (rule presets are a league
    feature; generation 6 is not one yet)."""
    multipliers = {
        key: 2.0 for key in POWER_SWITCHES + FIELDING_SWITCHES
        if key != "bat_speed_power_table"
    }
    for generation in (4, 5):
        applied = S.rule_preset_overrides({**multipliers, "hr_scale": 1.02}, generation)
        assert not (set(POWER_SWITCHES) | set(FIELDING_SWITCHES)) & set(applied)
        assert "hr_scale" in applied
