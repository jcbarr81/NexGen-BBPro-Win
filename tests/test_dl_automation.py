from datetime import date, timedelta

from models.player import Player
from services.dl_automation import process_disabled_lists
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.roster_loader import load_roster


def _make_player(
    pid: str, *, injury_list: str, start: date, minimum: int = 15, position: str = "P"
) -> Player:
    player = Player(
        player_id=pid,
        first_name="Test",
        last_name=pid,
        birthdate="1990-01-01",
        height=72,
        weight=190,
        bats="R",
        primary_position=position,
        other_positions=[],
        gf=0,
    )
    player.injured = True
    player.injury_list = injury_list
    player.injury_start_date = start.isoformat()
    player.injury_minimum_days = minimum
    player.injury_eligible_date = (start + timedelta(days=minimum)).isoformat()
    player.ready = False
    player.injury_description = "Test injury"
    return player


def _prepare_env(tmp_path, monkeypatch):
    base = tmp_path
    data = base / "data"
    rosters = data / "rosters"
    rosters.mkdir(parents=True)
    teams_path = data / "teams.csv"
    teams_path.write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "TST,Testers,Test City,TST,East,Test Dome,#000000,#FFFFFF,owner\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.path_utils.get_base_dir", lambda: base)
    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.roster_loader.get_base_dir", lambda: base)
    monkeypatch.setattr("utils.roster_loader.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.player_loader.get_base_dir", lambda: base)
    monkeypatch.setattr("utils.player_loader.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.team_loader.get_base_dir", lambda: base)
    monkeypatch.setattr("utils.team_loader.get_data_dir", lambda: data)
    monkeypatch.setattr("services.dl_automation.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.team_loader.load_stats", lambda: {"players": {}, "teams": {}})
    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    return data


def test_process_disabled_lists_activates_players(tmp_path, monkeypatch):
    data = _prepare_env(tmp_path, monkeypatch)
    player = _make_player("PINJ", injury_list="dl15", start=date(2025, 4, 1))
    save_players_to_csv([player], str(data / "players.csv"))
    roster_path = data / "rosters" / "TST.csv"
    roster_path.write_text(
        "PACT1,ACT\n"
        "PAAA1,AAA\n"
        "PLOW1,LOW\n"
        "PINJ,DL15\n",
        encoding="utf-8",
    )

    summary = process_disabled_lists(today="2025-04-25", auto_activate=True)

    assert summary.activated
    roster = load_roster("TST")
    assert "PINJ" in roster.act
    assert "PINJ" not in roster.dl
    players = load_players_from_csv("data/players.csv")
    activated = next(p for p in players if p.player_id == "PINJ")
    assert activated.injured is False
    assert activated.ready is True


def test_process_disabled_lists_skips_ir_auto_activation(tmp_path, monkeypatch):
    """An owner's 60-day list is managed by hand."""
    data = _prepare_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"TST"}
    )
    start = date(2025, 4, 1)
    player = _make_player("PREH", injury_list="ir", start=start, minimum=10)
    save_players_to_csv([player], str(data / "players.csv"))
    roster_path = data / "rosters" / "TST.csv"
    roster_path.write_text(
        "PACT1,ACT\n"
        "PAAA1,AAA\n"
        "PREH,IR\n",
        encoding="utf-8",
    )

    summary = process_disabled_lists(
        today="2025-04-20",
        days_elapsed=2,
        auto_activate=True,
    )

    assert not summary.activated
    roster = load_roster("TST")
    assert "PREH" in roster.ir
    players = load_players_from_csv("data/players.csv")
    ir_player = next(p for p in players if p.player_id == "PREH")
    assert ir_player.injured is True


def test_cpu_club_activates_its_60_day_list(tmp_path, monkeypatch):
    """Nobody runs a CPU club's injured list, so its IL60 players come back
    on their own (audit H9 review: they never did)."""
    data = _prepare_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set()
    )
    start = date(2025, 4, 1)
    player = _make_player("PREH", injury_list="ir", start=start, minimum=10)
    save_players_to_csv([player], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text(
        "PACT1,ACT\nPAAA1,AAA\nPREH,IR\n", encoding="utf-8"
    )
    summary = process_disabled_lists(today="2025-04-20", days_elapsed=2, auto_activate=True)
    assert summary.activated
    assert "PREH" not in load_roster("TST").ir


# --- Release 3 (owner decision Q11): per-team owner choices -------------------


def _owner_league(tmp_path, monkeypatch, *, owners=("TST",)):
    data = _prepare_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict",
        lambda *a, **k: set(owners),
    )
    return data


