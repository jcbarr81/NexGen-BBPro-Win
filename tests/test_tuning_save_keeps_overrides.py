"""Saving the tuning editor must keep the overrides it did not touch.

The API used to return the EFFECTIVE values as ``defaults``. The page saves
every knob that differs from ``defaults``, so it sent only the knobs changed
in that session and the save replaced the file with just those: a
commissioner who nudged one slider lost every earlier setting (and anything a
rule preset had applied).
"""

from __future__ import annotations

import json

import pytest

import api.routers.tuning as T
import services.physics_tuning_settings as S
from physics_sim.config import DEFAULT_TUNING
from services.physics_tuning_spec import tuning_sections

ADMIN = {"u": "commish", "r": "admin"}


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "physics_tuning_overrides.json"
    monkeypatch.setattr(S, "TUNING_OVERRIDES_PATH", path)
    return path


def _page_save(view: dict, changes: dict) -> dict:
    """What the tuning page sends: its draft, minus knobs equal to defaults."""
    draft = {**view["defaults"], **view["overrides"], **changes}
    return {
        key: float(value)
        for key, value in draft.items()
        if abs(float(value) - float(view["defaults"].get(key, 0.0))) > 1e-9
    }


def _stored(path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def test_defaults_are_the_engine_defaults_not_the_effective_values(overrides_file):
    S.save_physics_tuning_overrides({"hr_scale": 1.12})
    view = T.get_tuning(ADMIN)
    assert view["overrides"]["hr_scale"] == pytest.approx(1.12)
    assert view["defaults"]["hr_scale"] == pytest.approx(DEFAULT_TUNING["hr_scale"])
    # The effective value is still available to everything that plays games.
    assert S.load_physics_tuning_values()["hr_scale"] == pytest.approx(1.12)


def test_touching_one_slider_keeps_the_others(overrides_file):
    S.save_physics_tuning_overrides(
        {"hr_scale": 1.12, "babip_scale": 0.95, "walk_scale": 0.9}
    )
    view = T.get_tuning(ADMIN)
    T.save_tuning({"overrides": _page_save(view, {"babip_scale": 1.06})}, ADMIN)
    assert _stored(overrides_file) == pytest.approx(
        {"hr_scale": 1.12, "babip_scale": 1.06, "walk_scale": 0.9}
    )


def test_two_saves_in_a_row_keep_the_first(overrides_file):
    view = T.get_tuning(ADMIN)
    view = T.save_tuning({"overrides": _page_save(view, {"hr_scale": 1.0})}, ADMIN)
    T.save_tuning({"overrides": _page_save(view, {"walk_scale": 0.9})}, ADMIN)
    assert _stored(overrides_file) == pytest.approx(
        {"hr_scale": 1.0, "walk_scale": 0.9}
    )


def test_setting_a_slider_back_to_the_engine_default_drops_only_that_one(
    overrides_file,
):
    S.save_physics_tuning_overrides({"hr_scale": 1.12, "walk_scale": 0.9})
    view = T.get_tuning(ADMIN)
    back = {"hr_scale": view["defaults"]["hr_scale"]}
    T.save_tuning({"overrides": _page_save(view, back)}, ADMIN)
    assert _stored(overrides_file) == pytest.approx({"walk_scale": 0.9})


def test_a_key_set_outside_the_sliders_survives_a_save(overrides_file):
    """A rule preset writes knobs the page has no slider for."""
    hidden = next(
        key
        for key, value in DEFAULT_TUNING.items()
        if isinstance(value, float)
        and key not in {s.key for _, specs in tuning_sections(0) for s in specs}
    )
    S.save_physics_tuning_overrides({hidden: DEFAULT_TUNING[hidden] + 0.01})
    view = T.get_tuning(ADMIN)
    T.save_tuning({"overrides": _page_save(view, {"hr_scale": 1.05})}, ADMIN)
    stored = _stored(overrides_file)
    assert stored[hidden] == pytest.approx(DEFAULT_TUNING[hidden] + 0.01)
    assert stored["hr_scale"] == pytest.approx(1.05)
