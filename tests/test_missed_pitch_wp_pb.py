"""Release 4 (W1, audit M10): wild pitches, passed balls, dropped third strikes.

- The per-pitch missed-pitch roll runs only with runners on and a live ball
  (never with the bases empty, never on a foul).
- A ball that gets by is a WP/PB only when a runner advances (rule 9.13); a
  blocked ball records nothing and the pickoff/steal rolls still follow.
- Dropped third strike: eligibility (1st open or two outs) is judged before
  anyone moves, an eligible batter is not automatically safe, and a batter
  thrown out for the third out scores nobody.
- The called and swinging strikeouts share one finisher, so a swinging-K
  reach registers the pitcher responsible for the runner.
"""

from __future__ import annotations

import functools
import math
import sys
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import BaseState
from physics_sim.models import BatterRatings

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"

W1_MISSED_PITCH_KNOBS = {
    "wild_pitch_rate": 0.0097,
    "passed_ball_rate": 0.00155,
    "k_in_dirt_rate": 0.0112,
    "wild_pitch_control_k": 40.0,
    "wild_pitch_block_k": 80.0,
    "passed_ball_fa_k": 25.0,
    "missed_pitch_rate_cap": 0.05,
    "k_in_dirt_control_k": 40.0,
    "k_in_dirt_fa_k": 60.0,
    "k_reach_base": 0.85,
    "k_reach_speed_div": 200.0,
    "k_reach_arm_div": 300.0,
    "k_reach_min": 0.5,
    "k_reach_max": 0.98,
}


def _batter(pid: str, speed: float = 50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position="CF", other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=speed, eye=50.0,
        height=72.0, durability=50.0,
    )


class _Script:
    """Stands in for the ``random`` module: draws come from a fixed list."""

    def __init__(self, draws):
        self._draws = list(draws)

    def random(self):
        assert self._draws, "the play drew more numbers than scripted"
        return self._draws.pop(0)

    @property
    def left(self):
        return len(self._draws)


def _d3k(monkeypatch, bases, outs, draws, *, speed=50.0, overrides=None, full=False):
    script = _Script(draws)
    monkeypatch.setattr(engine, "random", script)
    result = engine._resolve_dropped_third_strike(
        bases=bases,
        outs=outs,
        batter=_batter("BAT", speed),
        pitcher_control=50.0,
        catcher_fielding=50.0,
        catcher_arm=50.0,
        tuning=load_tuning(overrides=overrides),
        location=(0.0, 2.5),
        zone_bottom=1.5,
        zone_top=3.5,
    )
    assert script.left == 0, "scripted draws left over"
    assert len(result) == 6
    return result if full else result[:5]


# --- knobs --------------------------------------------------------------------


def test_missed_pitch_knobs_are_registered_and_round_trip():
    for key, value in W1_MISSED_PITCH_KNOBS.items():
        assert DEFAULT_TUNING[key] == pytest.approx(value), key
        bumped = TuningConfig.from_overrides(overrides={key: str(value * 2)})
        assert bumped.get(key) == pytest.approx(value * 2), key


# --- rate helper ----------------------------------------------------------------


def test_rate_helper_rating_ratios():
    tuning = load_tuning()
    wp30, _ = engine._missed_pitch_rates(30.0, 50.0, 0.0, tuning)
    wp70, _ = engine._missed_pitch_rates(70.0, 50.0, 0.0, tuning)
    assert wp30 / wp70 == pytest.approx(math.e)
    _, pb30 = engine._missed_pitch_rates(50.0, 30.0, 0.0, tuning)
    _, pb70 = engine._missed_pitch_rates(50.0, 70.0, 0.0, tuning)
    assert pb30 / pb70 == pytest.approx(math.exp(1.6))
    wp, pb = engine._missed_pitch_rates(50.0, 50.0, 0.0, tuning)
    assert wp == pytest.approx(0.0097) and pb == pytest.approx(0.00155)


def test_rate_helper_clips_ratings_and_caps_rates():
    tuning = load_tuning()
    assert engine._missed_pitch_rates(0.0, 50.0, 0.0, tuning) == (
        engine._missed_pitch_rates(20.0, 50.0, 0.0, tuning)
    )
    assert engine._missed_pitch_rates(99.0, 99.0, 0.0, tuning) == (
        engine._missed_pitch_rates(95.0, 95.0, 0.0, tuning)
    )
    wp, pb = engine._missed_pitch_rates(20.0, 20.0, 50.0, tuning)
    assert wp == pytest.approx(0.05) and pb == pytest.approx(0.05)


