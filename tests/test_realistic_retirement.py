"""Backlog #52a (8.6.5): retirement by an age curve, scaled by quality.

The old fixed (age, OVR) bars were out of reach of engine-scale overalls, so
every big leaguer of 38+ and every AAA player of 32+ retired whatever his
quality, and unsigned free agents never retired. Each player now has a
yearly chance that climbs with age, scaled by his rank at his level in his
own league, drawn from his id and the season; free agents are included.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services import player_retirement as pr


def test_nobody_retires_before_the_curve_starts():
    assert pr.retirement_chance(30, "ACT") == 0.0
    assert pr.retirement_chance(26, "AAA") == 0.0
    assert pr.retirement_chance(21, "LOW") == 0.0
    assert pr.retirement_chance(28, pr.NEW_FREE_AGENT) == 0.0


def test_the_chance_climbs_with_age():
    chances = [pr.retirement_chance(age, "ACT") for age in range(31, 47)]
    assert chances == sorted(chances)
    assert chances[0] < 0.05
    assert pr.retirement_chance(39, "ACT") == pytest.approx(0.5)
    assert pr.retirement_chance(46, "ACT") > 0.9


def test_the_injured_lists_are_big_leaguers():
    for level in ("DL", "IR"):
        assert pr.retirement_chance(37, level) == pr.retirement_chance(37, "ACT")


def test_the_minors_and_free_agency_age_faster():
    act = pr.retirement_chance(32, "ACT")
    assert pr.retirement_chance(32, "AAA") > act
    assert pr.retirement_chance(32, pr.NEW_FREE_AGENT) > act
    assert pr.retirement_chance(27, "LOW") > 0.0


def test_a_better_player_is_less_likely_to_retire():
    star, average, fringe = (pr.retirement_chance(37, "ACT", p) for p in (0.95, 0.5, 0.05))
    assert star < average < fringe
    assert star < average / 2
    assert fringe > average * 2


def test_a_multi_year_contract_keeps_a_player_a_little_longer():
    assert pr.retirement_chance(36, "ACT", multi_year_contract=True) < pr.retirement_chance(36, "ACT")


def test_a_free_agent_unsigned_all_season_often_quits_at_any_age():
    assert pr.retirement_chance(24, pr.FREE_AGENT) >= 0.25
    assert pr.retirement_chance(24, pr.FREE_AGENT, 0.05) > pr.retirement_chance(24, pr.FREE_AGENT, 0.95)
    # One whose contract just ran out is judged by age.
    assert pr.retirement_chance(24, pr.NEW_FREE_AGENT) == 0.0


def test_percentiles_rank_each_level_against_itself():
    scores = {f"A{i}": ("ACT", 50.0 + i) for i in range(10)}
    scores.update({f"M{i}": ("AAA", 40.0 + i) for i in range(10)})
    scores["D"] = ("DL", 59.5)
    scores["F"] = (pr.FREE_AGENT, 54.5)
    scores["N"] = ("ACT", None)
    ranks = pr.level_percentiles(scores)
    assert ranks["A9"] > ranks["A0"]
    # The best AAA player ranks at the top of AAA, not against big leaguers.
    assert ranks["M9"] > 0.9
    # The injured list is ranked with the big leaguers; a free agent is
    # placed among them without joining the pool.
    assert ranks["D"] > ranks["A8"]
    assert 0.4 < ranks["F"] < 0.6
    assert ranks["N"] == 0.5


def test_a_tiny_level_counts_everyone_as_average():
    ranks = pr.level_percentiles({"L0": ("LOW", 30.0), "L1": ("LOW", 60.0)})
    assert ranks == {"L0": 0.5, "L1": 0.5}


def test_the_roll_is_fixed_by_player_and_season():
    player = SimpleNamespace(player_id="P1")
    first = [pr.should_retire(player, season_year=y, age=38, level="ACT") for y in range(2027, 2047)]
    again = [pr.should_retire(player, season_year=y, age=38, level="ACT") for y in range(2027, 2047)]
    assert first == again
    # About half of 38-year-old average big leaguers retire in a year; across
    # twenty seasons this player sees both outcomes.
    assert any(first) and not all(first)


def test_a_star_can_retire_and_reasons_follow_quality():
    assert pr._reason("ACT", 37, 0.9) == "goes out on top"
    assert pr._reason("ACT", 41, 0.5) == "can't keep up"
    assert pr._reason("ACT", 35, 0.1) == "washed"
    assert pr._reason("ACT", 35, 0.5) == "declining"
    assert pr._reason("AAA", 33, 0.5) == "career minor leaguer"
    assert pr._reason("LOW", 27, 0.5) == "prospect washout"
    assert pr._reason(pr.FREE_AGENT, 36, 0.5) == "unsigned"


# ---------------------------------------------------------------------------
# The yearly sweep on a league
# ---------------------------------------------------------------------------
HEADER = (
    "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,"
    "other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
)


def _row(pid: str, first: str, born: int) -> str:
    return f"{pid},{first},{pid},{born}-01-01,72,190,R,LF,,50,55,55,50,55,55,55,55,55,56,0"


@pytest.fixture
def league(tmp_path, monkeypatch):
    """BBB carries 20 young and 20 45-year-old big leaguers; 20 old and 20
    young free agents are unsigned; OLDC is 45, under contract with BBB on
    no roster file; GONE retired years ago."""

    data = tmp_path / "league"
    (data / "rosters").mkdir(parents=True)
    rows, roster = [], []
    for i in range(20):
        rows.append(_row(f"Y{i}", "Young", 2002))
        rows.append(_row(f"O{i}", "Old", 1982))
        rows.append(_row(f"FO{i}", "Free", 1982))
        rows.append(_row(f"FY{i}", "Free", 2003))
        roster += [f"Y{i},ACT", f"O{i},ACT"]
    rows += [_row("OLDC", "Old", 1982), _row("GONE", "Long", 1980)]
    (data / "players.csv").write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    (data / "rosters" / "BBB.csv").write_text("\n".join(roster) + "\n", encoding="utf-8")
    (data / "contracts.json").write_text(json.dumps({"version": 1, "players": {
        "OLDC": {"team_id": "BBB", "years_left": 2, "annual_salary": 1_000_000},
        **{f"O{i}": {"team_id": "BBB", "years_left": 1, "annual_salary": 1_000_000} for i in range(20)},
    }}), encoding="utf-8")
    pr.save_retirees({"GONE": {"retired_year": 2020}}, data_dir=data)
    # Ages from the birth year, as of the 2027 rollover.
    monkeypatch.setattr(pr, "calculate_age", lambda bd: 2027 - int(str(bd)[:4]))
    released: list = []
    import services.contracts_service as cs

    monkeypatch.setattr(
        cs, "release_contracts_to_free_agency",
        lambda ids, **k: released.extend(ids),
    )
    monkeypatch.setattr(pr, "_scrub_rosters", lambda *a, **k: None)
    return data, released


def test_old_players_and_old_free_agents_retire_young_ones_play_on(league):
    data, released = league
    summary = pr.run_yearly_retirements(season_year=2027, data_dir=data)
    gone = {r["player_id"]: r for r in summary["retirees"]}
    assert not any(pid.startswith("Y") for pid in gone)
    assert sum(pid.startswith("O") for pid in gone) >= 15
    assert sum(pid.startswith("FO") for pid in gone) >= 15
    # Unsigned all season: some of the young ones quit as well.
    assert 0 < sum(pid.startswith("FY") for pid in gone) < 20
    # A contract on no roster file keeps the player his club's; a retiree
    # is not judged again.
    assert "OLDC" not in gone and "GONE" not in gone
    assert all(gone[pid]["level"] == pr.FREE_AGENT for pid in gone if pid.startswith("F"))
    # Only the signed retirees' contracts are released.
    assert set(released) == {pid for pid in gone if pid.startswith("O")}
    registry = pr.load_retirees(data)
    assert set(gone) <= set(registry) and registry["GONE"] == {"retired_year": 2020}


def test_a_contract_that_just_ran_out_is_judged_by_age(league):
    data, _ = league
    young = [f"FY{i}" for i in range(20)]
    summary = pr.run_yearly_retirements(season_year=2027, data_dir=data, new_free_agents=young)
    assert not any(r["player_id"].startswith("FY") for r in summary["retirees"])


def test_the_same_offseason_retires_the_same_players(league, tmp_path):
    import shutil

    data, _ = league
    copy = tmp_path / "copy"
    shutil.copytree(data, copy)
    first = {r["player_id"] for r in pr.run_yearly_retirements(season_year=2027, data_dir=data)["retirees"]}
    second = {r["player_id"] for r in pr.run_yearly_retirements(season_year=2027, data_dir=copy)["retirees"]}
    assert first == second


def test_a_new_free_agent_who_retires_is_his_old_clubs_retiree(tmp_path):
    from services.offseason_departures import load_departures, record_departures

    (tmp_path / "players.csv").write_text(HEADER, encoding="utf-8")
    record_departures(
        2027,
        data_dir=tmp_path,
        expiring={"P1": "BAL", "P2": "BAL"},
        expired_ids=["P1", "P2"],
        retirees=[{"player_id": "P1", "team_id": "", "first_name": "Old",
                   "last_name": "Vet", "primary_position": "SS", "age": 37}],
    )
    dep = load_departures("BAL", data_dir=tmp_path)
    assert [p["name"] for p in dep["retired"]] == ["Old Vet"]
    assert [p["player_id"] for p in dep["contract_expired"]] == ["P2"]


def test_an_open_offer_on_a_retired_free_agent_closes(tmp_path):
    import services.fa_negotiations as neg

    (tmp_path / "rosters").mkdir()
    pr.save_retirees({"P9": {"retired_year": 2027}}, data_dir=tmp_path)
    neg.save_negotiations({"negotiations": {
        "P9": {"player_id": "P9", "status": "open", "deadline_date": "2026-01-01",
               "offers": [{"team_id": "AAA", "annual_salary": 9_000_000, "years": 2}]},
    }}, data_dir=tmp_path)
    calls = []
    summary = neg.process_negotiations(
        "2027-01-05", data_dir=tmp_path, sign_fn=lambda **k: calls.append(k) or True
    )
    assert calls == []
    assert summary["retired"] == ["P9"]
    state = neg.load_negotiations(data_dir=tmp_path)["negotiations"]["P9"]
    assert state["resolution"]["outcome"] == "retired"
