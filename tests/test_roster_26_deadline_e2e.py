"""End to end: the owner deadline never leaves an illegal pitching staff.

Cross-item acceptance for the 26-man roster (owner decision 8, 7.46.0). When
a deadline passes, ``api.routers.season._run_schedule`` activates every player
whose injured-list stint is over (``process_disabled_lists`` with
``force_auto_activate``) and then CPU-fills each unready owner's team in
"gaps" mode. A pitcher coming back to a club already carrying the limit must
not leave it over the limit, and nobody may be released along the way, on an
owner's club or a CPU club.

Runs in a throwaway league (``NEXGEN_DATA_ROOT`` + ``set_request_league``,
exactly as the server resolves a league); the game sim itself is stubbed.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.roster_rules import (
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
    counts_as_pitcher,
)

LEAGUE_ID = "e2e26"
OWNER = "OWN"
OTHER_OWNER = "OTH"
CPU = "CPU"
TEAMS = (OWNER, OTHER_OWNER, CPU)
STARTER_POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
# A full 26-man roster (13 / 13), and one carrying a pitcher too many (14 / 12).
FULL = {
    "act_pitchers": MAX_ACTIVE_PITCHERS,
    "act_hitters": ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS,
}
OVER = {
    "act_pitchers": MAX_ACTIVE_PITCHERS + 1,
    "act_hitters": ACTIVE_ROSTER_SIZE - MAX_ACTIVE_PITCHERS - 1,
}

HEADER = (
    "player_id,first_name,last_name,birthdate,height,weight,ethnicity,skin_tone,"
    "hair_color,facial_hair,bats,throws,primary_position,other_positions,"
    "is_pitcher,role,preferred_pitching_role,ch,ph,sp,eye,gf,pl,vl,sc,fa,arm,"
    "endurance,control,movement,hold_runner,fb,cu,cb,sl,si,scb,kn,pot_ch,pot_ph,"
    "pot_sp,pot_eye,pot_gf,pot_pl,pot_vl,pot_sc,pot_fa,pot_arm,pot_control,"
    "pot_movement,pot_endurance,pot_hold_runner,pot_fb,pot_cu,pot_cb,pot_sl,"
    "pot_si,pot_scb,pot_kn,injured,injury_description,return_date,ready,"
    "injury_list,injury_start_date,injury_minimum_days,injury_eligible_date,"
    "injury_rehab_assignment,injury_rehab_days,durability,pitcher_archetype,"
    "hitter_archetype,mo,cl,hm,zone_bottom,zone_top,pot_fielding,delivery"
).split(",")
_RATINGS = (
    "ch,ph,sp,eye,gf,pl,vl,sc,fa,arm,endurance,control,movement,hold_runner,fb,"
    "cu,cb,sl,pot_ch,pot_ph,pot_sp,pot_eye,pot_gf,pot_pl,pot_vl,pot_sc,pot_fa,"
    "pot_arm,pot_control,pot_movement,pot_endurance,pot_hold_runner,pot_fb,"
    "pot_cu,pot_cb,pot_sl,durability,mo,cl,hm"
).split(",")


def _row(pid: str, pos: str, *, ovr: int, age: int = 26, injured: bool = False) -> dict:
    row = {col: "" for col in HEADER}
    for col in _RATINGS:
        row[col] = str(ovr)
    for col in ("si", "scb", "kn", "pot_si", "pot_scb", "pot_kn"):
        row[col] = "0"
    pitcher = pos == "P"
    row.update(
        player_id=pid,
        first_name="Test",
        last_name=pid,
        birthdate=f"{2026 - age}-03-01",
        height="72",
        weight="190",
        bats="R",
        throws="R",
        primary_position=pos,
        is_pitcher=str(pitcher),
        injured="False",
        ready="True",
        injury_rehab_days="0",
        zone_bottom="1.5",
        zone_top="3.5",
    )
    if injured:
        # On the 15-day list since May: long eligible to come back.
        row.update(
            injured="True",
            ready="False",
            injury_description="Sore elbow",
            injury_list="dl15",
            injury_start_date="2026-05-01",
            injury_minimum_days="15",
            injury_eligible_date="2026-05-16",
            return_date="2026-05-16",
        )
    return row


def _team(tid: str, *, act_pitchers: int, act_hitters: int):
    """Rows and roster lines for one club, plus one eligible DL pitcher."""

    rows, lines = [], []

    def add(pid, pos, level, **kw):
        rows.append(_row(pid, pos, **kw))
        lines.append(f"{pid},{level}")

    for i in range(act_hitters):
        pos = STARTER_POSITIONS[i] if i < len(STARTER_POSITIONS) else "1B"
        add(f"{tid}_H{i}", pos, "ACT", ovr=65)
    for i in range(act_pitchers):
        add(f"{tid}_P{i}", "P", "ACT", ovr=70 - i)
    for i in range(6):
        add(f"{tid}_AH{i}", STARTER_POSITIONS[i], "AAA", ovr=50)
    for i in range(5):
        add(f"{tid}_AP{i}", "P", "AAA", ovr=50)
    for i in range(4):
        add(f"{tid}_LH{i}", "1B", "LOW", ovr=40, age=20)
    add(f"{tid}_DLP", "P", "DL15", ovr=75, injured=True)
    return rows, lines


@pytest.fixture()
def league(tmp_path, monkeypatch):
    import utils.path_utils as path_utils
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster

    root = tmp_path / "root"
    data = root / "leagues" / LEAGUE_ID / "data"
    (data / "rosters").mkdir(parents=True)
    (data / "lineups").mkdir()
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    monkeypatch.delenv("PB_SIM_DATE", raising=False)
    monkeypatch.delenv("PB_SIM_YEAR", raising=False)

    with (data / "teams.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            "team_id,name,city,abbreviation,division,stadium,"
            "primary_color,secondary_color,owner_id\n"
        )
        for tid in TEAMS:
            fh.write(f"{tid},{tid} Club,{tid} City,{tid},East,{tid} Park,#000000,#ffffff,\n")
    # Two owners: the deadline only CPU-fills a multi-owner league.
    (data / "users.txt").write_text(
        f"owner1,pw,owner,{OWNER}\nowner2,pw,owner,{OTHER_OWNER}\n", encoding="utf-8"
    )
    # teams.csv + players.csv + users.txt present before the first
    # get_data_dir() call, or it seeds the repo's whole data folder (schedule
    # and all) into the league.
    (data / "players.csv").write_text(",".join(HEADER) + "\n", encoding="utf-8")

    token = path_utils.set_request_league(LEAGUE_ID)
    path_utils._DATA_DIR_CACHE.clear()
    load_roster.cache_clear()
    load_players_from_csv.cache_clear()
    monkeypatch.setattr("utils.news_logger.log_news_event", lambda *a, **k: None)
    try:
        yield data
    finally:
        load_roster.cache_clear()
        load_players_from_csv.cache_clear()
        path_utils.reset_request_league(token)
        path_utils._DATA_DIR_CACHE.clear()


def _write_league(data: Path, shapes: dict) -> set:
    rows = []
    for tid in TEAMS:
        team_rows, lines = _team(tid, **shapes[tid])
        rows += team_rows
        (data / "rosters" / f"{tid}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (data / "players.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return {r["player_id"] for r in rows}


def _run_deadline(data: Path, monkeypatch) -> dict:
    import api.routers.season as season

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    (data / "season_deadline.json").write_text(
        json.dumps({"deadline": past, "run_kind": "days", "run_n": 1, "cpu_fill": True}),
        encoding="utf-8",
    )
    sims = []
    monkeypatch.setattr(season, "_sim_running", lambda: False)
    monkeypatch.setattr(
        season, "_start_sim", lambda kind, identity, n_arg=1: sims.append(kind) or {}
    )
    result = season._run_schedule({"r": "admin"})
    assert sims == ["days"], "the deadline still starts the (stubbed) sim"
    return result


def _levels(tid: str) -> dict:
    from utils.roster_loader import load_roster

    load_roster.cache_clear()
    roster = load_roster(tid)
    return {lvl: list(getattr(roster, lvl)) for lvl in ("act", "aaa", "low", "dl", "ir")}


def _act_pitchers(levels: dict) -> int:
    from utils.player_loader import load_players_from_csv

    load_players_from_csv.cache_clear()
    players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
    return sum(1 for pid in levels["act"] if counts_as_pitcher(players.get(pid)))


def _assert_nobody_released(data: Path, everyone: set) -> None:
    on_rosters = set()
    for tid in TEAMS:
        for ids in _levels(tid).values():
            on_rosters.update(ids)
    assert everyone <= on_rosters, f"released: {sorted(everyone - on_rosters)}"
    tx = data / "transactions.csv"
    if tx.exists():
        assert ",cut," not in tx.read_text(encoding="utf-8")


def test_deadline_with_a_returning_pitcher_keeps_every_staff_legal(league, monkeypatch):
    everyone = _write_league(league, {tid: FULL for tid in TEAMS})

    result = _run_deadline(league, monkeypatch)

    activated = " ".join(result["activated"])
    for tid in TEAMS:
        assert f"{tid}_DLP" in activated or tid in activated, result["activated"]
    assert OWNER in result["filled"], "the unready owner's club was CPU-filled"

    owner = _levels(OWNER)
    assert f"{OWNER}_DLP" not in owner["dl"]
    assert _act_pitchers(owner) <= MAX_ACTIVE_PITCHERS
    assert len(owner["act"]) <= ACTIVE_ROSTER_SIZE

    cpu = _levels(CPU)
    assert f"{CPU}_DLP" in cpu["act"], "a CPU club brings its pitcher back up"
    assert _act_pitchers(cpu) <= MAX_ACTIVE_PITCHERS
    assert len(cpu["act"]) <= ACTIVE_ROSTER_SIZE

    _assert_nobody_released(league, everyone)


def test_deadline_on_an_owner_club_carrying_too_many_arms(league, monkeypatch):
    # The owner left 14 pitchers active (12 hitters): the deadline fill brings
    # the staff back to the limit without cutting anyone.
    everyone = _write_league(league, {OWNER: OVER, OTHER_OWNER: FULL, CPU: OVER})

    _run_deadline(league, monkeypatch)

    for tid in TEAMS:
        levels = _levels(tid)
        assert _act_pitchers(levels) <= MAX_ACTIVE_PITCHERS, tid
        assert len(levels["act"]) <= ACTIVE_ROSTER_SIZE, tid
    _assert_nobody_released(league, everyone)


def test_september_deadline_keeps_legal_call_ups(league, monkeypatch):
    # From Sept 1 in the regular season 28 active / 14 pitchers is legal: the
    # deadline fill must not strip an owner's September call-ups.
    from playbalance import season_manager as sm

    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda *a, **k: "2026-09-10")
    monkeypatch.setattr(
        sm,
        "SeasonManager",
        lambda *a, **k: SimpleNamespace(phase=sm.SeasonPhase.REGULAR_SEASON),
    )
    september = {
        "act_pitchers": SEPTEMBER_MAX_ACTIVE_PITCHERS,
        "act_hitters": SEPTEMBER_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS,
    }
    everyone = _write_league(league, {tid: september for tid in TEAMS})
    before = _levels(OWNER)["act"]

    result = _run_deadline(league, monkeypatch)

    assert OWNER in result["filled"]
    owner = _levels(OWNER)
    assert set(before) <= set(owner["act"]), "no September call-up was sent down"
    assert _act_pitchers(owner) <= SEPTEMBER_MAX_ACTIVE_PITCHERS
    for tid in TEAMS:
        levels = _levels(tid)
        assert _act_pitchers(levels) <= SEPTEMBER_MAX_ACTIVE_PITCHERS, tid
        assert len(levels["act"]) <= SEPTEMBER_ROSTER_SIZE, tid
    _assert_nobody_released(league, everyone)
