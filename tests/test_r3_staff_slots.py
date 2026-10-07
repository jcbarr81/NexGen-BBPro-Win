"""MR4/MR5 optional staff slots (Release 3, item C, owner decision Q7).

Eleven slots stay required; MR4 and MR5 are optional homes for the 12th and
13th active arms. The validator accepts them, warns (never blocks) on a label
that is not a slot or a slot listed twice, and the Pitching auto-fill fills
them while arms remain. The /pitching/autofill endpoint picks pitchers with
the shared roster rule instead of the stale ``role`` column. Nothing here
touches a real league.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from services.roster_validation import (
    ALL_STAFF_ROLES,
    PITCHING_ROLES,
    validate_pitching_staff,
)
from utils.pitcher_role import role_from_preferred
from utils.pitching_autofill import autofill_pitching_staff
from utils.roster_rules import MAX_ACTIVE_PITCHERS
from utils.staff_roles import OPTIONAL_PITCHING_ROLES, REQUIRED_PITCHING_ROLES

TEAM = "T1"


def _pitchers(n: int) -> dict[str, dict]:
    return {
        f"P{i}": {
            "player_id": f"P{i}",
            "first_name": "Arm",
            "last_name": str(i),
            "primary_position": "P",
            "is_pitcher": True,
        }
        for i in range(n)
    }


def _staff(roles) -> list[dict]:
    return [{"player_id": f"P{i}", "role": role} for i, role in enumerate(roles)]


# --- validate_pitching_staff ---------------------------------------------------


def test_slot_lists_come_from_staff_roles():
    assert tuple(PITCHING_ROLES) == REQUIRED_PITCHING_ROLES
    assert tuple(ALL_STAFF_ROLES) == REQUIRED_PITCHING_ROLES + OPTIONAL_PITCHING_ROLES


def test_full_thirteen_slot_staff_is_clean():
    staff = _staff(ALL_STAFF_ROLES)
    result = validate_pitching_staff(
        staff=staff, players=_pitchers(13), active_ids=[f"P{i}" for i in range(13)]
    )
    assert result.ok, result.errors
    assert result.warnings == []


def test_optional_slots_may_stay_empty():
    staff = _staff(REQUIRED_PITCHING_ROLES) + [{"player_id": "", "role": "MR4"}]
    result = validate_pitching_staff(staff=staff, players=_pitchers(11))
    assert result.ok, result.errors


def test_a_missing_required_slot_is_an_error():
    roles = [r for r in REQUIRED_PITCHING_ROLES if r != "MR2"] + ["MR4"]
    result = validate_pitching_staff(staff=_staff(roles), players=_pitchers(11))
    assert not result.ok
    assert result.errors == ["Role MR2 is not assigned."]


def test_legacy_mr_label_warns_but_saves():
    staff = _staff(list(REQUIRED_PITCHING_ROLES) + ["MR"])
    result = validate_pitching_staff(staff=staff, players=_pitchers(12))
    assert result.ok, result.errors
    assert len(result.warnings) == 1 and "MR is not a staff slot" in result.warnings[0]


def test_duplicate_slot_warns_but_saves():
    """An older file's two SU rows: the second SU pitcher is still checked."""
    staff = _staff(list(REQUIRED_PITCHING_ROLES) + ["SU"])
    players = _pitchers(12)
    result = validate_pitching_staff(staff=staff, players=players)
    assert result.ok, result.errors
    assert result.warnings == ["Role SU is listed 2 times."]

    players["P11"]["is_pitcher"] = False
    result = validate_pitching_staff(staff=staff, players=players)
    assert not result.ok
    assert any("is not a pitcher" in e for e in result.errors)


def test_a_pitcher_in_two_slots_is_still_an_error():
    staff = _staff(ALL_STAFF_ROLES)
    staff[-1]["player_id"] = "P0"  # MR5 repeats SP1
    result = validate_pitching_staff(staff=staff, players=_pitchers(13))
    assert not result.ok
    assert any("assigned to both SP1 and MR5" in e for e in result.errors)


def test_an_inactive_optional_slot_holder_is_an_error():
    staff = _staff(ALL_STAFF_ROLES)
    active = [f"P{i}" for i in range(12)]  # P12 (MR5) was optioned down
    result = validate_pitching_staff(staff=staff, players=_pitchers(13), active_ids=active)
    assert not result.ok
    assert result.errors == ["MR5: Arm 12 is not on the active roster."]


