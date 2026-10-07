"""Review fixes for the 26-man CPU roster automation (decision 8, 7.46.0).

Each test reproduces a reviewer finding (B1-B10): owner clubs moved by the
yearly promotions or the CPU free-agent market, a full CPU club stalling a
negotiation, the September revert optioning the only healthy catcher or
overfilling AAA, and CPU trims that sent down the wrong type of player.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from models.roster import Roster
from utils.roster_rules import (
    AAA_CAP,
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    LOW_CAP,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    counts_as_pitcher,
)

_YOUNG = f"{date.today().year - 21}-01-01"
_OLD = f"{date.today().year - 31}-01-01"


def _p(pid, pos="LF", score=50, **kw):
    data = dict(
        player_id=pid, primary_position=pos, other_positions=[], injured=False,
        is_pitcher=(pos == "P"), ch=score, ph=score, sp=score, fa=score, arm=score,
        eye=score, control=score, movement=score, endurance=score,
        first_name=pid, last_name="", birthdate="1998-01-01",
    )
    data.update(kw)
    return SimpleNamespace(**data)


def _shape(roster, players):
    arms = sum(counts_as_pitcher(players[p]) for p in roster.act)
    return arms, len(roster.act) - arms


# --- B1: yearly promotions never move an owner's player --------------------------


@pytest.fixture
def promo(monkeypatch, tmp_path):
    import services.prospect_promotion as pp

    players, rosters = {}, {}

    def add_team(team_id, low_ready):
        act = []
        for i in range(MAX_ACTIVE_PITCHERS):
            players[f"{team_id}p{i}"] = _p(f"{team_id}p{i}", "P")
            act.append(f"{team_id}p{i}")
        for i in range(ACT_HITTER_TARGET):
            players[f"{team_id}h{i}"] = _p(f"{team_id}h{i}")
            act.append(f"{team_id}h{i}")
        low = []
        for i in range(low_ready):
            pid = f"{team_id}l{i}"
            players[pid] = _p(pid, "SS", 60, birthdate="2000-01-01")     # age >= 22
            low.append(pid)
        rosters[team_id] = Roster(team_id, act=act, low=low)

    def levels():
        return {
            tid: {**{p: "LOW" for p in r.low}, **{p: "AAA" for p in r.aaa}, **{p: "ACT" for p in r.act}}
            for tid, r in rosters.items()
        }

    news = []
    monkeypatch.setattr(pp, "_load_team_rosters_with_levels", lambda *_a: levels())
    monkeypatch.setattr(pp, "load_players_from_csv", lambda *a, **k: list(players.values()))
    monkeypatch.setattr(pp, "load_roster", lambda tid, *a, **k: rosters[tid])
    monkeypatch.setattr(pp, "save_roster", lambda tid, r, *a, **k: None)
    monkeypatch.setattr("utils.news_logger.log_news_event", lambda msg, **k: news.append(msg))
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    return SimpleNamespace(pp=pp, add_team=add_team, rosters=rosters, news=news, tmp=tmp_path)


def test_an_owners_low_prospect_is_suggested_never_moved(promo, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"})
    promo.add_team("CPU", low_ready=1)
    promo.add_team("HUM", low_ready=1)
    res = promo.pp.run_yearly_promotions(season_year=2027, data_dir=promo.tmp)
    assert "CPUl0" in promo.rosters["CPU"].aaa                # a CPU club's moves
    hum = promo.rosters["HUM"]
    assert "HUMl0" in hum.low and "HUMl0" not in hum.aaa       # the owner's doesn't
    assert [(s["player_id"], s["to_level"]) for s in res["suggestions"]] == [("HUMl0", "AAA")]
    assert [p["player_id"] for p in res["promotions"]] == ["CPUl0"]
    assert any("HUMl0" in line and "ready for AAA" in line for line in promo.news)


def test_yearly_promotions_move_nobody_when_ownership_is_unknown(promo, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None)
    promo.add_team("CPU", low_ready=1)
    promo.add_team("HUM", low_ready=1)
    res = promo.pp.run_yearly_promotions(season_year=2027, data_dir=promo.tmp)
    assert res.get("reason") == "ownership_unknown" and res["count"] == 0
    assert "CPUl0" in promo.rosters["CPU"].low and "HUMl0" in promo.rosters["HUM"].low
    assert res["suggestions"] == []


# --- B2: the CPU free-agent market reads ownership strictly ------------------------


def _fa_league(tmp_path, *, owner_ids=("", "")):
    from services.finance_settings import ensure_financial_defaults, update_financial_settings

    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        f"AAA,CPU Club,City,AAA,East,Park,#112233,#445566,{owner_ids[0]}\n"
        f"BBB,Human Club,Town,BBB,West,Park,#221133,#665544,{owner_ids[1]}\n",
        encoding="utf-8",
    )
    ensure_financial_defaults(data_dir=data_dir, league_id="test")
    update_financial_settings(
        preset="standard", path=data_dir / "league_financial_settings.json", league_id="test"
    )
    (data_dir / "standings.json").write_text(
        json.dumps({"AAA": {"wins": 86, "losses": 76}, "BBB": {"wins": 74, "losses": 88}}),
        encoding="utf-8",
    )
    (data_dir / "players.csv").write_text(
        "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,"
        "other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher\n"
        "P100,Free,Agent,2000-01-01,72,190,R,1B,,50,64,60,50,55,55,55,55,58,56,0\n",
        encoding="utf-8",
    )
    (data_dir / "rosters").mkdir(parents=True, exist_ok=True)
    (data_dir / "rosters" / "AAA.csv").write_text("", encoding="utf-8")
    (data_dir / "rosters" / "BBB.csv").write_text("", encoding="utf-8")
    (data_dir / "users.txt").write_text("jane,pw,owner,BBB\n", encoding="utf-8")
    return data_dir


def _rostered(data_dir, team_id):
    return "P100" in (data_dir / "rosters" / f"{team_id}.csv").read_text(encoding="utf-8")


def test_cpu_market_signs_nobody_when_ownership_is_unreadable(tmp_path, monkeypatch):
    from services.free_agency import run_cpu_free_agency_round

    data_dir = _fa_league(tmp_path)

    def _unreadable(*_a, **_k):
        raise OSError("users.txt unreadable")

    monkeypatch.setattr("utils.user_manager.load_users", _unreadable)
    summary = run_cpu_free_agency_round(
        data_dir=data_dir, league_id="test", max_signings=3, rng=random.Random(7)
    )
    assert summary["reason"] == "ownership_unknown"
    assert summary["signed_players"] == 0
    assert not _rostered(data_dir, "AAA") and not _rostered(data_dir, "BBB")


def test_cpu_market_never_signs_for_an_owners_club(tmp_path, monkeypatch):
    import services.free_agency as fa

    data_dir = _fa_league(tmp_path)
    # A bid book that (wrongly) bids for the owner's club: the placement
    # guard still refuses it.
    monkeypatch.setattr(fa, "build_cpu_free_agent_bid_book", lambda *a, **k: {"BBB": 5_000_000})
    summary = fa.run_cpu_free_agency_round(
        data_dir=data_dir, league_id="test", max_signings=3, rng=random.Random(7)
    )
    assert summary["signed_players"] == 0
    assert not _rostered(data_dir, "BBB")
    assert fa._add_player_to_team_roster("BBB", "P100", data_dir=data_dir, cpu_only=True) is None
    assert fa._add_player_to_team_roster("AAA", "P100", data_dir=data_dir, cpu_only=True) == "ACT"


# --- B4: a full CPU club can't stall a free-agent negotiation ------------------------


def _full_org(team_id):
    act = [f"{team_id}a{i}" for i in range(ACTIVE_ROSTER_SIZE)]
    aaa = [f"{team_id}b{i}" for i in range(AAA_CAP)]
    low = [f"{team_id}c{i}" for i in range(ORG_LIMIT - ACTIVE_ROSTER_SIZE - AAA_CAP)]
    return Roster(team_id, act=act, aaa=aaa, low=low)


def test_the_bid_book_skips_a_cpu_club_with_no_room(tmp_path):
    from services.finance_ai import build_cpu_free_agent_bid_book

    data_dir = _fa_league(tmp_path, owner_ids=("cpu", "cpu"))
    (data_dir / "users.txt").unlink()
    full = _full_org("AAA")
    lines = [f"{p},ACT" for p in full.act] + [f"{p},AAA" for p in full.aaa] + [f"{p},LOW" for p in full.low]
    (data_dir / "rosters" / "AAA.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    teams = [SimpleNamespace(team_id="AAA", owner_id="cpu"), SimpleNamespace(team_id="BBB", owner_id="cpu")]
    player = _p("P100", "1B", 60)

    class _MaxRng:
        @staticmethod
        def randint(low, high):
            return high

    bids = build_cpu_free_agent_bid_book(
        player, teams, ai_level="advanced", data_dir=data_dir, rng=_MaxRng()
    )
    assert "AAA" not in bids
    assert "BBB" in bids


def test_a_full_cpu_club_cannot_stall_an_owners_negotiation(tmp_path, monkeypatch):
    import services.fa_negotiations as neg
    import services.free_agency as fa

    monkeypatch.setattr(fa, "active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE)
    monkeypatch.setattr(fa, "active_pitcher_cap", lambda *a, **k: MAX_ACTIVE_PITCHERS)
    rosters = {"CPU": _full_org("CPU"), "HUM": Roster("HUM", act=["h0"])}
    target = _p("FA1", "SS", 70)
    monkeypatch.setattr(fa, "load_roster", lambda tid, *a, **k: rosters[tid])
    monkeypatch.setattr(fa, "save_roster", lambda tid, r, *a, **k: None)
    monkeypatch.setattr(fa, "load_players_from_csv", lambda *a, **k: [target])
    monkeypatch.setattr(fa, "sign_free_agent_contract", lambda *a, **k: None)
    monkeypatch.setattr(fa, "record_transaction", lambda **k: None)
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"})
    # The CPU club outbids the owner every day.
    monkeypatch.setattr(
        "services.finance_ai.build_cpu_free_agent_bid_book",
        lambda p, teams, **k: {"CPU": 9_000_000},
    )
    monkeypatch.setattr(
        "services.contract_negotiator.evaluate_extension_offer",
        lambda p, **k: SimpleNamespace(decision="accepted"),
    )
    monkeypatch.setattr("services.contract_negotiator.fair_market_years", lambda p, **k: 2)

    def _sign(*, team_id, player_id, offer, player):
        return fa.finalize_fa_signing(
            team_id, player_id, level=offer.get("level", "ACT"),
            years=int(offer.get("years", 1)), annual_salary=int(offer.get("annual_salary", 0)),
            player=player, data_dir=tmp_path,
        )

    neg.submit_offer("FA1", "HUM", years=2, annual_salary=2_000_000, sim_date="2025-06-01", data_dir=tmp_path)
    day = date(2025, 6, 2)
    for _ in range(20):
        neg.process_negotiations(
            day.isoformat(), data_dir=tmp_path, sign_fn=_sign,
            players_by_id={"FA1": target}, teams=[SimpleNamespace(team_id="CPU", owner_id="")],
        )
        if neg.get_negotiation("FA1", data_dir=tmp_path)["status"] != "open":
            break
        day += timedelta(days=1)
    final = neg.get_negotiation("FA1", data_dir=tmp_path)
    assert final["status"] == "resolved"
    assert final["resolution"]["signed_team"] == "HUM"
    assert day <= date(2025, 6, 17)                       # a day or two past the deadline
    assert "FA1" in rosters["HUM"].act
    assert "CPU" in final.get("excluded_teams", [])


# --- B7: a CPU signing goes to Low-A only if he is young enough ----------------------


def test_cpu_signing_level_keeps_veterans_out_of_low(monkeypatch):
    import services.free_agency as fa

    monkeypatch.setattr(fa, "active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE)
    monkeypatch.setattr(fa, "active_pitcher_cap", lambda *a, **k: MAX_ACTIVE_PITCHERS)
    roster = Roster(
        "TST",
        act=[f"x{i}" for i in range(ACTIVE_ROSTER_SIZE)],
        aaa=[f"y{i}" for i in range(AAA_CAP)],
    )
    assert fa.cpu_signing_level(roster, _p("kid", "SS", birthdate=_YOUNG), {}) == "LOW"
    assert fa.cpu_signing_level(roster, _p("vet", "SS", birthdate=_OLD), {}) is None


# --- B3 / B8: the September revert -----------------------------------------------------


def _wire_callups(monkeypatch, *, players, rosters, owners=()):
    import services.inseason_callups as ic

    records = []
    monkeypatch.setattr(ic, "load_players_from_csv", lambda *a, **k: list(players.values()))
    monkeypatch.setattr(ic, "load_teams", lambda *a, **k: [SimpleNamespace(team_id=t) for t in rosters])
    monkeypatch.setattr(ic, "human_owned_team_ids_strict", lambda *a, **k: set(owners))
    monkeypatch.setattr(ic, "load_outlooks", lambda **k: {})
    monkeypatch.setattr(ic, "_current_phase_is_regular_season", lambda: True)
    monkeypatch.setattr(ic, "load_roster", lambda tid, *a, **k: rosters[str(tid).upper()])
    monkeypatch.setattr(ic, "save_roster", lambda tid, roster, **k: None)
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: records.append(k))
    monkeypatch.setattr("utils.news_logger.log_news_event", lambda *a, **k: None)
    return ic, records


def test_the_revert_never_options_the_only_healthy_catcher(monkeypatch, tmp_path):
    players = {"c1": _p("c1", "C", 20), "c2": _p("c2", "C", 70, injured=True)}
    players.update({f"p{i}": _p(f"p{i}", "P", 60) for i in range(MAX_ACTIVE_PITCHERS)})
    players.update({f"h{i}": _p(f"h{i}", "LF", 70 + i) for i in range(13)})
    roster = Roster("HUM", act=list(players))                   # 28 active
    assert len(roster.act) == ACTIVE_ROSTER_SIZE + 2
    ic, _ = _wire_callups(monkeypatch, players=players, rosters={"HUM": roster}, owners={"HUM"})
    ic.revert_september_expansion(data_dir=tmp_path)
    assert len(roster.act) == ACTIVE_ROSTER_SIZE
    assert "c1" in roster.act


def _over_staff(extra_aaa_age):
    players = {"c": _p("c", "C", 70)}
    players.update({f"p{i}": _p(f"p{i}", "P", 60) for i in range(MAX_ACTIVE_PITCHERS)})
    players["weak"] = _p("weak", "P", 20, birthdate=extra_aaa_age)   # the 14th arm
    players.update({f"h{i}": _p(f"h{i}", "LF", 70) for i in range(ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS - 2)})
    act = list(players)
    players.update({f"a{i}": _p(f"a{i}", "LF", 40) for i in range(AAA_CAP)})
    roster = Roster("HUM", act=act, aaa=[f"a{i}" for i in range(AAA_CAP)])
    return players, roster


def test_the_revert_sends_a_young_arm_to_low_when_aaa_is_full(monkeypatch, tmp_path):
    players, roster = _over_staff(_YOUNG)
    ic, _ = _wire_callups(monkeypatch, players=players, rosters={"HUM": roster}, owners={"HUM"})
    res = ic.revert_september_expansion(data_dir=tmp_path)
    assert _shape(roster, players)[0] == MAX_ACTIVE_PITCHERS
    assert "weak" in roster.low and len(roster.aaa) == AAA_CAP
    assert [d["to_level"] for d in res["demotions"]] == ["low"]


def test_the_revert_overfills_aaa_only_when_low_cannot_take_him_and_says_so(monkeypatch, tmp_path):
    players, roster = _over_staff(_OLD)
    ic, records = _wire_callups(monkeypatch, players=players, rosters={"HUM": roster}, owners={"HUM"})
    ic.revert_september_expansion(data_dir=tmp_path)
    assert _shape(roster, players)[0] == MAX_ACTIVE_PITCHERS     # legal for the playoffs
    assert "weak" in roster.aaa and len(roster.aaa) == AAA_CAP + 1
    assert roster.low == []
    [line] = [r for r in records if r.get("player_id") == "weak"]
    assert f"over its {AAA_CAP}-man cap" in line["details"]


# --- B9: a hitter call-up on a full 13/13 CPU club sends down a hitter -------------------


def test_a_hitter_call_up_on_a_full_club_keeps_13_and_13(monkeypatch, tmp_path):
    players = {"c": _p("c", "C", 60)}
    players.update({f"h{i}": _p(f"h{i}", "LF", 60) for i in range(ACT_HITTER_TARGET - 1)})
    players.update({f"p{i}": _p(f"p{i}", "P", 30) for i in range(MAX_ACTIVE_PITCHERS)})
    act = list(players)
    players["star"] = _p("star", "SS", 85, birthdate="2001-01-01")     # SS: a hole
    roster = Roster("CPU", act=act, aaa=["star"])
    ic, _ = _wire_callups(monkeypatch, players=players, rosters={"CPU": roster})
    res = ic.run_monthly_callups(played_dates=["2026-06-15"], data_dir=tmp_path)
    assert [p["player_id"] for p in res["promotions"]] == ["star"]
    assert _shape(roster, players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)


# --- B5: the CPU trim forces only a surplus pitcher -----------------------------------------


def test_the_cpu_trim_never_forces_a_hitter_down():
    from services.roster_fill import ForcedMove, maintain_cpu_active_roster

    players = {"c": _p("c", "C", 60)}
    players.update({f"h{i}": _p(f"h{i}", "LF", 50 + i) for i in range(ACT_HITTER_TARGET)})
    players.update({f"p{i}": _p(f"p{i}", "P", 50 + i) for i in range(MAX_ACTIVE_PITCHERS)})
    roster = Roster("CPU", act=list(players))                   # 27: 13 P / 14 H
    moves = maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE,
        option_allowed=lambda pid: False,
    )
    forced_hitters = [
        m for m in moves if isinstance(m, ForcedMove) and not counts_as_pitcher(players[m[0]])
    ]
    assert forced_hitters == []
    assert len(roster.act) == ACTIVE_ROSTER_SIZE + 1            # left over; the daily path


# --- B10: a CPU pitcher back from the IL costs exactly one move ----------------------------


def test_a_returning_cpu_pitcher_costs_one_move(monkeypatch):
    import services.injury_manager as im

    players = {"c": _p("c", "C", 60)}
    players.update({f"h{i}": _p(f"h{i}", "LF", 40 + i) for i in range(ACT_HITTER_TARGET - 1)})
    players.update({f"p{i}": _p(f"p{i}", "P", 50 + i) for i in range(MAX_ACTIVE_PITCHERS)})
    back = _p("back", "P", 70, injury_list=None)
    players["back"] = back
    roster = Roster("CPU", act=[p for p in players if p != "back"], dl=["back"])
    recorded = []
    monkeypatch.setattr(im, "_team_is_cpu", lambda tid: True)
    # Every other arm is out of options; the position players are not.
    monkeypatch.setattr(
        im, "_option_allowed", lambda tid: (lambda pid: not counts_as_pitcher(players[pid]))
    )
    monkeypatch.setattr("services.injury_replacements.pop_replacement", lambda *a, **k: None)
    monkeypatch.setattr("utils.roster_loader.active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE)
    monkeypatch.setattr("utils.roster_loader.active_pitcher_cap", lambda *a, **k: MAX_ACTIVE_PITCHERS)
    monkeypatch.setattr(
        "services.roster_fill.record_roster_moves",
        lambda tid, moves, p, details, news=False: recorded.extend(moves),
    )
    monkeypatch.setattr("services.roster_fill.apply_prospect_bookkeeping", lambda *a, **k: None)
    im.recover_from_injury(back, roster, "act", force=True, players_by_id=players)
    assert len(recorded) == 1
    assert counts_as_pitcher(players[recorded[0][0]])
    assert _shape(roster, players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)


# --- B6: the roster backfill ends legal ------------------------------------------------------


@pytest.fixture
def backfill(monkeypatch):
    import utils.roster_backfill as rb

    rosters = {}
    saved = []
    monkeypatch.setattr(rb, "load_teams", lambda *a, **k: [SimpleNamespace(team_id=t) for t in rosters])
    monkeypatch.setattr(rb, "load_roster", lambda tid, *a, **k: rosters[tid])
    monkeypatch.setattr(rb, "save_roster", lambda tid, r, *a, **k: saved.append(tid))
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set())
    return SimpleNamespace(rb=rb, rosters=rosters, saved=saved)


def _arm_heavy_club(minor_pos):
    players = {"c0": _p("c0", "C")}
    players.update({f"p{i}": _p(f"p{i}", "P") for i in range(20)})
    act = list(players)
    players.update({f"a{i}": _p(f"a{i}", minor_pos) for i in range(AAA_CAP)})
    players.update({f"l{i}": _p(f"l{i}", minor_pos, birthdate=_YOUNG) for i in range(LOW_CAP)})
    players.update({f"fa_h{i}": _p(f"fa_h{i}", "LF") for i in range(30)})
    roster = Roster(
        "CPU", act=act, aaa=[f"a{i}" for i in range(AAA_CAP)], low=[f"l{i}" for i in range(LOW_CAP)]
    )
    return players, roster


def _org(roster):
    return len(roster.act) + len(roster.aaa) + len(roster.low)


def test_backfill_trims_the_staff_then_fills_the_freed_spots(backfill):
    players, roster = _arm_heavy_club("LF")
    backfill.rosters["CPU"] = roster
    backfill.rb.ensure_active_rosters(players=players)
    assert len(roster.act) == ACTIVE_ROSTER_SIZE
    assert _shape(roster, players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)
    assert len(roster.aaa) <= AAA_CAP and len(roster.low) <= LOW_CAP
    assert _org(roster) <= ORG_LIMIT
    assert "c0" in roster.act


def test_backfill_never_overfills_a_level_or_the_organisation(backfill):
    players, roster = _arm_heavy_club("P")             # no own hitters to swap up
    backfill.rosters["CPU"] = roster
    backfill.rb.ensure_active_rosters(players=players)
    assert len(roster.act) <= ACTIVE_ROSTER_SIZE
    assert len(roster.aaa) <= AAA_CAP and len(roster.low) <= LOW_CAP
    assert _org(roster) <= ORG_LIMIT
    assert "c0" in roster.act


def test_backfill_trim_keeps_the_last_healthy_catcher(backfill):
    players = {"c0": _p("c0", "C", 10)}
    players.update({f"h{i}": _p(f"h{i}", "LF") for i in range(ACTIVE_ROSTER_SIZE + 2)})
    roster = Roster("CPU", act=list(players))
    roster.act.append(roster.act.pop(0))                # the catcher sits last
    backfill.rosters["CPU"] = roster
    backfill.rb.ensure_active_rosters(players=players)
    assert len(roster.act) == ACTIVE_ROSTER_SIZE
    assert "c0" in roster.act
