"""Release 6a (fielding): the report-only rows read from the engine's
fielding records, and the slope re-fit that reads the same seasons.

The engine hands the KPI harness, beside each game
(``GameResult.play_records``): every error it charged with its source, and
-- when the game was played with ``fielding_chance_log`` -- for each ball in
play the responsible fielder, the out chance used and a league-average
fielder's, and the same pair for each error roll. From them:

- ``oaa_per_fa_sd_<pos>`` / ``oaa_per_8pt_<pos>``: outs above an average
  fielder per 150 games against the fa rating, range plus errors;
- ``team_der_true_sd``: the spread of team defence with the luck taken out;
- ``range_level_shift`` / ``neutral_out_prob_mean``: the league level;
- ``e_per_team_game_src_<source>``: errors by where they came from.

None is a gate. ``scripts/fit_fielding_slopes.py`` turns the same sums into
the range slopes, the infield band cut points and the error bases.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

import scripts.fit_fielding_slopes as fit
import scripts.kpi_extras as kx
import scripts.physics_sim_season_kpis as kpis
from tests.test_r6a_tools_kpis import _acc, _arm, _ball, _game, _hitter, _players, _report

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PROFILE = REPO / "scripts" / "kpi_profiles" / "r6_fielding.json"
SCALE = 0.92


def _fielders(tmp_path, position, ratings):
    rows = []
    for index, fa in enumerate(ratings):
        row = _hitter(f"F{index}", pos=position)
        row["fa"] = fa
        rows.append(row)
    return _players(tmp_path, rows + [_arm("ARM")])


def _chance_game(chances, errors=(), charged=(), log=None):
    log = log if log is not None else [_ball("out", ball_type="gb")] * 4
    records = {
        "bip_chances": list(chances), "error_chances": list(errors),
        "errors": list(charged), "babip_scale": SCALE,
    }
    return _game(log, records=records)


# --- the keys ----------------------------------------------------------------------


def test_the_rows_are_report_only_and_none_without_the_records():
    assert set(kx.R6_FIELDING_LOG_KEYS) <= set(kx.R6_METRIC_KEYS)
    assert "oaa_per_fa_sd_ss" in kx.R6_FIELDING_LOG_KEYS
    assert "team_der_true_sd" in kx.R6_FIELDING_LOG_KEYS
    assert "e_per_team_game_src_steal" in kx.R6_FIELDING_LOG_KEYS
    gated = set(kpis.DEFAULT_TOLERANCES) | set(kpis.STRICT_EXTRAS_TARGETS)
    for spec in kpis.ENGINE_GATES.values():
        gated |= set(spec["tolerances"]) | set(spec["extras_targets"])
    assert not gated & set(kx.R6_FIELDING_LOG_KEYS)
    acc = _acc()
    acc.add_game(_game([_ball("out", ball_type="gb")]), away="A", home="H")
    metrics = _report(acc)["metrics"]
    for key in kx.R6_FIELDING_LOG_KEYS:
        assert metrics[key] is None, key


# --- what a rating is worth --------------------------------------------------------


def test_outs_per_rating_sd_from_the_logged_chances(tmp_path):
    """Ten shortstops, fa 40 to 58. Each ball's out chance is the average
    fielder's plus .002 a point: 20 balls a game is .0368 outs a game a
    point (times babip_scale), 5.52 a point per 150 games."""
    ratings = list(range(40, 60, 2))
    acc = kx.ReportOnlyKpis(
        players_path=_fielders(tmp_path, "SS", ratings), games_per_team=20
    )
    for _game_no in range(12):
        chances = []
        for index, fa in enumerate(ratings):
            used = 0.70 + 0.002 * (fa - 50)
            chances += [
                (0, "home", "gb", ("SS",), (f"F{index}",), used, 0.70, 0.25)
            ] * 20
        acc.add_game(_chance_game(chances), away="A", home="H")
    report = _report(acc)
    per_point = 150 * 20 * SCALE * 0.002
    sd = statistics.pstdev(ratings)
    m = report["metrics"]
    assert m["oaa_per_8pt_ss"] == pytest.approx(8 * per_point)
    assert m["oaa_per_fa_sd_ss"] == pytest.approx(sd * per_point)
    row = report["tables"]["fielding_value_by_position"]["SS"]
    assert row["fielders"] == 10 and row["fa_sd"] == pytest.approx(sd)
    assert row["range_outs_per_point"] == pytest.approx(per_point)
    assert row["error_outs_per_point"] == pytest.approx(0.0)
    # Nobody played second: no row, not a zero.
    assert m["oaa_per_fa_sd_2b"] is None and m["oaa_per_8pt_cf"] is None
    assert m["range_level_shift"] == pytest.approx(0.002 * (49 - 50))
    assert m["neutral_out_prob_mean"] == pytest.approx(0.70)


def test_errors_saved_count_as_outs_and_a_shared_ball_is_split(tmp_path):
    ratings = list(range(40, 60, 2))
    acc = kx.ReportOnlyKpis(
        players_path=_fielders(tmp_path, "3B", ratings), games_per_team=20
    )
    for _game_no in range(12):
        chances, errors = [], []
        for index, fa in enumerate(ratings):
            pid = f"F{index}"
            # A ground ball two infielders share (the additive chance): the
            # third baseman is credited half of what the pair added.
            chances += [
                (0, "home", "gb", ("3B", "SS"), (pid, None), 0.70 + 0.004 * (fa - 50),
                 0.70, 0.25)
            ] * 10
            # Five error rolls: an average fielder's .05, his .05 - .001 a point.
            errors += [(0, "home", "3B", pid, 0.05 - 0.001 * (fa - 50), 0.05)] * 5
        acc.add_game(_chance_game(chances, errors), away="A", home="H")
    report = _report(acc)
    row = report["tables"]["fielding_value_by_position"]["3B"]
    assert row["range_outs_per_point"] == pytest.approx(150 * 10 * SCALE * 0.004 / 2)
    assert row["error_outs_per_point"] == pytest.approx(150 * 5 * 0.001)
    total = row["range_outs_per_point"] + row["error_outs_per_point"]
    assert report["metrics"]["oaa_per_8pt_3b"] == pytest.approx(8 * total)
    assert row["error_outs_per_fa_sd"] == pytest.approx(
        statistics.pstdev(ratings) * 150 * 5 * 0.001
    )


def test_a_position_needs_enough_regulars(tmp_path):
    """Fewer than eight fielders with a chance in half the club's games,
    and the position has no row."""
    ratings = list(range(40, 60, 2))
    acc = kx.ReportOnlyKpis(
        players_path=_fielders(tmp_path, "CF", ratings), games_per_team=20
    )
    for game_no in range(12):
        chances = []
        for index, fa in enumerate(ratings):
            if index >= 7 and game_no >= 6:
                continue  # three part-timers: six games each, under the ten
            chances.append(
                (0, "home", "fb", ("CF",), (f"F{index}",), 0.75, 0.73, 0.25)
            )
        acc.add_game(_chance_game(chances), away="A", home="H")
    report = _report(acc)
    assert report["tables"]["fielding_value_by_position"]["CF"] == {"fielders": 7}
    assert report["metrics"]["oaa_per_fa_sd_cf"] is None


# --- team defence without the luck --------------------------------------------------


def test_team_defence_true_sd(tmp_path):
    """Two clubs: one whose balls were worth .72 outs each with a .02 error
    chance on two of every ten, one .66 with .05."""
    acc = _acc(_players(tmp_path, [_arm("ARM")]))
    home = [(0, "home", "fb", ("CF",), (None,), 0.76, 0.70, 0.28)] * 10
    away = [(0, "away", "fb", ("CF",), (None,), 0.70, 0.70, 0.34)] * 10
    errors = [(0, "home", "CF", None, 0.02, 0.03)] * 2 + [
        (0, "away", "CF", None, 0.05, 0.03)
    ] * 2
    acc.add_game(_chance_game(home + away, errors), away="A", home="H")
    report = _report(acc)
    good = (10 * 0.72 - 2 * 0.02) / 10
    poor = (10 * 0.66 - 2 * 0.05) / 10
    assert report["metrics"]["team_der_true_sd"] == pytest.approx((good - poor) / 2)
    table = report["tables"]["team_der_true"]
    assert table["teams"] == 2 and table["mean"] == pytest.approx((good + poor) / 2)
    assert table["range_sd"] == pytest.approx(SCALE * 0.06 / 2)
    assert table["error_sd"] == pytest.approx((0.002 + 0.004) / 2)
    assert table["binomial_noise_sd"] > 0.0


# --- errors by source ---------------------------------------------------------------


def test_errors_by_source_and_by_the_position_charged():
    charged = [
        (0, "roe", "SS", "S", "home"), (0, "roe", "SS", "S", "home"),
        (1, "roe", "P", "ARM", "home"), (2, "steal", "C", "C1", "away"),
        (3, "of_hit", "RF", "R", "home"), (4, "pickoff", "P", "ARM", "home"),
        (5, "relay", "2B", "K", "away"), (6, "advance", "LF", "L", "home"),
        (7, "tag_up", "CF", "M", "home"),
    ]
    acc = _acc()
    acc.add_game(_chance_game([], charged=charged), away="A", home="H")
    acc.add_game(_chance_game([], charged=charged[:1]), away="A", home="H")
    report = _report(acc)
    m = report["metrics"]
    # Two games, four team-games.
    assert m["e_per_team_game_src_roe"] == pytest.approx(3 / 4)
    # The pitcher's error on a batted ball is a comebacker, not a plain roe.
    assert m["e_per_team_game_src_comebacker"] == pytest.approx(1 / 4)
    for source in ("steal", "of_hit", "pickoff", "relay", "advance", "tag_up"):
        assert m[f"e_per_team_game_src_{source}"] == pytest.approx(1 / 4), source
    table = report["tables"]["errors_by_source"]
    assert table["by_source"]["roe"] == {"SS": 3}
    assert table["by_source"]["comebacker"] == {"P": 1}
    assert table["by_position_charged"]["P"] == 2
    assert table["per_team_game_by_position_charged"]["SS"] == pytest.approx(3 / 4)
    assert sum(table["by_position_charged"].values()) == 10


def test_the_pitcher_s_share_of_the_ground_balls():
    log = (
        [_ball("out", ball_type="gb", fld_pos="P", out_type="groundout")]
        + [_ball("out", ball_type="gb", fld_pos="SS", out_type="groundout")] * 3
    )
    acc = _acc()
    acc.add_game(_game(log), away="A", home="H")
    m = _report(acc)["metrics"]
    assert m["gb_play_share_p"] == pytest.approx(0.25)
    assert m["gb_play_share_ss"] == pytest.approx(0.75)


# --- on the real engine -------------------------------------------------------------


@pytest.fixture(scope="module")
def short_season():
    """Four calibration clubs, 40 games each, generation 6 with the
    fielding values, through the harness's own run."""
    import csv

    with (CAL / "teams.csv").open() as fh:
        teams = [row["team_id"] for row in csv.DictReader(fh)][:4]
    patch = pytest.MonkeyPatch()
    patch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    patch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    try:
        overrides = kpis.resolve_run_overrides(engine=6, overrides_path=PROFILE)
        summary = kpis.run_sim(
            games_per_team=40, seed=2, players_path=CAL / "players.csv",
            tuning_overrides=overrides, base_dir=CAL,
        )
    finally:
        patch.undo()
    return summary


