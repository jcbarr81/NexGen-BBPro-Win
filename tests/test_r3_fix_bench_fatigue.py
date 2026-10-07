"""Release 3 fix round, item F (bench and batter fatigue): review findings.

* fatigue debt has a ceiling, so a returning backup does not sit the regular
  for a dozen straight games;
* a regular nobody can rest (no legal substitute) plays only a little worse;
  the full penalty is for a club that chose not to rest him;
* "hard" rests (which allow a similar-position substitute) need real fatigue
  or a long overdue streak;
* the engine stamps ``fatigue_level`` (applied penalty over its cap) for the
  post-game fatigue injury roll;
* bench-usage tallies count every due rest, and the ones past the swap cap;
* CPU roster upkeep: a day-to-day catcher still counts, a third healthy
  catcher is trimmed, the victim of a catcher call-up is never the last
  player at a position, the only spare SS/CF or an injury cover, and CPU
  clubs carry a spare SS and CF from their own minors;
* the two-catcher send-down protection is for CPU clubs only;
* new leagues: every organisation carries two catchers and a spare SS / CF;
* the one-catcher warning and the tutorial state the real cost.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from models.roster import Roster
from physics_sim.config import load_tuning
from physics_sim.engine import _apply_batter_fatigue, _apply_rest_days
from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.usage import UsageState, batter_fatigue_threshold
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    MIN_ACTIVE_CATCHERS,
    counts_as_pitcher,
    is_catcher,
)

CAL = Path("data/calibration")
TUNING = load_tuning()
THRESHOLD = batter_fatigue_threshold(50, TUNING)


def _b(pid: str, pos: str, *, dur: int = 50, other: str = "", ch: int = 55) -> BatterRatings:
    return BatterRatings.from_row(
        {"player_id": pid, "bats": "R", "primary_position": pos,
         "other_positions": other, "ch": str(ch), "ph": "55", "vl": "50",
         "eye": "50", "gf": "50", "pl": "50", "fa": "50", "arm": "50",
         "sp": "50", "durability": str(dur)}
    )


def _pitcher() -> PitcherRatings:
    return PitcherRatings.from_row(
        {"player_id": "p", "bats": "L", "throws": "L", "control": "50", "fb": "60"}
    )


def _rest(lineup, bench, positions, state, *, day=20, **kw):
    return _apply_rest_days(
        lineup, bench, positions, opposing_starter=_pitcher(),
        usage_state=state, game_day=day, tuning=TUNING, **kw,
    )


def _ceiling() -> float:
    from physics_sim.usage import batter_fatigue_debt_ceiling

    return batter_fatigue_debt_ceiling(50, TUNING)


# --- finding 1: the debt has a ceiling ----------------------------------------


def test_fatigue_debt_never_passes_the_penalty_cap_point():
    state = UsageState()
    for day in range(200):
        state.record_batter_game(
            player_id="c", day=day, durability=50, tuning=TUNING, position="C"
        )
    cap = TUNING.get("batter_fatigue_penalty_cap")
    scale = TUNING.get("batter_fatigue_penalty_scale")
    ceiling = THRESHOLD * (1.0 + cap / scale)
    assert _ceiling() == pytest.approx(ceiling)
    assert state.batter_workload_for("c").fatigue_debt <= ceiling + 1e-9


def test_a_returning_backup_rests_the_regular_only_a_few_games_in_a_row():
    """60 straight games with nobody to spell him (auto rest off), then a
    second catcher arrives: the regular sits at most four in a row (it was
    twelve while 250 points of debt drained)."""

    state = UsageState()
    c1, c2 = _b("c1", "C"), _b("c2", "C")
    for day in range(60):
        state.advance_day(day=day, pitchers=[], batters=[c1], tuning=TUNING)
        state.record_batter_game(
            player_id="c1", day=day, durability=50, tuning=TUNING, position="C"
        )
    run, longest = 0, 0
    for day in range(60, 100):
        state.advance_day(day=day, pitchers=[], batters=[c1, c2], tuning=TUNING)
        lineup, _bench, _pos = _rest([c1], [c2], {"c1": "C"}, state, day=day)
        starter = lineup[0].player_id
        state.record_batter_game(
            player_id=starter, day=day, durability=50, tuning=TUNING, position="C"
        )
        run = run + 1 if starter == "c2" else 0
        longest = max(longest, run)
    assert longest <= 4


# --- finding 2: blocked rests cost little; the owner's choice costs more ------


def test_a_blocked_rest_is_reported_and_capped_low():
    state = UsageState()
    state.batter_workload_for("c1").fatigue_debt = _ceiling()
    kept: set = set()
    lineup, _bench, _pos = _rest(
        [_b("c1", "C")], [_b("x", "LF")], {"c1": "C"}, state, could_not_rest=kept
    )
    assert lineup[0].player_id == "c1" and kept == {"c1"}
    low_cap = TUNING.get("batter_blocked_rest_penalty_cap")
    assert 0.0 < low_cap <= 0.08
    capped = _apply_batter_fatigue(
        lineup, usage_state=state, game_day=20, tuning=TUNING, blocked_ids=kept
    )
    assert 0.0 < capped[0].fatigue_penalty <= low_cap + 1e-9


def test_an_unrested_regular_by_choice_plays_with_the_full_penalty():
    state = UsageState()
    state.batter_workload_for("c1").fatigue_debt = _ceiling()
    full = _apply_batter_fatigue(
        [_b("c1", "C")], usage_state=state, game_day=20, tuning=TUNING, blocked_ids=()
    )
    assert full[0].fatigue_penalty == pytest.approx(TUNING.get("batter_fatigue_penalty_cap"))


def test_a_blocked_fatigue_rest_gets_some_relief_a_streak_rest_does_not():
    relief = TUNING.get("batter_blocked_rest_relief")
    assert relief > 0.0
    tired = UsageState()
    tired.batter_workload_for("c1").fatigue_debt = 0.9 * THRESHOLD
    _rest([_b("c1", "C")], [_b("x", "LF")], {"c1": "C"}, tired)
    assert tired.batter_workload_for("c1").fatigue_debt == pytest.approx(
        0.9 * THRESHOLD - relief
    )
    streak = UsageState()
    wl = streak.batter_workload_for("c1")
    wl.consecutive_days_used = 5
    wl.fatigue_debt = 10.0
    _rest([_b("c1", "C")], [_b("x", "LF")], {"c1": "C"}, streak)
    assert streak.batter_workload_for("c1").fatigue_debt == pytest.approx(10.0)


def test_a_rest_blocked_by_the_owners_similar_setting_is_his_choice():
    state = UsageState()
    state.batter_workload_for("s").fatigue_debt = 1.4 * THRESHOLD
    kept: set = set()
    lineup, _bench, _pos = _rest(
        [_b("s", "LF")], [_b("rf", "RF")], {"s": "LF"}, state,
        allow_similar=False, could_not_rest=kept,
    )
    assert lineup[0].player_id == "s"
    assert kept == set()  # a substitute existed: full penalty
    assert state.batter_workload_for("s").fatigue_debt == pytest.approx(1.4 * THRESHOLD)


def _penalties_in_a_game(monkeypatch, auto_rest: bool) -> dict:
    import physics_sim.engine as engine
    from physics_sim.engine import simulate_matchup_from_files

    state = UsageState()
    seen: dict = {}
    real_game = engine.simulate_game
    real_fatigue = engine._apply_batter_fatigue

    def game(**kw):
        positions = kw["home_lineup_positions"]
        catcher = next(pid for pid, pos in positions.items() if pos == "C")
        seen["catcher"] = catcher
        from physics_sim.usage import batter_fatigue_debt_ceiling

        kw["home_bench"] = [b for b in kw["home_bench"] if not is_catcher(b)]
        batter = next(b for b in kw["home_lineup"] if b.player_id == catcher)
        state.batter_workload_for(catcher).fatigue_debt = batter_fatigue_debt_ceiling(
            batter.durability, TUNING
        )
        kw["home_rest_policy"] = {"auto_rest_days": auto_rest}
        return real_game(**kw)

    def fatigue(batters, **kw):
        out = real_fatigue(batters, **kw)
        for b in out:
            seen.setdefault("penalty", {})[b.player_id] = getattr(b, "fatigue_penalty", 0.0)
        return out

    monkeypatch.setattr(engine, "simulate_game", game)
    monkeypatch.setattr(engine, "_apply_batter_fatigue", fatigue)
    simulate_matchup_from_files(
        away_team="CAL02", home_team="CAL01",
        players_path=CAL / "players.csv", base_dir=CAL,
        park_name="Fenway Park", seed=5, usage_state=state, game_day=3,
    )
    return seen


@pytest.mark.parametrize("auto_rest", [True, False])
def test_in_a_game_only_the_owners_choice_carries_the_full_penalty(auto_rest, monkeypatch):
    seen = _penalties_in_a_game(monkeypatch, auto_rest)
    penalty = seen["penalty"][seen["catcher"]]
    if auto_rest:
        # Auto rest on, no catcher on the bench: he cannot be rested.
        assert 0.0 < penalty <= TUNING.get("batter_blocked_rest_penalty_cap") + 1e-9
    else:
        assert penalty == pytest.approx(TUNING.get("batter_fatigue_penalty_cap"))


# --- finding 5: a hard rest needs real fatigue --------------------------------


def test_ordinary_fatigue_is_not_a_hard_rest():
    state = UsageState()
    state.batter_workload_for("s").fatigue_debt = 0.95 * THRESHOLD
    report: dict = {}
    lineup, _bench, _pos = _rest([_b("s", "2B")], [_b("ss", "SS")], {"s": "2B"}, state,
                                 report=report)
    assert lineup[0].player_id == "s" and report["blocked"] == 1


def test_heavy_fatigue_is_a_hard_rest():
    state = UsageState()
    hard = TUNING.get("batter_rest_hard_ratio")
    state.batter_workload_for("s").fatigue_debt = (hard + 0.05) * THRESHOLD
    lineup, _bench, pos = _rest([_b("s", "2B")], [_b("ss", "SS")], {"s": "2B"}, state)
    assert lineup[0].player_id == "ss" and pos["ss"] == "2B"


# --- finding 9: the injury model's fatigue scale --------------------------------


def test_the_engine_stamps_fatigue_level_on_the_injury_models_scale():
    from physics_sim.arm_injury import batter_fatigue_level

    cap = TUNING.get("batter_fatigue_penalty_cap")
    state = UsageState()
    state.batter_workload_for("a").fatigue_debt = 1.2 * THRESHOLD
    state.batter_workload_for("b").fatigue_debt = _ceiling()
    out = _apply_batter_fatigue(
        [_b("a", "1B"), _b("b", "C"), _b("f", "LF")], usage_state=state, game_day=9,
        tuning=TUNING, blocked_ids={"b"},
    )
    a, b, fresh = out
    assert a.fatigue_level == pytest.approx(a.fatigue_penalty / cap)
    assert batter_fatigue_level(a, TUNING) == pytest.approx(a.fatigue_penalty / cap)
    low = TUNING.get("batter_blocked_rest_penalty_cap")
    assert b.fatigue_level == pytest.approx(low / cap)  # risk follows the applied penalty
    assert batter_fatigue_level(fresh, TUNING) == 0.0


# --- finding 10: due / capped tallies ------------------------------------------


def test_due_counts_every_due_rest_and_capped_counts_past_the_swap_cap():
    state = UsageState()
    lineup = [_b("a", "LF"), _b("b", "RF"), _b("c", "1B")]
    for pid in ("a", "b", "c"):
        state.batter_workload_for(pid).fatigue_debt = 0.95 * THRESHOLD
    bench = [_b("a2", "LF"), _b("b2", "RF"), _b("c2", "1B")]
    report: dict = {}
    _rest(lineup, bench, {"a": "LF", "b": "RF", "c": "1B"}, state, report=report)
    assert int(TUNING.get("batter_rest_max_swaps")) == 2
    assert report["due"] == 3 and report["rests"] == 2 and report["capped"] == 1


# --- CPU roster upkeep (findings 3, 6) ------------------------------------------


def _hp(pid, pos, score=50, injured=False, other=()):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=list(other), injured=injured,
        is_pitcher=(pos == "P"), ch=score, ph=score, first_name=pid, last_name="",
    )


def _club(hitters, *, aaa=(), low=(), dl=()):
    """``hitters``: (pid, pos, score[, injured]) on ACT plus 13 pitchers."""
    players, act = {}, []
    for spec in hitters:
        pid, pos, score = spec[:3]
        injured = spec[3] if len(spec) > 3 else False
        players[pid] = _hp(pid, pos, score=score, injured=injured)
        act.append(pid)
    for i in range(MAX_ACTIVE_PITCHERS):
        players[f"p{i}"] = _hp(f"p{i}", "P", score=55)
        act.append(f"p{i}")
    for pid, pos, score in list(aaa) + list(low) + list(dl):
        players[pid] = _hp(pid, pos, score=score)
    roster = Roster(
        "CPU", act=act, aaa=[a[0] for a in aaa], low=[x[0] for x in low], dl=[d[0] for d in dl]
    )
    return players, roster


_FULL_NINE = [
    ("c1", "C", 60), ("b1", "1B", 70), ("b2", "2B", 62), ("b3", "3B", 64),
    ("ss", "SS", 61), ("lf", "LF", 66), ("cf", "CF", 63), ("rf", "RF", 65),
]


def _upkeep(players, roster, **kw):
    from services.roster_fill import maintain_cpu_active_roster

    return maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE, **kw
    )


def test_a_day_to_day_catcher_still_counts_no_third_catcher_is_called_up():
    hitters = _FULL_NINE + [
        ("c2", "C", 40, True), ("bss", "SS", 45), ("bcf", "CF", 46),
        ("dh", "1B", 55), ("x", "LF", 50),
    ]
    players, roster = _club(hitters, aaa=[("mC", "C", 30)])
    moves = _upkeep(players, roster)
    assert ("mC", "aaa", "act") not in moves
    assert "mC" in roster.aaa


def test_a_third_healthy_catcher_is_trimmed():
    hitters = _FULL_NINE + [
        ("c2", "C", 40), ("c3", "C", 35), ("bss", "SS", 45), ("bcf", "CF", 46),
        ("dh", "1B", 55),
    ]
    players, roster = _club(hitters, aaa=[("mLF", "LF", 52)])
    moves = _upkeep(players, roster)
    assert ("c3", "act", "aaa") in moves
    assert sum(1 for pid in roster.act if is_catcher(players[pid])) == MIN_ACTIVE_CATCHERS
    hitters_now = [pid for pid in roster.act if not counts_as_pitcher(players[pid])]
    assert len(hitters_now) == ACT_HITTER_TARGET and "c3" not in roster.act


def test_a_third_catcher_is_not_trimmed_past_an_option_veto():
    hitters = _FULL_NINE + [
        ("c2", "C", 40), ("c3", "C", 35), ("bss", "SS", 45), ("bcf", "CF", 46),
        ("dh", "1B", 55),
    ]
    players, roster = _club(hitters, aaa=[("mLF", "LF", 52)])
    _upkeep(players, roster, option_allowed=lambda pid: pid != "c3")
    assert "c3" in roster.act


def test_a_catcher_call_up_never_options_the_backup_shortstop():
    # The backup SS is the weakest hitter; the call-up must take someone else.
    hitters = _FULL_NINE + [
        ("bss", "SS", 30), ("bcf", "CF", 46), ("dh", "1B", 55), ("x", "LF", 40),
        ("y", "RF", 41),
    ]
    players, roster = _club(hitters, aaa=[("mC", "C", 30)])
    moves = _upkeep(players, roster)
    assert ("mC", "aaa", "act") in moves
    assert "bss" in roster.act and "bcf" in roster.act
    assert ("x", "act", "aaa") in moves


def test_a_catcher_call_up_never_options_the_last_player_at_a_position():
    # The weakest hitters are the only 2B, 3B and LF and the spare SS / CF;
    # the next weakest, a second first baseman, goes.
    regulars = [h for h in _FULL_NINE if h[1] not in {"2B", "3B", "LF"}]
    hitters = regulars + [
        ("b2b", "2B", 20), ("b3b", "3B", 21), ("blf", "LF", 22), ("bss", "SS", 30),
        ("bcf", "CF", 31), ("dh1", "1B", 50), ("dh2", "RF", 51), ("dh3", "1B", 52),
    ]
    players, roster = _club(hitters, aaa=[("mC", "C", 30)])
    moves = _upkeep(players, roster)
    assert ("mC", "aaa", "act") in moves
    assert ("dh1", "act", "aaa") in moves
    for protected in ("b2b", "b3b", "blf", "bss", "bcf"):
        assert protected in roster.act


def test_a_catcher_call_up_never_options_an_injury_cover(monkeypatch):
    import services.injury_replacements as replacements

    hitters = _FULL_NINE + [
        ("bss", "SS", 45), ("bcf", "CF", 46), ("dh", "1B", 55), ("cov", "LF", 30),
        ("y", "RF", 41),
    ]
    players, roster = _club(hitters, aaa=[("mC", "C", 30)], dl=[("hurt", "LF", 70)])
    monkeypatch.setattr(
        replacements, "_load",
        lambda: {"hurt": {"team_id": "CPU", "replacement_id": "cov", "from_level": "low"}},
    )
    moves = _upkeep(players, roster)
    assert ("mC", "aaa", "act") in moves
    assert "cov" in roster.act and ("y", "act", "aaa") in moves


def test_cpu_upkeep_carries_a_spare_shortstop_and_center_fielder_from_its_minors():
    hitters = _FULL_NINE + [
        ("c2", "C", 40), ("dh", "1B", 55), ("x", "LF", 40), ("y", "RF", 41), ("w", "1B", 42),
    ]
    players, roster = _club(
        hitters, aaa=[("mSS", "SS", 35), ("mLF", "LF", 60)], low=[("mCF", "CF", 30)]
    )
    moves = _upkeep(players, roster)
    assert ("mSS", "aaa", "act") in moves and ("mCF", "low", "act") in moves
    assert "x" in roster.aaa and "y" in roster.aaa
    hitters_now = [pid for pid in roster.act if not counts_as_pitcher(players[pid])]
    assert len(hitters_now) == ACT_HITTER_TARGET
    # stable: a second pass changes nothing
    assert _upkeep(players, roster) == []


def test_spare_upkeep_honours_option_vetoes():
    hitters = _FULL_NINE + [
        ("c2", "C", 40), ("dh", "1B", 55), ("x", "LF", 40), ("y", "RF", 41), ("w", "1B", 42),
    ]
    players, roster = _club(hitters, aaa=[("mSS", "SS", 35)])
    before = list(roster.act)
    moves = _upkeep(players, roster, option_allowed=lambda pid: False)
    assert moves == [] and roster.act == before


def test_required_positions_mirror_auto_assign():
    from services.roster_auto_assign import REQUIRED_POSITIONS
    from services.roster_fill import _REQUIRED_POSITIONS

    assert tuple(_REQUIRED_POSITIONS) == tuple(REQUIRED_POSITIONS)


def test_the_daily_upkeep_passes_the_option_rules(monkeypatch):
    import api.routers.season as season

    seen = {}

    def fake(team_id, *a, **k):
        seen.update(k)
        return []

    sentinel = lambda pid: True  # noqa: E731
    monkeypatch.setattr("services.roster_fill.maintain_cpu_active_roster", fake)
    monkeypatch.setattr("services.roster_fill.ensure_fieldable_roster", lambda *a, **k: [])
    monkeypatch.setattr("utils.player_loader.load_players_from_csv", lambda *a, **k: [])
    monkeypatch.setattr("utils.roster_loader.load_roster", lambda tid, *a, **k: Roster(tid))
    monkeypatch.setattr("utils.roster_loader.active_roster_cap", lambda *a, **k: 26)
    monkeypatch.setattr("services.injury_manager._promotion_allowed", lambda tid: None)
    monkeypatch.setattr("services.injury_manager._option_allowed", lambda tid: sentinel)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set()
    )
    sim = SimpleNamespace(schedule=[{"date": "2026-05-01", "home": "AAA", "away": "BBB"}])
    season._prepare_rosters_for_date(sim, "2026-05-01")
    assert seen.get("option_allowed") is sentinel


# --- finding 4: two-catcher protection is for CPU clubs only --------------------


def _send_down_team():
    players, act = {}, []
    for i in range(ACT_HITTER_TARGET + 1):
        pos = "C" if i < 2 else "LF"
        players[f"h{i}"] = _hp(f"h{i}", pos, score=40 if pos == "C" else 60)
        act.append(f"h{i}")
    for i in range(ACTIVE_ROSTER_SIZE - ACT_HITTER_TARGET - 1):
        players[f"p{i}"] = _hp(f"p{i}", "P", score=55)
        act.append(f"p{i}")
    return players, Roster("CPU", act=act)


def test_send_down_protects_a_second_catcher_only_when_asked():
    from services.roster_fill import choose_send_down

    players, roster = _send_down_team()
    assert choose_send_down(roster, players) in {"h0", "h1"}  # owner default: one
    assert choose_send_down(
        roster, players, keep_catchers=MIN_ACTIVE_CATCHERS
    ) not in {"h0", "h1"}


@pytest.mark.parametrize("owner", [True, False])
def test_il_activation_trim_protects_two_catchers_on_cpu_clubs_only(owner, monkeypatch, tmp_path):
    import services.injury_replacements as replacements
    import utils.path_utils as path_utils
    from services import injury_manager as im

    monkeypatch.setattr(path_utils, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(replacements, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.roster_loader.active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE)
    monkeypatch.setattr("utils.roster_loader.active_pitcher_cap", lambda *a, **k: MAX_ACTIVE_PITCHERS)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict",
        lambda *a, **k: ({"CPU"} if owner else set()),
    )
    players = {}
    act = []
    for i in range(ACT_HITTER_TARGET):
        pos = "C" if i < 2 else "LF"
        players[f"h{i}"] = _hp(f"h{i}", pos, score=30 if i == 1 else 60)
        act.append(f"h{i}")
    for i in range(MAX_ACTIVE_PITCHERS):
        players[f"p{i}"] = _hp(f"p{i}", "P", score=55)
        act.append(f"p{i}")
    players["back"] = _hp("back", "LF", score=65)
    for p in players.values():
        p.birthdate = "1995-01-01"
        p.injury_list = None
    roster = Roster("CPU", act=act, dl=["back"])
    monkeypatch.setattr("services.roster_fill.record_roster_moves", lambda *a, **k: None)
    monkeypatch.setattr("services.roster_fill.apply_prospect_bookkeeping", lambda *a, **k: None)
    monkeypatch.setattr(im, "record_roster_level_movements", lambda *a, **k: None)
    im.recover_from_injury(players["back"], roster, "act", force=True, players_by_id=players)
    assert "back" in roster.act
    if owner:
        assert "h1" in roster.aaa     # the weakest hitter, a second catcher or not
    else:
        assert "h1" in roster.act     # a CPU club keeps its two catchers


# --- finding 7: new organisations carry two catchers and a spare SS / CF ---------


def test_a_new_league_gives_every_organisation_two_catchers_and_spares(tmp_path):
    import csv
    import random

    from playbalance.league_creator import create_league
    from services.roster_fill import can_play

    random.seed(3)
    divisions = {"East": [("CityA", "Cats"), ("CityB", "Dogs"), ("CityC", "Owls")]}
    create_league(str(tmp_path), divisions, "Depth League")
    with open(tmp_path / "players.csv", newline="") as fh:
        players = {r["player_id"]: r for r in csv.DictReader(fh)}
    for roster_file in (tmp_path / "rosters").glob("*.csv"):
        if roster_file.stem.endswith("_pitching"):
            continue
        with roster_file.open() as fh:
            rows = [line.strip().split(",") for line in fh if line.strip()]
        act = [
            SimpleNamespace(**{**players[pid], "other_positions": players[pid]["other_positions"]})
            for pid, level in rows if level == "ACT" and players[pid]["is_pitcher"] == "0"
        ]
        assert sum(1 for p in act if is_catcher(p)) >= 2, roster_file.stem
        assert sum(1 for p in act if can_play(p, "SS")) >= 2, roster_file.stem
        assert sum(1 for p in act if can_play(p, "CF")) >= 2, roster_file.stem


# --- finding 8: the real cost, in words -----------------------------------------


def test_the_one_catcher_warning_states_the_cost():
    from services.roster_validation import validate_catcher_depth

    result = validate_catcher_depth(["c"], {"c": {"primary_position": "C"}})
    text = " ".join(result.warnings).lower()
    assert "tires" in text and "worse" in text and "backup" in text


def test_the_rest_tutorial_says_a_rest_day_needs_a_backup():
    import services.tutorials as tutorials

    source = Path(tutorials.__file__).read_text(encoding="utf-8")
    assert "only one catcher" in source and "a little worse" in source


# --- the streak counts team games, not calendar days (A's calendar clock) --------


def _streak_after(game_days, *, position="C"):
    state = UsageState()
    player = _b("r", position)
    for day in game_days:
        state.advance_day(day=day, pitchers=[], batters=[player], tuning=TUNING)
        state.record_batter_game(
            player_id="r", day=day, durability=50, tuning=TUNING, position=position
        )
    return state


def test_a_team_off_day_does_not_reset_the_streak():
    """Under the calendar-day clock every weekly off day zeroed the streak,
    so the 13-game backstop never fired and 208 calibration regulars started
    all 162 games. A team off day is not a rest; sitting a team game is."""

    state = _streak_after([0, 1, 3], position="C")  # day 2: no game
    wl = state.batter_workload_for("r")
    assert wl.games_in_a_row == 3
    assert wl.consecutive_days_used == 1  # the calendar count (item A) is unchanged
    lineup, _bench, _pos = _rest([_b("r", "C")], [_b("c2", "C")], {"r": "C"}, state, day=4)
    assert lineup[0].player_id == "c2"  # his 4th straight game: rests
    # Thirteen straight team games over two weeks with weekly off days.
    days = [d for d in range(16) if d % 7 != 6][:13]
    state = _streak_after(days, position="LF")
    assert state.batter_workload_for("r").games_in_a_row == 13


def test_sitting_a_team_game_resets_the_streak():
    state = _streak_after([0, 1, 2], position="C")
    sitter = _b("r", "C")
    state.advance_day(day=3, pitchers=[], batters=[sitter], tuning=TUNING)  # he sat
    state.advance_day(day=5, pitchers=[], batters=[sitter], tuning=TUNING)
    assert state.batter_workload_for("r").games_in_a_row == 0
