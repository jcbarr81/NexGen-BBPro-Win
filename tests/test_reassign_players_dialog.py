from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from models.roster import Roster
from tests.qt_stubs import patch_qt


def test_import_reassign_players_dialog_headless():
    patch_qt()
    from ui.reassign_players_dialog import ReassignPlayersDialog  # noqa: F401

    assert ReassignPlayersDialog is not None


def test_auto_reassign_team_updates_roster_and_shows_success(monkeypatch):
    patch_qt()
    import ui.reassign_players_dialog as dialog_mod

    refreshed = Roster(
        team_id="AAA",
        act=["A1", "A2"],
        aaa=["B1"],
        low=["C1"],
        dl=["D1"],
        ir=["I1"],
        dl_tiers={"D1": "dl15"},
    )

    captured: dict[str, object] = {"info": None, "warning": None, "auto": None}

    def fake_auto_assign_team(team_id: str, **kwargs):
        captured["auto"] = {"team_id": team_id, "kwargs": kwargs}

    def fake_load_roster(_team_id: str, _roster_dir: Path):
        return refreshed

    def fake_cache_clear(**_kwargs):
        return None

    fake_load_roster.cache_clear = fake_cache_clear  # type: ignore[attr-defined]

    class _MsgBox:
        class StandardButton:
            Yes = 1
            No = 2

        @staticmethod
        def information(_parent, _title, message):
            captured["info"] = message

        @staticmethod
        def warning(_parent, _title, message):
            captured["warning"] = message

    monkeypatch.setattr(dialog_mod, "auto_assign_team", fake_auto_assign_team)
    monkeypatch.setattr(dialog_mod, "load_roster", fake_load_roster)
    monkeypatch.setattr(dialog_mod, "get_data_dir", lambda: Path("data"))
    monkeypatch.setattr(dialog_mod, "clear_recovery", lambda _path: None)
    monkeypatch.setattr(dialog_mod, "missing_positions", lambda _roster, _players: [])
    monkeypatch.setattr(dialog_mod, "QMessageBox", _MsgBox)

    dialog = dialog_mod.ReassignPlayersDialog.__new__(dialog_mod.ReassignPlayersDialog)
    dialog.players = {}
    dialog.roster = Roster(team_id="AAA", act=["X"], aaa=["Y"], low=["Z"])
    dialog._has_unsaved_changes = lambda: False
    dialog._populate_lists_from_roster = lambda: None
    dialog._update_counts = lambda: None
    dialog._roster_file_path = lambda: Path("data/rosters/AAA.csv")
    dialog._refresh_baseline = lambda: None

    dialog._auto_reassign_team()

    assert captured["auto"] is not None
    assert dialog.roster.act == ["A1", "A2"]
    assert dialog.roster.aaa == ["B1"]
    assert dialog.roster.low == ["C1"]
    assert dialog.roster.dl == ["D1"]
    assert dialog.roster.ir == ["I1"]
    assert dialog.roster.dl_tiers == {"D1": "dl15"}
    assert captured["warning"] is None
    assert captured["info"] == "Auto-reassign completed for this team."


def test_save_roster_records_manual_reassign_events(monkeypatch):
    patch_qt()
    import ui.reassign_players_dialog as dialog_mod

    captured: dict[str, object] = {"events": None, "saved": None, "info": None}

    def fake_save_roster(team_id: str, roster: Roster):
        captured["saved"] = (team_id, list(roster.act), list(roster.aaa), list(roster.low))

    def fake_record_events(before, after, **kwargs):
        captured["events"] = {
            "before": dict(before),
            "after": dict(after),
            "kwargs": kwargs,
        }

    class _MsgBox:
        @staticmethod
        def warning(*_args, **_kwargs):
            return None

        @staticmethod
        def critical(*_args, **_kwargs):
            return None

        @staticmethod
        def information(_parent, _title, message):
            captured["info"] = message

    monkeypatch.setattr(dialog_mod, "save_roster", fake_save_roster)
    monkeypatch.setattr(dialog_mod, "record_roster_level_movements", fake_record_events)
    monkeypatch.setattr(dialog_mod, "clear_recovery", lambda _path: None)
    monkeypatch.setattr(dialog_mod, "QMessageBox", _MsgBox)

    dialog = dialog_mod.ReassignPlayersDialog.__new__(dialog_mod.ReassignPlayersDialog)
    dialog.players = {
        "P1": SimpleNamespace(first_name="One", last_name="Alpha"),
        "P2": SimpleNamespace(first_name="Two", last_name="Beta"),
    }
    dialog.roster = Roster(team_id="AAA", act=["P1"], aaa=["P2"], low=[])
    dialog._baseline = {
        "act": ["P2"],
        "aaa": ["P1"],
        "low": [],
        "dl": [],
        "ir": [],
        "dl_tiers": {},
    }
    dialog._validate_roster = lambda: []
    dialog._roster_file_path = lambda: Path("data/rosters/AAA.csv")
    dialog._refresh_baseline = lambda: None

    dialog._save_roster()

    assert captured["saved"] is not None
    assert captured["events"] is not None
    assert captured["info"] == "Roster saved successfully."
