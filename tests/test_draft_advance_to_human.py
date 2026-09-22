"""Advancing the draft must never spend an owner's pick for him.

With seven human owners drafting 11th through 20th, the commissioner had no
way to move the draft along: ``end_of_round`` drafted for all of them, and
``my_pick`` only ever stopped at one named team. ``next_human`` stops at
whichever real person is up next, and every other mode now stops there too
unless the caller explicitly asks to pick for everyone.
"""

import pytest

import api.routers.draft as D

ADMIN = {"u": "commish", "r": "admin", "mr": "admin", "t": ""}
ORDER = ["CHA", "ELP", "DAL", "BAL", "ALB", "MIL"]  # BAL and MIL are people
HUMANS = {"BAL", "MIL"}


@pytest.fixture
def draft(monkeypatch):
    """A draft whose picks are recorded but not committed to rosters."""
    state = {"year": 2026, "round": 1, "overall_pick": 1, "order": list(ORDER), "selected": []}
    made = []

    def fake_load_state(year):
        return state

    def fake_do_pick(year, st, *, player_id, season_date=None):
        team = D._team_on_clock(st)
        made.append(team)
        st["selected"] = list(st.get("selected") or []) + [
            {"overall": st["overall_pick"], "round": st["round"], "team_id": team, "player_id": player_id}
        ]
        st["overall_pick"] = int(st["overall_pick"]) + 1
        if (st["overall_pick"] - 1) % len(ORDER) == 0:
            st["round"] = int(st["round"]) + 1
        return {"team_id": team, "player_id": player_id}

    monkeypatch.setattr(D.draft_state, "load_state", fake_load_state)
    monkeypatch.setattr(D, "_do_pick", fake_do_pick)
    monkeypatch.setattr(D, "_best_available", lambda y, s: {"player_id": f"P{s['overall_pick']}"})
    monkeypatch.setattr(D, "_load_settings_rounds", lambda: 2)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids", lambda *a, **k: set(HUMANS)
    )
    return state, made


# --- the new mode ----------------------------------------------------------


def test_next_human_picks_for_cpu_teams_and_stops_at_the_owner(draft):
    state, made = draft
    result = D.auto_advance({"year": 2026, "stop": "next_human"}, identity=ADMIN)
    assert made == ["CHA", "ELP", "DAL"]
    assert result["team_on_clock"] == "BAL"
    assert result["stopped_reason"] == "human_on_clock"


def test_it_stops_immediately_when_an_owner_is_already_up(draft):
    state, made = draft
    state["overall_pick"] = 4  # BAL
    result = D.auto_advance({"year": 2026, "stop": "next_human"}, identity=ADMIN)
    assert made == []
    assert result["picks_made"] == 0
    assert result["stopped_reason"] == "human_on_clock"


def test_it_crosses_into_the_next_round(draft):
    """The last owner picks 6th of 6; the next human is back at the top."""
    state, made = draft
    state["overall_pick"] = 6  # MIL, a human
    D.auto_advance({"year": 2026, "stop": "next_human"}, identity=ADMIN)  # stops at MIL
    state["overall_pick"] = 7  # MIL has now picked; round 2 begins with CHA
    result = D.auto_advance({"year": 2026, "stop": "next_human"}, identity=ADMIN)
    assert made == ["CHA", "ELP", "DAL"]
    assert result["team_on_clock"] == "BAL"


def test_no_owner_left_means_it_runs_to_the_end(draft, monkeypatch):
    monkeypatch.setattr("services.team_ownership.human_owned_team_ids", lambda *a, **k: set())
    state, made = draft
    result = D.auto_advance({"year": 2026, "stop": "next_human"}, identity=ADMIN)
    assert result["draft_complete"] is True
    assert len(made) == len(ORDER) * 2


# --- the other modes are protected too -------------------------------------


def test_end_of_round_no_longer_drafts_for_owners(draft):
    """The regression: this used to spend every owner's pick in the round."""
    state, made = draft
    result = D.auto_advance({"year": 2026, "stop": "end_of_round"}, identity=ADMIN)
    assert "BAL" not in made and "MIL" not in made
    assert result["stopped_reason"] == "human_on_clock"


def test_my_pick_stops_at_an_earlier_owner_rather_than_drafting_for_him(draft):
    state, made = draft
    result = D.auto_advance(
        {"year": 2026, "stop": "my_pick", "team_id": "MIL"}, identity=ADMIN
    )
    assert made == ["CHA", "ELP", "DAL"]
    assert result["team_on_clock"] == "BAL"


def test_a_commissioner_can_still_force_the_draft_to_finish(draft):
    """Owners have gone quiet and the league needs to move on."""
    state, made = draft
    result = D.auto_advance(
        {"year": 2026, "stop": "end_of_draft", "include_human_teams": True},
        identity=ADMIN,
    )
    assert result["draft_complete"] is True
    assert "BAL" in made and "MIL" in made


# --- guardrails ------------------------------------------------------------


def test_an_unknown_stop_mode_is_rejected(draft):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        D.auto_advance({"year": 2026, "stop": "whenever"}, identity=ADMIN)
    assert exc.value.status_code == 400


def test_next_human_needs_no_team_id(draft):
    """Unlike my_pick -- the commissioner has no team of his own."""
    result = D.auto_advance({"year": 2026, "stop": "next_human"}, identity=ADMIN)
    assert result["target_team"] is None
