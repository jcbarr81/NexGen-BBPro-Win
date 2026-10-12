"""Release 5a (tooling): the report-only KPIs Release 5 tunes against
(scripts/kpi_extras.py ``_add_r5`` / ``_r5_metrics`` and the matchup-grid
tables). They read the pitch log and box lines the engine already writes
and are never a strict gate.
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.kpi_extras as kx
import scripts.physics_sim_season_kpis as kpis

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"

COUNT_KEYS = [c.replace("-", "_") for c in kx.COUNTS]
R5A_METRICS = (
    ["foul_per_two_strike_pitch", "foul_share_of_contact", "looking_k_per_pa"]
    + [f"zone_swing_rate_{c}" for c in COUNT_KEYS]
    + [f"chase_swing_rate_{c}" for c in COUNT_KEYS]
    + [
        "bb_pct_per10_eye", "bb_pct_per10_control", "k_pct_per10_contact",
        "hitter_o_z_swing_corr", "pitcher_zone_pct_true_sd", "hbp_in_zone_share",
        "hbp_same_over_opposite_hand",
        "oz_take_called_strike_rate", "iz_take_called_ball_rate",
        "ibb_late_close_share", "hitter_avg_true_sd", "babip_contact_slope_per10",
        "r_ch_babip", "platoon_gap_k_pct", "platoon_gap_bb_pct", "platoon_gap_iso",
        "switch_woba_vs_lhp", "switch_woba_vs_rhp", "rhb_share_of_pa_vs_lhp",
        "late_close_ubb_pct_delta", "bb_pct_empty_minus_r1",
        "relief_bf1_6_minus_starter_pass1_woba", "save_conversion",
        "home_minus_away_woba", "tto_ops_gap_starters", "lineup_hand_match_rate",
    ]
)
GRID_METRICS = (
    [f"matchup_looking_k_share_ch{c}" for c in (35, 50, 65, 80)]
    + [f"matchup_looking_k_per_pa_ch{c}" for c in (35, 50, 65, 80)]
    + [
        f"matchup_platoon_hr_ratio_{side}_ph{int(level)}"
        for side in ("lhb", "rhb") for level in kx.PLATOON_GRID_POWER
    ]
)


def _pitch(count="0-0", *, zone=True, swing=False, outcome=None, batter="B",
           pitcher="P", **extra):
    """One pitch_log entry. Default outcome: a take called by location."""
    if outcome is None:
        outcome = "strike" if zone else "ball"
    entry = {
        "pitch_type": "fb", "count": count, "in_zone": zone, "swing": swing,
        "contact": outcome in ("foul", "in_play"), "outcome": outcome,
        "batter_id": batter, "pitcher_id": pitcher, "tto": 1, "pitch_count": 1,
    }
    entry.update(extra)
    return entry


def _state(inning=1, half="top", outs=0, bases=0, bat=0, fld=0):
    return {
        "pa_start": True, "inning": inning, "half": half, "outs_before": outs,
        "bases_before": bases, "bat_score_before": bat, "fld_score_before": fld,
    }


def _pa(token, *pitches, state=None, **last):
    """A plate appearance: its pitches (a single in-play swing by default),
    the PA-start state on the first and the result on the last."""
    entries = [dict(p) for p in pitches] or [_pitch(swing=True, outcome="in_play")]
    entries[0].update(state if state is not None else _state())
    entries[-1].update(last)
    entries[-1]["pa_result"] = token
    return entries


def _game(log, *, pitcher_lines=None, batting_lines=None, meta=None):
    metadata = {
        "inning_runs": {"away": [0], "home": [0]},
        "score": {"away": 0, "home": 0},
        "innings": 1,
        "pitcher_lines": pitcher_lines or {"away": [], "home": []},
        "batting_lines": batting_lines or {"away": [], "home": []},
        "fielding_lines": {"away": [], "home": []},
    }
    metadata.update(meta or {})
    return SimpleNamespace(totals={}, pitch_log=log, metadata=metadata)


def _acc(players: Path | None = None, games_per_team: int = 162):
    return kx.ReportOnlyKpis(
        players_path=players or Path("missing.csv"), games_per_team=games_per_team
    )


def _finalize(acc):
    return acc.finalize(kx.load_reference())


# --- never a gate ---------------------------------------------------------------


def test_every_key_is_reported_and_none_is_a_gate():
    metrics = _acc().finalize({})["metrics"]
    for key in R5A_METRICS:
        assert key in metrics and metrics[key] is None, key
    gated = (
        set(kpis.DEFAULT_TOLERANCES)
        | set(kpis.REPORT_ONLY_TOLERANCES)
        | set(kpis.STRICT_EXTRAS_TARGETS)
        | set(kpis.RATING_OUTCOME_TARGETS)
        | {k for keys in kpis.GATE_SETS.values() for k in keys}
        | {k for tol in kpis.GATE_SET_TOLERANCES.values() for k in tol}
    )
    assert not gated & (set(R5A_METRICS) | set(GRID_METRICS))
    # The strict times-through-order gate is still the league one.
    assert "tto_ops_gap" in kpis.DEFAULT_TOLERANCES
    assert "tto_ops_gap" not in metrics


def test_reference_rows_come_from_the_statcast_counts_file():
    ref = kx.load_reference()
    rows = {}
    with (REPO / "data" / "MLB_avg" / "statcast_counts_2023.csv").open() as fh:
        for row in csv.DictReader(fh):
            rows[f"{row['balls']}_{row['strikes']}"] = row
    for count in COUNT_KEYS:
        assert ref[f"zone_swing_rate_{count}"]["value"] == pytest.approx(
            float(rows[count]["zone_swing_rate"]), abs=5e-5
        )
        assert ref[f"chase_swing_rate_{count}"]["value"] == pytest.approx(
            float(rows[count]["chase_rate"]), abs=5e-5
        )
    two = [rows[c] for c in COUNT_KEYS if c.endswith("_2")]
    fouls = sum(int(r["fouls"]) for r in two)
    assert ref["foul_per_two_strike_pitch"]["value"] == pytest.approx(
        fouls / sum(int(r["pitches"]) for r in two), abs=5e-5
    )
    every = [rows[c] for c in COUNT_KEYS]
    all_fouls = sum(int(r["fouls"]) for r in every)
    in_play = sum(int(r["ball_in_play"]) for r in every)
    assert ref["foul_share_of_contact"]["value"] == pytest.approx(
        all_fouls / (all_fouls + in_play), abs=5e-5
    )
    assert ref["looking_k_per_pa"]["value"] == pytest.approx(0.052, abs=0.001)
    assert ref["lineup_hand_match_rate"]["value"] == 1
    assert ref["hbp_in_zone_share"]["value"] == 0


# --- pitch level -----------------------------------------------------------------


def _discipline_game():
    log = []
    # PA 1: 0-0 zone take (strike), 0-1 chase swing foul, 0-2 zone swing
    # foul, 0-2 zone take: a called third strike.
    log += _pa(
        "so",
        _pitch("0-0", zone=True),
        _pitch("0-1", zone=False, swing=True, outcome="foul"),
        _pitch("0-2", zone=True, swing=True, outcome="foul"),
        _pitch("0-2", zone=True),
        strikeout_type="called",
    )
    # PA 2: 0-0 chase take (ball), 1-0 chase take called a strike, 1-1 zone
    # take called a ball, 2-1 zone swing and miss, 2-2 chase swing and miss.
    log += _pa(
        "so",
        _pitch("0-0", zone=False),
        _pitch("1-0", zone=False, outcome="strike"),
        _pitch("1-1", zone=True, outcome="ball"),
        _pitch("2-1", zone=True, swing=True, outcome="swinging_strike"),
        _pitch("2-2", zone=False, swing=True, outcome="swinging_strike"),
        strikeout_type="swinging",
    )
    # PA 3: hit by a pitch in the zone; PA 4: hit by one off the plate.
    log += _pa("hbp", _pitch("0-0", zone=True, outcome="hbp"))
    log += _pa("hbp", _pitch("0-0", zone=False, outcome="hbp"))
    # PA 5: 0-0 zone swing in play.
    log += _pa("out", _pitch("0-0", zone=True, swing=True, outcome="in_play"))
    return _game(log)


def test_fouls_called_strikes_and_swings_by_count_and_location():
    acc = _acc()
    acc.add_game(_discipline_game(), away="A", home="H")
    report = _finalize(acc)
    m, t = report["metrics"], report["tables"]
    # Two-strike pitches: 0-2 (x2) and 2-2; one foul.
    assert m["foul_per_two_strike_pitch"] == pytest.approx(1 / 3)
    # Two fouls and one ball in play.
    assert m["foul_share_of_contact"] == pytest.approx(2 / 3)
    assert m["looking_k_per_pa"] == pytest.approx(1 / 5)
    # 0-0: zone pitches = take, hbp, in play (1 swing of 3); chase pitches =
    # take, hbp (no swing).
    assert m["zone_swing_rate_0_0"] == pytest.approx(1 / 3)
    assert m["chase_swing_rate_0_0"] == pytest.approx(0.0)
    assert m["chase_swing_rate_0_1"] == pytest.approx(1.0)
    assert m["zone_swing_rate_0_1"] is None
    assert m["zone_swing_rate_0_2"] == pytest.approx(1 / 2)
    assert m["chase_swing_rate_2_2"] == pytest.approx(1.0)
    assert m["zone_swing_rate_3_2"] is None and m["chase_swing_rate_3_2"] is None
    row = t["zone_chase_swing_by_count"]["0-0"]
    assert (row["zone_pitches"], row["chase_pitches"]) == (3, 2)
    # The zone and chase rows add up to the existing per-count swing rate.
    assert m["swing_rate_0_0"] == pytest.approx(1 / 5)
    # Hit batters and takes. Takes out of the zone: 0-0 ball, 1-0 strike.
    # Takes in the zone: 0-0 strike, 0-2 strike, 1-1 ball.
    assert m["hbp_in_zone_share"] == pytest.approx(1 / 2)
    assert m["oz_take_called_strike_rate"] == pytest.approx(1 / 2)
    assert m["iz_take_called_ball_rate"] == pytest.approx(1 / 3)
    assert t["r5_counts"]["pitch"]["hbp"] == 2
    # Reference rows ride along, as for every other report-only row.
    kx.attach_reference(report, kx.load_reference())
    assert report["reference"]["foul_per_two_strike_pitch"]["value"] == 0.2432
    assert report["deltas"]["zone_swing_rate_0_0"] == pytest.approx(1 / 3 - 0.4445)


def test_pitchless_entries_are_not_pitches():
    log = [
        {"outcome": "ibb", "batter_id": "B", "pitcher_id": "P", "pa_result": "ibb",
         **_state()},
        {"outcome": "bunt", "batter_id": "B", "pitcher_id": "P", "pa_result": "sh",
         **_state()},
    ]
    acc = _acc()
    acc.add_game(_game(log), away="A", home="H")
    m = _finalize(acc)["metrics"]
    assert m["foul_share_of_contact"] is None
    assert m["zone_swing_rate_0_0"] is None
    assert m["looking_k_per_pa"] == 0.0


# --- rating response -------------------------------------------------------------


def test_rate_slope_is_in_points_per_ten_rating_points():
    # BB% = 8% + 0.2 points per rating point: +2.0 per 10.
    rows = [(x, round(1000 * (0.08 + 0.002 * (x - 50))), 1000) for x in range(40, 61, 2)]
    assert kx._rate_slope_pp_per10(rows) == pytest.approx(2.0, abs=1e-9)
    # Weighted by trials: a 10-PA player at 50% moves it little (unweighted,
    # the same point would take the slope to about +9).
    noisy = rows + [(60.0, 5, 10)]
    assert kx._rate_slope_pp_per10(noisy) == pytest.approx(2.0, abs=0.15)
    assert kx._rate_slope_pp_per10(rows[:9]) is None  # fewer than 10 players
    assert kx._rate_slope_pp_per10([(50.0, 80, 1000)] * 12) is None  # no spread


def _ratings_file(tmp_path: Path) -> Path:
    path = tmp_path / "players.csv"
    rows = ["player_id,bats,throws,primary_position,is_pitcher,ch,eye,control"]
    for i in range(12):
        rating = 40 + 2 * i
        # Hitter: Eye = rating, Contact = 100 - rating. H11 has a blank Eye,
        # which reads as his Contact.
        eye = "" if i == 11 else str(rating)
        rows.append(f"H{i},R,R,CF,0,{100 - rating},{eye},")
        rows.append(f"P{i},R,R,SP,1,,,{rating}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_walk_and_strikeout_slopes_on_the_ratings(tmp_path):
    acc = _acc(_ratings_file(tmp_path), games_per_team=162)
    assert acc.eye["H0"] == 40.0 and acc.ch["H0"] == 60.0
    assert acc.eye["H11"] == acc.ch["H11"] == 38.0
    assert "P0" not in acc.ch
    for i in range(11):
        rating = 40 + 2 * i
        # 1000 PA each. Walks rise 0.25 points per Eye point; strikeouts
        # fall 0.5 per Contact point (Contact = 100 - rating).
        acc.batters[f"H{i}"].update(
            pa=1010, ibb=6, sh=4, bb=round(1000 * (0.08 + 0.0025 * (rating - 50))) + 6,
            so=round(1000 * (0.22 + 0.005 * (rating - 50))),
        )
        # Walks fall 0.1 points per Control point.
        acc.pitchers[f"P{i}"].update(
            bf=1005, ibb=5, bb=round(1000 * (0.08 - 0.001 * (rating - 50))) + 5,
        )
    # Below the regular bar (400 PA): left out.
    acc.batters["H11"].update(pa=120, bb=60, so=0)
    report = acc.finalize({})
    m = report["metrics"]
    assert m["bb_pct_per10_eye"] == pytest.approx(2.5, abs=0.02)
    assert m["k_pct_per10_contact"] == pytest.approx(-5.0, abs=0.02)
    assert m["bb_pct_per10_control"] == pytest.approx(-1.0, abs=0.02)
    assert report["tables"]["rating_slope_players"] == {
        "min_pa": 400, "bb_pct_per10_eye": 11, "bb_pct_per10_control": 11,
        "k_pct_per10_contact": 11,
    }


def test_babip_slope_and_correlation_on_contact(tmp_path):
    acc = _acc(_ratings_file(tmp_path))
    for i in range(11):
        contact = 100 - (40 + 2 * i)
        hits = round(400 * (0.300 + 0.001 * (contact - 50)))
        acc.speed_bat[f"H{i}"].update(pa=600, bip=400, h=hits)
    m = acc.finalize({})["metrics"]
    # +.001 BABIP per Contact point: +.010 per 10.
    assert m["babip_contact_slope_per10"] == pytest.approx(0.010, abs=0.0005)
    assert m["r_ch_babip"] == pytest.approx(1.0, abs=0.01)
    # The helper is babip_speed_slope_per10's rule: 50+ balls in play.
    thin = [(50.0 + i, Counter(bip=49, h=20)) for i in range(5)]
    assert kx._babip_slope_per10(thin) is None


def test_o_swing_z_swing_correlation_and_zone_rate_spread(tmp_path):
    acc = _acc(_ratings_file(tmp_path))
    r5 = acc._r5()
    for i in range(11):
        acc.batters[f"H{i}"].update(pa=500)
        # Free swingers chase more AND swing more in the zone.
        r5.batter_pitches[f"H{i}"].update(
            zone=1000, zone_swing=600 + 10 * i, chase=1000, chase_swing=200 + 20 * i
        )
        # Zone rates from 40% to 60%: a real spread, far above binomial noise.
        r5.pitcher_pitches[f"P{i}"].update(pitches=2000, zone=800 + 40 * i)
    # A part-timer and a short-outing arm are left out.
    r5.batter_pitches["H11"].update(zone=10, zone_swing=0, chase=10, chase_swing=10)
    r5.pitcher_pitches["P11"].update(pitches=40, zone=40)
    report = acc.finalize({})
    m = report["metrics"]
    assert m["hitter_o_z_swing_corr"] == pytest.approx(1.0)
    assert m["pitcher_zone_pct_true_sd"] == pytest.approx(0.0655, abs=0.002)
    disp = report["tables"]["dispersion"]["pitcher_zone_pct"]
    assert disp["n"] == 11 and disp["min_pitches"] == 1500
    # The existing dispersion rows are still there.
    assert "hitter_bb_pct" in report["tables"]["dispersion"]


def test_hitter_avg_true_sd_from_the_batting_lines():
    acc = _acc(games_per_team=162)
    lines = []
    for i in range(12):
        lines.append({"player_id": f"H{i}", "pa": 550, "ab": 500, "h": 100 + 10 * i})
    lines.append({"player_id": "BENCH", "pa": 30, "ab": 30, "h": 30})
    acc.add_game(_game([], batting_lines={"away": lines, "home": []}), away="A", home="H")
    report = acc.finalize({})
    row = report["tables"]["dispersion"]["hitter_avg"]
    assert row["n"] == 12 and row["min_pa"] == 400
    # AVG .200 to .420 in steps of .020: sample sd .0721, less binomial noise.
    assert report["metrics"]["hitter_avg_true_sd"] == pytest.approx(0.0693, abs=0.001)
    assert report["metrics"]["hitter_avg_true_sd"] == row["true_sd"]


# --- platoon -----------------------------------------------------------------------


def test_platoon_gaps_switch_hitters_and_the_right_handed_share():
    acc = _acc()
    # Same hand (LL + RR): 100 PA, 30 K, 5 BB (95 AB), hr 5, 2b 5.
    acc.platoon["LL"].update(so=10, bb=2, hr=1, **{"2b": 2, "1b": 5}, out=20)
    acc.platoon["RR"].update(so=20, bb=3, hr=4, **{"2b": 3, "1b": 10}, out=20)
    # Opposite hand (LR + RL): 100 PA, 20 K, 10 BB, hr 9, 3b 1, 2b 5.
    acc.platoon["LR"].update(so=12, bb=6, hr=5, **{"3b": 1, "2b": 2, "1b": 10}, out=24)
    acc.platoon["RL"].update(so=8, bb=4, hr=4, **{"2b": 3, "1b": 8}, out=13, ibb=3, sh=2)
    # Switch hitters: all singles vs LHP, all outs vs RHP.
    acc.platoon["SL"].update(**{"1b": 10})
    acc.platoon["SR"].update(out=10)
    report = acc.finalize({})
    m = report["metrics"]
    rates = report["tables"]["platoon_rates"]
    same, opp = rates["same"], rates["opposite"]
    assert (same["pa"], opp["pa"]) == (100, 100)  # ibb and sh are not PA here
    assert m["platoon_gap_k_pct"] == pytest.approx(0.20 - 0.30)
    assert m["platoon_gap_bb_pct"] == pytest.approx(0.10 - 0.05)
    # ISO: same (5 + 3*5) / 95 AB; opposite (5 + 2*1 + 3*9) / 90 AB.
    assert m["platoon_gap_iso"] == pytest.approx(34 / 90 - 20 / 95)
    assert m["switch_woba_vs_lhp"] == pytest.approx(0.88)
    assert m["switch_woba_vs_rhp"] == pytest.approx(0.0)
    # PA against LHP: LL 40, RL 45 (with the ibb and sh), SL 10.
    assert m["rhb_share_of_pa_vs_lhp"] == pytest.approx(45 / 95)
    # Reading the buckets created none (finalize twice gives the same rows).
    assert acc.finalize({})["metrics"]["platoon_gap_k_pct"] == m["platoon_gap_k_pct"]


def test_hit_batters_by_matchup_hand_per_batter_faced():
    acc = _acc()
    assert acc.finalize({})["metrics"]["hbp_same_over_opposite_hand"] is None
    # Same hand (LL + RR): 12 hit batters in 800 batters faced.
    acc.platoon["LL"].update(hbp=4, out=250, bb=46)
    acc.platoon["RR"].update(hbp=8, out=400, so=92)
    # Opposite hand: 6 in 800, with a switch hitter (who always bats from
    # the opposite side) and the pitchless PA (ibb, sh) counted as faced.
    acc.platoon["LR"].update(hbp=2, out=298)
    acc.platoon["RL"].update(hbp=3, out=280, ibb=10, sh=7)
    acc.platoon["SL"].update(hbp=1, out=99)
    acc.platoon["SR"].update(out=100)
    report = _finalize(acc)
    table = report["tables"]["hbp_by_matchup_hand"]
    assert table["same"] == {"bf": 800, "hbp": 12, "hbp_per_bf": 12 / 800}
    assert table["opposite"] == {"bf": 800, "hbp": 6, "hbp_per_bf": 6 / 800}
    assert report["metrics"]["hbp_same_over_opposite_hand"] == pytest.approx(2.0)
    # Report-only, with the review's target beside it.
    kx.attach_reference(report, kx.load_reference())
    assert report["reference"]["hbp_same_over_opposite_hand"]["value"] == 2.0
    assert report["reference"]["hbp_same_over_opposite_hand"]["approximate"] is True
    assert report["deltas"]["hbp_same_over_opposite_hand"] == pytest.approx(0.0)
    # No hit batter on one side of the ratio: not a number.
    lonely = _acc()
    lonely.platoon["RR"].update(hbp=3, out=97)
    lonely.platoon["LR"].update(out=100)
    assert lonely.finalize({})["metrics"]["hbp_same_over_opposite_hand"] is None


# --- situations --------------------------------------------------------------------


def _situation_game():
    log = []
    # Overall, top halves: 8 PA with 2 walks, bottom halves: 4 PA.
    # Bases empty: 4 PA, 2 walks. Runner on first only: 4 PA, 1 walk.
    for _ in range(2):
        log += _pa("bb", _pitch("3-0", zone=False), state=_state(1, "top", 0, 0))
        log += _pa("out", state=_state(1, "top", 1, 0))
    log += _pa("bb", _pitch("3-0", zone=False), state=_state(2, "top", 0, 1))
    for _ in range(3):
        log += _pa("out", state=_state(2, "top", 1, 1))
    # Late and close (8th, tied), bottom half: 4 PA, 1 walk, and the game's
    # two intentional walks split late / early.
    log += _pa("bb", _pitch("3-1", zone=False), state=_state(8, "bottom", 0, 2, 3, 3))
    log += _pa("1b", state=_state(8, "bottom", 0, 3, 3, 3))
    log += _pa("hr", state=_state(8, "bottom", 0, 3, 3, 3))
    log += _pa("out", state=_state(8, "bottom", 0, 0, 7, 3))  # no longer close
    log.append({"outcome": "ibb", "batter_id": "B", "pitcher_id": "P",
                "pa_result": "ibb", **_state(8, "bottom", 1, 2, 3, 3)})
    log.append({"outcome": "ibb", "batter_id": "B", "pitcher_id": "P",
                "pa_result": "ibb", **_state(3, "top", 1, 2, 0, 0)})
    return _game(
        log, meta={"inning_runs": {"away": [0] * 8, "home": [0] * 7 + [4]}, "innings": 8}
    )


def test_situational_walks_and_the_home_side():
    acc = _acc()
    acc.add_game(_situation_game(), away="A", home="H")
    report = _finalize(acc)
    m = report["metrics"]
    # Unintentional walks per PA (ibb left out): overall 4 / 12; late and
    # close 1 / 3 (the fourth 8th-inning PA came with a four-run lead).
    assert m["late_close_ubb_pct_delta"] == pytest.approx(1 / 3 - 4 / 12)
    # Bases empty 2 / 5 (the late blowout out included); first only 1 / 4.
    assert m["bb_pct_empty_minus_r1"] == pytest.approx(2 / 5 - 1 / 4)
    assert m["ibb_late_close_share"] == pytest.approx(1 / 2)
    # Home: bb, 1b, hr, out (ibb left out of wOBA). Away: 3 bb, 5 outs.
    home = (0.69 + 0.88 + 2.05) / 4
    away = (3 * 0.69) / 8
    assert m["home_minus_away_woba"] == pytest.approx(home - away)
    counts = report["tables"]["r5_counts"]
    assert (counts["home_pa"], counts["away_pa"]) == (5, 9)
    assert counts["r1_only_pa"] == 4


def test_base_out_rows_are_none_without_the_logging():
    log = [
        _pitch("0-0", swing=True, outcome="in_play", pa_result="out"),
        _pitch("0-0", swing=True, outcome="in_play", pa_result="1b"),
    ]
    acc = _acc()
    acc.add_game(_game(log), away="A", home="H")
    m = _finalize(acc)["metrics"]
    for key in (
        "late_close_ubb_pct_delta", "bb_pct_empty_minus_r1", "ibb_late_close_share",
        "home_minus_away_woba",
    ):
        assert m[key] is None, key


def _usage_game(pass3_pa: int):
    """One starter (S) through the order and two relievers (R1, R2)."""
    log = []
    # Starter: pass 1 all outs, pass 2 all singles, pass 3 all home runs.
    for tto, token, n in ((1, "out", 9), (2, "1b", 9), (3, "hr", pass3_pa)):
        for _ in range(n):
            log += _pa(token, _pitch(swing=True, outcome="in_play", pitcher="S", tto=tto))
    # A fourth trip counts as pass 3.
    log += _pa("hr", _pitch(swing=True, outcome="in_play", pitcher="S", tto=4))
    # R1 faces eight: singles to the first six, then two home runs.
    for i in range(8):
        token = "1b" if i < 6 else "hr"
        log += _pa(token, _pitch(swing=True, outcome="in_play", pitcher="R1", tto=1))
    # R2 faces two: walks. A separate outing, so both are "fresh".
    for _ in range(2):
        log += _pa("bb", _pitch("3-0", zone=False, pitcher="R2", tto=1))
    lines = {
        "away": [
            {"player_id": "S", "gs": 1, "sv": 0, "svo": 0},
            {"player_id": "R1", "gs": 0, "sv": 0, "svo": 1},
            {"player_id": "R2", "gs": 0, "sv": 1, "svo": 1},
        ],
        "home": [{"player_id": "X", "gs": 1, "sv": 1, "svo": 1}],
    }
    return _game(log, pitcher_lines=lines)


def test_fresh_reliever_starter_passes_and_saves():
    acc = _acc()
    acc.add_game(_usage_game(pass3_pa=499), away="A", home="H")
    report = _finalize(acc)
    m = report["metrics"]
    counts = report["tables"]["r5_counts"]
    assert counts["starter_pa_by_pass"] == {"1": 9, "2": 9, "3": 500}
    # Fresh relief PA: R1's first six (singles) and R2's two (walks).
    assert counts["relief_fresh_pa"] == 8
    fresh = (6 * 0.88 + 2 * 0.69) / 8
    assert m["relief_bf1_6_minus_starter_pass1_woba"] == pytest.approx(fresh - 0.0)
    # Starters only: pass 3 (all home runs, OPS 5.0) minus pass 1 (0.0).
    assert m["tto_ops_gap_starters"] == pytest.approx(5.0)
    assert m["save_conversion"] == pytest.approx(2 / 3)
    assert counts["saves"] == {"sv": 2, "svo": 3}


def test_starter_tto_gap_needs_500_pass_three_pa():
    acc = _acc()
    acc.add_game(_usage_game(pass3_pa=498), away="A", home="H")
    m = _finalize(acc)["metrics"]
    assert m["tto_ops_gap_starters"] is None
    assert m["relief_bf1_6_minus_starter_pass1_woba"] is not None


# --- matchup grid ------------------------------------------------------------------


def test_k_split_grid_pools_the_pitcher_levels():
    levels = [35.0, 50.0]
    cells = {
        (35.0, 35.0): Counter(pa=100, k=40, k_looking=4, k_swinging=36),
        (35.0, 50.0): Counter(pa=100, k=60, k_looking=6, k_swinging=54),
        (50.0, 35.0): Counter(pa=100, k=20, k_looking=8, k_swinging=12),
        (50.0, 50.0): Counter(pa=100, k=0),
    }
    out = kx._k_split_grid(cells, levels)
    assert out["metrics"]["matchup_looking_k_share_ch35"] == pytest.approx(10 / 100)
    assert out["metrics"]["matchup_looking_k_per_pa_ch35"] == pytest.approx(10 / 200)
    assert out["metrics"]["matchup_looking_k_share_ch50"] == pytest.approx(8 / 20)
    first, last = out["cells"][0], out["cells"][-1]
    assert first == {
        "batter": 35.0, "pitcher": 35.0, "k_swinging_per_pa": 0.36,
        "k_looking_per_pa": 0.04, "looking_share": 0.1,
    }
    assert last["looking_share"] is None and last["k_looking_per_pa"] == 0.0


def test_platoon_hr_grid_is_opposite_over_same(monkeypatch):
    monkeypatch.setattr(kx, "PLATOON_GRID_POWER", (50.0, 80.0))
    cells = {
        ("L", 50.0, "L"): Counter(pa=1000, hr=20),
        ("L", 50.0, "R"): Counter(pa=1000, hr=30),
        ("R", 50.0, "R"): Counter(pa=1000, hr=25),
        ("R", 50.0, "L"): Counter(pa=1000, hr=20),
        # Thin cells: no ratio.
        ("L", 80.0, "L"): Counter(pa=1000, hr=19),
        ("L", 80.0, "R"): Counter(pa=1000, hr=60),
        ("R", 80.0, "R"): Counter(pa=1000, hr=0),
        ("R", 80.0, "L"): Counter(pa=1000, hr=0),
    }
    out = kx._platoon_hr_grid(cells)
    assert out["metrics"] == {
        "matchup_platoon_hr_ratio_lhb_ph50": pytest.approx(1.5),
        "matchup_platoon_hr_ratio_lhb_ph80": None,
        "matchup_platoon_hr_ratio_rhb_ph50": pytest.approx(0.8),
        "matchup_platoon_hr_ratio_rhb_ph80": None,
    }
    assert out["cells"][0]["hr_per_pa_opposite"] == pytest.approx(0.03)
    # A zero denominator never divides, whatever the event floor.
    monkeypatch.setattr(kx, "GRID_MIN_EVENTS", 0)
    assert kx._platoon_hr_grid(cells)["metrics"][
        "matchup_platoon_hr_ratio_rhb_ph80"
    ] is None


def test_grid_run_adds_the_new_tables_and_leaves_the_old_ones_alone(monkeypatch):
    monkeypatch.setattr(kx, "GRID_MIN_EVENTS", 0)  # 60 PA cells are thin
    random.seed(321)
    before = random.getstate()
    out = kx.matchup_grid_metrics(pa_per_cell=60, players_path=CAL / "players.csv")
    assert random.getstate() == before
    for key in GRID_METRICS:
        assert key in out["metrics"], key
    split = out["tables"]["matchup_k_split_grid"]
    assert len(split["cells"]) == 16
    # Swinging + looking is the strikeout rate of the same cell.
    k_grid = out["tables"]["matchup_k_grid"]
    anchor = [c for c in split["cells"] if c["batter"] == 50.0 and c["pitcher"] == 50.0][0]
    observed = [
        c for c in k_grid["cells"] if c["batter"] == 50.0 and c["pitcher"] == 50.0
    ][0]["observed"]
    assert anchor["k_swinging_per_pa"] + anchor["k_looking_per_pa"] == pytest.approx(observed)
    platoon = out["tables"]["matchup_platoon_hr_grid"]
    assert platoon["power_levels"] == list(kx.PLATOON_GRID_POWER)
    assert len(platoon["cells"]) == 2 * len(kx.PLATOON_GRID_POWER)

    # The platoon cells come after the old ones and every cell reseeds: the
    # CH and PH grids are what they were without them.
    monkeypatch.setattr(kx, "PLATOON_GRID_POWER", ())
    plain = kx.matchup_grid_metrics(pa_per_cell=60, players_path=CAL / "players.csv")
    assert plain["tables"]["matchup_k_grid"] == k_grid
    assert plain["tables"]["matchup_hr_grid"] == out["tables"]["matchup_hr_grid"]
    assert plain["metrics"]["matchup_k_log5_max_abs_resid"] == (
        out["metrics"]["matchup_k_log5_max_abs_resid"]
    )


def test_a_grid_cell_is_the_same_with_the_default_hands():
    from physics_sim.config import load_tuning
    from physics_sim.park import load_park

    tuning, park = load_tuning(), load_park(None)
    kwargs = dict(contact=50.0, power=50.0, pitcher_level=50.0, n=80, seed=9,
                  tuning=tuning, park=park)
    state = random.getstate()
    try:
        plain = kx._simulate_cell(**kwargs)
        same = kx._simulate_cell(**kwargs, bats="R", throws="R")
        lefty = kx._simulate_cell(**kwargs, bats="L", throws="R")
    finally:
        random.setstate(state)
    assert plain == same
    assert plain["k"] == plain["k_looking"] + plain["k_swinging"]
    assert plain["pa"] == lefty["pa"] == 80
    assert lefty != plain  # the hand does reach the batter's context


# --- a real run ----------------------------------------------------------------------


def test_harness_run_fills_the_new_rows(monkeypatch):
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
    m = report["metrics"]
    for key in R5A_METRICS:
        assert key in m, key
    assert 0.15 < m["foul_per_two_strike_pitch"] < 0.5
    assert 0.3 < m["foul_share_of_contact"] < 0.7
    assert 0.02 < m["looking_k_per_pa"] < 0.12
    for count in COUNT_KEYS:
        zone, chase = m[f"zone_swing_rate_{count}"], m[f"chase_swing_rate_{count}"]
        assert 0.0 <= chase < zone <= 1.0, count
    assert 0.0 <= m["hbp_in_zone_share"] <= 1.0
    assert m["oz_take_called_strike_rate"] < m["iz_take_called_ball_rate"] < 0.5
    assert 0.2 < m["save_conversion"] <= 1.0
    assert m["lineup_hand_match_rate"] == 1.0
    assert abs(m["home_minus_away_woba"]) < 0.2
    assert abs(m["platoon_gap_k_pct"]) < 0.2
    # Called third strikes per PA, read from the log, agree with the engine's
    # own totals (the gated called-third-strike share times K%).
    gated = summary["metrics"]
    assert m["looking_k_per_pa"] == pytest.approx(
        gated["called_third_strike_share_of_so"] * gated["k_pct"], abs=1e-12
    )
    # None of it is in the gated block, and the strict TTO gate is the
    # league-wide one (pass 3 PA are too few here: it reports None).
    for key in R5A_METRICS:
        assert key not in summary["metrics"], key
    assert "tto_ops_gap" in summary["metrics"]
    text = kx.format_report(report)
    assert "foul_per_two_strike_pitch" in text and "lineup_hand_match_rate" in text
