"""Audit 2026-10-06 Release 2: KPI benchmark corrections and new metrics.

Covers the corrected benchmark rows (H2 steals, M3 HR counts), the hitter
K% sd rename (H6), the report-only tolerance group, the Statcast contact
quality metrics (M2/M3) and the engine's extra-base-taken tally (M7). All of
it is tooling: nothing here may change a game's outcome.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

import pytest

import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import load_tuning
from physics_sim.engine import (
    BaseState,
    _advance_on_hit,
    _tally_extra_bases_taken,
    simulate_matchup_from_files,
)
from physics_sim.models import BatterRatings

BENCHMARKS = Path("data/MLB_avg/mlb_league_benchmarks_2025_filled.csv")
CAL = Path("data/calibration")


def _runner(pid: str, speed: float = 50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid,
        bats="R",
        primary_position="LF",
        other_positions=[],
        contact=50.0,
        power=50.0,
        gb_tendency=50.0,
        pull_tendency=50.0,
        vs_left=50.0,
        fielding=50.0,
        arm=50.0,
        speed=speed,
        eye=50.0,
        height=72.0,
        durability=50.0,
    )


# --- benchmark CSV corrections ----------------------------------------------


def test_corrected_benchmark_rows() -> None:
    bench = kpis._load_benchmarks(BENCHMARKS)
    # H2: MLB 2023-24 team totals, not the old 0.050 (about 2x real MLB).
    assert bench["sba_per_pa"] == pytest.approx(0.025)
    assert bench["sb_per_team_game"] == pytest.approx(0.73)
    # M3: real MLB has ~20 qualified 30-HR and ~5 40-HR hitters a season.
    assert bench["qualified_hr30_count"] == pytest.approx(20.0)
    assert bench["qualified_hr40_count"] == pytest.approx(5.0)
    # H6: relabelled, same value.
    assert bench["qualified_hitter_k_pct_sd"] == pytest.approx(0.055)
    assert "qualified_k_pct_sd" not in bench


def test_mlb_team_totals_support_the_steal_benchmarks() -> None:
    """The H2 targets come from the repo's own MLB team totals (2023-24)."""
    import csv

    sb = cs = games = pa = 0.0
    with Path("data/MLB_avg/Teams_last5years.csv").open() as handle:
        for row in csv.DictReader(handle):
            if row["yearID"] not in {"2023", "2024"}:
                continue
            sb += float(row["SB"])
            cs += float(row["CS"])
            games += float(row["G"])
            pa += sum(float(row[k]) for k in ("AB", "BB", "HBP", "SF"))
    bench = kpis._load_benchmarks(BENCHMARKS)
    assert (sb + cs) / pa == pytest.approx(bench["sba_per_pa"], abs=0.001)
    assert sb / games == pytest.approx(bench["sb_per_team_game"], abs=0.02)


def test_report_only_and_strict_groups_do_not_overlap() -> None:
    overlap = set(kpis.DEFAULT_TOLERANCES) & set(kpis.REPORT_ONLY_TOLERANCES)
    assert not overlap


def test_every_report_only_gate_has_a_benchmark_row() -> None:
    bench = kpis._load_benchmarks(BENCHMARKS)
    missing = [key for key in kpis.REPORT_ONLY_TOLERANCES if key not in bench]
    assert not missing


def test_hr30_is_strict_and_hr40_can_fail_low() -> None:
    bench = kpis._load_benchmarks(BENCHMARKS)
    assert kpis.DEFAULT_TOLERANCES["qualified_hr30_count"] == pytest.approx(8.0)
    tol = kpis.REPORT_ONLY_TOLERANCES["qualified_hr40_count"]
    # The old 2.5 +/- 5.0 band could never fail on the low side.
    assert bench["qualified_hr40_count"] - tol > 0


def test_old_steal_volume_no_longer_fails_strict() -> None:
    """The engine's ~0.050 SBA/PA is reported, not gated, until Release 4."""
    bench = kpis._load_benchmarks(BENCHMARKS)
    metrics = {"sba_per_pa": 0.050, "sb_per_team_game": 1.42}
    assert not kpis.evaluate_tolerances(
        metrics=metrics, benchmarks=bench, tolerances=kpis.DEFAULT_TOLERANCES
    )
    rows = kpis.evaluate_report_only(
        metrics=metrics, benchmarks=bench, tolerances=kpis.REPORT_ONLY_TOLERANCES
    )
    by_key = {row["metric"]: row for row in rows}
    assert by_key["sba_per_pa"]["ok"] is False
    assert by_key["sb_per_team_game"]["ok"] is False
    # Metrics absent from this run are listed with ok=None, not dropped.
    assert by_key["hard_hit_pct"]["ok"] is None
    assert by_key["hard_hit_pct"]["value"] is None


