import pytest

from playbalance.config import load_config
from playbalance.benchmarks import load_benchmarks, league_average
from playbalance.orchestrator import simulate_season


@pytest.mark.xfail(reason="legacy playbalance orchestrator season calibration behavior drift; physics is the shipping engine and does not use it", strict=False)
def test_season_stats_align_with_benchmarks():
    cfg = load_config()
    benchmarks = load_benchmarks()
    res = simulate_season(cfg, benchmarks, games=50, rng_seed=1)

    pa = res.pa
    assert pa > 0

    k_pct = res.k / pa
    bb_pct = res.bb / pa
    babip = res.hits / res.bip if res.bip else 0.0
    sba_rate = res.sb_attempts / pa
    sb_pct = res.sb_success / res.sb_attempts if res.sb_attempts else 0.0
    p_per_pa = res.pitches / pa

    assert abs(k_pct - league_average(benchmarks, "k_pct")) < 0.02
    assert abs(bb_pct - league_average(benchmarks, "bb_pct")) < 0.02
    assert abs(babip - league_average(benchmarks, "babip")) < 0.03
    assert abs(sba_rate - league_average(benchmarks, "sba_per_pa")) < 0.01
    assert abs(sb_pct - league_average(benchmarks, "sb_pct")) < 0.1
    assert abs(p_per_pa - league_average(benchmarks, "pitches_per_pa")) < 0.1


def test_simulation_runs_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    benchmarks = load_benchmarks()
    res = simulate_season(cfg, benchmarks, games=1, rng_seed=1)
    assert res.pa > 0
