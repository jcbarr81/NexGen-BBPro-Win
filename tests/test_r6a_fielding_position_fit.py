"""Release 6a (fielding): the out-of-position table (audit M12, decision 8).

``position_fit_model`` 1 charges a fielder the points of
``utils.position_fit.POSITION_MOVE_PENALTY`` instead of the flat x0.9 /
x0.75 multipliers; a listed second position costs a quarter of the table
value and an unlisted one the cheapest route from any position he lists.
One function (``utils.position_fit.position_fielding``) serves the engine's
plays, its defensive-substitution and injury-replacement scorers and the
lineup auto-fill's ``fielding_fit``. With the model off every one of them
gives the number it gave before.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as engine
import physics_sim.fielding as fielding
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.models import BatterRatings
from utils import position_fit as fit
from utils.lineup_autofill import build_lineup

REPO = Path(__file__).resolve().parents[1]
FIELD = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
TABLE = fit.POSITION_MOVE_PENALTY


def _player(pid="X", primary="SS", other=(), fa=60.0, arm=50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position=primary,
        other_positions=list(other), contact=50.0, power=50.0, gb_tendency=50.0,
        pull_tendency=50.0, vs_left=50.0, fielding=fa, arm=arm, speed=50.0,
        eye=50.0, height=72.0, durability=50.0,
    )


def _tuning(**overrides):
    return load_tuning(overrides)


ON = {"position_fit_model": 1.0}


# --- the table ---------------------------------------------------------------------


def test_the_switch_is_off_and_the_scale_is_a_quarter():
    assert DEFAULT_TUNING["position_fit_model"] == 0.0
    assert DEFAULT_TUNING["position_secondary_penalty_scale"] == 0.25
    assert fit.SECONDARY_PENALTY_SCALE == 0.25
    assert DEFAULT_TUNING["defense_primary_pos_scale"] == 1.0
    assert DEFAULT_TUNING["defense_secondary_pos_scale"] == 0.9
    assert DEFAULT_TUNING["defense_out_of_pos_scale"] == 0.75


def test_the_table_has_the_plan_s_values():
    """RELEASE6_PLAN.md 2.3 and the design brief's table."""
    assert TABLE["CF"]["LF"] == 0 and TABLE["CF"]["RF"] == 0
    assert TABLE["RF"]["LF"] == 1 and TABLE["LF"]["RF"] == 2
    assert TABLE["SS"]["2B"] == 1 and TABLE["SS"]["3B"] == 2
    assert TABLE["2B"]["3B"] == 4 and TABLE["3B"]["2B"] == 4
    assert TABLE["2B"]["SS"] == 6 and TABLE["3B"]["SS"] == 7
    assert TABLE["LF"]["CF"] == 7 and TABLE["RF"]["CF"] == 7
    for infielder in ("2B", "3B", "SS"):
        assert TABLE[infielder]["1B"] == 2
        assert 6 <= TABLE[infielder]["LF"] <= 8 and 6 <= TABLE[infielder]["RF"] <= 8
    for outfielder in ("LF", "RF"):
        assert TABLE[outfielder]["2B"] == 10 and TABLE[outfielder]["3B"] == 10
        assert TABLE[outfielder]["SS"] == 14
    assert TABLE["1B"]["SS"] == 14
    assert (TABLE["C"]["1B"], TABLE["C"]["LF"], TABLE["C"]["SS"]) == (5, 9, 16)
    for start, row in TABLE.items():
        if start != "C":
            assert row["C"] == 25, start


def test_the_table_is_whole_and_never_negative():
    assert set(TABLE) == set(FIELD) | {"DH"}
    for start, row in TABLE.items():
        assert set(row) == set(FIELD) - {start}, start
        assert all(value >= 0 for value in row.values()), start
    # The worst move that is not to catcher is 16 points.
    worst = max(v for row in TABLE.values() for to, v in row.items() if to != "C")
    assert worst == 16


def test_the_similar_position_and_family_moves_are_the_cheap_ones():
    """Every rest-substitute move costs 2 or less, every fill-family move 7
    or less: the tables that decide who is asked to move agree with what
    the move costs."""
    for to, sources in fit.REST_SIMILAR_SOURCES.items():
        for start in sources:
            assert TABLE[start][to] <= 2, (start, to)
    for to, sources in fit.FILL_FAMILY.items():
        for start in sources:
            assert TABLE[start][to] <= 7, (start, to)


# --- the cheapest route ------------------------------------------------------------


def test_nothing_at_the_primary_position():
    for pos in FIELD:
        assert fit.move_penalty(_player(primary=pos), pos) == 0.0


