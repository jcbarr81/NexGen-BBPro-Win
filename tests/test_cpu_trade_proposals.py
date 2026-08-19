from __future__ import annotations

from types import SimpleNamespace
import random

from services.cpu_trade_proposals import run_cpu_trade_proposal_cycle


def _player(pid: str, rating: int) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        is_pitcher=False,
        primary_position="CF",
        ch=rating,
        ph=rating,
        sp=rating,
        fa=rating,
        arm=rating,
        sc=rating,
    )


def test_cpu_trade_proposals_respect_cadence_off(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kwargs: SimpleNamespace(
            league_id="alpha",
            trades_enabled=True,
            cpu_initiated_trades_enabled=True,
            cpu_proposal_cadence="off",
        ),
    )

    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-01"],
        data_dir=tmp_path,
        rng=random.Random(0),
    )

    assert result["applied"] is False
    assert result["offers_created"] == 0
    assert result["reason"] == "cadence_off"


def test_cpu_trade_proposals_generate_offer_and_apply_cooldown(monkeypatch, tmp_path):
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

    cpu_players = [_player(f"C{i}", 60) for i in range(1, 7)]
    hum_players = [_player(f"H{i}", 61) for i in range(1, 7)]
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_args, **_kwargs: cpu_players + hum_players,
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kwargs: SimpleNamespace(
            act=[f"C{i}" for i in range(1, 7)]
            if str(team_id).upper() == "CPU"
            else [f"H{i}" for i in range(1, 7)]
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="accept",
            total_score=1.0,
            threshold=0.6,
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
    monkeypatch.setattr(
        "services.cpu_trade_proposals._offer_package_signature",
        lambda trade: f"{trade.from_team}>{trade.to_team}|fixed",
    )

    saved: list[object] = []
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade",
        lambda trade, *_args, **_kwargs: saved.append(trade),
    )

    first = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-01"],
        data_dir=tmp_path,
        rng=random.Random(1),
    )
    second = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-02"],
        data_dir=tmp_path,
        rng=random.Random(1),
    )

    assert first["offers_created"] == 1
    assert first["applied"] is True
    assert len(saved) == 1
    assert second["offers_created"] == 0
    assert second["applied"] is False


