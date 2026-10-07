"""26-man auto-assign review fixes (owner decision 8, 7.46.0).

- C1: a surplus pitcher demoted into a full AAA must not leave AAA over its
  cap when the active roster just dropped below its own.
- C2: auto-assign resolves the September caps (28 / 14) from the date, so a
  "fill gaps" run never strips legal September call-ups.
- C3: a full reassign of an organisation over the limit releases only the
  excess, not every unplaced player.
- C4: the gaps pitcher trim demotes relievers before starters and never
  breaks the rotation.
- C5: ``POST /reassign/all`` reports what it did, and refuses (409) when
  ownership is unknown.
- C6: a relative ``teams_file`` reads ownership next to the teams file.

Nothing here touches a real league.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.roster import Roster
from services import roster_auto_assign as ra
from services.roster_validation import validate_roster_state
from utils.roster_rules import (
    AAA_CAP,
    ACTIVE_ROSTER_SIZE,
    LOW_CAP,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
)

STARTER_POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
AS_OF = date(2025, 1, 1)


def _hitter(pid, pos, ovr=70, age=24):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=False,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, arm=ovr, gf=ovr, eye=ovr,
        birthdate=f"{AS_OF.year - age}-06-15", injured=False,
        first_name="First", last_name=pid,
    )


def _arm(pid, ovr=70, age=24, pos="P", endurance=None):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=True,
        arm=ovr, control=ovr, movement=ovr,
        endurance=ovr if endurance is None else endurance, fb=ovr,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, gf=ovr, eye=ovr,
        birthdate=f"{AS_OF.year - age}-06-15", injured=False,
        first_name="First", last_name=pid,
    )


def _org(*, act_pitchers, act_hitters, aaa_hitters=10, aaa_pitchers=5, low=LOW_CAP):
    """ACT with full coverage, AAA and a young LOW. Returns (players, Roster)."""

    players = {}
    act, aaa, low_ids = [], [], []
    for i in range(act_hitters):
        pos = STARTER_POSITIONS[i] if i < len(STARTER_POSITIONS) else "1B"
        p = _hitter(f"ACT_H{i}", pos)
        players[p.player_id] = p
        act.append(p.player_id)
    for i in range(act_pitchers):
        p = _arm(f"ACT_P{i}", ovr=70 - i)
        players[p.player_id] = p
        act.append(p.player_id)
    for i in range(aaa_hitters):
        p = _hitter(f"AAA_H{i}", "1B", ovr=55 + i, age=25)
        players[p.player_id] = p
        aaa.append(p.player_id)
    for i in range(aaa_pitchers):
        p = _arm(f"AAA_P{i}", ovr=55, age=25)
        players[p.player_id] = p
        aaa.append(p.player_id)
    for i in range(low):
        p = _hitter(f"LOW_{i}", "1B", ovr=45, age=19)
        players[p.player_id] = p
        low_ids.append(p.player_id)
    return players, Roster(team_id="T", act=act, aaa=aaa, low=low_ids)


def _run(monkeypatch, players, roster, **kwargs):
    saved = {}
    monkeypatch.setattr(ra, "load_roster", lambda *a, **k: roster)
    monkeypatch.setattr(ra, "save_roster", lambda tid, r, **k: saved.update(r=r))
    monkeypatch.setattr(ra, "_resolve_strategy_profile_token", lambda *a, **k: "balanced")
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    monkeypatch.setattr(
        "services.contracts_service.release_contracts_to_free_agency", lambda ids: None
    )
    kwargs.setdefault("as_of_date", AS_OF)
    result = ra.auto_assign_team("T", players_by_id=players, age_cache={}, **kwargs)
    return result, saved.get("r")


def _validate(players, roster, **kwargs):
    rows = {}
    for pid, p in players.items():
        rows[pid] = {
            "player_id": pid,
            "primary_position": p.primary_position,
            "other_positions": p.other_positions,
            "is_pitcher": p.is_pitcher,
            "age": AS_OF.year - int(p.birthdate[:4]) - 1,
        }
    levels = {"act": roster.act, "aaa": roster.aaa, "low": roster.low}
    return validate_roster_state(current_levels=levels, players=rows, **kwargs)


def _act_pitchers(players, roster):
    return [pid for pid in roster.act if players[pid].is_pitcher]


# --- C1: the pitcher trim must not strand AAA over its cap -----------------


def test_gaps_pitcher_trim_into_full_aaa_promotes_a_hitter(monkeypatch):
    players, roster = _org(act_pitchers=14, act_hitters=11)
    assert (len(roster.act), len(roster.aaa), len(roster.low)) == (25, AAA_CAP, LOW_CAP)

    result, r = _run(monkeypatch, players, roster, mode="gaps")

    assert result["released"] == []
    assert result["overflow"] == []
    assert len(_act_pitchers(players, r)) == MAX_ACTIVE_PITCHERS
    assert len(r.aaa) == AAA_CAP
    # The best AAA bat took the slot the demoted arm freed.
    assert "AAA_H9" in r.act
    check = _validate(players, r)
    assert check.ok, check.errors


def test_gaps_full_26_man_at_org_limit_with_14_pitchers(monkeypatch):
    players, roster = _org(act_pitchers=14, act_hitters=12)
    assert len(roster.act) == ACTIVE_ROSTER_SIZE
    assert len(roster.act) + len(roster.aaa) + len(roster.low) == ORG_LIMIT

    result, r = _run(monkeypatch, players, roster, mode="gaps")

    assert result["released"] == [] and result["overflow"] == []
    assert len(r.act) == ACTIVE_ROSTER_SIZE
    assert len(_act_pitchers(players, r)) == MAX_ACTIVE_PITCHERS
    check = _validate(players, r)
    assert check.ok, check.errors


def test_gaps_pitcher_trim_falls_back_to_low_when_aaa_has_no_bats(monkeypatch):
    # AAA is all arms (nobody can fill the freed ACT slot under the pitcher
    # cap) but LOW has room: an age-eligible AAA player goes down instead.
    players, roster = _org(
        act_pitchers=14, act_hitters=11, aaa_hitters=0, aaa_pitchers=AAA_CAP, low=5
    )
    result, r = _run(monkeypatch, players, roster, mode="gaps")
    assert result["released"] == [] and result["overflow"] == []
    assert len(r.aaa) == AAA_CAP and len(r.low) == 6
    assert _validate(players, r).ok


# --- C2: September caps come from the date --------------------------------


def _regular_season(monkeypatch):
    from playbalance import season_manager as sm

    monkeypatch.setattr(
        sm,
        "SeasonManager",
        lambda *a, **k: SimpleNamespace(phase=sm.SeasonPhase.REGULAR_SEASON),
    )


def _september_org():
    players, roster = _org(
        act_pitchers=SEPTEMBER_MAX_ACTIVE_PITCHERS,
        act_hitters=SEPTEMBER_ROSTER_SIZE - SEPTEMBER_MAX_ACTIVE_PITCHERS,
        aaa_hitters=4,
        aaa_pitchers=4,
        low=3,
    )
    assert len(roster.act) == SEPTEMBER_ROSTER_SIZE
    return players, roster


def test_gaps_in_september_keeps_a_28_14_roster(monkeypatch):
    _regular_season(monkeypatch)
    players, roster = _september_org()
    result, r = _run(monkeypatch, players, roster, mode="gaps", as_of_date=date(2026, 9, 10))
    assert result["moved"] == []
    assert len(r.act) == SEPTEMBER_ROSTER_SIZE
    assert len(_act_pitchers(players, r)) == SEPTEMBER_MAX_ACTIVE_PITCHERS


def test_gaps_in_august_trims_the_same_roster(monkeypatch):
    _regular_season(monkeypatch)
    players, roster = _september_org()
    result, r = _run(monkeypatch, players, roster, mode="gaps", as_of_date=date(2026, 8, 15))
    assert len(r.act) == ACTIVE_ROSTER_SIZE
    assert len(_act_pitchers(players, r)) <= MAX_ACTIVE_PITCHERS
    assert result["released"] == []


def test_gaps_without_a_date_uses_the_current_sim_date(monkeypatch):
    # The deadline fill, readiness cpu-fill, the team endpoint and opt-in
    # auto-reassign pass no date: the league's sim date decides the caps.
    _regular_season(monkeypatch)
    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda *a, **k: "2026-09-10")
    players, roster = _september_org()
    result, r = _run(monkeypatch, players, roster, mode="gaps", as_of_date=None)
    assert result["moved"] == []
    assert len(r.act) == SEPTEMBER_ROSTER_SIZE


def test_explicit_caps_still_win(monkeypatch):
    _regular_season(monkeypatch)
    players, roster = _september_org()
    _, r = _run(
        monkeypatch,
        players,
        roster,
        mode="gaps",
        as_of_date=date(2026, 9, 10),
        act_cap=ACTIVE_ROSTER_SIZE,
        pitcher_cap=MAX_ACTIVE_PITCHERS,
    )
    assert len(r.act) == ACTIVE_ROSTER_SIZE


# --- C3: a full reassign over the limit releases only the excess ----------


def _vet_hitter(pid, pos, ovr):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=False,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, arm=ovr, gf=ovr, eye=ovr, birthdate="1990-06-15",
    )


def _vet_arm(pid, ovr):
    return SimpleNamespace(
        player_id=pid, primary_position="P", other_positions="", is_pitcher=True,
        arm=ovr, control=ovr, movement=ovr, endurance=ovr, fb=ovr,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, gf=ovr, eye=ovr, birthdate="1990-06-15",
    )


def test_full_mode_one_over_the_org_limit_releases_exactly_one(monkeypatch):
    hitters = [_vet_hitter(f"H_{pos}", pos, 70) for pos in STARTER_POSITIONS]
    hitters += [_vet_hitter(f"H_X{i}", "1B", 60) for i in range(4)]
    pitchers = [_vet_arm(f"PIT{i:02d}", 80 - i) for i in range(40)]
    everyone = hitters + pitchers
    players = {p.player_id: p for p in everyone}
    assert len(players) == ORG_LIMIT + 1
    roster = Roster(team_id="T", act=[p.player_id for p in everyone])

    result, r = _run(monkeypatch, players, roster, mode="full", as_of_date=None)

    assert result["released"] == ["PIT39"], "only the weakest player goes"
    assert len(result["overflow"]) == 11
    kept = set(r.act) | set(r.aaa) | set(r.low)
    assert len(kept) == ORG_LIMIT
    assert set(result["overflow"]) <= set(r.aaa)


# --- C4: the gaps pitcher trim protects the rotation -----------------------


def _rotation_org():
    """13 hitters + 14 arms: 5 starters (one the weakest arm) and 9 relievers."""

    players, roster = _org(act_pitchers=0, act_hitters=13, aaa_hitters=4, aaa_pitchers=0, low=0)
    for i in range(5):
        p = _arm(f"SP{i}", ovr=30 if i == 4 else 75, pos="SP")
        players[p.player_id] = p
        roster.act.append(p.player_id)
    for i in range(9):
        p = _arm(f"RP{i}", ovr=60 + i, pos="RP")
        players[p.player_id] = p
        roster.act.append(p.player_id)
    return players, roster


def test_gaps_trim_sends_a_reliever_not_the_weakest_starter(monkeypatch, tmp_path):
    players, roster = _rotation_org()
    result, r = _run(monkeypatch, players, roster, mode="gaps", roster_dir=str(tmp_path))
    assert "SP4" in r.act, "a rotation starter must not be demoted"
    assert "RP0" in r.aaa, "the weakest reliever goes down"
    assert len(_act_pitchers(players, r)) == MAX_ACTIVE_PITCHERS
    assert result["released"] == []


def test_gaps_trim_demotes_unslotted_arms_before_slotted_relievers(monkeypatch, tmp_path):
    players, roster = _rotation_org()
    # The staff file slots the rotation and RP0 (the weakest reliever) as the
    # closer; RP5 has no role, so he goes down even though he rates higher.
    rows = [f"SP{i},SP{i + 1}" for i in range(5)] + ["RP0,CL"]
    rows += [f"RP{i},MR" for i in range(1, 9) if i != 5]
    (tmp_path / "T_pitching.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    result, r = _run(monkeypatch, players, roster, mode="gaps", roster_dir=str(tmp_path))
    assert "RP5" in r.aaa
    assert "RP0" in r.act and "SP4" in r.act
    assert result["released"] == []


def test_gaps_trim_with_a_full_rotation_treats_spare_starters_as_relievers(
    monkeypatch, tmp_path
):
    # The staff file names five active starters; a sixth "SP" with no slot is
    # a spare arm and goes before any slotted reliever.
    players, roster = _rotation_org()
    roster.act.remove("RP8")
    spare = _arm("SPARE", ovr=90, pos="SP")
    players[spare.player_id] = spare
    roster.act.append(spare.player_id)
    rows = [f"SP{i},SP{i + 1}" for i in range(5)]
    rows += [f"RP{i},MR" for i in range(8)]
    (tmp_path / "T_pitching.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    _, r = _run(monkeypatch, players, roster, mode="gaps", roster_dir=str(tmp_path))
    assert "SPARE" in r.aaa
    assert all(f"SP{i}" in r.act for i in range(5))


# --- C5: /reassign/all reports its summary ----------------------------------


def test_reassign_all_returns_the_summary(monkeypatch):
    from api.routers import reassign

    summary = {"assigned": ["A"], "skipped_owned": ["B"], "ownership_unknown": False}
    monkeypatch.setattr(reassign, "auto_assign_all_teams", lambda: dict(summary))
    out = asyncio.run(reassign.auto_assign_all({"r": "admin"}))
    assert out == {"status": "ok", **summary}


def test_reassign_all_refuses_when_ownership_is_unknown(monkeypatch):
    from api.routers import reassign

    monkeypatch.setattr(
        reassign,
        "auto_assign_all_teams",
        lambda: {"assigned": [], "skipped_owned": [], "ownership_unknown": True},
    )
    with pytest.raises(HTTPException) as err:
        asyncio.run(reassign.auto_assign_all({"r": "admin"}))
    assert err.value.status_code == 409
    assert "ownership" in str(err.value.detail).lower()


# --- C6: a relative teams_file reads ownership next to it -----------------


def test_relative_teams_file_reads_users_next_to_it(monkeypatch, tmp_path):
    import utils.path_utils as path_utils

    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "users.txt").write_text("", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    path_utils._DATA_DIR_CACHE.clear()

    base = tmp_path / "base"
    league = base / "league"
    league.mkdir(parents=True)
    (league / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n"
        "AAA,A,A,AAA,East,S,#000,#fff,\n"
        "BBB,B,B,BBB,East,S,#000,#fff,\n",
        encoding="utf-8",
    )
    (league / "users.txt").write_text("owner,pw,owner,AAA\n", encoding="utf-8")
    monkeypatch.setattr(path_utils, "get_base_dir", lambda: base)

    calls = []
    monkeypatch.setattr(ra, "auto_assign_team", lambda tid, **k: calls.append(tid))
    monkeypatch.setattr(ra, "auto_fill_lineup_for_team", lambda *a, **k: None)
    monkeypatch.setattr(ra, "load_players_from_csv", lambda *a, **k: [])
    monkeypatch.setattr(ra, "_resolve_strategy_profile_token", lambda *a, **k: "balanced")
    try:
        summary = ra.auto_assign_all_teams(teams_file="league/teams.csv")
    finally:
        path_utils._DATA_DIR_CACHE.clear()

    assert summary["ownership_unknown"] is False
    assert summary["skipped_owned"] == ["AAA"]
    assert calls == ["BBB"]