def test_an_unlisted_position_costs_the_table():
    for start in FIELD:
        for to in FIELD:
            if to != start:
                assert fit.move_penalty(_player(primary=start), to) == TABLE[start][to]


def test_a_listed_second_position_costs_a_quarter():
    player = _player(primary="2B", other=["3B"])
    assert fit.move_penalty(player, "3B") == pytest.approx(0.25 * 4)
    player = _player(primary="1B", other=["SS"])
    assert fit.move_penalty(player, "SS") == pytest.approx(0.25 * 14)
    assert fit.move_penalty(player, "SS", secondary_scale=0.5) == pytest.approx(7.0)
    assert fit.move_penalty(player, "SS", secondary_scale=1.0) == 14.0


def test_the_cheapest_route_from_any_listed_position():
    # A first baseman who lists left field: centre field straight from first
    # is 13; from left it is 7, plus a quarter of 1B -> LF (7).
    player = _player(primary="1B", other=["LF"])
    assert fit.move_penalty(player, "CF") == pytest.approx(7 + 0.25 * 7)
    assert fit.move_penalty(player, "RF") == pytest.approx(2 + 0.25 * 7)
    # The direct move wins when the detour is dearer: 1B -> 3B is 6, by way
    # of left field 10 + 1.75.
    assert fit.move_penalty(player, "3B") == 6.0
    # A second baseman who lists third: short is 6 direct, 7 + 1 by third.
    assert fit.move_penalty(_player(primary="2B", other=["3B"]), "SS") == 6.0
    # A catcher who lists first base reaches third cheaper by first.
    catcher = _player(primary="C", other=["1B"])
    assert fit.move_penalty(catcher, "3B") == pytest.approx(min(10, 6 + 0.25 * 5))
    # The cheapest of several listed positions.
    utility = _player(primary="LF", other=["2B", "CF"])
    assert fit.move_penalty(utility, "SS") == pytest.approx(
        min(14, 6 + 0.25 * 10, 13 + 0.25 * 7)
    )


def test_a_route_is_never_dearer_than_the_table_and_never_negative():
    for start in FIELD:
        for listed in FIELD:
            if listed == start:
                continue
            player = _player(primary=start, other=[listed])
            for to in FIELD:
                cost = fit.move_penalty(player, to)
                assert 0.0 <= cost <= TABLE[start].get(to, 0.0), (start, listed, to)


def test_a_player_with_no_fielding_position_reads_the_dh_row():
    for primary in ("DH", "P", "", "OF"):
        assert fit.move_penalty(_player(primary=primary), "SS") == TABLE["DH"]["SS"]
    # A move the table does not know (to DH) costs a flat 10.
    assert fit.move_penalty(_player(primary="SS"), "DH") == 10.0


def test_players_csv_rows_and_engine_ratings_agree():
    row = {"primary_position": "ss", "other_positions": "2B|3B", "fa": "61"}
    obj = SimpleNamespace(primary_position="SS", other_positions=["2B", "3B"], fa=61)
    for to in FIELD:
        assert fit.move_penalty(row, to) == fit.move_penalty(obj, to)
    assert fit.position_fielding(row, "2B", model=1) == pytest.approx(61 - 0.25)


# --- the one function ---------------------------------------------------------------


@pytest.mark.parametrize("fa", [31.0, 50.0, 58.5, 77.25])
def test_the_model_off_is_the_old_multipliers_to_the_last_bit(fa):
    """What ``fielding.adjusted_fielding_rating`` and
    ``engine._defense_rating_for_pos`` computed before this release."""
    tuning = _tuning()
    player = _player(primary="2B", other=["SS", "3B"], fa=fa)

    def old(position):
        rating = player.fielding
        if position == player.primary_position:
            rating *= tuning.get("defense_primary_pos_scale", 1.0)
        elif position in player.other_positions:
            rating *= tuning.get("defense_secondary_pos_scale", 0.9)
        else:
            rating *= tuning.get("defense_out_of_pos_scale", 0.75)
        return rating

    for position in FIELD:
        assert fielding.adjusted_fielding_rating(player, position, tuning) == old(position)
        assert engine._defense_rating_for_pos(player, position, tuning) == old(position)
        assert fit.position_fielding(player, position) == old(position)
    # The commissioner's scales still apply.
    scaled = _tuning(defense_secondary_pos_scale=0.8, defense_out_of_pos_scale=0.5)
    assert fielding.adjusted_fielding_rating(player, "SS", scaled) == fa * 0.8
    assert fielding.adjusted_fielding_rating(player, "CF", scaled) == fa * 0.5


