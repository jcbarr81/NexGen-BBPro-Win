"""The seeded data/injury_catalog.json must be a real, varied catalog (not the
3-injury fallback) AND stay calibration-neutral: its trigger probabilities /
modifiers / severity lists are identical to the engine's built-in fallback, so
injury frequency and severity mix are unchanged — only the variety of resulting
injuries widens.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import injury_simulator as isim

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "injury_catalog.json"
# The simulator emits MLB list names. "dl15" survives as the "standard
# stint" marker that injury_manager resolves by role (10-day for a
# position player, 15-day for a pitcher).
VALID_TIERS = {"none", "dl15", "il7", "il10", "il15", "il60"}
VALID_ATTRS = {"pow", "con", "spd", "vel", "ctrl", "sta"}


@pytest.fixture(scope="module")
def catalog():
    assert CATALOG_PATH.exists(), f"missing seed catalog at {CATALOG_PATH}"
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_is_real_catalog_not_fallback(catalog):
    assert catalog["metadata"]["name"] != "Auto-generated fallback"
    # Meaningfully richer than the 3-injury fallback.
    assert len(catalog["injuries"]) >= 15


def test_triggers_identical_to_fallback_calibration_neutral(catalog):
    # The strongest guarantee: identical trigger blocks => identical injury
    # frequency + severity selection as what the engine was calibrated against.
    assert catalog["triggers"] == isim._FALLBACK_INJURY_CATALOG["triggers"]


def test_schema_valid(catalog):
    seen_ids = set()
    for inj in catalog["injuries"]:
        assert inj["id"] and inj["id"] not in seen_ids, f"dup/blank id {inj.get('id')}"
        seen_ids.add(inj["id"])
        assert inj["name"] and inj["body_part"]
        assert inj["eligible_triggers"], f"{inj['id']} has no triggers"
        assert inj["severity_profiles"], f"{inj['id']} has no severities"
        for sev, prof in inj["severity_profiles"].items():
            assert sev in {"minor", "moderate", "major"}
            assert 1 <= prof["min_days"] <= prof["max_days"]
            assert isim.InjurySimulator._normalize_tier(prof["dl_tier"]) in VALID_TIERS
            for attr in (prof.get("attributes_penalty") or {}):
                assert attr in VALID_ATTRS, f"{inj['id']} unknown attr {attr}"


def test_no_dead_trigger_severity_combos(catalog):
    # Every (trigger, severity) the engine can roll must have >=1 eligible injury,
    # otherwise that roll silently produces nothing.
    injuries = catalog["injuries"]
    for trigger, tdef in catalog["triggers"].items():
        for severity in tdef["severities"]:
            eligible = [
                i for i in injuries
                if trigger in i["eligible_triggers"] and severity in i["severity_profiles"]
            ]
            assert eligible, f"no injury for trigger={trigger} severity={severity}"


def test_every_combo_is_consumable_by_the_simulator(catalog):
    sim = isim.InjurySimulator(catalog=catalog)
    pitcher = SimpleNamespace(player_id="P1", is_pitcher=True, primary_position="P", durability=50)
    hitter = SimpleNamespace(player_id="H1", is_pitcher=False, primary_position="1B", durability=50)
    for trigger, tdef in catalog["triggers"].items():
        player = pitcher if trigger == "pitcher_overuse" else hitter
        for severity in tdef["severities"]:
            outcome = sim.maybe_create_injury(
                trigger, player, force=True, severity_override=severity
            )
            assert outcome is not None, f"sim produced nothing for {trigger}/{severity}"
            assert outcome.days >= 1
            assert outcome.dl_tier in VALID_TIERS


def test_variety_of_body_parts(catalog):
    parts = {i["body_part"] for i in catalog["injuries"]}
    assert len(parts) >= 8, f"expected varied body parts, got {sorted(parts)}"
