"""Backlog #52 (8.6.4): the CPU's remaining scores use the shared overall.

The draft board and auto-pick, the CPU free-agent signing order, CPU trade
proposals, retirement and in-season call-ups each used their own flat mean
(arm and endurance in for pitchers, eye out); they now score players with
``utils.player_overall.player_overall_score``, so a hard thrower with poor
command is no longer ranked like a good pitcher.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routers import draft as draft_router
from services import cpu_trade_proposals, free_agency, inseason_callups
from services import player_retirement
from utils.player_overall import player_overall_score


def _pitcher(pid, *, arm, control, movement, endurance=40, as_row=False):
    fields = dict(player_id=pid, is_pitcher=True, primary_position="P",
                  arm=arm, control=control, movement=movement,
                  endurance=endurance, fb=50, sl=50, cb=0, ch=0, si=0, cu=0)
    return fields if as_row else SimpleNamespace(**fields)


def _hitter(pid, *, ch, ph, eye=50, sp=50, fa=50, arm=50, pos="LF", as_row=False):
    fields = dict(player_id=pid, is_pitcher=False, primary_position=pos,
                  ch=ch, ph=ph, eye=eye, sp=sp, fa=fa, arm=arm)
    return fields if as_row else SimpleNamespace(**fields)


# A hard thrower without command, and a soft-tossing command pitcher.
THROWER = dict(arm=85, control=38, movement=40, endurance=80)
COMMAND = dict(arm=40, control=62, movement=60, endurance=40)


SCORES = [
    ("free agency", free_agency._quality_score),
    ("trade proposals", cpu_trade_proposals._player_trade_value),
    ("retirement", player_retirement._player_overall),
    ("call-ups", inseason_callups._score),
]


@pytest.mark.parametrize("name,score", SCORES, ids=[s[0] for s in SCORES])
def test_each_score_is_the_shared_overall(name, score):
    for player in (
        _pitcher("P1", **THROWER),
        _pitcher("P2", **COMMAND),
        _hitter("H1", ch=60, ph=55, pos="SS"),
        _hitter("H2", ch=40, ph=45, eye=70, sp=80),
    ):
        assert score(player) == pytest.approx(player_overall_score(player), abs=0.5)


@pytest.mark.parametrize("name,score", SCORES, ids=[s[0] for s in SCORES])
def test_command_beats_a_hard_thrower(name, score):
    assert score(_pitcher("P2", **COMMAND)) > score(_pitcher("P1", **THROWER))


def test_the_draft_auto_pick_takes_command_over_velocity():
    thrower = _pitcher("D1", **THROWER, as_row=True)
    command = _pitcher("D2", **COMMAND, as_row=True)
    assert draft_router._prospect_overall(command) > draft_router._prospect_overall(thrower)
    assert draft_router._prospect_overall(command) == round(player_overall_score(command))


def test_a_prospect_shows_the_overall_he_keeps_once_drafted():
    """The board (a pool row) and the drafted player (an object) show the
    same overall on either scale."""

    from api.routers._rating_presentation import compute_overall

    row = _hitter("D3", ch=58, ph=52, pos="SS", as_row=True)
    drafted = SimpleNamespace(**row)
    for scale in (1, 2):
        board = draft_router._prospect_shown_overall(row, False, scale)
        kept = compute_overall(
            lambda k: getattr(drafted, k, None),
            is_pitcher=False,
            position="SS",
            scale=scale,
        )
        assert board["overall_display"] == kept["overall_display"]


def test_call_ups_send_down_the_weaker_player_across_hitters_and_pitchers():
    """One footing: a decent pitcher no longer looks worse than a weak
    hitter because his flat mean counted a low arm."""

    pitcher = _pitcher("P3", arm=35, control=58, movement=57)
    hitter = _hitter("H3", ch=42, ph=40)
    assert inseason_callups._score(hitter) < inseason_callups._score(pitcher)


def test_missing_ratings_keep_their_old_fallbacks():
    blank = SimpleNamespace(player_id="X", is_pitcher=True, primary_position="P")
    assert free_agency._quality_score(blank) == 55
    assert cpu_trade_proposals._player_trade_value(blank) == 45.0
    assert cpu_trade_proposals._player_trade_value(None) == 0.0
    assert player_retirement._player_overall(blank) == 50
    assert inseason_callups._score(blank) == 0.0
    assert draft_router._prospect_overall({"player_id": "X"}) == 0
