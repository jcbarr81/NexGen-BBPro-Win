import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture()
def ledger_module(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None

    import services.draft_pick_ledger as draft_pick_ledger

    importlib.reload(draft_pick_ledger)
    monkeypatch.setattr(
        draft_pick_ledger,
        "load_teams",
        lambda: [SimpleNamespace(team_id="A"), SimpleNamespace(team_id="B")],
    )
    monkeypatch.setattr(
        draft_pick_ledger,
        "load_draft_config",
        lambda: {"rounds": 2},
    )
    return draft_pick_ledger


def test_list_team_picks_seeds_missing_assets(ledger_module):
    picks = ledger_module.list_team_picks("A", years=[2028])
    ids = [pick.pick_id for pick in picks]
    assert ids == ["2028|1|A", "2028|2|A"]


def test_transfer_pick_updates_owner(ledger_module):
    pick_id = "2028|1|A"
    ledger_module.list_team_picks("A", years=[2028])
    ledger_module.transfer_pick(pick_id, "A", "B")
    assert ledger_module.get_pick_owner(2028, 1, "A") == "B"
