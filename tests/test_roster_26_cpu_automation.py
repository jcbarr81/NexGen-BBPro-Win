"""CPU roster automation under the 26-man / 13-pitcher rule (decision 8).

The Opening Day CPU pass, injured-list returns, CPU free-agent placement,
the CPU trade evaluator's pitcher lines, yearly promotions and the roster
backfill. Every path is CPU-only by the strict ownership read: an owner's
club is never moved, and unreadable ownership means nothing moves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from models.roster import Roster
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    AAA_CAP,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    counts_as_pitcher,
)


def _p(pid, pos="LF", score=50, **kw):
    data = dict(
        player_id=pid, primary_position=pos, other_positions=[], injured=False,
        is_pitcher=(pos == "P"), ch=score, ph=score, sp=score, fa=score, arm=score,
        eye=score, control=score, movement=score, endurance=score,
        first_name=pid, last_name="", birthdate="1998-01-01",
    )
    data.update(kw)
    return SimpleNamespace(**data)


def _creator_shape(prefix):
    """The league creator's 25-man shape: 11 pitchers / 14 hitters, plus a
    few arms and bats in AAA."""
    arms = MAX_ACTIVE_PITCHERS - 2
    hitters = ACTIVE_ROSTER_SIZE - 1 - arms
    players = {f"{prefix}c": _p(f"{prefix}c", "C")}
    players.update({f"{prefix}h{i}": _p(f"{prefix}h{i}", "LF", 50 + i) for i in range(hitters - 1)})
    players.update({f"{prefix}p{i}": _p(f"{prefix}p{i}", "P", 50 + i) for i in range(arms)})
    players.update({f"{prefix}ap{i}": _p(f"{prefix}ap{i}", "P", 60 + i) for i in range(4)})
    players.update({f"{prefix}ah{i}": _p(f"{prefix}ah{i}", "CF", 40 + i) for i in range(2)})
    act = [pid for pid in players if pid[len(prefix):][0] in "chp"]
    aaa = [pid for pid in players if pid[len(prefix):].startswith("a")]
    return players, Roster(prefix.upper(), act=act, aaa=aaa)


def _shape(roster, players):
    arms = sum(counts_as_pitcher(players[p]) for p in roster.act)
    return arms, len(roster.act) - arms


# --- the Opening Day CPU pass (PRESEASON -> REGULAR_SEASON) ------------------


@pytest.fixture
def opening_day(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import api.routers.season as season

    cpu_players, cpu = _creator_shape("cpu")
    hum_players, hum = _creator_shape("hum")
    players = {**cpu_players, **hum_players}
    rosters = {"CPU": cpu, "HUM": hum}
    saved, logged = [], []
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.player_loader.load_players_from_csv", lambda *a, **k: list(players.values()))
    monkeypatch.setattr(
        "utils.team_loader.load_teams",
        lambda *a, **k: [SimpleNamespace(team_id="CPU"), SimpleNamespace(team_id="HUM")],
    )
    monkeypatch.setattr("utils.roster_loader.load_roster", lambda tid, *a, **k: rosters[tid])
    monkeypatch.setattr("utils.roster_loader.save_roster", lambda tid, r, *a, **k: saved.append(tid))
    monkeypatch.setattr(
        "services.roster_fill.record_roster_moves",
        lambda tid, moves, p, details, news=False: logged.append((tid, list(moves), details)),
    )
    monkeypatch.setattr("services.roster_fill.apply_prospect_bookkeeping", lambda *a, **k: None)
    monkeypatch.setattr("services.injury_manager._promotion_allowed", lambda tid: None)
    monkeypatch.setattr("services.injury_manager._option_allowed", lambda tid: None)
    return SimpleNamespace(
        season=season, players=players, rosters=rosters, saved=saved, logged=logged,
        before={t: (list(r.act), list(r.aaa)) for t, r in rosters.items()},
    )


def test_opening_day_brings_cpu_clubs_to_13_and_13(opening_day, monkeypatch):
    od = opening_day
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"}
    )
    summary = od.season._cpu_opening_day_roster_upkeep()
    cpu = od.rosters["CPU"]
    assert _shape(cpu, od.players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)
    assert len(cpu.act) == ACTIVE_ROSTER_SIZE
    assert summary["teams"] == 1 and od.saved == ["CPU"]
    assert [t for t, _, _ in od.logged] == ["CPU"]          # every move recorded
    # The owner's club is never touched.
    hum = od.rosters["HUM"]
    assert (hum.act, hum.aaa) == od.before["HUM"]


def test_opening_day_does_nothing_when_ownership_is_unknown(opening_day, monkeypatch):
    od = opening_day
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None
    )
    summary = od.season._cpu_opening_day_roster_upkeep()
    assert summary.get("skipped") == "ownership_unknown"
    assert od.saved == [] and od.logged == []
    for team_id, roster in od.rosters.items():
        assert (roster.act, roster.aaa) == od.before[team_id]


@pytest.mark.parametrize(
    "start, fires",
    [("PRESEASON", True), ("AMATEUR_DRAFT", False)],
)
def test_opening_day_pass_runs_only_on_the_preseason_edge(monkeypatch, start, fires):
    pytest.importorskip("fastapi")
    import api.routers.season as season
    from playbalance.season_manager import SeasonPhase

    class _Manager:
        phase = SeasonPhase[start]

        def advance_phase(self):
            self.phase = SeasonPhase.REGULAR_SEASON
            return self.phase

    calls = []
    monkeypatch.setattr("utils.league_settings.can_run_season_progression", lambda *a, **k: True)
    monkeypatch.setattr(
        season, "_build_manager_and_simulator",
        lambda: (_Manager(), SimpleNamespace(dates=[], _index=0), None),
    )
    monkeypatch.setattr(season, "_state_payload", lambda m, s, d, extra=None: extra)
    monkeypatch.setattr(
        season, "_cpu_opening_day_roster_upkeep", lambda: calls.append(1) or {"teams": 0}
    )
    extra = season.advance_phase(payload={"force": True}, identity={"r": "admin", "t": ""})
    assert bool(calls) is fires
    assert ("cpu_roster_upkeep" in extra) is fires


# --- injured-list returns: an owner's pitcher waits in AAA at a full staff ----


def _staff(arms, hitters):
    players = {f"p{i}": _p(f"p{i}", "P") for i in range(arms)}
    players.update({f"h{i}": _p(f"h{i}", "LF") for i in range(hitters)})
    return players, Roster("TST", act=list(players))


def test_owner_pitcher_activates_to_aaa_when_the_staff_is_full(monkeypatch):
    import services.dl_automation as dl

    monkeypatch.setattr(dl, "active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE)
    monkeypatch.setattr(dl, "active_pitcher_cap", lambda *a, **k: MAX_ACTIVE_PITCHERS)
    players, roster = _staff(MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET - 1)   # a spot open
    arm, bat = _p("back", "P"), _p("bat", "LF")
    assert dl._resolve_destination(roster, player=arm, players_by_id=players) == "aaa"
    assert dl._resolve_destination(roster, player=bat, players_by_id=players) == "act"
    # A CPU club always takes him back; recover_from_injury trims the staff.
    assert dl._resolve_destination(roster, cpu_owned=True, player=arm, players_by_id=players) == "act"
    players, roster = _staff(MAX_ACTIVE_PITCHERS - 1, ACT_HITTER_TARGET - 1)
    assert dl._resolve_destination(roster, player=arm, players_by_id=players) == "act"


# --- CPU free-agent signings --------------------------------------------------


@pytest.fixture
def fa(monkeypatch):
    import services.free_agency as fa

    monkeypatch.setattr(fa, "active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE)
    monkeypatch.setattr(fa, "active_pitcher_cap", lambda *a, **k: MAX_ACTIVE_PITCHERS)
    return fa


def test_cpu_signing_level_sends_a_pitcher_to_aaa_at_a_full_staff(fa):
    players, roster = _staff(MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET - 1)
    assert fa.cpu_signing_level(roster, _p("arm", "P"), players) == "AAA"
    assert fa.cpu_signing_level(roster, _p("bat", "SS"), players) == "ACT"
    roster.aaa = [f"x{i}" for i in range(AAA_CAP)]
    # Low-A only for a player young enough for it (LOW_LEVEL_MAX_AGE).
    assert fa.cpu_signing_level(roster, _p("arm", "P", birthdate="2006-01-01"), players) == "LOW"
    roster.low = [f"y{i}" for i in range(ORG_LIMIT - len(roster.act) - AAA_CAP)]
    assert fa.cpu_signing_level(roster, _p("bat", "SS"), players) is None


def _finalize_env(monkeypatch, fa, roster, players):
    saved = {}
    monkeypatch.setattr(fa, "load_roster", lambda tid, *a, **k: roster)
    monkeypatch.setattr(fa, "save_roster", lambda tid, r, *a, **k: saved.setdefault(tid, r))
    monkeypatch.setattr(fa, "load_players_from_csv", lambda *a, **k: list(players.values()))
    monkeypatch.setattr(fa, "sign_free_agent_contract", lambda *a, **k: None)
    monkeypatch.setattr(fa, "record_transaction", lambda **k: None)
    return saved


def test_a_cpu_negotiation_winner_who_pitches_goes_to_aaa(fa, monkeypatch, tmp_path):
    players, roster = _staff(MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET - 1)
    arm = _p("arm", "P")
    players["arm"] = arm
    _finalize_env(monkeypatch, fa, roster, players)
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set())
    assert fa.finalize_fa_signing("TST", "arm", level="ACT", player=arm, data_dir=tmp_path)
    assert "arm" in roster.aaa and "arm" not in roster.act


def test_an_owners_signing_goes_where_the_owner_chose(fa, monkeypatch, tmp_path):
    players, roster = _staff(MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET - 1)
    arm = _p("arm", "P")
    _finalize_env(monkeypatch, fa, roster, players)
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"TST"})
    assert fa.finalize_fa_signing("TST", "arm", level="ACT", player=arm, data_dir=tmp_path)
    assert "arm" in roster.act


def test_a_cpu_club_with_a_full_organisation_passes_on_the_signing(fa, monkeypatch, tmp_path):
    players, roster = _staff(MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)
    roster.aaa = [f"x{i}" for i in range(AAA_CAP)]
    roster.low = [f"y{i}" for i in range(ORG_LIMIT - len(roster.act) - AAA_CAP)]
    _finalize_env(monkeypatch, fa, roster, players)
    assert not fa.finalize_fa_signing(
        "TST", "bat", level="ACT", player=_p("bat", "SS"), data_dir=tmp_path, cpu_placement=True
    )
    assert "bat" not in roster.act + roster.aaa + roster.low


# --- CPU trades: the evaluator's pitcher lines ---------------------------------


def test_trade_evaluator_pitcher_lines_follow_the_limit():
    from services import cpu_trade_evaluator as ev

    def fit(arms):
        players, roster = _staff(arms, ACT_HITTER_TARGET)
        return ev._build_roster_fit_context(
            "TST", players_by_id=players, rosters_by_team={"TST": roster}
        )

    assert "P" in fit(MAX_ACTIVE_PITCHERS - 2)["needs"]
    assert "P" not in fit(MAX_ACTIVE_PITCHERS - 1)["needs"]
    arm = _p("arm", "P")
    open_spot = ev._fit_value(arm, roster_fit=fit(MAX_ACTIVE_PITCHERS - 1), strategy_profile="balanced")
    full = ev._fit_value(arm, roster_fit=fit(MAX_ACTIVE_PITCHERS), strategy_profile="balanced")
    assert full < open_spot


def test_cpu_trade_proposals_stand_down_when_ownership_is_unknown(monkeypatch, tmp_path):
    import random

    from services import cpu_trade_proposals as ctp

    monkeypatch.setattr(
        ctp, "load_trade_settings",
        lambda **_k: SimpleNamespace(
            league_id="alpha", trades_enabled=True, cpu_initiated_trades_enabled=True,
            cpu_proposal_cadence="normal",
        ),
    )
    monkeypatch.setattr(
        ctp, "load_teams",
        lambda *a, **k: [SimpleNamespace(team_id="A", owner_id=""), SimpleNamespace(team_id="B", owner_id="")],
    )
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None)
    result = ctp.run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-01"], data_dir=tmp_path, rng=random.Random(0)
    )
    assert result["reason"] == "ownership_unknown" and result["offers_created"] == 0


# --- yearly promotions ----------------------------------------------------------


@pytest.fixture
def promo(monkeypatch, tmp_path):
    import services.prospect_promotion as pp

    players = {}
    rosters = {}

    def add_team(team_id, act_arms, act_bats, aaa_ready, low_ready=0, aaa_fill=0):
        act = []
        for i in range(act_arms):
            players[f"{team_id}p{i}"] = _p(f"{team_id}p{i}", "P", 50)
            act.append(f"{team_id}p{i}")
        for i in range(act_bats):
            players[f"{team_id}h{i}"] = _p(f"{team_id}h{i}", "LF", 50)
            act.append(f"{team_id}h{i}")
        aaa, low = [], []
        for pid, pos in aaa_ready:
            players[pid] = _p(pid, pos, 80, birthdate="1998-01-01")
            aaa.append(pid)
        for i in range(aaa_fill):
            players[f"{team_id}f{i}"] = _p(f"{team_id}f{i}", "LF", 40, birthdate="2004-01-01")
            aaa.append(f"{team_id}f{i}")
        for i in range(low_ready):
            players[f"{team_id}l{i}"] = _p(f"{team_id}l{i}", "LF", 60, birthdate="2000-01-01")
            low.append(f"{team_id}l{i}")
        rosters[team_id] = Roster(team_id, act=act, aaa=aaa, low=low)

    def levels():
        out = {}
        for tid, r in rosters.items():
            out[tid] = {**{p: "AAA" for p in r.aaa}, **{p: "LOW" for p in r.low}, **{p: "ACT" for p in r.act}}
        return out

    monkeypatch.setattr(pp, "_load_team_rosters_with_levels", lambda *_a: levels())
    monkeypatch.setattr(pp, "load_players_from_csv", lambda *a, **k: list(players.values()))
    monkeypatch.setattr(pp, "load_roster", lambda tid, *a, **k: rosters[tid])
    monkeypatch.setattr(pp, "save_roster", lambda tid, r, *a, **k: None)
    monkeypatch.setattr("utils.news_logger.log_news_event", lambda *a, **k: None)
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    return SimpleNamespace(pp=pp, add_team=add_team, rosters=rosters, players=players, tmp=tmp_path)


def test_yearly_promotions_move_only_cpu_players_to_the_active_roster(promo, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"})
    arms, bats = MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET - 2     # two open spots, full staff
    promo.add_team("CPU", arms, bats, [("CPUace", "P"), ("CPUbat", "SS")])
    promo.add_team("HUM", arms, bats, [("HUMbat", "SS")])
    res = promo.pp.run_yearly_promotions(season_year=2027, data_dir=promo.tmp)
    cpu, hum = promo.rosters["CPU"], promo.rosters["HUM"]
    assert "CPUbat" in cpu.act
    assert "CPUace" in cpu.aaa                                   # a 14th arm stays down
    assert _shape(cpu, promo.players)[0] == MAX_ACTIVE_PITCHERS
    assert "HUMbat" in hum.aaa                                   # an owner's: a suggestion
    assert [s["player_id"] for s in res["suggestions"]] == ["HUMbat"]
    assert res["skipped"]["staff_full"] == 1


def test_yearly_promotions_respect_the_size_and_aaa_caps(promo, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set())
    promo.add_team(
        "CPU", MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET, [("CPUbat", "SS")],
        low_ready=2, aaa_fill=AAA_CAP - 2,           # one AAA spot open
    )
    promo.pp.run_yearly_promotions(season_year=2027, data_dir=promo.tmp)
    cpu = promo.rosters["CPU"]
    assert len(cpu.act) == ACTIVE_ROSTER_SIZE and "CPUbat" in cpu.aaa
    assert len(cpu.aaa) == AAA_CAP and len(cpu.low) == 1


def test_yearly_promotions_need_known_ownership_for_call_ups(promo, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None)
    promo.add_team("CPU", MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET - 2, [("CPUbat", "SS")])
    promo.pp.run_yearly_promotions(season_year=2027, data_dir=promo.tmp)
    assert "CPUbat" in promo.rosters["CPU"].aaa


# --- roster backfill ----------------------------------------------------------------


@pytest.fixture
def backfill(monkeypatch):
    import utils.roster_backfill as rb

    rosters = {
        "CPU": Roster("CPU", act=["c0"]),
        "HUM": Roster("HUM", act=["u0"]),
    }
    players = {"c0": _p("c0", "C"), "u0": _p("u0", "C")}
    players.update({f"fa_h{i}": _p(f"fa_h{i}", "LF") for i in range(30)})
    players.update({f"fa_p{i}": _p(f"fa_p{i}", "P") for i in range(30)})
    saved = []
    monkeypatch.setattr(rb, "load_teams", lambda *a, **k: [SimpleNamespace(team_id=t) for t in rosters])
    monkeypatch.setattr(rb, "load_roster", lambda tid, *a, **k: rosters[tid])
    monkeypatch.setattr(rb, "save_roster", lambda tid, r, *a, **k: saved.append(tid))
    return SimpleNamespace(rb=rb, rosters=rosters, players=players, saved=saved)


def test_backfill_fills_cpu_clubs_to_13_and_13_and_skips_owners(backfill, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"})
    backfill.rb.ensure_active_rosters(players=backfill.players)
    cpu = backfill.rosters["CPU"]
    assert _shape(cpu, backfill.players) == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET)
    assert backfill.saved == ["CPU"]
    assert backfill.rosters["HUM"].act == ["u0"]


def test_backfill_does_nothing_when_ownership_is_unknown(backfill, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None)
    res = backfill.rb.ensure_active_rosters(players=backfill.players)
    assert res["skipped"] == "ownership_unknown" and backfill.saved == []
