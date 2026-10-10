"""Audit 2026-10-06 Release 2: report-only KPIs (scripts/kpi_extras.py)."""
import csv
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.kpi_extras as kx
import scripts.physics_sim_season_kpis as kpis

CAL = Path("data/calibration")


def _pa(state, token, *, pitches=1, batter="B", pitcher="P1", last=None, mid_event=None):
    """One plate appearance's pitch_log entries. ``state`` is
    (inning, half, outs, bases, bat_score, fld_score)."""
    inning, half, outs, bases, bat, fld = state
    entries = []
    for i in range(pitches):
        balls = min(i, 3)
        entries.append(
            {
                "pitch_type": "fb",
                "count": f"{balls}-0",
                "swing": i == pitches - 1,
                "outcome": "ball" if i < pitches - 1 else "in_play",
                "pitcher_id": pitcher,
                "batter_id": batter,
                "pitch_count": i + 1,
                "tto": 1,
                "velocity": 94.0,
            }
        )
    entries[0].update(
        {
            "pa_start": True,
            "inning": inning,
            "half": half,
            "outs_before": outs,
            "bases_before": bases,
            "bat_score_before": bat,
            "fld_score_before": fld,
        }
    )
    if mid_event and pitches > 1:
        entries[0]["runner_event"] = mid_event
    entries[-1].update(last or {})
    entries[-1]["pa_result"] = token
    return entries


def _game(pitch_log, *, inning_runs, score, innings=1, meta=None):
    metadata = {
        "inning_runs": inning_runs,
        "score": score,
        "innings": innings,
        "pitcher_lines": {"away": [], "home": []},
        "batting_lines": {"away": [], "home": []},
        "fielding_lines": {"away": [], "home": []},
    }
    metadata.update(meta or {})
    return SimpleNamespace(totals={}, pitch_log=pitch_log, metadata=metadata)


GDP = {"ball_type": "gb", "runner_event": "dp"}


def _situational_game():
    log = []
    # Top 1: 1B; 1B with the runner going 1st->3rd; a 0-out DP that scores
    # him; a strikeout ends the inning.
    log += _pa((1, "top", 0, 0, 0, 0), "1b")
    log += _pa((1, "top", 0, 1, 0, 0), "1b")
    log += _pa((1, "top", 0, 5, 0, 0), "out", last=GDP)
    log += _pa((1, "top", 2, 0, 1, 0), "so", last={"outcome": "swinging_strike"})
    # Bottom 1: 1B; 2B scoring the runner from 1st; BB; K; 1B with both
    # runners moving one base; an inning-ending DP on which a run scores (L15).
    log += _pa((1, "bottom", 0, 0, 0, 1), "1b", pitcher="P2")
    log += _pa((1, "bottom", 0, 1, 0, 1), "2b", pitcher="P2")
    log += _pa((1, "bottom", 0, 2, 1, 1), "bb", pitches=4, pitcher="P2")
    log += _pa((1, "bottom", 0, 3, 1, 1), "so", pitcher="P2")
    log += _pa((1, "bottom", 1, 3, 1, 1), "1b", pitcher="P2")
    log += _pa((1, "bottom", 1, 7, 1, 1), "out", pitcher="P2", last=GDP)
    return _game(log, inning_runs={"away": [1], "home": [2]}, score={"away": 1, "home": 2})


def _finalize(acc):
    return acc.finalize(kx.load_reference())


def test_split_plate_appearances_uses_pa_start_when_logged():
    log = _pa((1, "top", 0, 0, 0, 0), "bb", pitches=4)
    log += _pa((1, "top", 0, 1, 0, 0), "so", pitches=3)
    pas = kx.split_plate_appearances(log)
    assert [pa.token for pa in pas] == ["bb", "so"]
    assert [pa.pitches for pa in pas] == [4, 3]
    assert pas[1].state == (1, "top", 0, 1, 0, 0)


