"""A drafted player stays on the roster of the team that drafted him.

An owner noticed only one of his four 2026 picks on his roster. League-wide, 35
of alpha-test's 80 drafted players were on no roster at all, with nothing in the
transaction log to say why.

Every roster load runs the placeholder pool's ``reconcile_roster``, which drops
a "D..." player from a team when its registry says another team owns him. Two
faults turned that into silent data loss:

* the pool was one per PROCESS, not per league. Draft ids are D{year}{n} in
  every league, so whichever league drafted D20260013 first "owned" it
  everywhere -- alpha-test's registry held owners like DET, PHO and LOU;
* a wrong owner, once recorded, could never be corrected: hydration only filled
  missing entries, so the player was dropped on every load and the next save
  made it permanent.

On a copy of the live league the old code dropped 11 more rostered picks on a
single load; the fixed code drops none.
"""

import csv
import json
from pathlib import Path

import pytest

import utils.roster_loader as RL


def _league(root: Path, rosters: dict[str, list[tuple[str, str]]], registry=None) -> Path:
    data = root / "data"
    (data / "rosters").mkdir(parents=True)
    for team, rows in rosters.items():
        with (data / "rosters" / f"{team}.csv").open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
    if registry is not None:
        (data / "rosters" / "_placeholder_registry.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
    return data


@pytest.fixture
def use_league(monkeypatch):
    """Point the loader at a league directory, as the request context would."""
    RL._reset_placeholder_pool()
    RL.load_roster.cache_clear()
    current = {}

    def switch(data: Path):
        current["dir"] = data
        monkeypatch.setattr(RL, "get_data_dir", lambda: current["dir"])

    yield switch
    RL._reset_placeholder_pool()
    RL.load_roster.cache_clear()


def _ids(roster):
    return set(roster.act + roster.aaa + roster.low + roster.dl + roster.ir)


def _load(team, data):
    RL.load_roster.cache_clear()
    return RL.load_roster(team, data / "rosters")


# --- the regression --------------------------------------------------------


def test_a_registry_owner_from_another_league_does_not_drop_the_pick(tmp_path, use_league):
    """alpha-test's registry said D20260013 belonged to DET, a team it doesn't have."""
    data = _league(
        tmp_path / "alpha",
        {"CHA": [("P1", "ACT"), ("D20260013", "LOW")], "CHI": [("P2", "ACT")]},
        registry={"D20260013": "DET"},
    )
    use_league(data)
    assert "D20260013" in _ids(_load("CHA", data))


def test_a_wrong_owner_inside_the_league_is_corrected_by_the_roster_files(tmp_path, use_league):
    """CHI is a real team here, but only CHA's file lists him: CHA owns him."""
    data = _league(
        tmp_path / "alpha",
        {"CHA": [("P1", "ACT"), ("D20260013", "LOW")], "CHI": [("P2", "ACT")]},
        registry={"D20260013": "CHI"},
    )
    use_league(data)
    assert "D20260013" in _ids(_load("CHA", data))
    saved = json.loads((data / "rosters" / "_placeholder_registry.json").read_text())
    assert saved["D20260013"] == "CHA"


def test_two_leagues_drafting_the_same_id_do_not_interfere(tmp_path, use_league):
    """The cross-league collision itself: both leagues' 2026 drafts produce
    D20260013. Loading league B first must not decide league A's rosters."""
    league_b = _league(tmp_path / "b", {"DET": [("P9", "ACT"), ("D20260013", "LOW")]})
    league_a = _league(tmp_path / "a", {"CHA": [("P1", "ACT"), ("D20260013", "LOW")]})

    use_league(league_b)
    assert "D20260013" in _ids(_load("DET", league_b))
    use_league(league_a)
    assert "D20260013" in _ids(_load("CHA", league_a))
    # ...and league A's registry is not polluted with league B's teams.
    saved = json.loads((league_a / "rosters" / "_placeholder_registry.json").read_text())
    assert saved.get("D20260013") == "CHA"
    assert "DET" not in saved.values()


def test_foreign_team_entries_are_purged_from_the_registry(tmp_path, use_league):
    data = _league(
        tmp_path / "alpha",
        {"CHA": [("P1", "ACT")]},
        registry={"D20260050": "PHO", "D20260051": "LOU", "P1": "CHA"},
    )
    use_league(data)
    _load("CHA", data)
    saved = json.loads((data / "rosters" / "_placeholder_registry.json").read_text())
    assert set(saved.values()) <= {"CHA"}


def test_pitching_staff_files_are_not_mistaken_for_teams(tmp_path, use_league):
    """{team}_pitching.csv rows are (pid, role); the old hydrate registered
    pitchers to a pseudo-team called "CHA_pitching"."""
    data = _league(tmp_path / "alpha", {"CHA": [("P1", "ACT")]})
    with (data / "rosters" / "CHA_pitching.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([("P1", "SP1")])
    use_league(data)
    _load("CHA", data)
    path = data / "rosters" / "_placeholder_registry.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    assert not any("_" in team for team in saved.values())


# --- the dedupe it exists for still works ----------------------------------


def test_a_pick_genuinely_listed_by_two_teams_is_kept_by_only_one(tmp_path, use_league):
    data = _league(
        tmp_path / "alpha",
        {"CHA": [("P1", "ACT"), ("D20260013", "LOW")], "CHI": [("P2", "ACT"), ("D20260013", "LOW")]},
        registry={"D20260013": "CHA"},
    )
    use_league(data)
    on_cha = "D20260013" in _ids(_load("CHA", data))
    on_chi = "D20260013" in _ids(_load("CHI", data))
    assert on_cha and not on_chi