def test_the_model_on_subtracts_the_table():
    tuning = _tuning(**ON)
    player = _player(primary="2B", other=["3B"], fa=60.0)
    assert fielding.adjusted_fielding_rating(player, "2B", tuning) == 60.0
    assert fielding.adjusted_fielding_rating(player, "3B", tuning) == 59.0
    assert fielding.adjusted_fielding_rating(player, "SS", tuning) == 54.0
    assert fielding.adjusted_fielding_rating(player, "C", tuning) == 35.0
    # The old multipliers are not read.
    wild = _tuning(**ON, defense_secondary_pos_scale=0.1, defense_out_of_pos_scale=0.1)
    assert fielding.adjusted_fielding_rating(player, "SS", wild) == 54.0
    # The secondary share is a knob.
    half = _tuning(**ON, position_secondary_penalty_scale=0.5)
    assert fielding.adjusted_fielding_rating(player, "3B", half) == 58.0


def test_the_penalty_no_longer_grows_with_the_rating():
    """The old rule cost a 70 fielder more points than a 40 one for the
    same move; the table costs both the same."""
    off, on = _tuning(), _tuning(**ON)
    good, poor = _player(primary="CF", fa=70.0), _player(primary="CF", fa=40.0)
    assert fielding.adjusted_fielding_rating(good, "LF", off) == 52.5
    assert fielding.adjusted_fielding_rating(poor, "LF", off) == 30.0
    assert fielding.adjusted_fielding_rating(good, "LF", on) == 70.0
    assert fielding.adjusted_fielding_rating(poor, "LF", on) == 40.0


def test_the_engine_has_one_copy_of_the_multipliers():
    """The duplicated logic (fielding.py and engine.py) is gone: the scale
    keys are read in one function, and the engine's scorer calls it."""
    pattern = re.compile(r"defense_(primary|secondary|out_of)_pos_scale")
    engine_source = (REPO / "physics_sim" / "engine.py").read_text(encoding="utf-8")
    assert not pattern.search(engine_source)
    assert "adjusted_fielding_rating(player, position, tuning)" in engine_source
    fielding_source = (REPO / "physics_sim" / "fielding.py").read_text(encoding="utf-8")
    body = fielding_source.split("def adjusted_fielding_rating(", 1)[1]
    body = body.split("\ndef ", 1)[0]
    assert "position_fielding(" in body
    # The out-of-position scales are read there and nowhere else (the
    # primary scale is also what a league-average fielder is read through,
    # for the chance log).
    for key in ("defense_secondary_pos_scale", "defense_out_of_pos_scale"):
        assert fielding_source.count(key) == 1 and body.count(key) == 1, key
    for folder in ("playbalance", "services", "utils", "api"):
        for path in sorted((REPO / folder).rglob("*.py")):
            assert not pattern.search(path.read_text(encoding="utf-8")), path


# --- the scorers -------------------------------------------------------------------


def _state(lineup, positions, bench):
    return engine.LineupState(lineup=lineup, positions=positions, bench=bench)


def _old_replacement(lineup_state, tuning):
    """``engine._select_defensive_replacement`` as it was, with the old
    private copy of the multipliers."""

    def rating_for(player, position):
        rating = player.fielding
        if position == player.primary_position:
            rating *= tuning.get("defense_primary_pos_scale", 1.0)
        elif position in player.other_positions:
            rating *= tuning.get("defense_secondary_pos_scale", 0.9)
        else:
            rating *= tuning.get("defense_out_of_pos_scale", 0.75)
        return rating

    current_by_id = {b.player_id: b for b in lineup_state.lineup}
    best = None
    best_gain = tuning.get("defensive_sub_fielding_diff", 8.0)
    for pos in FIELD:
        current_id = next(
            (pid for pid, where in lineup_state.positions.items() if where == pos), None
        )
        current = current_by_id.get(current_id)
        if current is None:
            continue
        for candidate in lineup_state.bench:
            if pos != candidate.primary_position and pos not in candidate.other_positions:
                continue
            gain = rating_for(candidate, pos) - rating_for(current, pos)
            if gain >= best_gain:
                best_gain = gain
                best = (pos, current, candidate)
    return best


def test_the_defensive_substitution_chooses_as_before_with_the_model_off():
    import random

    rng = random.Random(6)
    tuning = _tuning()
    choices = 0
    for trial in range(300):
        lineup, positions = [], {}
        for pos in FIELD:
            primary = pos if rng.random() < 0.7 else rng.choice(FIELD)
            other = [p for p in FIELD if p != primary and rng.random() < 0.2]
            player = _player(f"L{trial}{pos}", primary, other, fa=rng.uniform(35, 70))
            lineup.append(player)
            positions[player.player_id] = pos
        bench = [
            _player(
                f"B{trial}{i}", rng.choice(FIELD),
                [p for p in FIELD if rng.random() < 0.3], fa=rng.uniform(35, 75),
            )
            for i in range(4)
        ]
        state = _state(lineup, positions, bench)
        got = engine._select_defensive_replacement(lineup_state=state, tuning=tuning)
        assert got == _old_replacement(state, tuning), trial
        choices += got is not None
    assert 30 < choices < 300


