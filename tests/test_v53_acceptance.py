from __future__ import annotations

from datetime import date
import importlib
import random
from types import SimpleNamespace

from models.player import Player
from models.roster import Roster
from models.trade import Trade
from services.cpu_trade_evaluator import evaluate_cpu_trade_offer
from services.cpu_trade_proposals import run_cpu_trade_proposal_cycle
from services.injury_manager import place_on_injury_list
from services.prospect_rules import is_player_protected, update_prospect_rules
from utils import path_utils


def _hitter(
    player_id: str,
    *,
    age: int,
    ch: int,
    ph: int,
    primary_position: str = "CF",
    pot_delta: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id,
        age=age,
        birthdate=f"{2026 - age:04d}-06-15",
        primary_position=primary_position,
        is_pitcher=False,
        ch=ch,
        ph=ph,
        sp=55,
        pl=ch,
        vl=ch,
        sc=ch,
        fa=55,
        arm=55,
        gf=55,
        pot_ch=min(99, ch + pot_delta),
        pot_ph=min(99, ph + pot_delta),
        pot_sp=min(99, 55 + pot_delta),
        pot_fa=min(99, 55 + pot_delta),
        pot_arm=min(99, 55 + pot_delta),
        pot_sc=min(99, ch + pot_delta),
        pot_gf=min(99, 55 + pot_delta),
        injured=False,
    )


def _pitcher(pid: str) -> Player:
    return Player(
        player_id=pid,
        first_name="Pitch",
        last_name="er",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=0,
    )


def _reset_data_root(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None


def test_acceptance_cpu_trade_quality_matrix():
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="owner"),
    }
    rosters = {"CPU": SimpleNamespace(act=["OLD_VET", "STAR_BAT"])}

    rebuild_trade = Trade(
        trade_id="acc-rebuild",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["YOUNG_STAR"],
        receive_player_ids=["OLD_VET"],
    )
    rebuild_players = {
        "YOUNG_STAR": _hitter(
            "YOUNG_STAR",
            age=22,
            ch=82,
            ph=79,
            primary_position="CF",
            pot_delta=12,
        ),
        "OLD_VET": _hitter(
            "OLD_VET",
            age=35,
            ch=67,
            ph=62,
            primary_position="LF",
            pot_delta=0,
        ),
        "STAR_BAT": _hitter(
            "STAR_BAT",
            age=28,
            ch=89,
            ph=87,
            primary_position="1B",
            pot_delta=2,
        ),
    }
    rebuild_eval = evaluate_cpu_trade_offer(
        rebuild_trade,
        players_by_id=rebuild_players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.405},
        strategy_profile="development_focus",
        current_year=2026,
    )
    assert rebuild_eval is not None
    assert rebuild_eval.action == "accept"
    assert rebuild_eval.competitive_window == "rebuild"

    contend_trade = Trade(
        trade_id="acc-contend",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["BENCH_BAT"],
        receive_player_ids=["STAR_BAT"],
    )
    contend_players = dict(rebuild_players)
    contend_players["BENCH_BAT"] = _hitter(
        "BENCH_BAT",
        age=33,
        ch=56,
        ph=57,
        primary_position="1B",
        pot_delta=0,
    )
    contend_eval = evaluate_cpu_trade_offer(
        contend_trade,
        players_by_id=contend_players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.630},
        strategy_profile="win_now",
        current_year=2026,
    )
    assert contend_eval is not None
    assert contend_eval.action == "reject"
    assert contend_eval.competitive_window == "contend"
    tags = {entry.tag for entry in contend_eval.reasons}
    assert {"value_balance", "roster_fit", "timeline_alignment"} <= tags