def test_evaluate_report_only_passes_in_band() -> None:
    rows = kpis.evaluate_report_only(
        metrics={"barrel_pct": 0.080},
        benchmarks={"barrel_pct": 0.075},
        tolerances={"barrel_pct": 0.015},
    )
    assert rows == [
        {
            "metric": "barrel_pct",
            "value": 0.080,
            "target": 0.075,
            "delta": pytest.approx(0.005),
            "tolerance": 0.015,
            "ok": True,
        }
    ]
    text = kpis._format_report_only(rows)
    assert "barrel_pct" in text and "ok" in text


def test_tolerance_overrides_reach_both_groups_and_old_k_sd_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tol.json"
    path.write_text(
        json.dumps({"qualified_k_pct_sd": 0.02, "sba_per_pa": 0.009, "bogus": 1})
    )
    strict = kpis._load_tolerances(path)
    report = kpis._load_tolerances(path, kpis.REPORT_ONLY_TOLERANCES)
    assert strict["qualified_hitter_k_pct_sd"] == pytest.approx(0.02)
    assert "qualified_k_pct_sd" not in strict
    assert "sba_per_pa" not in strict
    assert report["sba_per_pa"] == pytest.approx(0.009)
    assert "bogus" not in strict and "bogus" not in report
    # No file -> the untouched defaults of the requested group.
    assert kpis._load_tolerances(None, kpis.REPORT_ONLY_TOLERANCES) == (
        kpis.REPORT_ONLY_TOLERANCES
    )


# --- Statcast contact quality -----------------------------------------------


@pytest.mark.parametrize(
    ("ev", "la", "expected"),
    [
        (98.0, 26.0, True),
        (98.0, 30.0, True),
        (98.0, 25.0, False),
        (98.0, 31.0, False),
        (97.9, 28.0, False),
        (99.0, 25.0, True),
        (99.0, 31.0, True),
        (100.0, 24.0, True),
        (100.0, 33.0, True),
        (100.0, 34.0, False),
        (116.0, 8.0, True),
        (116.0, 50.0, True),
        (116.0, 7.0, False),
        (120.0, 51.0, False),
        (120.0, 4.0, True),
        (120.0, 3.0, False),
    ],
)
def test_is_barrel_matches_statcast_windows(
    ev: float, la: float, expected: bool
) -> None:
    assert kpis._is_barrel(ev, la) is expected


def test_contact_quality_metrics() -> None:
    counts: Counter = Counter()
    for ev, la in [
        (100.0, 28.0),  # hard, sweet spot, barrel
        (95.0, 40.0),  # hard only
        (90.0, 10.0),  # sweet spot only
        (80.0, -20.0),  # nothing
        (96.0, None),  # hard; no angle -> left out of the angle-based rates
        (None, 20.0),  # no exit velocity -> not a tracked batted ball
    ]:
        kpis._record_contact_quality(counts, ev, la)
    m = kpis._contact_quality_metrics(counts)
    assert m["hard_hit_pct"] == pytest.approx(3 / 5)
    assert m["sweet_spot_pct"] == pytest.approx(2 / 4)
    assert m["barrel_pct"] == pytest.approx(1 / 4)
    assert kpis._contact_quality_metrics(Counter()) == {
        "hard_hit_pct": None,
        "barrel_pct": None,
        "sweet_spot_pct": None,
    }


# --- extra bases taken (engine tally) ---------------------------------------


def _tally(hit_type, before, after, scored=(), errors=()):
    totals: dict[str, int] = {"xbt_opp": 0, "xbt_taken": 0, "xbt_out": 0}
    _tally_extra_bases_taken(
        totals,
        hit_type=hit_type,
        runner_first=before.first,
        runner_second=before.second,
        bases=after,
        scored=list(scored),
        error_advances=list(errors),
    )
    return totals["xbt_opp"], totals["xbt_taken"], totals["xbt_out"]


def test_xbt_single_runner_on_second() -> None:
    bat, r2 = _runner("bat"), _runner("r2")
    before = BaseState(second=r2)
    assert _tally("single", before, BaseState(first=bat), scored=[r2]) == (1, 1, 0)
    assert _tally("single", before, BaseState(first=bat, third=r2)) == (1, 0, 0)
    assert _tally("single", before, BaseState(first=bat)) == (1, 0, 1)


