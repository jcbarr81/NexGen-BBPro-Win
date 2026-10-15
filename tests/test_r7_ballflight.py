"""Release 6b, stages 2-6: the kernel, the play model, foul-outs, spray and
the pitcher's ground-ball identity.

Each is behind a switch registered off (``batted_ball_model``,
``fielding_play_model``, ``foul_out_model``, ``spray_model``,
``pitcher_gb_launch_scale``) and turned on only in generation 7's profile.
Off, nothing new is called or drawn (the pinned-digest tests and the
identity seasons hold every earlier generation to the last digit).
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
import scripts.physics_sim_season_kpis as kpis
from physics_sim import ballflight as bf
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from physics_sim.park import load_park
from utils import park_utils

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"
SWITCHES = (
    "batted_ball_model", "fielding_play_model", "foul_out_model", "spray_model",
    "carry_model", "pitcher_gb_launch_scale",
)
CENTRES = {"hitter_gf_center": 50.0, "hitter_pull_center": 50.0,
           "pitcher_gf_usage_center": 50.0}


@pytest.fixture(autouse=True)
def _pinned_parks(monkeypatch):
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(REPO / "data"))
    bf.clear_fence_cache()
    yield
    bf.clear_fence_cache()


def _kernel(tuning, *, barrel_error=0.0, timing_error=0.0, gf=50.0, pl=50.0,
            pitcher_gf=50.0, pitch_type="fb", seed=1):
    random.seed(seed)
    return physics._batted_ball_kernel(
        potential=90.0, timing_error=timing_error, barrel_error=barrel_error,
        vertical_loc=0.0, batter={"gb_tendency": gf, "pull_tendency": pl},
        pitcher={"gb_tendency": pitcher_gf}, pitch_type=pitch_type, tuning=tuning,
    )


def test_every_switch_is_registered_off():
    for key in SWITCHES:
        assert DEFAULT_TUNING[key] == 0.0, key
    assert DEFAULT_TUNING["pitcher_gb_air_share"] == 1.0
    assert set(DEFAULT_TUNING["pitch_type_usage_weight"].values()) == {1.0}
    assert set(DEFAULT_TUNING["pitch_type_launch_offset"].values()) == {0.0}
    # Generation 6 turns none of them on; generation 7 turns all of them on.
    six = engine_profile(6, development=True)
    seven = engine_profile(7, development=True)
    for key in SWITCHES:
        assert not six.get(key), key
        assert seven.get(key), key


def test_the_kernel_is_never_called_while_the_switch_is_off(monkeypatch):
    def boom(**_kwargs):
        raise AssertionError("kernel called")

    monkeypatch.setattr(physics, "_batted_ball_kernel", boom)
    game = engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", base_dir=CAL, players_path=PLAYERS,
        seed=3, tuning_overrides=kpis.with_rating_centers(
            engine_profile(6, development=True), PLAYERS, CAL
        ),
    )
    assert game.totals["pa"] > 50
    assert not any(e.get("ball_type") == "pu" for e in game.pitch_log)
    assert not any("foul_out" in e for e in game.pitch_log)


def test_one_offset_sets_both_launch_angle_and_exit_velocity():
    tuning = load_tuning({"batted_ball_model": 1.0, "bb6_weak_share": 0.0, **CENTRES})
    peak = _kernel(tuning, barrel_error=0.33 * 0.314)
    under = _kernel(tuning, barrel_error=0.9 * 0.314)
    topped = _kernel(tuning, barrel_error=-0.6 * 0.314)
    # Under the ball lifts it (a pop-up), over it tops it into the ground,
    # and either way it is hit softer than at the peak.
    assert under[1] > peak[1] > topped[1]
    assert topped[1] < 10.0 and under[1] > 25.0
    assert peak[0] > under[0] and peak[0] > topped[0]
    assert physics.classify_ball_type(under[1] + 30.0, tuning) == "pu"
    assert physics.classify_ball_type(12.0, tuning) == "ld"
    assert physics.classify_ball_type(12.0, load_tuning()) == "fb"  # old cutoffs
    # A fly-ball hitter (low gf) lifts the ball 0.40 degree a point.
    low_gf = _kernel(tuning, barrel_error=0.0, gf=40.0)
    assert low_gf[1] - _kernel(tuning, barrel_error=0.0)[1] == pytest.approx(4.0, abs=0.01)


def test_spray_widening_pulls_and_stays_fair():
    tuning = load_tuning({"batted_ball_model": 1.0, "spray_model": 1.0, **CENTRES})
    sprays = [_kernel(tuning, barrel_error=0.1, seed=s)[2] for s in range(400)]
    assert all(-45.0 <= s <= 45.0 for s in sprays)
    assert sum(sprays) / len(sprays) > 3.0  # pulled on average
    pullers = [_kernel(tuning, barrel_error=0.1, pl=70.0, seed=s)[2] for s in range(400)]
    assert sum(pullers) / 400 > sum(sprays) / 400 + 5.0


def test_the_pitchers_ground_ball_term_acts_most_at_the_grounder_boundary():
    on = load_tuning({
        "batted_ball_model": 1.0, "pitcher_gb_launch_scale": 0.2,
        "pitcher_gb_air_share": 0.3, **CENTRES,
    })
    off = load_tuning({"batted_ball_model": 1.0, **CENTRES})
    low = 0.0  # a ball near the grounder / liner line
    high = 1.0 * 0.314  # a fly ball
    base_low = _kernel(off, barrel_error=low)[1]
    base_high = _kernel(off, barrel_error=high)[1]
    sinkerballer_low = _kernel(on, barrel_error=low, pitcher_gf=60.0)[1]
    sinkerballer_high = _kernel(on, barrel_error=high, pitcher_gf=60.0)[1]
    assert base_low - sinkerballer_low == pytest.approx(2.0, abs=0.05)
    assert 0.55 < base_high - sinkerballer_high < 1.0  # 30% of the shift + ramp
    # A sinker's own offset.
    sinker = load_tuning({
        "batted_ball_model": 1.0, "pitch_type_launch_offset": {"si": -4.0}, **CENTRES,
    })
    assert _kernel(off, barrel_error=low)[1] - _kernel(
        sinker, barrel_error=low, pitch_type="si"
    )[1] == pytest.approx(4.0, abs=0.05)


def _ball(ev, la, spray, park="Generic Park", speed=50.0, **extra):
    tuning = load_tuning({"fielding_play_model": 1.0, "carry_model": 1.0, **extra})
    ball = bf.resolve_ball(ev, la, spray, park=load_park(park), tuning=tuning,
                           batter_speed=speed)
    if not ball.is_hr:
        bf.play(ball, tuning, batter_speed=speed)
    return ball


def test_the_play_model_reads_the_ball():
    routine_grounder = _ball(88.0, -2.0, -12.0)  # at the shortstop
    assert routine_grounder.route == "ground" and routine_grounder.fielder == "SS"
    assert routine_grounder.out0 > 0.85
    hole = _ball(100.0, 2.0, -22.0)  # between short and third, hard
    assert hole.out0 < routine_grounder.out0
    chopper_slow = _ball(55.0, -15.0, -5.0, speed=30.0)
    chopper_fast = _ball(55.0, -15.0, -5.0, speed=75.0)
    assert chopper_fast.out0 < chopper_slow.out0  # speed beats the throw
    assert chopper_fast.infield_hit > chopper_slow.infield_hit
    lazy_fly = _ball(88.0, 35.0, 0.0)
    assert lazy_fly.route == "air" and lazy_fly.fielder == "CF"
    assert lazy_fly.out0 > 0.95 and lazy_fly.out_type == "flyout"
    popup = _ball(70.0, 65.0, 5.0)
    assert popup.fielder not in bf.OUTFIELD_SPOTS and popup.infield_play
    liner = _ball(95.0, 14.0, -14.0)
    assert liner.route == "air"
    gapper = _ball(104.0, 22.0, -22.0)
    assert gapper.out0 < 0.3 and gapper.hit_type in ("double", "triple")
    assert _ball(108.0, 28.0, 40.0).is_hr


def test_a_ball_off_a_high_wall_stays_in():
    # The same ball to left field: over a 10 ft wall, off Fenway's 37 ft one.
    generic = _ball(98.0, 26.0, -44.0)
    fenway = _ball(98.0, 26.0, -44.0, park="Fenway Park")
    assert generic.distance > 330.0
    assert not fenway.is_hr and fenway.hit_type == "double"


def _pitches(monkeypatch, tuning, n=1500):
    """(outcome, draws) of ``n`` pitches, each from its own seed."""
    calls = {"n": 0}

    class Counted:
        """physics' ``random``, counting every draw it makes."""

        def __getattr__(self, name):
            real = getattr(random, name)
            if not callable(real):
                return real

            def counted(*args, **kwargs):
                calls["n"] += 1
                return real(*args, **kwargs)

            return counted

    monkeypatch.setattr(physics, "random", Counted())
    batter = {"contact": 70.0, "power": 50.0, "eye": 50.0, "gb_tendency": 50.0,
              "pull_tendency": 50.0, "bats": "R", "speed": 50.0}
    pitcher = {"repertoire": {"fb": 50.0}, "velocity": 92.0, "control": 50.0,
               "movement": 50.0, "hand": "R", "gb_tendency": 50.0}
    out = []
    for i in range(n):
        random.seed(i)
        before = calls["n"]
        res = physics.simulate_pitch(batter=batter, pitcher=pitcher, tuning=tuning,
                                     count=(0, 0), context={"foul_territory_scale": 1.0})
        out.append((res.outcome, getattr(res, "foul_out", None), calls["n"] - before))
    monkeypatch.undo()
    return out