def test_acceptance_cpu_proposal_cycle_quality_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kwargs: SimpleNamespace(
            league_id="alpha",
            trades_enabled=True,
            cpu_initiated_trades_enabled=True,
            cpu_proposal_cadence="normal",
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_teams",
        lambda *_args, **_kwargs: [
            SimpleNamespace(team_id="CPU", owner_id="cpu"),
            SimpleNamespace(team_id="HUM", owner_id="owner"),
        ],
    )

    players = [
        _hitter(f"C{i}", age=27, ch=60 + i, ph=60 + i) for i in range(1, 8)
    ] + [_hitter(f"H{i}", age=27, ch=61 + i, ph=61 + i) for i in range(1, 8)]
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_args, **_kwargs: players,
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kwargs: SimpleNamespace(
            act=[f"C{i}" for i in range(1, 8)]
            if str(team_id).upper() == "CPU"
            else [f"H{i}" for i in range(1, 8)]
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trades",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals._window_probability",
        lambda *_args, **_kwargs: 1.0,
    )

    saved: list[Trade] = []
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade",
        lambda trade, *_args, **_kwargs: saved.append(trade),
    )

    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="accept",
            total_score=0.70,
            threshold=0.60,
        ),
    )
    low_margin = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-01"],
        data_dir=tmp_path,
        rng=random.Random(3),
    )
    assert low_margin["offers_created"] == 0
    assert low_margin["filtered_counts"]["no_valid_offer"] >= 1
    assert not saved

    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="accept",
            total_score=1.00,
            threshold=0.60,
        ),
    )
    high_margin = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-02"],
        data_dir=tmp_path,
        rng=random.Random(3),
    )
    assert high_margin["offers_created"] == 1
    assert high_margin["applied"] is True
    assert len(saved) == 1


def test_acceptance_prospect_workflow_regression(monkeypatch, tmp_path):
    _reset_data_root(tmp_path, monkeypatch)
    import services.prospect_rules as prospect_rules

    importlib.reload(prospect_rules)
    prospect_rules.update_prospect_rules(
        enabled=True,
        auto_protect_on_promotion=False,
        default_option_years=1,
    )

    blocked = prospect_rules.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="aaa",
        to_level="act",
    )
    assert blocked.allowed is False
    assert blocked.reason_tag == "protection_required"
    assert blocked.decision_explanation.get("outcome") == "blocked"

    prospect_rules.set_player_protection(
        "AAA",
        "P1",
        protected=True,
        actor="test",
        trigger="acceptance_seed",
    )
    allowed = prospect_rules.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="aaa",
        to_level="act",
    )
    assert allowed.allowed is True
    assert allowed.reason_tag == "protected_promotion"

    demote_one = prospect_rules.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="act",
        to_level="aaa",
    )
    assert demote_one.allowed is True
    assert demote_one.reason_tag == "option_available"
    assert demote_one.details.get("options_remaining") == 1
    prospect_rules.apply_roster_move(
        "AAA",
        "P1",
        from_level="act",
        to_level="aaa",
        decision=demote_one,
        actor="test",
        trigger="acceptance_demote_1",
    )

    demote_two = prospect_rules.evaluate_roster_move(
        "AAA",
        "P1",
        from_level="act",
        to_level="low",
    )
    assert demote_two.allowed is False
    assert demote_two.reason_tag == "option_limit_reached"
    assert demote_two.details.get("options_used") == 1
    assert demote_two.details.get("option_limit") == 1


def test_acceptance_injury_replacement_regression(monkeypatch, tmp_path):
    _reset_data_root(tmp_path, monkeypatch)
    update_prospect_rules(enabled=True, auto_protect_on_promotion=False)
    roster_blocked = Roster(team_id="T1", act=["P1"], aaa=["P2"], low=[])
    place_on_injury_list(
        _pitcher("P1"),
        roster_blocked,
        list_name="dl15",
        today=date(2026, 4, 1),
    )
    assert "P2" in roster_blocked.aaa
    assert "P2" not in roster_blocked.act

    update_prospect_rules(enabled=True, auto_protect_on_promotion=True)
    roster_auto = Roster(team_id="T2", act=["P3"], aaa=["P4"], low=[])
    place_on_injury_list(
        _pitcher("P3"),
        roster_auto,
        list_name="dl15",
        today=date(2026, 4, 1),
    )
    assert "P4" in roster_auto.act
    assert is_player_protected("T2", "P4") is True
