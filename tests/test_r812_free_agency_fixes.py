"""8.1.2: three owner-facing free-agency fixes.

1. The Players browser labelled retired players and contracted players with
   no roster spot as free agents (it read the roster files only). It now
   follows the one-club-per-player rule the free-agent list uses: a retiree
   reads ``RET``, a contracted player on no roster level reads
   ``UNASSIGNED`` with his club, and neither is a free agent.
2. Free-agent rows carry the player's injury (flag, description, return
   date) so the Free Agency page can show it.
3. A signing or offer made without a salary was priced at the one-season
   fair-market figure, whose aging discount the negotiator does not apply:
   a 35-year-old's "default" signing was countered. The default is now his
   asking price, the figure the negotiator accepts.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster

_TEAMS = (
    "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
    "AAA,CPU Club,City,AAA,East,Park,#112233,#445566,cpu\n"
    "BBB,Other Club,Town,BBB,West,Park,#221133,#665544,cpu\n"
)
_PLAYER_HEADER = (
    "player_id,first_name,last_name,birthdate,height,weight,bats,primary_position,"
    "other_positions,gf,ch,ph,sp,eye,pl,vl,sc,fa,arm,is_pitcher,"
    "injured,injury_description,return_date\n"
)


def _player_row(pid: str, *, born: str = "2000-01-01", quality: int = 60,
                injured: str = "") -> str:
    hurt = "true,Torn hamstring,2026-07-15" if injured else "false,,"
    return (
        f"{pid},First,{pid},{born},72,190,R,1B,,50,{quality},{quality},50,55,"
        f"55,55,55,{quality},56,0,{hurt}\n"
    )


@pytest.fixture
def league(tmp_path, monkeypatch):
    """A scratch league as the data root (never a real league).

    BBB holds P100 (active) and P200 (15-day list); P300 is under contract
    with BBB on no roster file; P400 retired (with a leftover contract);
    P500 retired; P600 is a healthy free agent, P700 an injured one and
    P800 a 35-year-old free agent.
    """

    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "teams.csv").write_text(_TEAMS, encoding="utf-8")
    (root / "users.txt").write_text("", encoding="utf-8")
    (root / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n2026-04-01,AAA,BBB,3-2,1,\n",
        encoding="utf-8",
    )
    rows = [
        _player_row("P100"), _player_row("P200"), _player_row("P300"),
        _player_row("P400"), _player_row("P500"), _player_row("P600"),
        _player_row("P700", injured="yes"),
        _player_row("P800", born="1991-01-01", quality=62),
    ]
    (root / "players.csv").write_text(_PLAYER_HEADER + "".join(rows), encoding="utf-8")
    (root / "rosters" / "AAA.csv").write_text("", encoding="utf-8")
    (root / "rosters" / "BBB.csv").write_text("P100,ACT\nP200,DL15\n", encoding="utf-8")
    (root / "contracts.json").write_text(json.dumps({"version": 1, "players": {
        "P300": {"team_id": "BBB", "years_left": 2, "annual_salary": 2_000_000},
        "P400": {"team_id": "BBB", "years_left": 1, "annual_salary": 1_000_000},
    }}), encoding="utf-8")
    (root / "retired_players.json").write_text(json.dumps({
        "P400": {"retired_year": 2026}, "P500": {"retired_year": 2025},
    }), encoding="utf-8")

    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    monkeypatch.setenv("PB_SIM_DATE", "2026-06-01")
    import utils.path_utils as path_utils
    import utils.roster_loader as rl

    # These toy rosters have no pitchers; loading one would pad it with
    # placeholder arms from the repo's sample league.
    monkeypatch.setattr(rl, "_ensure_pitcher_depth", lambda roster, **k: False)
    rl.load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield root
    rl.load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def _browse(**kw):
    from api.routers import players

    args = dict(q=None, team_id=None, position=None, role=None,
                free_agents_only=False, limit=10000)
    args.update(kw)
    out = players.browse_players(**args)
    return {r["player_id"]: (r["team_id"], r["level"]) for r in out["players"]}


# ---------------------------------------------------------------------------
# 1. The Players browser
# ---------------------------------------------------------------------------
def test_browser_labels_retired_and_unrostered_contracted_players(league):
    rows = _browse()
    assert rows["P100"] == ("BBB", "ACT")
    assert rows["P200"] == ("BBB", "DL15")
    assert rows["P300"] == ("BBB", "UNASSIGNED")
    # A retiree's leftover contract does not make him a club's player.
    assert rows["P400"] == ("", "RET")
    assert rows["P500"] == ("", "RET")
    assert rows["P600"] == ("", "FA")


def test_browser_free_agents_only_matches_the_free_agent_list(league):
    from services.free_agency import list_unsigned_players_from_files

    free = set(_browse(free_agents_only=True))
    assert free == {"P600", "P700", "P800"}
    assert free == {p.player_id for p in list_unsigned_players_from_files(data_dir=league)}


def test_browser_team_filter_includes_the_unrostered_contracted_player(league):
    assert set(_browse(team_id="BBB")) == {"P100", "P200", "P300"}


# ---------------------------------------------------------------------------
# 2. Injured free agents
# ---------------------------------------------------------------------------
def test_free_agent_rows_carry_the_injury(league):
    from api.routers import free_agency

    rows = {r["player_id"]: r for r in free_agency.list_free_agents(limit=1000)["free_agents"]}
    assert set(rows) == {"P600", "P700", "P800"}
    hurt = rows["P700"]
    assert hurt["injured"] is True
    assert hurt["injury_description"] == "Torn hamstring"
    assert hurt["return_date"] == "2026-07-15"
    healthy = rows["P600"]
    assert healthy["injured"] is False
    assert healthy["injury_description"] is None and healthy["return_date"] is None


# ---------------------------------------------------------------------------
# 3. The default salary is the asking price
# ---------------------------------------------------------------------------
def _player(league: Path, pid: str):
    return next(p for p in load_players_from_csv(league / "players.csv") if p.player_id == pid)


def test_old_default_was_countered_and_asking_price_is_accepted(league):
    from services.contract_negotiator import (
        FA_SERVICE_DAYS,
        asking_salary,
        evaluate_extension_offer,
        fair_market_salary,
        fair_market_years,
    )

    player = _player(league, "P800")
    years = fair_market_years(player, service_time_days=FA_SERVICE_DAYS)
    old_default = fair_market_salary(player, service_time_days=FA_SERVICE_DAYS)
    old = evaluate_extension_offer(
        player, offered_years=years, offered_annual_salary=old_default,
        service_time_days=FA_SERVICE_DAYS,
    )
    assert old.decision != "accepted"  # the bug this release fixes
    ask = asking_salary(player, years=years, service_time_days=FA_SERVICE_DAYS)
    new = evaluate_extension_offer(
        player, offered_years=years, offered_annual_salary=ask,
        service_time_days=FA_SERVICE_DAYS,
    )
    assert new.decision == "accepted"
    assert ask == new.fair_market_salary


def _point_router_at(monkeypatch, league: Path):
    import api.routers.free_agency as router

    roster_dir = league / "rosters"
    signed = {}
    monkeypatch.setattr(router, "_phase_gate_for_fa", lambda: None)
    monkeypatch.setattr(router, "load_roster", lambda tid: load_roster(tid, roster_dir=roster_dir))
    monkeypatch.setattr(router, "save_roster", lambda tid, r: save_roster(tid, r, roster_dir=roster_dir))
    monkeypatch.setattr(router, "_find_player", lambda pid: _player(league, pid))
    monkeypatch.setattr(
        router, "sign_free_agent_contract",
        lambda pid, tid, **k: signed.update(k, player_id=pid, team_id=tid) or {},
    )
    monkeypatch.setattr(router, "record_transaction", lambda **k: None)
    monkeypatch.setattr(
        router, "evaluate_free_agent_signing",
        lambda *a, **k: SimpleNamespace(allowed=True, warning=False, violations=[], mode="off", level="off"),
    )
    return router, signed


def test_sign_endpoint_without_a_salary_signs_at_the_asking_price(league, monkeypatch):
    from services.contract_negotiator import FA_SERVICE_DAYS, asking_salary, fair_market_years

    router, signed = _point_router_at(monkeypatch, league)
    player = _player(league, "P800")
    years = fair_market_years(player, service_time_days=FA_SERVICE_DAYS)
    ask = asking_salary(player, years=years, service_time_days=FA_SERVICE_DAYS)

    out = router.sign_free_agent(
        "AAA", {"player_id": "P800", "level": "ACT"}, {"r": "owner", "t": "AAA"}
    )

    assert out["signed"] is True
    assert out["negotiation"]["decision"] == "accepted"
    assert out["annual_salary"] == ask and out["years"] == years
    # The contract is the deal the player accepted (it used to be one year).
    assert signed["annual_salary"] == ask and signed["years_left"] == years
    assert "P800,ACT" in (league / "rosters" / "AAA.csv").read_text(encoding="utf-8")


def test_sign_endpoint_with_a_salary_still_negotiates(league, monkeypatch):
    from fastapi import HTTPException

    router, _ = _point_router_at(monkeypatch, league)
    with pytest.raises(HTTPException) as exc:
        router.sign_free_agent(
            "AAA", {"player_id": "P800", "level": "ACT", "annual_salary": 800_000},
            {"r": "owner", "t": "AAA"},
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "rejected"


def test_evaluate_and_offer_default_to_the_asking_price(league, monkeypatch):
    from services.contract_negotiator import FA_SERVICE_DAYS, asking_salary

    router, _ = _point_router_at(monkeypatch, league)
    monkeypatch.setattr(router, "_competing_bids", lambda *a, **k: [])
    player = _player(league, "P800")
    owner = {"r": "owner", "t": "AAA"}

    preview = router.evaluate_fa_offer("P800", {"years": 1}, owner)
    assert preview["decision"] == "accepted"

    captured = {}
    import services.fa_negotiations as neg

    monkeypatch.setattr(neg, "submit_offer", lambda pid, tid, **k: captured.update(k) or {})
    router.submit_fa_offer("P800", {"team_id": "AAA", "years": 1}, owner)
    assert captured["annual_salary"] == asking_salary(
        player, years=1, service_time_days=FA_SERVICE_DAYS
    )
