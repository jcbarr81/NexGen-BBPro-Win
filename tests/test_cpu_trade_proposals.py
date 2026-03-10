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