def test_cpu_trade_proposals_limit_offers_per_target(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kwargs: SimpleNamespace(
            league_id="alpha",
            trades_enabled=True,
            cpu_initiated_trades_enabled=True,
            cpu_proposal_cadence="high",
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_teams",
        lambda *_args, **_kwargs: [
            SimpleNamespace(team_id="CPUA", owner_id="cpu"),
            SimpleNamespace(team_id="CPUB", owner_id="cpu"),
            SimpleNamespace(team_id="HUM", owner_id="owner"),
        ],
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_args, **_kwargs: (
            [_player(f"A{i}", 60) for i in range(1, 7)]
            + [_player(f"B{i}", 60) for i in range(1, 7)]
            + [_player(f"H{i}", 61) for i in range(1, 7)]
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kwargs: SimpleNamespace(
            act=[f"A{i}" for i in range(1, 7)]
            if str(team_id).upper() == "CPUA"
            else (
                [f"B{i}" for i in range(1, 7)]
                if str(team_id).upper() == "CPUB"
                else [f"H{i}" for i in range(1, 7)]
            )
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="accept",
            total_score=1.0,
            threshold=0.6,
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
    monkeypatch.setattr(
        "services.cpu_trade_proposals._offer_package_signature",
        lambda trade: f"{trade.from_team}>{trade.to_team}|fixed",
    )

    saved: list[object] = []
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade",
        lambda trade, *_args, **_kwargs: saved.append(trade),
    )

    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-01"],
        data_dir=tmp_path,
        rng=random.Random(2),
    )

    assert result["offers_created"] == 1
    assert len(saved) == 1
    assert str(saved[0].to_team).upper() == "HUM"


def test_cpu_trade_proposals_block_repeat_package(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kwargs: SimpleNamespace(
            league_id="alpha",
            trades_enabled=True,
            cpu_initiated_trades_enabled=True,
            cpu_proposal_cadence="high",
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_teams",
        lambda *_args, **_kwargs: [
            SimpleNamespace(team_id="CPU", owner_id="cpu"),
            SimpleNamespace(team_id="HUM", owner_id="owner"),
        ],
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_args, **_kwargs: (
            [_player(f"C{i}", 60) for i in range(1, 7)]
            + [_player(f"H{i}", 61) for i in range(1, 7)]
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kwargs: SimpleNamespace(
            act=[f"C{i}" for i in range(1, 7)]
            if str(team_id).upper() == "CPU"
            else [f"H{i}" for i in range(1, 7)]
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="accept",
            total_score=1.0,
            threshold=0.6,
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
    monkeypatch.setattr(
        "services.cpu_trade_proposals._offer_package_signature",
        lambda trade: f"{trade.from_team}>{trade.to_team}|fixed",
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals._blocked_package_signatures",
        lambda *_args, **_kwargs: {"CPU>HUM|fixed"},
    )

    saved: list[object] = []
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade",
        lambda trade, *_args, **_kwargs: saved.append(trade),
    )

    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-04-10"],
        data_dir=tmp_path,
        rng=random.Random(4),
    )

    assert result["offers_created"] == 0
    assert len(saved) == 0


# --- S2-09 deadline-aware trading -----------------------------------------

def _aged(pid: str, rating: int, age: int) -> SimpleNamespace:
    p = _player(pid, rating)
    p.age = age
    p.birthdate = f"{2026 - age:04d}-06-15"
    return p


def _settings(cadence: str = "normal") -> SimpleNamespace:
    return SimpleNamespace(
        league_id="alpha",
        trades_enabled=True,
        cpu_initiated_trades_enabled=True,
        cpu_proposal_cadence=cadence,
    )


def _full_setup(monkeypatch, *, teams, players, roster_map, cadence="high"):
    """Wire the common monkeypatches; return the ``saved`` capture list."""

    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kw: _settings(cadence),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_teams",
        lambda *_a, **_kw: teams,
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_a, **_kw: players,
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kw: SimpleNamespace(act=list(roster_map[str(team_id).upper()])),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_a, **_kw: SimpleNamespace(action="accept", total_score=1.0, threshold=0.6),
    )
    monkeypatch.setattr("services.cpu_trade_proposals.load_trades", lambda *_a, **_kw: [])
    monkeypatch.setattr(
        "services.cpu_trade_proposals._window_probability", lambda *_a, **_kw: 1.0
    )
    saved: list[object] = []
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade",
        lambda trade, *_a, **_kw: saved.append(trade),
    )
    return saved


def test_cycle_blocks_after_deadline(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings", lambda **_kw: _settings()
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-08-02"], data_dir=tmp_path, rng=random.Random(0)
    )
    assert result["reason"] == "past_deadline"
    assert result["offers_created"] == 0
    assert result["deadline"] == "2026-07-31"


def test_cycle_allows_on_deadline_day(monkeypatch, tmp_path):
    teams = [
        SimpleNamespace(team_id="CPU", owner_id="cpu"),
        SimpleNamespace(team_id="HUM", owner_id="owner"),
    ]
    players = [_player(f"C{i}", 60) for i in range(1, 7)] + [
        _player(f"H{i}", 61) for i in range(1, 7)
    ]
    roster_map = {
        "CPU": [f"C{i}" for i in range(1, 7)],
        "HUM": [f"H{i}" for i in range(1, 7)],
    }
    _full_setup(monkeypatch, teams=teams, players=players, roster_map=roster_map)
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-31"], data_dir=tmp_path, rng=random.Random(1)
    )
    assert result["reason"] == "ok"
    assert result["days_to_deadline"] == 0


def test_deadline_volume_boost(monkeypatch, tmp_path):
    teams = [
        SimpleNamespace(team_id="CPU", owner_id="cpu"),
        SimpleNamespace(team_id="HUM", owner_id="owner"),
    ]
    players = [_player("C1", 60), _player("H1", 61)]
    roster_map = {"CPU": ["C1"] * 6, "HUM": ["H1"] * 6}
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kw: _settings("normal"),
    )
    monkeypatch.setattr("services.cpu_trade_proposals.load_teams", lambda *_a, **_kw: teams)
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv", lambda *_a, **_kw: players
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kw: SimpleNamespace(act=list(roster_map[str(team_id).upper()])),
    )
    monkeypatch.setattr("services.cpu_trade_proposals.load_trades", lambda *_a, **_kw: [])

    captured: dict[str, float] = {}

    def _cap(chance, days):
        captured["chance"] = chance
        return 0.0

    monkeypatch.setattr("services.cpu_trade_proposals._window_probability", _cap)

    run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-25"], data_dir=tmp_path, rng=random.Random(3)
    )
    import pytest

    assert captured["chance"] == pytest.approx(min(0.95, 0.45 * 2.0))


