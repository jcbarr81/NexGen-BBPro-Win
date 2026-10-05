"""A big-league game is played by the active roster.

From 3.2.12 the game's player pool was the whole organisation (ACT, AAA, LOW,
DL and IR). The default lineup was the best nine hitters at any level, the
bench and bullpen held everyone else -- benches ~21 deep, bullpens 24-27 arms
on alpha-test -- and league creation wrote those lineups to disk, so half the
CPU clubs started 3-5 minor leaguers in every game of 2026, and a player on the
15-day DL played all 71.
"""

from pathlib import Path

import pytest

import utils.lineup_loader as LL
from models.roster import Roster
from utils.pitcher_role import get_role
from utils.player_loader import load_players_from_csv

PLAYERS = Path(__file__).resolve().parents[1] / "data" / "players.csv"


@pytest.fixture(scope="module")
def pool():
    players = load_players_from_csv(str(PLAYERS))
    hitters = [p for p in players if get_role(p) not in {"SP", "RP"}]
    pitchers = [p for p in players if get_role(p) in {"SP", "RP"}]
    hitters.sort(key=lambda p: getattr(p, "ph", 0))  # weakest first
    pitchers.sort(key=lambda p: getattr(p, "endurance", 0))
    return hitters, pitchers


@pytest.fixture
def team(monkeypatch, tmp_path):
    """Build a team from explicit level lists and return its game state."""

    def build(act, aaa=(), low=(), dl=(), ir=()):
        roster = Roster(
            "TST",
            act=[p.player_id for p in act],
            aaa=[p.player_id for p in aaa],
            low=[p.player_id for p in low],
            dl=[p.player_id for p in dl],
            ir=[p.player_id for p in ir],
        )
        monkeypatch.setattr(LL, "load_roster", lambda *a, **k: roster)
        return LL.build_default_game_state(
            "TST", players_file=str(PLAYERS), roster_dir=str(tmp_path), teams_file=""
        )

    return build


def _ids(players):
    return {p.player_id for p in players}


def test_minor_leaguers_and_injured_players_stay_out(pool, team):
    hitters, pitchers = pool
    weak_act = hitters[:13] + pitchers[:12]
    # The organisation's BEST players are all in the minors or hurt.
    star_aaa, star_low, hurt_dl, hurt_ir = hitters[-3:], hitters[-6:-3], hitters[-8:-6], hitters[-9:-8]
    arm_aaa = pitchers[-4:]
    state = team(weak_act, aaa=star_aaa + arm_aaa, low=star_low, dl=hurt_dl, ir=hurt_ir)

    in_game = _ids(state.lineup) | _ids(state.bench) | _ids(state.pitchers)
    assert in_game == _ids(weak_act)
    assert len(state.lineup) == 9
    assert len(state.bench) == 4
    assert len(state.pitchers) == 12


def test_a_short_active_roster_borrows_its_best_healthy_minor_leaguers(pool, team):
    hitters, pitchers = pool
    act = hitters[:7] + pitchers[:12]               # only 7 hitters active
    aaa = hitters[20:22] + hitters[-1:]             # best minor leaguer is hitters[-1]
    state = team(act, aaa=aaa, dl=hitters[-2:-1])   # an even better one is injured
    lineup = _ids(state.lineup)
    assert len(lineup) == 9
    assert _ids(hitters[:7]) <= lineup
    assert hitters[-1].player_id in lineup          # the best healthy minor leaguer
    assert hitters[-2].player_id not in lineup      # never the injured one
    assert _ids(state.bench) == set()               # nobody else comes up


def test_with_no_active_pitchers_the_minors_supply_the_staff(pool, team):
    hitters, pitchers = pool
    state = team(hitters[:10], aaa=pitchers[:3], low=pitchers[3:5])
    assert _ids(state.pitchers) == _ids(pitchers[:5])
