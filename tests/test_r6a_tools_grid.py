"""Release 6a (tooling): the matchup grid's composite pitcher axis, the
Power table and the engine's two play records.

Generation 6 weights the pitch grade at .55 of pitch quality, so a grid
whose pitcher axis moves only control and movement understates the pitcher.
``--matchup-grid-composite`` moves every pitch grade with them; the default
grid is, cell for cell, what it was. ``power_hr600_p<level>`` is home runs
per 600 PA by league-relative Power against the fixture's own staff. The
engine hands the harness two records beside the game
(``GameResult.play_records``: ``fld_pos`` and ``starting_positions``); they
draw nothing and are in neither the pitch log nor the metadata.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.kpi_extras as kx
import scripts.physics_sim_season_kpis as kpis
from physics_sim.engine import simulate_matchup_from_files
from physics_sim.engine_generation import engine_profile
from services import league_rating_centers as centers

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"
FIELD = {"P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"}


def _fake_cells(monkeypatch, rates=None):
    """Replace the Monte Carlo cell with a table lookup; returns the calls."""
    calls = []

    def fake(*, contact, power, pitcher_level, n, seed, tuning, park, bats="R",
             throws="R", pitch_grade=kx.GRID_PITCH_GRADE):
        calls.append({
            "contact": contact, "power": power, "pitcher_level": pitcher_level,
            "pitch_grade": pitch_grade, "bats": bats, "throws": throws,
        })
        k, hr = (rates or (lambda *_a: (250, 30)))(contact, power, pitcher_level)
        return Counter(pa=1000, k=k, k_looking=k // 5, k_swinging=k - k // 5, hr=hr, bb=80)

    monkeypatch.setattr(kx, "_simulate_cell", fake)
    return calls


# --- the composite axis --------------------------------------------------------


def test_the_default_grid_throws_the_average_grade_in_every_cell(monkeypatch):
    calls = _fake_cells(monkeypatch)
    out = kx.matchup_grid_metrics(pa_per_cell=1000, players_path=PLAYERS)
    assert out["tables"]["matchup_grid_pitcher_axis"] == "control_movement"
    assert {call["pitch_grade"] for call in calls} == {kx.GRID_PITCH_GRADE}
    assert {call["pitcher_level"] for call in calls} > {50.0}
    # 16 Contact cells, the fixture's 3 x 3 Power cells and 20 platoon cells.
    assert len(calls) == 16 + 9 + 20
    assert "matchup_hr_box_grid" not in out["tables"]
    assert "matchup_hr_log5_box_max_abs_resid_logit" not in out["metrics"]
    assert not [key for key in out["metrics"] if key.startswith("power_hr600")]


def test_the_composite_axis_moves_every_pitch_grade_with_the_level(monkeypatch):
    assert kx._grid_pitch_grade(50.0, True) == kx.GRID_PITCH_GRADE
    assert kx._grid_pitch_grade(80.0, True) == kx.GRID_PITCH_GRADE + 30.0
    assert kx._grid_pitch_grade(35.0, True) == kx.GRID_PITCH_GRADE - 15.0
    assert kx._grid_pitch_grade(80.0, False) == kx.GRID_PITCH_GRADE
    calls = _fake_cells(monkeypatch)
    out = kx.matchup_grid_metrics(
        pa_per_cell=1000, players_path=PLAYERS, composite_pitcher=True
    )
    assert out["tables"]["matchup_grid_pitcher_axis"] == "composite"
    for call in calls:
        assert call["pitch_grade"] == kx.GRID_PITCH_GRADE + call["pitcher_level"] - 50.0
    # The anchor pitcher is the same pitcher on both axes.
    anchor = [call for call in calls if call["pitcher_level"] == 50.0]
    assert anchor and {call["pitch_grade"] for call in anchor} == {kx.GRID_PITCH_GRADE}
    # The Power x pitcher box over 35-80: 12 more cells (its Power 50 row is
    # the Contact grid's Contact 50 row).
    assert len(calls) == 16 + 9 + 20 + 12
    box = [c for c in calls[-12:]]
    assert {c["power"] for c in box} == {35.0, 65.0, 80.0}
    assert {c["pitcher_level"] for c in box} == set(kx.HR_BOX_LEVELS)
    assert {c["contact"] for c in box} == {50.0}
    table = out["tables"]["matchup_hr_box_grid"]
    assert table["levels"] == list(kx.HR_BOX_LEVELS) and len(table["cells"]) == 16
    assert len(table["hr_per_pa"]) == 16
    assert out["metrics"]["matchup_hr_log5_box_thin_cells"] == 0
    # Every cell has the same rate here: log5 holds exactly.
    assert out["metrics"]["matchup_hr_log5_box_max_abs_resid_logit"] == pytest.approx(0.0)
    # The metric names are the same on both axes (the table says which).
    plain = kx.matchup_grid_metrics(pa_per_cell=1000, players_path=PLAYERS)
    assert set(plain["metrics"]) <= set(out["metrics"])


def test_the_grid_pitcher_really_throws_that_grade(monkeypatch):
    """``_simulate_cell`` builds its pitcher with the grade it is given."""
    import physics_sim.engine as engine

    seen = []
    real = engine._pitcher_context

    def spy(pitcher, tuning):
        seen.append(dict(pitcher.repertoire))
        return real(pitcher, tuning)

    monkeypatch.setattr(engine, "_pitcher_context", spy)
    from physics_sim.config import load_tuning
    from physics_sim.park import load_park

    state = random.getstate()
    try:
        for grade in (kx.GRID_PITCH_GRADE, 85.0):
            kx._simulate_cell(
                contact=50.0, power=50.0, pitcher_level=80.0, n=3, seed=1,
                tuning=load_tuning({}), park=load_park(None), pitch_grade=grade,
            )
    finally:
        random.setstate(state)
    assert seen[0] == {pitch: kx.GRID_PITCH_GRADE for pitch in ("fb", "sl", "cu", "cb")}
    assert seen[1] == {pitch: 85.0 for pitch in ("fb", "sl", "cu", "cb")}


def test_a_thin_home_run_cell_is_counted_not_trusted(monkeypatch):
    """A composite-80 pitcher allows too few home runs for log5 at a small
    cell size: the cells are left out of the maximum and counted."""

    def rates(contact, power, pitcher_level):
        return 250, (3 if pitcher_level == 80.0 else 40)

    _fake_cells(monkeypatch, rates)
    out = kx.matchup_grid_metrics(
        pa_per_cell=1000, players_path=PLAYERS, composite_pitcher=True
    )
    # The whole pitcher-80 column: its anchor cell is thin too.
    assert out["metrics"]["matchup_hr_log5_box_thin_cells"] == 4
    assert out["metrics"]["matchup_hr_log5_box_max_abs_resid_logit"] == pytest.approx(0.0)


def test_the_inner_k_residual_leaves_out_the_80_row_and_column(monkeypatch):
    def rates(contact, power, pitcher_level):
        # Log5 holds everywhere except the Contact 80 x pitcher 80 corner.
        return (400 if (contact, pitcher_level) == (80.0, 80.0) else 250), 30

    _fake_cells(monkeypatch, rates)
    out = kx.matchup_grid_metrics(pa_per_cell=1000, players_path=PLAYERS)
    assert out["metrics"]["matchup_k_log5_max_abs_resid"] == pytest.approx(0.15)
    assert out["metrics"]["matchup_k_log5_inner_max_abs_resid"] == pytest.approx(0.0)
    assert kx.K_GRID_INNER_MAX == 65.0


def test_the_grid_pins_the_new_centres_to_its_own_hitter_and_pitcher():
    for key in ("hitter_gf_center", "hitter_pull_center", "pitcher_gf_usage_center"):
        assert kx.GRID_RATING_CENTERS[key] == 50.0
    # No fielder plays in a grid cell.
    assert not [k for k in kx.GRID_RATING_CENTERS if k.startswith("fielder_")]


# --- the Power table ---------------------------------------------------------------


def _fixture_overrides(profile=None):
    return kpis.with_rating_centers(dict(profile or {}), PLAYERS, CAL)


def test_the_power_table_reads_the_league_average_hitter_at_each_level(monkeypatch):
    """Power is the level's distance from the fixture's Power centre; every
    other rating sits at the fixture's centre."""
    import physics_sim.engine as engine
    import physics_sim.physics as physics

    overrides = _fixture_overrides(engine_profile(5))
    seen = []

    def fake_context(batter, pitcher, tuning, *, tto=1, home=None):
        seen.append((batter, pitcher.player_id))
        return {}

    monkeypatch.setattr(engine, "_batter_context", fake_context)
    monkeypatch.setattr(engine, "_pitcher_context", lambda pitcher, tuning: {})
    monkeypatch.setattr(
        physics, "simulate_pitch", lambda **kwargs: SimpleNamespace(outcome="hbp")
    )
    state = random.getstate()
    try:
        out = kx.power_hr600_table(
            pa_per_cell=3000, fixture_dir=CAL, players_path=PLAYERS,
            tuning_overrides=overrides,
        )
    finally:
        random.setstate(state)
    levels = [float(level) for level in range(30, 85, 5)]
    assert list(kx.POWER_TABLE_LEVELS) == levels
    assert list(out["metrics"]) == [f"power_hr600_p{int(level)}" for level in levels]
    assert out["table"]["levels"] == levels and out["table"]["pa_per_cell"] == 3000
    assert len(seen) == 3000 * len(levels)

    first = seen[:3000]  # the Power 30 cell
    batter = first[0][0]
    assert batter.power == pytest.approx(30.0 - 50.0 + overrides["hitter_power_center"])
    assert batter.contact == overrides["hitter_contact_center"]
    assert batter.eye == overrides["hitter_eye_center"]
    assert batter.speed == overrides["hitter_speed_center"]
    assert batter.gb_tendency == overrides["hitter_gf_center"]
    assert batter.pull_tendency == overrides["hitter_pull_center"]
    assert {b.vs_left for b, _p in first if b.bats == "L"} == {
        overrides["hitter_vl_center_l"]
    }
    last = seen[-3000:]  # the Power 80 cell
    assert last[0][0].power == pytest.approx(80.0 - 50.0 + overrides["hitter_power_center"])

    # He bats left as often as the league does, a switch hitter half the time.
    left = overrides["hitter_bats_share_l"] + 0.5 * overrides["hitter_bats_share_s"]
    share = sum(1 for b, _p in first if b.bats == "L") / len(first)
    assert share == pytest.approx(left, abs=0.03)

    # The staff is the fixture's ACT pitchers, a rotation starter drawn 2.5
    # times as often as a reliever.
    loads = {
        row["player_id"]: weight
        for row, weight in centers.active_pitcher_workloads(CAL, players_path=PLAYERS)
    }
    assert out["table"]["pitchers"] == len(loads)
    faced = Counter(pid for _b, pid in seen)
    assert set(faced) <= set(loads)
    starters = sum(n for pid, n in faced.items() if loads[pid] == 2.5)
    relievers = sum(n for pid, n in faced.items() if loads[pid] == 1.0)
    n_sp = sum(1 for w in loads.values() if w == 2.5)
    n_rp = len(loads) - n_sp
    assert (starters / n_sp) / (relievers / n_rp) == pytest.approx(2.5, rel=0.05)
    # Common random numbers: every level meets the same pitchers in order.
    assert [pid for _b, pid in first] == [pid for _b, pid in last]


