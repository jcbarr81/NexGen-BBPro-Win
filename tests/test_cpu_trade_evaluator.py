from __future__ import annotations

from types import SimpleNamespace

from models.trade import Trade
from services.cpu_trade_evaluator import evaluate_cpu_trade_offer


def _hitter(
    player_id: str,
    *,
    age: int,
    ch: int,
    ph: int,
    sp: int = 50,
    fa: int = 50,
    arm: int = 50,
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
        sp=sp,
        pl=ch,
        vl=ch,
        sc=ch,
        fa=fa,
        arm=arm,
        gf=55,
        pot_ch=min(99, ch + pot_delta),
        pot_ph=min(99, ph + pot_delta),
        pot_sp=min(99, sp + pot_delta),
        pot_fa=min(99, fa + pot_delta),
        pot_arm=min(99, arm + pot_delta),
        pot_sc=min(99, ch + pot_delta),
        pot_gf=min(99, 55 + pot_delta),
        injured=False,
    )


def test_cpu_trade_evaluator_accepts_rebuild_upside_offer():
    trade = Trade(
        trade_id="t1",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["YOUNG_STAR"],
        receive_player_ids=["OLD_VET"],
    )
    players = {
        "YOUNG_STAR": _hitter(
            "YOUNG_STAR",
            age=22,
            ch=81,
            ph=76,
            pot_delta=12,
            primary_position="CF",
        ),
        "OLD_VET": _hitter(
            "OLD_VET",
            age=35,
            ch=67,
            ph=62,
            pot_delta=0,
            primary_position="LF",
        ),
    }
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="james"),
    }
    rosters = {"CPU": SimpleNamespace(act=["OLD_VET"])}

    evaluation = evaluate_cpu_trade_offer(
        trade,
        players_by_id=players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.390},
        strategy_profile="development_focus",
        current_year=2026,
    )

    assert evaluation is not None
    assert evaluation.action == "accept"
    assert evaluation.competitive_window == "rebuild"
    assert evaluation.value_delta > 0.0
    assert any(r.tag == "value_balance" for r in evaluation.reasons)


def test_cpu_trade_evaluator_rejects_contend_downgrade():
    trade = Trade(
        trade_id="t2",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["BENCH_BAT"],
        receive_player_ids=["STAR_BAT"],
    )
    players = {
        "BENCH_BAT": _hitter(
            "BENCH_BAT",
            age=33,
            ch=56,
            ph=58,
            pot_delta=0,
            primary_position="1B",
        ),
        "STAR_BAT": _hitter(
            "STAR_BAT",
            age=28,
            ch=89,
            ph=88,
            pot_delta=2,
            primary_position="1B",
        ),
    }
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="human"),
    }
    rosters = {"CPU": SimpleNamespace(act=["STAR_BAT"])}

    evaluation = evaluate_cpu_trade_offer(
        trade,
        players_by_id=players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.640},
        strategy_profile="win_now",
        current_year=2026,
    )

    assert evaluation is not None
    assert evaluation.action == "reject"
    assert evaluation.competitive_window == "contend"
    assert evaluation.total_score < evaluation.threshold


def test_cpu_trade_evaluator_values_rebuild_draft_capital():
    trade = Trade(
        trade_id="t3",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["P_EQ_1"],
        receive_player_ids=["P_EQ_2"],
        give_pick_ids=["2027|1|HUM"],
        receive_pick_ids=["2027|8|CPU"],
    )
    players = {
        "P_EQ_1": _hitter(
            "P_EQ_1",
            age=27,
            ch=70,
            ph=69,
            pot_delta=1,
            primary_position="2B",
        ),
        "P_EQ_2": _hitter(
            "P_EQ_2",
            age=27,
            ch=70,
            ph=69,
            pot_delta=1,
            primary_position="2B",
        ),
    }
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="owner"),
    }
    rosters = {"CPU": SimpleNamespace(act=["P_EQ_2"])}

    evaluation = evaluate_cpu_trade_offer(
        trade,
        players_by_id=players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.420},
        strategy_profile="development_focus",
        current_year=2026,
    )

    assert evaluation is not None
    assert evaluation.action == "accept"
    assert evaluation.details.get("incoming_picks") == 1
    assert any(r.tag == "draft_capital" for r in evaluation.reasons)


def test_cpu_trade_evaluator_returns_none_for_human_target():
    trade = Trade(
        trade_id="t4",
        from_team="CPU",
        to_team="HUM",
        give_player_ids=["A"],
        receive_player_ids=["B"],
    )
    teams = {"HUM": SimpleNamespace(team_id="HUM", owner_id="owner")}

    evaluation = evaluate_cpu_trade_offer(
        trade,
        players_by_id={},
        teams_by_id=teams,
        rosters_by_team={},
        strategy_profile="balanced",
    )

    assert evaluation is None


