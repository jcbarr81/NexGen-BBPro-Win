"""Release 4 W3: outs in play (audit M6 DP half, M7, M8).

- Tag-ups (``tag_up_model`` 1): an infield liner or a short pop-up freezes
  the runners with no draw; the runner on 3rd races the throw and holds,
  scores or is thrown out; a throw-out is a ``tag_dp`` (fly out + tag), never
  a GIDP; the runner on 2nd only rolls on a ball deep enough to send him.
- Ground outs (``ground_out_model`` 1): triple play, then DP, then R3. A
  0-out DP scores R3, a 1-out DP does not (L15); a 0-out bases-loaded DP
  that does not score R3 is a home-to-first DP; with the bases loaded R3 is
  forced home unless the infield plays in; forced runners always move up;
  an unforced R2 takes 3rd on a productive out.
- DP: ``double_play_probability(..., batter_speed=)`` with the multiplicative
  batter-speed factor and the ``double_play_max`` cap.
- With both switches at 0 every game is byte-identical to the 7.47.0 code
  (frozen copies of the legacy functions below), and pinned per-seed digests
  catch a change at the call sites the frozen copies cannot see.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import BaseState, _advance_on_air_out, _resolve_ground_out
from physics_sim.fielding import compute_defense_ratings, double_play_probability
from physics_sim.models import BatterRatings

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
PROFILE = REPO / "scripts" / "kpi_profiles" / "r4b.json"

W3_KNOBS = {
    "tag_up_model": 1.0,
    "ground_out_model": 1.0,
    "tag_up_run_base": 3.6,
    "tag_up_run_speed": 0.011,
    "tag_up_throw_velo": 105.0,
    "tag_up_throw_arm": 0.9,
    "tag_up_release": 2.1,
    "tag_up_carry_k": 1.1,
    "tag_up_hang_k": 0.2,
    "tag_up_hang_ref": 2.5,
    "tag_up_send_margin": 0.25,
    "tag_up_send_margin_0out": 0.05,
    "tag_up_send_sd": 0.3,
    "tag_up_out_sd": 0.35,
    "tag_up_out_floor": 0.01,
    "tag_up_second_scale": 1.4,
    "tag_up_min_carry_ft": 140.0,
    "tag_up_second_min_send": 0.08,
    "ground_out_dp_r3_score": 0.85,
    "ground_out_dp_r3_speed": 0.003,
    "ground_out_r3_score_0out": 0.4,
    "ground_out_r3_score_1out": 0.5,
    "ground_out_r3_infield_in_adj": -0.2,
    "ground_out_r3_speed": 0.005,
    "ground_out_home_play_in": 0.6,
    "ground_out_home_play_back": 0.1,
    "productive_out_right": 0.7,
    "productive_out_left": 0.3,
    "productive_out_speed": 0.005,
    "infield_in_min_inning": 8.0,
    "infield_in_max_lead": 1.0,
    "double_play_batter_speed_k": 0.25,
    "double_play_max": 0.55,
}

V1 = {"tag_up_model": 1.0, "ground_out_model": 1.0}


def _batter(pid: str, pos: str = "CF", speed: float = 50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position=pos, other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=speed, eye=50.0,
        height=72.0, durability=50.0,
    )


def _defense():
    return {
        pos: _batter(f"F{pos}", pos)
        for pos in ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
    }


class _Script:
    """Stands in for the ``random`` module: draws come from a fixed list."""

    def __init__(self, draws):
        self._draws = list(draws)

    def random(self):
        assert self._draws, "the play drew more numbers than scripted"
        return self._draws.pop(0)


# --- knobs ---------------------------------------------------------------------


def test_w3_knobs_are_registered_and_round_trip():
    for key in W3_KNOBS:
        assert key in DEFAULT_TUNING, key
    tuning = TuningConfig.from_overrides(overrides=W3_KNOBS)
    for key, value in W3_KNOBS.items():
        assert tuning.get(key) == pytest.approx(value), key


def test_defaults_are_the_legacy_path():
    assert DEFAULT_TUNING["tag_up_model"] == 0.0
    assert DEFAULT_TUNING["ground_out_model"] == 0.0
    assert DEFAULT_TUNING["double_play_base"] == pytest.approx(0.32)
    assert DEFAULT_TUNING["double_play_batter_speed_k"] == 0.0
    assert DEFAULT_TUNING["double_play_max"] == pytest.approx(0.45)


def test_r4b_profile_carries_the_w3_values():
    from scripts.physics_sim_season_kpis import load_tuning_overrides_file

    profile = load_tuning_overrides_file(PROFILE)
    assert profile["tag_up_model"] == 1.0
    assert profile["ground_out_model"] == 1.0
    assert profile["double_play_base"] == pytest.approx(0.38)
    assert profile["double_play_batter_speed_k"] == pytest.approx(0.20)
    assert profile["double_play_max"] == pytest.approx(0.60)
    assert profile["tag_up_second_scale"] == pytest.approx(1.6)
    # F2 retune on the full bundle (W0-W3): a slightly bolder send and a
    # higher out floor put tag-up score / out per send in .72-.78 / .02-.04.
    assert profile["tag_up_send_margin"] == pytest.approx(0.17)
    assert profile["tag_up_out_floor"] == pytest.approx(0.008)
    assert profile["tag_up_min_carry_ft"] == pytest.approx(150.0)
    assert profile["tag_up_second_min_send"] == pytest.approx(0.05)


# --- double play probability ---------------------------------------------------


def _old_dp(*, runner_speed, infield_range, turn_arm, tuning):
    base = tuning.get("double_play_base", 0.14)
    range_adj = (infield_range - 50.0) / 230.0
    range_adj *= tuning.get("double_play_range_scale", 1.0)
    arm_adj = (turn_arm - 50.0) / 260.0
    arm_adj *= tuning.get("double_play_arm_scale", 1.0)
    speed_adj = (runner_speed - 50.0) / 220.0
    speed_adj *= tuning.get("double_play_speed_scale", 1.0)
    return max(0.03, min(0.45, base + range_adj + arm_adj - speed_adj))


@pytest.mark.parametrize("batter_speed", [None, 20.0, 50.0, 90.0])
def test_dp_default_tuning_reproduces_the_old_value(batter_speed):
    tuning = load_tuning()
    rng = random.Random(7)
    for _ in range(200):
        kw = dict(
            runner_speed=rng.uniform(20, 90),
            infield_range=rng.uniform(20, 90),
            turn_arm=rng.uniform(20, 90),
            tuning=tuning,
        )
        assert double_play_probability(**kw, batter_speed=batter_speed) == _old_dp(**kw)


def test_dp_batter_speed_factor_is_multiplicative_and_centred():
    tuning = load_tuning(
        {"double_play_batter_speed_k": 0.2, "hitter_speed_center": 55.0,
         "double_play_max": 0.9}
    )
    kw = dict(runner_speed=50.0, infield_range=50.0, turn_arm=50.0, tuning=tuning)
    raw = double_play_probability(**kw)
    assert double_play_probability(**kw, batter_speed=55.0) == pytest.approx(raw)
    assert double_play_probability(**kw, batter_speed=75.0) == pytest.approx(
        raw * math.exp(-0.4)
    )
    assert double_play_probability(**kw, batter_speed=35.0) == pytest.approx(
        raw * math.exp(0.4)
    )


def test_dp_cap_is_a_knob():
    kw = dict(runner_speed=20.0, infield_range=90.0, turn_arm=90.0)
    assert double_play_probability(**kw, tuning=load_tuning()) == pytest.approx(0.45)
    assert double_play_probability(
        **kw, tuning=load_tuning({"double_play_max": 0.6})
    ) == pytest.approx(0.6)


# --- tag-ups -------------------------------------------------------------------


def _air_out(monkeypatch, bases, outs, draws, *, overrides=None, arm=50.0, **ball):
    script = _Script(draws)
    monkeypatch.setattr(engine, "random", script)
    tuning = load_tuning({**V1, **(overrides or {})})
    ball.setdefault("distance", 250.0)
    ball.setdefault("exit_velo", 95.0)
    ball.setdefault("launch_angle", 30.0)
    ball.setdefault("ball_type", "fb")
    result = _advance_on_air_out(
        bases=bases, outs=outs, thrower_arm=arm, tuning=tuning, **ball
    )
    return result, script


def test_infield_liner_freezes_the_runners_without_a_draw(monkeypatch):
    r2, r3 = _batter("R2"), _batter("R3")
    bases = BaseState(second=r2, third=r3)
    (runs, extra, sf, scored, out_runner), script = _air_out(
        monkeypatch, bases, 0, [], distance=110.0, ball_type="ld",
        launch_angle=10.0, infield_play=True,
    )
    assert (runs, extra, sf, scored, out_runner) == (0, 0, False, [], None)
    assert bases.third is r3 and bases.second is r2


def test_legacy_model_ignores_the_infield_flag(monkeypatch):
    bases = BaseState(third=_batter("R3"))
    monkeypatch.setattr(engine, "random", _Script([0.0]))
    runs, *_ = _advance_on_air_out(
        bases=bases, outs=0, thrower_arm=50.0, tuning=load_tuning(),
        distance=110.0, exit_velo=80.0, launch_angle=10.0, ball_type="ld",
        infield_play=True,
    )
    assert runs == 1  # 7.47.0: one combined roll, the liner scores


@pytest.mark.parametrize(
    "draws, result",
    [([0.999], "hold"), ([0.0, 0.999], "score"), ([0.0, 0.0], "out")],
)
def test_tag_up_hold_score_out(monkeypatch, draws, result):
    r3 = _batter("R3")
    bases = BaseState(third=r3)
    (runs, extra, sf, scored, out_runner), script = _air_out(
        monkeypatch, bases, 1, draws, distance=175.0
    )
    assert script._draws == []
    if result == "hold":
        assert (runs, extra, sf) == (0, 0, False) and bases.third is r3
    elif result == "score":
        assert (runs, extra, sf, scored) == (1, 0, True, [r3]) and bases.third is None
    else:
        assert (runs, extra, sf, out_runner) == (0, 1, False, r3) and bases.third is None


def _p_send(distance, *, speed=50.0, arm=50.0, outs=1, ev=95.0, la=30.0):
    p_send, p_out, _ = engine._tag_up_race(
        speed=speed, arm=arm, distance=distance, exit_velo=ev,
        launch_angle=la, outs=outs, tuning=load_tuning(V1),
    )
    return p_send, p_out


def test_send_rate_rises_with_depth():
    sends = [_p_send(d)[0] for d in (120, 150, 175, 200, 225, 300)]
    assert sends == sorted(sends)
    assert sends[0] <= 0.15
    p_send, p_out = _p_send(300.0)
    assert p_send * (1.0 - p_out) >= 0.99


def test_speed_and_arm_move_the_send_at_175_feet():
    base = _p_send(175.0)[0]
    assert 0.6 <= base <= 0.85  # the plan's .74 at sp 50, arm 50
    assert _p_send(175.0, speed=85.0)[0] - base >= 0.20
    assert _p_send(175.0, arm=65.0)[0] <= base - 0.25


def test_nobody_out_is_more_cautious_and_short_hang_helps_the_throw():
    assert _p_send(190.0, outs=0)[0] < _p_send(190.0, outs=1)[0]
    # A low, short-hang fly is caught on the move: a quicker throw.
    assert _p_send(190.0, la=12.0)[0] < _p_send(190.0, la=35.0)[0]


def test_runner_on_second_uses_the_tag_scale(monkeypatch):
    r2 = _batter("R2")
    bases = BaseState(second=r2)
    _, script = _air_out(
        monkeypatch, bases, 0, [0.5], overrides={"tag_up_second_scale": 0.1}
    )
    assert bases.second is r2 and script._draws == []  # .05 floor: holds
    bases = BaseState(second=r2)
    _air_out(monkeypatch, bases, 0, [0.5], overrides={"tag_up_second_scale": 3.0})
    assert bases.third is r2


def test_runner_on_second_does_not_tag_once_the_inning_is_over(monkeypatch):
    r2, r3 = _batter("R2"), _batter("R3")
    bases = BaseState(second=r2, third=r3)
    (runs, extra, *_), script = _air_out(monkeypatch, bases, 1, [0.0, 0.0])
    assert (runs, extra) == (0, 1)
    assert bases.second is r2 and bases.third is None and script._draws == []


def test_two_outs_no_tag(monkeypatch):
    bases = BaseState(second=_batter("R2"), third=_batter("R3"))
    (runs, extra, *_), _ = _air_out(monkeypatch, bases, 2, [])
    assert (runs, extra) == (0, 0)


# --- ground outs (model 1) -----------------------------------------------------


def _ground_out(monkeypatch, bases, outs, draws, *, overrides=None, primary=None,
                inning=1, lead=0, batter=None):
    script = _Script(draws)
    monkeypatch.setattr(engine, "random", script)
    if primary is not None:
        monkeypatch.setattr(engine, "_fielder_position_for_ball", lambda **_: primary)
    tuning = load_tuning({**V1, **(overrides or {})})
    defense = _defense()
    result = _resolve_ground_out(
        bases=bases, outs=outs, batter=batter or _batter("BAT"),
        defense_map=defense, defense_ratings=compute_defense_ratings(defense, tuning),
        spray_angle=0.0, batter_side="R", tuning=tuning,
        inning=inning, fielding_lead=lead,
    )
    return result, script


def test_nobody_out_double_play_scores_the_runner_on_third(monkeypatch):
    r1, r3 = _batter("R1"), _batter("R3")
    bases = BaseState(first=r1, third=r3)
    (runs, outs_added, events, scored), script = _ground_out(
        monkeypatch, bases, 0, [0.0, 0.0]
    )
    assert (runs, outs_added, events, scored) == (1, 2, ["dp"], [r3])
    assert script._draws == []
    # The run is .90 + (sp - 50) / 400: a .91 draw holds a 50 runner.
    bases = BaseState(first=r1, third=r3)
    (runs, *_), _ = _ground_out(monkeypatch, bases, 0, [0.0, 0.91])
    assert runs == 0 and bases.third is r3


def test_one_out_double_play_scores_nobody_and_draws_nothing_for_r3(monkeypatch):
    bases = BaseState(first=_batter("R1"), third=_batter("R3"))
    (runs, outs_added, events, scored), script = _ground_out(
        monkeypatch, bases, 1, [0.0]
    )
    assert (runs, outs_added, events, scored) == (0, 2, ["dp"], [])
    assert script._draws == []


def test_draw_order_triple_play_then_dp_then_r3(monkeypatch):
    calls = []
    real_dp = engine.double_play_probability

    def dp_spy(**kw):
        calls.append(len(script._draws))
        return real_dp(**kw)

    monkeypatch.setattr(engine, "double_play_probability", dp_spy)
    r3 = _batter("R3")
    bases = BaseState(first=_batter("R1"), second=_batter("R2"), third=r3)
    # Triple play roll first, then the DP chance (turned), then R3's run.
    script = _Script([0.99, 0.0, 0.0])
    monkeypatch.setattr(engine, "random", script)
    tuning = load_tuning(V1)
    defense = _defense()
    runs, outs_added, events, scored = _resolve_ground_out(
        bases=bases, outs=0, batter=_batter("BAT"), defense_map=defense,
        defense_ratings=compute_defense_ratings(defense, tuning),
        spray_angle=0.0, batter_side="R", tuning=tuning,
    )
    assert calls == [2]  # the DP chance is computed after the TP draw
    assert (runs, outs_added, events, scored) == (1, 2, ["dp"], [r3])
    assert script._draws == []
    assert bases.third is not None and bases.third.player_id == "R2"
    # No DP: TP, DP, the home-plate play, the force at 2nd -- four draws.
    bases = BaseState(first=_batter("R1"), second=_batter("R2"), third=_batter("R3"))
    script = _Script([0.99, 0.99, 0.99, 0.99])
    monkeypatch.setattr(engine, "random", script)
    _resolve_ground_out(
        bases=bases, outs=0, batter=_batter("BAT"), defense_map=defense,
        defense_ratings=compute_defense_ratings(defense, tuning),
        spray_angle=0.0, batter_side="R", tuning=tuning,
    )
    assert script._draws == []


def test_bases_loaded_runner_on_third_is_forced_home(monkeypatch):
    r1, r2, r3 = _batter("R1"), _batter("R2"), _batter("R3")
    bases = BaseState(first=r1, second=r2, third=r3)
    # One out (no TP roll): no DP, no play at home (infield back .05),
    # batter out at 1st.
    (runs, outs_added, events, scored), script = _ground_out(
        monkeypatch, bases, 1, [0.99, 0.06, 0.99]
    )
    assert (runs, outs_added, events, scored) == (1, 1, [], [r3])
    assert (bases.first, bases.second, bases.third) == (None, r1, r2)
    assert script._draws == []


def test_infield_in_makes_the_play_at_home(monkeypatch):
    r1, r2, r3 = _batter("R1"), _batter("R2"), _batter("R3")
    bat = _batter("BAT")
    bases = BaseState(first=r1, second=r2, third=r3)
    (runs, outs_added, events, scored), script = _ground_out(
        monkeypatch, bases, 0, [0.99, 0.99, 0.49], inning=8, lead=1, batter=bat
    )
    assert (runs, outs_added, events, scored) == (0, 1, ["fc_home"], [])
    assert (bases.first, bases.second, bases.third) == (bat, r1, r2)
    assert script._draws == []
    # Same draw with the infield back (6th inning): R3 scores.
    bases = BaseState(first=r1, second=r2, third=r3)
    (runs, *_), _ = _ground_out(
        monkeypatch, bases, 0, [0.99, 0.99, 0.49, 0.99], inning=6, lead=1
    )
    assert runs == 1


@pytest.mark.parametrize(
    "inning, lead, expected",
    [(7, 0, True), (9, 2, True), (7, 3, False), (7, -1, False), (6, 0, False)],
)
def test_infield_in_rule(inning, lead, expected):
    bases = BaseState(third=_batter("R3"))
    tuning = load_tuning(V1)
    assert engine._infield_in(
        bases=bases, outs=1, inning=inning, fielding_lead=lead, tuning=tuning
    ) is expected
    assert not engine._infield_in(
        bases=bases, outs=2, inning=inning, fielding_lead=lead, tuning=tuning
    )


@pytest.mark.parametrize(
    "outs, inning, draw, scores",
    [
        (0, 1, 0.44, True), (0, 1, 0.46, False),
        (1, 1, 0.54, True), (1, 1, 0.56, False),
        (1, 8, 0.29, True), (1, 8, 0.31, False),  # infield in: .55 - .25
    ],
)
def test_runner_on_third_alone(monkeypatch, outs, inning, draw, scores):
    r3 = _batter("R3")
    bases = BaseState(third=r3)
    (runs, outs_added, events, scored), script = _ground_out(
        monkeypatch, bases, outs, [draw], inning=inning, lead=0
    )
    assert runs == int(scores) and outs_added == 1 and events == []
    assert script._draws == []


def test_runner_on_third_speed_term_is_centred(monkeypatch):
    r3 = _batter("R3", speed=60.0)
    for centre, draw, scores in ((60.0, 0.46, False), (50.0, 0.46, True)):
        bases = BaseState(third=r3)
        (runs, *_), _ = _ground_out(
            monkeypatch, bases, 0, [draw], overrides={"hitter_speed_center": centre}
        )
        assert runs == int(scores)


@pytest.mark.parametrize(
    "primary, draw, advances",
    [("2B", 0.74, True), ("1B", 0.76, False), ("SS", 0.34, True), ("3B", 0.36, False)],
)
def test_productive_out_moves_an_unforced_runner_on_second(monkeypatch, primary, draw, advances):
    r2 = _batter("R2")
    bases = BaseState(second=r2)
    (runs, outs_added, events, _), script = _ground_out(
        monkeypatch, bases, 0, [draw], primary=primary
    )
    assert (runs, outs_added, events) == (0, 1, [])
    assert (bases.third is r2) is advances
    assert script._draws == []


def test_runner_on_first_always_moves_up(monkeypatch):
    r1, r2 = _batter("R1"), _batter("R2")
    bases = BaseState(first=r1, second=r2)
    # One out (no TP roll): no DP, batter out at 1st: both forced runners
    # move up.
    (runs, outs_added, events, _), script = _ground_out(
        monkeypatch, bases, 1, [0.99, 0.99]
    )
    assert (runs, outs_added, events) == (0, 1, [])
    assert (bases.first, bases.second, bases.third) == (None, r1, r2)
    assert script._draws == []
    # Force at 2nd instead: the batter is on 1st and R2 still moves up.
    bat = _batter("BAT")
    bases = BaseState(first=r1, second=r2)
    _ground_out(monkeypatch, bases, 1, [0.99, 0.0], batter=bat)
    assert (bases.first, bases.second, bases.third) == (bat, None, r2)


def test_ground_outs_conserve_runners_model_1():
    """20,000 random base-out states under ground_out_model 1: every runner is
    on base, scored or out; no run on a 1-out DP; R1 never stays on 1st."""
    tuning = load_tuning(
        {**V1, "double_play_batter_speed_k": 0.2, "double_play_base": 0.38,
         "double_play_max": 0.6}
    )
    defense = _defense()
    ratings = compute_defense_ratings(defense, tuning)
    rng = random.Random(20261009)
    seen = Counter()
    for i in range(20000):
        outs = rng.randrange(3)
        bases = BaseState(
            first=_batter(f"A{i}", speed=rng.uniform(20, 90)) if rng.random() < 0.6 else None,
            second=_batter(f"B{i}", speed=rng.uniform(20, 90)) if rng.random() < 0.5 else None,
            third=_batter(f"C{i}", speed=rng.uniform(20, 90)) if rng.random() < 0.4 else None,
        )
        r1 = bases.first
        before = {r.player_id for r in (bases.first, bases.second, bases.third) if r}
        batter = _batter(f"BAT{i}", speed=rng.uniform(20, 90))
        runs, outs_added, events, scored = _resolve_ground_out(
            bases=bases, outs=outs, batter=batter, defense_map=defense,
            defense_ratings=ratings, spray_angle=rng.uniform(-45, 45),
            batter_side=rng.choice("LR"), tuning=tuning,
            inning=rng.randrange(1, 12), fielding_lead=rng.randrange(-3, 4),
        )
        after = [r.player_id for r in (bases.first, bases.second, bases.third) if r]
        assert len(after) == len(set(after)), events
        assert runs == len(scored)
        assert len(before) + 1 == len(after) + runs + outs_added, (events, outs)
        if outs + outs_added >= 3:
            assert runs == 0, (events, outs)
        if r1 is not None and outs < 2:
            assert bases.first is not r1, events
        seen.update(events)
    assert seen["dp"] and seen["fc"] and seen["fc_home"] and seen["tp"]


# --- whole games ---------------------------------------------------------------


def _play(seed, overrides=None):
    return engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv", seed=seed,
        tuning_overrides=dict(overrides) if overrides else None,
    )


def _digest(result) -> str:
    blob = json.dumps(
        {"log": result.pitch_log, "meta": result.metadata, "totals": result.totals},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _legacy_air_out(*, bases, outs, thrower_arm, tuning, **_ignored):
    """7.47.0 ``_advance_on_air_out``, frozen."""
    runs = 0
    extra_outs = 0
    sac_fly = False
    scored = []
    tag_out_runner = None
    if bases.third and outs < 2:
        prob = engine._advance_prob(
            bases.third.speed, thrower_arm, tuning,
            extra=tuning.get("tag_up_third_extra", 0.15),
        )
        if engine.random.random() < prob:
            runs += 1
            scored.append(bases.third)
            sac_fly = True
            bases.third = None
        else:
            extra_outs += 1
            tag_out_runner = bases.third
            bases.third = None
    if bases.second and outs < 2 and bases.third is None:
        prob = engine._advance_prob(
            bases.second.speed, thrower_arm, tuning,
            extra=tuning.get("tag_up_second_extra", 0.05),
        )
        if engine.random.random() < prob:
            bases.third = bases.second
            bases.second = None
    return runs, extra_outs, sac_fly, scored, tag_out_runner


def _legacy_ground_out(*, bases, outs, batter, defense_map, defense_ratings,
                       spray_angle, batter_side, tuning, **_ignored):
    """7.47.0 ``_resolve_ground_out``, frozen."""
    E = engine
    runs = 0
    outs_added = 1
    events = []
    scored = []
    infield_range = defense_ratings.infield
    turn_arm = defense_ratings.arm
    primary_pos = E._fielder_position_for_ball(
        ball_type="gb", spray_angle=spray_angle, batter_side=batter_side,
        tuning=tuning, infield_play=True,
    )
    primary_pos, primary_fielder = E._find_fielder(
        defense_map, primary_pos, fallback_positions=["SS", "2B", "3B", "1B"]
    )
    pivot_pos = "2B" if primary_pos in {"SS", "3B"} else "SS"
    _, pivot_fielder = E._find_fielder(defense_map, pivot_pos, fallback_positions=["2B", "SS"])
    _, oneb_fielder = E._find_fielder(defense_map, "1B", fallback_positions=["P"])
    range_scale = tuning.get("range_scale", 1.0)
    range_values = []
    if primary_fielder is not None and primary_pos is not None:
        range_values.append(
            E.adjusted_fielding_rating(primary_fielder, primary_pos, tuning) * range_scale
        )
    if pivot_fielder is not None:
        range_values.append(
            E.adjusted_fielding_rating(pivot_fielder, pivot_pos, tuning) * range_scale
        )
    if range_values:
        infield_range = sum(range_values) / len(range_values)
    arm_values = []
    for fielder in (primary_fielder, pivot_fielder, oneb_fielder):
        if fielder is not None:
            arm_values.append(E.adjusted_arm_rating(fielder, tuning))
    if arm_values:
        turn_arm = sum(arm_values) / len(arm_values)
    if bases.first and bases.second and outs < 2:
        tp_prob = tuning.get("triple_play_base", 0.0008)
        tp_prob += (infield_range - 50.0) / 900.0
        tp_prob -= (bases.first.speed - 50.0) / 800.0
        tp_prob -= (bases.second.speed - 50.0) / 800.0
        tp_prob = max(0.0, min(0.02, tp_prob))
        if E.random.random() < tp_prob:
            bases.first = None
            bases.second = None
            events.append("tp")
            return runs, 3, events, scored
    third_scores = False
    if bases.third and outs < 2:
        prob = tuning.get("ground_rbi_prob", 0.12)
        prob += (bases.third.speed - 50.0) / 400.0
        third_scores = E.random.random() < prob
    if bases.first and outs < 2:
        dp_prob = _old_dp(
            runner_speed=bases.first.speed, infield_range=infield_range,
            turn_arm=turn_arm, tuning=tuning,
        )
        if E.random.random() < dp_prob:
            outs_added = 2
            bases.first = None
            events.append("dp")
            if third_scores and outs + outs_added < 3:
                runs += 1
                scored.append(bases.third)
                bases.third = None
            return runs, outs_added, events, scored
    if third_scores:
        runs += 1
        scored.append(bases.third)
        bases.third = None
    if bases.first and outs < 2:
        force_prob = tuning.get("fielder_choice_force_prob", 0.55)
        force_prob += (infield_range - 50.0) / 200.0
        force_prob += (turn_arm - 50.0) / 320.0
        force_prob -= (bases.first.speed - 50.0) / 220.0
        if E.random.random() < force_prob:
            bases.first = batter
            events.append("fc")
        else:
            prob = E._advance_prob(bases.first.speed, turn_arm, tuning, extra=0.05)
            if E.random.random() < prob:
                if bases.second is not None and bases.third is None:
                    bases.third = bases.second
                    bases.second = None
                if bases.second is None:
                    bases.second = bases.first
                    bases.first = None
    return runs, outs_added, events, scored


SEEDS = (1, 2, 3, 4, 5, 6)


def _primary_positions() -> dict[str, str]:
    with (CALIBRATION / "players.csv").open(newline="", encoding="utf-8") as handle:
        return {
            str(row["player_id"]): str(row.get("primary_position") or "").upper()
            for row in csv.DictReader(handle)
        }


PRIMARY = _primary_positions()


def test_switches_off_games_are_byte_identical_to_the_legacy_code(monkeypatch):
    current = [_digest(_play(seed)) for seed in SEEDS]
    monkeypatch.setattr(engine, "_advance_on_air_out", _legacy_air_out)
    monkeypatch.setattr(engine, "_resolve_ground_out", _legacy_ground_out)
    legacy = [_digest(_play(seed)) for seed in SEEDS]
    assert current == legacy


def test_switches_off_games_have_no_w3_events():
    for seed in SEEDS:
        result = _play(seed)
        assert result.totals["dp_air"] == 0
        tokens = Counter()
        for entry in result.pitch_log:
            tokens.update(str(entry.get("runner_event") or "").split("+"))
        assert tokens["tag_dp"] == 0 and tokens["fc_home"] == 0


@pytest.fixture(scope="module")
def profile_games():
    from scripts.physics_sim_season_kpis import load_tuning_overrides_file

    profile = load_tuning_overrides_file(PROFILE)
    return [_play(seed, profile) for seed in range(1, 41)]


def test_profile_changes_the_games(profile_games):
    assert [_digest(r) for r in profile_games[:6]] != [_digest(_play(s)) for s in SEEDS]


def test_tag_dp_credits(profile_games):
    """A runner thrown out at home on a tag-up is a DP for the fielder and the
    catcher, counted in ``dp_air``, and never a GIDP."""
    seen = 0
    for result in profile_games:
        tag_dp = 0
        gidp_tokens = 0
        for entry in result.pitch_log:
            tokens = str(entry.get("runner_event") or "").split("+")
            tag_dp += "tag_dp" in tokens
            if entry.get("pa_result") == "out" and ("dp" in tokens or "tp" in tokens):
                gidp_tokens += 1
            if "tag_dp" in tokens:
                assert entry["tag3"]["result"] == "out"
                assert "dp" not in tokens
        assert result.totals["dp_air"] == tag_dp
        assert result.totals["gidp"] == gidp_tokens
        batting = result.metadata["batting_lines"]
        assert sum(
            int(line.get("gidp", 0)) for side in ("away", "home") for line in batting[side]
        ) == result.totals["gidp"]
        lines = {
            str(line["player_id"]): line
            for side in ("away", "home")
            for line in result.metadata["fielding_lines"][side]
        }
        throwers = Counter(
            entry["tag3"]["fielder"] for entry in result.pitch_log
            if "tag_dp" in str(entry.get("runner_event") or "").split("+")
        )
        for pid, n in throwers.items():
            assert int(lines[pid]["dp"]) >= n
        catcher_dp = sum(
            int(line["dp"]) for pid, line in lines.items() if PRIMARY.get(pid) == "C"
        )
        assert catcher_dp >= tag_dp
        seen += tag_dp
    assert seen, "no tag-up throw-out in 40 games"


def test_profile_games_score_no_run_on_an_inning_ending_play(profile_games):
    from scripts.kpi_extras import ReportOnlyKpis

    kpis = ReportOnlyKpis(players_path=CALIBRATION / "players.csv", games_per_team=40)
    for result in profile_games:
        kpis.add_game(result, away="CAL01", home="CAL02")
    report = kpis.finalize(reference={})
    metrics = report["metrics"]
    assert metrics["runs_on_inning_ending_plays"] == 0
    assert metrics["tagup_r3_opps"] > 0
    assert metrics["tagup_score_rate"] < 0.95  # the old engine scored ~.95
    assert metrics["dp_air"] == sum(r.totals["dp_air"] for r in profile_games)
    assert metrics["tag_dp_events"] == metrics["dp_air"]


def test_kpi_extras_does_not_count_tag_dp_as_gidp():
    from types import SimpleNamespace

    from scripts.kpi_extras import ReportOnlyKpis

    log = [
        {
            "pa_start": True, "inning": 1, "half": "top", "outs_before": 0,
            "bases_before": 5, "bat_score_before": 0, "fld_score_before": 0,
            "batter_id": "B1", "pitcher_id": "P1", "pitch_type": "fb",
            "count": "0-0", "pa_result": "out", "ball_type": "fb",
            "runner_event": "tag_dp",
            "tag3": {"runner": "R3", "arm": 60.0, "infield": False,
                     "result": "out", "outs": 0},
        },
    ]
    result = SimpleNamespace(
        metadata={"inning_runs": {"away": [0], "home": [0]},
                  "score": {"away": 0, "home": 0}},
        totals={"dp_air": 1}, pitch_log=log,
    )
    kpis = ReportOnlyKpis(players_path=CALIBRATION / "players.csv", games_per_team=1)
    kpis.add_game(result, away="A", home="H")
    report = kpis.finalize(reference={})
    assert report["tables"]["gidp_counts"] == {"opp": 1}
    assert report["metrics"]["dp_air"] == 1
    assert report["metrics"]["tag_dp_events"] == 1
    assert report["metrics"]["tagup_out_rate"] == 1.0


# --- review fixes (F2) ---------------------------------------------------------


def test_short_pop_up_freezes_the_runners_without_a_draw(monkeypatch):
    r2, r3 = _batter("R2", speed=90.0), _batter("R3", speed=90.0)
    bases = BaseState(second=r2, third=r3)
    (runs, extra, sf, scored, out_runner), _ = _air_out(
        monkeypatch, bases, 0, [], distance=149.0, launch_angle=60.0
    )
    assert (runs, extra, sf, scored, out_runner) == (0, 0, False, [], None)
    assert bases.third is r3 and bases.second is r2
    # At the knob the race is on again (send drawn), and the knob moves it.
    bases = BaseState(third=r3)
    _, script = _air_out(monkeypatch, bases, 0, [0.0, 0.999], distance=150.0)
    assert script._draws == [] and bases.third is None
    bases = BaseState(third=r3)
    _air_out(
        monkeypatch, bases, 0, [], distance=150.0,
        overrides={"tag_up_min_carry_ft": 160.0},
    )
    assert bases.third is r3


def test_legacy_model_ignores_the_min_carry(monkeypatch):
    bases = BaseState(third=_batter("R3"))
    monkeypatch.setattr(engine, "random", _Script([0.0]))
    runs, *_ = _advance_on_air_out(
        bases=bases, outs=0, thrower_arm=50.0, tuning=load_tuning(),
        distance=60.0, exit_velo=70.0, launch_angle=70.0, ball_type="fb",
    )
    assert runs == 1


def test_runner_on_second_holds_without_a_draw_when_too_shallow(monkeypatch):
    # sp 30 against a 70 arm at 160 ft, nobody out: his race home would send
    # him well under .05 of the time, so he does not roll at all.
    r2 = _batter("R2", speed=30.0)
    p_send = engine._tag_up_race(
        speed=30.0, arm=70.0, distance=160.0, exit_velo=95.0, launch_angle=30.0,
        outs=0, tuning=load_tuning(V1),
    )[0]
    assert p_send < 0.05
    bases = BaseState(second=r2)
    _air_out(monkeypatch, bases, 0, [], distance=160.0, arm=70.0)
    assert bases.second is r2 and bases.third is None
    # Deep enough: the old roll at tag_up_second_scale, one draw.
    bases = BaseState(second=r2)
    _, script = _air_out(monkeypatch, bases, 0, [0.0], distance=300.0, arm=70.0)
    assert bases.third is r2 and script._draws == []
    # The gate is a knob.
    bases = BaseState(second=r2)
    _, script = _air_out(
        monkeypatch, bases, 0, [0.0], distance=160.0, arm=70.0,
        overrides={"tag_up_second_min_send": 0.0},
    )
    assert bases.third is r2 and script._draws == []


def test_missing_ball_values_fall_back_in_one_place(monkeypatch):
    seen = {}
    real_race = engine._tag_up_race

    def race_spy(**kw):
        seen.update(kw)
        return real_race(**kw)

    monkeypatch.setattr(engine, "_tag_up_race", race_spy)
    bases = BaseState(third=_batter("R3"))
    _air_out(
        monkeypatch, bases, 1, [0.0, 0.999], distance=None, exit_velo=None,
        launch_angle=None,
    )
    assert (seen["distance"], seen["exit_velo"], seen["launch_angle"]) == (
        250.0, 90.0, 30.0
    )


def test_bases_loaded_nobody_out_dp_without_the_run_is_home_to_first(monkeypatch):
    r1, r2, r3 = _batter("R1"), _batter("R2"), _batter("R3")
    bases = BaseState(first=r1, second=r2, third=r3)
    # No TP, DP turned, R3's .90 run chance missed: he was forced at home.
    (runs, outs_added, events, scored), script = _ground_out(
        monkeypatch, bases, 0, [0.99, 0.0, 0.95]
    )
    assert (runs, outs_added, events, scored) == (0, 2, ["dp", "dp_home"], [])
    assert (bases.first, bases.second, bases.third) == (None, r1, r2)
    assert script._draws == []
    # R3 scores: the usual 6-4-3, R2 to 3rd, nobody on 1st or 2nd.
    bases = BaseState(first=r1, second=r2, third=r3)
    (runs, outs_added, events, scored), _ = _ground_out(
        monkeypatch, bases, 0, [0.99, 0.0, 0.0]
    )
    assert (runs, events, scored) == (1, ["dp"], [r3])
    assert (bases.first, bases.second, bases.third) == (None, None, r2)
    # Not loaded (1st and 3rd): R3 is not forced and simply holds.
    bases = BaseState(first=r1, third=r3)
    (runs, outs_added, events, _), _ = _ground_out(monkeypatch, bases, 0, [0.0, 0.95])
    assert (runs, events) == (0, ["dp"])
    assert (bases.first, bases.second, bases.third) == (None, None, r3)
    # The runners who leave the bases are R3 and the batter: R1 and R2 keep
    # their responsible pitchers.
    pitchers = {"R1": "p1", "R2": "p2", "R3": "p3"}
    bases = BaseState(first=r1, second=r2, third=r3)
    before = engine._base_runner_ids(bases)
    _ground_out(monkeypatch, bases, 0, [0.99, 0.0, 0.95])
    engine._reconcile_runner_pitchers(
        pitchers, before_ids=before, bases=bases, scored=[]
    )
    assert pitchers == {"R1": "p1", "R2": "p2"}


def test_home_to_first_dp_credits():
    from physics_sim.engine import LineupState

    defense = _defense()
    for primary_pos in ("SS", "1B"):
        state = LineupState(lineup=[], positions={})
        engine._credit_home_to_first_double_play(
            defense_state=state, defense_map=defense,
            primary_fielder=defense[primary_pos], oneb_fielder=defense["1B"],
        )
        lines = {
            pid: (line.po, line.a, line.dp)
            for pid, line in state.fielding_lines.items()
        }
        if primary_pos == "SS":
            assert lines == {"FSS": (0, 1, 1), "FC": (1, 1, 1), "F1B": (1, 0, 1)}
        else:  # 3-2-3: the 1B starts it and takes the relay
            assert lines == {"FC": (1, 1, 1), "F1B": (1, 1, 1)}
        assert sum(po for po, _a, _dp in lines.values()) == 2


def test_home_to_first_dp_in_games(monkeypatch):
    """Profile games where every DP chance is turned and R3 never scores on
    one, so 0-out bases-loaded ground outs become home-to-first DPs."""
    from scripts.physics_sim_season_kpis import load_tuning_overrides_file

    profile = load_tuning_overrides_file(PROFILE)
    monkeypatch.setattr(engine, "double_play_probability", lambda **_: 1.0)
    overrides = {**profile, "ground_out_dp_r3_score": -1.0}
    seen = 0
    for seed in range(1, 61):
        result = _play(seed, overrides)
        log = result.pitch_log
        gidp_tokens = 0
        for i, entry in enumerate(log):
            tokens = str(entry.get("runner_event") or "").split("+")
            gidp_tokens += entry.get("pa_result") == "out" and "dp" in tokens
            if "dp_home" not in tokens:
                continue
            seen += 1
            assert "dp" in tokens
            assert entry["go3"]["dp"] and not entry["go3"]["scored"]
            assert entry["go3"]["bases"] == 7 and entry["go3"]["outs"] == 0
            nxt = next(e for e in log[i + 1:] if e.get("pa_start"))
            # Two out, runners on 2nd and 3rd (R1 and R2 moved up a base).
            assert (nxt["outs_before"], nxt["bases_before"]) == (2, 6)
        assert result.totals["gidp"] == gidp_tokens
        for side in ("away", "home"):
            # Every out has exactly one putout.
            po = sum(
                int(line["po"]) for line in result.metadata["fielding_lines"][side]
            )
            outs = sum(
                int(line["outs"]) for line in result.metadata["pitcher_lines"][side]
            )
            assert po == outs, (seed, side)
    assert seen, "no home-to-first DP in 60 games"


def test_tag2_record_only_when_r2_had_a_chance(profile_games):
    seen = 0
    for result in profile_games:
        for entry in result.pitch_log:
            tag2 = entry.get("tag2")
            tag3 = entry.get("tag3")
            if tag3 and tag3["outs"] == 1 and tag3["result"] in ("out", "error"):
                # The throw-out was the 3rd out before R2's roll; an e_th
                # that later undoes it does not give him one.
                assert tag2 is None
            if tag2 is not None:
                seen += 1
                assert {"dist", "short", "infield"} <= set(tag2)
    assert seen


def test_air_out_call_site_passes_the_ball_straight_through(monkeypatch):
    calls = []
    real = engine._advance_on_air_out

    def spy(**kw):
        calls.append((kw["distance"], kw["exit_velo"], kw["launch_angle"]))
        return real(**kw)

    monkeypatch.setattr(engine, "_advance_on_air_out", spy)
    result = _play(3, V1)
    in_play = {
        (e.get("distance"), e.get("exit_velo"), e.get("launch_angle"))
        for e in result.pitch_log
        if e.get("out_type") in ("flyout", "lineout")
    }
    assert calls and set(calls) <= in_play


# Model-0 guard: sha256 of the canonical JSON (floats rounded to 6 places) of
# totals + pitch_log with the W3 play records (tag3 / tag2 / go3) and
# ``dp_air`` stripped, for CAL01 at CAL02 at the branch defaults. The frozen
# legacy copies above only stand in for the two helpers; these pins also
# catch a change at the air-out / ground-out call sites (an extra draw, a
# changed credit). RE-BASELINE whenever the 4a (default) stream changes on
# purpose: run this file and copy the "got" digests from the failure message
# into PINNED_DIGESTS. Baseline: release-4 after F1-F3 and the one-out
# triple-play fix (7.48.0); totals, pitch log and game metadata.
PINNED_DIGESTS = {
    1: "1fe9bd9b05a5acf0f3ae81b23f009dcbc1bde85aac0e729f6072db7feccf50e8",
    2: "14d6c883ef9b473fde472d7de26428fa58950a182ef9ab4a1fb6a583347932c9",
    3: "dea1e05a584b83063addacf681df00a9cd9d983f899e4bb3adc459ca7577f51c",
    4: "0bd33487f7b648fa7ab9f9c23959c1cdcbe09b3f6b630d8284269cb89d9668af",
    5: "af3731f978bf7ef06a0e1af5d914b3523f9735930238ad4ec9cbf13c28cfc226",
    6: "69a5dabf2a40ec2da47ab25909e3729d43931aceb5b41d708d53fd714bdd59f8",
}
W3_RECORDS = ("tag3", "tag2", "go3")


def _canon(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def _model0_digest(result) -> str:
    log = [
        {k: v for k, v in entry.items() if k not in W3_RECORDS}
        for entry in result.pitch_log
    ]
    totals = {k: v for k, v in result.totals.items() if k != "dp_air"}
    # The metadata carries every per-player credit (fielding, batting and
    # pitcher lines: PO/A/DP, RBI, GIDP, earned runs), so a changed credit at
    # a call site changes the digest too.
    blob = json.dumps(
        _canon({"pitch_log": log, "totals": totals, "meta": result.metadata}),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def test_switches_off_games_match_the_pinned_digests():
    results = {seed: _play(seed) for seed in PINNED_DIGESTS}
    got = {seed: _model0_digest(r) for seed, r in results.items()}
    assert got == PINNED_DIGESTS, f"got {got}"
    # The pinned games reach both call sites with a runner on 3rd.
    records = Counter(
        key for r in results.values() for e in r.pitch_log for key in W3_RECORDS
        if key in e
    )
    assert records["tag3"] and records["tag2"] and records["go3"], records


def test_kpi_extras_race_outs_and_final_outs():
    from types import SimpleNamespace

    from scripts.kpi_extras import ReportOnlyKpis

    def play(result, dist=250.0, short=False):
        return {
            "pa_start": True, "inning": 1, "half": "top", "outs_before": 0,
            "bases_before": 6, "bat_score_before": 0, "fld_score_before": 0,
            "batter_id": "B1", "pitcher_id": "P1", "pitch_type": "fb",
            "count": "0-0", "pa_result": "out", "ball_type": "fb",
            "tag3": {"runner": "R3", "arm": 50.0, "infield": False,
                     "short": short, "dist": dist, "result": result, "outs": 0},
            "tag2": {"runner": "R2", "arm": 50.0, "infield": False,
                     "short": short, "dist": dist, "outs": 0,
                     "result": "adv" if result == "score" else "hold"},
        }

    log = [play("score"), play("error"), play("out"), play("hold", 120.0, True)]
    result = SimpleNamespace(
        metadata={"inning_runs": {"away": [0], "home": [0]},
                  "score": {"away": 0, "home": 0}},
        totals={"dp_air": 1}, pitch_log=log,
    )
    kpis = ReportOnlyKpis(players_path=CALIBRATION / "players.csv", games_per_team=1)
    kpis.add_game(result, away="A", home="H")
    report = kpis.finalize(reference={})
    metrics = report["metrics"]
    assert metrics["tagup_out_per_send"] == pytest.approx(1 / 3)
    assert metrics["tagup_race_out_per_send"] == pytest.approx(2 / 3)
    assert metrics["tagup_score_rate"] == pytest.approx(0.5)
    assert metrics["tagup_short_share"] == pytest.approx(0.25)
    carry = report["tables"]["r2_tagup_by_carry"]
    assert carry["<150"] == {"n": 1, "adv": 0.0}
    assert carry["250-299"] == {"n": 3, "adv": pytest.approx(1 / 3)}
