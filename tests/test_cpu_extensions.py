"""CPU clubs extend the walk-year players they want to keep (8.5.0,
``services.cpu_extensions``): whom (quality, age, need, strategy), the most
they'll pay (free-agent band top, held under the payroll target), and the
negotiation under the players' own rules. Owners' clubs are never touched.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import services.cpu_extensions as cx
import services.extension_talks as et

QUALITY = {}
AGE = {}


def _p(pid, pos="CF", quality=56, age=27):
    QUALITY[pid] = quality
    AGE[pid] = age
    return SimpleNamespace(player_id=pid, first_name="Pat", last_name=pid,
                           primary_position=pos, is_pitcher=pos == "P",
                           other_positions=[])


@pytest.fixture(autouse=True)
def ratings(monkeypatch):
    QUALITY.clear()
    AGE.clear()
    monkeypatch.setattr("services.contract_negotiator._talent_score",
                        lambda p: QUALITY.get(p.player_id, 50.0))
    monkeypatch.setattr("services.contract_negotiator._age_of",
                        lambda p: AGE.get(p.player_id))
    monkeypatch.setattr("services.contract_negotiator.fair_market_years",
                        lambda p, **k: 4)


# --- whom a club wants ------------------------------------------------------------


def test_strategy_sets_the_bar():
    star = _p("S", quality=56, age=28)
    others = [_p("X", quality=40)]
    assert cx.wants_to_keep(star, profile="contend", others=others)
    assert cx.wants_to_keep(star, profile="balanced", others=others)  # 56 + 2 need
    assert not cx.wants_to_keep(star, profile="rebuild", others=others + [_p("CF2", quality=55)])


def test_age_and_need():
    old = _p("OLD", quality=58, age=34)  # 58 - 6
    assert not cx.wants_to_keep(old, profile="balanced", others=[_p("Y", quality=40)])
    # A rebuilding club lets a 30-year-old non-star go however good he scores.
    vet = _p("VET", quality=59, age=30)
    assert not cx.wants_to_keep(vet, profile="rebuild", others=[])
    # Need: nobody else at his position within three points adds two.
    mid = _p("MID", quality=54, age=28)
    assert cx.wants_to_keep(mid, profile="balanced", others=[_p("1B", pos="1B", quality=60)])
    assert not cx.wants_to_keep(mid, profile="balanced", others=[_p("CF3", quality=53)])


def test_ceiling_holds_under_the_payroll_target():
    strategy = SimpleNamespace(profile="balanced", budget_tone="neutral")
    top = cx.ceiling(10_000_000, strategy=strategy, ai_level="basic", quality=56,
                     current_salary=2_000_000, payroll_room=None)
    assert top == 11_000_000  # balanced, neutral band top 1.10
    tight = cx.ceiling(10_000_000, strategy=strategy, ai_level="basic", quality=56,
                       current_salary=2_000_000, payroll_room=5_000_000)
    assert tight == 7_000_000


# --- the pass ----------------------------------------------------------------------


@pytest.fixture
def league(tmp_path, monkeypatch):
    base = tmp_path
    (base / "rosters").mkdir()
    players = {
        "KEEP": _p("KEEP", quality=58, age=26),
        "MEH": _p("MEH", quality=45, age=26),
        "LONG": _p("LONG", quality=60, age=26),
        "OWNED": _p("OWNED", quality=62, age=26),
    }
    (base / "rosters" / "CPU.csv").write_text("KEEP,ACT\nMEH,ACT\nLONG,ACT\n", encoding="utf-8")
    (base / "rosters" / "BAL.csv").write_text("OWNED,ACT\n", encoding="utf-8")
    contracts = {
        "KEEP": {"team_id": "CPU", "years_left": 1, "annual_salary": 2_000_000},
        "MEH": {"team_id": "CPU", "years_left": 1, "annual_salary": 2_000_000},
        "LONG": {"team_id": "CPU", "years_left": 3, "annual_salary": 2_000_000},
        "OWNED": {"team_id": "BAL", "years_left": 1, "annual_salary": 2_000_000},
    }
    settings = SimpleNamespace(enabled=True, finance_ai_tuning={},
                               module_level=lambda name: "basic")
    monkeypatch.setattr("services.finance_settings.load_financial_settings",
                        lambda **k: settings)
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict",
                        lambda base=None: {"BAL"})
    monkeypatch.setattr("services.contracts_service.load_contracts_payload",
                        lambda **k: {"players": contracts})
    extended = []
    monkeypatch.setattr("services.contracts_service.extend_contract",
                        lambda pid, **kw: extended.append((pid, kw)) or {"player_id": pid})
    monkeypatch.setattr("utils.player_loader.load_players_from_csv",
                        lambda path: list(players.values()))
    monkeypatch.setattr("services.finance_ai.load_team_finance_strategies",
                        lambda **k: {"CPU": SimpleNamespace(
                            profile="balanced", budget_tone="neutral",
                            annual_payroll=100_000_000, next_year_commitment=0)})
    monkeypatch.setattr(et, "fair_price", lambda *a, **k: 10_000_000)
    monkeypatch.setattr(et, "season_key", lambda base: "lg-2027")
    monkeypatch.setattr(et, "talks_clock", lambda base: ("sim", "2027-05-02"))
    news = []
    monkeypatch.setattr(cx, "_announce", lambda base, club, pid, p, y, s: news.append((club, pid, y, s)))
    return SimpleNamespace(base=base, extended=extended, news=news, contracts=contracts)


def run(league, date="2027-05-02", phase="REGULAR_SEASON", **kw):
    return cx.run_cpu_extension_pass(date, phase=phase, data_dir=league.base, **kw)


def test_the_club_extends_the_walk_year_player_it_wants(league):
    out = run(league)
    assert out["applied"] and out["window"] == "2027-05a"
    # KEEP only: MEH isn't wanted, LONG isn't in his walk year, OWNED is an
    # owner's. Opened at 9.0M, met his counter halfway, signed.
    assert [pid for pid, _ in league.extended] == ["KEEP"]
    pid, kw = league.extended[0]
    assert kw["additional_years"] == 4
    assert 9_600_000 <= kw["annual_salary"] <= 11_000_000  # his minimum .. the ceiling
    assert league.news and league.news[0][:2] == ("CPU", "KEEP")


def test_twice_a_month_in_season(league):
    run(league)
    assert run(league, date="2027-05-09")["reason"] == "already_ran"
    assert run(league, date="2027-05-16")["window"] == "2027-05b"
    assert run(league, phase="AMATEUR_DRAFT")["reason"] == "phase"


def test_a_club_over_its_target_does_not_open_talks(league, monkeypatch):
    monkeypatch.setattr("services.finance_ai.load_team_finance_strategies",
                        lambda **k: {"CPU": SimpleNamespace(
                            profile="balanced", budget_tone="neutral",
                            annual_payroll=250_000_000, next_year_commitment=0)})
    out = run(league)
    assert out["talks"] == 0 and league.extended == []


def test_finance_ai_off_or_ownership_unknown_stands_down(league, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids_strict",
                        lambda base=None: None)
    assert run(league)["reason"] == "ownership_unknown"
    assert league.extended == []


def test_once_in_the_offseason_window_and_once_in_the_preseason(league):
    out = run(league, date="2027-12-03", phase="OFFSEASON")
    assert out["window"] == "lg-2027-offseason" and out["applied"]
    assert run(league, date="2027-12-04", phase="OFFSEASON")["reason"] == "already_ran"
    assert run(league, date="", phase="PRESEASON")["window"] == "lg-2027-preseason"
    assert run(league, date="", phase="AMATEUR_DRAFT")["reason"] == "phase"
