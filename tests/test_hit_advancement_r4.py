"""Release 4 W2: balls that fall for hits (audit L21, M6, M7 and triples).

- L21: runners on a ground-ball single advance on the outfielder who picks
  the ball up (his arm, his assist, his throwing error), not the infielder.
- The hit-advance knobs reproduce 7.47.0 at their defaults (a frozen copy of
  the old ``_advance_on_hit`` over random base states) and give MLB-like
  rates with the 4b profile (scripts/kpi_profiles/r4b.json).
- Triples by tier ("T3"): the speed slope is split, so burners triple about
  twice as often as an average runner instead of nearly four times.
- M6: the ground-ball out chance reads batter speed against the league's
  ACT-hitter mean; at the default scale 0 nothing changes.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import BaseState
from physics_sim.fielding import DefenseRatings, out_probability
from physics_sim.models import BatterRatings
from physics_sim.park import load_park
from physics_sim.physics import resolve_batted_ball

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
LEAGUE_FIXTURE = REPO / "data" / "calibration_league"
R4B_PROFILE = REPO / "scripts" / "kpi_profiles" / "r4b.json"

W2_KEYS = {
    "hit_advance_aggression_scale": 1.6,
    "hit_advance_out_scale": 1.0,
    "xbt_single_r1_extra": 0.05,
    "xbt_single_r2_extra": 0.15,
    "xbt_double_r1_extra": -0.05,
    "xbt_two_out_extra": 0.0,
    "forced_runner_out_scale": 1.0,
    "triple_speed_scale_fast": 0.12,
    "infield_hit_speed_scale": 0.0,
    "infield_hit_ev_lo": 80.0,
    "infield_hit_ev_hi": 100.0,
    "infield_single_ev_max": 0.0,
}
INFIELD = {"1B", "2B", "3B", "SS"}
OUTFIELD = {"LF", "CF", "RF"}


def _batter(pid: str, pos: str = "CF", speed: float = 50.0, arm: float = 50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position=pos, other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=arm, speed=speed, eye=50.0,
        height=72.0, durability=50.0,
    )


class _NoDraws:
    def random(self):
        raise AssertionError("an infield single must not draw")


# --- knobs ---------------------------------------------------------------------


def test_w2_knobs_are_registered_with_legacy_defaults():
    for key, value in W2_KEYS.items():
        assert key in DEFAULT_TUNING, key
        assert DEFAULT_TUNING[key] == pytest.approx(value), key
    # T3 values ship in 4a.
    assert DEFAULT_TUNING["triple_speed_scale"] == pytest.approx(0.15)
    assert DEFAULT_TUNING["stretch_triple_speed_scale"] == pytest.approx(0.10)
    assert DEFAULT_TUNING["triple_distance_scale"] == pytest.approx(0.96)


def test_w2_knobs_round_trip_through_from_overrides():
    overrides = {key: value + 0.37 for key, value in W2_KEYS.items()}
    tuning = TuningConfig.from_overrides(overrides=overrides)
    for key, value in overrides.items():
        assert tuning.get(key) == pytest.approx(value), key


def test_r4b_profile_keys_are_registered_and_numeric():
    profile = json.loads(R4B_PROFILE.read_text(encoding="utf-8"))
    assert profile, "the 4b profile is empty"
    tuning = TuningConfig.from_overrides(overrides=profile)
    for key, value in profile.items():
        assert key in DEFAULT_TUNING, key
        assert tuning.get(key) == pytest.approx(float(value)), key


# --- legacy equivalence --------------------------------------------------------


def _frozen_advance_prob(speed, arm, tuning, extra=0.0):
    base = 0.45 + (speed - 50.0) / 200.0 - (arm - 50.0) / 250.0 + extra
    base *= tuning.get("advancement_aggression_scale", 1.0)
    return max(0.05, min(0.95, base))


def _frozen_out_on_base_prob(speed, arm, tuning, extra=0.0):
    base = tuning.get("extra_base_out_base", 0.08) + extra
    base += (arm - 50.0) / 200.0
    base -= (speed - 50.0) / 240.0
    base *= tuning.get("extra_base_out_scale", 1.0)
    return max(0.01, min(0.55, base))


def _frozen_attempt(*, runner, defense_arm, tuning, attempt_extra=0.0, out_extra=0.0, force=False):
    attempt_prob = _frozen_advance_prob(runner.speed, defense_arm, tuning, extra=attempt_extra)
    if not force and random.random() >= attempt_prob:
        return "hold"
    out_prob = _frozen_out_on_base_prob(runner.speed, defense_arm, tuning, extra=out_extra)
    if random.random() < out_prob:
        if random.random() < engine._throw_error_probability(defense_arm, tuning):
            return "error"
        return "out"
    return "advance"


def _frozen_advance_on_hit(*, bases, batter, hit_type, defense_arm, tuning):
    """7.47.0 ``engine._advance_on_hit``, copied verbatim (logic only)."""
    runs = 0
    outs = 0
    events = []
    scored = []
    error_advances = []
    if hit_type == "hr":
        scored.extend(r for r in (bases.first, bases.second, bases.third) if r)
        scored.append(batter)
        runs = len(scored)
        bases.first = bases.second = bases.third = None
        return runs, outs, events, scored, error_advances
    if hit_type == "triple":
        scored.extend(r for r in (bases.first, bases.second, bases.third) if r)
        runs = len(scored)
        bases.first = bases.second = None
        bases.third = batter
        return runs, outs, events, scored, error_advances
    if hit_type == "double":
        runner_first, runner_second, runner_third = bases.first, bases.second, bases.third
        bases.first = None
        bases.second = batter
        bases.third = None
        for runner, extra, out_extra in ((runner_third, 0.25, -0.02), (runner_second, 0.15, 0.02)):
            if not runner:
                continue
            result = _frozen_attempt(runner=runner, defense_arm=defense_arm, tuning=tuning,
                                     attempt_extra=extra, out_extra=out_extra, force=True)
            if result == "out":
                outs += 1
                events.append("oobH")
            elif result == "error":
                runs += 1
                scored.append(runner)
                error_advances.append(runner)
                events.append("e_th")
            else:
                runs += 1
                scored.append(runner)
        if runner_first:
            result = _frozen_attempt(runner=runner_first, defense_arm=defense_arm, tuning=tuning,
                                     attempt_extra=-0.05, out_extra=0.12, force=False)
            if result == "advance":
                runs += 1
                scored.append(runner_first)
            elif result == "error":
                runs += 1
                scored.append(runner_first)
                error_advances.append(runner_first)
                events.append("e_th")
            elif result == "out":
                outs += 1
                events.append("oobH")
            else:
                bases.third = runner_first
        return runs, outs, events, scored, error_advances
    runner_first, runner_second, runner_third = bases.first, bases.second, bases.third
    bases.first = batter
    bases.second = None
    bases.third = None
    if runner_third:
        result = _frozen_attempt(runner=runner_third, defense_arm=defense_arm, tuning=tuning,
                                 attempt_extra=0.25, out_extra=-0.02, force=True)
        if result == "out":
            outs += 1
            events.append("oobH")
        elif result == "error":
            runs += 1
            scored.append(runner_third)
            error_advances.append(runner_third)
            events.append("e_th")
        else:
            runs += 1
            scored.append(runner_third)
    if runner_second:
        result = _frozen_attempt(runner=runner_second, defense_arm=defense_arm, tuning=tuning,
                                 attempt_extra=0.15, out_extra=0.05, force=False)
        if result == "advance":
            runs += 1
            scored.append(runner_second)
        elif result == "error":
            runs += 1
            scored.append(runner_second)
            error_advances.append(runner_second)
            events.append("e_th")
        elif result == "out":
            outs += 1
            events.append("oobH")
        else:
            bases.third = runner_second
    if runner_first:
        if bases.third is None:
            result = _frozen_attempt(runner=runner_first, defense_arm=defense_arm, tuning=tuning,
                                     attempt_extra=0.05, out_extra=0.08, force=False)
            if result == "advance":
                bases.third = runner_first
            elif result == "error":
                error_advances.append(runner_first)
                events.append("e_th")
                if random.random() < tuning.get("throw_error_extra_base_chance", 0.35):
                    runs += 1
                    scored.append(runner_first)
                else:
                    bases.third = runner_first
            elif result == "out":
                outs += 1
                events.append("oob3")
            else:
                bases.second = runner_first
        else:
            bases.second = runner_first
    return runs, outs, events, scored, error_advances


def _ids(runners):
    return [r.player_id for r in runners]


def _state(bases):
    return tuple(r.player_id if r else None for r in (bases.first, bases.second, bases.third))


def test_default_knobs_reproduce_the_7470_advance_on_hit():
    """2,000 random base states x 4 hit types: same outcome, same draws."""
    tuning = load_tuning()
    rng = random.Random(20261009)
    for i in range(2000):
        runners = [
            _batter(f"R{k}{i}", speed=rng.uniform(15, 99)) if rng.random() < p else None
            for k, p in ((1, 0.6), (2, 0.5), (3, 0.4))
        ]
        arm = rng.uniform(15, 99)
        outs = rng.randrange(3)
        batter = _batter(f"BAT{i}", speed=rng.uniform(15, 99))
        for hit_type in ("single", "double", "triple", "hr"):
            seed = rng.randrange(1 << 30)
            old_bases = BaseState(first=runners[0], second=runners[1], third=runners[2])
            new_bases = BaseState(first=runners[0], second=runners[1], third=runners[2])
            random.seed(seed)
            old = _frozen_advance_on_hit(bases=old_bases, batter=batter, hit_type=hit_type,
                                         defense_arm=arm, tuning=tuning)
            old_next = random.random()
            random.seed(seed)
            new = engine._advance_on_hit(bases=new_bases, batter=batter, hit_type=hit_type,
                                         defense_arm=arm, tuning=tuning, outs=outs)
            new_next = random.random()
            assert new[:3] == old[:3], (i, hit_type)
            assert _ids(new[3]) == _ids(old[3]) and _ids(new[4]) == _ids(old[4])
            assert _state(new_bases) == _state(old_bases)
            assert new_next == old_next, "the draw count changed"


# --- 4b knobs ------------------------------------------------------------------


def _profile_tuning() -> TuningConfig:
    return load_tuning(json.loads(R4B_PROFILE.read_text(encoding="utf-8")))


def _fixture_speeds_and_of_arms() -> tuple[list[float], list[float]]:
    speeds, arms = [], []
    with (LEAGUE_FIXTURE / "players.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("is_pitcher") or "0").strip() not in ("0", "", "False", "false"):
                continue
            if row.get("sp"):
                speeds.append(float(row["sp"]))
            if row.get("primary_position") in OUTFIELD and row.get("arm"):
                arms.append(float(row["arm"]))
    return speeds, arms


def _situation_rates(tuning: TuningConfig, outs_mix=(0, 1, 2), n: int = 12000) -> dict:
    """Monte Carlo of one runner per situation, tier fixture speeds and OF arms."""
    speeds, arms = _fixture_speeds_and_of_arms()
    random.seed(4242)
    rates = {}
    for situation in ("s_r1", "s_r2", "s_r3", "d_r1", "d_r2"):
        for outs in outs_mix:
            taken = thrown = 0
            for i in range(n):
                runner = _batter("RUN", speed=random.choice(speeds))
                bases = BaseState()
                setattr(bases, {"1": "first", "2": "second", "3": "third"}[situation[-1]], runner)
                hit_type = "single" if situation[0] == "s" else "double"
                _runs, outs_added, _ev, scored, _err = engine._advance_on_hit(
                    bases=bases, batter=_batter("BAT"), hit_type=hit_type,
                    defense_arm=random.choice(arms), tuning=tuning, outs=outs,
                )
                if situation == "s_r1":
                    taken += bases.third is runner or runner in scored
                else:
                    taken += runner in scored
                thrown += outs_added
            rates[(situation, outs)] = (taken / n, thrown / n)
    return rates


def test_r4b_profile_lands_in_the_mlb_bands():
    rates = _situation_rates(_profile_tuning())

    def mean(situation, field, outs=(0, 1, 2)):
        return sum(rates[(situation, o)][field] for o in outs) / len(outs)

    assert 0.25 <= mean("s_r1", 0) <= 0.33
    assert 0.55 <= mean("s_r2", 0) <= 0.66
    assert rates[("s_r2", 2)][0] >= rates[("s_r2", 0)][0] + 0.15
    assert 0.36 <= mean("d_r1", 0) <= 0.46
    thrown = sum(mean(s, 1) for s in ("s_r1", "s_r2", "d_r1")) / 3
    assert 0.01 <= thrown <= 0.04
    assert mean("s_r3", 0) >= 0.99
    assert mean("d_r2", 0) >= 0.98


def test_two_out_extra_only_moves_the_running_on_contact_situations():
    tuning = _profile_tuning()
    assert tuning.get("xbt_two_out_extra") > 0.15
    rates = _situation_rates(tuning, outs_mix=(1, 2), n=6000)
    assert rates[("s_r2", 2)][0] > rates[("s_r2", 1)][0] + 0.1
    assert rates[("d_r1", 2)][0] > rates[("d_r1", 1)][0] + 0.1
    assert abs(rates[("s_r1", 2)][0] - rates[("s_r1", 1)][0]) < 0.03


def _p_taken(sp, arm, tuning, extra, out_extra):
    attempt = engine._advance_prob(
        sp, arm, tuning, extra=extra, scale=tuning.get("hit_advance_aggression_scale")
    )
    out = engine._out_on_base_prob(
        sp, arm, tuning, extra=out_extra, scale=tuning.get("hit_advance_out_scale")
    )
    return attempt, attempt * (1.0 - out)


@pytest.mark.parametrize("extra_key,out_extra", [
    ("xbt_single_r1_extra", 0.08), ("xbt_single_r2_extra", 0.05), ("xbt_double_r1_extra", 0.12),
])
def test_r4b_advances_are_monotone_and_unsaturated(extra_key, out_extra):
    tuning = _profile_tuning()
    extra = tuning.get(extra_key)
    attempt_50, _ = _p_taken(50.0, 50.0, tuning, extra, out_extra)
    assert 0.05 < attempt_50 < 0.95, "saturated at an average runner"
    by_speed = [_p_taken(sp, 50.0, tuning, extra, out_extra)[1] for sp in range(20, 100, 5)]
    assert all(b > a for a, b in zip(by_speed, by_speed[1:]))
    by_arm = [_p_taken(50.0, arm, tuning, extra, out_extra)[1] for arm in range(20, 100, 5)]
    assert all(b < a for a, b in zip(by_arm, by_arm[1:]))


def test_forced_runner_out_scale_only_touches_forced_runners(monkeypatch):
    tuning = load_tuning({"forced_runner_out_scale": 0.0, "hit_advance_out_scale": 1.0})
    # Forced runner: attempt is skipped; the out draw (0.0) can't beat 0.
    monkeypatch.setattr(engine, "random", _Script([0.0]))
    assert engine._attempt_extra_base(
        runner=_batter("R3"), defense_arm=50.0, tuning=tuning, force=True
    ) == "advance"
    # Unforced runner: attempt (0.0 < p), out (0.0 < p), no error (0.99).
    monkeypatch.setattr(engine, "random", _Script([0.0, 0.0, 0.99]))
    assert engine._attempt_extra_base(
        runner=_batter("R2"), defense_arm=50.0, tuning=tuning, force=False
    ) == "out"


class _Script:
    def __init__(self, draws):
        self._draws = list(draws)

    def random(self):
        assert self._draws, "the play drew more numbers than scripted"
        return self._draws.pop(0)


# --- infield singles (4b subset) ---------------------------------------------


def test_infield_single_moves_every_runner_exactly_one_base(monkeypatch):
    monkeypatch.setattr(engine, "random", _NoDraws())
    r1, r2, r3, bat = _batter("R1"), _batter("R2"), _batter("R3"), _batter("BAT")
    bases = BaseState(first=r1, second=r2, third=r3)
    runs, outs_added, events, scored, errors = engine._advance_on_hit(
        bases=bases, batter=bat, hit_type="single", defense_arm=50.0,
        tuning=load_tuning(), infield_hit=True,
    )
    assert (runs, outs_added, events, errors) == (1, 0, [], [])
    assert scored == [r3]
    assert (bases.first, bases.second, bases.third) == (bat, r1, r2)
    bases = BaseState(first=r1)
    engine._advance_on_hit(bases=bases, batter=bat, hit_type="single",
                           defense_arm=50.0, tuning=load_tuning(), infield_hit=True)
    assert (bases.first, bases.second, bases.third) == (bat, r1, None)


def test_infield_single_switch_is_off_by_default():
    default = load_tuning()
    on = load_tuning({"infield_single_ev_max": 85.0})
    kwargs = dict(ball_type="gb", hit_type="single", exit_velo=70.0)
    assert not engine._is_infield_single(tuning=default, **kwargs)
    assert engine._is_infield_single(tuning=on, **kwargs)
    assert engine._is_infield_single(tuning=on, ball_type="gb", hit_type="single", exit_velo=85.0)
    assert not engine._is_infield_single(tuning=on, ball_type="gb", hit_type="single", exit_velo=85.1)
    assert not engine._is_infield_single(tuning=on, ball_type="ld", hit_type="single", exit_velo=70.0)
    assert not engine._is_infield_single(tuning=on, ball_type="gb", hit_type="double", exit_velo=70.0)


# --- L21 routing ---------------------------------------------------------------


@pytest.mark.parametrize("side", ["L", "R"])
def test_hit_advance_position_is_an_outfielder_unless_infield_hit(side):
    tuning = load_tuning()
    for spray in range(-45, 46, 3):
        assert engine._hit_advance_position(
            spray_angle=spray, batter_side=side, tuning=tuning
        ) in OUTFIELD
        assert engine._hit_advance_position(
            spray_angle=spray, batter_side=side, tuning=tuning, infield_hit=True
        ) == engine._infield_pos_for_spray(engine._spray_dir(spray, side))


def _defense_map():
    return {pos: _batter(f"F{pos}", pos) for pos in INFIELD | OUTFIELD | {"C"}}


def test_assist_and_throwing_error_go_to_the_given_outfielder():
    tuning = load_tuning()
    defense_map = _defense_map()
    state = engine.LineupState(lineup=list(defense_map.values()), positions={})
    engine._credit_outs_on_base(
        defense_state=state, defense_map=defense_map, events=["oobH", "oob3"],
        ball_type="gb", spray_angle=0.0, batter_side="R", tuning=tuning, fielder_pos="LF",
    )
    assert engine._fielding_line(state, "FLF").a == 2
    assert engine._fielding_line(state, "FC").po == 1
    assert engine._fielding_line(state, "F3B").po == 1
    assert all(engine._fielding_line(state, f"F{p}").a == 0 for p in INFIELD)
    engine._credit_throw_error(
        defense_state=state, defense_map=defense_map, ball_type="gb", spray_angle=0.0,
        batter_side="R", infield_play=False, tuning=tuning, fielder_pos="RF",
    )
    assert engine._fielding_line(state, "FRF").e == 1
    assert all(engine._fielding_line(state, f"F{p}").e == 0 for p in INFIELD)
    # Without a position the ground ball still re-derives an infielder (ROE).
    engine._credit_outs_on_base(
        defense_state=state, defense_map=defense_map, events=["oobH"],
        ball_type="gb", spray_angle=0.0, batter_side="R", tuning=tuning,
    )
    assert sum(engine._fielding_line(state, f"F{p}").a for p in INFIELD) == 1


def _play_games(monkeypatch, overrides=None, seeds=range(1, 41)):
    """Calibration games with infield arms 90 and outfield arms 20.

    Records, for each batted-ball hit, the ball type, the arm the runners
    tested and the position credited for outs on the bases.
    """
    arms = []
    credits = []
    pending = {}
    orig_ratings = engine._fielder_ratings
    orig_upgrade = engine._maybe_upgrade_hit
    orig_advance = engine._advance_on_hit
    orig_credit = engine._credit_outs_on_base

    def ratings(**kw):
        fielding, _arm = orig_ratings(**kw)
        pos = kw.get("position")
        return fielding, 90.0 if pos in INFIELD else 20.0 if pos in OUTFIELD else _arm

    def upgrade(**kw):
        pending["ball_type"] = kw["ball_type"]
        return orig_upgrade(**kw)

    def advance(**kw):
        ball_type = pending.pop("ball_type", None)
        if ball_type is not None:
            arms.append((ball_type, kw["hit_type"], kw["defense_arm"], kw.get("infield_hit")))
            pending["credit"] = ball_type
        return orig_advance(**kw)

    def credit(**kw):
        ball_type = pending.pop("credit", None)
        if ball_type is not None:
            credits.append((ball_type, kw.get("fielder_pos")))
        return orig_credit(**kw)

    monkeypatch.setattr(engine, "_fielder_ratings", ratings)
    monkeypatch.setattr(engine, "_maybe_upgrade_hit", upgrade)
    monkeypatch.setattr(engine, "_advance_on_hit", advance)
    monkeypatch.setattr(engine, "_credit_outs_on_base", credit)
    results = [
        engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
            players_path=CALIBRATION / "players.csv", seed=seed,
            tuning_overrides=overrides,
        )
        for seed in seeds
    ]
    return arms, credits, results


def test_ground_ball_singles_advance_on_the_outfielders_arm(monkeypatch):
    arms, credits, _ = _play_games(monkeypatch)
    gb = [a for a in arms if a[0] == "gb"]
    assert len(gb) > 50
    assert all(arm == 20.0 for _bt, _ht, arm, _inf in arms), "an infield arm was used"
    assert all(not inf for *_rest, inf in arms)
    gb_credit = [pos for bt, pos in credits if bt == "gb"]
    assert gb_credit and all(pos in OUTFIELD for pos in gb_credit)


def test_infield_singles_keep_the_infielder_when_switched_on(monkeypatch):
    arms, credits, _ = _play_games(
        monkeypatch, overrides={"infield_single_ev_max": 200.0}, seeds=range(1, 21)
    )
    gb_singles = [a for a in arms if a[0] == "gb" and a[1] == "single"]
    assert gb_singles and all(arm == 90.0 and inf for _bt, _ht, arm, inf in gb_singles)
    assert all(arm == 20.0 for bt, _ht, arm, _inf in arms if bt != "gb")
    assert all(pos in INFIELD for bt, pos in credits if bt == "gb")


def test_hit_advance_log_matches_the_engine_xbt_counters():
    from scripts.kpi_extras import ReportOnlyKpis

    acc = ReportOnlyKpis(players_path=CALIBRATION / "players.csv", games_per_team=20)
    opp = taken = 0
    for seed in range(1, 21):
        result = engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL02", base_dir=CALIBRATION,
            players_path=CALIBRATION / "players.csv", seed=seed,
        )
        acc.add_game(result, away="CAL01", home="CAL02")
        opp += result.totals["xbt_opp"]
        taken += result.totals["xbt_taken"]
        for entry in result.pitch_log:
            for row in entry.get("hit_adv") or []:
                assert row[1] in (1, 2, 3) and row[2] in (0, 1, 2, 3, 4)
                assert row[2] == 0 or row[2] >= row[1]
    report = acc.finalize()
    assert opp > 50
    assert acc.hit_adv_tier["all"]["opp"] == opp
    assert acc.hit_adv_tier["all"]["taken"] == taken
    assert report["metrics"]["xbt_logged_rate"] == pytest.approx(taken / opp)
    assert report["tables"]["xbt_by_speed_tier"]
    assert report["tables"]["batting_by_speed_tier"]


def test_kpi_extras_hit_advance_rows_by_situation_and_tier(tmp_path):
    from scripts.kpi_extras import ReportOnlyKpis, split_plate_appearances

    players = tmp_path / "players.csv"
    players.write_text(
        "player_id,bats,throws,primary_position,sp,fa\n"
        "SLOW,R,R,1B,35,50\nAVG,R,R,2B,55,50\nFAST,L,L,CF,88,50\nBAT,R,R,SS,50,50\n",
        encoding="utf-8",
    )
    acc = ReportOnlyKpis(players_path=players, games_per_team=1)

    def pa(outs, token, rows, **extra):
        entry = {
            "pa_start": True, "inning": 1, "half": "top", "outs_before": outs,
            "bases_before": 0, "bat_score_before": 0, "fld_score_before": 0,
            "batter_id": "BAT", "pitcher_id": "P", "pa_result": token,
            "ball_type": "ld", "hit_adv": rows, **extra,
        }
        return entry

    log = [
        # Single: R2 (FAST) scores; R1 (SLOW) to 3rd -> both taken.
        pa(0, "1b", [["SLOW", 1, 3, 0], ["FAST", 2, 4, 0]]),
        # Single, two out: R2 (AVG) holds at 3rd, so R1 (SLOW) is blocked.
        pa(2, "1b", [["SLOW", 1, 2, 0], ["AVG", 2, 3, 0]]),
        # Double: R1 (FAST) thrown out at home; R3 (AVG) forced home.
        pa(1, "2b", [["FAST", 1, 0, 0], ["AVG", 3, 4, 0]]),
        # Infield single on the ground: no runners.
        pa(0, "1b", None, ball_type="gb", infield_hit=True),
    ]
    acc._add_hit_speed(split_plate_appearances(log))
    report = {"metrics": {}, "tables": {}}
    acc._hit_speed_metrics(report["metrics"], report["tables"], 1)
    m, t = report["metrics"], report["tables"]
    assert acc.hit_adv_tier["all"]["opp"] == 4  # s_r1, s_r2, s_r2, d_r1
    assert acc.hit_adv_tier["all"]["taken"] == 2
    assert m["xbt_logged_rate"] == pytest.approx(0.5)
    assert m["xbt_thrown_out_per_opp"] == pytest.approx(0.25)
    assert m["r2_scores_on_single_2out_pct"] == 0.0
    assert m["r2_scores_on_single_01out_pct"] == 1.0
    assert m["r1_scores_on_double_pct"] == 0.0
    assert t["hit_advance_by_situation"]["d_r3"]["taken"] == 1.0
    assert t["xbt_by_speed_tier"]["85+"]["opp"] == 2
    assert t["xbt_by_speed_tier"]["<40"]["opp"] == 1
    assert m["infield_single_share"] == pytest.approx(1 / 3)
    assert m["gb_hit_rate"] == 1.0


# --- triples by tier (T3) -------------------------------------------------------


def _triple_share(tuning: TuningConfig, speed: float) -> float:
    park = load_park()
    n = triples = 0
    for ev in range(85, 116, 2):
        for la in range(10, 36, 2):
            for spray in range(-40, 41, 8):
                _dist, is_hr, _bt, hit_type = resolve_batted_ball(
                    exit_velo=ev, launch_angle=la, spray_angle=spray, park=park,
                    tuning=tuning, batter_speed=speed,
                )
                if is_hr:
                    continue
                n += 1
                triples += hit_type == "triple"
    return triples / n


def test_triple_threshold_tier_ratios():
    tuning = load_tuning()
    sp50 = _triple_share(tuning, 50.0)
    assert sp50 > 0
    assert _triple_share(tuning, 70.0) / sp50 <= 2.0
    assert _triple_share(tuning, 85.0) / sp50 <= 2.6
    assert _triple_share(tuning, 30.0) > 0, "a slow runner can still triple"
    # The old symmetric slope fails the same check (the test has teeth).
    old = load_tuning({"triple_speed_scale": 0.28, "triple_speed_scale_fast": -1.0})
    assert _triple_share(old, 85.0) / _triple_share(old, 50.0) > 2.6


def test_triple_fast_scale_inherits_when_negative():
    inherit = load_tuning({"triple_speed_scale": 0.2, "triple_speed_scale_fast": -1.0})
    explicit = load_tuning({"triple_speed_scale": 0.2, "triple_speed_scale_fast": 0.2})
    for sp in (20.0, 50.0, 80.0, 95.0):
        assert _triple_share(inherit, sp) == _triple_share(explicit, sp)


# --- M6 infield-hit hook ---------------------------------------------------------


def _defense_ratings() -> DefenseRatings:
    return DefenseRatings(
        infield=50.0, outfield=50.0, arm=50.0, infield_left=50.0, infield_right=50.0,
        outfield_left=50.0, outfield_center=50.0, outfield_right=50.0,
    )


def _out_prob(tuning, *, speed, ev=80.0, ball_type="gb"):
    return out_probability(
        ball_type=ball_type, exit_velo=ev, launch_angle=-5.0, spray_angle=10.0,
        batter_side="R", pull_tendency=50.0, defense=_defense_ratings(), tuning=tuning,
        batter_speed=speed,
    )


def test_out_probability_unchanged_at_scale_zero_centre_or_no_speed():
    default = load_tuning({"hitter_speed_center": 47.7})
    on = load_tuning({"infield_hit_speed_scale": 0.04, "hitter_speed_center": 47.7})
    base = _out_prob(default, speed=None)
    for speed in (20.0, 47.7, 95.0):
        assert _out_prob(default, speed=speed) == base
    assert _out_prob(on, speed=None) == base
    assert _out_prob(on, speed=47.7) == base


def test_infield_hit_term_by_speed_and_exit_velocity():
    centre = 54.4
    tuning = load_tuning({"infield_hit_speed_scale": 0.04, "hitter_speed_center": centre})
    off = load_tuning({"hitter_speed_center": centre})
    base = _out_prob(off, speed=centre + 30.0)
    assert _out_prob(tuning, speed=centre + 30.0) == pytest.approx(base - 0.12)
    assert _out_prob(tuning, speed=centre - 30.0) == pytest.approx(base + 0.12)
    # Half weight at 90 mph, none at 100+ and on balls in the air.
    base90 = _out_prob(off, speed=centre + 30.0, ev=90.0)
    assert _out_prob(tuning, speed=centre + 30.0, ev=90.0) == pytest.approx(base90 - 0.06)
    for ev in (100.0, 110.0):
        assert _out_prob(tuning, speed=centre + 30.0, ev=ev) == _out_prob(off, speed=centre + 30.0, ev=ev)
    assert _out_prob(tuning, speed=centre + 30.0, ball_type="ld") == _out_prob(
        off, speed=centre + 30.0, ball_type="ld"
    )
