from __future__ import annotations

import os

from scripts.smoke_multi_league import run_smoke


def test_run_smoke_includes_finance_isolation(tmp_path):
    data_root = tmp_path / "data"
    prior_data_dir = os.environ.get("NEXGEN_DATA_DIR")
    prior_active_league = os.environ.get("NEXGEN_ACTIVE_LEAGUE")
    try:
        report = run_smoke(data_root)
    finally:
        if prior_data_dir is None:
            os.environ.pop("NEXGEN_DATA_DIR", None)
        else:
            os.environ["NEXGEN_DATA_DIR"] = prior_data_dir
        if prior_active_league is None:
            os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
        else:
            os.environ["NEXGEN_ACTIVE_LEAGUE"] = prior_active_league

    checks = {entry["check"]: entry for entry in report["results"]}
    assert "finance_data_isolation" in checks
    assert checks["finance_data_isolation"]["status"] == "PASS"
