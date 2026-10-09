import math
from collections import Counter

import pytest

from scripts import kpi_extras
from scripts import physics_sim_season_kpis as kpis
from scripts.physics_sim_season_kpis import (
    _build_rating_splits,
    _decile_groups,
    evaluate_tolerances,
)


def test_evaluate_tolerances_flags_violation() -> None:
    metrics = {"k_pct": 0.3}
    benchmarks = {"k_pct": 0.2}
    tolerances = {"k_pct": 0.05}
    failures = evaluate_tolerances(
        metrics=metrics,
        benchmarks=benchmarks,
        tolerances=tolerances,
    )
    assert failures
    assert failures[0]["metric"] == "k_pct"


def test_decile_groups_selects_edges() -> None:
    ratings = {f"P{i}": float(i) for i in range(10)}
    bottom, top = _decile_groups(ratings)
    assert bottom == {"P0"}
    assert top == {"P9"}


def test_build_rating_splits_returns_expected_keys() -> None:
    batter_totals = {
        "B1": Counter(pa=10, ab=10, h=4, bb=1, so=2, hr=1),
        "B2": Counter(pa=12, ab=12, h=6, bb=0, so=1, hr=0),
        "B3": Counter(pa=8, ab=8, h=2, bb=0, so=3, hr=0),
        "B4": Counter(pa=9, ab=9, h=3, bb=1, so=2, hr=1),
        "B5": Counter(pa=11, ab=11, h=5, bb=1, so=1, hr=0),
        "B6": Counter(pa=7, ab=7, h=2, bb=0, so=2, hr=0),
        "B7": Counter(pa=10, ab=10, h=4, bb=1, so=2, hr=0),
        "B8": Counter(pa=10, ab=10, h=4, bb=1, so=2, hr=1),
        "B9": Counter(pa=10, ab=10, h=4, bb=1, so=2, hr=0),
        "B10": Counter(pa=10, ab=10, h=4, bb=1, so=2, hr=0),
    }
    pitcher_totals = {
        "P1": Counter(bf=20, outs=15, er=2, h=4, bb=2, so=5, hr=1),
        "P2": Counter(bf=18, outs=12, er=3, h=5, bb=3, so=4, hr=1),
        "P3": Counter(bf=22, outs=18, er=1, h=3, bb=1, so=6, hr=0),
        "P4": Counter(bf=16, outs=12, er=2, h=5, bb=2, so=3, hr=1),
        "P5": Counter(bf=24, outs=18, er=2, h=4, bb=2, so=7, hr=1),
        "P6": Counter(bf=19, outs=15, er=3, h=6, bb=3, so=3, hr=1),
        "P7": Counter(bf=21, outs=18, er=2, h=4, bb=2, so=5, hr=0),
        "P8": Counter(bf=17, outs=12, er=2, h=4, bb=2, so=4, hr=1),
        "P9": Counter(bf=20, outs=15, er=1, h=3, bb=1, so=6, hr=0),
        "P10": Counter(bf=18, outs=12, er=3, h=5, bb=3, so=4, hr=1),
    }
    contact = {player_id: 40.0 + idx for idx, player_id in enumerate(batter_totals)}
    power = {player_id: 60.0 + idx for idx, player_id in enumerate(batter_totals)}
    control = {player_id: 50.0 + idx for idx, player_id in enumerate(pitcher_totals)}
    splits = _build_rating_splits(
        batter_totals=batter_totals,
        pitcher_totals=pitcher_totals,
        contact=contact,
        power=power,
        control=control,
    )
    assert "batters" in splits
    assert "pitchers" in splits
    assert "contact" in splits["batters"]
    assert "power" in splits["batters"]
    assert "control" in splits["pitchers"]


# --- Release 3 strict-gate changes (plan section 4) -------------------------


def test_platoon_gap_widening_is_the_documented_temporary_value() -> None:
    # Owner decision Q2 (2026-10-07): 0.006 -> 0.009 until the Release 5
    # platoon retune (H7); restore 0.006 then.
    tol = kpis.DEFAULT_TOLERANCES["platoon_gap_woba"]
    assert tol == pytest.approx(0.009)
    failures = evaluate_tolerances(
        metrics={"platoon_gap_woba": 0.0334},
        benchmarks={},
        tolerances={"platoon_gap_woba": tol},
        targets={"platoon_gap_woba": 0.026},
    )
    assert not failures