def test_the_harness_turns_the_log_on_and_fills_the_rows(short_season):
    report = short_season["report_only"]
    assert "error" not in report and "r6_kpi_error" not in report["tables"]
    m = report["metrics"]
    # The run did not ask for the log: the harness turns it on.
    assert "fielding_chance_log" not in short_season["meta"]["tuning_overrides"]
    assert abs(m["range_level_shift"]) < 0.01
    assert 0.6 < m["neutral_out_prob_mean"] < 0.75
    assert 0.0 < m["team_der_true_sd"] < 0.03
    by_source = sum(m[f"e_per_team_game_src_{s}"] for s in kx.R6_ERROR_SOURCES)
    assert by_source == pytest.approx(m["e_per_team_game"])
    assert m["e_per_team_game_src_of_hit"] > 0.0
    assert m["gb_play_share_p"] == pytest.approx(0.07, abs=0.03)
    infield = sum(m[f"gb_play_share_{p}"] for p in ("1b", "2b", "3b", "ss", "p"))
    assert infield == pytest.approx(1.0)
    # Four clubs are too few for a regression at any one position.
    assert m["oaa_per_fa_sd_ss"] is None
    table = report["tables"]["fielding_value_by_position"]
    assert set(table) == set(kx.R6_RANGE_POSITIONS)
    assert all(row["fielders"] <= 8 for row in table.values())
    assert not set(kx.R6_FIELDING_LOG_KEYS) & set(short_season["metrics"])


