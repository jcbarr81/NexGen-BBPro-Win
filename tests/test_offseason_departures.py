"""8.1.3: owners are told by name who left their club at the rollover.

The rollover records retirements and expired contracts per club
(``services.offseason_departures``); the owner's rollover notice names them,
a club that is not short still hears who left, and the Roster page's
shortfall endpoint carries the list.
"""

from __future__ import annotations

import json

from tests.test_roster_shortfall import _news, league  # noqa: F401 (fixture)


def _contracts(root, players):
    (root / "contracts.json").write_text(
        json.dumps({"version": 1, "players": players}), encoding="utf-8"
    )


def test_record_lists_retirees_and_expired_contracts_by_club(league):  # noqa: F811
    from services.offseason_departures import (
        departures_text,
        expiring_contract_clubs,
        load_departures,
        record_departures,
    )

    build, root = league
    build("BAL", 13, 13)
    _contracts(
        root,
        {
            "BALH0": {"team_id": "BAL", "years_left": 1, "annual_salary": 1},
            "BALH1": {"team_id": "BAL", "years_left": 1, "annual_salary": 1},
            "BALP0": {"team_id": "BAL", "years_left": 1, "annual_salary": 1},
            "BALP1": {"team_id": "BAL", "years_left": 3, "annual_salary": 1},
        },
    )
    expiring = expiring_contract_clubs(data_dir=root)
    assert expiring == {"BALH0": "BAL", "BALH1": "BAL", "BALP0": "BAL"}
    # The contract step expires all three; BALH1 then accepts his club's
    # qualifying offer (his contract is back), and BALP0 also retires.
    _contracts(root, {"BALH1": {"team_id": "BAL", "years_left": 1, "annual_salary": 1}})
    record = record_departures(
        2027,
        data_dir=root,
        expiring=expiring,
        expired_ids=["BALH0", "BALH1", "BALP0"],
        retirees=[
            {"player_id": "BALP0", "team_id": "BAL", "first_name": "Old",
             "last_name": "Arm", "primary_position": "P", "age": 38},
            {"player_id": "BALP2", "team_id": "BAL", "first_name": "Ed",
             "last_name": "Lovingood", "primary_position": "P", "age": 38},
        ],
    )
    assert record["year"] == 2027
    dep = load_departures("BAL", data_dir=root)
    assert [p["name"] for p in dep["retired"]] == ["Ed Lovingood", "Old Arm"]
    assert [p["player_id"] for p in dep["contract_expired"]] == ["BALH0"]
    assert dep["contract_expired"][0]["position"] == "C"
    text = departures_text(dep)
    assert text == (
        "Retired: Ed Lovingood (P), Old Arm (P). "
        "Contract expired (now free agents): First BALH0 (C)."
    )
    assert load_departures("NYY", data_dir=root) == {
        "year": 2027, "retired": [], "contract_expired": []
    }


def _record(root, team, retired=(), expired=()):
    from services.offseason_departures import FILENAME

    entry = lambda pid, pos: {"player_id": pid, "name": pid, "position": pos, "age": 30}  # noqa: E731
    (root / FILENAME).write_text(
        json.dumps({"year": 2027, "teams": {team: {
            "retired": [entry(p, "P") for p in retired],
            "contract_expired": [entry(p, "1B") for p in expired],
        }}}),
        encoding="utf-8",
    )


def test_the_short_clubs_notice_names_who_left(league):  # noqa: F811
    from services.notification_engine import load_history
    from services.roster_shortfall import notify_owner_shortfalls

    build, root = league
    build("BAL", 12, 9, skip=("C",))
    _record(root, "BAL", retired=["OLDP"], expired=["GONE1"])
    assert notify_owner_shortfalls(expired_teams=["BAL"])["teams"] == ["BAL"]
    (line,) = _news(root)
    assert "5 active-roster spots to fill (contracts expired)" in line
    assert line.endswith("Retired: OLDP (P). Contract expired (now free agents): GONE1 (1B).")
    assert "Retired: OLDP (P)" in load_history("BAL")[0]["message"]


def test_a_full_club_that_lost_players_still_hears_who(league):  # noqa: F811
    from services.notification_engine import load_history
    from services.roster_shortfall import notify_owner_shortfalls

    build, root = league
    build("BAL", 13, 13)
    _record(root, "BAL", retired=["OLDP"])
    assert notify_owner_shortfalls(expired_teams=[])["teams"] == ["BAL"]
    (line,) = _news(root)
    assert line.endswith("BAL: left the club this offseason. Retired: OLDP (P).")
    (event,) = load_history("BAL")
    assert event["title"] == "Players who left your club"


def test_endpoint_carries_the_departures(league):  # noqa: F811
    import api.routers.validation as val

    build, root = league
    build("BAL", 13, 13)
    _record(root, "BAL", expired=["GONE1"])
    body = val.roster_shortfall_endpoint("BAL")
    assert [p["player_id"] for p in body["departures"]["contract_expired"]] == ["GONE1"]
    assert body["departures"]["retired"] == []
    # No record (a league that has not rolled over on 8.1.3): empty lists.
    (root / "offseason_departures.json").unlink()
    assert val.roster_shortfall_endpoint("BAL")["departures"]["contract_expired"] == []


def test_the_rollover_records_departures_before_the_notices():
    import inspect

    from services import league_rollover

    src = inspect.getsource(league_rollover.LeagueRolloverService.archive_season)
    snap = src.index("expiring_contract_clubs(")
    contracts = src.index("rollover_contracts_for_new_season(")
    retire = src.index("run_yearly_retirements(")
    record = src.index("record_departures(")
    notices = src.index("_notify_owner_roster_shortfalls(")
    assert snap < contracts < retire < record < notices
