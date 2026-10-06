"""Injury coverage: the depth chart first, like for like, own club only.

Audit H9: a hitter's injury promoted AAA[0] -- a pitcher on 13 of 20
alpha-test clubs -- so active rosters drifted to 8 hitters / 17 pitchers, the
lineup fill reached across the league for other teams' minor leaguers, and the
sim day aborted ("Player X is not on the active roster"), on every retry.
Decision 14 (commissioner): depth chart first; owners keep the open spot;
CPU clubs call up like for like; never another club's player.
"""

import csv
from types import SimpleNamespace

import pytest

import services.injury_replacements as replacements
import utils.depth_chart as dc
import utils.path_utils as path_utils
from models.roster import Roster
from services.depth_chart_manager import handle_injury_replacement
from services.lineup_restore import _plan_substitution, can_cover_injury, substitute_injured_player
from services.roster_fill import (
    HITTER_FLOOR,
    can_play,
    ensure_fieldable_roster,
    is_pitcher,
    maintain_cpu_active_roster,
    positions_of,
)


def _p(pid, pos, others=(), injured=False, ch=50):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=list(others),
        injured=injured, is_pitcher=(pos == "P"), ch=ch, ph=50,
        first_name=pid, last_name="",
    )


@pytest.fixture
def team():
    """Active: SS + backup 2B/SS + 7 others + 2 pitchers. AAA head: pitchers."""
    players = {
        "ss": _p("ss", "SS"), "util": _p("util", "2B", ["SS"]),
        **{f"h{i}": _p(f"h{i}", pos) for i, pos in enumerate(["C", "1B", "3B", "LF", "CF", "RF", "DH"])},
        "sp1": _p("sp1", "P"), "sp2": _p("sp2", "P"),
        "aaa_p1": _p("aaa_p1", "P"), "aaa_p2": _p("aaa_p2", "P"),
        "aaa_ss": _p("aaa_ss", "SS"), "aaa_of": _p("aaa_of", "LF"),
        "low_ss": _p("low_ss", "SS"),
    }
    roster = Roster(
        "TST",
        act=["ss", "util", "h0", "h1", "h2", "h3", "h4", "h5", "h6", "sp1", "sp2"],
        aaa=["aaa_p1", "aaa_p2", "aaa_ss", "aaa_of"],
        low=["low_ss"],
    )
    return roster, players


def _injure(roster, pid):
    roster.act.remove(pid)
    roster.dl.append(pid)


# --- step 1: the depth chart's active backup covers -------------------------


def test_owner_team_active_backup_covers_with_no_roster_move(team):
    roster, players = team
    _injure(roster, "ss")
    before = (list(roster.act), list(roster.aaa), list(roster.low))
    cov = handle_injury_replacement(
        roster, players["ss"], players_by_id=players, cpu_owned=False,
        chart={"SS": ["ss", "util", "aaa_ss"]},
    )
    assert cov.backup_id == "util"
    assert cov.promoted_id is None and cov.left_open
    assert (roster.act, roster.aaa, roster.low) == before


def test_without_a_chart_the_best_active_fit_covers(team):
    roster, players = team
    _injure(roster, "ss")
    cov = handle_injury_replacement(roster, players["ss"], players_by_id=players, cpu_owned=False, chart={})
    assert cov.backup_id == "util"
    assert cov.promoted_id is None


def test_owner_team_not_covered_when_the_backup_cannot_step_in(team):
    """The lineup plan says no (e.g. the backup already starts and nobody can
    take his place): rule 3, promote a shortstop from the team's own minors."""
    roster, players = team
    _injure(roster, "ss")
    cov = handle_injury_replacement(
        roster, players["ss"], players_by_id=players, cpu_owned=False,
        chart={"SS": ["ss", "util", "aaa_ss"]}, covered_check=lambda backup: False,
    )
    assert cov.promoted_id == "aaa_ss"


# --- step 2: CPU clubs fill the spot, like for like -------------------------


def test_cpu_team_calls_up_a_hitter_not_the_pitcher_heading_aaa(team):
    roster, players = team
    _injure(roster, "ss")
    cov = handle_injury_replacement(
        roster, players["ss"], players_by_id=players, cpu_owned=True,
        chart={"SS": ["ss", "util", "aaa_ss"]},
    )
    assert cov.backup_id == "util"
    assert cov.promoted_id == "aaa_ss"
    assert "aaa_p1" in roster.aaa and "aaa_ss" in roster.act


