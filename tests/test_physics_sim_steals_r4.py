"""Release 4 (W1, audit H2): stolen bases.

- No steals on a foul ball (a dead ball).
- The attempt rate reads speed through a logistic curve centred on the
  league's ACT-hitter mean (``hitter_speed_center``), 1.0 for an average
  runner; the base rates were rebased so ``steal_freq_scale`` 1.0 = MLB.
- Success is a saturating logistic curve on raw ratings.
- A double steal draws one throw, to 3rd: at most one out, and the trailing
  runner's advance on a caught lead runner ("adv2") is not a stolen base.
- The Steal Frequency slider was rebased (1.0 = MLB, range 0.25-3.0); a
  stored pre-rebase value is divided by 3 exactly once.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import BaseState
from physics_sim.models import BatterRatings
from physics_sim.outputs import serialize_game_result
from services import physics_tuning_settings as settings
from services.physics_tuning_spec import _TUNING_SECTIONS

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"

W1_STEAL_KNOBS = {
    "steal_freq_scale": 1.0,
    "steal_attempt_rate_first": 0.0328,
    "steal_attempt_rate_second": 0.00728,
    "steal_attempt_rate_home": 0.00073,
    "double_steal_rate": 0.00218,
    "steal_speed_mid": 75.0,
    "steal_speed_width": 12.0,
    "steal_success_logit_base": 1.50,
    "steal_success_speed_logit": 0.30,
    "steal_success_hold_logit": 0.21,
    "steal_success_parm_logit": 0.17,
    "steal_success_carm_logit": 0.24,
    "steal_success_cfa_logit": 0.19,
    "steal_success_cap": 0.97,
    "steal_success_floor": 0.05,
}


def _runner(pid: str, speed: float = 50.0) -> BatterRatings:
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


def _factor(sp, centre=50.0):
    return engine._steal_speed_factor(sp, load_tuning(overrides={"hitter_speed_center": centre}))


def _success(sp=50.0, hold=50.0, p_arm=50.0, c_arm=50.0, c_fa=50.0, tuning=None):
    return engine._steal_success_prob(
        speed=sp, pitcher_hold=hold, pitcher_arm=p_arm, catcher_arm=c_arm,
        catcher_fielding=c_fa, tuning=tuning or load_tuning(),
    )


# --- knobs and slider -----------------------------------------------------------


def test_steal_knobs_are_registered_and_round_trip():
    for key, value in W1_STEAL_KNOBS.items():
        assert DEFAULT_TUNING[key] == pytest.approx(value), key
        bumped = TuningConfig.from_overrides(overrides={key: str(value * 2)})
        assert bumped.get(key) == pytest.approx(value * 2), key
    # Retired, but a stored override must still load.
    assert "steal_success_base" in DEFAULT_TUNING
    assert TuningConfig.from_overrides(
        overrides={"steal_success_base": 0.7}
    ).get("steal_success_base") == pytest.approx(0.7)


def test_slider_is_rebased_so_one_is_mlb():
    specs = [s for _label, group in _TUNING_SECTIONS for s in group]
    spec = next(s for s in specs if s.key == "steal_freq_scale")
    assert spec.min_value == pytest.approx(0.25)
    assert spec.max_value == pytest.approx(3.0)
    assert spec.min_value <= DEFAULT_TUNING["steal_freq_scale"] == 1.0 <= spec.max_value
    assert "1.0" in spec.description


# --- attempt curve --------------------------------------------------------------


def test_speed_factor_is_one_at_the_centre_and_increasing():
    assert _factor(50.0) == pytest.approx(1.0)
    assert _factor(54.0, centre=54.0) == pytest.approx(1.0)
    values = [_factor(sp) for sp in range(20, 100)]
    assert all(b > a for a, b in zip(values, values[1:]))
    assert 3.0 <= _factor(70.0) / _factor(50.0) <= 4.2
    assert 5.5 <= _factor(85.0) / _factor(50.0) <= 7.0
    assert _factor(99.0) < 8.5
    assert _factor(40.0) == pytest.approx(0.46, abs=0.01)


def test_a_faster_league_shifts_the_curve():
    # The same 60 is above average in a 50 league and below in a 64 league.
    assert _factor(60.0, centre=50.0) > 1.0 > _factor(60.0, centre=64.0)
    assert _factor(64.0, centre=64.0) == pytest.approx(_factor(50.0))


def test_attempt_rate_uses_the_curve():
    tuning = load_tuning()

    def rate(sp):
        return engine._steal_attempt_rate(
            speed=sp, base_rate=0.0328, pitcher_hold=50.0, pitcher_arm=50.0,
            catcher_arm=50.0, catcher_fielding=50.0, tuning=tuning,
        )

    assert rate(50.0) == pytest.approx(0.0328)
    assert rate(70.0) == pytest.approx(0.0328 * _factor(70.0))


def test_rare_attempts_keep_the_speed_curve_and_the_slider():
    """Steals of home sit far below the old 0.001 floor: slower runners and
    a low slider setting must still lower the rate, not hit a flat floor."""
    home = DEFAULT_TUNING["steal_attempt_rate_home"]

    def rate(sp, scale=1.0):
        tuning = load_tuning(overrides={"steal_freq_scale": scale})
        return engine._steal_attempt_rate(
            speed=sp, base_rate=home, pitcher_hold=50.0, pitcher_arm=50.0,
            catcher_arm=50.0, catcher_fielding=50.0, tuning=tuning,
        )

    assert 0.0 < rate(30.0) < rate(40.0) < rate(50.0) < rate(60.0)
    assert rate(50.0, scale=0.25) == pytest.approx(rate(50.0) * 0.25)


# --- success curve --------------------------------------------------------------


def test_success_is_monotone_and_saturating():
    values = [_success(sp) for sp in range(20, 100, 5)]
    assert values == sorted(values)
    assert _success(85.0) - _success(70.0) < _success(70.0) - _success(50.0)
    assert 0.80 <= _success() <= 0.84
    assert _success(70.0) == pytest.approx(0.89, abs=0.01)
    assert _success(85.0) == pytest.approx(0.93, abs=0.01)
    assert max(_success(99.0, 20.0, 20.0, 20.0, 20.0), _success(200.0)) <= 0.97
    assert _success(0.0, 99.0, 99.0, 99.0, 99.0) >= 0.05


def test_each_deterrent_lowers_success():
    base = _success()
    assert _success(hold=70.0) < base
    assert _success(p_arm=70.0) < base
    assert _success(c_arm=70.0) < base
    assert _success(c_fa=70.0) < base


# --- double steal ---------------------------------------------------------------


def _double_steal(monkeypatch, draws):
    monkeypatch.setattr(engine, "random", _Script(draws))
    r1, r2 = _runner("R1"), _runner("R2")
    bases = BaseState(first=r1, second=r2)
    events, outs, runs, scored = engine._attempt_steal(
        bases=bases, pitcher_hold=50.0, pitcher_arm=50.0, catcher_arm=50.0,
        catcher_fielding=50.0, balls=1, strikes=0, outs=0, inning=5,
        score_diff=0, tuning=load_tuning(),
    )
    return r1, r2, bases, events, outs, runs


def test_caught_double_steal_is_one_out_and_no_sb(monkeypatch):
    r1, r2, bases, events, outs, runs = _double_steal(monkeypatch, [0.0, 0.999])
    assert [(r.player_id, e) for r, e in events] == [("R2", "cs3"), ("R1", "adv2")]
    assert outs == 1 and runs == 0
    assert (bases.first, bases.second, bases.third) == (None, r1, None)


def test_successful_double_steal(monkeypatch):
    r1, r2, bases, events, outs, runs = _double_steal(monkeypatch, [0.0, 0.0])
    assert [(r.player_id, e) for r, e in events] == [("R2", "sb3"), ("R1", "sb2")]
    assert outs == 0
    assert (bases.first, bases.second, bases.third) == (None, r1, r2)


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


def _tokens(entry):
    return [t for t in str(entry.get("runner_event") or "").split("+") if t]


def test_no_steal_on_a_foul_in_twenty_games():
    steals = 0
    for seed in range(1, 21):
        for entry in _play(seed).pitch_log:
            events = [t for t in _tokens(entry) if t[:2] in ("sb", "cs")]
            if events:
                steals += 1
                assert entry.get("outcome") != "foul", entry
                assert sum(t.startswith("cs") for t in events) <= 1, entry
    assert steals > 10


@functools.lru_cache(maxsize=None)
def _double_steal_games():
    overrides = {"double_steal_rate": 2.0, "steal_success_logit_base": -1.0}
    return tuple(_play(seed, overrides) for seed in range(1, 13))


def test_adv2_is_never_a_stolen_base():
    adv2 = 0
    for game in _double_steal_games():
        for entry in game.pitch_log:
            tokens = _tokens(entry)
            adv2 += "adv2" in tokens
            if "adv2" in tokens:
                assert "cs3" in tokens and sum(t.startswith("cs") for t in tokens) == 1
        # The engine's own counters, the batting lines (box score, season
        # stats) and the serialised box score agree with the sb tokens.
        sb_tokens = sum(
            1 for e in game.pitch_log for t in _tokens(e) if t.startswith("sb")
        )
        assert game.totals["sb"] == sb_tokens
        lines = game.metadata["batting_lines"]
        assert sum(int(l.get("sb", 0)) for side in lines.values() for l in side) == sb_tokens
        box = serialize_game_result(game)["boxscore"]
        box_sb = sum(
            int(row.get("sb", 0))
            for side in ("away", "home")
            for row in box[side]["batting"]
        )
        assert box_sb == sb_tokens
    assert adv2 > 5


# --- slider migration -----------------------------------------------------------


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "physics_tuning_overrides.json"
    monkeypatch.setattr(settings, "TUNING_OVERRIDES_PATH", path)
    return path


def test_pre_rebase_steal_scale_is_divided_once(overrides_file):
    overrides_file.write_text(json.dumps({"steal_freq_scale": 4.5, "hr_scale": 1.1}))
    assert settings.load_physics_tuning_overrides() == {
        "steal_freq_scale": pytest.approx(1.5), "hr_scale": pytest.approx(1.1),
    }
    stored = json.loads(overrides_file.read_text())
    assert stored[settings.STEAL_FREQ_REBASE_MARKER] is True
    assert stored["steal_freq_scale"] == pytest.approx(1.5)
    # Loading again (and the merged values) never divides a second time.
    assert settings.load_physics_tuning_overrides()["steal_freq_scale"] == pytest.approx(1.5)
    assert settings.load_physics_tuning_values()["steal_freq_scale"] == pytest.approx(1.5)


def test_saved_values_are_on_the_new_scale(overrides_file):
    settings.save_physics_tuning_overrides({"steal_freq_scale": 2.0})
    assert settings.load_physics_tuning_overrides() == {"steal_freq_scale": 2.0}
    assert settings.load_physics_tuning_overrides() == {"steal_freq_scale": 2.0}


def test_migration_leaves_other_files_alone(overrides_file):
    overrides_file.write_text(json.dumps({"hr_scale": 1.1}))
    before = overrides_file.read_text()
    assert settings.load_physics_tuning_overrides() == {"hr_scale": pytest.approx(1.1)}
    assert overrides_file.read_text() == before
    settings.reset_physics_tuning_overrides()
    assert settings.load_physics_tuning_overrides() == {}


def test_the_league_centre_moves_steal_volume():
    """Plan risk 1: a caller that drops the centre changes the volume."""

    def attempts(centre):
        total = 0
        for seed in range(1, 7):
            game = _play(seed, {"hitter_speed_center": centre})
            total += game.totals["sb"] + game.totals["cs"]
        return total

    assert attempts(40.0) > 1.5 * attempts(60.0)
