"""Guards against a data-loss bug where a finance READ (on a partially-hydrated
working copy) rewrote team_financials.json + contracts.json empty, and the
working-copy PUSH then clobbered the real bucket data with the empties.

Two independent guards:
1. finance reads pass write_missing=False -> a missing/unreadable finance file is
   NOT (re)written empty.
2. the working-copy copy refuses to overwrite a non-empty critical finance file
   with an empty one (either sync direction).
"""

import json
from pathlib import Path

from api.working_copy import _copy_one, _finance_json_is_empty
from services.finance_settings import (
    _ensure_contracts_file,
    _ensure_team_financials_file,
)


# --- Guard 1: read path never fabricates empties -------------------------------

def test_contracts_not_created_on_read_when_missing(tmp_path):
    path = tmp_path / "contracts.json"
    _ensure_contracts_file(path, write_missing=False)
    assert not path.exists()  # a read must not create an empty contracts file


def test_contracts_created_on_write_path(tmp_path):
    path = tmp_path / "contracts.json"
    _ensure_contracts_file(path, write_missing=True)  # league-creation path
    assert path.exists()
    assert json.loads(path.read_text())["players"] == {}


def test_present_contracts_preserved_on_read(tmp_path):
    path = tmp_path / "contracts.json"
    path.write_text(json.dumps({"version": 1, "players": {"P1": {"salary": 5}}}))
    _ensure_contracts_file(path, write_missing=False)
    assert "P1" in json.loads(path.read_text())["players"]


def test_team_financials_not_created_on_read_when_missing(tmp_path):
    path = tmp_path / "team_financials.json"
    _ensure_team_financials_file(path, data_dir=tmp_path, write_missing=False)
    assert not path.exists()


def test_settings_not_rewritten_on_read_when_missing(tmp_path):
    # The read path must not persist finance settings — otherwise a hydration gap
    # would save disabled defaults over the league's real enabled settings.
    from services.finance_settings import ensure_financial_defaults

    (tmp_path / "teams.csv").write_text("team_id,name\nBAL,Orioles\n")
    ensure_financial_defaults(data_dir=tmp_path, write_missing=False)
    assert not (tmp_path / "league_financial_settings.json").exists()
    ensure_financial_defaults(data_dir=tmp_path, write_missing=True)
    assert (tmp_path / "league_financial_settings.json").exists()


# --- Guard 2: push never overwrites a non-empty finance file with an empty one -

def _dst(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def _src(tmp_path, name, data):
    p = tmp_path / "src" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(data))
    return p


def test_empty_contracts_does_not_overwrite_real(tmp_path):
    dst = _dst(tmp_path, "contracts.json", {"version": 1, "players": {"P1": {}, "P2": {}}})
    src = _src(tmp_path, "contracts.json", {"version": 1, "players": {}})
    _copy_one((src, dst))
    assert len(json.loads(dst.read_text())["players"]) == 2  # remote preserved


def test_zeroed_team_financials_does_not_overwrite_real(tmp_path):
    dst = _dst(tmp_path, "team_financials.json", {"teams": {"BAL": {"cash_on_hand": 500}}})
    src = _src(tmp_path, "team_financials.json", {"teams": {"BAL": {"cash_on_hand": 0}}})
    _copy_one((src, dst))
    assert json.loads(dst.read_text())["teams"]["BAL"]["cash_on_hand"] == 500


def test_legit_nonempty_overwrite_still_works(tmp_path):
    dst = _dst(tmp_path, "contracts.json", {"version": 1, "players": {"P1": {}}})
    src = _src(tmp_path, "contracts.json", {"version": 1, "players": {"P9": {}}})
    _copy_one((src, dst))
    assert "P9" in json.loads(dst.read_text())["players"]


def test_finance_json_is_empty_detection(tmp_path):
    empty_c = _src(tmp_path, "contracts.json", {"version": 1, "players": {}})
    full_c = _dst(tmp_path, "contracts.json", {"version": 1, "players": {"P1": {}}})
    assert _finance_json_is_empty(empty_c) is True
    assert _finance_json_is_empty(full_c) is False
