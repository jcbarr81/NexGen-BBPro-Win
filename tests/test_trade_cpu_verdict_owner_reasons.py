"""A CPU club's verdict on a trade carries plain-words reasons (8.13.0).

The trade card showed owners the evaluator's own notes ("Incoming vs outgoing
value delta scored +6.99", "strategy profile 'balanced'"), while the
acceptance meter in the same dialog said "They'd come out ahead on talent".
The stored verdict now keeps both: ``reasons`` for the commissioner and
``owner_reasons`` in the meter's words.
"""

from __future__ import annotations

from services.cpu_trade_evaluator import CpuTradeEvaluation, DecisionReason


def _evaluation(**over):
    base = dict(
        team_id="LAS",
        action="accept",
        total_score=5.03,
        threshold=0.65,
        value_delta=6.99,
        fit_delta=-0.6,
        timeline_delta=3.28,
        strategy_profile="balanced",
        competitive_window="balanced",
        reasons=[],
        details={"roster_needs": []},
    )
    base.update(over)
    return CpuTradeEvaluation(**base)


def test_the_verdict_keeps_the_notes_and_adds_plain_reasons():
    from api.routers.trades import _cpu_response

    out = _cpu_response(_evaluation())
    assert out["action"] == "accept"
    assert out["team_id"] == "LAS"
    assert out["owner_reasons"] == [
        "They'd come out ahead on talent in this deal.",
        "It doesn't fit what their roster needs right now.",
        "The player ages fit their timeline well.",
    ]
    for reason in out["owner_reasons"]:
        assert "delta" not in reason and "score" not in reason


def test_the_evaluator_notes_are_still_there_for_the_commissioner():
    from api.routers.trades import _cpu_response

    note = DecisionReason(tag="value", message="Incoming vs outgoing value delta scored +6.99")
    out = _cpu_response(_evaluation(reasons=[note]))
    assert out["reasons"] == ["Incoming vs outgoing value delta scored +6.99"]
    assert out["total_score"] == 5.03 and out["threshold"] == 0.65


def test_a_failing_plain_reason_builder_never_loses_the_verdict(monkeypatch):
    import services.cpu_trade_evaluator as ev
    from api.routers.trades import _cpu_response

    def boom(_evaluation):
        raise ValueError("broken")

    monkeypatch.setattr(ev, "owner_facing_reasons", boom)
    out = _cpu_response(_evaluation(action="reject"))
    assert out["action"] == "reject"
    assert out["owner_reasons"] == []