# --- blocked balls --------------------------------------------------------------


def test_nobody_moving_reports_zero_bases(monkeypatch):
    monkeypatch.setattr(engine, "random", _Script([0.999, 0.999, 0.999]))
    r1, r2, r3 = _batter("R1"), _batter("R2"), _batter("R3")
    bases = BaseState(first=r1, second=r2, third=r3)
    runs, scored, advanced = engine._advance_on_missed_pitch(
        bases=bases, catcher_arm=50.0, tuning=load_tuning()
    )
    assert (runs, scored, advanced) == (0, [], 0)
    assert (bases.first, bases.second, bases.third) == (r1, r2, r3)


def test_advances_are_counted(monkeypatch):
    monkeypatch.setattr(engine, "random", _Script([0.0, 0.0]))
    r1, r3 = _batter("R1"), _batter("R3")
    bases = BaseState(first=r1, third=r3)
    runs, scored, advanced = engine._advance_on_missed_pitch(
        bases=bases, catcher_arm=50.0, tuning=load_tuning()
    )
    assert (runs, scored, advanced) == (1, [r3], 2)
    assert (bases.first, bases.second, bases.third) == (None, r1, None)


# --- dropped third strike -------------------------------------------------------


def test_k_reach_prob_values_and_monotone():
    tuning = load_tuning()

    def p(sp, arm=50.0):
        return engine._k_reach_prob(batter_speed=sp, catcher_arm=arm, tuning=tuning)

    assert p(50.0) == pytest.approx(0.85)
    assert p(70.0) == pytest.approx(0.95)
    assert p(99.0) == pytest.approx(0.98)
    assert p(0.0, arm=99.0) >= 0.5
    speeds = [20.0, 35.0, 50.0, 60.0, 70.0, 80.0]
    values = [p(s) for s in speeds]
    assert values == sorted(values)
    assert p(50.0, arm=80.0) < p(50.0, arm=30.0)


def test_d3k_r1_fewer_than_two_outs_never_reaches(monkeypatch):
    """R1 taking 2nd on the loose ball no longer frees the batter (bug a)."""
    for outs in (0, 1):
        r1 = _batter("R1")
        bases = BaseState(first=r1)
        # K roll hits, WP/PB split, R1 advances. No reach draw at all.
        reached, outs_added, runs, event, scored = _d3k(
            monkeypatch, bases, outs, [0.0, 0.0, 0.0]
        )
        assert not reached and outs_added == 1
        assert event == "wp"  # R1 moved, so the WP stands
        assert bases.second is r1 and bases.first is None


def test_d3k_eligible_batter_reaches_with_probability_p(monkeypatch):
    p = 0.85
    # First base open, nobody on: K roll, split, (no runners), reach draw.
    bases = BaseState()
    reached, outs_added, runs, event, _ = _d3k(
        monkeypatch, bases, 0, [0.0, 0.0, p - 1e-6]
    )
    assert reached and outs_added == 0 and event == "wp"
    assert bases.first is not None and bases.first.player_id == "BAT"
    bases = BaseState()
    reached, outs_added, runs, event, _ = _d3k(
        monkeypatch, bases, 0, [0.0, 0.0, p + 1e-6]
    )
    # Thrown out and nobody moved: no WP/PB is charged.
    assert not reached and outs_added == 1 and event is None
    assert bases.first is None


def test_d3k_throw_out_is_flagged_for_1b_putout_credit(monkeypatch):
    # Eligible and thrown out: 1B putout + C assist (rule 9.09(a)(2)).
    result = _d3k(monkeypatch, BaseState(), 0, [0.0, 0.0, 0.999], full=True)
    assert result[0] is False and result[1] == 1 and result[5] is True
    # Not eligible (R1, 0 out): the strikeout itself, the catcher's putout.
    result = _d3k(
        monkeypatch, BaseState(first=_batter("R1")), 0, [0.0, 0.0, 0.0], full=True
    )
    assert result[1] == 1 and result[5] is False
    # The K roll missed: an ordinary strikeout.
    result = _d3k(monkeypatch, BaseState(), 0, [0.999], full=True)
    assert result[1] == 1 and result[5] is False


def test_d3k_two_outs_with_r1_is_eligible(monkeypatch):
    r1 = _batter("R1")
    bases = BaseState(first=r1)
    # K roll, split, R1 holds (0.999), batter beats the throw.
    reached, outs_added, runs, event, _ = _d3k(
        monkeypatch, bases, 2, [0.0, 0.0, 0.999, 0.0]
    )
    assert reached and outs_added == 0
    assert bases.second is r1 and bases.first.player_id == "BAT"


