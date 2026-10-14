"""Release 6a (tooling): the report-only KPIs Release 6 is built against
(scripts/kpi_extras.py ``_add_r6`` / ``_r6_metrics``).

Pitching (what each rating is worth, batted balls by pitch type, the
tired-starter and times-through-the-order deltas with the batters taken
out), power (home runs by Power, doubles by Power, Contact and ground-ball
rating), fielding (errors and plays by position, starters off their
position) and the batted ball (Statcast classes, home run distance, spray
by batting side). They read the pitch log and the box lines; none is a
strict gate and a fault in the block leaves every other row alone.
"""

from __future__ import annotations

import csv
import random
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.kpi_extras as kx
import scripts.physics_sim_season_kpis as kpis

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"

PLAYER_FIELDS = [
    "player_id", "primary_position", "other_positions", "is_pitcher", "bats",
    "throws", "ch", "ph", "gf", "pl", "fa", "arm", "control", "movement", "fb",
    "sl", "cu",
]


def _players(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "players.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in PLAYER_FIELDS})
    return path


def _hitter(pid, *, bats="R", ph=50, ch=50, gf=50, pl=50, pos="CF", other=""):
    return {
        "player_id": pid, "primary_position": pos, "other_positions": other,
        "is_pitcher": "0", "bats": bats, "throws": "R", "ch": ch, "ph": ph,
        "gf": gf, "pl": pl, "fa": 50, "arm": 50,
    }


def _arm(pid, *, throws="R", arm=50, control=50, movement=50, grade=50, gf=50):
    return {
        "player_id": pid, "primary_position": "P", "is_pitcher": "1",
        "bats": throws, "throws": throws, "gf": gf, "arm": arm,
        "control": control, "movement": movement, "fb": grade, "sl": grade,
    }


def _ball(token, *, ev=90.0, la=12.0, spray=0.0, ball_type="ld", batter="B",
          pitcher="P", pitch_type="fb", pitch_count=1, tto=1, **extra):
    """A one-pitch plate appearance ending on a ball in play."""
    entry = {
        "pitch_type": pitch_type, "count": "0-0", "in_zone": True, "swing": True,
        "contact": True, "outcome": "in_play", "batter_id": batter,
        "pitcher_id": pitcher, "tto": tto, "pitch_count": pitch_count,
        "exit_velo": ev, "launch_angle": la, "spray_angle": spray,
        "ball_type": ball_type, "pa_result": token,
    }
    entry.update(extra)
    return entry


def _pitch(token=None, *, outcome="strike", batter="B", pitcher="P",
           pitch_type="fb", pitch_count=1, tto=1):
    """A pitch that is not put in play; ``token`` ends the plate appearance."""
    entry = {
        "pitch_type": pitch_type, "count": "0-0", "in_zone": True,
        "swing": False, "contact": False, "outcome": outcome,
        "batter_id": batter, "pitcher_id": pitcher, "tto": tto,
        "pitch_count": pitch_count,
    }
    if token:
        entry["pa_result"] = token
    return entry


def _game(log, *, pitcher_lines=None, batting_lines=None, fielding_lines=None,
          meta=None, records=None):
    """A game result. A ``fld_pos`` given to ``_ball`` is taken out of the
    entry and put where the engine puts it: ``play_records["fld_pos"]``, by
    the entry's index in the log."""
    metadata = {
        "inning_runs": {"away": [0], "home": [0]},
        "score": {"away": 0, "home": 0},
        "innings": 1,
        "pitcher_lines": pitcher_lines or {"away": [], "home": []},
        "batting_lines": batting_lines or {"away": [], "home": []},
        "fielding_lines": fielding_lines or {"away": [], "home": []},
    }
    metadata.update(meta or {})
    entries, fielded = [], {}
    for index, entry in enumerate(log):
        entry = dict(entry)
        if "fld_pos" in entry:
            fielded[index] = entry.pop("fld_pos")
        entries.append(entry)
    play_records = dict(records or {})
    if fielded:
        play_records["fld_pos"] = fielded
    return SimpleNamespace(
        totals={}, pitch_log=entries, metadata=metadata, play_records=play_records
    )


def _acc(players: Path | None = None, games_per_team: int = 162):
    return kx.ReportOnlyKpis(
        players_path=players or Path("missing.csv"), games_per_team=games_per_team
    )


def _report(acc):
    report = acc.finalize({})
    assert "r6_kpi_error" not in report["tables"], report["tables"]
    return report


def _one_game(log, players=None, games_per_team=162, **game):
    acc = _acc(players, games_per_team)
    acc.add_game(_game(log, **game), away="A", home="H")
    return _report(acc)


# --- never a gate, never in the way ---------------------------------------------


def test_every_key_is_reported_and_none_is_a_gate():
    report = _report(_acc())
    metrics = report["metrics"]
    assert len(set(kx.R6_METRIC_KEYS)) == len(kx.R6_METRIC_KEYS) == 92
    for key in kx.R6_METRIC_KEYS:
        assert key in metrics and metrics[key] is None, key
    gated = (
        set(kpis.DEFAULT_TOLERANCES)
        | set(kpis.REPORT_ONLY_TOLERANCES)
        | set(kpis.STRICT_EXTRAS_TARGETS)
        | set(kpis.RATING_OUTCOME_TARGETS)
        | {k for keys in kpis.GATE_SETS.values() for k in keys}
        | {k for tol in kpis.GATE_SET_TOLERANCES.values() for k in tol}
        | {k for tgt in kpis.GATE_SET_EXTRAS_TARGETS.values() for k in tgt}
    )
    for spec in kpis.ENGINE_GATES.values():
        gated |= set(spec["tolerances"]) | set(spec["extras_targets"])
        gated |= set(spec.get("grid_tolerances", {}))
    assert not gated & set(kx.R6_METRIC_KEYS)


def test_the_block_reports_exactly_its_keys_and_replaces_none(monkeypatch, tmp_path):
    """Every key the block writes is declared, and none is the name of a
    row that existed before it."""
    seen = {}
    real = kx.ReportOnlyKpis._r6_metrics

    def spy(self, metrics, tables, gpt, team_games):
        real(self, metrics, tables, gpt, team_games)
        seen["metrics"] = set(metrics)

    monkeypatch.setattr(kx.ReportOnlyKpis, "_r6_metrics", spy)
    report = _one_game([_ball("1b")])
    assert seen["metrics"] == set(kx.R6_METRIC_KEYS)
    monkeypatch.setattr(kx.ReportOnlyKpis, "_r6_metrics", lambda *a, **k: None)
    monkeypatch.setattr(kx, "R6_METRIC_KEYS", ())
    before = _acc().finalize({})
    assert not set(before["metrics"]) & seen["metrics"]
    r6_tables = set(report["tables"]) - set(before["tables"])
    assert r6_tables and "dispersion" not in r6_tables


@pytest.mark.parametrize("broken", ["_add_r6", "_r6_metrics"])
def test_a_fault_in_the_block_leaves_every_other_row(monkeypatch, broken):
    log = [_pitch(outcome="ball"), _ball("1b")]
    healthy = _one_game(log)

    def boom(self, *args, **kwargs):
        raise RuntimeError("broken row")

    monkeypatch.setattr(kx.ReportOnlyKpis, broken, boom)
    acc = _acc()
    acc.add_game(_game(log), away="A", home="H")
    acc.add_game(_game(log), away="A", home="H")  # goes on after the fault
    report = acc.finalize({})
    assert report["tables"]["r6_kpi_error"] == "RuntimeError: broken row"
    for key in kx.R6_METRIC_KEYS:
        assert report["metrics"][key] is None, key
    for key, value in healthy["metrics"].items():
        if key not in kx.R6_METRIC_KEYS and key != "extra_inning_game_share":
            assert report["metrics"][key] == value, key
    assert report["coverage"]["games"] == 2


# --- the batted ball -------------------------------------------------------------


def test_statcast_classes_use_10_25_and_50_degrees():
    assert [kx.statcast_class(la) for la in (-20, 9.99, 10, 24.99, 25, 50, 50.01, 80)] == [
        "gb", "gb", "ld", "ld", "fb", "fb", "pu", "pu",
    ]
    assert kx.STATCAST_CLASSES == ("gb", "ld", "fb", "pu")


def test_statcast_shares_exit_velocity_and_hit_rate_by_class():
    log = (
        # Ground balls: 4, one single.
        [_ball("out", la=2.0, ev=80.0, ball_type="gb") for _ in range(3)]
        + [_ball("1b", la=8.0, ev=100.0, ball_type="gb")]
        # Line drives: 3, two hits; the engine calls the 20-degree one a fly.
        + [_ball("2b", la=12.0, ev=95.0, ball_type="ld")]
        + [_ball("1b", la=14.0, ev=95.0, ball_type="ld")]
        + [_ball("out", la=20.0, ev=92.0, ball_type="fb")]
        # Fly balls: 2 home runs and an out that is a sacrifice fly.
        + [_ball("hr", la=28.0, ev=104.0, ball_type="fb", distance=400.0)]
        + [_ball("hr", la=30.0, ev=106.0, ball_type="fb", distance=460.0)]
        + [_ball("sf", la=35.0, ev=90.0, ball_type="fb")]
        # One pop-up.
        + [_ball("out", la=62.0, ev=70.0, ball_type="fb")]
    )
    report = _one_game(log)
    m = report["metrics"]
    assert m["statcast_gb_pct"] == pytest.approx(4 / 11)
    assert m["statcast_ld_pct"] == pytest.approx(3 / 11)
    assert m["statcast_fb_pct"] == pytest.approx(3 / 11)
    assert m["statcast_pu_pct"] == pytest.approx(1 / 11)
    assert m["statcast_gb_ev"] == pytest.approx(85.0)
    assert m["statcast_ld_ev"] == pytest.approx(94.0)
    assert m["statcast_pu_ev"] == pytest.approx(70.0)
    # Hits that stayed in the park over balls that stayed in the park.
    assert m["statcast_gb_hit_rate"] == pytest.approx(1 / 4)
    assert m["statcast_ld_hit_rate"] == pytest.approx(2 / 3)
    assert m["statcast_fb_hit_rate"] == pytest.approx(0.0)  # 0 of the 1 non-HR
    assert m["statcast_pu_hit_rate"] == pytest.approx(0.0)
    # Home runs over fly balls AND pop-ups (2 of 4), a different number from
    # the gated hr_per_fb_pct, which divides by the engine's fly-ball class.
    assert m["hr_per_fb_pu"] == pytest.approx(2 / 4)
    classes = report["tables"]["batted_ball_classes"]
    assert classes["statcast"]["fb"]["hr"] == 2
    # The engine's own classes are reported beside them.
    assert classes["engine"] == pytest.approx({"gb": 4 / 11, "ld": 2 / 11, "fb": 5 / 11})
    assert m["hr_distance_mean_ft"] == pytest.approx(430.0)
    assert m["hr_450plus_share"] == pytest.approx(0.5)
    assert report["tables"]["hr_distance"] == {"n": 2, "longest_ft": 460.0}


def test_pull_side_depends_on_the_batting_side(tmp_path):
    """The spray angle is read as physical: positive is right field, a
    left-handed batter's pull side and a right-handed batter's opposite
    field. A switch hitter bats opposite the pitcher's hand."""
    assert kx.pull_angle(20.0, "L") == 20.0 and kx.pull_angle(20.0, "R") == -20.0
    players = _players(tmp_path, [
        _hitter("R1", bats="R"), _hitter("L1", bats="L"), _hitter("S1", bats="S"),
        _arm("PR", throws="R"), _arm("PL", throws="L"),
    ])
    log = (
        [_ball("out", spray=-20.0, batter="R1", pitcher="PR")] * 3  # pulled
        + [_ball("out", spray=0.0, batter="R1", pitcher="PR")] * 2
        + [_ball("out", spray=20.0, batter="R1", pitcher="PR")]  # opposite field
        + [_ball("out", spray=20.0, batter="L1", pitcher="PR")] * 2  # pulled
        + [_ball("out", spray=-15.0, batter="L1", pitcher="PR")]  # the edge: straight
        + [_ball("hr", spray=30.0, batter="S1", pitcher="PR", distance=380.0)]
        + [_ball("hr", spray=30.0, batter="S1", pitcher="PL", distance=380.0)]
    )
    report = _one_game(log, players)
    m = report["metrics"]
    # Right-handed: R1's six balls and the switch hitter's one off the lefty.
    assert m["pull_pct_rhb"] == pytest.approx(3 / 7)
    assert m["straight_pct_rhb"] == pytest.approx(2 / 7)
    assert m["oppo_pct_rhb"] == pytest.approx(2 / 7)
    # Left-handed: L1's three and the switch hitter's one off the righty.
    assert m["pull_pct_lhb"] == pytest.approx(3 / 4)
    assert m["straight_pct_lhb"] == pytest.approx(1 / 4)
    assert m["oppo_pct_lhb"] == pytest.approx(0.0)
    assert m["pull_pct"] == pytest.approx(6 / 11)
    assert m["straight_pct"] + m["pull_pct"] + m["oppo_pct"] == pytest.approx(1.0)
    spray = report["tables"]["spray_by_batting_side"]
    assert spray["lhb"]["hr_pulled_share"] == 1.0
    assert spray["rhb"]["hr_pulled_share"] == 0.0
    # The three thirds are the benchmark file's names.
    benchmarks = kpis._load_benchmarks(
        REPO / "data" / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"
    )
    assert {"pull_pct", "straight_pct", "oppo_pct"} <= set(benchmarks)


@pytest.mark.parametrize("hand_blind", [True, False])
def test_pull_rating_against_pull_angle_by_side(tmp_path, hand_blind):
    """With a hand-blind spray (today's engine: a high pull rating sends
    every hitter's balls to the positive side) the correlation is +1 for
    left-handed batters and -1 for right-handed ones; with the physical
    angle the spray fix stores it is +1 for both."""
    hitters = [
        _hitter(f"{side}{i}", bats=side, pl=40 + 2 * i)
        for side in ("L", "R") for i in range(12)
    ]
    players = _players(tmp_path, hitters + [_arm("P")])
    log = []
    for row in hitters:
        toward_pull = (row["pl"] - 50) / 2.0
        physical = toward_pull if (hand_blind or row["bats"] == "L") else -toward_pull
        log += [_ball("out", spray=physical, batter=row["player_id"])] * 30
    # 30 games a club: the bar is 30 balls in play from the side.
    m = _one_game(log, players, games_per_team=30)["metrics"]
    assert m["r_pull_rating_pull_angle_lhb"] == pytest.approx(1.0)
    assert m["r_pull_rating_pull_angle_rhb"] == pytest.approx(
        -1.0 if hand_blind else 1.0
    )
    # Too few balls each at a full season's bar (150): not computed.
    assert _one_game(log, players)["metrics"]["r_pull_rating_pull_angle_rhb"] is None


# --- pitching --------------------------------------------------------------------


def test_ground_balls_and_exit_velocity_by_pitch_type():
    log = (
        [_ball("out", pitch_type="fb", ball_type="gb", ev=92.0)]
        + [_ball("out", pitch_type="fb", ball_type="fb", ev=96.0)] * 3
        + [_ball("out", pitch_type="si", ball_type="gb", ev=88.0)] * 3
        + [_ball("out", pitch_type="si", ball_type="ld", ev=84.0)]
        + [_pitch(pitch_type="cb"), _pitch(pitch_type="cb"), _pitch("so", pitch_type="kn")]
    )
    report = _one_game(log)
    m = report["metrics"]
    assert m["gb_pct_pitch_fb"] == pytest.approx(0.25)
    assert m["ev_pitch_fb"] == pytest.approx(95.0)
    assert m["gb_pct_pitch_si"] == pytest.approx(0.75)
    assert m["ev_pitch_si"] == pytest.approx(87.0)
    assert m["gb_pct_pitch_cb"] is None and m["ev_pitch_cu"] is None
    # Fastballs and sinkers over every pitch thrown (8 of 11).
    assert m["fb_si_pitch_share"] == pytest.approx(8 / 11)
    table = report["tables"]["batted_ball_by_pitch_type"]
    assert table["fb"]["pitches"] == 4 and table["si"]["bip"] == 4
    assert "kn" not in table  # thrown, never put in play


def test_least_squares_takes_the_ratings_together():
    rng = random.Random(4)
    xs = [[rng.uniform(30, 70), rng.uniform(30, 70)] for _ in range(60)]
    ys = [3.0 - 0.25 * a + 0.5 * b for a, b in xs]
    weights = [rng.uniform(1, 9) for _ in xs]
    assert kx._least_squares(xs, ys) == pytest.approx([-0.25, 0.5])
    assert kx._least_squares(xs, ys, weights) == pytest.approx([-0.25, 0.5])
    # A column that does not vary is left out, not a reason to give up.
    flat = [[a, 50.0, b] for a, b in xs]
    assert kx._least_squares(flat, ys) == [
        pytest.approx(-0.25), None, pytest.approx(0.5),
    ]
    assert kx._least_squares([[1.0, 2.0]], [1.0]) == [None, None]
    assert kx._least_squares([], []) == []
    # Weights matter when the relation is not exact: the heavy rows win.
    xs2 = [[0.0], [1.0], [0.0], [1.0]]
    ys2 = [0.0, 1.0, 0.0, 3.0]
    assert kx._least_squares(xs2, ys2, [1, 1, 1, 9])[0] == pytest.approx(2.8)
    # One sd of x moves y by r sd when there is one regressor.
    xs3 = [[float(i)] for i in range(40)]
    ys3 = [float(i) + (5.0 if i % 2 else -5.0) for i in range(40)]
    beta = kx._standardised_betas(xs3, ys3)[0]
    assert beta == pytest.approx(kx._pearson([x[0] for x in xs3], ys3))


def _pitcher_season(pid, *, so, bb=60, hr=20, hbp=5, outs=600, bf=800, er=70):
    return {
        "player_id": pid, "gs": 1, "bf": bf, "so": so, "bb": bb, "ibb": 0,
        "hr": hr, "hbp": hbp, "outs": outs, "r": er + 5, "er": er, "h": 150,
        "pitches": 100,
    }


def test_what_each_pitcher_rating_is_worth(tmp_path):
    """Strikeouts are built from the arm and the pitch grade alone: +10 arm
    is +2 points of K, +10 grade +4, control and movement nothing."""
    rng = random.Random(11)
    arms, lines = [], []
    for i in range(40):
        arm, grade = rng.randrange(40, 61), rng.randrange(40, 61)
        control, movement = rng.randrange(40, 61), rng.randrange(40, 61)
        pid = f"P{i}"
        arms.append(_arm(pid, arm=arm, control=control, movement=movement, grade=grade))
        # 800 batters faced: a point of K% is 8 strikeouts.
        so = 160 + round(1.6 * (arm - 50) + 3.2 * (grade - 50))
        lines.append(_pitcher_season(pid, so=so))
    players = _players(tmp_path, arms)
    report = _one_game([], players, pitcher_lines={"away": lines, "home": []})
    m = report["metrics"]
    assert m["pitcher_k_pct_per10_arm"] == pytest.approx(2.0, abs=0.05)
    assert m["pitcher_k_pct_per10_grade"] == pytest.approx(4.0, abs=0.05)
    assert m["pitcher_k_pct_per10_control"] == pytest.approx(0.0, abs=0.05)
    assert m["pitcher_k_pct_per10_movement"] == pytest.approx(0.0, abs=0.05)
    # FIP = (13 HR + 3 (BB + HBP) - 2 K) / IP over 200 innings: 16 more
    # strikeouts per +10 arm are -0.16 of FIP, 32 per +10 grade -0.32.
    assert m["pitcher_fip_per10_arm"] == pytest.approx(-0.16, abs=0.005)
    assert m["pitcher_fip_per10_grade"] == pytest.approx(-0.32, abs=0.005)
    assert m["pitcher_fip_per10_control"] == pytest.approx(0.0, abs=0.005)
    # In standard deviations the grade carries twice the arm, and nearly all
    # of it between them.
    slopes = report["tables"]["pitcher_rating_slopes"]
    assert slopes["pitchers"] == 40 and slopes["min_outs"] == 120
    betas = slopes["k_std_beta"]
    assert m["pitcher_k_std_beta_grade"] == betas["grade"]
    # slope x sd(rating) / sd(K rate), with the slopes the season was built on.
    sd_k = statistics.pstdev(line["so"] / 800 for line in lines)
    sd_arm = statistics.pstdev(float(row["arm"]) for row in arms)
    sd_grade = statistics.pstdev(float(row["fb"]) for row in arms)
    assert betas["arm"] == pytest.approx(0.002 * sd_arm / sd_k, abs=0.01)
    assert betas["grade"] == pytest.approx(0.004 * sd_grade / sd_k, abs=0.01)
    assert betas["grade"] > 1.5 * betas["arm"] > 0.3
    assert abs(betas["control"]) < 0.02 and abs(betas["movement"]) < 0.02
    assert set(slopes["bb"]) == {"arm", "control", "movement", "grade"}
    # Everyone threw 200 innings, so all 40 are ERA-qualified: FIP varies
    # only through strikeouts.
    assert m["qualified_fip_sd"] > 0.0


def test_too_few_pitchers_is_none_not_a_guess(tmp_path):
    arms = [_arm(f"P{i}", arm=40 + i) for i in range(12)]
    lines = [_pitcher_season(f"P{i}", so=150 + i) for i in range(12)]
    players = _players(tmp_path, arms)
    report = _one_game([], players, pitcher_lines={"away": lines, "home": []})
    assert report["metrics"]["pitcher_fip_per10_arm"] is None
    assert report["metrics"]["pitcher_k_std_beta_grade"] is None
    assert report["tables"]["pitcher_rating_slopes"]["pitchers"] == 12
    assert report["metrics"]["qualified_fip_sd"] is not None  # 12 qualified


def test_pitcher_ground_ball_identity(tmp_path):
    """A pitcher's GB% against his ground-ball rating, and the true spread."""
    arms, lines, log = [], [], []
    for i in range(30):
        pid = f"P{i}"
        arms.append(_arm(pid, gf=35 + i))
        lines.append(_pitcher_season(pid, so=160))
        grounders = 20 + i  # of 60 balls in play: 33% to 82%
        log += [_ball("out", pitcher=pid, ball_type="gb", ev=85.0)] * grounders
        log += [_ball("out", pitcher=pid, ball_type="fb", ev=95.0)] * (60 - grounders)
    players = _players(tmp_path, arms)
    # 30 games a club: the bar is 50 balls in play and 40 * 30 / 162 innings.
    report = _one_game(
        log, players, games_per_team=30, pitcher_lines={"away": lines, "home": []}
    )
    m = report["metrics"]
    assert m["r_pitcher_gf_gb_pct"] == pytest.approx(1.0)
    rates = [(20 + i) / 60 for i in range(30)]
    sd, _var, n = kx.true_sd([(20 + i, 60) for i in range(30)])
    assert n == 30 and m["pitcher_gb_pct_true_sd"] == pytest.approx(sd)
    assert 0.10 < m["pitcher_gb_pct_true_sd"] < max(rates) - min(rates)
    assert report["tables"]["pitcher_gb_pct_dispersion"]["min_bip"] == 50
    # Exit velocity allowed varies with the mix of grounders and flies.
    assert m["qualified_ev_against_sd"] > 0.0
    # The table of true spreads the earlier releases wrote is untouched.
    assert "pitcher_gb_pct" not in report["tables"]["dispersion"]


def _starter_lines(*pids):
    return {"away": [], "home": [{"player_id": pid, "gs": 1} for pid in pids]}


def test_the_same_starter_at_pitches_91_to_105():
    """Strikeouts, walks and exit velocity late in the outing against the
    first 25 pitches, within the pitcher and weighted by his late PA."""
    log = []
    # SP1 early: 2 K in 4 PA, the balls in play at 88 mph.
    log += [_pitch("so", pitcher="SP1", pitch_count=3)] * 2
    log += [_ball("out", pitcher="SP1", pitch_count=10, ev=88.0)] * 2
    # SP1 late: 0 K, 1 BB, 3 balls in play at 94 mph.
    log += [_pitch("bb", outcome="ball", pitcher="SP1", pitch_count=95)]
    log += [_ball("1b", pitcher="SP1", pitch_count=100, ev=94.0)] * 3
    # SP2 never gets there: he counts for nothing.
    log += [_pitch("so", pitcher="SP2", pitch_count=5)] * 3
    # A reliever's 95th pitch is not a starter's.
    log += [_pitch("bb", outcome="ball", pitcher="RP", pitch_count=95)]
    # Pitches 26-90 are in neither bucket.
    log += [_pitch("so", pitcher="SP1", pitch_count=50)] * 5
    m = _one_game(log, pitcher_lines=_starter_lines("SP1", "SP2"))["metrics"]
    assert m["starter_k_pct_delta_91_105"] == pytest.approx(0.0 - 0.5)
    assert m["starter_bb_pct_delta_91_105"] == pytest.approx(0.25 - 0.0)
    assert m["starter_ev_delta_91_105"] == pytest.approx(94.0 - 88.0)


def test_the_batter_adjustment_takes_out_who_was_at_the_plate():
    """A starter faces the weak bottom of the order fresh and the strong top
    of it tired. Raw, he looks far worse tired; against each hitter's own
    season he is exactly as good."""
    weak = [_ball("out", batter="WEAK", pitcher="SP", pitch_count=5)] * 4
    strong = [_ball("hr", batter="STRONG", pitcher="SP", pitch_count=95,
                    distance=400.0)] * 4
    report = _one_game(weak + strong, pitcher_lines=_starter_lines("SP"))
    m = report["metrics"]
    assert m["starter_woba_delta_91_105"] == pytest.approx(2.05)  # the raw row
    assert m["starter_woba_delta_91_105_batter_adj"] == pytest.approx(0.0)
    row = report["tables"]["batter_adjusted_deltas"]["starter_woba_delta_91_105"]
    assert row["starters_raw"] == pytest.approx(m["starter_woba_delta_91_105"])
    assert row["pa"] == 4

    # Now the strong hitter does better off this starter late than he does
    # over his season (outs against a reliever pull his mean down).
    elsewhere = [_ball("out", batter="STRONG", pitcher="RP")] * 4
    report = _one_game(
        weak + strong + elsewhere, pitcher_lines=_starter_lines("SP")
    )
    m = report["metrics"]
    assert m["starter_woba_delta_91_105"] == pytest.approx(2.05)
    # His season mean is 2.05 / 2; the late PA sit 1.025 above it.
    assert m["starter_woba_delta_91_105_batter_adj"] == pytest.approx(1.025)


def test_the_times_through_the_order_deltas_are_adjusted_the_same_way():
    log = []
    # Pass 1: the starter gets WEAK out four times. Pass 2: STRONG singles
    # twice in four. Pass 3: STRONG homers once in two.
    log += [_ball("out", batter="WEAK", pitcher="SP", tto=1)] * 4
    log += [_ball("1b", batter="STRONG", pitcher="SP", tto=2)] * 2
    log += [_ball("out", batter="STRONG", pitcher="SP", tto=2)] * 2
    log += [_ball("hr", batter="STRONG", pitcher="SP", tto=4, distance=400.0)]
    log += [_ball("out", batter="STRONG", pitcher="SP", tto=3)]
    report = _one_game(log, pitcher_lines=_starter_lines("SP"))
    m = report["metrics"]
    strong_mean = (2 * 0.88 + 2.05) / 6
    assert m["tto_pass2_woba_delta"] == pytest.approx(0.44)
    assert m["tto_pass2_woba_delta_batter_adj"] == pytest.approx(0.44 - strong_mean)
    assert m["tto_pass3_woba_delta"] == pytest.approx(1.025)  # pass 4 is pass 3
    assert m["tto_pass3_woba_delta_batter_adj"] == pytest.approx(1.025 - strong_mean)
    table = report["tables"]["batter_adjusted_deltas"]
    assert table["tto_pass2_woba_delta"]["pa"] == 4
    assert table["tto_pass3_woba_delta"]["pa"] == 2
    # A reliever's second look at a hitter is not in the starters' rows.
    relief = [_ball("out", batter="B", pitcher="RP", tto=1),
              _ball("hr", batter="B", pitcher="RP", tto=2, distance=400.0)]
    report = _one_game(log + relief, pitcher_lines=_starter_lines("SP"))
    again = report["tables"]["batter_adjusted_deltas"]["tto_pass2_woba_delta"]
    assert again["pa"] == 4 and again["starters_raw"] == pytest.approx(0.44)
    # Intentional walks and sacrifice bunts are in neither side.
    assert kx._starter_pa_delta([], {}, 3, 1, 2) == (None, None, 0)


# --- power -----------------------------------------------------------------------


def _bat_line(pid, *, hr=10, b2=20, so=100, pa=600, ab=540, h=150, b3=2):
    return {
        "player_id": pid, "pa": pa, "ab": ab, "h": h, "b2": b2, "b3": b3,
        "hr": hr, "so": so,
    }


def _power_season(tmp_path, rows, lines, games_per_team=162):
    players = _players(tmp_path, rows)
    return _one_game(
        [], players, games_per_team, batting_lines={"away": lines, "home": []}
    )


def test_home_runs_by_power_fifth(tmp_path):
    """50 hitters, Power 30-79, each hitting (Power - 20) home runs."""
    rows = [_hitter(f"H{i:02d}", ph=30 + i) for i in range(50)]
    lines = [_bat_line(f"H{i:02d}", hr=10 + i) for i in range(50)]
    report = _power_season(tmp_path, rows, lines)
    m = report["metrics"]
    # Fifths of ten: mean HR 14.5, 24.5, 34.5, 44.5, 54.5 per 600 PA.
    for i, expected in enumerate((14.5, 24.5, 34.5, 44.5, 54.5), start=1):
        assert m[f"hr600_power_q{i}"] == pytest.approx(expected)
    assert m["hr_power_bottom_quintile_ratio"] == pytest.approx(14.5 / 34.5)
    table = report["tables"]["hr600_by_power_quintile"]
    assert [row["n"] for row in table] == [10] * 5
    assert table[0]["mean_power"] == pytest.approx(34.5)
    bands = report["tables"]["hr600_by_power_band"]
    assert bands["0-42"]["n"] == 12 and bands["62-101"]["n"] == 18
    assert bands["0-42"]["hr600"] == pytest.approx(15.5)
    assert report["tables"]["qualified_hitters"] == {"n": 50, "min_pa": 502}
    # The spread of the totals themselves, and the 30-homer share (30+).
    assert m["qualified_hr600_q1"] == pytest.approx(14.5)
    assert m["qualified_hr600_median"] == pytest.approx(34.5)
    assert m["qualified_hr600_q5"] == pytest.approx(54.5)
    assert m["hr30_share_of_qualified"] == pytest.approx(30 / 50)


def test_hitters_tied_in_power_share_their_group(tmp_path):
    """Ratings are whole numbers, so a fifth's edge falls inside a tie. The
    answer must not depend on the order of the tied hitters -- sorting them
    by home runs, as the design prototype did, reads the weak fifth low."""
    powers = [45] * 14 + [50] * 22 + [55] * 14
    rng = random.Random(3)
    homers = [rng.randrange(5, 40) for _ in powers]
    rows = [_hitter(f"H{i:02d}", ph=p) for i, p in enumerate(powers)]
    lines = [_bat_line(f"H{i:02d}", hr=h) for i, h in enumerate(homers)]
    (tmp_path / "a").mkdir()
    first = _power_season(tmp_path / "a", rows, lines)["metrics"]
    # The same season with the players renamed and listed in another order.
    order = list(range(50))
    rng.shuffle(order)
    renamed = {i: f"Z{rank:02d}" for rank, i in enumerate(order)}
    rows2 = [_hitter(renamed[i], ph=powers[i]) for i in order]
    lines2 = [_bat_line(renamed[i], hr=homers[i]) for i in order]
    (tmp_path / "b").mkdir()
    second = _power_season(tmp_path / "b", rows2, lines2)["metrics"]
    for key in [f"hr600_power_q{i}" for i in range(1, 6)] + [
        "hr_power_bottom_quintile_ratio"
    ]:
        assert first[key] == pytest.approx(second[key]), key
    # The weakest ten are all Power 45: the mean of all fourteen of them.
    mean_45 = sum(homers[:14]) / 14
    assert first["hr600_power_q1"] == pytest.approx(mean_45)
    # The prototype's order (ties by home runs) gives a lower weak fifth.
    by_hr = sorted(zip(powers, homers))
    assert sum(h for _p, h in by_hr[:10]) / 10 < mean_45

    tied = kx._tie_averaged(
        [{"k": 1, "v": 0.0}, {"k": 2, "v": 9.0}, {"k": 1, "v": 4.0}], "k", ("v",)
    )
    assert [(row["k"], row["v"]) for row in tied] == [(1, 2.0), (1, 2.0), (2, 9.0)]


def test_doubles_by_power_and_contact(tmp_path):
    """Doubles are built as 12 + 0.6 per Contact point + 0.2 per Power
    point: +6 and +2 per 600 PA per +10 of the rating."""
    rng = random.Random(8)
    rows, lines = [], []
    for i in range(45):
        ph, ch = rng.randrange(40, 61), rng.randrange(40, 61)
        b2 = round(12 + 0.6 * (ch - 40) + 0.2 * (ph - 40))
        rows.append(_hitter(f"H{i:02d}", ph=ph, ch=ch))
        lines.append(_bat_line(f"H{i:02d}", b2=b2, hr=15, so=120 - (ch - 50)))
    m = _power_season(tmp_path, rows, lines)["metrics"]
    # The rounding to whole doubles is the slack.
    assert m["doubles_per10_contact"] == pytest.approx(6.0, abs=0.25)
    assert m["doubles_per10_power"] == pytest.approx(2.0, abs=0.25)
    # Everyone hit 15 home runs: doubles cannot go with them.
    assert m["corr_2b_hr"] is None
    # More Contact, fewer strikeouts and more doubles: K% against ISO.
    assert m["corr_k_iso"] < -0.9
    # Everyone has the same ground-ball rating: the thirds are one group.
    assert m["doubles600_gf_t1"] == pytest.approx(m["doubles600_gf_t3"])


def test_doubles_by_ground_ball_rating_third(tmp_path):
    """t1 is the lowest gf, the line-drive and fly-ball bats."""
    doubles = {45: 30, 50: 24, 55: 18}
    rows, lines = [], []
    for i in range(45):
        gf = (45, 50, 55)[i % 3]
        rows.append(_hitter(f"H{i:02d}", gf=gf))
        lines.append(_bat_line(f"H{i:02d}", b2=doubles[gf], hr=10 + i % 5))
    report = _power_season(tmp_path, rows, lines)
    m = report["metrics"]
    assert m["doubles600_gf_t1"] == pytest.approx(30.0)
    assert m["doubles600_gf_t2"] == pytest.approx(24.0)
    assert m["doubles600_gf_t3"] == pytest.approx(18.0)
    table = report["tables"]["doubles600_by_gf_tercile"]
    assert [row["n"] for row in table] == [15, 15, 15]
    assert [row["mean_gf"] for row in table] == [45.0, 50.0, 55.0]
    # Power and Contact do not vary here: no slope, not a zero.
    assert m["doubles_per10_power"] is None and m["doubles_per10_contact"] is None


def test_power_rows_need_qualified_hitters(tmp_path):
    rows = [_hitter(f"H{i:02d}", ph=40 + i) for i in range(40)]
    lines = [_bat_line(f"H{i:02d}", hr=i, pa=501, ab=450) for i in range(40)]
    m = _power_season(tmp_path, rows, lines)["metrics"]
    for key in ("hr600_power_q1", "hr_power_bottom_quintile_ratio", "corr_k_iso",
                "qualified_hr600_median", "hr30_share_of_qualified",
                "doubles_per10_power", "doubles600_gf_t2"):
        assert m[key] is None, key
    # 81 games: the bar is 251 PA and a 30-homer pace is 15.
    (tmp_path / "half").mkdir()
    half = _power_season(tmp_path / "half", rows, lines, games_per_team=81)["metrics"]
    assert half["hr30_share_of_qualified"] == pytest.approx(25 / 40)


# --- fielding ----------------------------------------------------------------------


def test_plays_by_position_come_from_the_engine_s_own_credit():
    log = (
        [_ball("out", ball_type="gb", la=2.0, fld_pos="SS", out_type="groundout")] * 4
        + [_ball("out", ball_type="gb", la=2.0, fld_pos="2B", out_type="groundout")] * 3
        + [_ball("out", ball_type="gb", la=2.0, fld_pos="3B", out_type="groundout")]
        + [_ball("out", ball_type="gb", la=2.0, fld_pos="1B", out_type="groundout")]
        # An error on a grounder is a ground-ball play at that position.
        + [_ball("roe", ball_type="gb", la=2.0, fld_pos="SS", reached_on_error=True)]
        # A ground-ball single is credited to nobody.
        + [_ball("1b", ball_type="gb", la=2.0)] * 5
        # Air outs: three to centre, one to each corner, a liner to short.
        + [_ball("out", ball_type="fb", la=30.0, fld_pos="CF", out_type="flyout")] * 3
        + [_ball("out", ball_type="fb", la=30.0, fld_pos="LF", out_type="flyout")]
        + [_ball("sf", ball_type="fb", la=30.0, fld_pos="RF", out_type="flyout")]
        + [_ball("out", ball_type="ld", la=12.0, fld_pos="SS", out_type="lineout")]
        # A dropped fly is no putout.
        + [_ball("roe", ball_type="fb", la=30.0, fld_pos="LF", reached_on_error=True)]
    )
    report = _one_game(log)
    m = report["metrics"]
    assert m["gb_play_share_ss"] == pytest.approx(5 / 10)
    assert m["gb_play_share_2b"] == pytest.approx(3 / 10)
    assert m["gb_play_share_3b"] == m["gb_play_share_1b"] == pytest.approx(1 / 10)
    assert m["of_putout_share_cf"] == pytest.approx(3 / 5)
    assert m["of_putout_share_lf"] == m["of_putout_share_rf"] == pytest.approx(1 / 5)
    plays = report["tables"]["plays_by_position"]
    assert plays["ground_ball"] == {"SS": 5, "2B": 3, "3B": 1, "1B": 1}
    assert plays["air_out"] == {"CF": 3, "LF": 1, "RF": 1, "SS": 1}


def test_a_game_without_play_records_reads_none_not_zero():
    log = [_ball("out", ball_type="gb", la=2.0, out_type="groundout")]
    report = _one_game(log)
    m = report["metrics"]
    for key in ("gb_play_share_ss", "of_putout_share_cf", "e_per_team_game_ss",
                "off_primary_slot_share", "secondary_slot_share"):
        assert m[key] is None, key
    assert m["statcast_gb_pct"] == 1.0  # the rest of the block still reads
    # A result object with no play_records at all (an older engine's).
    acc = _acc()
    bare = _game(log)
    del bare.play_records
    acc.add_game(bare, away="A", home="H")
    assert _report(acc)["metrics"]["gb_play_share_ss"] is None
    # A position the log entry itself carries is not a play record.
    stray = dict(log[0], fld_pos="SS")
    acc = _acc()
    acc.add_game(
        SimpleNamespace(totals={}, pitch_log=[stray], metadata={}, play_records={}),
        away="A", home="H",
    )
    assert _report(acc)["metrics"]["gb_play_share_ss"] is None


def test_errors_and_fielder_slots_by_starting_position(tmp_path):
    players = _players(tmp_path, [
        _hitter("SS1", pos="SS"), _hitter("UT1", pos="2B", other="['SS', '3B']"),
        _hitter("UT2", pos="CF", other="LF|RF"), _hitter("OOP", pos="1B"),
        _hitter("DH1", pos="DH"), _hitter("BENCH", pos="LF"), _arm("ARM"),
    ])
    home = {"SS1": "SS", "UT1": "3B", "UT2": "LF", "OOP": "CF", "DH1": "DH"}
    away = {"SS1": "SS", "UT1": "2B", "UT2": "CF", "OOP": "1B"}
    fielding = {
        "home": [
            {"player_id": "SS1", "e": 2}, {"player_id": "UT1", "e": 1},
            {"player_id": "ARM", "e": 1}, {"player_id": "BENCH", "e": 1},
            {"player_id": "DH1", "e": 0},
        ],
        "away": [{"player_id": "OOP", "e": 1}],
    }
    game = dict(
        fielding_lines=fielding,
        pitcher_lines={"home": [{"player_id": "ARM", "gs": 1}], "away": []},
        records={"starting_positions": {"home": home, "away": away}},
    )
    acc = _acc(players)
    acc.add_game(_game([], **game), away="A", home="H")
    acc.add_game(_game([], **game), away="A", home="H")
    report = _report(acc)
    m = report["metrics"]
    # Two games, four team-games: errors per team-game by starting position.
    assert m["e_per_team_game_ss"] == pytest.approx(4 / 4)
    assert m["e_per_team_game_3b"] == pytest.approx(2 / 4)
    assert m["e_per_team_game_1b"] == pytest.approx(2 / 4)
    assert m["e_per_team_game_p"] == pytest.approx(2 / 4)
    assert m["e_per_team_game_c"] == 0.0 and m["e_per_team_game_cf"] == 0.0
    # The man off the bench is in the table, at no position.
    assert report["tables"]["errors_by_position"]["SUB"] == 2
    # Eight fielder-slots a game (the DH is not one): two at a listed second
    # position (UT1 at third, UT2 in left), one at an unlisted one (OOP in
    # centre), five at the primary.
    slots = report["tables"]["fielder_slots"]
    assert slots == {"n": 16, "primary": 10, "secondary": 4, "unlisted": 2}
    assert m["off_primary_slot_share"] == pytest.approx(6 / 16)
    assert m["secondary_slot_share"] == pytest.approx(4 / 16)


def test_unearned_run_share():
    lines = {
        "away": [{"player_id": "P1", "r": 6, "er": 4}],
        "home": [{"player_id": "P2", "r": 4, "er": 4}, {"player_id": "P3", "r": 0}],
    }
    m = _one_game([], pitcher_lines=lines)["metrics"]
    assert m["unearned_run_share"] == pytest.approx(2 / 10)
    assert _one_game([])["metrics"]["unearned_run_share"] is None


# --- on the real engine ----------------------------------------------------------


def test_a_real_short_season_fills_every_group(monkeypatch):
    """Two calibration clubs, generation 5: the rows the engine's play
    records feed are read, and the gated metrics hold none of them."""
    from physics_sim.engine_generation import engine_profile

    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    summary = kpis.run_sim(
        games_per_team=30, seed=3, players_path=CAL / "players.csv",
        tuning_overrides=engine_profile(5), base_dir=CAL,
    )
    report = summary["report_only"]
    assert "error" not in report and "r6_kpi_error" not in report["tables"]
    m = report["metrics"]
    assert not set(kx.R6_METRIC_KEYS) & set(summary["metrics"])
    classes = sum(m[f"statcast_{name}_pct"] for name in kx.STATCAST_CLASSES)
    assert classes == pytest.approx(1.0)
    thirds = m["pull_pct"] + m["straight_pct"] + m["oppo_pct"]
    assert thirds == pytest.approx(1.0)
    infield = sum(m[f"gb_play_share_{p}"] for p in ("1b", "2b", "3b", "ss"))
    assert infield == pytest.approx(1.0)  # today only infielders field grounders
    outfield = sum(m[f"of_putout_share_{p}"] for p in ("lf", "cf", "rf"))
    assert outfield == pytest.approx(1.0)
    errors = sum(m[f"e_per_team_game_{p.lower()}"] for p in kx.R6_FIELD_POSITIONS)
    bench = report["tables"]["errors_by_position"].get("SUB", 0) / 60
    assert errors + bench == pytest.approx(m["e_per_team_game"])
    assert 0.0 <= m["off_primary_slot_share"] < 0.5
    assert m["secondary_slot_share"] <= m["off_primary_slot_share"]
    assert report["tables"]["fielder_slots"]["n"] == 30 * 2 * 8
    assert 0.0 < m["unearned_run_share"] < 0.3
    assert 0.3 < m["fb_si_pitch_share"] < 0.6
    assert 350.0 < m["hr_distance_mean_ft"] < 500.0
    assert m["hr_per_fb_pu"] > summary["metrics"]["hr_per_fb_pct"] > 0.0
    assert m["starter_woba_delta_91_105_batter_adj"] is None or isinstance(
        m["starter_woba_delta_91_105_batter_adj"], float
    )
    raw = report["tables"]["batter_adjusted_deltas"]["tto_pass2_woba_delta"]
    assert raw["pa"] > 200 and isinstance(m["tto_pass2_woba_delta_batter_adj"], float)
    # The harness told the engine the centres only it supplies.
    extra = summary["meta"]["unstored_rating_centers"]
    assert extra["fielder_fa_center_ss"] > 40.0
    assert extra["hitter_pull_center"] > 40.0
    assert not set(extra) & set(summary["meta"]["rating_centers"])
    text = kx.format_report(report)
    assert "statcast_ld_pct" in text and "pitcher_fip_per10_arm" in text
