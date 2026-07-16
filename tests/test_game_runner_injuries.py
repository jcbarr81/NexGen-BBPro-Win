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


def test_apply_injury_events_caps_pitcher_dl(monkeypatch):
    pitchers = [_make_pitcher(f"P{i}") for i in range(1, 5)]
    players_store = {"players": list(pitchers)}
    roster = Roster(team_id="TST", act=["P1", "P2", "P3", "P4"], aaa=[], low=[], dl=[], ir=[], dl_tiers={})

    monkeypatch.setattr(game_runner, "load_players_from_csv", lambda _: list(players_store["players"]))
    monkeypatch.setattr(game_runner, "save_players", lambda players, __: players_store.__setitem__("players", list(players)))
    monkeypatch.setattr(game_runner, "load_roster", lambda team_id, roster_dir=None: roster)
    monkeypatch.setattr(game_runner, "save_roster", lambda team_id, updated: None)
    monkeypatch.setattr(game_runner, "MAX_PITCHERS_ON_DL", 2)
    monkeypatch.setattr(game_runner, "DAY_TO_DAY_MAX_DAYS", 3)

    events = [
        {"team_id": "TST", "player_id": "P1", "dl_tier": "dl15", "days": 12, "description": "Elbow"},
        {"team_id": "TST", "player_id": "P2", "dl_tier": "dl15", "days": 14, "description": "Shoulder"},
        {"team_id": "TST", "player_id": "P3", "dl_tier": "dl15", "days": 10, "description": "Forearm"},
    ]

    game_runner._apply_injury_events(
        events,
        players_file="ignored.csv",
        roster_dir="unused",
        game_date="2025-04-01",
    )

    assert {"P1", "P2"}.issubset(set(roster.dl))
    assert "P3" not in roster.dl

    players = players_store["players"]
    day_to_day = next(p for p in players if p.player_id == "P3")
    assert day_to_day.injured is True
    assert (day_to_day.injury_description or "").endswith("(day-to-day)")
    assert not day_to_day.injury_list