def test_contender_requests_veterans(monkeypatch, tmp_path):
    teams = [
        SimpleNamespace(team_id="CPU", owner_id="cpu"),
        SimpleNamespace(team_id="HUM", owner_id="owner"),
    ]
    cpu = [_aged(f"C{i}", 60, age=24 if i <= 3 else 30) for i in range(1, 7)]
    vets = [_aged(f"V{i}", 60, age=30) for i in range(1, 4)]
    kids = [_aged(f"K{i}", 60, age=22) for i in range(1, 4)]
    players = cpu + vets + kids
    roster_map = {
        "CPU": [f"C{i}" for i in range(1, 7)],
        "HUM": [p.player_id for p in vets + kids],
    }
    saved = _full_setup(monkeypatch, teams=teams, players=players, roster_map=roster_map)
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_outlooks", lambda **_kw: {"CPU": "contend"}
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(5)
    )
    assert result["offers_created"] == 1
    vet_ids = {p.player_id for p in vets}
    assert saved[0].receive_player_ids[0] in vet_ids
    assert result["offers"][0]["proposer_outlook"] == "contend"


def test_rebuilder_ships_veterans_for_youth(monkeypatch, tmp_path):
    teams = [
        SimpleNamespace(team_id="CPU", owner_id="cpu"),
        SimpleNamespace(team_id="HUM", owner_id="owner"),
    ]
    cpu_vets = [_aged(f"CV{i}", 60, age=30) for i in range(1, 4)]
    cpu_mid = [_aged(f"CM{i}", 60, age=24) for i in range(1, 4)]
    kids = [_aged(f"K{i}", 60, age=22) for i in range(1, 4)]
    hum_vets = [_aged(f"HV{i}", 60, age=30) for i in range(1, 4)]
    players = cpu_vets + cpu_mid + kids + hum_vets
    roster_map = {
        "CPU": [p.player_id for p in cpu_vets + cpu_mid],
        "HUM": [p.player_id for p in kids + hum_vets],
    }
    saved = _full_setup(monkeypatch, teams=teams, players=players, roster_map=roster_map)
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_outlooks", lambda **_kw: {"CPU": "rebuild"}
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(6)
    )
    assert result["offers_created"] == 1
    cpu_vet_ids = {p.player_id for p in cpu_vets}
    kid_ids = {p.player_id for p in kids}
    assert saved[0].give_player_ids[0] in cpu_vet_ids
    assert saved[0].receive_player_ids[0] in kid_ids


# --- S2-10 CPU-to-CPU lane -------------------------------------------------

import json
import uuid

from models.trade import Trade
from services.cpu_trade_proposals import _CandidateOffer


def _canned_offer(**kwargs):
    """Deterministic _build_best_offer stand-in: proposer -> first eligible
    target, both CPU. Returns None/[] for the human pass (empty target list).
    Honors return_ranked (the CPU-CPU lane shops a ranked shortlist)."""

    ranked = int(kwargs.get("return_ranked", 0) or 0)
    targets = list(kwargs.get("target_team_ids") or [])
    if not targets:
        return [] if ranked else None
    proposer = kwargs["cpu_team_id"]
    receiver = targets[0]
    trade = Trade(
        trade_id=uuid.uuid4().hex[:8],
        from_team=proposer,
        to_team=receiver,
        give_player_ids=[f"{proposer}_p"],
        receive_player_ids=[f"{receiver}_p"],
        initiated_by="cpu",
    )
    offer = _CandidateOffer(
        trade=trade, score_margin=0.5, cpu_team_id=proposer, target_team_id=receiver
    )
    return [offer] if ranked else offer


