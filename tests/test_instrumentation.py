import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from playbalance.legacy_guard import legacy_enabled

ROOT = Path(__file__).resolve().parents[1]
SIM_SCRIPT = ROOT / "scripts" / "playbalance_simulate.py"

# playbalance_simulate.py is the ARCHIVED legacy sim CLI (require_legacy_enabled
# -> non-zero exit). The physics sim + KPI harness are the shipping path. Skip
# unless the legacy engine is explicitly enabled.
pytestmark = pytest.mark.skipif(
    not legacy_enabled(),
    reason="Legacy playbalance_simulate.py archived; set PB_ALLOW_LEGACY_ENGINE=1 to run.",
)


def test_playbalance_sim_cli_emits_pitch_counts(tmp_path):
    """Smoke test: run a short sim with diagnostics and ensure JSON contains new fields."""

    output_path = tmp_path / "results.json"
    diag_path = tmp_path / "diag.json"
    env = os.environ.copy()
    env["SWING_DIAGNOSTICS"] = "1"

    cmd = [
        sys.executable,
        str(SIM_SCRIPT),
        "--games",
        "44",
        "--seed",
        "1",
        "--no-progress",
        "--output",
        str(output_path),
        "--diag-output",
        str(diag_path),
    ]
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    data = json.loads(output_path.read_text())
    pitch_counts = data["pitch_counts"]
    assert pitch_counts["pitches_thrown"] > 0
    assert pitch_counts["strikes_thrown"] + pitch_counts["balls_thrown"] > 0
    assert "zone_pitches" in pitch_counts

    objectives = data["pitch_objectives"]
    total_logged = objectives["total_logged"]
    assert total_logged == (
        objectives["attack"] + objectives["chase"] + objectives["waste"]
    )

    diag = json.loads(diag_path.read_text())
    assert isinstance(diag.get("events"), list)
    batter_diag = diag.get("batter_decisions"); assert batter_diag
    assert batter_diag["counts"], "expected batter decision breakdowns"
    assert batter_diag["distance_histogram"], "expected pitch distance histogram"
    assert "avg_pitch_distance" in batter_diag["counts"][0]
    intent_diag = diag.get("pitch_intent"); assert intent_diag
    assert intent_diag["bucket_counts"], "expected pitch intent bucket counts"
