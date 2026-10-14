"""The development model for players on rating scale 2 (playbalance.development).

Shape (RATING_SCALE_DESIGN.md section 3): a young player closes part of his
gap to potential each year, more as he gets older; from his peak he
declines and his potential follows; potentials are never below the rating;
ratings stay in 1-99; training shares growth out without adding to it;
budgets help but cannot make a 99; pitch grades are treated the same way
(no x1.35, no drift to 99). Scale 1 players are refused.
"""

from __future__ import annotations

import copy
import statistics

import pytest

from models.pitcher import Pitcher
from models.player import Player
from playbalance import development as dev
from playbalance.player_development import TrainingWeights
from utils.rating_scale import engine_potential, engine_rating, rating_map

HITTER_KEYS = ("ch", "ph", "eye", "fa", "arm", "sp")


def _hitter(pid="H1", *, scale=2, ch=30, ph=30, eye=20, fa=40, arm=40, sp=40, gap=30, **extra):
    values = dict(
        player_id=pid,
        first_name="Test",
        last_name="Hitter",
        birthdate="2007-05-01",
        height=72,
        weight=190,
        bats="R",
        primary_position="SS",
        other_positions=[],
        gf=50,
        ch=ch,
        ph=ph,
        eye=eye,
        fa=fa,
        arm=arm,
        sp=sp,
        rating_scale=scale,
    )
    values.update(extra)
    player = Player(**values)
    player.potential = {key: min(99, getattr(player, key) + gap) for key in HITTER_KEYS}
    return player


def _pitcher(pid="P1", *, control=30, movement=30, arm=40, fb=60, sl=55, gap=30, **extra):
    values = dict(
        player_id=pid,
        first_name="Test",
        last_name="Pitcher",
        birthdate="2007-05-01",
        height=74,
        weight=200,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=50,
        control=control,
        movement=movement,
        arm=arm,
        endurance=50,
        hold_runner=50,
        fb=fb,
        sl=sl,
        rating_scale=2,
    )
    values.update(extra)
    pitcher = Pitcher(**values)
    keys = ("control", "movement", "arm", "endurance", "hold_runner", "fb", "sl")
    pitcher.potential = {key: min(99, getattr(pitcher, key) + gap) for key in keys}
    return pitcher


def _career(player, ages, **kwargs):
    path = []
    for season, age in enumerate(ages, start=2027):
        dev.develop_player(player, age=age, season=season, **kwargs)
        path.append({k: getattr(player, k) for k in player.potential})
    return path


def test_scale_1_players_are_refused():
    with pytest.raises(ValueError, match="rating scale 1"):
        dev.develop_player(_hitter(scale=1), age=20, season=2027)
    row = {"player_id": "R", "is_pitcher": "0", "ch": "50", "pot_ch": "60"}
    with pytest.raises(ValueError, match="rating scale 1"):
        dev.develop_row(row, age=20, season=2027)


def test_the_share_closed_rises_with_age_and_stops_at_the_peak():
    curve = dev.DEFAULT_PARAMS.hitter["ch"]
    shares = [dev.growth_share(age, curve) for age in range(17, curve.peak + 2)]
    assert all(b >= a for a, b in zip(shares, shares[1:-2]))
    assert shares[0] > 0 and dev.growth_share(curve.peak, curve) == 0
    assert dev.decline_points(curve.peak - 1, curve) == 0
    declines = [dev.decline_points(age, curve) for age in range(curve.peak, 42)]
    assert declines[0] > 0 and all(b > a for a, b in zip(declines, declines[1:]))


def test_a_prospect_grows_toward_his_potential_and_never_past_it():
    player = _hitter(ch=30, gap=30)
    engine_ceiling = engine_potential(player, "ch")
    path = _career(player, range(19, 30))
    values = [step["ch"] for step in path]
    assert values[-1] > 30 + 10  # he grew a lot
    assert all(b >= a for a, b in zip(values, values[1:]))  # never down while young
    # The ceiling is kept in whole stored points, rounded at random: it
    # wanders by a fraction of a point, never grows away.
    assert engine_rating(player, "ch") <= engine_ceiling + 1.5
    # Potential is never below the rating.
    for key in HITTER_KEYS:
        assert player.potential[key] >= getattr(player, key)