def test_cpu_trade_evaluator_generates_counter_for_close_offer(monkeypatch):
    import services.cpu_trade_evaluator as evaluator

    monkeypatch.setattr(evaluator, "_decision_variation", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(evaluator, "_player_current_value", lambda _player: 1.0)
    monkeypatch.setattr(
        evaluator,
        "_fit_value",
        lambda *_args, **_kwargs: 0.0,
    )
    monkeypatch.setattr(
        evaluator,
        "_timeline_value",
        lambda *_args, **_kwargs: 0.0,
    )
    monkeypatch.setattr(evaluator, "_pick_value", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(
        evaluator,
        "_pick_timeline_bonus",
        lambda *_args, **_kwargs: 0.0,
    )

    trade = Trade(
        trade_id="t5",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["MID_A"],
        receive_player_ids=["MID_B", "EXTRA_BAT"],
    )
    players = {
        "MID_A": _hitter(
            "MID_A",
            age=27,
            ch=72,
            ph=70,
            pot_delta=2,
            primary_position="2B",
        ),
        "MID_B": _hitter(
            "MID_B",
            age=28,
            ch=75,
            ph=73,
            pot_delta=1,
            primary_position="2B",
        ),
        "EXTRA_BAT": _hitter(
            "EXTRA_BAT",
            age=30,
            ch=64,
            ph=67,
            pot_delta=0,
            primary_position="LF",
        ),
    }
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="owner"),
    }
    rosters = {
        "CPU": SimpleNamespace(act=["MID_B", "EXTRA_BAT"]),
        "HUM": SimpleNamespace(act=["MID_A"]),
    }

    evaluation = evaluator.evaluate_cpu_trade_offer(
        trade,
        players_by_id=players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.515},
        strategy_profile="balanced",
        current_year=2026,
    )

    assert evaluation is not None
    assert evaluation.action == "counter"
    assert isinstance(evaluation.counter_offer, dict)
    assert evaluation.counter_offer.get("incoming_player_ids")
    assert evaluation.counter_offer.get("outgoing_player_ids")


def test_cpu_trade_evaluator_can_disable_counter_generation(monkeypatch):
    import services.cpu_trade_evaluator as evaluator

    monkeypatch.setattr(evaluator, "_decision_variation", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(evaluator, "_player_current_value", lambda _player: 1.0)
    monkeypatch.setattr(
        evaluator,
        "_fit_value",
        lambda *_args, **_kwargs: 0.0,
    )
    monkeypatch.setattr(
        evaluator,
        "_timeline_value",
        lambda *_args, **_kwargs: 0.0,
    )
    monkeypatch.setattr(evaluator, "_pick_value", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(
        evaluator,
        "_pick_timeline_bonus",
        lambda *_args, **_kwargs: 0.0,
    )

    trade = Trade(
        trade_id="t6",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["MID_A"],
        receive_player_ids=["MID_B", "EXTRA_BAT"],
    )
    players = {
        "MID_A": _hitter(
            "MID_A",
            age=27,
            ch=72,
            ph=70,
            pot_delta=2,
            primary_position="2B",
        ),
        "MID_B": _hitter(
            "MID_B",
            age=28,
            ch=75,
            ph=73,
            pot_delta=1,
            primary_position="2B",
        ),
        "EXTRA_BAT": _hitter(
            "EXTRA_BAT",
            age=30,
            ch=64,
            ph=67,
            pot_delta=0,
            primary_position="LF",
        ),
    }
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="owner"),
    }
    rosters = {
        "CPU": SimpleNamespace(act=["MID_B", "EXTRA_BAT"]),
        "HUM": SimpleNamespace(act=["MID_A"]),
    }

    evaluation = evaluator.evaluate_cpu_trade_offer(
        trade,
        players_by_id=players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.515},
        strategy_profile="balanced",
        current_year=2026,
        allow_counter_offers=False,
    )

    assert evaluation is not None
    assert evaluation.action == "reject"
    assert evaluation.counter_offer is None


def test_timeline_weight_factor_scales_score():
    # S2-09: the deadline reweight amplifies the 0.12 timeline weight. Two
    # evaluations of the same trade differ in total_score by exactly
    # (0.18 - 0.12) * timeline_delta == 0.06 * timeline_delta.
    trade = Trade(
        trade_id="tw1",
        from_team="HUM",
        to_team="CPU",
        give_player_ids=["YOUNG_STAR"],
        receive_player_ids=["OLD_VET"],
    )
    players = {
        "YOUNG_STAR": _hitter("YOUNG_STAR", age=22, ch=81, ph=76, pot_delta=12),
        "OLD_VET": _hitter("OLD_VET", age=35, ch=67, ph=62, primary_position="LF"),
    }
    teams = {
        "CPU": SimpleNamespace(team_id="CPU", owner_id="cpu"),
        "HUM": SimpleNamespace(team_id="HUM", owner_id="james"),
    }
    rosters = {"CPU": SimpleNamespace(act=["OLD_VET"])}
    kwargs = dict(
        players_by_id=players,
        teams_by_id=teams,
        rosters_by_team=rosters,
        win_pct_by_team={"CPU": 0.390},
        strategy_profile="development_focus",
        current_year=2026,
    )

    base = evaluate_cpu_trade_offer(trade, timeline_weight_factor=1.0, **kwargs)
    boosted = evaluate_cpu_trade_offer(trade, timeline_weight_factor=1.5, **kwargs)

    assert base is not None and boosted is not None
    assert base.timeline_delta == boosted.timeline_delta
    assert abs(base.timeline_delta) > 0.0
    assert boosted.total_score - base.total_score == \
        __import__("pytest").approx(0.06 * base.timeline_delta)