def test_d3k_third_out_scores_nobody(monkeypatch):
    r3 = _batter("R3")
    bases = BaseState(third=r3)
    # R3 crosses on the loose ball, but the batter is thrown out for out 3.
    reached, outs_added, runs, event, scored = _d3k(
        monkeypatch, bases, 2, [0.0, 0.0, 0.0, 0.999]
    )
    assert not reached and outs_added == 1
    assert runs == 0 and scored == [] and event is None
    assert bases.third is r3


def test_d3k_miss_draws_only_the_k_roll(monkeypatch):
    bases = BaseState(first=_batter("R1"))
    result = _d3k(monkeypatch, bases, 0, [0.999])
    assert result == (False, 1, 0, None, [])


# --- game level -----------------------------------------------------------------


def _play(seed, overrides=None):
    return engine.simulate_matchup_from_files(
        away_team="CAL01",
        home_team="CAL02",
        base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv",
        seed=seed,
        tuning_overrides=dict(overrides) if overrides else None,
    )


@functools.lru_cache(maxsize=None)
def _busy_games():
    """Games with plenty of missed pitches and dropped third strikes."""
    overrides = {"wild_pitch_rate": 0.03, "passed_ball_rate": 0.01, "k_in_dirt_rate": 0.3}
    return tuple(_play(seed, overrides) for seed in range(1, 13))


def test_missed_pitch_roll_needs_runners_and_a_live_ball(monkeypatch):
    calls = []
    original = engine._missed_pitch_type

    def spy(**kwargs):
        if not kwargs.get("force"):
            caller = sys._getframe(1).f_locals
            bases = caller["bases"]
            calls.append(
                (
                    any((bases.first, bases.second, bases.third)),
                    caller["res"].outcome,
                )
            )
        return original(**kwargs)

    monkeypatch.setattr(engine, "_missed_pitch_type", spy)
    for seed in (1, 2, 3):
        _play(seed)
    assert calls, "no missed-pitch roll at all"
    assert all(runners for runners, _ in calls)
    assert all(outcome != "foul" for _, outcome in calls)


def test_logged_missed_pitches_are_legal():
    wp_pb = k_reach = 0
    for game in _busy_games():
        for entry in game.pitch_log:
            tokens = set(str(entry.get("runner_event") or "").split("+"))
            if tokens & {"wp", "pb"}:
                wp_pb += 1
                assert entry.get("outcome") != "foul"
                assert entry["event_bases"] != 0
            if entry.get("k_reached"):
                k_reach += 1
                assert tokens & {"k_wp", "k_pb"}
                assert not (entry["event_bases"] & 1 and entry["event_outs"] < 2)
        assert game.totals["k_reach"] == sum(
            1 for e in game.pitch_log if e.get("k_reached")
        )
    assert wp_pb > 15 and k_reach > 15


def test_runner_events_carry_the_bases_before():
    for game in _busy_games():
        for entry in game.pitch_log:
            if entry.get("runner_event") and "pitch_type" in entry:
                assert "event_bases" in entry and "event_outs" in entry
                assert 0 <= entry["event_bases"] <= 7
                assert 0 <= entry["event_outs"] <= 2


def test_blocked_ball_records_nothing_and_pickoff_still_rolls(monkeypatch):
    seq = []
    original_pickoff = engine._attempt_pickoff

    def blocked(*, bases, catcher_arm, tuning):
        seq.append("blocked")
        return 0, [], 0

    def pickoff(**kwargs):
        seq.append("pickoff")
        return original_pickoff(**kwargs)

    monkeypatch.setattr(engine, "_advance_on_missed_pitch", blocked)
    monkeypatch.setattr(engine, "_attempt_pickoff", pickoff)
    overrides = {"wild_pitch_rate": 0.05, "passed_ball_rate": 0.05, "k_in_dirt_rate": 0.0}
    for seed in (1, 2, 3, 4):
        game = _play(seed, overrides)
        assert game.totals["wp"] == 0 and game.totals["pb"] == 0
    assert seq.count("blocked") > 10
    for i, step in enumerate(seq):
        if step == "blocked":
            assert seq[i + 1] == "pickoff"