def test_from_his_peak_he_declines_and_his_potential_follows():
    player = _hitter(ch=70, ph=70, eye=70, gap=10)
    path = _career(player, range(31, 40))
    assert path[-1]["ch"] < 70 - 10
    assert all(b["ch"] <= a["ch"] for a, b in zip(path, path[1:]))
    for key in HITTER_KEYS:
        assert player.potential[key] == getattr(player, key)


def test_ratings_stay_inside_the_scale():
    top = _hitter(ch=98, ph=99, eye=99, fa=99, arm=99, sp=99, gap=30)
    _career(top, range(18, 30))
    low = _hitter(ch=1, ph=1, eye=1, fa=1, arm=1, sp=1, gap=0)
    _career(low, range(30, 46))
    for player in (top, low):
        for key in HITTER_KEYS:
            assert 1 <= getattr(player, key) <= 99
            assert getattr(player, key) <= player.potential[key] <= 99


def test_the_same_season_gives_the_same_result_and_rows_match_objects():
    a, b = _hitter("X"), _hitter("X")
    ra = dev.develop_player(a, age=20, season=2030)
    rb = dev.develop_player(b, age=20, season=2030)
    assert ra.changes == rb.changes and vars(a) == vars(b)
    c = _hitter("X")
    rc = dev.develop_player(c, age=20, season=2031)
    assert rc.changes != ra.changes or vars(c) == vars(a)  # another season, other noise
    row = {
        "player_id": "X", "is_pitcher": "0", "rating_scale": "2",
        **{k: str(getattr(_hitter("X"), k)) for k in HITTER_KEYS},
        **{f"pot_{k}": str(v) for k, v in _hitter("X").potential.items()},
        "other": "kept",
    }
    rr = dev.develop_row(row, age=20, season=2030)
    assert rr.changes == ra.changes
    assert row["other"] == "kept"
    for key in HITTER_KEYS:
        assert row[key] == str(getattr(a, key))
        assert row[f"pot_{key}"] == str(a.potential[key])


def test_growth_is_worked_on_the_engine_scale():
    """A gap is in engine points (the scale 2 potential rule), so the same
    engine gain is about three stored points of Contact above average and
    one of speed."""

    totals = {"ch": 0, "sp": 0}
    for i in range(200):
        player = _hitter(f"E{i}", ch=55, sp=55, gap=25)
        result = dev.develop_player(player, age=24, season=2030)
        for key in totals:
            totals[key] += result.changes.get(key, 0)
    ratio = totals["ch"] / max(1, totals["sp"])
    slope = rating_map("ch", 2).slope_above
    assert slope - 0.8 < ratio < slope + 0.8


def test_a_young_regular_with_a_small_gap_barely_grows():
    """The gap discount: a 23-year-old already at a regular's level, with
    the 5-15 point gap the generator gives his age, does not shoot up."""

    gains = []
    for i in range(200):
        player = _hitter(f"Y{i}", ch=60, ph=60, eye=60, gap=10)
        result = dev.develop_player(player, age=23, season=2030)
        gains.append(result.changes.get("ch", 0))
    assert statistics.fmean(gains) < 0.5


def test_training_focus_shares_growth_out_without_adding_to_it():
    default = {"contact": 30, "power": 25, "speed": 15, "discipline": 15, "defense": 15}
    pitchers = {"command": 25, "movement": 20, "stamina": 20, "velocity": 20, "hold": 5, "pitch_lab": 10}
    contact = dict(default, contact=60, power=10, discipline=10, defense=10, speed=10)
    plain_total = focus_total = plain_ch = focus_ch = 0
    for i in range(300):
        plain, focused = _hitter(f"T{i}", gap=30), _hitter(f"T{i}", gap=30)
        a = dev.develop_player(plain, age=21, season=2030,
                               weights=TrainingWeights(hitters=default, pitchers=pitchers))
        b = dev.develop_player(focused, age=21, season=2030,
                               weights=TrainingWeights(hitters=contact, pitchers=pitchers))
        plain_total += sum(a.changes.values())
        focus_total += sum(b.changes.values())
        plain_ch += a.changes.get("ch", 0)
        focus_ch += b.changes.get("ch", 0)
    assert focus_ch > plain_ch * 1.15  # the focus means something
    assert abs(focus_total - plain_total) < 0.12 * plain_total  # nothing added


