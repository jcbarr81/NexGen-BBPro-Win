"""Release 5 switch-on: the commissioner sliders follow the engine generation.

Owner decision 9: from engine generation 5 Walk Rate, Zone Swing, Chase and
Strikeout Rate are rebased (1.0 = MLB), the two two-strike sliders are one
and Contact Rate merges into Strikeout Rate; stored values are converted
once. Which set a league is on comes from its season's generation, never
from a ``swing_model`` key in its overrides file.

Every review finding on the first build of the conversion has its scenario
here: markers a save dropped, legacy keys a save or a rule preset carried
that were silently ignored, a converted value that came back after a round
trip, clamps that bound inside the old sliders' own ranges, non-finite
values, the unlocked migration, and the two contact sliders that went dead.
"""

from __future__ import annotations

import json
import logging
import math
import threading

import pytest

import api.routers.tuning as T
import physics_sim.physics as physics
import services.physics_tuning_settings as S
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_defaults, engine_profile
from services import league_presets, league_rating_centers as centers
from services.physics_tuning_spec import (
    _CONTACT_MODEL_SLIDERS,
    _SWING_MODEL_SLIDERS,
    _TUNING_SECTIONS,
    tuning_sections,
    tuning_sections_for_generation,
)
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    ADMIN,
    NEW_SEASON_ENGINE_ENV,
    league,
    roll_over,
    write_schedule,
)

LEGACY, NEW = 4, 5
PROFILE = engine_profile(NEW)
SWING_LEGACY = (
    "walk_scale", "zone_swing_scale", "chase_scale",
    "two_strike_aggression_scale", "two_strike_zone_protect",
)
CONTACT_LEGACY = ("k_scale", "contact_prob_scale")
NEW_KEYS = (
    "swing_walk_scale", "swing_zone_scale", "swing_chase_scale",
    "swing_two_strike_scale", "contact_strikeout_scale",
)
# A commissioner's file as today's code stores it.
LEGACY_FILE = {
    "walk_scale": 1.0, "zone_swing_scale": 0.8, "two_strike_zone_protect": 0.8,
    "k_scale": 0.6, "hr_scale": 1.1, S.STEAL_FREQ_REBASE_MARKER: True,
}


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / S.TUNING_OVERRIDES_FILENAME
    monkeypatch.setattr(S, "TUNING_OVERRIDES_PATH", path)
    return path


def _slider_keys(sections):
    return [spec.key for _label, specs in sections for spec in specs]


def _legacy_spec(key):
    return next(s for _l, specs in _TUNING_SECTIONS for s in specs if s.key == key)


