from types import SimpleNamespace
import importlib

from tests.qt_stubs import patch_qt

patch_qt()

import ui.player_profile_dialog as legacy_profile
import ui.player_profile_dialog_v2 as ppd_v2
import ui.player_profile_v2_viewmodel as vm_mod

importlib.reload(vm_mod)
importlib.reload(ppd_v2)


def _sample_vm(*, is_pitcher: bool = False, stats_rows=()):
    return vm_mod.PlayerProfileViewModel(
        player_id="p1",
        full_name="Test Player",
        initials="TP",
        team_id="AAA",
        is_pitcher=is_pitcher,
        positions_text="P" if is_pitcher else "CF",
        age_text="25",
        height_text="6'1\"",
        weight_text="195 lb",
        bats_text="R",
        throws_text="R",
        role_text="Starter" if is_pitcher else "",
        overall_display=72.0,
        overall_stars_text="2.5",
        scouting_summary="No scouting report available.",
        scouting_confidence_text="Exact",
        health_status="Available",
        header_metrics=(("Age", "25"), ("Team", "AAA")),
        defense_ratings=(("Fielding", "55"), ("Arm", "60"), ("Speed", "58")),
        overview_ratings=(("Contact", "70"), ("Power", "65")),
        training_focus=vm_mod.TrainingFocusSummary(
            source_text="League default",
            hitters_text="Contact 30%",
            pitchers_text="Command 25%",
        ),
        recent_training_entries=(vm_mod.ProfileNote(title="2026 - Contact"),),
        injury_history=(vm_mod.ProfileNote(title="2025-05-01 - Hamstring"),),
        stats_rows=tuple(stats_rows),
        stats_columns=("g", "h"),
    )


def test_player_profile_dialog_v2_smoke_hitter(monkeypatch):
    monkeypatch.setattr(ppd_v2, "build_player_profile_view_model", lambda _player: _sample_vm())

    dlg = ppd_v2.PlayerProfileDialogV2(SimpleNamespace(player_id="p1"))

    assert dlg is not None


def test_player_profile_dialog_v2_smoke_pitcher(monkeypatch):
    monkeypatch.setattr(
        ppd_v2,
        "build_player_profile_view_model",
        lambda _player: _sample_vm(is_pitcher=True),
    )

    dlg = ppd_v2.PlayerProfileDialogV2(SimpleNamespace(player_id="p1", primary_position="P"))

    assert dlg is not None


def test_player_profile_dialog_v2_uses_history(monkeypatch):
    rows = [
        ("2025", {"g": 162, "h": 180}),
        ("2024", {"g": 120, "h": 130}),
    ]
    monkeypatch.setattr(
        ppd_v2,
        "build_player_profile_view_model",
        lambda _player: _sample_vm(stats_rows=rows),
    )

    calls = []

    def fake_create_stats_table(self, seen_rows, seen_columns):
        calls.append((list(seen_rows), list(seen_columns)))
        return SimpleNamespace()

    monkeypatch.setattr(ppd_v2.PlayerProfileDialogV2, "_create_stats_table", fake_create_stats_table)

    ppd_v2.PlayerProfileDialogV2(SimpleNamespace(player_id="p1"))

    assert calls
    rows_seen, cols_seen = calls[0]
    assert rows_seen[0][0] == "2025"
    assert rows_seen[0][1]["g"] == 162
    assert rows_seen[1][0] == "2024"
    assert cols_seen == ["g", "h"]


def test_player_profile_dialog_v2_prompt_comparison_updates_native_state(monkeypatch):
    selected = SimpleNamespace(player_id="p9", first_name="Scout", last_name="Pick")
    visible = {}

    class FakeSelector:
        def __init__(self, pool, player_id, parent):
            self.pool = pool
            self.player_id = player_id
            self.parent = parent
            self.selected_player = selected

        def exec(self):
            return True

    class FakeButton:
        def setVisible(self, value):
            visible["value"] = value

    monkeypatch.setattr(ppd_v2, "build_player_profile_view_model", lambda _player: _sample_vm())
    monkeypatch.setattr(legacy_profile, "ComparisonSelectorDialog", FakeSelector)
    monkeypatch.setattr(ppd_v2, "load_players_from_csv", lambda _path: [selected])
    monkeypatch.setattr(ppd_v2, "load_stats", lambda: {"players": {"p9": {"ab": 12, "h": 4}}})

    dialog = ppd_v2.PlayerProfileDialogV2(SimpleNamespace(player_id="p1"))
    dialog._clear_compare_button = FakeButton()

    dialog._prompt_comparison_player()

    assert dialog._comparison_player is selected
    assert selected.season_stats == {"ab": 12, "h": 4}
    assert visible["value"] is True