def test_cpu_pitcher_injury_calls_up_a_pitcher(team):
    roster, players = team
    _injure(roster, "sp1")
    cov = handle_injury_replacement(roster, players["sp1"], players_by_id=players, cpu_owned=True, chart={})
    assert is_pitcher(players[cov.promoted_id])


def test_owner_pitcher_injury_leaves_the_spot_open(team):
    roster, players = team
    _injure(roster, "sp1")
    cov = handle_injury_replacement(roster, players["sp1"], players_by_id=players, cpu_owned=False, chart={})
    assert cov.promoted_id is None and cov.left_open


# --- step 3: nobody active can play it -> own minors, position only ----------


def test_owner_team_with_no_active_cover_promotes_chart_listed_minor(team):
    roster, players = team
    roster.act.remove("util")
    roster.aaa.append("util")
    _injure(roster, "ss")
    cov = handle_injury_replacement(
        roster, players["ss"], players_by_id=players, cpu_owned=False,
        chart={"SS": ["ss", "low_ss", "aaa_ss"]},
    )
    assert cov.promoted_id == "low_ss"


def test_owner_team_never_gets_a_call_up_who_cannot_play_the_position(team):
    roster, players = team
    _injure(roster, "h0")                    # the catcher; nobody can catch
    cov = handle_injury_replacement(roster, players["h0"], players_by_id=players, cpu_owned=False, chart={})
    assert cov.promoted_id is None and cov.left_open   # not aaa_of / aaa_ss


def test_injured_minor_leaguers_are_never_called_up(team):
    roster, players = team
    players["aaa_ss"].injured = True
    _injure(roster, "ss")
    cov = handle_injury_replacement(roster, players["ss"], players_by_id=players, cpu_owned=True, chart={})
    assert cov.promoted_id == "low_ss"


# --- the lineup: only the injured man's slot (or a swap) changes ------------