def _wire_cpu_cpu(monkeypatch, *, teams, outlooks, evaluate, cadence="high"):
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kw: SimpleNamespace(
            league_id="alpha",
            trades_enabled=True,
            cpu_initiated_trades_enabled=True,
            cpu_proposal_cadence=cadence,
            draft_pick_trading_enabled=False,
            max_pick_trade_years=3,
        ),
    )
    monkeypatch.setattr("services.cpu_trade_proposals.load_teams", lambda *_a, **_kw: teams)
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_a, **_kw: [_player(f"{t.team_id}_p", 60) for t in teams],
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_roster",
        lambda team_id, **_kw: SimpleNamespace(
            act=[f"{str(team_id).upper()}_{i}" for i in range(6)], aaa=[], low=[]
        ),
    )
    monkeypatch.setattr("services.cpu_trade_proposals.load_trades", lambda *_a, **_kw: [])
    monkeypatch.setattr(
        "services.cpu_trade_proposals._window_probability", lambda *_a, **_kw: 1.0
    )
    monkeypatch.setattr("services.cpu_trade_proposals._build_best_offer", _canned_offer)
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_outlooks", lambda **_kw: dict(outlooks)
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer", evaluate
    )
    monkeypatch.setattr(
        "services.roster_validation.validate_trade",
        lambda **_kw: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(
        "services.payroll_policy.evaluate_trade_payroll_impact",
        lambda *_a, **_kw: SimpleNamespace(allowed=True),
    )
    saved: list[object] = []
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade",
        lambda trade, *_a, **_kw: saved.append(trade),
    )
    commits: list[object] = []
    announced: list[object] = []
    monkeypatch.setattr(
        "services.trade_execution.commit_trade",
        lambda trade, **_kw: commits.append(trade),
    )
    monkeypatch.setattr(
        "services.trade_execution.announce_trade",
        lambda trade, **_kw: announced.append(trade),
    )
    return saved, commits, announced


_CPU_TEAMS = [
    SimpleNamespace(team_id="CPUA", owner_id="cpu"),
    SimpleNamespace(team_id="CPUB", owner_id="cpu"),
]


def test_cpu_cpu_forced_pair_executes(monkeypatch, tmp_path):
    saved, commits, announced = _wire_cpu_cpu(
        monkeypatch,
        teams=_CPU_TEAMS,
        outlooks={"CPUA": "contend", "CPUB": "bubble"},
        evaluate=lambda *_a, **_kw: SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        ),
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(1)
    )
    executed = result["cpu_cpu_trades"]["executed"]
    assert len(executed) == 1
    assert commits and announced
    assert saved[-1].status == "accepted"
    assert saved[-1].initiated_by == "cpu"


def test_cpu_cpu_counter_round_accepted(monkeypatch, tmp_path):
    calls: list[object] = []

    def _eval(trade, **_kw):
        calls.append(trade)
        if len(calls) == 1:
            return SimpleNamespace(
                action="counter",
                total_score=0.5,
                threshold=0.6,
                counter_offer={
                    "incoming_player_ids": ["CPUA_p"],
                    "outgoing_player_ids": ["CPUB_p"],
                    "incoming_pick_ids": [],
                    "outgoing_pick_ids": [],
                },
            )
        return SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        )

    saved, commits, _ = _wire_cpu_cpu(
        monkeypatch,
        teams=_CPU_TEAMS,
        outlooks={"CPUA": "contend", "CPUB": "bubble"},
        evaluate=_eval,
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(1)
    )
    executed = result["cpu_cpu_trades"]["executed"]
    assert len(executed) == 1
    assert len(calls) == 2  # receiver counters, proposer accepts
    # Executed package == the counter package (receiver ships CPUB_p for CPUA_p).
    assert saved[-1].give_player_ids == ["CPUB_p"]
    assert saved[-1].receive_player_ids == ["CPUA_p"]
    assert saved[-1].from_team == "CPUB" and saved[-1].to_team == "CPUA"


