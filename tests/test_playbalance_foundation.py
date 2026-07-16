"""Basic tests for the playbalance scaffolding."""
import pytest
from playbalance import (
    load_config,
    load_benchmarks,
    park_factors,
    weather_profile,
    league_averages,
    get_park_factor,
    league_average,
)


def test_load_config_sections():
    cfg = load_config()
    # The PBINI file is a single "PlayBalance" section with many entries.
    assert "PlayBalance" in cfg.sections
    assert cfg.get("PlayBalance", "speedBase") is not None
    # Attribute access exposes the same value.
    assert cfg.speedBase == cfg.sections["PlayBalance"].speedBase
    # JSON overrides should merge onto the PlayBalance section.
    assert cfg.hbpBatterStepOutChance == 80


def test_load_benchmarks_has_values():
    benchmarks = load_benchmarks()
    assert benchmarks["pitches_put_in_play_pct"] == pytest.approx(0.175, abs=0.0001)
    # Helper slices of the benchmark data
    pf = park_factors(benchmarks)
    assert pf["overall"] == 100.0
    # Unknown park falls back to league value
    assert get_park_factor(benchmarks, "hr", park="Nowhere") == 102.0
    weather = weather_profile(benchmarks)
    assert weather["temperature"] == 75.0
    avgs = league_averages(benchmarks)
    assert avgs["exit_velocity"] == 88.5
    assert league_average(benchmarks, "exit_velocity") == 88.5


def test_override_validation(tmp_path):
    # Unknown keys WITHIN a known section are rejected (typo protection). Flat
    # top-level keys are intentionally accepted as new defaults on the
    # PlayBalance section (see load_config: "Allow flat overrides"), so validate
    # the retained behavior: a bogus key nested under PlayBalance must raise.
    override = tmp_path / "override.json"
    override.write_text("{\"PlayBalance\": {\"unknownKey\": 1}}")
    with pytest.raises(KeyError):
        load_config(overrides_path=override)


def test_all_pbini_keys_present():
    cfg = load_config()
    # Compare keys in PBINI file to those exposed on the config dataclass.
    from playbalance.pbini_loader import load_pbini

    pbini_sections = load_pbini("playbalance/PBINI.txt")
    pb_keys = set(pbini_sections["PlayBalance"].keys())
    cfg_keys = set(cfg.sections["PlayBalance"].__dict__.keys())
    assert pb_keys <= cfg_keys
