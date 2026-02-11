import csv
from pathlib import Path

import pytest

from services import draft_assignment
from services.roster_moves import cut_player
from services.transaction_log import load_transactions, reset_player_cache
from utils.exceptions import DraftRosterError
from utils.roster_loader import load_roster


def _prepare_base(tmp_path: Path, monkeypatch) -> Path:
    data = tmp_path / "data"
    rosters = data / "rosters"
    rosters.mkdir(parents=True)
    monkeypatch.setattr("utils.path_utils.get_base_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.path_utils.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.roster_loader.get_base_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.roster_loader.get_data_dir", lambda: data)
    monkeypatch.setattr("utils.player_loader.get_base_dir", lambda: tmp_path)
    monkeypatch.setattr("utils.player_loader.get_data_dir", lambda: data)
    monkeypatch.setattr(draft_assignment, "BASE", tmp_path)
    monkeypatch.setattr(draft_assignment, "DATA", data)
    import services.transaction_log as tx

    monkeypatch.setattr(tx, "_TRANSACTIONS_PATH", data / "transactions.csv")
    monkeypatch.setattr(tx, "get_base_dir", lambda: tmp_path)
    reset_player_cache()
    try:
        load_roster.cache_clear()
    except AttributeError:
        pass
    return data


def _write_players(path: Path, rows: list[list[str]]) -> None:
    with (path / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["player_id", "first_name", "last_name"])
        for row in rows:
            writer.writerow(row)


def _write_roster(path: Path, team: str, entries: list[tuple[str, str]]) -> None:
    roster_path = path / "rosters" / f"{team}.csv"
    with roster_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for pid, level in entries:
            writer.writerow([pid, level])


def _write_draft_files(path: Path, year: int, results: list[tuple[str, str]], pool_rows: list[dict[str, str]]):
    res_path = path / f"draft_results_{year}.csv"
    with res_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["player_id", "team_id"])
        for pid, tid in results:
            writer.writerow([pid, tid])
    pool_path = path / f"draft_pool_{year}.csv"
    if not pool_rows:
        return
    fieldnames = sorted({key for row in pool_rows for key in row})
    with pool_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in pool_rows:
            writer.writerow(row)


@pytest.mark.parametrize("low_entries", [10, 9])
def test_commit_draft_results_handles_low_capacity(tmp_path, monkeypatch, low_entries):
    data = _prepare_base(tmp_path, monkeypatch)
    _write_players(data, [["p000", "Existing", "Player"]])
    low_roster = [(f"low{i}", "LOW") for i in range(low_entries)]
    _write_roster(data, "AAA", [(f"act{i}", "ACT") for i in range(25)] + low_roster)
    _write_draft_files(
        data,
        2025,
        [("d100", "AAA")],
        [{
            "player_id": "d100",
            "first_name": "Casey",
            "last_name": "Draftpick",
            "is_pitcher": "0",
            "primary_position": "SS",
        }],
    )

    roster_file = data / "rosters" / "AAA.csv"
    if low_entries >= draft_assignment.LOW_MAX:
        with pytest.raises(DraftRosterError) as exc:
            draft_assignment.commit_draft_results(2025, season_date="2025-07-15")
        summary = exc.value.summary
        assert summary.get("players_added") == 1
        assert summary.get("roster_assigned") == 1
        compliance = summary.get("compliance_issues") or []
        assert any("LOW roster exceeds" in msg for msg in compliance)
    else:
        summary = draft_assignment.commit_draft_results(2025, season_date="2025-07-15")
        assert summary["players_added"] == 1
        assert summary["roster_assigned"] == 1
        assert not summary.get("compliance_issues")

    with roster_file.open(encoding="utf-8") as fh:
        rows = [line.strip().split(',') for line in fh.readlines() if line.strip()]
    low_ids = [pid for pid, level in rows if level == "LOW"]
    assert "d100" in low_ids

    with (data / "players.csv").open(encoding="utf-8") as fh:
        contents = fh.read()
    assert "d100" in contents

    transactions = load_transactions()
    assert transactions, "Draft should record a transaction entry"
    entry = transactions[0]
    assert entry["action"] == "draft"
    assert entry["team_id"] == "AAA"
    assert entry.get("player_id") == "d100"


def test_cut_player_updates_roster_and_logs(tmp_path, monkeypatch):
    data = _prepare_base(tmp_path, monkeypatch)
    _write_players(data, [["c001", "Taylor", "Release"]])
    _write_roster(data, "BBB", [(f"act{i}", "ACT") for i in range(25)] + [("c001", "AAA"), ("keep", "AAA")])

    roster = load_roster("BBB")
    cut_player("BBB", "c001", roster)

    refreshed = load_roster("BBB")
    assert "c001" not in refreshed.aaa

    transactions = load_transactions(team_id="BBB", actions={"cut"})
    assert transactions
    entry = transactions[0]
    assert entry["player_id"] == "c001"
    assert entry["from_level"] == "AAA"
    assert entry["to_level"] == "FA"
