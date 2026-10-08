"""Release 3, second fix round: bench and batter fatigue.

* CPU roster upkeep: a day-to-day player still on the active roster counts
  as present -- he protects his position (and is never the one optioned to
  make room), and a day-to-day SS / CF is no reason to call up a spare;
* a regular nobody can rest reaches the small capped penalty when he is worn
  down (it used to cost nothing: the blocked-rest relief kept him just under
  the trigger), and Auto rest days off still carries the full penalty;
* the third-catcher trim counts real (primary C) catchers only;
* the one-catcher warning and the tutorial say exactly what happens.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from models.roster import Roster
from physics_sim.config import load_tuning
from physics_sim.engine import _apply_batter_fatigue, _apply_rest_days
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.usage import UsageState, batter_fatigue_threshold
from utils.roster_rules import ACTIVE_ROSTER_SIZE, MAX_ACTIVE_PITCHERS, is_catcher

TUNING = load_tuning()
THRESHOLD = batter_fatigue_threshold(50, TUNING)


# --- finding 1: a day-to-day player is present, never the victim --------------


def _hp(pid, pos, score=50, injured=False, other=()):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=list(other), injured=injured,
        is_pitcher=(pos == "P"), ch=score, ph=score, first_name=pid, last_name="",
    )


def _club(hitters, *, aaa=(), low=()):
    """``hitters``: (pid, pos, score[, injured[, other]]) on ACT plus 13 arms."""
    players, act = {}, []
    for spec in hitters:
        pid, pos, score = spec[:3]
        injured = spec[3] if len(spec) > 3 else False
        other = spec[4] if len(spec) > 4 else ()
        players[pid] = _hp(pid, pos, score=score, injured=injured, other=other)
        act.append(pid)
    for i in range(MAX_ACTIVE_PITCHERS):
        players[f"p{i}"] = _hp(f"p{i}", "P", score=55)
        act.append(f"p{i}")
    for pid, pos, score in list(aaa) + list(low):
        players[pid] = _hp(pid, pos, score=score)
    roster = Roster("CPU", act=act, aaa=[a[0] for a in aaa], low=[x[0] for x in low])
    return players, roster


def _upkeep(players, roster, **kw):
    from services.roster_fill import maintain_cpu_active_roster

    return maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE, **kw
    )


def _sent_down(moves):
    return {m[0] for m in moves if m[1] == "act"}


def test_a_day_to_day_shortstop_with_a_healthy_backup_is_no_reason_to_call_one_up():
    hitters = [
        ("c1", "C", 60), ("c2", "C", 40), ("b1", "1B", 70), ("b2", "2B", 62),
        ("b3", "3B", 64), ("ss", "SS", 20, True), ("bss", "SS", 45),
        ("lf", "LF", 66), ("cf", "CF", 63), ("bcf", "CF", 46), ("rf", "RF", 65),
        ("dh", "1B", 55), ("x", "LF", 50),
    ]
    players, roster = _club(hitters, aaa=[("mSS", "SS", 35)])
    moves = _upkeep(players, roster)
    assert moves == []
    assert "ss" in roster.act and "mSS" in roster.aaa


def test_the_only_shortstop_day_to_day_is_never_optioned_for_his_spare():
    # The club's only SS is day-to-day and the weakest hitter: a spare may
    # come up, but the injured SS stays (he is back in a day or two).
    hitters = [
        ("c1", "C", 60), ("c2", "C", 40), ("b1", "1B", 70), ("b2", "2B", 62),
        ("b3", "3B", 64), ("ss", "SS", 20, True), ("lf", "LF", 66),
        ("cf", "CF", 63), ("bcf", "CF", 46), ("rf", "RF", 65), ("dh", "1B", 55),
        ("x", "LF", 50), ("y", "RF", 51),
    ]
    players, roster = _club(hitters, aaa=[("mSS", "SS", 35)])
    moves = _upkeep(players, roster)
    assert "ss" not in _sent_down(moves)
    assert "ss" in roster.act


def test_the_only_center_fielder_day_to_day_is_never_optioned_for_his_spare():
    hitters = [
        ("c1", "C", 60), ("c2", "C", 40), ("b1", "1B", 70), ("b2", "2B", 62),
        ("b3", "3B", 64), ("ss", "SS", 61), ("bss", "SS", 45), ("lf", "LF", 66),
        ("cf", "CF", 20, True), ("rf", "RF", 65), ("dh", "1B", 55),
        ("x", "LF", 50), ("y", "RF", 51),
    ]
    players, roster = _club(hitters, aaa=[("mCF", "CF", 35)])
    moves = _upkeep(players, roster)
    assert "cf" not in _sent_down(moves)
    assert "cf" in roster.act


def test_a_catcher_call_up_never_options_a_day_to_day_regular():
    # One catcher: the upkeep calls one up and options a position player.
    # The weakest is the club's only second baseman, day-to-day.
    hitters = [
        ("c1", "C", 60), ("b1", "1B", 70), ("b2", "2B", 10, True), ("b3", "3B", 64),
        ("ss", "SS", 61), ("bss", "SS", 45), ("lf", "LF", 66), ("cf", "CF", 63),
        ("bcf", "CF", 46), ("rf", "RF", 65), ("dh", "1B", 55), ("x", "LF", 40),
        ("y", "RF", 41),
    ]
    players, roster = _club(hitters, aaa=[("mC", "C", 30)])
    moves = _upkeep(players, roster)
    assert ("mC", "aaa", "act") in moves
    assert "b2" in roster.act
    assert ("x", "act", "aaa") in moves


def test_an_injured_hitter_is_never_the_victim():
    from services.roster_fill import _weakest_non_catcher_hitter

    hitters = [("c1", "C", 60), ("b1", "1B", 70), ("hurt", "LF", 5, True), ("x", "LF", 40)]
    players, roster = _club(hitters)
    assert _weakest_non_catcher_hitter(roster, players) == "x"


# --- finding 3: the third-catcher trim counts real catchers --------------------


def test_a_first_baseman_listing_c_does_not_make_a_third_catcher():
    hitters = [
        ("c1", "C", 60), ("c2", "C", 40), ("b1", "1B", 70), ("b2", "2B", 62),
        ("b3", "3B", 64), ("ss", "SS", 61), ("bss", "SS", 45), ("lf", "LF", 66),
        ("cf", "CF", 63), ("bcf", "CF", 46), ("rf", "RF", 65),
        ("util", "1B", 55, False, ("C",)), ("x", "LF", 50),
    ]
    players, roster = _club(hitters)
    assert is_catcher(players["util"])
    moves = _upkeep(players, roster)
    assert moves == []
    assert "c1" in roster.act and "c2" in roster.act and "util" in roster.act


def test_a_real_third_catcher_is_still_trimmed_beside_a_utility_one():
    hitters = [
        ("c1", "C", 60), ("c2", "C", 40), ("c3", "C", 35), ("b1", "1B", 70),
        ("b2", "2B", 62), ("b3", "3B", 64), ("ss", "SS", 61), ("bss", "SS", 45),
        ("lf", "LF", 66), ("cf", "CF", 63), ("bcf", "CF", 46), ("rf", "RF", 65),
        ("util", "1B", 55, False, ("C",)),
    ]
    players, roster = _club(hitters, aaa=[("mLF", "LF", 52)])
    moves = _upkeep(players, roster)
    assert ("c3", "act", "aaa") in moves
    assert "c1" in roster.act and "c2" in roster.act


# --- finding 2: a regular nobody can rest reaches the small capped penalty -----


def _b(pid: str, pos: str, *, dur: int = 50) -> BatterRatings:
    return BatterRatings.from_row(
        {"player_id": pid, "bats": "R", "primary_position": pos, "other_positions": "",
         "ch": "55", "ph": "55", "vl": "50", "eye": "50", "gf": "50", "pl": "50",
         "fa": "50", "arm": "50", "sp": "50", "durability": str(dur)}
    )


def _pitcher() -> PitcherRatings:
    return PitcherRatings.from_row(
        {"player_id": "p", "bats": "L", "throws": "L", "control": "50", "fb": "60"}
    )


def _lone_catcher_season(*, auto_rest: bool, days: int = 182) -> list:
    """Penalties a club's only catcher plays with over a season of six
    games and an off day a week, his bench holding no catcher."""

    state = UsageState()
    catcher, bench_bat = _b("c", "C"), _b("lf", "LF")
    penalties = []
    for day in range(days):
        state.advance_day(day=day, pitchers=[], batters=[catcher, bench_bat], tuning=TUNING)
        if day % 7 == 6:
            continue  # the team's off day
        kept: set = set()
        lineup, bench, positions = [catcher], [bench_bat], {"c": "C"}
        if auto_rest:
            lineup, bench, positions = _apply_rest_days(
                lineup, bench, positions, opposing_starter=_pitcher(),
                usage_state=state, game_day=day, tuning=TUNING, could_not_rest=kept,
            )
        assert lineup[0].player_id == "c"  # nobody can catch for him
        played = _apply_batter_fatigue(
            lineup, usage_state=state, game_day=day, tuning=TUNING, blocked_ids=kept
        )
        penalties.append(getattr(played[0], "fatigue_penalty", 0.0))
        state.record_batter_game(
            player_id="c", day=day, durability=50, tuning=TUNING, position="C"
        )
    return penalties


def test_a_catcher_nobody_can_rest_plays_a_little_worse_some_of_the_time():
    penalties = _lone_catcher_season(auto_rest=True)
    tired = [p for p in penalties if p > 0.0]
    cap = TUNING.get("batter_blocked_rest_penalty_cap")
    # He does wear down: a cost, not none (it was 0 games of 156).
    assert len(tired) >= 0.08 * len(penalties)
    # ... but only some of the time, and only a little.
    assert len(tired) <= 0.5 * len(penalties)
    assert max(tired) <= cap + 1e-9
    assert sum(tired) / len(tired) <= cap


def test_auto_rest_off_carries_the_full_penalty_most_of_the_season():
    penalties = _lone_catcher_season(auto_rest=False)
    tired = [p for p in penalties if p > 0.0]
    assert len(tired) >= 0.75 * len(penalties)
    # Clearly worse than the capped cost of a rest nobody could give him.
    assert max(tired) >= 3.0 * TUNING.get("batter_blocked_rest_penalty_cap")
    assert max(tired) <= TUNING.get("batter_fatigue_penalty_cap") + 1e-9


def test_merely_tired_he_gets_no_relief_worn_down_he_does():
    relief = TUNING.get("batter_blocked_rest_relief")
    assert relief > 0.0
    tired = UsageState()
    tired.batter_workload_for("c").fatigue_debt = 0.9 * THRESHOLD
    kept: set = set()
    lineup, _b2, _p = _apply_rest_days(
        [_b("c", "C")], [_b("lf", "LF")], {"c": "C"}, opposing_starter=_pitcher(),
        usage_state=tired, game_day=20, tuning=TUNING, could_not_rest=kept,
    )
    _apply_batter_fatigue(lineup, usage_state=tired, game_day=20, tuning=TUNING,
                          blocked_ids=kept)
    assert kept == {"c"}
    assert tired.batter_workload_for("c").fatigue_debt == pytest.approx(0.9 * THRESHOLD)
    worn = UsageState()
    worn.batter_workload_for("c").fatigue_debt = 1.1 * THRESHOLD
    played = _apply_batter_fatigue(
        [_b("c", "C")], usage_state=worn, game_day=20, tuning=TUNING, blocked_ids={"c"}
    )
    assert played[0].fatigue_penalty > 0.0  # priced on the debt he brought in
    assert worn.batter_workload_for("c").fatigue_debt == pytest.approx(
        1.1 * THRESHOLD - relief
    )
    # A regular his club chose not to rest gets no relief.
    chosen = UsageState()
    chosen.batter_workload_for("c").fatigue_debt = 1.1 * THRESHOLD
    _apply_batter_fatigue([_b("c", "C")], usage_state=chosen, game_day=20, tuning=TUNING)
    assert chosen.batter_workload_for("c").fatigue_debt == pytest.approx(1.1 * THRESHOLD)


# --- finding 2: the words say what happens -------------------------------------


def test_the_one_catcher_warning_says_exactly_what_happens():
    from services.roster_validation import validate_catcher_depth

    result = validate_catcher_depth(["c"], {"c": {"primary_position": "C"}})
    text = " ".join(result.warnings).lower()
    assert "can't get days off" in text
    assert "worn down" in text and "a little worse" in text
    assert "auto rest days" in text and "injury risk" in text


def test_the_rest_tutorial_says_exactly_what_happens():
    import services.tutorials as tutorials

    source = Path(tutorials.__file__).read_text(encoding="utf-8")
    assert "only one catcher" in source
    assert "can't get days off" in source
    assert "worn down" in source and "a little worse" in source
    assert "small extra injury risk" in source