@pytest.mark.parametrize("profile", [None, 5])
def test_the_power_table_runs_on_the_real_kernel(profile):
    overrides = _fixture_overrides(engine_profile(profile) if profile else None)
    random.seed(99)
    before = random.getstate()
    out = kx.matchup_grid_metrics(
        pa_per_cell=120, players_path=PLAYERS, tuning_overrides=overrides,
        fixture_dir=CAL, fixture_overrides=overrides,
    )
    assert random.getstate() == before
    table = out["tables"]["power_hr600_table"]
    assert [cell["pa"] for cell in table["cells"]] == [120] * 11
    for level in range(30, 85, 5):
        value = out["metrics"][f"power_hr600_p{level}"]
        assert value is not None and 0.0 <= value < 300.0
    # More Power, more home runs, end to end (same pitchers, same seed).
    low = sum(cell["hr"] for cell in table["cells"][:3])
    high = sum(cell["hr"] for cell in table["cells"][-3:])
    assert high > low
    assert 0.1 < table["cells"][4]["k_per_pa"] < 0.4


def test_the_power_table_needs_a_staff(tmp_path):
    out = kx.power_hr600_table(
        pa_per_cell=50, fixture_dir=tmp_path, players_path=tmp_path / "players.csv"
    )
    assert set(out["metrics"].values()) == {None}
    assert len(out["metrics"]) == 11 and out["table"]["pitchers"] == 0