def test_xbt_single_runner_on_first() -> None:
    bat, r1 = _runner("bat"), _runner("r1")
    before = BaseState(first=r1)
    assert _tally("single", before, BaseState(first=bat, third=r1)) == (1, 1, 0)
    assert _tally("single", before, BaseState(first=bat, second=r1)) == (1, 0, 0)
    assert _tally("single", before, BaseState(first=bat)) == (1, 0, 1)


def test_xbt_runner_on_first_blocked_by_lead_runner_holding() -> None:
    bat, r1, r2 = _runner("bat"), _runner("r1"), _runner("r2")
    before = BaseState(first=r1, second=r2)
    # Lead runner held at 3rd: only his chance counts; r1 had no open base.
    after = BaseState(first=bat, second=r1, third=r2)
    assert _tally("single", before, after) == (1, 0, 0)
    # Lead runner scored: both had a chance, both took the extra base.
    after = BaseState(first=bat, third=r1)
    assert _tally("single", before, after, scored=[r2]) == (2, 2, 0)


def test_xbt_double_runner_on_first() -> None:
    bat, r1 = _runner("bat"), _runner("r1")
    before = BaseState(first=r1)
    assert _tally("double", before, BaseState(second=bat), scored=[r1]) == (1, 1, 0)
    assert _tally("double", before, BaseState(second=bat, third=r1)) == (1, 0, 0)
    assert _tally("double", before, BaseState(second=bat)) == (1, 0, 1)


def test_xbt_error_advance_is_a_chance_but_not_taken_or_out() -> None:
    bat, r2 = _runner("bat"), _runner("r2")
    before = BaseState(second=r2)
    after = BaseState(first=bat)
    assert _tally("single", before, after, scored=[r2], errors=[r2]) == (1, 0, 0)


def test_xbt_no_chances_on_triples_or_forced_runners() -> None:
    bat, r1, r2, r3 = _runner("bat"), _runner("r1"), _runner("r2"), _runner("r3")
    # A triple clears the bases; runner on 3rd on a single and runner on 2nd
    # on a double always score, so none of those are chances.
    assert _tally("triple", BaseState(first=r1, second=r2), BaseState(third=bat)) == (
        0,
        0,
        0,
    )
    assert _tally("single", BaseState(third=r3), BaseState(first=bat), [r3]) == (
        0,
        0,
        0,
    )
    assert _tally("double", BaseState(second=r2), BaseState(second=bat), [r2]) == (
        0,
        0,
        0,
    )


def test_xbt_tally_is_read_only_and_draws_no_randomness() -> None:
    """Outcome neutrality: the tally neither rolls dice nor moves runners."""
    tuning = load_tuning()
    for seed in range(200):
        random.seed(seed)
        r1, r2, r3 = _runner("r1", 40 + seed % 40), _runner("r2"), _runner("r3")
        bases = BaseState(
            first=r1 if seed % 2 else None,
            second=r2 if seed % 3 else None,
            third=r3 if seed % 5 == 0 else None,
        )
        first, second = bases.first, bases.second
        hit_type = "double" if seed % 4 == 0 else "single"
        _runs, _outs, _events, scored, errors = _advance_on_hit(
            bases=bases,
            batter=_runner("bat"),
            hit_type=hit_type,
            defense_arm=50.0,
            tuning=tuning,
        )
        snapshot = (bases.first, bases.second, bases.third)
        state = random.getstate()
        totals: Counter = Counter()
        _tally_extra_bases_taken(
            totals,
            hit_type=hit_type,
            runner_first=first,
            runner_second=second,
            bases=bases,
            scored=scored,
            error_advances=errors,
        )
        assert random.getstate() == state
        assert (bases.first, bases.second, bases.third) == snapshot
        assert totals["xbt_taken"] + totals["xbt_out"] <= totals["xbt_opp"]


def test_engine_reports_xbt_counters_in_game_totals() -> None:
    opp = taken = out = 0
    for seed in range(3):
        result = simulate_matchup_from_files(
            away_team="CAL02",
            home_team="CAL01",
            players_path=CAL / "players.csv",
            base_dir=CAL,
            seed=seed,
        )
        opp += result.totals["xbt_opp"]
        taken += result.totals["xbt_taken"]
        out += result.totals["xbt_out"]
    assert opp > 0
    assert 0 <= taken + out <= opp
    metrics = kpis._extra_base_metrics(
        Counter(xbt_opp=opp, xbt_taken=taken, xbt_out=out)
    )
    assert metrics["extra_base_advance_rate"] == pytest.approx(taken / opp)
    assert metrics["extra_base_out_rate"] == pytest.approx(out / opp)


def test_extra_base_metrics_none_without_chances() -> None:
    assert kpis._extra_base_metrics(Counter()) == {
        "extra_base_advance_rate": None,
        "extra_base_out_rate": None,
    }
