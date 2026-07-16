import pytest

from playbalance.playbalance_config import PlayBalanceConfig
from playbalance.sim_config import apply_league_benchmarks


def test_apply_league_benchmarks():
    cfg = PlayBalanceConfig.from_dict({"hitHRProb": 5})
    benchmarks = {
        # Updated MLB benchmark BABIP
        "babip": 0.291,
        "pitches_put_in_play_pct": 0.175,
        "pitches_per_pa": 3.86,
        "bip_gb_pct": 0.44,
        "bip_fb_pct": 0.35,
        "bip_ld_pct": 0.21,
    }
    apply_league_benchmarks(cfg, benchmarks)
    assert cfg.hitProbBase == pytest.approx(0.291 * 1.5, abs=0.0001)
    assert cfg.ballInPlayPitchPct == 17
    # swingProbScale = round(3.85 / pitches_per_pa, 2) clamped to [0.9, 1.15].
    expected_scale = max(0.9, min(round(3.85 / benchmarks["pitches_per_pa"], 2), 1.15))
    assert cfg.swingProbScale == pytest.approx(expected_scale, abs=0.001)
    assert cfg.groundOutProb == pytest.approx(0.920, abs=0.001)
    assert cfg.lineOutProb == pytest.approx(0.387, abs=0.001)
    assert cfg.flyOutProb == pytest.approx(1.000, abs=0.001)