# --- the command line ---------------------------------------------------------------


@pytest.mark.parametrize("composite", [False, True])
def test_main_passes_the_grid_options(monkeypatch, tmp_path, composite):
    captured = {}

    def fake_grid(**kwargs):
        captured.update(kwargs)
        return {"metrics": {"power_hr600_p30": 9.0}, "tables": {}}

    monkeypatch.setattr(
        kpis, "run_sim",
        lambda *a, **k: {"metrics": {}, "report_only": {"metrics": {}, "tables": {}}},
    )
    monkeypatch.setattr(kpis.kpi_extras, "matchup_grid_metrics", fake_grid)
    monkeypatch.setattr(kpis.kpi_extras, "format_report", lambda r: "")
    out = tmp_path / "kpis.json"
    argv = [
        "kpis", "--engine", "5", "--base-dir", str(CAL), "--players", str(PLAYERS),
        "--matchup-grid-pa", "25", "--output", str(out),
    ]
    if composite:
        argv.append("--matchup-grid-composite")
    monkeypatch.setattr(kpis.sys, "argv", argv)
    kpis.main()
    assert captured["pa_per_cell"] == 25
    assert captured["composite_pitcher"] is composite
    assert Path(captured["fixture_dir"]) == CAL
    # The grid gets the run's overrides; the Power table the same overrides
    # with the fixture's centres, stored and unstored.
    assert captured["tuning_overrides"] == engine_profile(5)
    fixture = captured["fixture_overrides"]
    assert fixture["swing_model"] == 1.0
    assert fixture["hitter_power_center"] == pytest.approx(50.2, abs=0.05)
    assert set(centers.UNSTORED_CENTER_KEYS) <= set(fixture)
    report = json.loads(out.read_text(encoding="utf-8"))["report_only"]
    assert report["metrics"]["power_hr600_p30"] == 9.0
    assert "matchup_grid_error" not in report


