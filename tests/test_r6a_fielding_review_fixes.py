"""Release 6a (fielding): the fixes from the branch review.

1. Earned runs under ``error_model`` 2 follow the reconstruction of rule
   9.16(a): a runner an extra-base error moved up carries a shadow base --
   where he would stand without it -- and his run is unearned only if the
   shadow would not have scored. An error that kept the inning alive (it
   cost the defence an out) still makes every later run unearned.
2. Under ``range_model`` 1 a low line drive is an infield play or not
   BEFORE its out chance, so the fielder whose range set the chance is the
   one credited with the out or charged with the error.
3. The default game lineup ranks a stand-in with the league's tuning.
4. No ``error_model`` 2 roll after a walk-off.
5. A steal throw with no catcher on the field is not charged to nobody.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.fielding as fielding
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import load_tuning
from physics_sim.engine_generation import engine_profile
from tests.test_r6a_fielding_errors import (
    BALLS,
    _fielder,
    _play_script,
    _scripted_game,
)

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"
PROFILE = REPO / "scripts" / "kpi_profiles" / "r6_fielding.json"

BALLS.setdefault("double", dict(ev=104.0, la=18.0, spray=25.0))
WALK = [{"pitch": "ball"}] * 4
STEAL_AND_THROW_AWAY = {
    "pitch": "strike", "steal": True, "forced": {"error_steal_throw_rate"}
}


def _runs(game):
    pitcher = game.metadata["pitcher_lines"]["home"][0]
    return pitcher["runs"], pitcher["earned_runs"]


# --- 1. earned runs: the reconstruction ---------------------------------------------


def test_a_runner_the_catcher_s_error_moved_scores_earned_on_a_home_run(monkeypatch):
    """Walk; he steals second and the throw goes into centre field (third
    base on the error); home run. Without the error he is on second and the
    home run scores him all the same: both runs are earned."""
    plan = WALK + [STEAL_AND_THROW_AWAY, {"pitch": "homer"}]
    game = _play_script(monkeypatch, plan, ["bb", "hr", "so", "so", "so"])
    assert _runs(game) == (2, 2)
    assert game.totals["e"] == 1


def test_a_batter_the_outfielder_s_error_moved_scores_earned_on_a_home_run(
    monkeypatch,
):
    """Single the right fielder lets through (the batter to second); home
    run. Without the error he is on first and scores anyway."""
    plan = [
        {"pitch": "single", "out": 0.0, "forced": {"error_of_hit_rate"}},
        {"pitch": "homer"},
    ]
    game = _play_script(monkeypatch, plan, ["1b", "hr", "so", "so", "so"])
    assert _runs(game) == (2, 2)


def test_a_double_carries_the_shadow_from_second(monkeypatch):
    """The catcher's error puts the runner on third; a double. From second,
    where he would have been, a double scores him: earned."""
    plan = WALK + [STEAL_AND_THROW_AWAY, {"pitch": "double", "out": 0.0}]
    game = _play_script(monkeypatch, plan, ["bb", "2b", "so", "so", "so"])
    assert _runs(game) == (1, 1)


def test_a_run_the_error_made_stays_unearned(monkeypatch):
    """The catcher's error puts the runner on third and a single scores
    him; from second, where he would have been, the benefit of the doubt
    goes to the pitcher (the runners take the bases they did): unearned.
    (The run batted in is the batter's all the same.)"""
    plan = WALK + [STEAL_AND_THROW_AWAY, {"pitch": "single", "out": 0.0}]
    game = _play_script(monkeypatch, plan, ["bb", "1b", "so", "so", "so"])
    assert _runs(game) == (1, 0)
    assert game.metadata["batting_lines"]["away"][1]["rbi"] == 1


def test_the_shadow_moves_on_with_the_later_plays(monkeypatch):
    """The outfielder's error puts the batter on second (shadow: first).
    Two singles: he stops at third on the first (his shadow reaches
    second) and scores on the second (his shadow only third): unearned.
    Nobody else scores."""
    plan = [
        {"pitch": "single", "out": 0.0, "forced": {"error_of_hit_rate"}},
        {"pitch": "single", "out": 0.0},
        {"pitch": "single", "out": 0.0},
    ]
    game = _play_script(monkeypatch, plan, ["1b", "1b", "1b", "so", "so", "so"])
    assert _runs(game) == (1, 0)


def test_an_error_that_kept_the_inning_alive_makes_the_rest_unearned(monkeypatch):
    """Two strikeouts, then a ground ball booted with two out (it should
    have been the third out), then a home run: neither run is earned."""
    plan = (
        [{"pitch": "strike"}] * 6
        + [{"pitch": "grounder", "out": 1.0, "roe": 1.0}, {"pitch": "homer"}]
    )
    game = _play_script(monkeypatch, plan, ["so", "so", "roe", "hr", "so"])
    assert _runs(game) == (2, 0)


def test_the_old_error_paths_are_untouched():
    """The throwing errors on advances (legacy and generation 5) still mark
    the saved runner unearned and extend the inning: those errors cost the
    defence an out, which is rule 9.16(a)'s other case."""
    source = (REPO / "physics_sim" / "engine.py").read_text(encoding="utf-8")
    body = source.split("def apply_advance_errors(", 1)[1].split("\n        def ", 1)[0]
    assert "unearned_outs += 1" in body
    assert "unearned_runners.add(runner.player_id)" in body
    assert "shadow" not in body


# --- 2. line drives: one fielder ----------------------------------------------------


@pytest.mark.parametrize("infield", [True, False])
@pytest.mark.parametrize("side", ["R", "L"])
def test_a_liner_s_responsible_fielder_is_the_one_credited(side, infield):
    tuning = load_tuning({
        "spray_direction_model": 1.0, "infield_band_model": 1.0, "range_model": 1.0,
    })
    rng = random.Random(8)
    for _ in range(2000):
        angle = rng.gauss(0.0, 20.0)
        assert engine._fielder_position_for_ball(
            ball_type="ld", spray_angle=angle, batter_side=side, tuning=tuning,
            infield_play=infield,
        ) == fielding.responsible_position(
            ball_type="ld", spray_angle=angle, tuning=tuning, infield_play=infield
        )


def test_the_liner_is_drawn_once_and_before_the_out_chance(monkeypatch):
    """Off: no early draw, ``select_out_type`` draws as it always has. On:
    one draw per low liner, before the hit roll (on a liner that becomes a
    hit it is one more draw), and ``select_out_type`` uses it."""
    drawn, handed = [], []
    real_draw, real_select = engine.draw_infield_liner, engine.select_out_type

    def draw(ball_type, launch_angle):
        result = real_draw(ball_type, launch_angle)
        drawn.append((ball_type, launch_angle, result))
        return result

    def select(ball_type, launch_angle, **kwargs):
        handed.append((ball_type, launch_angle, kwargs.get("infield_play")))
        return real_select(ball_type, launch_angle, **kwargs)

    monkeypatch.setattr(engine, "draw_infield_liner", draw)
    monkeypatch.setattr(engine, "select_out_type", select)
    key = ("CAL01", "CAL02")

    def play(extra):
        return engine.simulate_matchup_from_files(
            away_team=key[0], home_team=key[1], players_path=PLAYERS, base_dir=CAL,
            seed=4, tuning_overrides=extra,
        )

    play({})
    assert drawn == [] and all(kw is None for *_x, kw in handed)
    handed.clear()
    play({"range_model": 1.0})
    low = [(b, la) for b, la, result in drawn if result is not None]
    assert low and all(b == "ld" and la < 18.0 for b, la in low)
    assert all(result is None for b, la, result in drawn if not (b == "ld" and la < 18.0))
    liners = [entry for entry in handed if entry[0] == "ld" and entry[1] < 18.0]
    assert liners and all(kw is not None for *_x, kw in liners)
    assert len(liners) < len(low)  # the hits drew too


@pytest.fixture(scope="module")
def logged_generation_6():
    overrides = kpis.resolve_run_overrides(engine=6, overrides_path=PROFILE)
    overrides = kpis.with_rating_centers(
        {**overrides, "fielding_chance_log": 1.0}, PLAYERS, CAL
    )
    return [
        engine.simulate_matchup_from_files(
            away_team=f"CAL{2 * i + 1:02d}", home_team=f"CAL{2 * i + 2:02d}",
            players_path=PLAYERS, base_dir=CAL, seed=40 + i, tuning_overrides=overrides,
        )
        for i in range(12)
    ]


def test_every_out_and_error_goes_to_the_fielder_whose_range_set_the_chance(
    logged_generation_6,
):
    checked = infield_liners = 0
    for game in logged_generation_6:
        responsible = {row[0]: row[3][0] for row in game.play_records["bip_chances"]}
        for index, pos in game.play_records["fld_pos"].items():
            assert pos == responsible[index], game.pitch_log[index]
            checked += 1
            entry = game.pitch_log[index]
            infield_liners += entry["ball_type"] == "ld" and pos in {
                "1B", "2B", "3B", "SS", "P"
            }
        for row in game.play_records["error_chances"]:
            assert row[2] == responsible[row[0]]
    assert checked > 300 and infield_liners > 20


# --- 3. the default game lineup -------------------------------------------------------


def test_the_default_game_lineup_reads_the_league_s_tuning(monkeypatch, tmp_path):
    """The stand-in a club with nobody at a position gets is ranked with
    the generation's position table; with the table off (legacy, generation
    5) the picks are what they were without any tuning."""
    import utils.lineup_autofill as autofill
    import utils.lineup_loader as loader
    from models.roster import Roster
    from utils.pitcher_role import get_role
    from utils.player_loader import load_players_from_csv

    players = load_players_from_csv(str(REPO / "data" / "players.csv"))
    hitters = [p for p in players if get_role(p) not in {"SP", "RP"}]
    pitchers = [p for p in players if get_role(p) in {"SP", "RP"}]
    no_short = [p for p in hitters if str(p.primary_position).upper() != "SS"]
    real_build = autofill.build_lineup
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs.get("tuning"))
        return real_build(*args, **kwargs)

    def picks(tuning, *, drop_tuning=False):
        def build(*args, **kwargs):
            if drop_tuning:
                kwargs.pop("tuning", None)
            return spy(*args, **kwargs)

        monkeypatch.setattr(autofill, "build_lineup", build)
        monkeypatch.setattr(autofill, "platoon_tuning", lambda *a, **k: tuning)
        state = loader.build_default_game_state(
            "TST", players_file=str(REPO / "data" / "players.csv"),
            roster_dir=str(tmp_path), teams_file="",
        )
        return [(p.player_id, getattr(p, "position")) for p in state.lineup]

    for start in range(0, 40, 8):
        act = no_short[start:start + 12] + pitchers[:13]
        roster = Roster("TST", act=[p.player_id for p in act])
        monkeypatch.setattr(loader, "load_roster", lambda *a, **k: roster)
        for profile in ({}, engine_profile(5)):
            tuning = load_tuning(profile)
            assert picks(tuning) == picks(tuning, drop_tuning=True)
            assert seen[-2] is tuning
        table = load_tuning({"position_fit_model": 1.0})
        picks(table)
        assert seen[-1] is table