def test_split_plate_appearances_heuristic_without_logging():
    log = [
        {"pitch_type": "fb", "count": "0-0", "batter_id": "A"},
        {"pitch_type": "fb", "count": "0-1", "batter_id": "A", "runner_event": "cs2"},
        # inning ended on the caught stealing: no pa_result; next PA starts 0-0
        {"pitch_type": "fb", "count": "0-0", "batter_id": "A"},
        {"pitch_type": "fb", "count": "1-0", "batter_id": "A", "pa_result": "1b"},
        {"outcome": "ibb", "batter_id": "B", "pa_result": "ibb"},
        {"outcome": "bunt", "batter_id": "C", "pa_result": "sh"},
    ]
    pas = kx.split_plate_appearances(log)
    assert [pa.token for pa in pas] == [None, "1b", "ibb", "sh"]
    assert pas[0].state is None
    assert pas[0].mid_event is False  # the event is on its last entry
    assert [pa.pitches for pa in pas] == [2, 2, 0, 0]


def test_mid_pa_runner_event_is_flagged():
    log = _pa((1, "top", 0, 1, 0, 0), "1b", pitches=3, mid_event="sb2")
    (pa,) = kx.split_plate_appearances(log)
    assert pa.mid_event is True


def test_situational_metrics_from_logged_game():
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(_situational_game(), away="A", home="H")
    report = _finalize(acc)
    m, t = report["metrics"], report["tables"]
    assert report["coverage"]["base_out_logging"] == "full"
    # RE24 bases empty / 0 out: top runs 1 from there, bottom 2.
    assert m["re24_empty_0"] == pytest.approx(1.5)
    assert m["runprob_empty_0"] == pytest.approx(1.0)
    assert t["re24"]["empty_0"]["n"] == 2
    # 1st & 3rd / 0 out (top PA3): one more run scored on the DP.
    assert m["re24_1b3b_0"] == pytest.approx(1.0)
    # XBT: 1st->3rd on a single and 1st->home on a double are taken; the
    # bottom single moving both runners one base is two chances, none taken.
    assert t["xbt_counts"]["opp"] == 4
    assert t["xbt_counts"]["taken"] == 2
    assert m["first_to_third_on_single_pct"] == pytest.approx(0.5)
    # GIDP opportunities: runner on 1st with < 2 out (6 PAs), 2 DPs.
    assert t["gidp_counts"] == {"opp": 6, "gidp": 2}
    # The inning-ending DP that scored a run is caught; the K is not.
    assert m["runs_on_inning_ending_plays"] == 1
    assert t["inning_ending_plays"]["plays"] == 2
    assert t["inning_ending_examples"][0]["bases_before"] == 7
    # Line score: P0..P3+ and runs per half (innings 1-8).
    assert m["inning_runs_p1"] == pytest.approx(0.5)
    assert m["inning_runs_p2"] == pytest.approx(0.5)
    assert m["runs_per_half_inning_1_8"] == pytest.approx(1.5)


def test_an_out_on_the_hits_play_is_skipped_not_charged_to_a_runner():
    # The engine also throws out runners who had no XBT chance, and the log
    # can't say whose out it was; the engine's own counters cover this.
    log = _pa((1, "top", 0, 3, 0, 0), "1b")  # runners on 1st and 2nd
    log += _pa((1, "top", 1, 3, 0, 0), "so")  # one runner was thrown out
    log += _pa((1, "top", 2, 3, 0, 0), "so")
    game = _game(log, inning_runs={"away": [0], "home": [0]}, score={"away": 0, "home": 0})
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(game, away="A", home="H")
    t = _finalize(acc)["tables"]
    assert t["xbt_counts"].get("opp", 0) == 0
    assert t["xbt_counts"]["skipped_out_on_play"] == 1


def test_walkoff_half_is_not_an_inning_ending_play():
    log = _pa((9, "top", 0, 0, 2, 2), "so")
    log += _pa((9, "top", 1, 0, 2, 2), "so")
    log += _pa((9, "top", 2, 0, 2, 2), "so")
    # Walk-off: a ground out scores the winning run with < 3 outs. Not a rule
    # violation, and the half did not end on three outs.
    log += _pa((9, "bottom", 0, 4, 2, 2), "out", last={"ball_type": "gb"})
    game = _game(
        log,
        inning_runs={"away": [0] * 9, "home": [0] * 8 + [1]},
        score={"away": 2, "home": 3},
        innings=9,
    )
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(game, away="A", home="H")
    m = _finalize(acc)["metrics"]
    assert m["runs_on_inning_ending_plays"] == 0