def test_cpu_cpu_counter_round_dropped(monkeypatch, tmp_path):
    calls: list[object] = []

    def _eval(trade, **_kw):
        calls.append(trade)
        if len(calls) == 1:
            return SimpleNamespace(
                action="counter",
                total_score=0.5,
                threshold=0.6,
                counter_offer={
                    "incoming_player_ids": ["CPUA_p"],
                    "outgoing_player_ids": ["CPUB_p"],
                    "incoming_pick_ids": [],
                    "outgoing_pick_ids": [],
                },
            )
        return SimpleNamespace(
            action="reject", total_score=0.0, threshold=0.6, counter_offer=None
        )

    _saved, commits, _ = _wire_cpu_cpu(
        monkeypatch,
        teams=_CPU_TEAMS,
        outlooks={"CPUA": "contend", "CPUB": "bubble"},
        evaluate=_eval,
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(1)
    )
    assert result["cpu_cpu_trades"]["executed"] == []
    assert result["cpu_cpu_trades"]["filtered"]["counter_dropped"] >= 1
    assert not commits


def test_cpu_cpu_weekly_cap(monkeypatch, tmp_path):
    (tmp_path / "cpu_trade_proposal_state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "alpha": {"cpu_cpu_executions": ["2026-07-07", "2026-07-07"]}
                },
            }
        ),
        encoding="utf-8",
    )
    _saved, commits, _ = _wire_cpu_cpu(
        monkeypatch,
        teams=_CPU_TEAMS,
        outlooks={"CPUA": "contend", "CPUB": "contend"},
        evaluate=lambda *_a, **_kw: SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        ),
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-10"], data_dir=tmp_path, rng=random.Random(1)
    )
    assert result["cpu_cpu_trades"]["filtered"]["weekly_cap"] == 1
    assert result["cpu_cpu_trades"]["executed"] == []
    assert not commits


def test_cpu_cpu_team_cooldown(monkeypatch, tmp_path):
    (tmp_path / "cpu_trade_proposal_state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "alpha": {
                        "cpu_cpu_last_trade_dates": {
                            "CPUA": "2026-07-05",
                            "CPUB": "2026-07-05",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _saved, commits, _ = _wire_cpu_cpu(
        monkeypatch,
        teams=_CPU_TEAMS,
        outlooks={"CPUA": "contend", "CPUB": "bubble"},
        evaluate=lambda *_a, **_kw: SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        ),
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(1)
    )
    assert result["cpu_cpu_trades"]["executed"] == []
    assert not commits


def test_cpu_cpu_payroll_block(monkeypatch, tmp_path):
    _saved, commits, _ = _wire_cpu_cpu(
        monkeypatch,
        teams=_CPU_TEAMS,
        outlooks={"CPUA": "contend", "CPUB": "bubble"},
        evaluate=lambda *_a, **_kw: SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        ),
    )
    monkeypatch.setattr(
        "services.payroll_policy.evaluate_trade_payroll_impact",
        lambda *_a, **_kw: SimpleNamespace(allowed=False),
    )
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=tmp_path, rng=random.Random(1)
    )
    assert result["cpu_cpu_trades"]["executed"] == []
    assert result["cpu_cpu_trades"]["filtered"]["payroll_blocked"] >= 1
    assert not commits


def test_cpu_cpu_never_touches_humans(monkeypatch, tmp_path):
    from datetime import date, timedelta

    teams = [
        SimpleNamespace(team_id="HUM1", owner_id="owner"),
        SimpleNamespace(team_id="HUM2", owner_id="owner"),
        SimpleNamespace(team_id="CPUA", owner_id="cpu"),
        SimpleNamespace(team_id="CPUB", owner_id="cpu"),
        SimpleNamespace(team_id="CPUC", owner_id="cpu"),
    ]
    _saved, commits, _ = _wire_cpu_cpu(
        monkeypatch,
        teams=teams,
        outlooks={"CPUA": "contend", "CPUB": "rebuild", "CPUC": "contend"},
        evaluate=lambda *_a, **_kw: SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        ),
    )
    cpu_ids = {"CPUA", "CPUB", "CPUC"}
    d0 = date(2026, 4, 1)
    for i in range(50):
        run_cpu_trade_proposal_cycle(
            simulated_dates=[(d0 + timedelta(days=i * 3)).isoformat()],
            data_dir=tmp_path,
            rng=random.Random(i),
        )
    assert commits, "expected at least one CPU-CPU execution"
    for trade in commits:
        assert trade.from_team in cpu_ids and trade.to_team in cpu_ids
