"""Release 4 gate promotion (plan section 5): the running game goes strict.

The defaults gate steal volume, WP/PB and five rule zero gates on
data/calibration and, since Release 4b became the default (7.49.0), extra
bases taken, sacrifice flies and ground-ball double plays; ``--gate-set
running`` gates the running game on data/calibration_league. All of it is
tooling: no test here simulates a game.
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

# Calibration seed 1 at 7.48.0 (Release 4a: the 4b models still switched
# off; bundle measurement at af31c436d). The gated metrics and the
# kpi_extras metrics they come from.
CAL_748_METRICS = {
    "sb_pct": 0.7745,
    "sba_per_pa": 0.0226,
    "sb_per_team_game": 0.6599,
    "triples_per_team_game": 0.1453,
    "runs_per_team_game": 4.2691,
    "bip_double_play_pct": 0.0230,
    "extra_base_advance_rate": 0.6830,
    "gidp_per_team_game": 0.5922,
}
CAL_748_EXTRAS = {
    "wp_per_team_game": 0.3317,
    "pb_per_team_game": 0.0537,
    "runs_on_inning_ending_plays": 0,
    "relief_60plus_pct": 0.002,
    "closer_third_straight_day": 0,
    "sf_per_pa": 0.0097,
    **{key: 0 for key in ZERO_GATES},
}
# The same seed at the 7.49.0 defaults (Release 4b on).
CAL_METRICS = {
    **CAL_748_METRICS,
    "sb_pct": 0.7771,
    "sba_per_pa": 0.0215,
    "sb_per_team_game": 0.6414,
    "triples_per_team_game": 0.1510,
    "runs_per_team_game": 4.4687,
    "bip_double_play_pct": 0.0271,
    "extra_base_advance_rate": 0.3770,
    "gidp_per_team_game": 0.7072,
}
CAL_EXTRAS = {
    **CAL_748_EXTRAS,
    "wp_per_team_game": 0.3255,
    "pb_per_team_game": 0.0525,
    "sf_per_pa": 0.0070,
}
FOUR_B_GATES = ("extra_base_advance_rate", "sf_per_pa", "gidp_per_team_game")


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
        # Release 4b, strict since 7.49.0.
        ("extra_base_advance_rate", 0.35, 0.45),
        ("sf_per_pa", 0.0058, 0.0078),
        ("gidp_per_team_game", 0.62, 0.74),
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


def test_4b_gates_are_default_strict_gates():
    for key in FOUR_B_GATES:
        assert key in kpis.DEFAULT_TOLERANCES
        assert key not in kpis.REPORT_ONLY_TOLERANCES
    # SF/PA is a kpi_extras metric, promoted with its target.
    assert kpis.STRICT_EXTRAS_TARGETS["sf_per_pa"] == pytest.approx(0.0068)
    # No gate set adds gates any more (the r4b profile set is gone).
    assert kpis.GATE_SET_TOLERANCES == {}
    assert kpis.GATE_SET_EXTRAS_TARGETS == {}
    assert kpis.strict_tolerances_for(None) == kpis.DEFAULT_TOLERANCES
    assert kpis.strict_tolerances_for("running") == kpis.DEFAULT_TOLERANCES
    assert kpis.strict_extras_targets_for(None) == kpis.STRICT_EXTRAS_TARGETS


def test_still_report_only():
    for key in (
        "k_reach_per_team_game",
        "corr_control_wp9",
        "corr_catcher_fa_pb",
        "re24_1b3b_0",
        "tagup_score_rate",
    ):
        assert key not in kpis.DEFAULT_TOLERANCES
        assert key not in kpis.STRICT_EXTRAS_TARGETS


def test_a_gate_set_can_still_add_gates(monkeypatch):
    """The hook the r4b profile used stays for the next built-but-off
    release: a set may add tolerances and promoted kpi_extras targets."""
    monkeypatch.setitem(kpis.GATE_SETS, "next", ["tagup_score_rate"])
    monkeypatch.setitem(kpis.GATE_SET_TOLERANCES, "next", {"tagup_score_rate": 0.03})
    monkeypatch.setitem(
        kpis.GATE_SET_EXTRAS_TARGETS, "next", {"tagup_score_rate": 0.75}
    )
    assert kpis.strict_tolerances_for("next")["tagup_score_rate"] == 0.03
    assert kpis.strict_extras_targets_for("next")["tagup_score_rate"] == 0.75
    assert "tagup_score_rate" not in kpis.strict_tolerances_for(None)
    extras = {**CAL_EXTRAS, "tagup_score_rate": 0.70}
    rows = _evaluate(CAL_METRICS, extras, "next")
    assert [row["metric"] for row in rows] == ["tagup_score_rate"]
    assert _evaluate(CAL_METRICS, {**extras, "tagup_score_rate": 0.74}, "next") == []


# --- the gate sets ------------------------------------------------------------


def test_running_gate_set_contents():
    assert set(kpis.GATE_SETS) == {"running"}
    assert set(kpis.GATE_SETS["running"]) == {
        "sb_pct",
        "sba_per_pa",
        "sb_per_team_game",
        *ZERO_GATES,
        "wp_per_team_game",
        "pb_per_team_game",
        "triples_per_team_game",
        "extra_base_advance_rate",
        "sf_per_pa",
    }
    # GIDP gates on data/calibration only: the league fixture's faster
    # batters sit at its floor (.62-.64 against .62).
    assert "gidp_per_team_game" not in kpis.GATE_SETS["running"]


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


def test_measured_season_passes_the_gates():
    assert _evaluate(CAL_METRICS, CAL_EXTRAS, None) == []
    assert _evaluate(CAL_METRICS, CAL_EXTRAS, "running") == []


def test_a_748_season_fails_exactly_the_4b_gates():
    # With the 4b models switched off (7.48.0) extra bases, sacrifice flies
    # and double plays sit far from MLB: the gates must catch a regression.
    failed = {row["metric"] for row in _evaluate(CAL_748_METRICS, CAL_748_EXTRAS, None)}
    assert failed == set(FOUR_B_GATES)
    failed = {
        row["metric"] for row in _evaluate(CAL_748_METRICS, CAL_748_EXTRAS, "running")
    }
    assert failed == {"extra_base_advance_rate", "sf_per_pa"}


@pytest.mark.parametrize("gate_set", [None, "running"])
@pytest.mark.parametrize(
    "key", [*ZERO_GATES, "wp_per_team_game", "pb_per_team_game", "sf_per_pa"]
)
def test_a_promoted_running_gate_that_was_not_computed_fails(gate_set, key):
    extras = dict(CAL_EXTRAS)
    extras[key] = None  # kpi_extras could not compute it (no event log)
    rows = _evaluate(CAL_METRICS, extras, gate_set)
    assert [row["metric"] for row in rows] == [key]
    assert math.isnan(rows[0]["value"])


@pytest.mark.parametrize("key", ZERO_GATES)
def test_a_zero_gate_above_zero_fails(key):
    extras = {**CAL_EXTRAS, key: 1}
    rows = _evaluate(CAL_METRICS, extras, "running")
    assert [row["metric"] for row in rows] == [key]


def test_a_nan_extra_counts_as_not_computed():
    extras = {**CAL_EXTRAS, "wp_per_team_game": float("nan")}
    rows = _evaluate(CAL_METRICS, extras, None)
    assert [row["metric"] for row in rows] == ["wp_per_team_game"]
    assert "not computed" in rows[0]["reason"]


def test_defaults_fail_when_sf_was_not_computed():
    extras = {**CAL_EXTRAS}
    del extras["sf_per_pa"]
    rows = _evaluate(CAL_METRICS, extras, None)
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


def test_main_defaults_promote_sf_and_gate_4b(monkeypatch, tmp_path):
    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_METRICS, CAL_EXTRAS, "--strict"
    )
    assert code == 0, summary["tolerance_failures"]
    assert summary["metrics"]["sf_per_pa"] == pytest.approx(0.0070)
    assert summary["tolerances"]["extra_base_advance_rate"] == pytest.approx(0.05)
    report_only = {r["metric"] for r in summary["report_only_gates"]["results"]}
    assert not report_only & set(FOUR_B_GATES)

    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_748_METRICS, CAL_748_EXTRAS, "--strict"
    )
    assert code == 2
    failed = {row["metric"] for row in summary["tolerance_failures"]}
    assert failed == set(FOUR_B_GATES)


def test_main_running_set_fails_on_a_missing_zero_gate(monkeypatch, tmp_path):
    extras = {k: v for k, v in CAL_EXTRAS.items() if k != "illegal_k_reach"}
    code, summary = _run_main(
        monkeypatch, tmp_path, CAL_METRICS, extras,
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


def test_ci_runs_the_calibration_and_running_gates_strictly():
    steps = _kpi_steps()
    calibration = steps["Run KPI harness (strict, calibration fixture)"]
    assert "--strict" in calibration and "--gate-set" not in calibration

    running = steps["Run KPI harness (strict running game, league-like fixture)"]
    assert "--strict" in running
    assert "--gate-set running" in running
    assert "data/calibration_league" in running

    # Release 4b is the default: no step runs a tuning profile any more.
    for script in steps.values():
        assert "--tuning-overrides" not in script
        assert "kpi_profiles" not in script

    for script in steps.values():
        for name in kpis.GATE_SETS:
            script = script.replace(f"--gate-set {name}", "")
        assert "--gate-set" not in script, "unknown gate set in the workflow"
