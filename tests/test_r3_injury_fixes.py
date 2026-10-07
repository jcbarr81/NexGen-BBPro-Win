"""Release 3 fix round: injured-list automation and injury hazards (item E).

Each test pins one review finding on the integrated release-3 branch:

* the deadline fallback (``force_auto_activate``) honours an owner's explicit
  15-day choice and forces only owners who never chose (owner decision Q11);
* unreadable ownership stands every club down, even under force;
* a veteran returner is never parked in Low-A (age limit);
* the "waiting on the owner" news line is logged once ownership is known;
* the "ready - make room" items say why he is waiting;
* exhibitions and other undated games injure nobody;
* a durability of 0 is a real rating, and side files are the only roster
  files the durability centre skips.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from models.player import Player
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.roster_loader import load_roster

TEAM = "TST"


def _make_player(
    pid: str,
    *,
    injury_list: str | None = None,
    start: date = date(2025, 4, 1),
    minimum: int = 10,
    position: str = "CF",
    birthdate: str = "1990-01-01",
) -> Player:
    player = Player(
        player_id=pid,
        first_name="Test",
        last_name=pid,
        birthdate=birthdate,
        height=72,
        weight=190,
        bats="R",
        primary_position=position,
        other_positions=[],
        gf=0,
    )
    if injury_list:
        player.injured = True
        player.injury_list = injury_list
        player.injury_start_date = start.isoformat()
        player.injury_minimum_days = minimum
        player.injury_eligible_date = (start + timedelta(days=minimum)).isoformat()
        player.ready = False
        player.injury_description = "Test injury"
    return player


def _prepare_env(tmp_path, monkeypatch, *, teams=(TEAM,)):
    base = tmp_path
    data = base / "data"
    (data / "rosters").mkdir(parents=True)
    rows = "".join(
        f"{tid},Team {tid},City,{tid},East,Dome,#000000,#FFFFFF,\n" for tid in teams
    )
    (data / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n" + rows,
        encoding="utf-8",
    )
    for module in (
        "utils.path_utils",
        "utils.roster_loader",
        "utils.player_loader",
        "utils.team_loader",
    ):
        monkeypatch.setattr(f"{module}.get_base_dir", lambda: base)
        monkeypatch.setattr(f"{module}.get_data_dir", lambda: data)
    monkeypatch.setattr("services.dl_automation.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.team_loader.load_stats", lambda: {"players": {}, "teams": {}})
    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    return data


def _owners(data, *owners):
    (data / "users.txt").write_text(
        "".join(f"own{t},pw,user,{t}\n" for t in owners), encoding="utf-8"
    )


def _news(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(
        "services.dl_automation.log_news_event",
        lambda msg, *a, **k: lines.append(str(msg)),
    )
    return lines


# --- (1) the deadline fallback honours an owner's explicit choice ----------


def test_force_honours_an_owner_who_turned_15_day_activation_off(tmp_path, monkeypatch):
    from services.dl_automation import process_disabled_lists
    from services.team_play_settings import save_team_play_settings

    data = _prepare_env(tmp_path, monkeypatch)
    _owners(data, TEAM)
    save_team_play_settings(TEAM, {"il_auto_activate_15": False}, data_dir=data)
    save_players_to_csv(
        [_make_player("PINJ", injury_list="dl15")], str(data / "players.csv")
    )
    (data / "rosters" / f"{TEAM}.csv").write_text("PACT1,ACT\nPINJ,DL15\n", encoding="utf-8")

    summary = process_disabled_lists(today="2025-04-25", force_auto_activate=True)

    assert not summary.activated
    assert "PINJ" in load_roster(TEAM).dl


def test_force_still_activates_an_owner_who_never_chose(tmp_path, monkeypatch):
    """The deadline is the fallback for a disengaged owner in a league whose
    15-day list is manual: with no stored choice, force still applies."""
    from services.dl_automation import process_disabled_lists

    data = _prepare_env(tmp_path, monkeypatch)
    _owners(data, TEAM)
    (data / "league_settings.json").write_text(
        json.dumps({"auto_activate_il": False}), encoding="utf-8"
    )
    monkeypatch.setattr("utils.league_settings.auto_activate_il", lambda *a: False)
    save_players_to_csv(
        [_make_player("PINJ", injury_list="dl15")], str(data / "players.csv")
    )
    (data / "rosters" / f"{TEAM}.csv").write_text("PACT1,ACT\nPINJ,DL15\n", encoding="utf-8")

    without = process_disabled_lists(today="2025-04-25")
    assert not without.activated  # the league's manual 15-day list
    summary = process_disabled_lists(today="2025-04-25", force_auto_activate=True)

    assert summary.activated
    assert "PINJ" in load_roster(TEAM).act


# --- (2) unknown ownership stands everyone down, even under force ----------


def test_force_with_unreadable_ownership_moves_nobody(tmp_path, monkeypatch):
    from services.dl_automation import AWAITING_ROOM_FILENAME, process_disabled_lists

    data = _prepare_env(tmp_path, monkeypatch, teams=("OWN", "CPU"))
    (data / "users.txt").mkdir()  # exists but cannot be read -> ownership None
    from services.team_ownership import human_owned_team_ids_strict

    assert human_owned_team_ids_strict() is None
    save_players_to_csv(
        [
            _make_player("OINJ", injury_list="dl15"),
            _make_player("CINJ", injury_list="dl15"),
        ],
        str(data / "players.csv"),
    )
    full = "".join(f"C{i},ACT\n" for i in range(26))
    (data / "rosters" / "OWN.csv").write_text("O1,ACT\nOINJ,DL15\n", encoding="utf-8")
    (data / "rosters" / "CPU.csv").write_text(full + "CINJ,DL15\n", encoding="utf-8")

    summary = process_disabled_lists(today="2025-04-25", force_auto_activate=True)

    assert not summary.activated
    assert not summary.awaiting_room
    assert "OINJ" in load_roster("OWN").dl
    assert "CINJ" in load_roster("CPU").dl
    assert not (data / AWAITING_ROOM_FILENAME).exists()


# --- (4) Low-A only for players young enough for it ------------------------


def _full_owner_roster(data, returner_rows: str) -> list[str]:
    active = [f"PACT{i}" for i in range(1, 27)]
    aaa = [f"PAAA{i}" for i in range(1, 16)]
    rows = "".join(f"{p},ACT\n" for p in active) + "".join(f"{p},AAA\n" for p in aaa)
    rows += "PLOW1,LOW\n" + returner_rows
    (data / "rosters" / f"{TEAM}.csv").write_text(rows, encoding="utf-8")
    return active


def test_veteran_returner_is_not_parked_in_low_a(tmp_path, monkeypatch):
    from services.dl_automation import process_disabled_lists

    data = _prepare_env(tmp_path, monkeypatch)
    _owners(data, TEAM)
    save_players_to_csv(
        [_make_player("VET", injury_list="dl15", birthdate="1985-01-01")],
        str(data / "players.csv"),
    )
    _full_owner_roster(data, "VET,DL15\n")

    summary = process_disabled_lists(today="2025-04-25")

    roster = load_roster(TEAM)
    assert "VET" not in roster.low
    assert "VET" in roster.dl  # blocked: still listed, the owner decides
    assert summary.blocked and not summary.activated


def test_young_returner_may_still_wait_in_low_a(tmp_path, monkeypatch):
    from services.dl_automation import process_disabled_lists

    data = _prepare_env(tmp_path, monkeypatch)
    _owners(data, TEAM)
    young = f"{date.today().year - 21}-01-01"
    save_players_to_csv(
        [_make_player("KID", injury_list="dl15", birthdate=young)],
        str(data / "players.csv"),
    )
    _full_owner_roster(data, "KID,DL15\n")

    process_disabled_lists(today="2025-04-25")

    assert "KID" in load_roster(TEAM).low


# --- (7) the owner line is logged on the first day ownership is known ------


def test_waiting_on_owner_line_follows_a_day_of_unreadable_ownership(
    tmp_path, monkeypatch
):
    from services.dl_automation import process_disabled_lists
    from services.team_play_settings import save_team_play_settings

    data = _prepare_env(tmp_path, monkeypatch)
    save_team_play_settings(TEAM, {"il_auto_activate_15": False}, data_dir=data)
    save_players_to_csv(
        [_make_player("PINJ", injury_list="dl15")], str(data / "players.csv")
    )
    (data / "rosters" / f"{TEAM}.csv").write_text("PACT1,ACT\nPINJ,DL15\n", encoding="utf-8")
    lines = _news(monkeypatch)

    (data / "users.txt").mkdir()  # day 1: ownership unreadable
    process_disabled_lists(today="2025-04-25")
    assert any("retrying" in line for line in lines)
    assert not any("waiting on the owner" in line for line in lines)

    (data / "users.txt").rmdir()  # day 2: ownership known
    _owners(data, TEAM)
    load_players_from_csv.cache_clear()
    process_disabled_lists(today="2025-04-26")
    assert sum("waiting on the owner" in line for line in lines) == 1

    load_players_from_csv.cache_clear()
    process_disabled_lists(today="2025-04-27")  # and only once
    assert sum("waiting on the owner" in line for line in lines) == 1


# --- (5) the action items say why he is waiting ----------------------------


def test_parked_pitcher_records_the_pitcher_limit_reason(tmp_path, monkeypatch):
    from services.dl_automation import _load_awaiting_room, process_disabled_lists

    data = _prepare_env(tmp_path, monkeypatch)
    _owners(data, TEAM)
    arms = [_make_player(f"P{i}", position="P") for i in range(13)]
    bats = [_make_player(f"H{i}") for i in range(10)]
    back = _make_player("ARM", injury_list="dl15", position="P")
    save_players_to_csv(arms + bats + [back], str(data / "players.csv"))
    rows = "".join(f"{p.player_id},ACT\n" for p in arms + bats) + "ARM,DL15\n"
    (data / "rosters" / f"{TEAM}.csv").write_text(rows, encoding="utf-8")

    summary = process_disabled_lists(today="2025-04-25")

    assert summary.awaiting_room
    assert "ARM" in load_roster(TEAM).aaa
    entry = _load_awaiting_room(data)["teams"][TEAM][0]
    assert entry["reason"] == "pitcher_cap"


@pytest.fixture()
def league_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir(parents=True)
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text("", encoding="utf-8")
    (root / "rosters").mkdir()
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


ITEMS_TODAY = "2026-08-15"


def _action_items(monkeypatch):
    import api.routers.season as season

    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    monkeypatch.setattr(
        season,
        "SeasonManager",
        lambda: SimpleNamespace(phase=SimpleNamespace(value="REGULAR_SEASON")),
    )
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [])
    monkeypatch.setattr("services.fa_window.window_status", lambda: {"status": None})
    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda: ITEMS_TODAY)
    out = season.season_action_items(identity={"r": "owner", "t": TEAM})
    return {item["kind"]: item for item in out["items"]}


def _listed(pid: str, injury_list: str) -> Player:
    done = (date.fromisoformat(ITEMS_TODAY) - timedelta(days=1)).isoformat()
    player = _make_player(pid, injury_list=injury_list)
    player.injury_start_date = "2026-07-01"
    player.injury_eligible_date = done
    return player


def test_ready_item_on_an_automatic_list_says_there_is_no_room(league_dir, monkeypatch):
    from services.team_play_settings import save_team_play_settings

    save_team_play_settings(TEAM, {"il_auto_activate_15": True}, data_dir=league_dir)
    save_players_to_csv([_listed("STUCK", "dl15")], str(league_dir / "players.csv"))
    (league_dir / "rosters" / f"{TEAM}.csv").write_text("STUCK,DL15\n", encoding="utf-8")

    item = _action_items(monkeypatch)["il_return_ready"]

    assert "turn on automatic activation" not in item["detail"]
    assert "no room" in item["detail"]


def test_ready_item_on_a_manual_list_still_points_to_the_setting(league_dir, monkeypatch):
    save_players_to_csv([_listed("READY", "il60")], str(league_dir / "players.csv"))
    (league_dir / "rosters" / f"{TEAM}.csv").write_text("READY,IR\n", encoding="utf-8")

    item = _action_items(monkeypatch)["il_return_ready"]

    assert "turn on automatic activation" in item["detail"]


def test_needs_room_item_gives_the_pitcher_limit_reason(league_dir, monkeypatch):
    from services.dl_automation import AWAITING_ROOM_FILENAME

    save_players_to_csv(
        [_make_player("H1"), _make_player("ARM", position="P")],
        str(league_dir / "players.csv"),
    )
    (league_dir / "rosters" / f"{TEAM}.csv").write_text(
        "H1,ACT\nARM,AAA\n", encoding="utf-8"
    )
    (league_dir / AWAITING_ROOM_FILENAME).write_text(
        json.dumps(
            {
                "version": 1,
                "teams": {
                    TEAM: [
                        {
                            "player_id": "ARM",
                            "list": "15-Day IL",
                            "level": "aaa",
                            "date": "2026-08-14",
                            "reason": "pitcher_cap",
                            "pitcher_cap": 13,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    item = _action_items(monkeypatch)["il_return_needs_room"]

    assert "active roster was full" not in item["detail"]
    assert "13-pitcher limit" in item["detail"]


# --- (3) exhibitions and other undated games injure nobody -----------------


def _tired_batter_roll(game_day):
    from physics_sim import arm_injury
    from physics_sim.config import DEFAULT_TUNING, load_tuning

    cap = DEFAULT_TUNING["batter_fatigue_penalty_cap"]
    batter = SimpleNamespace(
        player_id="TIRED", durability=50.0, primary_position="CF", fatigue_penalty=cap
    )
    lineup = SimpleNamespace(batting_lines={"TIRED": None}, fielding_lines={})
    return arm_injury.roll_post_game_injuries(
        seed=7,
        tuning=load_tuning(
            overrides={"pitcher_arm_enabled": 0.0, "batter_fatigue_injury_base": 1.0}
        ),
        usage_state=None,
        game_day=game_day,
        staffs={},
        lineups={"home": lineup},
        batters={"home": [batter]},
        injured_players=set(),
    )


def test_undated_game_rolls_no_post_game_injuries():
    assert _tired_batter_roll(game_day=0)  # a season game: the hazard is live
    assert _tired_batter_roll(game_day=None) == []


def test_exhibition_runs_with_injuries_off(league_dir, monkeypatch):
    import api.routers.exhibition as exhibition
    from services.injury_settings import get_injury_tuning_overrides

    seen: dict = {}

    def fake_run_single_game(home, away, **kwargs):
        seen["overrides"] = get_injury_tuning_overrides()
        team = SimpleNamespace()
        return team, team, {}, "<html></html>", {}

    monkeypatch.setattr("playbalance.game_runner.run_single_game", fake_run_single_game)
    monkeypatch.setattr(
        "playbalance.simulation.save_boxscore_html", lambda *a, **k: None
    )

    out = asyncio.run(
        exhibition.simulate_exhibition(
            {"home_team": "AAA", "away_team": "BBB"}, {"r": "admin"}
        )
    )

    assert out["home_team"] == "AAA"
    assert seen["overrides"]["injuries_enabled"] == 0.0
    # Season games are untouched: outside the exhibition injuries are on.
    assert get_injury_tuning_overrides()["injuries_enabled"] == 1.0


# --- (6) durability 0 and side files ----------------------------------------


def test_durability_zero_is_a_real_rating():
    from physics_sim import arm_injury
    from physics_sim.config import load_tuning

    tuning = load_tuning(overrides={"pitcher_arm_base": 0.5, "pitcher_arm_per_pitch": 0.0})

    def roll(durability):
        pitcher = SimpleNamespace(player_id="ARM", durability=durability)
        state = SimpleNamespace(pitches=20, pitcher=pitcher)
        staff = SimpleNamespace(starter=None, all_pitchers=lambda: [state])
        events = arm_injury.roll_post_game_injuries(
            seed=4,
            tuning=tuning,
            usage_state=None,
            game_day=0,
            staffs={"home": staff},
            lineups={},
            batters={},
            injured_players=set(),
        )
        return events

    # Seed 4 draws 0.675: above the durability-50 chance (0.5), below the
    # durability-0 one (capped at 1.0).
    zero = roll(0)
    assert zero and zero[0]["durability"] == 0.0
    blank = roll(None)
    assert not blank or blank[0]["durability"] == 50.0


def test_durability_centre_reads_team_ids_with_underscores(tmp_path):
    from services.injury_settings import active_pitcher_mean_durability

    (tmp_path / "rosters").mkdir()
    (tmp_path / "players.csv").write_text(
        "player_id,primary_position,durability\nA1,P,40\nB1,P,80\n", encoding="utf-8"
    )
    (tmp_path / "rosters" / "NY_A.csv").write_text("A1,ACT\n", encoding="utf-8")
    (tmp_path / "rosters" / "BOS.csv").write_text("B1,ACT\n", encoding="utf-8")
    (tmp_path / "rosters" / "BOS_pitching.csv").write_text("B1,ACT\n", encoding="utf-8")

    assert active_pitcher_mean_durability(tmp_path) == pytest.approx(60.0)
