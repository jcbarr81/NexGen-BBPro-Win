import sys
import types
from types import SimpleNamespace
import importlib

from tests.qt_stubs import patch_qt

patch_qt()

import ui.player_profile_dialog as legacy_profile
import ui.player_profile_launcher as launcher

importlib.reload(legacy_profile)
importlib.reload(launcher)


def test_create_player_profile_dialog_defaults_to_v2(monkeypatch):
    player = SimpleNamespace(player_id="p0")
    seen = {}

    class FakeLegacyDialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Legacy should not be constructed for V2 default")

    class FakeV2Dialog:
        def __init__(self, passed_player, parent=None):
            seen["player"] = passed_player
            seen["parent"] = parent

    legacy_module = types.ModuleType("ui.player_profile_dialog")
    legacy_module.PlayerProfileDialog = FakeLegacyDialog
    v2_module = types.ModuleType("ui.player_profile_dialog_v2")
    v2_module.PlayerProfileDialogV2 = FakeV2Dialog
    monkeypatch.setitem(sys.modules, "ui.player_profile_dialog", legacy_module)
    monkeypatch.setitem(sys.modules, "ui.player_profile_dialog_v2", v2_module)

    dialog = launcher.create_player_profile_dialog(player)

    assert isinstance(dialog, FakeV2Dialog)
    assert seen == {"player": player, "parent": None}


def test_create_player_profile_dialog_use_v2_overrides_variant(monkeypatch):
    player = SimpleNamespace(player_id="p1")
    seen = {}

    class FakeDialog:
        def __init__(self, passed_player, parent=None):
            seen["player"] = passed_player
            seen["parent"] = parent

    monkeypatch.setitem(
        __import__("sys").modules,
        "ui.player_profile_dialog_v2",
        SimpleNamespace(PlayerProfileDialogV2=FakeDialog),
    )
    monkeypatch.setattr(launcher, "show_on_top", lambda dialog: seen.setdefault("dialog", dialog))

    parent = object()
    result = launcher.open_player_profile_dialog(player, parent, variant="v2")

    assert seen["player"] is player
    assert seen["parent"] is parent
    assert isinstance(seen["dialog"], FakeDialog)
    assert result is seen["dialog"]


def test_create_player_profile_dialog_unknown_variant_falls_back_to_v2(monkeypatch):
    player = SimpleNamespace(player_id="p2")
    seen = {}

    class FakeLegacyDialog:
        def __init__(self, passed_player, parent=None):
            raise AssertionError("Legacy should not be constructed for unknown variant")

    class FakeV2Dialog:
        def __init__(self, passed_player, parent=None):
            seen["player"] = passed_player
            seen["parent"] = parent

    legacy_module = types.ModuleType("ui.player_profile_dialog")
    legacy_module.PlayerProfileDialog = FakeLegacyDialog
    v2_module = types.ModuleType("ui.player_profile_dialog_v2")
    v2_module.PlayerProfileDialogV2 = FakeV2Dialog
    monkeypatch.setitem(sys.modules, "ui.player_profile_dialog", legacy_module)
    monkeypatch.setitem(sys.modules, "ui.player_profile_dialog_v2", v2_module)

    dialog = launcher.create_player_profile_dialog(player, variant="unknown-token")

    assert isinstance(dialog, FakeV2Dialog)
    assert seen == {"player": player, "parent": None}


def test_create_player_profile_dialog_explicit_legacy_uses_legacy(monkeypatch):
    player = SimpleNamespace(player_id="p3")
    seen = {}

    class FakeLegacyDialog:
        def __init__(self, passed_player, parent=None):
            seen["player"] = passed_player
            seen["parent"] = parent

    class FakeV2Dialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Unexpected V2 construction for explicit legacy variant")

    legacy_module = types.ModuleType("ui.player_profile_dialog")
    legacy_module.PlayerProfileDialog = FakeLegacyDialog
    v2_module = types.ModuleType("ui.player_profile_dialog_v2")
    v2_module.PlayerProfileDialogV2 = FakeV2Dialog
    monkeypatch.setitem(sys.modules, "ui.player_profile_dialog", legacy_module)
    monkeypatch.setitem(sys.modules, "ui.player_profile_dialog_v2", v2_module)

    dialog = launcher.create_player_profile_dialog(player, variant="legacy")

    assert isinstance(dialog, FakeLegacyDialog)
    assert seen == {"player": player, "parent": None}


def test_legacy_profile_preview_calls_launcher(monkeypatch):
    player = SimpleNamespace(player_id="p2")
    seen = {}

    dlg = legacy_profile.PlayerProfileDialog.__new__(legacy_profile.PlayerProfileDialog)
    dlg.player = player

    def fake_open(passed_player, parent=None, *, variant="legacy"):
        seen["player"] = passed_player
        seen["parent"] = parent
        seen["variant"] = variant

    monkeypatch.setattr(legacy_profile, "open_player_profile_dialog", fake_open)

    legacy_profile.PlayerProfileDialog._open_preview_v2_dialog(dlg)

    assert seen == {"player": player, "parent": dlg, "variant": "v2"}