# --- auto-fill -------------------------------------------------------------------


def _arms(n: int) -> list[tuple[str, dict]]:
    out = [(f"sp{i}", {"role": "SP", "endurance": 90 - i}) for i in range(5)]
    out += [(f"rp{i}", {"role": "RP", "endurance": 50 - i}) for i in range(n - 5)]
    return out


@pytest.mark.parametrize(
    "arms,optional",
    [(13, ["MR4", "MR5"]), (12, ["MR4"]), (11, []), (9, [])],
)
def test_autofill_fills_optional_slots_while_arms_remain(arms, optional):
    assignments = autofill_pitching_staff(_arms(arms))
    assert len(assignments) == min(arms, len(ALL_STAFF_ROLES))
    assert [r for r in OPTIONAL_PITCHING_ROLES if r in assignments] == optional
    assert len(set(assignments.values())) == len(assignments)


def test_autofill_of_thirteen_lists_every_active_arm():
    arms = _arms(MAX_ACTIVE_PITCHERS)
    assignments = autofill_pitching_staff(arms)
    assert set(assignments.values()) == {pid for pid, _ in arms}
    assert sorted(assignments) == sorted(ALL_STAFF_ROLES)


def test_autofill_never_slots_a_fourteenth_arm():
    assignments = autofill_pitching_staff(_arms(14))
    assert sorted(assignments) == sorted(ALL_STAFF_ROLES)


# --- relief tokens -----------------------------------------------------------------


@pytest.mark.parametrize("token", ["MR4", "MR5", "mr4", "MR12"])
def test_numbered_middle_relief_slots_read_as_relief(token):
    assert role_from_preferred(token) == "RP"


def test_unknown_tokens_still_fall_through():
    assert role_from_preferred("MRX") == ""
    assert role_from_preferred("SP4") == "SP"


# --- /teams/{team_id}/pitching/autofill ---------------------------------------------


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,"
        "primary_color,secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text("", encoding="utf-8")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _write_league(root: Path, pitchers: list[dict], hitters: list[dict]) -> None:
    header = [
        "player_id", "first_name", "last_name", "primary_position",
        "other_positions", "is_pitcher", "role", "endurance",
        "preferred_pitching_role", "birthdate",
    ]
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in pitchers + hitters:
            writer.writerow({k: row.get(k, "") for k in header})
    lines = [f"{row['player_id']},ACT" for row in pitchers + hitters]
    (root / "rosters" / f"{TEAM}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_autofill_endpoint_uses_the_roster_rule_not_the_role_column(data_dir):
    import api.routers.lineups as lineups

    pitchers = [
        {"player_id": f"P{i}", "first_name": "Arm", "last_name": str(i),
         "primary_position": "P", "is_pitcher": "1", "role": "SP" if i < 5 else "RP",
         "endurance": str(80 - i)}
        for i in range(12)
    ]
    # The 13th arm is a flagged pitcher listed at SP with an empty role
    # column. The old filter (role SP/RP or primary "P") dropped him.
    pitchers.append(
        {"player_id": "P12", "first_name": "Late", "last_name": "Arm",
         "primary_position": "SP", "is_pitcher": "1", "role": "", "endurance": ""}
    )
    hitters = [
        # A position player whose stale role column says "RP".
        {"player_id": "H0", "first_name": "Stale", "last_name": "Role",
         "primary_position": "SS", "is_pitcher": "0", "role": "RP", "endurance": "30"},
    ]
    _write_league(data_dir, pitchers, hitters)

    out = lineups.autofill_pitching_staff_endpoint(TEAM, identity={"r": "admin", "u": "c", "t": ""})
    staff = {row["player_id"]: row["role"] for row in out["staff"]}
    assert "H0" not in staff
    assert "P12" in staff
    assert sorted(staff.values()) == sorted(ALL_STAFF_ROLES)

    with (data_dir / "rosters" / f"{TEAM}_pitching.csv").open(newline="", encoding="utf-8") as fh:
        written = [row for row in csv.reader(fh) if row]
    assert len(written) == 13


def test_autofill_endpoint_is_owner_only(data_dir):
    from fastapi import HTTPException

    import api.routers.lineups as lineups

    with pytest.raises(HTTPException) as exc:
        lineups.autofill_pitching_staff_endpoint(TEAM, identity={"r": "user", "u": "x", "t": "OTHER"})
    assert exc.value.status_code == 403
