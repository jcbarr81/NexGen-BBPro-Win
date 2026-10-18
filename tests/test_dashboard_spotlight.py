"""The owner dashboard's Spotlight (8.2.0): ``GET /teams/{team_id}/spotlight``.

Each item kind appears only when it applies and disappears when it does not:
free agency, the amateur draft, expiring contracts, qualifying offers, and
the rollover's departures / spots to fill. The Season page's action items
come from the same ``team_action_items`` function, unchanged. The feed is a
read: no file in the league changes. Everything runs on a tmp data root.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from models.player import Player
from utils.player_writer import save_players_to_csv

TEAMS_CSV = (
    "team_id,name,city,abbreviation,division,stadium,primary_color,"
    "secondary_color,owner_id\n"
    "BAL,Orioles,Baltimore,BAL,East,Camden,#000000,#FFFFFF,\n"
    "NYY,Yankees,New York,NYY,East,Stadium,#000000,#FFFFFF,\n"
)


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "teams.csv").write_text(TEAMS_CSV, encoding="utf-8")
    (root / "users.txt").write_text(
        "commish,pass,admin,\nbal_owner,pass,owner,BAL\n", encoding="utf-8"
    )
    # Sentinel so get_data_dir() resolves this root, never a stray league.
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()

    import api.routers.season as season

    monkeypatch.setattr(season, "_read_season_deadline", lambda: None)
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [])
    monkeypatch.setattr("services.fa_window.finance_fa_enabled", lambda **k: True)
    set_phase(monkeypatch, "REGULAR_SEASON")
    set_date(monkeypatch, "2026-07-01")
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def set_phase(monkeypatch, phase, after_draft="REGULAR_SEASON"):
    import api.routers.season as season

    manager = SimpleNamespace(
        phase=SimpleNamespace(value=phase),
        phase_after_draft=lambda: SimpleNamespace(value=after_draft),
    )
    monkeypatch.setattr(season, "SeasonManager", lambda: manager)


def set_date(monkeypatch, iso):
    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda *a, **k: iso)


def _player(pid, pos="CF", pitcher=False):
    return Player(
        player_id=pid,
        first_name="Pat",
        last_name=pid,
        birthdate="1995-01-01",
        height=72,
        weight=190,
        bats="R",
        primary_position="P" if pitcher else pos,
        other_positions=[],
        gf=0,
    )


def _players(root, *ids):
    save_players_to_csv([_player(pid) for pid in ids], str(root / "players.csv"))


def spotlight(team="BAL"):
    from api.routers.dashboard import team_spotlight

    return team_spotlight(team)


def kinds(out):
    return {item["kind"]: item for item in out["items"]}


def _tree_hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --- the Season page's action items: one function, two feeds ------------------


def test_season_action_items_are_the_same_function(league, monkeypatch):
    import api.routers.season as season

    pend = SimpleNamespace(to_team="BAL", status="pending")
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [pend])
    out = season.season_action_items(identity={"r": "owner", "t": "BAL"})
    assert out["items"] == season.team_action_items("BAL")
    assert out["count"] == len(out["items"]) and out["team_id"] == "BAL"
    offer = kinds(spotlight())["trade_offer"]
    assert offer["severity"] == "action" and offer["href"] == "/trades"


def test_most_urgent_first(league, monkeypatch):
    pend = SimpleNamespace(to_team="BAL", status="pending")
    monkeypatch.setattr("utils.trade_utils.load_trades", lambda: [pend])
    _contracts(league, {"E1": ("BAL", 1)})
    _players(league, "E1")
    out = spotlight()
    ranks = [{"action": 0, "warning": 1, "info": 2}[i["severity"]] for i in out["items"]]
    assert ranks == sorted(ranks)
    assert out["items"][0]["kind"] == "trade_offer"
    assert out["phase"] == "REGULAR_SEASON"


# --- free agency -----------------------------------------------------------------


def _open_window(root, day=3, status="open", start="2026-11-01", log=None):
    state = {
        "version": 1,
        "status": status,
        "start_date": start,
        "deadline_date": "2026-11-15",
        "day": day,
        "total_days": 14,
        "current_date": start,
        "log": log or [],
    }
    (root / "fa_window.json").write_text(json.dumps(state), encoding="utf-8")


def test_open_window_names_where_you_lead_and_where_you_are_outbid(league, monkeypatch):
    from services import fa_negotiations as neg

    set_phase(monkeypatch, "OFFSEASON")
    set_date(monkeypatch, "2026-11-01")
    _players(league, "LEAD", "LOST")
    _open_window(league)
    for pid, team, salary in (
        ("LEAD", "BAL", 5_000_000),
        ("LEAD", "NYY", 4_000_000),
        ("LOST", "BAL", 2_000_000),
        ("LOST", "NYY", 6_000_000),
    ):
        neg.submit_offer(pid, team, years=1, annual_salary=salary,
                         sim_date="2026-11-01", data_dir=league)
    (league / "fa_window_schedule.json").write_text(
        json.dumps({"deadline": "2030-01-01T18:00:00+00:00", "auto_advance": True}),
        encoding="utf-8",
    )

    out = spotlight()
    item = kinds(out)["free_agency"]
    assert item["title"] == "Free-agent bidding is open: day 3 of 14"
    assert item["severity"] == "action"  # outbid on one
    assert item["deadline_utc"] == "2030-01-01T18:00:00+00:00"
    assert "Outbid on 1: Pat LOST" in item["detail"]
    assert "You lead for 1: Pat LEAD" in item["detail"]
    assert "closes automatically" in item["detail"]
    assert [p["name"] for p in item["players"]] == ["Pat LOST", "Pat LEAD"]
    assert item["players"][0]["note"].startswith("outbid")
    assert item["href"] == "/free-agency"
    # The Season page's "no active bid" row is not repeated.
    assert "fa_bid_needed" not in kinds(out)


def test_leading_everywhere_is_informational(league, monkeypatch):
    from services import fa_negotiations as neg

    set_phase(monkeypatch, "OFFSEASON")
    _players(league, "LEAD")
    _open_window(league)
    neg.submit_offer("LEAD", "BAL", years=2, annual_salary=5_000_000,
                     sim_date="2026-11-01", data_dir=league)
    item = kinds(spotlight())["free_agency"]
    assert item["severity"] == "info"
    assert "The commissioner advances the day." in item["detail"]
    assert "deadline_utc" not in item


def test_no_live_bid_is_an_action(league, monkeypatch):
    set_phase(monkeypatch, "OFFSEASON")
    _open_window(league)
    item = kinds(spotlight())["free_agency"]
    assert item["severity"] == "action"
    assert "You have no live bid." in item["detail"]


def test_closed_window_this_offseason_lists_your_signings(league, monkeypatch):
    set_phase(monkeypatch, "OFFSEASON")
    set_date(monkeypatch, "2026-11-01")
    _open_window(
        league,
        status="closed",
        log=[{"day": 2, "signed": [
            {"player_id": "S1", "player_name": "Sam One", "team_id": "BAL",
             "annual_salary": 3_000_000, "years": 2},
            {"player_id": "S2", "player_name": "Sam Two", "team_id": "NYY",
             "annual_salary": 1_000_000, "years": 1},
        ]}],
    )
    item = kinds(spotlight())["free_agency"]
    assert item["title"] == "Free-agent bidding has closed"
    assert item["severity"] == "info"
    assert [p["name"] for p in item["players"]] == ["Sam One"]
    assert item["players"][0]["note"] == "2y / $3M"


def test_before_the_window_opens_and_never_opens_it(league, monkeypatch):
    set_phase(monkeypatch, "OFFSEASON")
    item = kinds(spotlight())["free_agency"]
    assert item["title"] == "Free-agent bidding opens this offseason"
    assert not (league / "fa_window.json").exists()
    # Last offseason's closed window is not this offseason's.
    _open_window(league, status="closed", start="2025-11-01")
    assert kinds(spotlight())["free_agency"]["title"] == (
        "Free-agent bidding opens this offseason"
    )


def test_no_free_agency_item_in_season(league):
    _open_window(league, status="closed")
    assert "free_agency" not in kinds(spotlight())


def test_finance_off_offseason_market(league, monkeypatch):
    monkeypatch.setattr("services.fa_window.finance_fa_enabled", lambda **k: False)
    set_phase(monkeypatch, "OFFSEASON")
    item = kinds(spotlight())["free_agency"]
    assert item["title"] == "Free agency is open" and item["severity"] == "info"
    set_phase(monkeypatch, "PRESEASON")
    assert "free_agency" not in kinds(spotlight())


# --- the amateur draft -------------------------------------------------------------


def _draft_state(root, year, **state):
    payload = {"year": year, "round": 1, "overall_pick": 1, "order": ["NYY", "BAL"],
               "selected": [], "seed": 1, **state}
    path = root / f"draft_state_{year}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _draft_year(monkeypatch, year):
    monkeypatch.setattr("api.routers.draft._resolve_year", lambda y=None: year)


def test_on_the_clock_with_a_pick_clock(league, monkeypatch):
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "AMATEUR_DRAFT")
    _draft_year(monkeypatch, 2026)
    save_draft_settings(DraftSettings(rounds=2, pick_clock_hours=24))
    path = _draft_state(
        league, 2026, overall_pick=2,
        selected=[{"overall": 1, "round": 1, "team_id": "NYY", "player_id": "D1"}],
        clock={"team_id": "BAL", "since": "2026-07-21T12:00:00+00:00"},
    )
    before = path.read_bytes()
    item = kinds(spotlight())["draft"]
    assert item["severity"] == "action"
    assert item["title"] == "You're on the clock in the 2026 amateur draft"
    assert item["deadline_utc"] == "2026-07-22T12:00:00+00:00"
    assert "Round 1, pick 2 of 4." in item["detail"]
    assert "CPU picks for you" in item["detail"]
    assert path.read_bytes() == before


def test_on_the_clock_never_starts_the_clock(league, monkeypatch):
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "AMATEUR_DRAFT")
    _draft_year(monkeypatch, 2026)
    save_draft_settings(DraftSettings(rounds=2, pick_clock_hours=24))
    path = _draft_state(league, 2026, order=["BAL", "NYY"])
    before = path.read_bytes()
    item = kinds(spotlight())["draft"]
    assert item["severity"] == "action" and "deadline_utc" not in item
    assert path.read_bytes() == before


def test_waiting_for_your_next_pick(league, monkeypatch):
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "AMATEUR_DRAFT")
    _draft_year(monkeypatch, 2026)
    save_draft_settings(DraftSettings(rounds=2))
    _draft_state(
        league, 2026, overall_pick=3,
        selected=[
            {"overall": 1, "round": 1, "team_id": "NYY", "player_id": "D1"},
            {"overall": 2, "round": 1, "team_id": "BAL", "player_id": "D2"},
        ],
    )
    item = kinds(spotlight())["draft"]
    assert item["severity"] == "info"
    assert item["title"] == "The 2026 amateur draft is under way"
    assert "Your next pick: round 2, pick 4 (1 pick away). You've made 1 pick." in item["detail"]


def test_a_finished_draft_is_not_shown(league, monkeypatch):
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "AMATEUR_DRAFT")
    _draft_year(monkeypatch, 2026)
    save_draft_settings(DraftSettings(rounds=1))
    _draft_state(league, 2026, overall_pick=3, completed=True)
    assert "draft" not in kinds(spotlight())


def _july_draft(monkeypatch, *, done=False):
    import api.routers.season as season

    monkeypatch.setattr(season, "_load_schedule", lambda: [{"date": "2026-04-01"}])
    monkeypatch.setattr(season, "_draft_completed_for_current_year", lambda: done)
    monkeypatch.setattr(season, "_draft_skipped_for_current_year", lambda: False)
    monkeypatch.setattr(season, "_draft_held_in_preseason", lambda: False)


def test_july_draft_heads_up(league, monkeypatch):
    _july_draft(monkeypatch)
    (league / "draft_pool_2026.csv").write_text(
        "player_id,first_name\nD1,A\nD2,B\n", encoding="utf-8"
    )
    item = kinds(spotlight())["draft"]  # 2026-07-01: the draft is July 21
    assert item["title"] == "Amateur draft on July 21, in 20 days"
    assert "The class of 2 prospects is ready to scout" in item["detail"]
    set_date(monkeypatch, "2026-05-01")
    assert "draft" not in kinds(spotlight())  # too far out
    set_date(monkeypatch, "2026-07-01")
    _july_draft(monkeypatch, done=True)
    assert "draft" not in kinds(spotlight())


def test_preseason_draft_class_to_scout_in_the_offseason(league, monkeypatch):
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "OFFSEASON")
    save_draft_settings(DraftSettings(timing="preseason"))
    monkeypatch.setattr("api.routers.draft._upcoming_preseason_draft_year", lambda: 2027)
    assert "draft" not in kinds(spotlight())  # no class yet
    (league / "draft_pool_2027.csv").write_text(
        "player_id,first_name\nD1,A\nD2,B\nD3,C\n", encoding="utf-8"
    )
    item = kinds(spotlight())["draft"]
    assert item["title"] == "The 2027 amateur draft opens when the preseason begins"
    assert "The class of 3 prospects" in item["detail"]


def test_preseason_draft_due_at_training_camp(league, monkeypatch):
    import api.routers.season as season
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "PRESEASON")
    save_draft_settings(DraftSettings(timing="preseason"))
    monkeypatch.setattr(season, "_current_draft_year", lambda: 2027)
    monkeypatch.setattr(season, "_preseason_draft_status", lambda m: {"due": True})
    assert kinds(spotlight())["draft"]["title"] == (
        "The 2027 amateur draft opens with training camp"
    )
    monkeypatch.setattr(season, "_preseason_draft_status", lambda m: {"due": False})
    assert "draft" not in kinds(spotlight())


# --- expiring contracts ------------------------------------------------------------


def _contracts(root, spec):
    players = {
        pid: {"team_id": team, "years_left": years, "annual_salary": 4_500_000,
              "service_time_days": 900}
        for pid, (team, years) in spec.items()
    }
    (root / "contracts.json").write_text(
        json.dumps({"version": 1, "players": players}), encoding="utf-8"
    )


def test_final_year_players_best_first(league, monkeypatch):
    _players(league, "E1", "E2", "LONG", "OTHER")
    _contracts(league, {"E1": ("BAL", 1), "E2": ("BAL", 1), "LONG": ("BAL", 3),
                        "OTHER": ("NYY", 1)})
    score = {"E1": 40.0, "E2": 70.0}
    monkeypatch.setattr(
        "utils.player_overall.player_overall_score",
        lambda p, **k: score.get(p.player_id, 0.0),
    )
    (league / "extension_history.json").write_text(
        json.dumps({"E1": {"last_rejected_at": "2026-06-26"}}), encoding="utf-8"
    )
    item = kinds(spotlight())["expiring_contracts"]
    assert item["title"] == "2 players in the final year of their contracts"
    assert [p["player_id"] for p in item["players"]] == ["E2", "E1"]
    assert item["players"][0]["note"] == "$4.5M; can extend"
    assert "turned down an offer, 25 more days" in item["players"][1]["note"]
    assert "until the end of the playoffs" in item["detail"]
    assert "1 of 2 can be offered an extension today." in item["detail"]
    assert item["href"] == "/contracts?mine=1&expiring=1"
    assert item["severity"] == "info"


def test_expiring_turns_to_a_warning_in_the_playoffs(league, monkeypatch):
    _players(league, "E1")
    _contracts(league, {"E1": ("BAL", 1)})
    set_phase(monkeypatch, "PLAYOFFS")
    assert kinds(spotlight())["expiring_contracts"]["severity"] == "warning"


def test_extension_talks_pause_for_the_july_draft(league, monkeypatch):
    _players(league, "E1")
    _contracts(league, {"E1": ("BAL", 1)})
    set_phase(monkeypatch, "AMATEUR_DRAFT")
    item = kinds(spotlight())["expiring_contracts"]
    assert "pause during the amateur draft" in item["detail"]
    assert item["players"][0]["note"].endswith("talks paused")
    set_phase(monkeypatch, "AMATEUR_DRAFT", after_draft="PRESEASON")
    assert "expiring_contracts" not in kinds(spotlight())


def test_no_expiring_item_in_the_offseason(league, monkeypatch):
    _players(league, "E1")
    _contracts(league, {"E1": ("BAL", 1)})
    set_phase(monkeypatch, "OFFSEASON")
    assert "expiring_contracts" not in kinds(spotlight())


# --- qualifying offers --------------------------------------------------------------


def test_pending_qualifying_offers_are_an_action(league, monkeypatch):
    set_phase(monkeypatch, "OFFSEASON")
    monkeypatch.setattr("api.routers.finance._current_qo_year", lambda: 2027)
    _players(league, "Q1", "Q2")
    qo = {"year": 2027, "qo_value": 20_000_000, "players": {
        "Q1": {"team_id": "BAL", "salary": 12_000_000, "decision": "pending"},
        "Q2": {"team_id": "BAL", "salary": 9_000_000, "decision": "declined"},
    }}
    path = league / "qualifying_offers_2027.json"
    path.write_text(json.dumps(qo), encoding="utf-8")
    item = kinds(spotlight())["qualifying_offers"]
    assert item["severity"] == "action"
    assert item["title"] == "1 qualifying-offer decision waiting on you"
    assert item["players"] == [
        {"player_id": "Q1", "name": "Pat Q1", "position": "CF",
         "note": "earned $12M last season"}
    ]
    qo["players"]["Q1"]["decision"] = "accepted"
    path.write_text(json.dumps(qo), encoding="utf-8")
    assert "qualifying_offers" not in kinds(spotlight())


# --- rollover departures + spots to fill ---------------------------------------------


def _roster(root, team, hitters, pitchers):
    positions = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
    players, ids = [], []
    for i in range(hitters):
        players.append(_player(f"{team}H{i}", pos=positions[i % len(positions)]))
    for i in range(pitchers):
        players.append(_player(f"{team}P{i}", pitcher=True))
    ids = [p.player_id for p in players]
    save_players_to_csv(players, str(root / "players.csv"))
    (root / "rosters" / f"{team}.csv").write_text(
        "\n".join(f"{pid},ACT" for pid in ids) + "\n", encoding="utf-8"
    )


def _departures(root):
    (root / "offseason_departures.json").write_text(
        json.dumps({"year": 2027, "teams": {"BAL": {
            "retired": [{"player_id": "R1", "name": "Ed Old", "position": "P", "age": 41}],
            "contract_expired": [
                {"player_id": "X1", "name": "Carlo Gone", "position": "1B", "age": 31}
            ],
        }}}),
        encoding="utf-8",
    )


def test_rollover_departures_and_open_spots(league, monkeypatch):
    set_phase(monkeypatch, "OFFSEASON")
    set_date(monkeypatch, "2026-11-15")
    _roster(league, "BAL", 11, 10)
    _departures(league)
    out = spotlight()
    item = kinds(out)["rollover_roster"]
    assert item["severity"] == "warning"
    assert item["title"] == "5 active-roster spots to fill"
    assert "2 left the club at the rollover (1 retired, 1 contract expired)." in item["detail"]
    assert "21 of 26 active" in item["detail"]
    assert [(p["name"], p["note"]) for p in item["players"]] == [
        ("Ed Old", "retired"), ("Carlo Gone", "contract expired")
    ]
    assert item["href"] == "/roster"
    assert "roster_spot_open" not in kinds(out)  # said once, here


def test_rollover_blocking_is_an_action(league, monkeypatch):
    set_phase(monkeypatch, "PRESEASON")
    set_date(monkeypatch, "2026-11-15")
    _roster(league, "BAL", 9, 13)  # too few position players
    item = kinds(spotlight())["rollover_roster"]
    assert item["severity"] == "action"
    assert item["title"] == "Your roster isn't ready for Opening Day"
    assert "Fix before Opening Day:" in item["detail"]


def test_departures_alone_are_informational(league, monkeypatch):
    set_phase(monkeypatch, "OFFSEASON")
    set_date(monkeypatch, "2026-11-15")
    _roster(league, "BAL", 13, 13)
    assert "rollover_roster" not in kinds(spotlight())
    _departures(league)
    item = kinds(spotlight())["rollover_roster"]
    assert item["severity"] == "info"
    assert item["title"] == "2 players left your club this offseason"


def test_no_rollover_item_in_season(league, monkeypatch):
    set_date(monkeypatch, "2026-05-15")
    _roster(league, "BAL", 11, 10)
    _departures(league)
    out = kinds(spotlight())
    assert "rollover_roster" not in out
    assert "roster_spot_open" in out  # the Season page's own row


# --- read-only, auth -----------------------------------------------------------------


def test_the_feed_changes_no_file(league, monkeypatch):
    from services import fa_negotiations as neg
    from services.draft_settings import DraftSettings, save_draft_settings

    set_phase(monkeypatch, "OFFSEASON")
    set_date(monkeypatch, "2026-11-15")
    _roster(league, "BAL", 11, 10)
    _departures(league)
    _open_window(league, start="2026-11-15")
    neg.submit_offer("BALH0", "NYY", years=1, annual_salary=1, sim_date="2026-11-15",
                     data_dir=league)
    save_draft_settings(DraftSettings(timing="preseason", pick_clock_hours=12))
    (league / "draft_pool_2027.csv").write_text("player_id\nD1\n", encoding="utf-8")
    monkeypatch.setattr("api.routers.draft._upcoming_preseason_draft_year", lambda: 2027)
    # A real league always has its phase file (a SeasonManager writes one
    # when it is missing, as the roster-cap lookup's does).
    (league / "season_state.json").write_text('{"phase": "OFFSEASON"}', encoding="utf-8")
    before = _tree_hashes(league)
    out = spotlight()
    assert {"free_agency", "draft", "rollover_roster"} <= set(kinds(out))
    assert _tree_hashes(league) == before


def test_unknown_team_is_404(league):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as err:
        spotlight("ZZZ")
    assert err.value.status_code == 404


def test_endpoint_needs_a_signed_in_user_and_serves_any_club(league):
    from fastapi.testclient import TestClient

    from api.app import create_app

    client = TestClient(create_app())
    assert client.get("/teams/BAL/spotlight").status_code == 401
    for user, team in (("bal_owner", "BAL"), ("bal_owner", "NYY"), ("commish", "BAL")):
        login = client.post("/auth/login", json={"username": user, "password": "pass"})
        assert login.status_code == 200, login.text
        token = login.json()["token"]
        res = client.get(
            f"/teams/{team}/spotlight", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["team_id"] == team and isinstance(body["items"], list)