def test_metrics_without_base_out_logging_are_none():
    log = [{**e} for e in _situational_game().pitch_log]
    for entry in log:
        for key in ("pa_start", "inning", "half", "outs_before", "bases_before",
                    "bat_score_before", "fld_score_before"):
            entry.pop(key, None)
    game = _game(log, inning_runs={"away": [1], "home": [2]}, score={"away": 1, "home": 2})
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(game, away="A", home="H")
    report = _finalize(acc)
    m = report["metrics"]
    assert report["coverage"]["base_out_logging"] == "absent"
    for key in ("re24_empty_0", "first_to_third_on_single_pct", "gidp_per_opp", "late_close_ops_delta",
                "runs_on_inning_ending_plays"):
        assert m[key] is None
    # Line-score metrics need no base-out state.
    assert m["inning_runs_p1"] == pytest.approx(0.5)


def test_late_and_close_definition():
    assert not kx.late_and_close(6, 0, 0, 0)
    assert kx.late_and_close(7, 0, 0, 0)  # tied
    assert kx.late_and_close(8, 1, 0, 0)  # up one
    assert not kx.late_and_close(8, 2, 0, 7)  # up two
    assert kx.late_and_close(9, 0, 2, 0)  # tying run on deck
    assert not kx.late_and_close(9, 0, 3, 0)
    assert kx.late_and_close(9, 0, 3, 1)  # tying run on deck with one on
    assert kx.late_and_close(9, 0, 5, 7)  # bases loaded, down 5


def test_true_sd_subtracts_binomial_noise():
    rng = random.Random(7)
    rows = []
    for _ in range(400):
        p = 0.08 + rng.gauss(0, 0.02)
        n = 600
        rows.append((sum(rng.random() < p for _ in range(n)), n))
    sd, var, n = kx.true_sd(rows)
    assert n == 400
    assert sd == pytest.approx(0.02, abs=0.004)
    assert kx.true_sd(rows[:5]) == (None, None, 5)
    # Pure noise: the clipped sd floors at 0, the variance may go negative.
    noise = [(sum(rng.random() < 0.08 for _ in range(600)), 600) for _ in range(300)]
    sd0, var0, _ = kx.true_sd(noise)
    assert sd0 < 0.006
    assert var0 < 0.0001


def test_usage_metrics_from_pitcher_lines():
    meta = {
        "pitcher_lines": {
            "away": [
                {"player_id": "SP1", "gs": 1, "pitches": 121, "outs": 21},
                {"player_id": "RP1", "gs": 0, "pitches": 65, "outs": 9},
            ],
            "home": [
                {"player_id": "SP2", "gs": 1, "pitches": 90, "outs": 18},
                {"player_id": "CL1", "gs": 0, "pitches": 15, "outs": 3},
            ],
        },
        "pitcher_usage": {"home": [{"player_id": "CL1", "staff_role": "CL"}]},
    }
    game = _game([], inning_runs={}, score={"away": 1, "home": 2}, innings=9, meta=meta)
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(game, away="A", home="H")
    m = _finalize(acc)["metrics"]
    assert m["starts_120plus_pct"] == pytest.approx(0.5)
    assert m["relief_60plus_pct"] == pytest.approx(0.5)
    assert m["relief_outs_per_app"] == pytest.approx(6.0)
    assert m["closer_ip_per_app"] == pytest.approx(1.0)
    assert m["closer_top_ip_per_162"] == pytest.approx(1.0)
    assert m["home_wpct"] == pytest.approx(1.0)