def _knobs(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def _stored(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _page_save(view: dict, changes: dict) -> dict:
    """What the tuning page sends: its draft, minus knobs equal to defaults."""
    draft = {**view["defaults"], **view["overrides"], **changes}
    return {
        key: float(value)
        for key, value in draft.items()
        if abs(float(value) - float(view["defaults"].get(key, 0.0))) > 1e-9
    }


# --- the slider set comes from the generation ------------------------------------


def test_the_catalog_follows_the_generation():
    assert tuning_sections_for_generation(LEGACY) is _TUNING_SECTIONS
    assert tuning_sections() is _TUNING_SECTIONS
    new = tuning_sections_for_generation(NEW)
    assert new == tuning_sections(1.0, 1.0)
    keys = _slider_keys(new)
    assert not set(keys) & set(SWING_LEGACY + CONTACT_LEGACY)
    assert set(NEW_KEYS) <= set(keys)
    # Two sliders fewer: Two-Strike Protect and Contact Rate are merged.
    assert len(keys) == len(_slider_keys(_TUNING_SECTIONS)) - 2
    assert [label for label, _ in new] == [label for label, _ in _TUNING_SECTIONS]
    # Each swap sits in its old slot, and only that swap changes.
    assert _slider_keys(tuning_sections(1.0, 0.0)) == [
        _SWING_MODEL_SLIDERS[k].key if _SWING_MODEL_SLIDERS.get(k) else k
        for k in _slider_keys(_TUNING_SECTIONS) if k != "two_strike_zone_protect"
    ]
    assert _slider_keys(tuning_sections(0.0, 1.0)) == [
        "contact_strikeout_scale" if k == "k_scale" else k
        for k in _slider_keys(_TUNING_SECTIONS) if k != "contact_prob_scale"
    ]
    assert S.effective_swing_model(LEGACY) == 0.0 == S.effective_contact_model(LEGACY)
    assert S.effective_swing_model(NEW) == 1.0 == S.effective_contact_model(NEW)


def test_a_switch_in_the_overrides_file_decides_nothing(overrides_file):
    """The first build read ``swing_model`` from the file. A legacy league
    with the key stored keeps its sliders and its values; the key never
    reaches the engine."""
    overrides_file.write_text(json.dumps({**LEGACY_FILE, "swing_model": 1.0}))
    before = overrides_file.read_text()
    loaded = S.load_physics_tuning_overrides(LEGACY)
    assert loaded == _knobs(LEGACY_FILE)
    assert overrides_file.read_text() == before  # nothing converted or written
    assert not set(NEW_KEYS) & set(loaded)
    # And the reverse: a stored 0 does not hold a generation 5 league back.
    overrides_file.write_text(
        json.dumps({**LEGACY_FILE, "swing_model": 0.0, "contact_model": 0.0})
    )
    loaded = S.load_physics_tuning_overrides(NEW)
    assert "swing_model" not in loaded and "contact_model" not in loaded
    assert loaded["swing_walk_scale"] > 1.0 and "walk_scale" not in loaded
    # Posting a switch through the API stores nothing.
    S.save_physics_tuning_overrides({"swing_model": 1.0, "hr_scale": 1.2}, LEGACY)
    assert _knobs(_stored(overrides_file)) == {"hr_scale": 1.2}
    for key in S.GENERATION_OWNED_KEYS:
        assert key in PROFILE or key in DEFAULT_TUNING
        assert S._sanitize_overrides({key: 1.0}) == {}


def test_a_legacy_league_keeps_its_file_and_values(overrides_file):
    overrides_file.write_text(json.dumps(LEGACY_FILE))
    before = overrides_file.read_text()
    assert S.load_physics_tuning_overrides(LEGACY) == _knobs(LEGACY_FILE)
    assert overrides_file.read_text() == before
    assert S.load_physics_tuning_defaults(LEGACY) == {
        k: float(v) for k, v in DEFAULT_TUNING.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    # A save from the legacy sliders stores them as they are.
    S.save_physics_tuning_overrides({"walk_scale": 0.9, "k_scale": 0.55}, LEGACY)
    assert _stored(overrides_file) == {
        "walk_scale": 0.9, "k_scale": 0.55, S.STEAL_FREQ_REBASE_MARKER: True,
    }


# --- stored values are converted when the league reaches generation 5 ---------------


def test_stored_sliders_are_converted_and_replaced(overrides_file):
    overrides_file.write_text(json.dumps(LEGACY_FILE))
    loaded = S.load_physics_tuning_overrides(NEW)
    assert loaded == S.convert_slider_overrides(_knobs(LEGACY_FILE))
    assert loaded["hr_scale"] == 1.1
    assert loaded["swing_walk_scale"] > 1.0 and loaded["swing_zone_scale"] < 1.0
    assert loaded["swing_two_strike_scale"] > 1.0
    assert loaded["contact_strikeout_scale"] > 1.0
    assert "swing_chase_scale" not in loaded  # was at its default
    # The legacy keys are gone from what the engine gets and from the file,
    # and kept for reference under a marker.
    assert not set(SWING_LEGACY + CONTACT_LEGACY) & set(loaded)
    stored = _stored(overrides_file)
    assert _knobs(stored) == loaded
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    assert stored[S.STEAL_FREQ_REBASE_MARKER] is True
    assert stored[S.LEGACY_SLIDERS_MARKER] == {
        "walk_scale": 1.0, "zone_swing_scale": 0.8,
        "two_strike_zone_protect": 0.8, "k_scale": 0.6,
    }
    # Once: a second load reads the same and writes nothing.
    text = overrides_file.read_text()
    assert S.load_physics_tuning_overrides(NEW) == loaded
    assert overrides_file.read_text() == text
    assert S.load_physics_tuning_values(NEW)["swing_walk_scale"] == (
        loaded["swing_walk_scale"]
    )


def test_both_migrations_run_together_and_each_only_once(overrides_file):
    overrides_file.write_text(json.dumps({"steal_freq_scale": 4.5, "chase_scale": 0.9}))
    loaded = S.load_physics_tuning_overrides(NEW)
    assert loaded["steal_freq_scale"] == pytest.approx(1.5)
    assert loaded["swing_chase_scale"] > 1.0 and "chase_scale" not in loaded
    assert S.load_physics_tuning_overrides(NEW) == loaded
    # The steal rebase alone (a legacy league) converts no swing slider.
    overrides_file.write_text(json.dumps({"steal_freq_scale": 4.5, "chase_scale": 0.9}))
    loaded = S.load_physics_tuning_overrides(LEGACY)
    assert loaded == {"steal_freq_scale": pytest.approx(1.5), "chase_scale": 0.9}
    stored = _stored(overrides_file)
    assert S.SWING_SLIDER_REBASE_MARKER not in stored
    assert stored[S.STEAL_FREQ_REBASE_MARKER] is True
    assert S.load_physics_tuning_overrides(LEGACY) == loaded


def test_conversion_survives_a_read_only_file(overrides_file, monkeypatch):
    overrides_file.write_text(json.dumps(LEGACY_FILE))
    before = overrides_file.read_text()

    def fail(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(S, "_write_atomic", fail)
    first = S.load_physics_tuning_overrides(NEW)
    assert first["swing_walk_scale"] > 1.0 and "walk_scale" not in first
    assert S.load_physics_tuning_overrides(NEW) == first
    assert overrides_file.read_text() == before


# --- finding: a save dropped the internal markers -----------------------------------


@pytest.mark.parametrize("generation", [LEGACY, NEW])
def test_a_save_carries_every_marker_forward(overrides_file, generation):
    markers = {
        S.STEAL_FREQ_REBASE_MARKER: True,
        S.SWING_SLIDER_REBASE_MARKER: True,
        S.LEGACY_SLIDERS_MARKER: {"walk_scale": 1.0},
        "_a_marker_from_a_later_release": {"n": 7},
    }
    overrides_file.write_text(json.dumps({"hr_scale": 1.1, **markers}))
    S.save_physics_tuning_overrides({"babip_scale": 0.95}, generation)
    stored = _stored(overrides_file)
    assert _knobs(stored) == {"babip_scale": 0.95}
    for key, value in markers.items():
        assert stored[key] == value, key


def test_the_page_save_that_used_to_drop_the_marker(league):
    """The reported sequence: the league reaches generation 5 with legacy
    sliders stored, they are converted, and the commissioner saves the page.
    The first build wrote that save without the marker (no ``swing_model``
    in the file), so the next load converted the legacy values AGAIN."""
    write_schedule(league, 2027)
    path = league / S.TUNING_OVERRIDES_FILENAME
    path.write_text(json.dumps(LEGACY_FILE))
    view = T.get_tuning(ADMIN)
    converted = dict(view["overrides"])
    assert converted["swing_walk_scale"] > 1.0
    view = T.save_tuning(
        {"overrides": _page_save(view, {"swing_walk_scale": 1.1})}, ADMIN
    )
    stored = _stored(path)
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    assert stored[S.LEGACY_SLIDERS_MARKER]["walk_scale"] == 1.0
    assert view["overrides"] == {**converted, "swing_walk_scale": 1.1}
    assert S.load_physics_tuning_overrides(5) == view["overrides"]
    assert T.get_tuning(ADMIN)["overrides"]["swing_walk_scale"] == 1.1


# --- finding: legacy keys in a save or a preset were silently ignored -----------------


def test_a_save_under_generation_5_converts_legacy_keys(overrides_file):
    S.save_physics_tuning_overrides({"walk_scale": 1.05, "hr_scale": 1.1}, NEW)
    stored = _stored(overrides_file)
    assert _knobs(stored) == {"hr_scale": 1.1, "swing_walk_scale": 1.25}
    assert stored[S.LEGACY_SLIDERS_MARKER] == {"walk_scale": 1.05}
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    # A value already on the new scale in the same save is the one kept.
    S.save_physics_tuning_overrides({"walk_scale": 1.05, "swing_walk_scale": 0.9}, NEW)
    assert _knobs(_stored(overrides_file)) == {"swing_walk_scale": 0.9}
    # A save on the new scale is stored as it is.
    S.save_physics_tuning_overrides(
        {"swing_walk_scale": 1.1, "contact_strikeout_scale": 0.9}, NEW
    )
    assert _knobs(_stored(overrides_file)) == {
        "swing_walk_scale": 1.1, "contact_strikeout_scale": 0.9,
    }


def test_the_rule_presets_state_rates_relative_to_the_engine():
    """``walk_scale`` 1.05 / ``k_scale`` 0.92 meant "5% more walks, 8% fewer
    strikeouts" to whoever wrote them, against defaults of 0.83 and 0.51."""
    presets = {p.preset_id: p for p in league_presets.load_rule_presets()}
    assert set(presets) >= {"mlb_standard", "high_offense", "pitcher_friendly"}
    for preset in presets.values():
        owned = set(S.LEGACY_SLIDER_KEYS) | set(NEW_KEYS) | set(S.GENERATION_OWNED_KEYS)
        assert not owned & set(preset.physics_tuning_overrides), preset.preset_id
    high = presets["high_offense"].physics_tuning_multipliers
    low = presets["pitcher_friendly"].physics_tuning_multipliers
    assert set(high) == set(low) == {
        "hr_scale", "babip_scale", "walk_rate", "strikeout_rate",
    }
    assert high["strikeout_rate"] < 1.0 < low["strikeout_rate"]
    assert low["walk_rate"] < 1.0 < high["walk_rate"]
    # Small steps: the knobs are strong (2% of hr_scale is about 5% of the
    # runs; offense_scale, 9% of the runs per 1%, is left alone). The old
    # values -- 1.08, 1.12, 1.04 -- were sized as if they were percentages
    # of scoring: 11 runs a game once the strikeouts were right.
    for multipliers in (high, low):
        assert "offense_scale" not in multipliers
        assert all(0.94 <= value <= 1.06 for value in multipliers.values())
    assert presets["mlb_standard"].physics_tuning_multipliers == {}


@pytest.mark.parametrize("generation", [LEGACY, NEW])
def test_a_preset_means_the_same_on_both_engines(generation):
    multipliers = {
        "offense_scale": 1.08, "hr_scale": 1.12, "babip_scale": 1.04,
        "walk_rate": 1.05, "strikeout_rate": 0.92,
    }
    overrides = S.rule_preset_overrides(multipliers, generation)
    defaults = engine_defaults(generation)
    for key in ("offense_scale", "hr_scale", "babip_scale"):
        assert overrides[key] == pytest.approx(defaults[key] * multipliers[key], abs=1e-4)
    # On the 1.0 = MLB scale, whichever engine: 5% more walks, 8% fewer Ks.
    new_scale = S.convert_slider_overrides(overrides)
    assert new_scale["swing_walk_scale"] == pytest.approx(1.05, abs=0.02)
    assert new_scale["contact_strikeout_scale"] == pytest.approx(0.92, abs=0.02)
    if generation == LEGACY:
        # The legacy sliders, near their real defaults -- not 1.05 and 0.92.
        assert 0.83 < overrides["walk_scale"] < 0.90
        assert 0.47 < overrides["k_scale"] < 0.51
        assert not set(NEW_KEYS) & set(overrides)
    else:
        assert overrides["swing_walk_scale"] == 1.05
        assert overrides["contact_strikeout_scale"] == 0.92
        assert not set(S.LEGACY_SLIDER_KEYS) & set(overrides)
    # Nothing to do, junk and engine switches are left out.
    assert S.rule_preset_overrides(
        {"walk_rate": 1.0, "hr_scale": "x", "nope": 2.0, "swing_model": 2.0,
         "babip_scale": float("nan")},
        generation,
    ) == {}


def test_applying_a_preset_in_a_new_league_and_in_a_legacy_one(league, monkeypatch):
    path = league / S.TUNING_OVERRIDES_FILENAME
    # A league being created: no schedule yet, so generation 5.
    assert league_presets.apply_rule_preset("high_offense") is not None
    stored = _stored(path)
    assert _knobs(stored) == {
        # A preset multiplies the league's own base: generation 5's profile.
        "hr_scale": pytest.approx(engine_defaults(NEW)["hr_scale"] * 1.02, abs=1e-4),
        "babip_scale": pytest.approx(
            engine_defaults(NEW)["babip_scale"] * 1.01, abs=1e-4
        ),
        "swing_walk_scale": 1.03,
        "contact_strikeout_scale": 0.95,
    }
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    assert league_presets.apply_rule_preset("mlb_standard") is not None
    assert not path.exists()

    # The same preset while new seasons are held on the legacy engine.
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, "4")
    league_presets.apply_rule_preset("pitcher_friendly")
    legacy = _knobs(_stored(path))
    assert not set(NEW_KEYS) & set(legacy)
    assert 0.51 < legacy["k_scale"] < 0.56  # 6% more strikeouts, not 1.08
    assert 0.75 < legacy["walk_scale"] < 0.83  # 3% fewer walks, not 0.90
    assert legacy["hr_scale"] == pytest.approx(0.925 * 0.98, abs=1e-4)


def test_a_preset_that_still_states_legacy_sliders_is_converted_on_apply(
    league, monkeypatch
):
    """``apply_rule_preset("high_offense")`` wrote ``walk_scale: 1.05``; under
    generation 5 the engine does not read it and the first build stored it
    as dead weight. A preset in the old form is converted, not ignored."""
    old_form = league_presets.RulePreset(
        preset_id="high_offense", name="High Offense", description="",
        physics_tuning_overrides={"hr_scale": 1.12, "walk_scale": 1.05},
    )
    monkeypatch.setattr(league_presets, "load_rule_presets", lambda: [old_form])
    league_presets.apply_rule_preset("high_offense")
    stored = _knobs(_stored(league / S.TUNING_OVERRIDES_FILENAME))
    assert stored == {"hr_scale": 1.12, "swing_walk_scale": 1.25}


# --- finding: a round trip resurrected the converted value ---------------------------


def test_setting_a_converted_slider_back_to_1_stays_at_1(league, monkeypatch):
    """New Walk Rate set back to 1.0, the league goes legacy and comes back:
    the value converted from the old ``walk_scale`` must not return."""
    path = league / S.TUNING_OVERRIDES_FILENAME
    write_schedule(league, 2027)
    path.write_text(json.dumps({"walk_scale": 1.0, "hr_scale": 1.1}))
    view = T.get_tuning(ADMIN)
    assert view["engine"]["generation"] == NEW
    assert view["overrides"]["swing_walk_scale"] == pytest.approx(1.2, abs=0.02)

    # The commissioner drags the new Walk Rate back to 1.0 and saves.
    view = T.save_tuning({"overrides": _page_save(view, {"swing_walk_scale": 1.0})}, ADMIN)
    assert view["overrides"] == {"hr_scale": 1.1}
    assert _knobs(_stored(path)) == {"hr_scale": 1.1}
    assert T.get_tuning(ADMIN)["overrides"] == {"hr_scale": 1.1}

    # The league goes legacy: the save above fixed the season on generation
    # 5, so it takes losing that record (a restore from before it) while new
    # seasons are held on the legacy engine ...
    (league / centers.RATING_CENTERS_FILENAME).unlink()
    monkeypatch.setenv(NEW_SEASON_ENGINE_ENV, "4")
    centers.clear_rating_center_cache()
    view = T.get_tuning(ADMIN)
    assert view["engine"]["generation"] == LEGACY
    assert view["overrides"] == {"hr_scale": 1.1}
    T.save_tuning({"overrides": _page_save(view, {"babip_scale": 0.95})}, ADMIN)
    # ... and back.
    monkeypatch.delenv(NEW_SEASON_ENGINE_ENV)
    centers.clear_rating_center_cache()
    for _ in range(2):
        view = T.get_tuning(ADMIN)
        assert view["engine"]["generation"] == NEW
        assert view["overrides"] == {"hr_scale": 1.1, "babip_scale": 0.95}
    assert "swing_walk_scale" not in _stored(path)
    assert "walk_scale" not in _knobs(_stored(path))


def test_a_legacy_slider_moved_while_legacy_is_a_new_value_to_convert(overrides_file):
    overrides_file.write_text(json.dumps({"walk_scale": 1.0}))
    assert S.load_physics_tuning_overrides(NEW)["swing_walk_scale"] > 1.0
    S.save_physics_tuning_overrides({}, NEW)  # back to 1.0: nothing stored
    assert not overrides_file.exists()
    S.save_physics_tuning_overrides({"walk_scale": 0.7}, LEGACY)
    assert S.load_physics_tuning_overrides(NEW) == {"swing_walk_scale": 0.84}


# --- finding: the clamps bound inside the old sliders' own ranges -------------------


@pytest.mark.parametrize("legacy_key", SWING_LEGACY + CONTACT_LEGACY)
def test_the_whole_range_of_each_old_slider_converts_without_clipping(
    legacy_key, caplog
):
    spec = _legacy_spec(legacy_key)
    new = {**_SWING_MODEL_SLIDERS, **_CONTACT_MODEL_SLIDERS}[legacy_key]
    if new is None:  # merged: converts through its partner's slider
        partner = (
            "two_strike_aggression_scale" if legacy_key == "two_strike_zone_protect"
            else "k_scale"
        )
        new = {**_SWING_MODEL_SLIDERS, **_CONTACT_MODEL_SLIDERS}[partner]
    values = []
    with caplog.at_level(logging.WARNING, logger=S.__name__):
        for step in range(31):
            stored = spec.min_value + (spec.max_value - spec.min_value) * step / 30
            values.append(S.convert_slider_overrides({legacy_key: stored}).get(new.key, 1.0))
    assert "outside the slider" not in caplog.text
    # Strictly inside: neither end of the old range lands on a bound.
    assert new.min_value < min(values) < 1.0 < max(values) < new.max_value
    rising = legacy_key != "contact_prob_scale"  # more contact = fewer strikeouts
    ordered = values if rising else values[::-1]
    assert all(a <= b for a, b in zip(ordered, ordered[1:]))


def test_the_reported_clips_no_longer_clip():
    convert = S.convert_slider_overrides
    assert convert({"zone_swing_scale": 0.6}) == {"swing_zone_scale": 0.46}
    assert convert({"zone_swing_scale": 1.2}) == {"swing_zone_scale": 2.24}
    assert convert({"two_strike_zone_protect": 0.9}) == {"swing_two_strike_scale": 3.98}
    # Both two-strike sliders at their maximum, and at their minimum.
    assert convert(
        {"two_strike_aggression_scale": 1.4, "two_strike_zone_protect": 0.9}
    ) == {"swing_two_strike_scale": 4.64}
    assert convert(
        {"two_strike_aggression_scale": 0.8, "two_strike_zone_protect": 0.4}
    ) == {"swing_two_strike_scale": 0.52}


def test_a_value_from_outside_the_old_range_is_held_and_logged(caplog):
    spec = _SWING_MODEL_SLIDERS["zone_swing_scale"]
    with caplog.at_level(logging.WARNING, logger=S.__name__):
        held = S.convert_slider_overrides({"zone_swing_scale": 50.0})
    assert held == {"swing_zone_scale": spec.max_value}
    assert "zone_swing_scale" in caplog.text and "outside the slider" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=S.__name__):
        low = S.convert_slider_overrides({"k_scale": 0.05, "contact_prob_scale": 3.0})
    assert low["contact_strikeout_scale"] < 1.0
    assert "outside the measured" in caplog.text


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_rejected(overrides_file, bad):
    for generation in (LEGACY, NEW):
        with pytest.raises(ValueError, match="finite"):
            S.save_physics_tuning_overrides({"hr_scale": bad}, generation)
        with pytest.raises(ValueError, match="finite"):
            S.save_physics_tuning_overrides({"walk_scale": bad}, generation)
    assert not overrides_file.exists()
    with pytest.raises(ValueError, match="number"):
        S.save_physics_tuning_overrides({"hr_scale": "lots"}, LEGACY)
    # The API answers 400, and the stored file is not replaced.
    S.save_physics_tuning_overrides({"hr_scale": 1.1}, LEGACY)
    with pytest.raises(T.HTTPException) as raised:
        T.save_tuning({"overrides": {"hr_scale": bad}}, ADMIN)
    assert raised.value.status_code == 400
    assert _knobs(_stored(overrides_file)) == {"hr_scale": 1.1}
    # One already in a file (json allows NaN) never reaches the engine or a
    # conversion.
    overrides_file.write_text(json.dumps({"walk_scale": bad, "hr_scale": bad, "k_scale": 0.6}))
    assert S.load_physics_tuning_overrides(LEGACY) == {"k_scale": 0.6}
    assert S.load_physics_tuning_overrides(NEW) == {
        "contact_strikeout_scale": S.convert_slider_overrides({"k_scale": 0.6})[
            "contact_strikeout_scale"
        ]
    }
    converted = S.convert_swing_slider_overrides({"walk_scale": bad})
    assert set(converted) == {"walk_scale"}  # no new-scale value made from it
    assert not math.isfinite(converted["walk_scale"])


# --- finding: the migration was an unlocked read-modify-write -------------------------


def test_a_save_landing_during_the_migration_is_not_overwritten(
    overrides_file, monkeypatch
):
    """A GET (or a game) starts converting the legacy file; before it writes,
    the commissioner's save replaces the file. The migration re-reads under
    the lock and must leave the save alone."""
    overrides_file.write_text(json.dumps(LEGACY_FILE))
    saved = {"hr_scale": 1.25, "swing_walk_scale": 0.9}
    real = S._migrated
    raced = []

    def migrated_then_a_save_lands(payload, generation):
        result = real(payload, generation)
        if not raced:
            raced.append(True)
            thread = threading.Thread(
                target=S.save_physics_tuning_overrides, args=(saved, NEW)
            )
            thread.start()
            thread.join(timeout=30)
            assert not thread.is_alive()
        return result

    monkeypatch.setattr(S, "_migrated", migrated_then_a_save_lands)
    loaded = S.load_physics_tuning_overrides(NEW)
    assert loaded == saved  # what is on disk now, not the stale conversion
    assert _knobs(_stored(overrides_file)) == saved


def test_the_migration_holds_the_lock_a_save_needs(overrides_file, monkeypatch):
    """The write of the migration and a save can not interleave: while the
    migration is inside the lock a save waits, then replaces the result."""
    overrides_file.write_text(json.dumps(LEGACY_FILE))
    real_write = S._write_atomic
    inside = threading.Event()
    release = threading.Event()
    order = []

    def slow_write(path, payload):
        if not inside.is_set():
            inside.set()
            assert release.wait(timeout=30)
            order.append("migration")
        else:
            order.append("save")
        real_write(path, payload)

    monkeypatch.setattr(S, "_write_atomic", slow_write)
    migrating = threading.Thread(target=S.load_physics_tuning_overrides, args=(NEW,))
    migrating.start()
    assert inside.wait(timeout=30)
    saving = threading.Thread(
        target=S.save_physics_tuning_overrides, args=({"hr_scale": 1.3}, NEW)
    )
    saving.start()
    saving.join(timeout=0.5)
    assert saving.is_alive()  # blocked on the lock, not racing the write
    release.set()
    migrating.join(timeout=30)
    saving.join(timeout=30)
    assert order == ["migration", "save"]
    stored = _stored(overrides_file)
    assert _knobs(stored) == {"hr_scale": 1.3}
    # The save carried forward what the migration recorded.
    assert stored[S.LEGACY_SLIDERS_MARKER]["walk_scale"] == 1.0
    assert (overrides_file.parent / f"{overrides_file.name}.lock").exists()


def test_many_loads_and_saves_at_once_leave_a_whole_file(overrides_file):
    overrides_file.write_text(json.dumps(LEGACY_FILE))
    errors = []

    def work(index):
        try:
            for turn in range(15):
                if (index + turn) % 3 == 0:
                    S.save_physics_tuning_overrides(
                        {"hr_scale": 1.0 + index / 100, "walk_scale": 0.9}, NEW
                    )
                else:
                    loaded = S.load_physics_tuning_overrides(NEW)
                    assert not set(S.LEGACY_SLIDER_KEYS) & set(loaded)
        except Exception as exc:  # pragma: no cover - the assertion below reports it
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors
    stored = _stored(overrides_file)
    assert not set(S.LEGACY_SLIDER_KEYS) & set(stored)
    assert stored[S.SWING_SLIDER_REBASE_MARKER] is True
    assert not list(overrides_file.parent.glob("*.tmp.*"))


# --- finding: Strikeout Rate and Contact Rate went dead under contact_model 1 ---------


def _contact(**knobs) -> float:
    tuning = load_tuning({**PROFILE, **knobs})
    return physics._contact_probability(
        contact=50.0, pitch_quality=50.0, break_mag=0.25, velocity=92.0,
        pitch_type="fb", in_zone=True, strikes=1, tuning=tuning,
    )


def test_the_new_strikeout_slider_moves_the_contact_roll():
    spec = _CONTACT_MODEL_SLIDERS["k_scale"]
    assert spec.key == "contact_strikeout_scale" and spec.label == "Strikeout Rate"
    assert "1.0 = MLB" in spec.description
    assert _CONTACT_MODEL_SLIDERS["contact_prob_scale"] is None
    assert DEFAULT_TUNING["contact_strikeout_scale"] == 1.0
    assert "contact_strikeout_scale" not in PROFILE  # 1.0 = the profile's level
    assert spec.min_value < 1.0 < spec.max_value

    def odds(p):
        return p / (1.0 - p)

    base = _contact()
    gain = DEFAULT_TUNING["contact_strikeout_logit_gain"]
    # 1.0 is no term at all; the slider divides the contact odds.
    assert _contact(contact_strikeout_scale=1.0) == base
    assert odds(_contact(contact_strikeout_scale=1.25)) == pytest.approx(
        odds(base) / 1.25 ** gain
    )
    # "Strikeout Rate up = more strikeouts": less contact, all the way.
    steps = [
        _contact(
            contact_strikeout_scale=spec.min_value
            + (spec.max_value - spec.min_value) * i / 30
        )
        for i in range(31)
    ]
    assert all(a > b for a, b in zip(steps, steps[1:]))
    assert all(0.0 < value < 1.0 for value in steps)
    # In and out of the zone alike, and with two strikes.
    for kwargs in ({"in_zone": False}, {"strikes": 2}):
        tuning_base = load_tuning(PROFILE)
        tuning_up = load_tuning({**PROFILE, "contact_strikeout_scale": 1.5})
        args = dict(
            contact=50.0, pitch_quality=50.0, break_mag=0.25, velocity=92.0,
            pitch_type="fb", in_zone=True, strikes=1,
        )
        args.update(kwargs)
        assert physics._contact_probability(tuning=tuning_up, **args) < (
            physics._contact_probability(tuning=tuning_base, **args)
        )
    # The old sliders really are dead under the new model, which is why
    # they are replaced.
    assert _contact(k_scale=1.2, contact_prob_scale=0.85) == base


def test_stored_strikeout_and_contact_sliders_convert_to_the_one_slider():
    convert = S.convert_strikeout_slider_overrides
    key = "contact_strikeout_scale"
    assert S._LEGACY_CONTACT_DEFAULTS == {
        k: DEFAULT_TUNING[k] for k in ("k_scale", "contact_prob_scale")
    }
    # At the old defaults: 1.0, not stored; the input is not changed.
    at_default = {"k_scale": 0.51, "contact_prob_scale": 0.885, "hr_scale": 1.1}
    assert convert(at_default) == at_default
    # More strikeouts stays more strikeouts.
    assert convert({"k_scale": 0.6})[key] > 1.0 > convert({"k_scale": 0.45})[key]
    # Contact Rate up was fewer strikeouts.
    assert convert({"contact_prob_scale": 1.0})[key] < 1.0
    assert convert({"contact_prob_scale": 0.85})[key] > 1.0
    # The two were one factor: these two files asked for the same thing.
    assert convert({"k_scale": 0.45})[key] == pytest.approx(
        convert({"contact_prob_scale": 0.885 * 0.51 / 0.45})[key], abs=0.011
    )
    # Together they combine; opposite moves cancel.
    both = convert({"k_scale": 0.6, "contact_prob_scale": 0.85})[key]
    assert both > convert({"k_scale": 0.6})[key]
    cancel = convert({"k_scale": 0.612, "contact_prob_scale": 1.062})
    assert cancel.get(key, 1.0) == pytest.approx(1.0, abs=0.011)
    # The slider that gives the contact rate the stored pair gave: the
    # legacy engine made contact on .674 of swings at k_scale 0.60.
    gain = DEFAULT_TUNING["contact_strikeout_logit_gain"]

    def odds(p):
        return p / (1.0 - p)

    assert convert({"k_scale": 0.6})[key] ** -gain == pytest.approx(
        odds(0.674) / odds(0.787), abs=0.01
    )
    # A value already on the new scale is never overwritten.
    assert convert({"k_scale": 1.0, key: 0.9})[key] == 0.9
    # The combined converter replaces both legacy keys.
    assert S.convert_slider_overrides(
        {"k_scale": 0.6, "contact_prob_scale": 0.85, "hr_scale": 1.1}
    ) == {key: both, "hr_scale": 1.1}


def test_stored_strikeout_sliders_are_converted_in_the_file(overrides_file):
    overrides_file.write_text(
        json.dumps({"k_scale": 0.6, "contact_prob_scale": 0.9, "hr_scale": 1.1})
    )
    loaded = S.load_physics_tuning_overrides(NEW)
    assert set(loaded) == {"contact_strikeout_scale", "hr_scale"}
    assert loaded["contact_strikeout_scale"] > 1.0
    stored = _stored(overrides_file)
    assert stored[S.LEGACY_SLIDERS_MARKER] == {"k_scale": 0.6, "contact_prob_scale": 0.9}
    assert S.load_physics_tuning_overrides(NEW) == loaded


# --- the API: sliders, defaults and the engine line -----------------------------------


def test_the_api_reports_a_legacy_league_as_it_always_did(league):
    write_schedule(league, 2026, played=3)
    view = T.get_tuning(ADMIN)
    assert _slider_keys(
        [(s["label"], [type("S", (), x) for x in s["sliders"]]) for s in view["sections"]]
    ) == _slider_keys(_TUNING_SECTIONS)
    assert view["defaults"] == S.load_physics_tuning_defaults(LEGACY)
    assert view["defaults"]["swing_model"] == 0.0
    assert view["overrides"] == {}
    assert view["engine"] == {
        "generation": LEGACY,
        "latest_generation": NEW,
        "message": (
            "This league moves to the new game engine at the start of next season."
        ),
    }
    # A page load fixes nothing for the season.
    assert not (league / centers.RATING_CENTERS_FILENAME).exists()


def test_the_api_reports_a_generation_5_league(league):
    write_schedule(league, 2027)
    path = league / S.TUNING_OVERRIDES_FILENAME
    view = T.get_tuning(ADMIN)
    assert view["engine"] == {
        "generation": NEW,
        "latest_generation": NEW,
        "message": "This league uses the new game engine.",
    }
    served = [s["key"] for section in view["sections"] for s in section["sliders"]]
    assert served == _slider_keys(tuning_sections_for_generation(NEW))
    # The defaults are the engine's under generation 5: the profile's values.
    assert view["defaults"] == engine_defaults(NEW)
    assert view["defaults"]["foul_rate"] == PROFILE["foul_rate"] != DEFAULT_TUNING["foul_rate"]
    assert view["defaults"]["swing_model"] == 1.0
    assert not (league / centers.RATING_CENTERS_FILENAME).exists()

    # Saving one slider stores that slider -- not the whole profile, which
    # would freeze today's profile numbers into the league's file.
    view = T.save_tuning({"overrides": _page_save(view, {"hr_scale": 1.05})}, ADMIN)
    assert _knobs(_stored(path)) == {"hr_scale": 1.05}
    assert view["overrides"] == {"hr_scale": 1.05}
    # A save is on the generation's scales, so it fixes the generation.
    stored = json.loads((league / centers.RATING_CENTERS_FILENAME).read_text())
    assert stored["seasons"]["2027"] == {"engine_generation": NEW}
    # A slider the profile moves can be overridden, and set back.
    view = T.save_tuning({"overrides": _page_save(view, {"foul_rate": 0.41})}, ADMIN)
    assert _knobs(_stored(path)) == {"hr_scale": 1.05, "foul_rate": 0.41}
    view = T.save_tuning(
        {"overrides": _page_save(view, {"foul_rate": PROFILE["foul_rate"]})}, ADMIN
    )
    assert _knobs(_stored(path)) == {"hr_scale": 1.05}
    assert T.reset_tuning(ADMIN)["overrides"] == {}
    assert not path.exists()


def test_a_league_s_sliders_change_at_its_rollover_not_before(league):
    path = league / S.TUNING_OVERRIDES_FILENAME
    write_schedule(league, 2026, played=6)
    path.write_text(json.dumps(LEGACY_FILE))
    before = path.read_text()
    view = T.get_tuning(ADMIN)
    assert view["engine"]["generation"] == LEGACY
    assert view["overrides"] == _knobs(LEGACY_FILE)
    assert path.read_text() == before

    roll_over(league, 2026)
    write_schedule(league, 2027)
    view = T.get_tuning(ADMIN)
    assert view["engine"]["generation"] == NEW
    assert view["overrides"] == S.convert_slider_overrides(_knobs(LEGACY_FILE))
    assert not set(S.LEGACY_SLIDER_KEYS) & set(_stored(path))
