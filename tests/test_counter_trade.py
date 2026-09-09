"""Countering an offer, including one from another owner.

Reported: "I was proposed a trade and I would like to counter, but I can't
figure out how to see the rest of the team's players, especially in AAA or
LOW."

Two things were wrong. The counter dialog still used raw comma-separated
player-ID text boxes — it never got the roster pickers the Propose dialog
gained — so there was no way to browse the other roster while countering. And
countering was refused outright for anything but a CPU offer, so an owner
facing a human proposal had no way to negotiate at all: the only route was to
reject it and rebuild the trade from scratch.
"""

import inspect

import pytest


# --- the backend rule -------------------------------------------------------


def test_a_human_offer_can_be_countered():
    """The guard that refused non-CPU offers is gone."""
    from api.routers import trades

    src = inspect.getsource(trades.counter_trade)
    assert "Only CPU-initiated offers can be countered" not in src


def test_you_still_cannot_counter_a_trade_against_itself():
    from api.routers import trades

    src = inspect.getsource(trades.counter_trade)
    assert "cannot be countered against itself" in src


def test_the_counter_is_filed_from_the_recipient():
    """require_team_owner is checked against the team the offer was sent TO —
    you counter what you received, not what you sent."""
    from api.routers import trades

    src = inspect.getsource(trades.counter_trade)
    assert "require_team_owner(identity, original.to_team)" in src
    assert "owner_team = original.to_team" in src
    assert "counterparty_team = original.from_team" in src


def test_cpu_evaluation_is_conditional_on_a_cpu_counterparty():
    """A counter aimed at another owner must land in their inbox, not be
    auto-judged by the CPU evaluator."""
    from api.routers import trades

    src = inspect.getsource(trades.counter_trade)
    assert "is_cpu_owned_team(counter.to_team)" in src


# --- the dialog -------------------------------------------------------------


@pytest.fixture
def trades_page():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return (root / "desktop" / "src" / "pages" / "TradesPage.tsx").read_text(
        encoding="utf-8"
    )


def _counter_dialog(src: str) -> str:
    start = src.index("function CounterTradeDialog({")
    return src[start : start + 6000]


def test_the_counter_dialog_uses_roster_pickers(trades_page):
    body = _counter_dialog(trades_page)
    assert body.count("RosterMultiSelect") >= 2, "both sides need a picker"
    assert "api.teamRoster" in body


def test_the_counter_dialog_shows_the_acceptance_meter(trades_page):
    body = _counter_dialog(trades_page)
    assert "AcceptanceMeter" in body


def test_the_counter_dialog_no_longer_takes_typed_ids(trades_page):
    """The whole complaint: you had to know the other roster's player ids."""
    body = _counter_dialog(trades_page)
    assert "player_id, player_id" not in body
    assert "Comma- or pipe-separated" not in body


def test_typed_id_parsing_is_gone_entirely(trades_page):
    """parseIds existed only to serve those text boxes."""
    assert "parseIds" not in trades_page


def test_counter_is_offered_on_every_received_offer(trades_page):
    """The Counter button used to be gated on trade.initiated_by === "cpu".

    The badge that labels an offer as coming from the CPU is a legitimate use
    of that flag, so this checks the button specifically rather than banning
    the expression.
    """
    idx = trades_page.index("ArrowLeftRight")
    window = trades_page[max(0, idx - 900) : idx]
    assert 'initiated_by === "cpu"' not in window, (
        "the Counter button is still gated to CPU offers"
    )
