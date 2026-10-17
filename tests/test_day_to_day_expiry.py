"""8.1.2 (backlog #49): day-to-day injuries end, and the offseason heals.

A day-to-day injury (no injured-list stint) was cleared by nothing at all, so
alpha-test carried 80 of them, 17 parked on the 15-day list where nothing
ever brought the player back. They now end on their own date; at rollover
the injured-list step runs as of next opening day.
"""

from datetime import date, timedelta

from tests.test_dl_automation import _make_player, _owner_league, _prepare_env
from services.dl_automation import process_disabled_lists
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.roster_loader import load_roster


def _day_to_day(pid: str, start: date, days: int = 3, position: str = "CF"):
    player = _make_player(pid, injury_list="none", start=start, minimum=days, position=position)
    player.injury_list = None
    player.return_date = None
    player.injury_description = "Wrist soreness (day-to-day)"
    return player


def _player(pid: str):
    return next(p for p in load_players_from_csv("data/players.csv") if p.player_id == pid)


def test_day_to_day_on_the_active_roster_ends_on_its_date(tmp_path, monkeypatch):
    data = _owner_league(tmp_path, monkeypatch)
    start = date(2026, 6, 1)
    save_players_to_csv(
        [_day_to_day("PDTD", start, days=3), _day_to_day("PNEW", date(2026, 6, 3), days=3)],
        str(data / "players.csv"),
    )
    (data / "rosters" / "TST.csv").write_text("PDTD,ACT\nPNEW,ACT\n", encoding="utf-8")

    summary = process_disabled_lists(today="2026-06-04", auto_activate=True)

    assert summary.healed == ["PDTD"]
    healed = _player("PDTD")
    assert healed.injured is False and healed.injury_description is None
    assert _player("PNEW").injured is True  # still inside his few days
    # Nothing moved: he was never off the active roster.
    assert load_roster("TST").act == ["PDTD", "PNEW"]


def test_injured_free_agent_heals_too(tmp_path, monkeypatch):
    data = _owner_league(tmp_path, monkeypatch)
    save_players_to_csv([_day_to_day("PFA", date(2026, 6, 1))], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("", encoding="utf-8")

    process_disabled_lists(today="2026-06-10", auto_activate=True)

    assert _player("PFA").injured is False


def test_stint_injury_off_the_lists_waits_for_its_clock(tmp_path, monkeypatch):
    """A player flagged with a list injury but sitting on the active roster
    (an older inconsistency) is not healed before the stint's date."""

    data = _owner_league(tmp_path, monkeypatch)
    player = _make_player("PSTI", injury_list="dl15", start=date(2026, 6, 1), minimum=15)
    save_players_to_csv([player], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PSTI,ACT\n", encoding="utf-8")

    process_disabled_lists(today="2026-06-10", auto_activate=True)
    assert _player("PSTI").injured is True
    process_disabled_lists(today="2026-06-20", auto_activate=True)
    assert _player("PSTI").injured is False


def test_stint_with_no_dates_waits_for_its_return_date(tmp_path, monkeypatch):
    """A list injury with no start / eligible date has no clock; its own
    return date decides, as it does for a player on the lists."""

    data = _owner_league(tmp_path, monkeypatch)
    player = _make_player("PNOD", injury_list="dl15", start=date(2026, 6, 1))
    player.injury_start_date = None
    player.injury_eligible_date = None
    player.return_date = "2026-07-01"
    save_players_to_csv([player], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PNOD,ACT\n", encoding="utf-8")

    process_disabled_lists(today="2026-06-10", auto_activate=True)
    assert _player("PNOD").injured is True
    process_disabled_lists(today="2026-07-01", auto_activate=True)
    assert _player("PNOD").injured is False


def test_day_to_day_parked_on_a_cpu_injured_list_comes_back(tmp_path, monkeypatch):
    data = _owner_league(tmp_path, monkeypatch, owners=())
    save_players_to_csv([_day_to_day("PDL", date(2026, 4, 29))], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PACT1,ACT\nPDL,DL15\n", encoding="utf-8")

    summary = process_disabled_lists(today="2026-05-05", auto_activate=True)

    assert summary.activated
    roster = load_roster("TST")
    assert "PDL" in roster.act and "PDL" not in roster.dl
    assert _player("PDL").injured is False


def test_day_to_day_parked_on_an_owners_list_follows_the_owner(tmp_path, monkeypatch):
    from services.team_play_settings import save_team_play_settings

    data = _owner_league(tmp_path, monkeypatch)
    save_team_play_settings("TST", {"il_auto_activate_15": False}, data_dir=data)
    save_players_to_csv([_day_to_day("PDL", date(2026, 4, 29))], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PACT1,ACT\nPDL,DL15\n", encoding="utf-8")

    early = process_disabled_lists(today="2026-04-30", auto_activate=True)
    assert not early.awaiting_owner  # his few days are not over yet

    summary = process_disabled_lists(today="2026-05-05", auto_activate=True)
    assert not summary.activated
    assert summary.awaiting_owner  # the owner is told; nothing moves
    assert "PDL" in load_roster("TST").dl


def test_rollover_heals_as_of_next_opening_day(tmp_path, monkeypatch):
    """Long injuries carry over; anything ending before 1 April is over."""

    data = _owner_league(tmp_path, monkeypatch, owners=())
    short = _make_player("PSHORT", injury_list="dl15", start=date(2027, 1, 10), minimum=15)
    long_ = _make_player("PLONG", injury_list="il60", start=date(2026, 11, 28), minimum=245)
    save_players_to_csv(
        [short, long_, _day_to_day("PDTD", date(2026, 12, 7))], str(data / "players.csv")
    )
    (data / "rosters" / "TST.csv").write_text(
        "PACT1,ACT\nPDTD,ACT\nPSHORT,DL15\nPLONG,IR\n", encoding="utf-8"
    )

    from services.league_rollover import LeagueRolloverService

    service = LeagueRolloverService.__new__(LeagueRolloverService)
    healed = service._heal_for_opening_day(2027)

    assert healed["opening_day"] == "2027-04-01"
    assert healed["day_to_day_healed"] == 1
    assert healed["activated"] == 1
    roster = load_roster("TST")
    assert "PSHORT" in roster.act
    assert "PLONG" in roster.ir
    assert _player("PLONG").injured is True
    assert _player("PDTD").injured is False
    assert date(2026, 11, 28) + timedelta(days=245) > date(2027, 4, 1)
