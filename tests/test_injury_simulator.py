import random
from types import SimpleNamespace

from services.injury_simulator import (
    InjurySimulator,
    InjuryOutcome,
    load_injury_catalog,
)


def _player(is_pitcher: bool = False, durability: int = 70):
    return SimpleNamespace(
        player_id="P1",
        first_name="Test",
        last_name="Player",
        is_pitcher=is_pitcher,
        primary_position="P" if is_pitcher else "CF",
        durability=durability,
    )


class FixedRNG:
    def __init__(self, value: float = 0.5):
        self.value = value

    def random(self):
        return self.value

    def choice(self, seq):
        return seq[0]

    def randint(self, a, b):
        return a


def _catalog():
    return {
        "triggers": {
            "collision": {
                "base_probability": 1.0,
                "severities": ["minor", "moderate"],
            },
            "pitcher_overuse": {
                "base_probability": 1.0,
                "severities": ["major"],
            },
        },
        "injuries": [
            {
                "id": "bruise_test",
                "name": "Test Bruise",
                "body_part": "arm",
                "eligible_triggers": ["collision"],
                "severity_profiles": {
                    "minor": {"min_days": 2, "max_days": 2, "dl_tier": "none"},
                    "moderate": {"min_days": 5, "max_days": 5, "dl_tier": "dl15"},
                },
            },
            {
                "id": "pitcher_elbow",
                "name": "Elbow Soreness",
                "body_part": "elbow",
                "eligible_triggers": ["pitcher_overuse"],
                "pitcher_only": True,
                "severity_profiles": {
                    "major": {"min_days": 30, "max_days": 30, "dl_tier": "dl45"}
                },
            },
        ],
    }


def test_force_injury_returns_expected_outcome():
    sim = InjurySimulator(catalog=_catalog(), rng=random.Random(0))
    outcome = sim.maybe_create_injury("collision", _player(), force=True, severity_override="moderate")
    assert isinstance(outcome, InjuryOutcome)
    assert outcome.days == 5
    assert outcome.dl_tier == "dl15"
    assert outcome.severity == "moderate"


def test_pitcher_only_injury_respects_role():
    sim = InjurySimulator(catalog=_catalog())
    assert sim.maybe_create_injury("pitcher_overuse", _player(is_pitcher=False), force=True) is None
    outcome = sim.maybe_create_injury("pitcher_overuse", _player(is_pitcher=True), force=True)
    assert outcome is not None
    assert outcome.days == 30
    # The old "ir" is MLB's 60-day IL.
    assert outcome.dl_tier == "il60"


def test_probability_gate_can_block_injury(monkeypatch):
    cat = _catalog()
    cat["triggers"]["collision"]["base_probability"] = 0.0
    sim = InjurySimulator(catalog=cat, rng=random.Random(1))
    assert sim.maybe_create_injury("collision", _player(), force=False) is None


def test_durability_modifier_influences_probability():
    catalog = {
        "triggers": {
            "collision": {
                "base_probability": 0.5,
                "modifiers": {"durability_factor": -0.5},
                "severities": ["minor"],
            }
        },
        "injuries": [
            {
                "id": "test",
                "name": "Test Injury",
                "body_part": "arm",
                "eligible_triggers": ["collision"],
                "severity_profiles": {"minor": {"min_days": 1, "max_days": 1, "dl_tier": "none"}},
            }
        ],
    }
    rng = FixedRNG(value=0.3)
    sim = InjurySimulator(catalog=catalog, rng=rng)

    durable_player = _player(durability=100)
    assert sim.maybe_create_injury("collision", durable_player, force=False) is None

    fragile_player = _player(durability=1)
    outcome = sim.maybe_create_injury("collision", fragile_player, force=False)
    assert isinstance(outcome, InjuryOutcome)


def test_load_injury_catalog_bootstraps_missing_file(tmp_path):
    target = tmp_path / "injury_catalog.json"
    load_injury_catalog.cache_clear()
    catalog = load_injury_catalog(path=str(target))
    assert target.exists()
    assert catalog.get("triggers")
    assert catalog.get("injuries")
    load_injury_catalog.cache_clear()


def test_load_injury_catalog_recovers_from_corrupt_file(tmp_path):
    target = tmp_path / "injury_catalog.json"
    target.write_text("{broken")
    load_injury_catalog.cache_clear()
    catalog = load_injury_catalog(path=str(target))
    assert catalog.get("injuries")
    load_injury_catalog.cache_clear()
