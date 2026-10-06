import csv

from utils.roster_loader import load_roster


def test_load_roster_reads_levels_without_promoting(tmp_path):
    """Loading reads the levels as saved; it no longer tops up the active
    roster from AAA[0]. That silent, unrecorded refill undid an owner's open
    spot and replaced injured hitters with pitchers (audit H9, decision 14)."""

    roster_file = tmp_path / "T.csv"
    rows = [
        ["p1", "ACT"],
        ["p2", "AAA"],
        ["p3", "DL15"],
        ["p4", "DL45"],
        ["p5", "IR"],
        ["p6", "LOW"],
    ]
    with roster_file.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    roster = load_roster("T", roster_dir=tmp_path)

    assert roster.dl == ["p3"]
    assert roster.dl_tiers["p3"] == "dl15"
    assert roster.ir == ["p4", "p5"]
    assert roster.aaa == ["p2"]
    assert roster.low == ["p6"]
    assert "p2" not in roster.act and "p6" not in roster.act
