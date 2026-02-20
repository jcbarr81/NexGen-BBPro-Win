from types import SimpleNamespace
import importlib

from tests.qt_stubs import patch_qt

patch_qt()

class Dummy:
    def __init__(self, *args, **kwargs):
        pass

import ui.player_profile_dialog as ppd
importlib.reload(ppd)


def test_player_profile_dialog_uses_history(monkeypatch):
    history = [
        {
            "date": "2024-09-30",
            "players": {"p1": {"ratings": {"ch": 38}, "stats": {"g": 120}}},
        },
        {
            "date": "2025-04-01",
            "players": {"p1": {"ratings": {"ch": 40}, "stats": {"g": 10}}},
        },
        {
            "date": "2025-10-05",
            "players": {"p1": {"ratings": {"ch": 45}, "stats": {"g": 162}}},
        },
    ]
    monkeypatch.setattr(
        ppd,
        "load_stats",
        lambda: {"players": {}, "teams": {}, "history": history},
    )

    player = SimpleNamespace(
        player_id="p1",
        first_name="T",
        last_name="P",
        birthdate="2000-01-01",
        height=70,
        weight=180,
        bats="R",
        primary_position="C",
        other_positions=[],
        gf=50,
        ch=50,
        ph=60,
        sp=70,
        pl=80,
        vl=65,
        sc=55,
        fa=40,
        arm=85,
    )

    calls = []

    def fake_create_stats_table(self, rows, columns):
        calls.append((rows, columns))
        return Dummy()

    monkeypatch.setattr(ppd.PlayerProfileDialog, "_create_stats_table", fake_create_stats_table)

    ppd.PlayerProfileDialog(player)

    assert calls, "Stats table should be built"
    rows_seen, _cols = calls[0]
    assert rows_seen[0][0] == "2025"
    assert rows_seen[0][1]["g"] == 162
    assert rows_seen[1][0] == "2024"
    assert rows_seen[1][1]["g"] == 120


def test_player_profile_dialog_handles_missing_positions(monkeypatch):
    """Ensure dialog renders even if position data is missing."""

    monkeypatch.setattr(
        ppd, "load_stats", lambda: {"players": {}, "teams": {}, "history": []}
    )

    player = SimpleNamespace(
        player_id="p2",
        first_name="A",
        last_name="B",
        birthdate="2000-01-01",
        height=70,
        weight=180,
        bats="R",
        primary_position=None,
        other_positions=[None],
        gf=40,
    )

    calls: list = []

    def fake_create_stats_table(self, rows, columns):
        calls.append((rows, columns))
        return Dummy()

    monkeypatch.setattr(ppd.PlayerProfileDialog, "_create_stats_table", fake_create_stats_table)

    dlg = ppd.PlayerProfileDialog(player)
    assert dlg is not None
    assert calls == []


def test_player_profile_overall_display_applies_scouting_adjustment(monkeypatch):
    monkeypatch.setattr(
        ppd, "load_stats", lambda: {"players": {}, "teams": {}, "history": []}
    )
    monkeypatch.setattr(ppd, "rating_display_value", lambda *args, **kwargs: 70)
    monkeypatch.setattr(
        ppd,
        "scouting_display_value",
        lambda value, **kwargs: int(value) + 2,
    )
    monkeypatch.setattr(ppd, "_lookup_player_team", lambda _pid: "AAA")

    player = SimpleNamespace(
        player_id="p3",
        first_name="Scout",
        last_name="Target",
        birthdate="2001-01-01",
        height=72,
        weight=185,
        bats="L",
        primary_position="CF",
        other_positions=[],
        gf=50,
        overall=68,
        ch=60,
        ph=62,
        sp=75,
        pl=55,
        vl=54,
        sc=58,
        fa=52,
        arm=57,
    )

    dlg = ppd.PlayerProfileDialog(player)
    display = dlg._overall_display_value(68, player)

    assert display == 72.0
