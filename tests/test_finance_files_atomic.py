"""8.3.2: reading the books never rewrites (or empties) the contracts file.

An owner's offer dialog showed "Payroll $0 -> $20M" for a club paying $55M.
``ensure_financial_defaults`` runs on read paths (every offer preview, every
payroll outlook) and rewrote contracts.json / team_financials.json on every
call with a truncate-then-write; the preview re-runs on each keystroke, so a
concurrent read caught the empty file and read it as "no contracts".
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from services import contracts_service as cs
from services import finance_settings as fs


@pytest.fixture
def books(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\nBAL,B,B,BAL,E,S,#000000,#FFFFFF,\n",
        encoding="utf-8",
    )
    contracts = {
        "version": 1,
        "players": {
            f"P{i}": {"team_id": "BAL", "annual_salary": 1_000_000, "years_left": 2}
            for i in range(200)
        },
    }
    (root / "contracts.json").write_text(json.dumps(contracts, indent=2), encoding="utf-8")
    fs.ensure_financial_defaults(data_dir=root, league_id="lg")  # settle formats
    return root


def test_reading_paths_do_not_rewrite_unchanged_files(books):
    paths = [books / "contracts.json", books / "team_financials.json",
             books / "league_financial_settings.json"]
    before = {p: os.stat(p).st_mtime_ns for p in paths}
    for _ in range(3):
        fs.ensure_financial_defaults(data_dir=books, league_id="lg")
        fs.ensure_financial_defaults(data_dir=books, league_id="lg", write_missing=False)
    assert {p: os.stat(p).st_mtime_ns for p in paths} == before


def test_payroll_never_reads_empty_while_files_are_ensured(books):
    from services.payroll_engine import calculate_annual_payroll_totals

    stop = threading.Event()
    seen: list[int] = []

    def ensure_loop():
        while not stop.is_set():
            fs.ensure_financial_defaults(data_dir=books, league_id="lg")
            cs.save_contracts_payload(cs.load_contracts_payload(data_dir=books), data_dir=books)

    worker = threading.Thread(target=ensure_loop)
    worker.start()
    try:
        for _ in range(300):
            seen.append(calculate_annual_payroll_totals(data_dir=books).get("BAL", 0))
    finally:
        stop.set()
        worker.join()
    assert min(seen) == 200_000_000


def test_a_read_that_meets_a_bad_file_tries_again(books, monkeypatch):
    real = Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        if self.name == "contracts.json" and calls["n"] == 0:
            calls["n"] += 1
            return ""  # caught mid-write
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    payload = cs.load_contracts_payload(data_dir=books)
    assert len(payload["players"]) == 200
