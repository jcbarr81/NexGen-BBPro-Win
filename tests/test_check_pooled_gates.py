"""scripts/check_pooled_gates.py: the pooled gates over a set of seasons."""

from __future__ import annotations

import json

import scripts.check_pooled_gates as checker
import scripts.physics_sim_season_kpis as kpis


def _season(tmp_path, name, report, metrics=None):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({
        "metrics": metrics or {}, "report_only": {"metrics": report},
    }), encoding="utf-8")
    return path


def test_a_mean_inside_every_band_passes_and_one_outside_fails(tmp_path):
    gates = kpis.ENGINE_GATES[7]["pooled"]
    good = {key: target for key, (target, _band) in gates.items()}
    paths = [_season(tmp_path, f"s{i}", good) for i in range(3)]
    rows = checker.pooled_results(7, paths)
    assert {row["metric"] for row in rows} == set(gates)
    assert all(row["ok"] and row["seasons"] == 3 for row in rows)
    # One season far out: the mean decides, not the season.
    key = "qualified_hr30_count"
    target, band = gates[key]
    noisy = [_season(tmp_path, f"n{i}", {**good, key: target + 1.5 * band * (1 if i else -1)})
             for i in range(2)]
    row = {r["metric"]: r for r in checker.pooled_results(7, noisy)}[key]
    assert row["ok"] and row["seasons"] == 2
    far = [_season(tmp_path, f"f{i}", {**good, key: target + 2 * band}) for i in range(2)]
    assert not {r["metric"]: r for r in checker.pooled_results(7, far)}[key]["ok"]
    # A metric no file has fails.
    missing = [_season(tmp_path, "m", {})]
    assert not any(row["ok"] for row in checker.pooled_results(7, missing))
