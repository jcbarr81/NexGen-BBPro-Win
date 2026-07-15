"""S2-01: handedness-aware two-pass lineup generation."""
import csv
from pathlib import Path

import pytest

from utils.lineup_autofill import auto_fill_lineup_for_team, _platoon_adjustment

COLUMNS = [
    "player_id", "first_name", "last_name", "birthdate", "height", "weight",
    "bats", "throws", "primary_position", "other_positions", "is_pitcher",
    "role", "ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm",
]


def _row(pid, pos, *, bats="R", vl=50, ch=50, ph=50, other="", is_pitcher=0):
    d = {c: "" for c in COLUMNS}
    d.update(
        player_id=pid, first_name="F", last_name="L", birthdate="1995-05-15",
        height="72", weight="200", bats=bats, throws=bats if bats != "S" else "R",
        primary_position=pos, other_positions=other, is_pitcher=str(is_pitcher),
        ch=str(ch), ph=str(ph), sp="50", eye="50", gf="50", pl="50",
        vl=str(vl), sc="50", fa="50", arm="50",
    )
    return d


def _write_league(tmp_path: Path, team: str, rows: list[dict]) -> tuple[Path, Path, Path]:
    players = tmp_path / "players.csv"
    rosters = tmp_path / "rosters"
    lineups = tmp_path / "lineups"
    rosters.mkdir()
    lineups.mkdir()
    with players.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with (rosters / f"{team}.csv").open("w", newline="", encoding="utf-8") as fh:
        for r in rows:
            fh.write(f"{r['player_id']},ACT\n")
    return players, rosters, lineups


def _read_lineup(path: Path) -> list[tuple[str, str]]:
    with path.open() as fh:
        return [(r["player_id"], r["position"]) for r in csv.DictReader(fh)]


def _roster_rows() -> list[dict]:
    rows = [
        _row("C1", "C"), _row("SS1", "SS"), _row("CF1", "CF"),
        _row("TB1", "3B"), _row("2B1", "2B"), _row("LF1", "LF"),
        _row("RF1", "RF"), _row("DH1", "DH"),
        # two 1B-only platoon candidates:
        _row("A", "1B", bats="R", vl=90, ch=60, ph=60),   # mashes LHP
        _row("B", "1B", bats="L", vl=30, ch=62, ph=62),   # better raw, worse vs LHP
    ]
    return rows


def test_platoon_candidate_produces_different_files(tmp_path):
    players, rosters, lineups = _write_league(tmp_path, "PLT", _roster_rows())
    auto_fill_lineup_for_team(
        "PLT", players_file=players, roster_dir=rosters, lineup_dir=lineups
    )
    lhp = _read_lineup(lineups / "PLT_vs_lhp.csv")
    rhp = _read_lineup(lineups / "PLT_vs_rhp.csv")
    assert lhp != rhp
    one_b_lhp = next(pid for pid, pos in lhp if pos == "1B")
    one_b_rhp = next(pid for pid, pos in rhp if pos == "1B")
    assert one_b_lhp == "A"   # R masher wins 1B vs LHP
    assert one_b_rhp == "B"   # lefty wins 1B vs RHP


def test_both_files_nine_unique_rows_and_coverage(tmp_path):
    players, rosters, lineups = _write_league(tmp_path, "COV", _roster_rows())
    auto_fill_lineup_for_team(
        "COV", players_file=players, roster_dir=rosters, lineup_dir=lineups
    )
    pitcher_ids: set[str] = set()
    for hand in ("lhp", "rhp"):
        rows = _read_lineup(lineups / f"COV_vs_{hand}.csv")
        assert len(rows) == 9
        pids = [pid for pid, _ in rows]
        assert len(set(pids)) == 9
        positions = {pos for _, pos in rows}
        assert {"C", "SS", "CF", "3B", "2B", "1B", "LF", "RF"} <= positions
        assert not (set(pids) & pitcher_ids)


def test_vs_filter_writes_single_file(tmp_path):
    players, rosters, lineups = _write_league(tmp_path, "ONE", _roster_rows())
    auto_fill_lineup_for_team(
        "ONE", players_file=players, roster_dir=rosters, lineup_dir=lineups, vs="lhp"
    )
    assert (lineups / "ONE_vs_lhp.csv").exists()
    assert not (lineups / "ONE_vs_rhp.csv").exists()


def test_platoon_adjustment_values():
    class P:
        def __init__(self, bats, vl):
            self.bats = bats
            self.vl = vl

    r = P("R", 90)
    assert _platoon_adjustment(r, vs_hand="L") == pytest.approx(1.2 + 0.135 * 40)   # 6.6
    assert _platoon_adjustment(r, vs_hand="R") == pytest.approx(-1.2 + 0.135 * (-0.35 * 40))  # -3.09
    s = P("S", 50)
    assert _platoon_adjustment(s, vs_hand="L") == pytest.approx(0.6)
    assert _platoon_adjustment(s, vs_hand="R") == pytest.approx(0.6)