# --- the engine's play records -------------------------------------------------------


@pytest.fixture(scope="module")
def played():
    """One calibration game on generation 5 with the fixture's centres."""
    overrides = kpis.with_rating_centers(engine_profile(5), PLAYERS, CAL)
    return simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=PLAYERS, base_dir=CAL,
        seed=11, tuning_overrides=overrides,
    )


def test_the_records_are_beside_the_game_not_in_it(played):
    """The pitch log and the metadata are what every pinned-game test
    hashes and what the live paths ship: the records are in neither."""
    from physics_sim.engine import GameResult

    assert set(played.play_records) == {"starting_positions", "fld_pos"}
    assert "starting_positions" not in played.metadata
    assert "play_records" not in played.metadata
    for entry in played.pitch_log:
        assert "fld_pos" not in entry
    # A result built without them (a test double, another engine) has none.
    assert GameResult(totals={}, pitch_log=[]).play_records == {}


def test_a_pinned_game_still_hashes_to_its_pinned_digest():
    """The digests pinned before this release cover the whole pitch log,
    the totals and the metadata of a game (tests/test_r5_discipline.py)."""
    from tests.test_r5_discipline import PINNED_DIGESTS, _digest, _play

    key = next(iter(PINNED_DIGESTS))
    result = _play(*key[:4])
    assert _digest(result) == PINNED_DIGESTS[key]
    assert result.play_records["fld_pos"]