def test_the_default_focus_is_the_same_as_no_focus():
    default = {"contact": 30, "power": 25, "speed": 15, "discipline": 15, "defense": 15}
    pitchers = {"command": 25, "movement": 20, "stamina": 20, "velocity": 20, "hold": 5, "pitch_lab": 10}
    a, b = _hitter("Z"), _hitter("Z")
    dev.develop_player(a, age=21, season=2030)
    dev.develop_player(b, age=21, season=2030,
                       weights=TrainingWeights(hitters=default, pitchers=pitchers))
    assert vars(a) == vars(b)


def test_budgets_help_growth_and_soften_decline_but_cannot_make_99s():
    def mean_change(age, budget, **ratings):
        total = 0
        for i in range(300):
            player = _hitter(f"B{i}", **ratings)
            result = dev.develop_player(player, age=age, season=2030,
                                        development=budget, intensity=budget)
            total += sum(result.changes.values())
        return total / 300

    low, mid, high = (mean_change(21, b, gap=30) for b in (0.85, 1.0, 1.15))
    assert low < mid < high
    assert high < mid * 1.3  # it matters, within the finance module's +-15%
    old_low, old_mid, old_high = (mean_change(35, b, ch=70, gap=0) for b in (0.85, 1.0, 1.15))
    assert old_low < old_mid < old_high < 0
    # A rich club's prospect still stops at what his potential allows.
    rich = _hitter(ch=40, ph=40, eye=40, gap=20)
    ceiling = {k: engine_potential(rich, k) for k in HITTER_KEYS}
    for season, age in enumerate(range(18, 30), start=2030):
        dev.develop_player(rich, age=age, season=season, development=5.0, intensity=5.0)
    for key in HITTER_KEYS:
        assert engine_rating(rich, key) <= ceiling[key] + 1.5
        assert getattr(rich, key) < 99


def test_pitch_grades_are_bounded_and_do_not_drift_to_99():
    """No x1.35 and no 99s: a 90 fastball with a 99 potential grows only
    within the gap, and from the peak it declines with the rest."""

    pitchers = [_pitcher(f"G{i}", fb=90, sl=70, gap=9) for i in range(100)]
    for pitcher in pitchers:
        for season, age in enumerate(range(20, 36), start=2030):
            dev.develop_player(pitcher, age=age, season=season)
            assert 1 <= pitcher.fb <= 99 and pitcher.fb <= pitcher.potential["fb"]
    assert sum(1 for p in pitchers if p.fb >= 99) == 0
    assert statistics.fmean(p.fb for p in pitchers) < 90
    # A year's gain is never a multiple of the grade.
    young = _pitcher(fb=60, sl=60, gap=30)
    before = young.fb
    dev.develop_player(young, age=22, season=2030)
    assert young.fb - before <= 10


def test_a_pitcher_who_throws_no_curve_is_not_given_one():
    pitcher = _pitcher()
    _career(pitcher, range(19, 34))
    assert pitcher.cb == 0 and pitcher.cu == 0 and pitcher.kn == 0
    assert "cb" not in pitcher.potential or pitcher.potential.get("cb", 0) == 0


def test_redistribution_keeps_the_total_and_respects_caps():
    out = dev._redistribute({"a": 2.0, "b": 2.0}, {"a": 3.0, "b": 1.0}, {"a": 2.5, "b": 10})
    assert out["a"] == pytest.approx(2.5)
    assert out["a"] + out["b"] == pytest.approx(4.0)
    assert dev._redistribute({"a": 0.0}, {"a": 2.0}) == {"a": 0.0}


def test_the_ceiling_does_not_creep():
    """The gap is in engine points and stored whole: rounding it must not
    move a growing player's ceiling on average (a fixed rounding moved it
    about 3 engine points up over a career). Growth is never rounded past
    the ceiling, which costs a little: under one engine point down."""

    drift = []
    for i in range(300):
        player = _hitter(f"C{i}", ch=30, ph=55, gap=30)
        start = {k: engine_potential(player, k) for k in ("ch", "ph")}
        _career(player, range(19, 29))
        drift += [engine_potential(player, k) - start[k] for k in start]
    assert -1.0 < statistics.fmean(drift) < 0.3