def test_the_sums_the_refit_reads(short_season):
    sums = short_season["report_only"]["tables"]["fielding_chance_sums"]
    assert sums["team_games"] == 160
    positions = sums["by_position"]
    assert set(positions) == {"1B", "2B", "3B", "SS", "P", "LF", "CF", "RF"}
    balls = sum(
        row.get(f"balls_{kind}", 0) for row in positions.values()
        for kind in ("gb", "ld", "fb")
    )
    assert balls == pytest.approx(sum(sums["grounder_direction"].values()) + sum(
        row.get("balls_ld", 0) + row.get("balls_fb", 0) for row in positions.values()
    ))
    # Only infielders (and the pitcher) own ground balls, only outfielders
    # balls in the air.
    for pos in ("1B", "2B", "3B", "SS", "P"):
        assert positions[pos].get("balls_fb", 0) == 0
    for pos in ("LF", "CF", "RF"):
        assert positions[pos].get("balls_gb", 0) == 0
    # A sum of p * (1 - p) over a position's balls is at most a quarter of them.
    for row in positions.values():
        owned = sum(row.get(f"balls_{k}", 0) for k in ("gb", "ld", "fb"))
        assert 0.0 < row.get("spread", 0.0) + row.get("spread_ld", 0.0) <= owned / 4
    # How the balls came out, for what an out is worth in runs.
    assert positions["CF"]["result_out"] > positions["CF"]["result_1b"] > 0


