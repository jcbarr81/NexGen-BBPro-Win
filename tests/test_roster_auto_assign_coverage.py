"""Auto-assign must never release the LAST eligible player for a required
defensive position (bug: a cut left a team with no 2B). The coverage guard
rescues such a player back into the minors instead of releasing them.
"""

from types import SimpleNamespace

from models.roster import Roster
from services import roster_auto_assign as ra


def _hitter(pid, pos, ovr):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=False,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, arm=ovr, gf=ovr, eye=ovr, birthdate="1998-06-15",
    )


def _arm(pid, ovr, pos="P", is_pitcher=True):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=is_pitcher,
        arm=ovr, control=ovr, movement=ovr, endurance=ovr, fb=ovr,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, gf=ovr, eye=ovr, birthdate="1998-06-15",
    )


def test_last_2b_is_rescued_not_released(monkeypatch):
    # Big org (58 > the 50-slot cap so some are released), coverage for every
    # required position EXCEPT 2B among the hitters. The only 2B is mis-flagged
    # as a pitcher with terrible ratings — without the guard it gets cut.
    hitters = [_hitter(f"{pos}1", pos, 70) for pos in ("C", "SS", "CF", "3B", "1B", "LF", "RF")]
    hitters += [_hitter(f"EX{i}", "1B", 60) for i in range(20)]
    pitchers = [_arm(f"PIT{i}", 70) for i in range(30)]
    only_2b = _arm("SECOND", 15, pos="2B", is_pitcher=True)  # the lone 2B, would be cut
    everyone = hitters + pitchers + [only_2b]
    players = {p.player_id: p for p in everyone}
    roster = Roster(team_id="AAA", act=[p.player_id for p in everyone])

    saved = {}
    monkeypatch.setattr(ra, "load_roster", lambda *a, **k: roster)
    monkeypatch.setattr(ra, "save_roster", lambda tid, r, **k: saved.update(r=r))
    monkeypatch.setattr(ra, "_resolve_strategy_profile_token", lambda *a, **k: "balanced")
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    monkeypatch.setattr(
        "services.contracts_service.release_contracts_to_free_agency", lambda ids: None
    )

    result = ra.auto_assign_team("AAA", players_by_id=players)

    r = saved["r"]
    assigned = set(r.act) | set(r.aaa) | set(r.low) | set(r.dl) | set(r.ir)
    assert result["released"], "scenario should release the over-cap overflow"
    assert "SECOND" not in result["released"], "the last 2B must not be cut"
    assert "SECOND" in assigned, "the last 2B must stay on the roster"
    # A player eligible at 2B must be assigned somewhere.
    assert any(
        "2B" in ra._eligible_positions(players[pid]) for pid in assigned if pid in players
    )