def test_owner_who_turns_on_60_day_activation_gets_his_player_back(tmp_path, monkeypatch):
    from services.team_play_settings import save_team_play_settings

    data = _owner_league(tmp_path, monkeypatch)
    save_team_play_settings("TST", {"il_auto_activate_60": True}, data_dir=data)
    player = _make_player("PREH", injury_list="ir", start=date(2025, 4, 1), minimum=60)
    save_players_to_csv([player], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PACT1,ACT\nPREH,IR\n", encoding="utf-8")

    summary = process_disabled_lists(today="2025-06-05", auto_activate=True)

    assert summary.activated
    roster = load_roster("TST")
    assert "PREH" in roster.act and "PREH" not in roster.ir


def test_owner_who_turns_off_15_day_activation_keeps_the_player_listed(tmp_path, monkeypatch):
    from services.team_play_settings import save_team_play_settings

    data = _owner_league(tmp_path, monkeypatch)
    save_team_play_settings("TST", {"il_auto_activate_15": False}, data_dir=data)
    player = _make_player("PINJ", injury_list="dl15", start=date(2025, 4, 1))
    save_players_to_csv([player], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PACT1,ACT\nPINJ,DL15\n", encoding="utf-8")

    summary = process_disabled_lists(today="2025-04-25", auto_activate=True)

    assert not summary.activated
    assert summary.awaiting_owner
    assert "PINJ" in load_roster("TST").dl
    players = load_players_from_csv("data/players.csv")
    assert next(p for p in players if p.player_id == "PINJ").ready is True


def test_cpu_club_ignores_owner_settings_and_activates(tmp_path, monkeypatch):
    from services.team_play_settings import save_team_play_settings

    data = _owner_league(tmp_path, monkeypatch, owners=())
    # A stale choice from a former owner must not strand a CPU club's player.
    save_team_play_settings(
        "TST", {"il_auto_activate_15": False, "il_auto_activate_60": False}, data_dir=data
    )
    player = _make_player("PINJ", injury_list="dl15", start=date(2025, 4, 1))
    save_players_to_csv([player], str(data / "players.csv"))
    (data / "rosters" / "TST.csv").write_text("PACT1,ACT\nPINJ,DL15\n", encoding="utf-8")

    summary = process_disabled_lists(today="2025-04-25", auto_activate=True)

    assert summary.activated
    assert "PINJ" in load_roster("TST").act


def test_owner_returner_with_no_room_waits_in_aaa_and_nobody_moves(tmp_path, monkeypatch):
    from services.dl_automation import players_awaiting_room

    data = _owner_league(tmp_path, monkeypatch)
    # A hitter: the roster loader's pitcher-depth repair would otherwise pull
    # the only known pitcher up to this player-less test roster.
    player = _make_player(
        "PINJ", injury_list="dl15", start=date(2025, 4, 1), minimum=10, position="CF"
    )
    save_players_to_csv([player], str(data / "players.csv"))
    active = [f"PACT{i}" for i in range(1, 27)]  # a full 26-man roster
    rows = "".join(f"{pid},ACT\n" for pid in active) + "PAAA1,AAA\nPINJ,DL15\n"
    (data / "rosters" / "TST.csv").write_text(rows, encoding="utf-8")

    summary = process_disabled_lists(today="2025-04-25", auto_activate=True)

    roster = load_roster("TST")
    assert roster.act == active  # the CPU never makes room on an owner's club
    assert "PINJ" in roster.aaa and "PINJ" not in roster.dl
    assert summary.awaiting_room
    levels = {"act": list(roster.act), "aaa": list(roster.aaa), "low": list(roster.low)}
    waiting = players_awaiting_room("TST", levels=levels, today="2025-04-26", data_dir=data)
    assert [w["player_id"] for w in waiting] == ["PINJ"]
    # Once the owner brings him up, the reminder is gone ...
    promoted = {"act": active + ["PINJ"], "aaa": ["PAAA1"], "low": []}
    assert players_awaiting_room("TST", levels=promoted, today="2025-04-26", data_dir=data) == []
    # ... and it lapses on its own if he is left down.
    assert players_awaiting_room("TST", levels=levels, today="2025-05-30", data_dir=data) == []
