from models.pitcher import Pitcher
from models.roster import Roster
import playbalance.game_runner as game_runner


def _make_pitcher(pid: str) -> Pitcher:
    return Pitcher(
        player_id=pid,
        first_name="Pitch",
        last_name=pid,
        birthdate="1995-01-01",
        height=74,
        weight=200,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=0,
        endurance=70,
        control=60,
        movement=60,
        hold_runner=40,
        role="SP",
        preferred_pitching_role="SP",
        fb=60,
        cu=50,
        cb=50,
        sl=50,
        si=45,
        scb=40,
        kn=35,
        arm=60,
        fa=50,
    )


def test_apply_injury_events_never_caps_the_pitcher_il(monkeypatch):
    """Release 3 (audit M15): every pitcher IL stint stands.

    The old cap (MAX_PITCHERS_ON_DL, 5) turned the sixth stint into a
    day-to-day knock, leaving a hurt pitcher free to pitch the next day.
    """
    pitchers = [_make_pitcher(f"P{i}") for i in range(1, 9)]
    players_store = {"players": list(pitchers)}
    roster = Roster(
        team_id="TST", act=[p.player_id for p in pitchers], aaa=[], low=[],
        dl=[], ir=[], dl_tiers={},
    )

    monkeypatch.setattr(game_runner, "load_players_from_csv", lambda _: list(players_store["players"]))
    monkeypatch.setattr(game_runner, "save_players", lambda players, __: players_store.__setitem__("players", list(players)))
    monkeypatch.setattr(game_runner, "load_roster", lambda team_id, roster_dir=None: roster)
    monkeypatch.setattr(game_runner, "save_roster", lambda team_id, updated: None)
    assert not hasattr(game_runner, "MAX_PITCHERS_ON_DL")

    events = [
        {"team_id": "TST", "player_id": f"P{i}", "dl_tier": "dl15", "days": 12, "description": "Elbow"}
        for i in range(1, 8)
    ]

    game_runner._apply_injury_events(
        events,
        players_file="ignored.csv",
        roster_dir="unused",
        game_date="2025-04-01",
    )

    assert {f"P{i}" for i in range(1, 8)} == set(roster.dl)
    assert all(e["dl_tier"] == "dl15" for e in events)
    for player in players_store["players"][:7]:
        assert player.injury_list == "il15"
        assert "day-to-day" not in (player.injury_description or "")