def test_a_foul_out_is_one_draw_on_a_foul_and_only_when_on(monkeypatch):
    base = {**engine_profile(6, development=True), **CENTRES}
    off = _pitches(monkeypatch, load_tuning(base))
    never = _pitches(monkeypatch, load_tuning({
        **base, "foul_out_model": 1.0, "foul_out_rate": 0.0}))
    always = _pitches(monkeypatch, load_tuning({
        **base, "foul_out_model": 1.0, "foul_out_rate": 1.0}))
    fouls = 0
    for (o0, f0, d0), (o1, f1, d1), (o2, f2, d2) in zip(off, never, always):
        assert f0 is None and f1 is None
        if o0 == "foul":
            fouls += 1
            # One more draw on a foul, whether it is caught or not.
            assert (o1, d1) == ("foul", d0 + 1)
            assert o2 == "in_play" and f2 in ("C", "1B", "3B") and d2 == d0 + 1
        else:
            # Nothing else changes.
            assert (o1, d1) == (o0, d0) == (o2, d2)
    assert fouls > 100


def test_the_ball_flight_kpis_are_written_only_for_a_ball_flight_run():
    from scripts import kpi_extras

    assert not kpis.ball_flight_run(None)
    assert not kpis.ball_flight_run(engine_profile(6, development=True))
    assert kpis.ball_flight_run(engine_profile(7, development=True))
    assert kpis.ball_flight_run({"foul_out_model": 1})
    game = engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", base_dir=CAL, players_path=PLAYERS,
        seed=5, tuning_overrides=kpis.with_rating_centers(
            {**engine_profile(7, development=True), "fielding_chance_log": 1.0},
            PLAYERS, CAL,
        ),
    )
    for flag in (False, True):
        extras = kpi_extras.ReportOnlyKpis(
            players_path=PLAYERS, games_per_team=1, lineup_dir=CAL / "lineups",
            ball_flight=flag, team_parks={"CAL02": "New Yankee Stadium"},
        )
        extras.add_game(game, away="CAL01", home="CAL02")
        metrics = extras.finalize()["metrics"]
        present = set(kpi_extras.R7_METRIC_KEYS) & set(metrics)
        assert present == (set(kpi_extras.R7_METRIC_KEYS) if flag else set())
    assert metrics["hit_chance_below_05_share"] is not None


def test_a_game_on_generation_7_plays_and_credits_the_play_models_fielders():
    overrides = kpis.with_rating_centers(
        engine_profile(7, development=True), PLAYERS, CAL
    )
    overrides["fielding_chance_log"] = 1.0
    seen_pu = foul_outs = 0
    for seed in (1, 2, 3):
        game = engine.simulate_matchup_from_files(
            away_team="CAL27", home_team="CAL01", base_dir=CAL, players_path=PLAYERS,
            seed=seed, tuning_overrides=dict(overrides),
        )
        assert game.totals["pa"] > 50
        for entry in game.pitch_log:
            if entry.get("outcome") != "in_play":
                continue
            seen_pu += entry.get("ball_type") == "pu"
            foul_outs += bool(entry.get("foul_out"))
            if entry.get("foul_out"):
                assert entry["foul_out"] in ("C", "1B", "3B")
                assert entry.get("pa_result") == "out"
        for row in game.play_records.get("bip_chances") or []:
            assert len(row[3]) == 1 and 0.0 <= row[6] <= 1.0
    assert seen_pu > 0