def test_player_profile_dialog_v2_clear_comparison_handles_missing_selection(monkeypatch):
    visible = {}

    class FakeButton:
        def setVisible(self, value):
            visible["value"] = value

    monkeypatch.setattr(ppd_v2, "build_player_profile_view_model", lambda _player: _sample_vm())

    dialog = ppd_v2.PlayerProfileDialogV2(SimpleNamespace(player_id="p1"))
    dialog._comparison_player = SimpleNamespace(player_id="p9")
    dialog._clear_compare_button = FakeButton()

    dialog._refresh_compare_actions()
    dialog._clear_comparison()

    assert dialog._comparison_player is None
    assert visible["value"] is False


def test_player_profile_view_model_handles_missing_positions(monkeypatch):
    monkeypatch.setattr(vm_mod, "load_stats", lambda: {"players": {}, "teams": {}, "history": []})
    monkeypatch.setattr(
        vm_mod,
        "load_training_settings",
        lambda: SimpleNamespace(
            player_overrides={},
            team_overrides={},
            for_player=lambda _pid, _team_id=None: SimpleNamespace(
                hitter_weight=lambda _track: 20.0,
                pitcher_weight=lambda _track: 20.0,
            ),
        ),
    )
    monkeypatch.setattr(vm_mod, "load_player_training_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(vm_mod, "load_player_injury_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(vm_mod, "rating_display_value", lambda value, **_kwargs: value)
    monkeypatch.setattr(vm_mod, "scouting_display_value", lambda value, **_kwargs: value)
    monkeypatch.setattr(
        vm_mod,
        "scouting_display_profile_for_team",
        lambda *_args, **_kwargs: SimpleNamespace(confidence_label="Exact"),
    )
    monkeypatch.setattr(vm_mod, "_lookup_player_team", lambda _pid: "")

    player = SimpleNamespace(
        player_id="p2",
        first_name="A",
        last_name="B",
        birthdate="2000-01-01",
        height=70,
        weight=180,
        bats="R",
        throws="R",
        primary_position=None,
        other_positions=[None],
        gf=40,
        overall=68,
        season_stats={},
        career_history={},
    )

    vm = vm_mod.build_player_profile_view_model(player)

    assert vm.positions_text == "?"


def test_player_profile_view_model_applies_scouting_adjustment(monkeypatch):
    monkeypatch.setattr(vm_mod, "load_stats", lambda: {"players": {}, "teams": {}, "history": []})
    monkeypatch.setattr(
        vm_mod,
        "load_training_settings",
        lambda: SimpleNamespace(
            player_overrides={},
            team_overrides={},
            for_player=lambda _pid, _team_id=None: SimpleNamespace(
                hitter_weight=lambda _track: 20.0,
                pitcher_weight=lambda _track: 20.0,
            ),
        ),
    )
    monkeypatch.setattr(vm_mod, "load_player_training_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(vm_mod, "load_player_injury_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(vm_mod, "rating_display_value", lambda *_args, **_kwargs: 70)
    monkeypatch.setattr(vm_mod, "scouting_display_value", lambda value, **_kwargs: int(value) + 2)
    monkeypatch.setattr(
        vm_mod,
        "scouting_display_profile_for_team",
        lambda *_args, **_kwargs: SimpleNamespace(confidence_label="High"),
    )
    monkeypatch.setattr(vm_mod, "_lookup_player_team", lambda _pid: "AAA")

    player = SimpleNamespace(
        player_id="p3",
        first_name="Scout",
        last_name="Target",
        birthdate="2001-01-01",
        height=72,
        weight=185,
        bats="L",
        throws="L",
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
        season_stats={},
        career_history={},
    )

    vm = vm_mod.build_player_profile_view_model(player)

    assert vm.overall_display == 72.0