def test_the_game_says_who_started_where(played):
    starting = played.play_records["starting_positions"]
    assert set(starting) == {"away", "home"}
    for side in ("away", "home"):
        positions = starting[side]
        assert len(positions) == 9
        assert sorted(positions.values()) == sorted(FIELD - {"P"} | {"DH"})
        assert all(isinstance(pos, str) for pos in positions.values())
        # Everyone it names batted.
        batted = {line["player_id"] for line in played.metadata["batting_lines"][side]}
        assert set(positions) <= batted


def test_every_out_and_error_in_play_names_the_fielder_s_position(played):
    fielded = played.play_records["fld_pos"]
    log = played.pitch_log
    assert all(isinstance(index, int) and 0 <= index < len(log) for index in fielded)
    balls = [i for i, e in enumerate(log) if e.get("outcome") == "in_play"]
    assert len(balls) > 30
    credited = 0
    for index in balls:
        entry = log[index]
        out_type = entry.get("out_type")
        if out_type is None:
            # A hit (or a home run): nobody is credited.
            assert index not in fielded, entry
            assert not entry.get("reached_on_error")
            continue
        credited += 1
        assert fielded[index] in FIELD - {"P", "C"}, entry
        if entry.get("ball_type") == "gb":
            assert fielded[index] in {"1B", "2B", "3B", "SS"}
        elif out_type == "flyout":
            assert fielded[index] in {"LF", "CF", "RF"}
    assert credited > 20
    # Only balls in play are in it.
    assert set(fielded) <= set(balls)


def test_the_records_are_what_the_engine_s_own_credit_says(played):
    """``fld_pos`` is the position the engine works out for the play today
    (``_fielder_position_for_ball``): the row follows the engine when the
    Release 6 band model changes who fields what."""
    import physics_sim.engine as engine
    from physics_sim.config import load_tuning

    tuning = load_tuning(kpis.with_rating_centers(engine_profile(5), PLAYERS, CAL))
    bats = {}
    throws = {}
    with PLAYERS.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            bats[row["player_id"]] = row["bats"]
            throws[row["player_id"]] = row["throws"]
    checked = 0
    for index, position in played.play_records["fld_pos"].items():
        entry = played.pitch_log[index]
        side = engine._effective_batter_side(
            bats[entry["batter_id"]], throws[entry["pitcher_id"]]
        )
        # A liner or a pop-up caught in the infield is an infield play.
        infield = entry["out_type"] == "groundout" or (
            position in {"1B", "2B", "3B", "SS"}
        )
        expected = engine._fielder_position_for_ball(
            ball_type=entry["ball_type"], spray_angle=entry["spray_angle"],
            batter_side=side, tuning=tuning, infield_play=infield,
        )
        assert position == expected, entry
        checked += 1
    assert checked > 20


def test_the_same_seed_plays_the_same_game_and_the_same_records():
    def play():
        return simulate_matchup_from_files(
            away_team="CAL03", home_team="CAL04", players_path=PLAYERS,
            base_dir=CAL, seed=5,
        )

    first, second = play(), play()
    assert first.totals == second.totals
    assert first.pitch_log == second.pitch_log
    assert first.metadata == second.metadata
    assert first.play_records == second.play_records