def test_release3_bullpen_tallies():
    meta = {
        "pitcher_lines": {
            "away": [
                {"player_id": "SP1", "gs": 1, "pitches": 90, "outs": 18},
                {"player_id": "MR1", "gs": 0, "pitches": 20, "outs": 4},
                {"player_id": "SP3", "gs": 0, "pitches": 40, "outs": 6},
            ],
            "home": [
                {"player_id": "SP2", "gs": 1, "pitches": 95, "outs": 21},
                {"player_id": "CL1", "gs": 0, "pitches": 15, "outs": 3},
                {"player_id": "SU1", "gs": 0, "pitches": 12, "outs": 2},
            ],
        },
        "pitcher_usage": {
            "away": [
                {"player_id": "SP1", "staff_role": "SP"},
                {"player_id": "MR1", "staff_role": "MR", "fallback": True},
                {"player_id": "SP3", "staff_role": "SP", "emergency": True},
            ],
            "home": [
                {"player_id": "SP2", "staff_role": "SP"},
                {"player_id": "CL1", "staff_role": "CL", "prior_streak": 2},
                {"player_id": "SU1", "staff_role": "SU", "prior_streak": 1},
            ],
        },
    }
    game = _game([], inning_runs={}, score={"away": 1, "home": 2}, innings=9, meta=meta)
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(game, away="A", home="H")
    report = _finalize(acc)
    m = report["metrics"]
    assert m["closer_third_straight_day"] == 1
    assert m["emergency_starter_relief_apps"] == 1
    assert m["bullpen_fallback_share"] == pytest.approx(0.25)
    assert m["relief_outs_per_app_mr"] == pytest.approx(4.0)
    assert m["relief_outs_per_app_cl"] == pytest.approx(3.0)
    assert m["relief_outs_per_app_lr"] is None
    assert report["tables"]["relief_outs_per_app_by_role"]["SP"] == {
        "apps": 1, "outs_per_app": 6.0,
    }


def test_fatigue_and_tto_are_within_pitcher():
    log = []
    # Starter SP: early PAs (pitch 1-) all outs, late PAs (91+) all HRs.
    for i in range(3):
        log += [{"pitch_type": "fb", "count": "0-0", "pitcher_id": "SP", "batter_id": "B",
                 "pitch_count": 1 + i, "tto": 1, "velocity": 95.0, "pa_result": "out"}]
    for i in range(2):
        log += [{"pitch_type": "fb", "count": "0-0", "pitcher_id": "SP", "batter_id": "B",
                 "pitch_count": 95 + i, "tto": 3, "velocity": 93.5, "pa_result": "hr"}]
    meta = {"pitcher_lines": {"away": [], "home": [{"player_id": "SP", "gs": 1, "pitches": 96}]}}
    game = _game(log, inning_runs={}, score={"away": 0, "home": 0}, meta=meta)
    acc = kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
    acc.add_game(game, away="A", home="H")
    m = _finalize(acc)["metrics"]
    assert m["starter_fb_velo_drop_91_105"] == pytest.approx(1.5)
    assert m["starter_woba_delta_91_105"] == pytest.approx(2.05)
    assert m["tto_pass3_woba_delta"] == pytest.approx(2.05)
    assert m["tto_pass2_woba_delta"] is None
    assert m["first_pitch_pa_end_pct"] == pytest.approx(1.0)
    assert m["swing_rate_0_0"] == pytest.approx(0.0)


def test_reference_csv_covers_known_metrics():
    ref = kx.load_reference()
    assert ref, "data/MLB_avg/mlb_report_only_reference.csv missing"
    with kx.DEFAULT_REFERENCE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    keys = [r["metric_key"] for r in rows]
    assert len(keys) == len(set(keys))
    assert {r["approximate"] for r in rows} <= {"0", "1"}
    produced = set(
        kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
        .finalize(ref)["metrics"]
    )
    produced |= {"matchup_k_log5_max_abs_resid", "matchup_hr_log5_max_abs_resid_logit"}
    notes = {
        "re24_env_scale_2023_24",
        "extra_half_runs_no_runner",
        "extra_half_p_score_no_runner",
    }
    assert set(keys) - notes <= produced
    assert ref["runs_on_inning_ending_plays"]["value"] == 0


def test_report_only_keys_are_never_gated():
    # Only the keys promoted on purpose (Release 3) overlap the strict gates.
    produced = set(
        kx.ReportOnlyKpis(players_path=Path("missing.csv"), games_per_team=162)
        .finalize({})["metrics"]
    )
    promoted = set(kpis.STRICT_EXTRAS_TARGETS)
    assert promoted <= produced
    assert produced & set(kpis.DEFAULT_TOLERANCES) == promoted
    assert not produced & set(kpis.RATING_OUTCOME_TARGETS)