# --- 4 and 5. walk-offs and a missing catcher -------------------------------------------


def _walk_off_plan(final):
    """Bottom of the ninth, 0-0: a walk, two pickoff throws away (the
    runner to third), then ``final``."""
    return WALK + [
        {"pitch": "ball", "pickoff": event, "forced": {"error_pickoff_throw_rate"}}
        for event in ("poa1", "poa2")
    ] + final


def _walk_off(monkeypatch, plan, **kwargs):
    for seed in range(1, 25):
        with monkeypatch.context() as patch:
            game = _scripted_game(patch, plan, seed=seed, half=(9, "home"), **kwargs)
        if game.metadata["score"] == {"away": 0, "home": 1}:
            return game
    raise AssertionError("no seed walked off")


def test_no_outfield_misplay_after_a_walk_off_hit(monkeypatch):
    plan = _walk_off_plan(
        [{"pitch": "single", "out": 0.0, "forced": {"error_of_hit_rate"}}]
    )
    game = _walk_off(monkeypatch, plan)
    sources = [row[1] for row in game.play_records["errors"]]
    assert sources == ["pickoff", "pickoff"]
    assert game.pitch_log[-1]["pa_result"] == "1b"


def test_no_relay_error_after_a_walk_off_force_play(monkeypatch):
    def force_scoring_third(*, bases, batter, **_kwargs):
        scored = [bases.third] if bases.third else []
        bases.third = None
        bases.first = batter
        return len(scored), 1, ["fc"], scored

    plan = _walk_off_plan(
        WALK + [{"pitch": "grounder", "out": 1.0, "forced": {"error_relay_throw_rate"}}]
    )
    game = _walk_off(monkeypatch, plan, ground_out=force_scoring_third)
    sources = [row[1] for row in game.play_records["errors"]]
    assert sources == ["pickoff", "pickoff"]


def test_a_steal_throw_with_no_catcher_is_not_charged(monkeypatch):
    real_build = engine.build_defense_from_lineup

    def no_catcher(batters, positions):
        defense = real_build(batters, positions)
        defense.pop("C", None)
        return defense

    monkeypatch.setattr(engine, "build_defense_from_lineup", no_catcher)
    plan = WALK + [STEAL_AND_THROW_AWAY]
    game = _play_script(monkeypatch, plan, ["bb", "so", "so", "so"])
    assert game.totals["e"] == 0 and game.play_records["errors"] == []
    assert game.totals["sb"] == 1
    # And with him there, the same script is an error charged to him.
    monkeypatch.setattr(engine, "build_defense_from_lineup", real_build)
    game = _play_script(monkeypatch, plan, ["bb", "so", "so", "so"])
    assert [row[1:3] for row in game.play_records["errors"]] == [("steal", "C")]
    assert game.totals["e"] == 1 and _fielder(game, "C")