def test_promoted_extras_are_strict_with_matching_reference_rows() -> None:
    promoted = kpis.STRICT_EXTRAS_TARGETS
    assert set(promoted) == {
        "runs_on_inning_ending_plays",
        "relief_60plus_pct",
        "closer_third_straight_day",
        # Release 4 (W1 pitch events).
        "wp_per_team_game",
        "pb_per_team_game",
        "steal_events_on_foul",
        "wp_pb_on_foul",
        "wp_pb_bases_empty",
        "double_steal_two_out_plays",
        "illegal_k_reach",
    }
    assert kpis.DEFAULT_TOLERANCES["runs_on_inning_ending_plays"] == 0.0
    assert kpis.DEFAULT_TOLERANCES["closer_third_straight_day"] == 0.0
    assert kpis.DEFAULT_TOLERANCES["relief_60plus_pct"] == pytest.approx(0.01)
    assert not set(promoted) & set(kpis.REPORT_ONLY_TOLERANCES)
    reference = kpi_extras.load_reference()
    for key, target in promoted.items():
        assert reference[key]["value"] == pytest.approx(target)
    # Kept report-only for one more release.
    for key in ("starts_120plus_pct", "closer_ip_per_app"):
        assert key not in kpis.DEFAULT_TOLERANCES


def _summary(extras: dict) -> dict:
    return {"metrics": {"k_pct": 0.22}, "report_only": {"metrics": extras}}


# Every promoted extra on its target (the zero gates at 0).
ON_TARGET = dict(kpis.STRICT_EXTRAS_TARGETS)


def test_promote_extras_copies_values_into_strict_metrics() -> None:
    summary = _summary(
        {
            **ON_TARGET,
            "runs_on_inning_ending_plays": 0,
            "relief_60plus_pct": 0.004,
            "closer_third_straight_day": 0,
            "starts_120plus_pct": 0.5,
        }
    )
    missing = kpis._promote_extras_metrics(summary, kpis.DEFAULT_TOLERANCES)
    assert missing == []
    metrics = summary["metrics"]
    assert metrics["runs_on_inning_ending_plays"] == 0.0
    assert metrics["relief_60plus_pct"] == pytest.approx(0.004)
    assert "starts_120plus_pct" not in metrics  # still report-only
    failures = evaluate_tolerances(
        metrics=metrics,
        benchmarks={},
        tolerances=kpis.DEFAULT_TOLERANCES,
        targets=kpis.STRICT_EXTRAS_TARGETS,
    )
    assert failures == []


@pytest.mark.parametrize(
    "key, value",
    [
        ("runs_on_inning_ending_plays", 1),
        ("closer_third_straight_day", 1),
        ("relief_60plus_pct", 0.021),
        # Release 4: WP .25-.41, PB .02-.08 and the zero gates.
        ("wp_per_team_game", 0.42),
        ("wp_per_team_game", 0.24),
        ("pb_per_team_game", 0.09),
        ("pb_per_team_game", 0.01),
        ("steal_events_on_foul", 1),
        ("wp_pb_on_foul", 1),
        ("wp_pb_bases_empty", 1),
        ("double_steal_two_out_plays", 1),
        ("illegal_k_reach", 1),
    ],
)
def test_promoted_extras_fail_strict_off_target(key: str, value: float) -> None:
    extras = dict(ON_TARGET)
    extras[key] = value
    summary = _summary(extras)
    kpis._promote_extras_metrics(summary, kpis.DEFAULT_TOLERANCES)
    failures = evaluate_tolerances(
        metrics=summary["metrics"],
        benchmarks={},
        tolerances=kpis.DEFAULT_TOLERANCES,
        targets=kpis.STRICT_EXTRAS_TARGETS,
    )
    assert [f["metric"] for f in failures] == [key]


def test_promoted_extra_that_was_not_computed_fails_strict() -> None:
    # The extras raised, so no report-only metrics: the strict gate must not
    # pass by being skipped.
    summary = {"metrics": {}, "report_only": {"metrics": {}, "error": "boom"}}
    missing = kpis._promote_extras_metrics(summary, kpis.DEFAULT_TOLERANCES)
    assert {row["metric"] for row in missing} == set(kpis.STRICT_EXTRAS_TARGETS)
    assert all(math.isnan(row["value"]) for row in missing)
    # The CI failure annotation formats value with :.4f.
    assert f"{missing[0]['value']:.4f}" == "nan"
    # A gate absent from the tolerances in use is not reported.
    assert kpis._promote_extras_metrics(summary, {}) == []