def test_run_sim_writes_report_only_block(monkeypatch):
    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    summary = kpis.run_sim(
        games_per_team=20, seed=1, players_path=CAL / "players.csv", base_dir=CAL
    )
    report = summary["report_only"]
    assert "error" not in report
    assert report["coverage"]["games"] == len(teams) * 20 // 2
    m = report["metrics"]
    assert 0.0 < m["swing_rate_0_0"] < 1.0
    assert m["starter_fb_velo_drop_91_105"] is None or m["starter_fb_velo_drop_91_105"] > -5
    assert "reference" in report and "deltas" in report
    # Report-only metrics stay out of the gated metrics dict.
    assert "swing_rate_0_0" not in summary["metrics"]
    text = kx.format_report(report)
    assert "Report-only KPIs" in text and "swing_rate_0_0" in text


def test_add_game_failure_is_recorded_not_raised(monkeypatch):
    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})

    def boom(self, *a, **k):
        raise RuntimeError("broken extra")

    monkeypatch.setattr(kx.ReportOnlyKpis, "add_game", boom)
    summary = kpis.run_sim(
        games_per_team=20, seed=1, players_path=CAL / "players.csv", base_dir=CAL
    )
    assert summary["report_only"]["error"] == "RuntimeError: broken extra"
    assert summary["metrics"]["k_pct"] > 0  # the gated run is untouched


def test_matchup_grid_small_run_restores_random_state(monkeypatch):
    monkeypatch.setattr(kx, "GRID_MIN_EVENTS", 0)  # 40 PA cells are thin
    random.seed(123)
    before = random.getstate()
    out = kx.matchup_grid_metrics(pa_per_cell=40, players_path=CAL / "players.csv")
    assert random.getstate() == before
    k_grid = out["tables"]["matchup_k_grid"]
    assert len(k_grid["cells"]) == 16
    # The anchor row and column reproduce themselves exactly under log5.
    anchor = [c for c in k_grid["cells"] if c["batter"] == 50.0 or c["pitcher"] == 50.0]
    assert all(abs(c["residual"]) < 1e-9 for c in anchor)
    assert out["metrics"]["matchup_k_log5_max_abs_resid"] >= 0.0
    hr_grid = out["tables"]["matchup_hr_grid"]
    assert 50.0 in hr_grid["ph_levels"] and 50.0 in hr_grid["pitcher_levels"]


def test_main_keeps_extras_and_report_only_gates_apart(monkeypatch, tmp_path, capsys):
    """Both Release 2 blocks land in the JSON; neither overwrites the other."""

    extras = {"metrics": {"swing_rate_0_0": 0.4}, "tables": {}, "coverage": {}}
    monkeypatch.setattr(
        kpis, "run_sim",
        lambda *a, **k: {
            "metrics": {"extra_base_advance_rate": 0.69, "sba_per_pa": 0.05},
            "report_only": extras,
        },
    )
    monkeypatch.setattr(kpis.kpi_extras, "format_report", lambda r: "")
    out = tmp_path / "kpis.json"
    monkeypatch.setattr(
        sys, "argv",
        ["physics_sim_season_kpis.py", "--games", "1", "--output", str(out)],
    )
    kpis.main()
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["report_only"]["metrics"]["swing_rate_0_0"] == 0.4
    rows = {r["metric"]: r for r in summary["report_only_gates"]["results"]}
    assert rows["extra_base_advance_rate"]["ok"] is False
    # Release 4: steal volume is strict now, no longer a report-only row.
    assert "sba_per_pa" not in rows
    failed = {f["metric"] for f in summary["tolerance_failures"]}
    assert "sba_per_pa" in failed


def test_thin_log5_cells_are_skipped():
    from collections import Counter

    cells = {(b, p): Counter(pa=100, k=0 if (b, p) == (60.0, 60.0) else 25)
             for b in (50.0, 60.0) for p in (50.0, 60.0)}
    grid = kx._log5_grid(cells, [50.0, 60.0], [50.0, 60.0], 50.0, "k")
    skipped = [c for c in grid["cells"] if c.get("skipped")]
    assert [(c["batter"], c["pitcher"]) for c in skipped] == [(60.0, 60.0)]
    assert grid["max_abs_residual_logit"] < 1.0