# --- the re-fit -------------------------------------------------------------------


def test_the_slope_is_the_budget_over_the_spread():
    sums = {
        "team_games": 300,
        "by_position": {
            "SS": {"spread": 100.0, "spread_ld": 0.0},
            "CF": {"spread": 60.0, "spread_ld": 40.0},
        },
    }
    slopes = fit.fit_slopes(sums, babip_scale=0.92, ld_ratio=0.6)
    # Per 150 team-games: SS 50, CF 30 + 0.6 * 20 = 42.
    assert slopes["SS"] == pytest.approx(fit.RANGE_BUDGET["SS"] / (0.92 * 50))
    assert slopes["CF"] == pytest.approx(fit.RANGE_BUDGET["CF"] / (0.92 * 42))
    assert set(slopes) == {"SS", "CF"}
    assert set(fit.RANGE_BUDGET) == set(kx.R6_RANGE_POSITIONS)


def test_a_slope_fitted_this_way_gives_its_budget():
    """The first-order claim behind the fit, on the engine's own function:
    one rating point at the fitted slope adds the budget in outs."""
    from physics_sim import fielding
    from physics_sim.config import load_tuning

    chances = [0.15, 0.35, 0.55, 0.62, 0.7, 0.78, 0.84, 0.9, 0.95] * 40
    spread = sum(p * (1 - p) for p in chances)
    slope = fit.fit_slopes(
        {"team_games": 150, "by_position": {"SS": {"spread": spread}}},
        babip_scale=0.92, ld_ratio=0.6,
    )["SS"]
    tuning = load_tuning({"range_model": 1.0, "range_logit_slope_ss": slope})
    gained = sum(
        fielding.range_shifted_out_probability(
            p, position="SS", rating=51.0, ball_type="gb", tuning=tuning
        ) - p
        for p in chances
    )
    assert 0.92 * gained == pytest.approx(fit.RANGE_BUDGET["SS"], rel=0.01)


