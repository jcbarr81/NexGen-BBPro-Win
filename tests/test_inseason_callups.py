"""S2-11: in-season callups + September expansion (26 -> 28, decision 8)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from models.roster import Roster
import services.inseason_callups as ic
from utils.roster_rules import (
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
    counts_as_pitcher,
)


def _p(
    pid,
    *,
    pos="SS",
    pitcher=False,
    ch=70,
    ph=70,
    sp=70,
    fa=70,
    arm=70,
    eye=70,
    control=60,
    movement=60,
    endurance=60,
    age=24,
    injured=False,
):
    return SimpleNamespace(
        player_id=pid,
        is_pitcher=pitcher,
        primary_position=pos,
        ch=ch,
        ph=ph,
        sp=sp,
        fa=fa,
        arm=arm,
        eye=eye,
        control=control,
        movement=movement,
        endurance=endurance,
        birthdate=f"{2026 - age:04d}-01-01",
        first_name="F",
        last_name=pid,
        injured=injured,
    )


def _wire(monkeypatch, *, teams, players, rosters, outlooks, users=None, phase_rs=True):
    monkeypatch.setattr(ic, "load_players_from_csv", lambda *a, **k: list(players))
    monkeypatch.setattr(ic, "load_teams", lambda *a, **k: list(teams))
    owners = {str(u.get("team_id", "")).upper() for u in (users or []) if u.get("team_id")}
    monkeypatch.setattr(ic, "human_owned_team_ids_strict", lambda *a, **k: set(owners))
    monkeypatch.setattr(ic, "load_outlooks", lambda **k: dict(outlooks))
    monkeypatch.setattr(ic, "_current_phase_is_regular_season", lambda: phase_rs)
    monkeypatch.setattr(ic, "load_roster", lambda tid, *a, **k: rosters[str(tid).upper()])
    monkeypatch.setattr(
        ic, "save_roster", lambda tid, roster, **k: rosters.__setitem__(str(tid).upper(), roster)
    )
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    monkeypatch.setattr("utils.news_logger.log_news_event", lambda *a, **k: None)


def test_monthly_hook_fires_once_per_month(monkeypatch, tmp_path):
    rosters = {"CPU": Roster("CPU", act=[], aaa=[])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=[],
        rosters=rosters,
        outlooks={"CPU": "bubble"},
    )
    first = ic.run_monthly_callups(played_dates=["2026-06-05"], data_dir=tmp_path)
    second = ic.run_monthly_callups(played_dates=["2026-06-20"], data_dir=tmp_path)
    third = ic.run_monthly_callups(played_dates=["2026-07-01"], data_dir=tmp_path)
    assert first["reason"] == "ok"
    assert second["reason"] == "already_ran"
    assert third["reason"] == "ok"


def test_contender_promotes_only_into_hole(monkeypatch, tmp_path):
    prospect = _p("PROS", pos="SS", ch=70, ph=70, age=24)
    # Variant A: no ACT shortstop -> SS is a hole -> promote.
    rosters = {"CPU": Roster("CPU", act=["F1", "F2"], aaa=["PROS"])}
    players = [prospect, _p("F1", pos="1B"), _p("F2", pos="CF")]
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "contend"},
    )
    res = ic.run_monthly_callups(played_dates=["2026-06-15"], data_dir=tmp_path)
    assert [p["player_id"] for p in res["promotions"]] == ["PROS"]

    # Variant B: a strong ACT shortstop -> SS not a hole -> skip.
    rosters2 = {"CPU": Roster("CPU", act=["SS0", "F2"], aaa=["PROS"])}
    players2 = [prospect, _p("SS0", pos="SS", ch=90, ph=90), _p("F2", pos="CF")]
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players2,
        rosters=rosters2,
        outlooks={"CPU": "contend"},
    )
    res2 = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    assert res2["promotions"] == []


def test_rebuilder_promotes_after_deadline_regardless(monkeypatch, tmp_path):
    players = [
        _p("PA", pos="LF", ch=75, ph=75, age=25),
        _p("PB", pos="RF", ch=74, ph=74, age=25),
        _p("A1", pos="1B"),
    ]
    rosters = {"CPU": Roster("CPU", act=["A1"], aaa=["PA", "PB"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "rebuild"},
    )
    res = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    assert len(res["promotions"]) == 2


def test_protection_respected(monkeypatch, tmp_path):
    players = [_p("PROS", pos="LF", ch=75, ph=75, age=25), _p("A1", pos="1B")]

    def _run(allowed, when):
        rosters = {"CPU": Roster("CPU", act=["A1"], aaa=["PROS"])}
        _wire(
            monkeypatch,
            teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
            players=players,
            rosters=rosters,
            outlooks={"CPU": "rebuild"},
        )
        monkeypatch.setattr(
            ic,
            "evaluate_roster_move",
            lambda *a, **k: SimpleNamespace(allowed=allowed, requires_auto_protect=False),
        )
        monkeypatch.setattr(ic, "apply_roster_move", lambda *a, **k: None)
        return ic.run_monthly_callups(played_dates=[when], data_dir=tmp_path)

    blocked = _run(False, "2026-06-15")
    assert blocked["promotions"] == []
    assert blocked["filtered"]["blocked_by_rules"] >= 1
    promoted = _run(True, "2026-08-15")
    assert [p["player_id"] for p in promoted["promotions"]] == ["PROS"]


def test_full_roster_swap(monkeypatch, tmp_path):
    n_fill = ACTIVE_ROSTER_SIZE - 10
    act_ids = ["C1"] + [f"P{i}" for i in range(8)] + ["WORST"] + [f"H{i}" for i in range(n_fill)]
    players = [_p("C1", pos="C", ch=60, ph=60)]
    players += [_p(f"P{i}", pos="P", pitcher=True, control=55, movement=55, arm=55, endurance=55) for i in range(8)]
    players += [_p("WORST", pos="1B", ch=20, ph=20, sp=20, fa=20, arm=20, eye=20)]
    players += [_p(f"H{i}", pos="RF", ch=60, ph=60) for i in range(n_fill)]
    players += [_p("BLUE", pos="SS", ch=75, ph=75, sp=75, fa=75, arm=75, eye=75, age=26)]
    rosters = {"CPU": Roster("CPU", act=list(act_ids), aaa=["BLUE"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "rebuild"},
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        "services.transaction_log.record_transaction",
        lambda **k: recorded.append(k),
    )
    res = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    roster = rosters["CPU"]
    assert len(roster.act) == ACTIVE_ROSTER_SIZE
    assert "BLUE" in roster.act
    assert "WORST" in roster.aaa
    actions = [r["action"] for r in recorded]
    assert actions.count("demote") == 1 and actions.count("promote") == 1


def test_full_roster_no_legal_demotion_skips(monkeypatch, tmp_path):
    act_ids = [f"H{i}" for i in range(ACTIVE_ROSTER_SIZE)]
    players = [_p(f"H{i}", pos="RF", ch=60, ph=60) for i in range(ACTIVE_ROSTER_SIZE)]
    players += [_p("BLUE", pos="SS", ch=75, ph=75, sp=75, fa=75, arm=75, eye=75, age=26)]
    rosters = {"CPU": Roster("CPU", act=list(act_ids), aaa=["BLUE"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "rebuild"},
    )
    monkeypatch.setattr(ic, "is_player_protected", lambda *a, **k: True)
    res = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    assert res["promotions"] == []
    assert res["filtered"]["no_roster_space"] >= 1
    assert len(rosters["CPU"].act) == ACTIVE_ROSTER_SIZE
    assert "BLUE" in rosters["CPU"].aaa


def test_september_expansion_size(monkeypatch):
    from utils.roster_loader import active_pitcher_cap, active_roster_cap
    from playbalance.season_manager import SeasonPhase

    class _FakeSM:
        def __init__(self, *a, **k):
            self.phase = SeasonPhase.REGULAR_SEASON

    monkeypatch.setattr("playbalance.season_manager.SeasonManager", _FakeSM)
    assert active_roster_cap("2026-09-01") == SEPTEMBER_ROSTER_SIZE
    assert active_roster_cap("2026-08-31") == ACTIVE_ROSTER_SIZE
    assert active_pitcher_cap("2026-09-01") == SEPTEMBER_MAX_ACTIVE_PITCHERS
    assert active_pitcher_cap("2026-08-31") == MAX_ACTIVE_PITCHERS

    class _Playoffs(_FakeSM):
        def __init__(self, *a, **k):
            self.phase = SeasonPhase.PLAYOFFS

    monkeypatch.setattr("playbalance.season_manager.SeasonManager", _Playoffs)
    assert active_roster_cap("2026-09-01") == ACTIVE_ROSTER_SIZE
    assert active_pitcher_cap("2026-09-01") == MAX_ACTIVE_PITCHERS


def _expanded(monkeypatch):
    monkeypatch.setattr(ic, "active_roster_cap", lambda *a, **k: SEPTEMBER_ROSTER_SIZE)
    monkeypatch.setattr(ic, "active_pitcher_cap", lambda *a, **k: SEPTEMBER_MAX_ACTIVE_PITCHERS)


def test_september_expansion_fills_to_28(monkeypatch, tmp_path):
    act_ids = [f"H{i}" for i in range(ACTIVE_ROSTER_SIZE)]
    players = [_p(f"H{i}", pos="RF", ch=60, ph=60) for i in range(ACTIVE_ROSTER_SIZE)]
    prospects = [
        _p("Q1", pos="SS", ch=80, ph=80, sp=80, fa=80, arm=80, eye=80, age=26),
        _p("Q2", pos="CF", ch=78, ph=78, sp=78, fa=78, arm=78, eye=78, age=26),
        _p("Q3", pos="LF", ch=76, ph=76, sp=76, fa=76, arm=76, eye=76, age=26),
        _p("Q4", pos="1B", ch=74, ph=74, sp=74, fa=74, arm=74, eye=74, age=26),
    ]
    players += prospects
    rosters = {"CPU": Roster("CPU", act=list(act_ids), aaa=["Q1", "Q2", "Q3", "Q4"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "bubble"},
    )
    _expanded(monkeypatch)
    res = ic.run_september_expansion(sim_date="2026-09-01", data_dir=tmp_path)
    extra = SEPTEMBER_ROSTER_SIZE - ACTIVE_ROSTER_SIZE
    assert len(res["promotions"]) == extra
    assert len(rosters["CPU"].act) == SEPTEMBER_ROSTER_SIZE
    # The best ones by overall.
    assert {p["player_id"] for p in res["promotions"]} == set(["Q1", "Q2", "Q3", "Q4"][:extra])


def _arm(pid, grade=70, **kw):
    return _p(pid, pos="P", pitcher=True, arm=grade, control=grade, movement=grade,
              endurance=grade, **kw)


def test_september_expansion_stops_adding_pitchers_at_14(monkeypatch, tmp_path):
    hitters = ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS
    act_ids = [f"H{i}" for i in range(hitters)] + [f"P{i}" for i in range(MAX_ACTIVE_PITCHERS)]
    players = [_p(f"H{i}", pos="RF", ch=60, ph=60) for i in range(hitters)]
    players += [_arm(f"P{i}", 55) for i in range(MAX_ACTIVE_PITCHERS)]
    # Three blue-chip arms outrank the one hitter in AAA.
    players += [_arm("A1", 90, age=26), _arm("A2", 88, age=26), _arm("A3", 86, age=26)]
    players += [_p("BAT", pos="SS", ch=74, ph=74, sp=74, fa=74, arm=74, eye=74, age=26)]
    rosters = {"CPU": Roster("CPU", act=list(act_ids), aaa=["A1", "A2", "A3", "BAT"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "bubble"},
    )
    _expanded(monkeypatch)
    ic.run_september_expansion(sim_date="2026-09-01", data_dir=tmp_path)
    by_id = {p.player_id: p for p in players}
    act = rosters["CPU"].act
    assert len(act) == SEPTEMBER_ROSTER_SIZE
    assert sum(counts_as_pitcher(by_id[p]) for p in act) == SEPTEMBER_MAX_ACTIVE_PITCHERS
    assert "BAT" in act and "A1" in act and "A3" in rosters["CPU"].aaa


def test_september_revert_trims_to_26(monkeypatch, tmp_path):
    over = SEPTEMBER_ROSTER_SIZE - 1
    act_ids = ["C1"] + [f"H{i}" for i in range(over)]
    players = [_p("C1", pos="C", ch=60, ph=60)]
    players += [_p(f"H{i}", pos="RF", ch=40 + i, ph=40 + i) for i in range(over)]
    rosters = {"CPU": Roster("CPU", act=list(act_ids), aaa=[])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "bubble"},
    )
    res = ic.revert_september_expansion(data_dir=tmp_path)
    assert len(rosters["CPU"].act) == ACTIVE_ROSTER_SIZE
    assert len(res["demotions"]) == SEPTEMBER_ROSTER_SIZE - ACTIVE_ROSTER_SIZE


def _sept_staff(prefix, hitters, pitchers):
    ids = [f"{prefix}C"] + [f"{prefix}H{i}" for i in range(hitters - 1)]
    ids += [f"{prefix}P{i}" for i in range(pitchers)]
    players = [_p(f"{prefix}C", pos="C", ch=60, ph=60)]
    players += [_p(f"{prefix}H{i}", pos="RF", ch=50 + i, ph=50 + i) for i in range(hitters - 1)]
    players += [_arm(f"{prefix}P{i}", 50 + i) for i in range(pitchers)]
    return ids, players


def test_september_revert_leaves_26_and_13_pitchers_on_owner_and_cpu_teams(monkeypatch, tmp_path):
    # A September-legal 28 (14 pitchers) on each side, plus an owner club
    # that is at 26 but carries 14 pitchers.
    hitters = SEPTEMBER_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS
    cpu_ids, cpu_players = _sept_staff("c", hitters, SEPTEMBER_MAX_ACTIVE_PITCHERS)
    hum_ids, hum_players = _sept_staff("h", hitters, SEPTEMBER_MAX_ACTIVE_PITCHERS)
    arm_ids, arm_players = _sept_staff(
        "a", ACTIVE_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS, SEPTEMBER_MAX_ACTIVE_PITCHERS
    )
    players = cpu_players + hum_players + arm_players
    rosters = {
        "CPU": Roster("CPU", act=list(cpu_ids), aaa=[]),
        "HUM": Roster("HUM", act=list(hum_ids), aaa=[]),
        "ARM": Roster("ARM", act=list(arm_ids), aaa=[]),
    }
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id=t, owner_id="") for t in ("CPU", "HUM", "ARM")],
        players=players,
        rosters=rosters,
        outlooks={},
        users=[{"role": "owner", "team_id": "HUM"}, {"role": "owner", "team_id": "ARM"}],
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        "services.transaction_log.record_transaction", lambda **k: recorded.append(k)
    )
    res = ic.revert_september_expansion(data_dir=tmp_path)
    by_id = {p.player_id: p for p in players}
    for team_id, prefix in (("CPU", "c"), ("HUM", "h"), ("ARM", "a")):
        act = rosters[team_id].act
        assert len(act) <= ACTIVE_ROSTER_SIZE, team_id
        assert sum(counts_as_pitcher(by_id[p]) for p in act) <= MAX_ACTIVE_PITCHERS, team_id
        assert f"{prefix}C" in act, team_id                # the only catcher stays
    # Optioned, never released, and every move is in the transaction log.
    assert len(rosters["ARM"].act) == ACTIVE_ROSTER_SIZE - 1
    assert all(r["action"] == "demote" and r["to_level"] == "AAA" for r in recorded)
    assert len(recorded) == len(res["demotions"])
    assert all(d["player_id"] in rosters[d["team_id"]].aaa for d in res["demotions"])


def test_pitcher_callup_to_a_full_staff_sends_a_pitcher_down(monkeypatch, tmp_path):
    hitters = ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS - 1     # one open spot
    act_ids = ["C1"] + [f"H{i}" for i in range(hitters - 1)]
    act_ids += [f"P{i}" for i in range(MAX_ACTIVE_PITCHERS)]
    players = [_p("C1", pos="C", ch=60, ph=60)]
    players += [_p(f"H{i}", pos="RF", ch=60, ph=60) for i in range(hitters - 1)]
    players += [_arm(f"P{i}", 50 + i) for i in range(MAX_ACTIVE_PITCHERS)]
    players += [_arm("ACE", 90, age=26)]
    rosters = {"CPU": Roster("CPU", act=list(act_ids), aaa=["ACE"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "rebuild"},
    )
    res = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    by_id = {p.player_id: p for p in players}
    act = rosters["CPU"].act
    assert "ACE" in act and "P0" in rosters["CPU"].aaa
    assert [d["player_id"] for d in res["demotions"]] == ["P0"]
    assert sum(counts_as_pitcher(by_id[p]) for p in act) == MAX_ACTIVE_PITCHERS


def test_unreadable_ownership_means_no_callups(monkeypatch, tmp_path):
    players = [_p("PROS", pos="LF", ch=80, ph=80, age=26), _p("A1", pos="1B")]
    rosters = {"CPU": Roster("CPU", act=["A1"], aaa=["PROS"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="CPU", owner_id="cpu")],
        players=players,
        rosters=rosters,
        outlooks={"CPU": "rebuild"},
    )
    monkeypatch.setattr(ic, "human_owned_team_ids_strict", lambda *a, **k: None)
    res = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    assert res["reason"] == "ownership_unknown"
    _expanded(monkeypatch)
    sept = ic.run_september_expansion(sim_date="2026-09-01", data_dir=tmp_path)
    assert sept["reason"] == "ownership_unknown"
    assert rosters["CPU"].act == ["A1"] and rosters["CPU"].aaa == ["PROS"]
    # Not marked as run: tomorrow's check tries again.
    again = ic.run_monthly_callups(played_dates=["2026-08-16"], data_dir=tmp_path)
    assert again["reason"] == "ownership_unknown"


def test_revert_wired_into_advance_phase(monkeypatch, tmp_path):
    from playbalance.season_manager import SeasonManager, SeasonPhase

    called: list[bool] = []
    monkeypatch.setattr(
        "services.inseason_callups.revert_september_expansion",
        lambda **k: called.append(True),
    )
    path = tmp_path / "season_state.json"
    path.write_text('{"phase": "REGULAR_SEASON"}', encoding="utf-8")
    mgr = SeasonManager(path=path, enable_rollover=False)
    assert mgr.phase == SeasonPhase.REGULAR_SEASON
    mgr.advance_phase()
    assert mgr.phase == SeasonPhase.PLAYOFFS
    assert called == [True]


def test_human_teams_untouched(monkeypatch, tmp_path):
    players = [_p("PROS", pos="LF", ch=80, ph=80, age=26), _p("A1", pos="1B")]
    rosters = {"HUM": Roster("HUM", act=["A1"], aaa=["PROS"])}
    _wire(
        monkeypatch,
        teams=[SimpleNamespace(team_id="HUM", owner_id="james")],
        players=players,
        rosters=rosters,
        outlooks={"HUM": "rebuild"},
        users=[{"role": "owner", "team_id": "HUM"}],
    )
    res = ic.run_monthly_callups(played_dates=["2026-08-15"], data_dir=tmp_path)
    assert res["promotions"] == []
    assert res["teams_checked"] == 0
    assert "PROS" in rosters["HUM"].aaa


def test_hook_wired_into_daily_automations(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import api.routers.season as season

    captured: dict = {}
    monkeypatch.setattr(
        "services.inseason_callups.run_monthly_callups",
        lambda **k: captured.setdefault("args", k) or {"applied": False, "reason": "ok"},
    )
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    summary = season._run_daily_automations(["2026-06-01"])
    assert "callups" in summary
    assert captured["args"]["played_dates"] == ["2026-06-01"]


def test_compliance_gate_accepts_28_in_september(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import api.routers.season as season

    # 27-man ACT roster (an empty players map produces unrelated composition
    # errors we ignore — S2-11 only changed the *cap* the gate enforces).
    monkeypatch.setattr(
        "api.routers.validation.load_team_levels",
        lambda team_id: {"act": [f"h{i}" for i in range(27)], "aaa": [], "low": []},
        raising=False,
    )
    monkeypatch.setattr(
        "api.routers.validation.load_players_map", lambda: {}, raising=False
    )

    # September cap (28): 27 players is NOT over cap.
    monkeypatch.setattr("utils.roster_loader.active_roster_cap", lambda *a, **k: 28)
    sept = season._team_roster_compliance_errors("CPU")
    assert not any("over cap" in e for e in sept)

    # Base cap (26): the same roster IS over cap — proves the cap flows in.
    monkeypatch.setattr(
        "utils.roster_loader.active_roster_cap", lambda *a, **k: ACTIVE_ROSTER_SIZE
    )
    strict = season._team_roster_compliance_errors("CPU")
    assert any("over cap" in e for e in strict)