def test_the_defensive_substitution_reads_the_table_with_the_model_on():
    """A shortstop standing in at second (1 point) against a real second
    baseman 5 points better: the old x0.9 hid the stand-in's glove and
    made the swap; the table does not."""
    starter = _player("start", "SS", [], fa=62.0)
    lineup = [starter]
    positions = {"start": "2B"}
    bench = [_player("glove", "2B", [], fa=55.0)]
    state = _state(lineup, positions, bench)
    off = engine._select_defensive_replacement(lineup_state=state, tuning=_tuning())
    assert off is not None and off[2].player_id == "glove"  # 55 against 46.5
    on = engine._select_defensive_replacement(lineup_state=state, tuning=_tuning(**ON))
    assert on is None  # 55 against 61
    # And it does make the swap the table says is worth 8 points.
    bench = [_player("glove", "2B", [], fa=69.0)]
    state = _state(lineup, positions, bench)
    on = engine._select_defensive_replacement(lineup_state=state, tuning=_tuning(**ON))
    assert on is not None and on[2].player_id == "glove"


def test_the_injury_replacement_goes_through_the_same_function():
    injured = _player("hurt", "SS")
    listed = _player("listed", "2B", ["SS"], fa=60.0)
    natural = _player("natural", "SS", [], fa=57.0)
    state = _state([injured], {"hurt": "SS"}, [listed, natural])
    pick = engine._select_injury_replacement(
        lineup_state=state, injured_player=injured, tuning=_tuning()
    )
    assert pick.player_id == "natural"  # 57 against 60 * 0.9 = 54
    pick = engine._select_injury_replacement(
        lineup_state=state, injured_player=injured, tuning=_tuning(**ON)
    )
    assert pick.player_id == "listed"  # 60 - 6 / 4 = 58.5 against 57


def test_fielding_fit_is_unchanged_without_the_model():
    player = {"primary_position": "1B", "other_positions": "", "fa": "60", "arm": "40"}
    for pos in FIELD:
        plain = fit.fielding_fit(player, pos)
        weight = 0.6 if pos in {"C", "SS", "3B", "CF", "RF"} else 0.85
        assert plain == pytest.approx(weight * 60 + (1 - weight) * 40)
        assert fit.fielding_fit(player, pos, None) == plain
        assert fit.fielding_fit(player, pos, _tuning()) == plain


def test_fielding_fit_reads_the_table_with_the_model_on():
    tuning = _tuning(**ON)
    player = {"primary_position": "1B", "other_positions": "LF", "fa": "60", "arm": "40"}
    assert fit.fielding_fit(player, "1B", tuning) == fit.fielding_fit(player, "1B")
    at_short = fit.fielding_fit(player, "SS", tuning)
    assert at_short == pytest.approx(0.6 * (60 - 14) + 0.4 * 40)
    at_left = fit.fielding_fit(player, "LF", tuning)
    assert at_left == pytest.approx(0.85 * (60 - 0.25 * 7) + 0.15 * 40)


def test_the_auto_fill_picks_the_stand_in_the_table_prefers():
    """Nobody lists centre field and nobody from its family is spare, so the
    auto-fill's last resort takes the best fit of a spare first baseman and
    a spare third baseman. By ratings alone that is the better glove, the
    first baseman; the table charges him 13 points there and the third
    baseman 11, which turns it."""
    players = {
        pid: {"primary_position": pos, "other_positions": "", "fa": fa, "arm": 50}
        for pid, pos, fa in (
            ("c", "C", 50), ("first", "1B", 50), ("second", "2B", 50),
            ("short", "SS", 50), ("third", "3B", 50), ("left", "LF", 50),
            ("right", "RF", 50), ("x1", "1B", 60), ("x3", "3B", 59),
        )
    }
    scores = {pid: 0.0 for pid in players}
    scores.update(first=1.0, third=1.0)  # the regulars keep their spots
    score = scores.__getitem__
    pool = sorted(players)

    def centre_fielder(**kwargs):
        lineup, _ = build_lineup(pool, players, score=score, **kwargs)
        return {pos: pid for pid, pos in lineup}["CF"]

    assert centre_fielder() == "x1"
    assert centre_fielder(tuning=_tuning()) == "x1"
    assert centre_fielder(tuning=_tuning(**ON)) == "x3"