def test_the_band_cut_points_give_the_shares():
    # Ground balls spread evenly from -40 to +40 degrees, half-degree bins.
    histogram = {f"{-40 + 0.5 * i:g}": 10 for i in range(160)}
    bounds = fit.fit_bands({"grounder_direction": histogram})
    whole = sum(share for _pos, share in fit.BAND_SHARES)
    top = 40.0
    for pos, share in fit.BAND_SHARES[:-1]:
        top -= 80.0 * share / whole
        assert bounds[pos] == pytest.approx(top, abs=0.01), pos
    assert fit.fit_bands({}) == {}
    assert [pos for pos, _ in fit.BAND_SHARES] == ["3B", "SS", "P", "2B", "1B"]
    assert whole == pytest.approx(0.97)


def test_the_error_bases_are_re_levelled_to_their_targets():
    report = {
        "tables": {
            "fielding_chance_sums": {"team_games": 100},
            "errors_by_source": {
                "by_source": {"roe": {"SS": 12, "1B": 2}, "comebacker": {"P": 5}}
            },
        }
    }
    bases = fit.fit_error_bases(
        report, {"SS": 0.10, "1B": 0.04, "P": 0.04, "3B": 0.1},
        {"SS": 0.036, "1B": 0.029, "P": 0.045, "3B": 0.049},
    )
    assert bases["SS"] == pytest.approx(0.036 * 0.10 / 0.12)
    assert bases["1B"] == pytest.approx(0.029 * 0.04 / 0.02)
    assert bases["P"] == pytest.approx(0.045 * 0.04 / 0.05)
    assert "3B" not in bases  # nothing charged there: nothing to re-level


def test_the_script_reads_a_harness_output(tmp_path, short_season, capsys):
    path = tmp_path / "season.json"
    path.write_text(json.dumps({
        "meta": short_season["meta"], "report_only": short_season["report_only"],
    }, default=str), encoding="utf-8")
    out = tmp_path / "fit.json"
    assert fit.main(["--from-json", str(path), "--output", str(out)]) == 0
    fitted = json.loads(out.read_text(encoding="utf-8"))["fitted"]
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    for pos in kx.R6_RANGE_POSITIONS:
        key = f"range_logit_slope_{pos.lower()}"
        # A 160-team-game sample against the profile's six seasons.
        assert fitted[key] == pytest.approx(profile[key], rel=0.15), key
    for key in ("infield_band_3b_min_deg", "infield_band_2b_min_deg"):
        assert fitted[key] == pytest.approx(profile[key], abs=2.5), key
    assert "range_logit_slope_ss" in capsys.readouterr().out
    # A season played without the range model is not out0: refused.
    off = dict(short_season["meta"], tuning_overrides={"range_model": 0.0})
    path.write_text(json.dumps({
        "meta": off, "report_only": short_season["report_only"],
    }, default=str), encoding="utf-8")
    assert fit.main(["--from-json", str(path)]) == 1
