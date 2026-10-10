"""Release 4 gate promotion (plan section 5): the running game goes strict.

4a (the defaults) gates steal volume, WP/PB and five rule zero gates on
data/calibration; ``--gate-set running`` gates the running game on
data/calibration_league; ``--gate-set r4b`` adds the 4b gates (XBT, SF/PA,
GIDP) for runs with scripts/kpi_profiles/r4b.json. All of it is tooling: no
test here simulates a game.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

import scripts.physics_sim_season_kpis as kpis
from scripts import kpi_extras

REPO = Path(__file__).resolve().parents[1]
BENCHMARKS = REPO / "data" / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
WORKFLOW = REPO / ".github" / "workflows" / "physics_sim_kpi.yml"

ZERO_GATES = (
    "steal_events_on_foul",
    "wp_pb_on_foul",
    "wp_pb_bases_empty",
    "double_steal_two_out_plays",
    "illegal_k_reach",
)

# Calibration seed 1 at 7.48.0 (4a defaults; bundle measurement at
# af31c436d). The gated metrics and the kpi_extras metrics they come from.
CAL_4A_METRICS = {
    "sb_pct": 0.7745,
    "sba_per_pa": 0.0226,
    "sb_per_team_game": 0.6599,
    "triples_per_team_game": 0.1453,
    "runs_per_team_game": 4.2691,
    "bip_double_play_pct": 0.0230,
    "extra_base_advance_rate": 0.6830,
    "gidp_per_team_game": 0.5922,
}
CAL_4A_EXTRAS = {
    "wp_per_team_game": 0.3317,
    "pb_per_team_game": 0.0537,
    "runs_on_inning_ending_plays": 0,
    "relief_60plus_pct": 0.002,
    "closer_third_straight_day": 0,
    "sf_per_pa": 0.0097,
    **{key: 0 for key in ZERO_GATES},
}
# The same seed with the r4b profile.
CAL_4B_METRICS = {
    **CAL_4A_METRICS,
    "sb_pct": 0.7784,
    "sba_per_pa": 0.0208,
    "sb_per_team_game": 0.6222,
    "triples_per_team_game": 0.1377,
    "runs_per_team_game": 4.4796,
    "bip_double_play_pct": 0.0266,
    "extra_base_advance_rate": 0.3765,
    "gidp_per_team_game": 0.6936,
}
CAL_4B_EXTRAS = {
    **CAL_4A_EXTRAS,
    "wp_per_team_game": 0.3716,
    "pb_per_team_game": 0.0556,
    "sf_per_pa": 0.0070,
}


def _references(gate_set: str | None) -> dict[str, float]:
    """Targets the way main() resolves them (benchmark CSV first)."""
    targets = {
        "platoon_gap_woba": 0.026,
        **kpis.RATING_OUTCOME_TARGETS,
        **kpis.strict_extras_targets_for(gate_set),
    }
    return {**targets, **kpis._load_benchmarks(BENCHMARKS)}


# --- the bands ---------------------------------------------------------------


@pytest.mark.parametrize(
    "key, low, high",
    [
        ("sba_per_pa", 0.020, 0.030),
        ("sb_per_team_game", 0.61, 0.85),
        ("wp_per_team_game", 0.25, 0.41),
        ("pb_per_team_game", 0.02, 0.08),
        ("sb_pct", 0.73, 0.83),
    ],
)
def test_running_gates_are_strict_with_plan_bands(key, low, high):
    target = _references(None)[key]
    tol = kpis.DEFAULT_TOLERANCES[key]
    assert target - tol == pytest.approx(low)
    assert target + tol == pytest.approx(high)
    assert key not in kpis.REPORT_ONLY_TOLERANCES


def test_zero_gates_are_strict_extras_at_zero():
    for key in ZERO_GATES:
        assert kpis.DEFAULT_TOLERANCES[key] == 0.0
        assert kpis.STRICT_EXTRAS_TARGETS[key] == 0.0


def test_4b_gates_stay_off_the_default_strict_set():
    for key in kpis.R4B_TOLERANCES:
        assert key not in kpis.DEFAULT_TOLERANCES
    refs = _references("r4b")
    tolerances = kpis.strict_tolerances_for("r4b")
    bands = {
        "extra_base_advance_rate": (0.35, 0.45),
        "sf_per_pa": (0.0058, 0.0078),
        "gidp_per_team_game": (0.62, 0.74),
    }
    for key, (low, high) in bands.items():
        assert refs[key] - tolerances[key] == pytest.approx(low)
        assert refs[key] + tolerances[key] == pytest.approx(high)
    # Report-only at the 4a defaults (sf_per_pa is a kpi_extras row).
    assert "extra_base_advance_rate" in kpis.REPORT_ONLY_TOLERANCES
    assert "gidp_per_team_game" in kpis.REPORT_ONLY_TOLERANCES
    assert kpis.strict_tolerances_for(None) == kpis.DEFAULT_TOLERANCES
    assert kpis.strict_tolerances_for("running") == kpis.DEFAULT_TOLERANCES
    assert kpis.strict_extras_targets_for(None) == kpis.STRICT_EXTRAS_TARGETS


def test_still_report_only_in_4a():
    for key in (
        "k_reach_per_team_game",
        "corr_control_wp9",
        "corr_catcher_fa_pb",
        "re24_1b3b_0",
        "tagup_score_rate",
        "extra_base_advance_rate",
        "sf_per_pa",
        "gidp_per_team_game",
    ):
        assert key not in kpis.DEFAULT_TOLERANCES
        assert key not in kpis.STRICT_EXTRAS_TARGETS


# --- the gate sets ------------------------------------------------------------


def test_running_gate_set_contents():
    assert set(kpis.GATE_SETS["running"]) == {
        "sb_pct",
        "sba_per_pa",
        "sb_per_team_game",
        *ZERO_GATES,
        "wp_per_team_game",
        "pb_per_team_game",
        "triples_per_team_game",
    }
    r4b = set(kpis.GATE_SETS["r4b"])
    assert set(kpis.R4B_TOLERANCES) <= r4b
    # Steal volume is left to the defaults: the profile puts seed 1 near the
    # floor, and the CI step must not flake on it.
    volume = {"sba_per_pa", "sb_per_team_game"}
    assert set(kpis.GATE_SETS["running"]) - volume <= r4b
    assert not volume & r4b
    assert {
        "runs_on_inning_ending_plays",
        "bip_double_play_pct",
        "runs_per_team_game",
    } <= r4b


@pytest.mark.parametrize("name", sorted(kpis.GATE_SETS))
def test_every_gate_set_key_has_a_tolerance_and_a_target(name):
    # gate_set_failures fails a listed key with neither (W0), so a gap here
    # would fail every CI run of the set.
    keys = kpis.GATE_SETS[name]
    assert keys, f"gate set {name} is empty"
    assert len(keys) == len(set(keys))
    tolerances = kpis.strict_tolerances_for(name)
    refs = _references(name)
    assert [k for k in keys if k not in tolerances] == []
    assert [k for k in keys if k not in refs] == []


def test_every_promoted_extra_is_produced_by_kpi_extras():
    produced = set(
        kpi_extras.ReportOnlyKpis(
            players_path=Path("missing.csv"), games_per_team=162
        ).finalize({})["metrics"]
    )
    for name in [None, *kpis.GATE_SETS]:
        assert set(kpis.strict_extras_targets_for(name)) <= produced


def test_reference_rows_match_the_promoted_targets():
    reference = kpi_extras.load_reference()
    for name in [None, *kpis.GATE_SETS]:
        for key, target in kpis.strict_extras_targets_for(name).items():
            assert reference[key]["value"] == pytest.approx(target), key
    bench = kpis._load_benchmarks(BENCHMARKS)
    assert bench["extra_base_advance_rate"] == pytest.approx(0.40)
    assert bench["gidp_per_team_game"] == pytest.approx(0.68)


def test_new_reference_rows():
    reference = kpi_extras.load_reference()
    expected = {
        "sba_per_tof": 0.103,
        "cs_per_team_game": 0.19,
        "wp_per_team_game": 0.33,
        "pb_per_team_game": 0.05,
        "k_reach_per_team_game": 0.06,
        "xbt_logged_rate": 0.40,
        "sf_per_pa": 0.0068,
        "r1_first_to_third_on_single_pct": 0.28,
        "r2_scores_on_single_pct": 0.60,
        "r1_scores_on_double_pct": 0.42,
        "tagup_score_rate": 0.75,
    }
    for key, value in expected.items():
        assert reference[key]["value"] == pytest.approx(value), key
        assert reference[key]["source"], key


def test_mlb_team_totals_support_the_new_rows():
    """sba_per_tof, CS/G and SF/PA come from the repo's MLB team totals
    (2023-24, the pitch-clock seasons, as the steal benchmarks do)."""
    import csv

    totals = dict.fromkeys(("sb", "cs", "tof", "g", "sf", "pa"), 0.0)
    with (REPO / "data" / "MLB_avg" / "Teams_last5years.csv").open() as handle:
        for row in csv.DictReader(handle):
            if row["yearID"] not in {"2023", "2024"}:
                continue
            singles = float(row["H"]) - sum(
                float(row[k]) for k in ("2B", "3B", "HR")
            )
            totals["sb"] += float(row["SB"])
            totals["cs"] += float(row["CS"])
            totals["g"] += float(row["G"])
            totals["sf"] += float(row["SF"])
            totals["tof"] += singles + float(row["BB"]) + float(row["HBP"])
            totals["pa"] += sum(float(row[k]) for k in ("AB", "BB", "HBP", "SF"))
    reference = kpi_extras.load_reference()
    sba_tof = (totals["sb"] + totals["cs"]) / totals["tof"]
    assert sba_tof == pytest.approx(reference["sba_per_tof"]["value"], abs=0.001)
    cs_g = totals["cs"] / totals["g"]
    assert cs_g == pytest.approx(reference["cs_per_team_game"]["value"], abs=0.002)
    sf_pa = totals["sf"] / totals["pa"]
    assert sf_pa == pytest.approx(reference["sf_per_pa"]["value"], abs=0.0001)


# --- evaluation ---------------------------------------------------------------


def _evaluate(metrics, extras, gate_set):
    summary = {"metrics": dict(metrics), "report_only": {"metrics": dict(extras)}}
    tolerances = kpis.strict_tolerances_for(gate_set)
    extras_targets = kpis.strict_extras_targets_for(gate_set)
    missing = kpis._promote_extras_metrics(summary, tolerances, extras_targets)
    targets = {
        "platoon_gap_woba": 0.026,
        **kpis.RATING_OUTCOME_TARGETS,
        **extras_targets,
    }
    failures = kpis.evaluate_tolerances(
        metrics=summary["metrics"],
        benchmarks=kpis._load_benchmarks(BENCHMARKS),
        tolerances=tolerances,
        targets=targets,
    ) + missing
    if gate_set is None:
        return failures
    return kpis.gate_set_failures(
        gate_set,
        metrics=summary["metrics"],
        tolerances=tolerances,
        failures=failures,
        references=set(kpis._load_benchmarks(BENCHMARKS)) | set(targets),
    )


def test_measured_4a_season_passes_the_new_gates():
    assert _evaluate(CAL_4A_METRICS, CAL_4A_EXTRAS, None) == []
    assert _evaluate(CAL_4A_METRICS, CAL_4A_EXTRAS, "running") == []


def test_measured_4b_season_passes_the_r4b_set():
    assert _evaluate(CAL_4B_METRICS, CAL_4B_EXTRAS, "r4b") == []
    assert _evaluate(CAL_4B_METRICS, CAL_4B_EXTRAS, None) == []


def test_4a_xbt_and_gidp_fail_only_the_r4b_set():
    # The 4a defaults sit far from the 4b targets: not strict by default.
    failed = {row["metric"] for row in _evaluate(CAL_4A_METRICS, CAL_4A_EXTRAS, "r4b")}
    assert failed == {"extra_base_advance_rate", "sf_per_pa", "gidp_per_team_game"}


@pytest.mark.parametrize("gate_set", [None, "running", "r4b"])
@pytest.mark.parametrize("key", [*ZERO_GATES, "wp_per_team_game", "pb_per_team_game"])
def test_a_promoted_running_gate_that_was_not_computed_fails(gate_set, key):
    metrics = CAL_4B_METRICS if gate_set == "r4b" else CAL_4A_METRICS
    extras = dict(CAL_4B_EXTRAS if gate_set == "r4b" else CAL_4A_EXTRAS)
    extras[key] = None  # kpi_extras could not compute it (no event log)
    rows = _evaluate(metrics, extras, gate_set)
    assert [row["metric"] for row in rows] == [key]
    assert math.isnan(rows[0]["value"])


@pytest.mark.parametrize("key", ZERO_GATES)
def test_a_zero_gate_above_zero_fails(key):
    extras = {**CAL_4A_EXTRAS, key: 1}
    rows = _evaluate(CAL_4A_METRICS, extras, "running")
    assert [row["metric"] for row in rows] == [key]


def test_a_nan_extra_counts_as_not_computed():
    extras = {**CAL_4A_EXTRAS, "wp_per_team_game": float("nan")}
    rows = _evaluate(CAL_4A_METRICS, extras, None)
    assert [row["metric"] for row in rows] == ["wp_per_team_game"]
    assert "not computed" in rows[0]["reason"]


def test_r4b_set_fails_when_sf_was_not_computed():
    extras = {**CAL_4B_EXTRAS}
    del extras["sf_per_pa"]
    rows = _evaluate(CAL_4B_METRICS, extras, "r4b")
    assert [row["metric"] for row in rows] == ["sf_per_pa"]


# --- main() ------------------------------------------------------------------


def _run_main(monkeypatch, tmp_path, metrics, extras, *args):
    summary = {
        "metrics": dict(metrics),
        "report_only": {"metrics": dict(extras), "tables": {}, "coverage": {}},
    }
    monkeypatch.setattr(
        kpis, "run_sim", lambda *a, **k: json.loads(json.dumps(summary))
    )
    monkeypatch.setattr(kpis.kpi_extras, "format_report", lambda r: "")
    out = tmp_path / "kpis.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["physics_sim_season_kpis.py", "--games", "1", "--output", str(out), *args],
    )
    code = 0
    try:
        kpis.main()
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_main_gate_set_r4b_promotes_sf_and_gates_4b(monkeypatch, tmp_path):
    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_4B_METRICS, CAL_4B_EXTRAS,
        "--strict", "--gate-set", "r4b",
    )
    assert code == 0
    assert summary["gate_set"]["ok"] is True
    assert summary["metrics"]["sf_per_pa"] == pytest.approx(0.0070)
    assert summary["tolerances"]["extra_base_advance_rate"] == pytest.approx(0.05)

    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_4A_METRICS, CAL_4A_EXTRAS,
        "--strict", "--gate-set", "r4b",
    )
    assert code == 2
    failed = {row["metric"] for row in summary["gate_set"]["failures"]}
    assert failed == {"extra_base_advance_rate", "sf_per_pa", "gidp_per_team_game"}


def test_main_defaults_do_not_gate_4b(monkeypatch, tmp_path):
    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_4A_METRICS, CAL_4A_EXTRAS, "--strict"
    )
    assert code == 0, summary["tolerance_failures"]
    assert "sf_per_pa" not in summary["metrics"]
    assert "extra_base_advance_rate" not in summary["tolerances"]
    rows = {r["metric"]: r for r in summary["report_only_gates"]["results"]}
    assert rows["extra_base_advance_rate"]["ok"] is False
    assert rows["gidp_per_team_game"]["ok"] is False


def test_main_running_set_fails_on_a_missing_zero_gate(monkeypatch, tmp_path):
    extras = {k: v for k, v in CAL_4A_EXTRAS.items() if k != "illegal_k_reach"}
    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_4A_METRICS, extras,
        "--strict", "--gate-set", "running",
    )
    assert code == 2
    assert [r["metric"] for r in summary["gate_set"]["failures"]] == [
        "illegal_k_reach"
    ]


# --- CI ------------------------------------------------------------------------


def _kpi_steps() -> dict[str, str]:
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["physics-sim-kpis"]["steps"]
    return {
        step["name"]: step["run"]
        for step in steps
        if "physics_sim_season_kpis.py" in step.get("run", "")
    }


def test_ci_runs_the_running_and_r4b_gate_sets_strictly():
    steps = _kpi_steps()
    calibration = steps["Run KPI harness (strict, calibration fixture)"]
    assert "--strict" in calibration and "--gate-set" not in calibration
    assert "--tuning-overrides" not in calibration

    running = steps["Run KPI harness (strict running game, league-like fixture)"]
    assert "--strict" in running
    assert "--gate-set running" in running
    assert "data/calibration_league" in running

    r4b = steps["Run KPI harness (strict 4b gates, r4b profile)"]
    assert "--strict" in r4b
    assert "--gate-set r4b" in r4b
    assert "--tuning-overrides scripts/kpi_profiles/r4b.json" in r4b
    assert "--base-dir data/calibration " in r4b.replace("\\", " ")

    for script in steps.values():
        for name in kpis.GATE_SETS:
            script = script.replace(f"--gate-set {name}", "")
        assert "--gate-set" not in script, "unknown gate set in the workflow"