def test_swinging_k_reach_registers_the_responsible_pitcher(monkeypatch):
    """Bug b: the swinging-K copy never set runner_pitchers on a reach."""
    last_k = {}
    checked = []
    original_d3k = engine._resolve_dropped_third_strike
    original_pr = engine._maybe_pinch_run

    def d3k(**kwargs):
        result = original_d3k(**kwargs)
        caller = sys._getframe(1).f_locals
        last_k.clear()
        if result[0]:
            last_k.update(
                batter=kwargs["batter"].player_id,
                pitcher=caller["pitcher"].player_id,
                kind=caller["res"].outcome,
            )
        return result

    def pinch_run(**kwargs):
        if last_k:
            line = (kwargs["runner_pitchers"] or {}).get(last_k["batter"])
            assert line is not None, last_k
            assert line.pitcher_id == last_k["pitcher"]
            checked.append(last_k["kind"])
            last_k.clear()
        return original_pr(**kwargs)

    monkeypatch.setattr(engine, "_resolve_dropped_third_strike", d3k)
    monkeypatch.setattr(engine, "_maybe_pinch_run", pinch_run)
    for seed in range(1, 7):
        last_k.clear()  # a walk-off K reach skips the post-PA hook
        _play(seed, {"k_in_dirt_rate": 0.4})
    assert "swinging_strike" in checked and "strike" in checked


def test_walk_off_missed_pitch_ends_the_game(monkeypatch):
    """A mid-PA walk-off run ends the game on that pitch, by one run.

    Scripted: every live pitch with runners on in a tied bottom of the 9th
    or later is a wild pitch, so the runners are walked home one base at a
    time and the first run is a walk-off.
    """
    original = engine._missed_pitch_type

    def scripted(**kwargs):
        if kwargs.get("force"):
            return original(**kwargs)
        caller = sys._getframe(1).f_locals
        if (
            caller["batting_team"] == "home"
            and caller["inning"] >= 9
            and caller["score_home"] == caller["score_away"]
        ):
            return "wp"
        return None

    monkeypatch.setattr(engine, "_missed_pitch_type", scripted)
    endings = 0
    for seed in range(1, 61):
        game = _play(seed)
        last = game.pitch_log[-1]
        score = game.metadata["score"]
        if last.get("runner_event") == "wp" and score["home"] > score["away"]:
            endings += 1
            assert not last.get("pa_result")
            assert score["home"] == score["away"] + 1
            # The cut-short PA is not charged: every PA has a result.
            _assert_every_pa_has_a_result(game)
    assert endings >= 2


def _assert_every_pa_has_a_result(game):
    t = game.totals
    assert t["pa"] == t["ab"] + t["bb"] + t["hbp"] + t["sf"] + t["sh"] + t["ci"]


def test_inning_ending_caught_stealing_charges_no_pa():
    """The third out on the bases ends the PA: no PA is charged and the
    batter leads off his team's next inning (rule 5.04(a)(2))."""
    overrides = {"steal_freq_scale": 3.0, "steal_success_logit_base": -1.0}
    checked = 0
    for seed in range(1, 9):
        game = _play(seed, overrides)
        _assert_every_pa_has_a_result(game)
        half = None
        pending = {}  # half -> batter whose PA the third out cut short
        for entry in game.pitch_log:
            if entry.get("pa_start") and entry.get("half"):
                half = entry["half"]
                if half in pending:
                    assert entry["batter_id"] == pending.pop(half)
                    checked += 1
            event = str(entry.get("runner_event") or "")
            if event.startswith("cs") and entry.get("event_outs") == 2:
                pending[half] = entry["batter_id"]
    assert checked >= 3


def test_reach_on_a_dropped_third_strike_passed_ball_is_unearned():
    """Rule 9.16(a): a batter who reaches on a third-strike passed ball
    scores an unearned run; the same reach on a wild pitch stays earned.
    Errors and the automatic runner are off, so nothing else is unearned."""
    clean = {
        "k_in_dirt_rate": 0.5,
        "error_rate_scale": 0.0,
        "throw_error_scale": 0.0,
        "extra_innings_runner": 0.0,
    }

    def unearned(overrides):
        gap = reaches = 0
        for seed in range(1, 9):
            game = _play(seed, {**clean, **overrides})
            for side in game.metadata["pitcher_lines"].values():
                gap += sum(int(pl["r"]) - int(pl["er"]) for pl in side)
            reaches += sum(1 for e in game.pitch_log if e.get("k_reached"))
        return gap, reaches

    pb_gap, pb_reaches = unearned({"wild_pitch_rate": 0.0, "passed_ball_rate": 0.02})
    wp_gap, wp_reaches = unearned({"wild_pitch_rate": 0.02, "passed_ball_rate": 0.0})
    assert pb_reaches > 0 and wp_reaches > 0
    assert pb_gap > 0
    assert wp_gap == 0