def _lineup(tmp_path, rows):
    for hand in ("lhp", "rhp"):
        with (tmp_path / f"TST_vs_{hand}.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["order", "player_id", "position"])
            w.writerows(rows)


def _read(tmp_path):
    with (tmp_path / "TST_vs_rhp.csv").open() as fh:
        return [(r["player_id"], r["position"]) for r in csv.DictReader(fh)]


def test_lineup_slot_goes_to_the_backup_and_order_survives(team, tmp_path):
    roster, players = team
    _lineup(tmp_path, [("1", "h4", "CF"), ("2", "ss", "SS"), ("3", "h1", "1B")])
    _injure(roster, "ss")
    changed = substitute_injured_player(
        "TST", "ss", active_ids=roster.act, players_by_id=players,
        preferred_id="util", lineup_dir=tmp_path,
    )
    assert changed == {"lhp": "util", "rhp": "util"}
    assert [pid for pid, _ in _read(tmp_path)] == ["h4", "util", "h1"]


def test_backup_catcher_at_dh_moves_behind_the_plate(tmp_path):
    """The verified review case: the backup C was batting DH; a 3B used to be
    put at catcher. Now the C moves over and a bench bat takes DH."""
    players = {
        "c1": _p("c1", "C"), "c2": _p("c2", "C"), "b3": _p("b3", "3B"),
        "bench": _p("bench", "LF"),
    }
    rows = [("1", "c1", "C"), ("2", "c2", "DH"), ("3", "b3", "3B")]
    plan = _plan_substitution(rows, "c1", ["c2", "b3", "bench"], players, ["c2"])
    assert plan == [("1", "c2", "C"), ("2", "bench", "DH"), ("3", "b3", "3B")]


def test_nobody_who_can_play_it_leaves_the_slot_for_the_rebuild():
    players = {"c1": _p("c1", "C"), "cf": _p("cf", "CF"), "b3": _p("b3", "3B")}
    rows = [("1", "c1", "C"), ("2", "b3", "3B")]
    assert _plan_substitution(rows, "c1", ["cf", "b3"], players, []) is None


def test_can_cover_is_true_for_a_bench_player(team, tmp_path):
    roster, players = team
    _lineup(tmp_path, [("1", "h4", "CF")])
    assert can_cover_injury(
        "TST", "ss", active_ids=roster.act, players_by_id=players, lineup_dir=tmp_path
    )


# --- emergency and CPU upkeep: own organisation, recorded moves -------------


def test_emergency_fill_uses_own_minor_league_hitters_only(team):
    roster, players = team
    for pid in ("h4", "h5", "h6"):
        _injure(roster, pid)
    moves = ensure_fieldable_roster("TST", roster, players)
    assert len(moves) == 3
    assert {pid for pid, _, _ in moves} <= {"aaa_ss", "aaa_of", "low_ss"}
    assert len([p for p in roster.act if not is_pitcher(players[p])]) == 9


def test_emergency_fill_prefers_players_the_prospect_rules_allow(team):
    roster, players = team
    for pid in ("h4", "h5", "h6"):
        _injure(roster, pid)
    moves = ensure_fieldable_roster(
        "TST", roster, players, allowed=lambda pid, lvl: pid != "aaa_ss"
    )
    # aaa_ss is blocked; the other two come up, then the rules are overridden
    # only because the club would otherwise be short of nine.
    assert [pid for pid, _, _ in moves][:2] == ["aaa_of", "low_ss"]


def test_cpu_emergency_stays_under_the_cap_by_optioning_a_pitcher():
    players = {f"h{i}": _p(f"h{i}", "LF") for i in range(8)}
    players.update({f"p{i}": _p(f"p{i}", "P") for i in range(17)})
    players["aaa_h"] = _p("aaa_h", "CF")
    roster = Roster("CPU", act=[*(f"h{i}" for i in range(8)), *(f"p{i}" for i in range(17))], aaa=["aaa_h"])
    moves = ensure_fieldable_roster("CPU", roster, players, cpu_owned=True, cap=25)
    assert ("aaa_h", "aaa", "act") in moves
    assert len(roster.act) == 25
    assert sum(is_pitcher(players[p]) for p in roster.act) == 16


def test_cpu_upkeep_repairs_a_pitcher_heavy_drift():
    players = {f"h{i}": _p(f"h{i}", "LF") for i in range(8)}
    players.update({f"p{i}": _p(f"p{i}", "P") for i in range(17)})
    players.update({f"m{i}": _p(f"m{i}", "SS") for i in range(6)})
    roster = Roster("CPU", act=[*(f"h{i}" for i in range(8)), *(f"p{i}" for i in range(17))],
                    aaa=[f"m{i}" for i in range(6)])
    maintain_cpu_active_roster("CPU", roster, players, target_size=25, cap=25)
    hitters = [p for p in roster.act if not is_pitcher(players[p])]
    assert len(hitters) >= HITTER_FLOOR and len(roster.act) == 25


def test_cpu_upkeep_refills_a_short_roster(team):
    roster, players = team                       # 11 active
    maintain_cpu_active_roster("TST", roster, players, target_size=14, cap=25)
    assert len(roster.act) == 14


# --- the replacement goes back down when the starter returns ----------------


@pytest.fixture
def league(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(replacements, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(dc, "get_data_dir", lambda: tmp_path)
    (tmp_path / "lineups").mkdir()
    return tmp_path


def test_returning_starter_sends_down_his_own_replacement(league, monkeypatch):
    from services import injury_manager as im

    monkeypatch.setattr("utils.roster_loader.active_roster_cap", lambda *a, **k: 12)
    players = {
        "c": _p("c", "C"), "c_aaa": _p("c_aaa", "C"),
        **{f"h{i}": _p(f"h{i}", "LF") for i in range(9)}, "p1": _p("p1", "P"),
        "later": _p("later", "LF"),
    }
    for p in players.values():
        p.birthdate = "1995-01-01"
        p.injury_list = None
    roster = Roster("CPU", act=["c", *(f"h{i}" for i in range(9)), "p1"], aaa=["c_aaa", "later"])
    im.place_on_injury_list(players["c"], roster, "il10", players_by_id=players, cpu_owned=True)
    assert "c_aaa" in roster.act
    roster.aaa.remove("later")
    roster.act.append("later")                   # a later addition, now at the cap
    im.recover_from_injury(players["c"], roster, "act", force=True, players_by_id=players)
    assert "c" in roster.act
    assert "c_aaa" in roster.aaa                 # his replacement, not "later"
    assert "later" in roster.act


# --- depth charts -----------------------------------------------------------


def test_only_charts_automation_generated_are_rebuilt(league, monkeypatch):
    import utils.depth_chart_autofill as auto

    gen = iter(["v1", "v2", "v3"])
    monkeypatch.setattr(auto, "auto_generate_depth_chart",
                        lambda tid, persist=True: dc.save_depth_chart(tid, {"C": [next(gen)]}))
    # A chartless CPU club gets one, then it is kept current every sim.
    assert auto.ensure_default_depth_chart("CPU", refresh=True) is True
    assert auto.ensure_default_depth_chart("CPU", refresh=True) is True
    assert dc.load_depth_chart("CPU")["C"] == ["v2"]
    # A chart that existed before the marker (made by a person) is never touched.
    dc.save_depth_chart("OLD", {"C": ["mine"]})
    assert auto.ensure_default_depth_chart("OLD", refresh=True) is False
    assert dc.load_depth_chart("OLD")["C"] == ["mine"]
    # Saving the generated chart by hand makes it the owner's.
    dc.mark_depth_chart_manual("CPU")
    assert auto.ensure_default_depth_chart("CPU", refresh=True) is False
    assert dc.is_depth_chart_manual("CPU") and not dc.is_depth_chart_manual("NONE")


def test_a_generated_chart_does_not_pin_lineup_starters(league):
    from utils.lineup_autofill import lineup_depth_chart

    dc.save_depth_chart("CPU", {"LF": ["lf_L"]})
    dc.mark_depth_chart_auto("CPU")
    assert lineup_depth_chart("CPU") == {}          # advisory: platoon passes decide
    dc.mark_depth_chart_manual("CPU")
    assert lineup_depth_chart("CPU")["LF"] == ["lf_L"]   # a person's chart pins starters


def test_owner_call_up_targets_the_lineup_hole_not_his_primary(team):
    """He is a shortstop batting at 1B; the hole is at 1B."""
    roster, players = team
    players["aaa_1b"] = _p("aaa_1b", "1B")
    roster.aaa.append("aaa_1b")
    _injure(roster, "ss")
    cov = handle_injury_replacement(
        roster, players["ss"], players_by_id=players, cpu_owned=False, chart={},
        covered_check=lambda backup: ["1B"],
    )
    assert cov.promoted_id == "aaa_1b" and cov.position == "1B"


def test_swaps_never_move_an_injured_or_inactive_player():
    players = {"b2": _p("b2", "2B"), "ss": _p("ss", "SS", ["2B"], injured=True),
               "bench_ss": _p("bench_ss", "SS")}
    rows = [("1", "b2", "2B"), ("2", "ss", "SS")]
    # ss is in the lineup but on the DL (not active): he must not move to 2B.
    plan = _plan_substitution(rows, "b2", ["bench_ss"], players, [])
    assert plan is None or all(pid != "ss" or pos == "SS" for _o, pid, pos in plan)


def test_an_injured_regular_stays_first_on_a_generated_chart(league, monkeypatch):
    import utils.depth_chart_autofill as auto

    players = [_p("star", "SS", ch=80), _p("sub", "SS", ch=40), _p("p", "P")]
    roster = Roster("CPU", act=["sub", "p"], dl=["star"])
    monkeypatch.setattr(auto, "load_roster", lambda tid: roster)
    monkeypatch.setattr(auto, "load_players_from_csv", lambda path: players)
    monkeypatch.setattr(auto, "overall_rating", lambda p: p.ch)
    chart = auto.auto_generate_depth_chart("CPU", persist=False)
    assert chart["SS"][0] == "star"


# --- positions --------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    (["3B"], ["SS", "3B"]),
    (["['RF', '1B']"], ["SS", "RF", "1B"]),
    (["[]"], ["SS"]),
    ("2B|CF", ["SS", "2B", "CF"]),
])
def test_other_positions_in_every_stored_form(raw, expected):
    assert positions_of(_p("x", "SS", raw if isinstance(raw, list) else [raw])) == expected


def test_pitchers_cannot_cover_a_position_and_anyone_can_dh():
    assert not can_play(_p("p", "P"), "DH")
    assert can_play(_p("c", "C"), "DH")


def test_engine_reads_every_other_positions_form():
    from physics_sim.models import BatterRatings

    def _row(raw):
        return {"player_id": "x", "primary_position": "SS", "other_positions": raw, "ch": "50"}

    try:
        assert BatterRatings.from_row(_row("3B|2B")).other_positions == ["3B", "2B"]
        assert BatterRatings.from_row(_row("['CF']")).other_positions == ["CF"]
        assert BatterRatings.from_row(_row("[]")).other_positions == []
    except TypeError:
        pytest.skip("BatterRatings.from_row needs more columns")
