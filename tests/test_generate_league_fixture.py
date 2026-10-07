"""Audit 2026-10-06 H3 (Release 2): the league-like KPI fixture.

``scripts/generate_league_fixture.py`` builds ``data/calibration_league`` from
the product's own league creation, auto-assign and auto-fill code. These tests
pin what makes it "league-like" (the things the hand-built calibration fixture
lacks), that the generator is deterministic and isolated, and that the
committed files are what the current code generates.
"""
from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
from pathlib import Path


from utils.park_utils import park_lookup_name_for_team
from utils.team_loader import load_teams

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "data" / "calibration_league"
SCRIPT = REPO / "scripts" / "generate_league_fixture.py"
AUTOFILL_SLOTS = sorted(
    ["SP1", "SP2", "SP3", "SP4", "SP5", "LR", "CL", "SU", "MR1", "MR2", "MR3"]
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _plain(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.reader(fh) if row]


def _hash_tree(root: Path) -> dict[str, str]:
    # Line endings normalised: a Windows checkout with core.autocrlf turns the
    # committed LF files into CRLF on disk.
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _generate(out: Path, *extra: str) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(out), *extra],
        cwd=REPO,
        check=True,
        capture_output=True,
        timeout=300,
    )


def _is_pitcher(row: dict[str, str]) -> bool:
    return row.get("is_pitcher", "").strip().lower() in {"1", "true"}


def test_every_team_plays_in_the_generic_park():
    # H3: the calibration fixture passes partly on real MLB parks; alpha-test
    # plays on the generic park. An empty park_id means "nothing chosen" (L13).
    teams = load_teams(str(FIXTURE / "teams.csv"))
    assert 20 <= len(teams) <= 30
    for team in teams:
        assert team.park_id == ""
        assert park_lookup_name_for_team(team) is None


def test_rosters_are_real_selections_with_autofill_staffs():
    players = {r["player_id"]: r for r in _rows(FIXTURE / "players.csv")}
    for team in _rows(FIXTURE / "teams.csv"):
        tid = team["team_id"]
        roster = _plain(FIXTURE / "rosters" / f"{tid}.csv")
        levels: dict[str, list[str]] = {}
        for pid, level in roster:
            levels.setdefault(level, []).append(pid)
        act = levels["ACT"]
        # A whole organisation (ACT + minors), not just 26 actives.
        assert len(roster) == 50 and len(levels["AAA"]) > 0 and len(levels["LOW"]) > 0
        assert len(act) == 25
        assert sum(_is_pitcher(players[pid]) for pid in act) == 13

        # The Pitching auto-fill's 11 rows, MR1-MR3 labels included (H1).
        staff = _plain(FIXTURE / "rosters" / f"{tid}_pitching.csv")
        assert sorted(role for _, role in staff) == AUTOFILL_SLOTS
        assert all(pid in act for pid, _ in staff)

        for hand in ("lhp", "rhp"):
            lineup = _rows(FIXTURE / "lineups" / f"{tid}_vs_{hand}.csv")
            assert len(lineup) == 9
            assert all(slot["player_id"] in act for slot in lineup)
            assert not any(_is_pitcher(players[s["player_id"]]) for s in lineup)


def test_act_is_each_organisations_best():
    from services.roster_auto_assign import _overall_score
    from utils.player_loader import load_players_from_csv

    players = {p.player_id: p for p in load_players_from_csv(str(FIXTURE / "players.csv"))}
    beaten = 0
    total = 0
    for team in _rows(FIXTURE / "teams.csv"):
        roster = _plain(FIXTURE / "rosters" / f"{team['team_id']}.csv")
        act = [players[pid] for pid, level in roster if level == "ACT"]
        minors = [players[pid] for pid, level in roster if level != "ACT"]
        for is_p in (True, False):
            act_scores = [_overall_score(p) for p in act if bool(p.is_pitcher) == is_p]
            for p in minors:
                if bool(p.is_pitcher) != is_p:
                    continue
                total += 1
                beaten += _overall_score(p) > sorted(act_scores)[len(act_scores) // 2]
    # Coverage rules (a backup C, SP slots) can seat a weaker player, but a
    # random 25 (what create_league hands out) would put about half the minors
    # above the active median.
    assert beaten / total < 0.05


def test_fixture_has_archetype_speed_tiers():
    # Decision 3 keeps the tiers: alpha-test has 15.5% of hitters at SP >= 70,
    # spiking at exactly 70 and 85; the calibration fixture tops out at 67.
    hitters = [r for r in _rows(FIXTURE / "players.csv") if not _is_pitcher(r)]
    speeds = [int(r["sp"]) for r in hitters]
    share = sum(s >= 70 for s in speeds) / len(speeds)
    assert 0.10 <= share <= 0.22
    assert speeds.count(70) >= 0.5 * sum(s >= 70 for s in speeds if s < 85)
    assert speeds.count(85) > 0


def test_generator_is_deterministic_and_seed_driven(tmp_path):
    _generate(tmp_path / "a", "--teams", "4", "--seed", "7")
    _generate(tmp_path / "b", "--teams", "4", "--seed", "7")
    _generate(tmp_path / "c", "--teams", "4", "--seed", "8")
    # The generator writes LF only (AGENTS.md), whatever the platform.
    for path in (tmp_path / "a").rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path
    a = _hash_tree(tmp_path / "a")
    assert a == _hash_tree(tmp_path / "b")
    assert a["players.csv"] != _hash_tree(tmp_path / "c")["players.csv"]


def test_generator_refuses_real_league_dirs(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir",
         str(REPO / "data" / "leagues" / "fixture-test")],
        cwd=REPO,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert not (REPO / "data" / "leagues" / "fixture-test").exists()


def test_committed_fixture_matches_the_current_generator(tmp_path):
    """The committed files are exactly what the generator makes today.

    If this fails, generation code changed (the generator, auto-assign, the
    Pitching or lineup auto-fill): regenerate with
    ``PYTHONHASHSEED=0 python scripts/generate_league_fixture.py`` and commit
    the new fixture with that change.
    """

    _generate(tmp_path / "fixture")
    assert _hash_tree(tmp_path / "fixture") == _hash_tree(FIXTURE)
