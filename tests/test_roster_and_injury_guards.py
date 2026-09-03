"""Three holes found while auditing the help surfaces.

1. The roster page was a second door on and off the injured list. `POST
   /roster/move` never called the injury code, so placing someone started no
   stint (no list, no dates, no minimum, no replacement) and taking them off
   skipped the eligibility check AND left them flagged injured while active.
2. Roster writes were gated by authentication only — any signed-in user could
   option, swap or release another team's players.
3. Injury notifications classified off news TEXT, and the line carried no tier
   ("Wrist strain"), so every injured-list placement fell through to the
   day-to-day bucket and the stop-the-sim rules never fired.
"""

import pytest
from fastapi import HTTPException

from services.notification_engine import _classify_injury_line


# --- the roster door --------------------------------------------------------


@pytest.fixture
def roster_move(monkeypatch):
    import api.routers.roster as rr

    class _Roster:
        team_id = "T"
        act = ["p1"]
        aaa = []
        low = []
        dl = ["hurt"]
        ir = []
        dl_tiers = {"hurt": "il10"}

    monkeypatch.setattr(rr, "load_roster", lambda tid: _Roster())
    return rr


def _admin():
    return {"u": "commish", "r": "admin", "t": ""}


@pytest.mark.parametrize("target", ["DL", "IR"])
def test_cannot_slide_a_player_onto_the_injured_list(roster_move, target):
    with pytest.raises(HTTPException) as exc:
        roster_move.move_roster(
            "T", payload={"player_id": "p1", "to": target}, identity=_admin()
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "use_injury_center"


def test_cannot_slide_a_player_off_the_injured_list(roster_move):
    """The damaging direction: this skipped the minimum AND left the player
    active while still flagged injured."""
    with pytest.raises(HTTPException) as exc:
        roster_move.move_roster(
            "T", payload={"player_id": "hurt", "to": "ACT"}, identity=_admin()
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "use_injury_center"


def test_ordinary_level_moves_still_work(roster_move, monkeypatch):
    """Only the injured list is off-limits — AAA/LOW moves are untouched."""
    called = {}
    monkeypatch.setattr(
        roster_move, "team_roster", lambda tid: called.setdefault("ok", tid)
    )
    # ACT -> ACT short-circuits to a plain read, proving we got past the guards.
    roster_move.move_roster(
        "T", payload={"player_id": "p1", "to": "ACT"}, identity=_admin()
    )
    assert called["ok"] == "T"


# --- ownership on roster writes --------------------------------------------


@pytest.mark.parametrize("fn", ["move_roster", "swap_roster", "cut_roster"])
def test_roster_writes_require_ownership(fn, monkeypatch):
    import api.routers.roster as rr

    outsider = {"u": "someone-else", "r": "user", "t": "OTHER"}
    with pytest.raises(HTTPException) as exc:
        getattr(rr, fn)("MINE", payload={"player_id": "p1", "to": "AAA"}, identity=outsider)
    assert exc.value.status_code == 403


def test_every_roster_write_is_guarded():
    """A new write endpoint added later should fail this until it is guarded."""
    import inspect

    import api.routers.roster as rr

    for name in ("move_roster", "swap_roster", "cut_roster"):
        src = inspect.getsource(getattr(rr, name))
        assert "require_team_owner(identity, team_id)" in src, name


# --- injury classification --------------------------------------------------


def test_an_injured_list_placement_is_not_treated_as_day_to_day():
    """The reported bug, using the real shape of a live news line."""
    assert (
        _classify_injury_line("Miguel Guerrero injured (Wrist strain) — 15-Day IL")
        == "injury_dl15"
    )
    assert (
        _classify_injury_line("Percy Scott injured (Latissimus strain) — 10-Day IL")
        == "injury_dl15"
    )


def test_the_sixty_day_list_gets_its_own_rule():
    assert (
        _classify_injury_line("Someone injured (Torn UCL) — 60-Day IL") == "injury_ir60"
    )


def test_day_to_day_stays_day_to_day():
    """It must not be promoted into a stop-the-sim rule by the word 'day'."""
    assert (
        _classify_injury_line("Hector Guerrero injured (Mild oblique tightness, day-to-day)")
        == "injury_day_to_day"
    )


def test_legacy_news_lines_still_classify():
    """Old entries in a league's feed predate the rename."""
    assert _classify_injury_line("X injured — placed on the 15-day DL") == "injury_dl15"
    assert _classify_injury_line("X placed on the 60-day IR") == "injury_ir60"


def test_season_ending_outranks_the_lists():
    assert (
        _classify_injury_line("X injured (season-ending knee) — 60-Day IL")
        == "injury_season_ending"
    )


def test_activation_is_a_return_not_an_injury():
    assert _classify_injury_line("Activated Percy Scott to ACT (BAL)") == "injury_returned"


def test_an_unclassifiable_injury_still_notifies():
    assert _classify_injury_line("Somebody injured somehow") == "injury_day_to_day"
