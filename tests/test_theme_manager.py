from __future__ import annotations

import ui.theme as theme


class _DummyApp:
    def __init__(self) -> None:
        self._style = ""
        self._props: dict[str, str] = {}

    def setStyleSheet(self, style: str) -> None:
        self._style = style

    def styleSheet(self) -> str:
        return self._style

    def setProperty(self, key: str, value: str) -> None:
        self._props[key] = value

    def property(self, key: str):
        return self._props.get(key)


class _DummyQApplication:
    _instance = None

    @staticmethod
    def instance():
        return _DummyQApplication._instance


def test_theme_preferences_roundtrip(tmp_path, monkeypatch):
    prefs_path = tmp_path / "theme_preferences.json"
    monkeypatch.setattr(theme, "_preferences_path", lambda: prefs_path)

    theme.save_theme_preferences("enhanced_warm", "light")
    loaded = theme.load_theme_preferences()

    assert loaded["theme_family"] == "enhanced_warm"
    assert loaded["theme_mode"] == "light"


def test_load_theme_preferences_invalid_file_defaults(tmp_path, monkeypatch):
    prefs_path = tmp_path / "theme_preferences.json"
    prefs_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(theme, "_preferences_path", lambda: prefs_path)

    loaded = theme.load_theme_preferences()

    assert loaded == {
        "theme_family": theme.DEFAULT_THEME_FAMILY,
        "theme_mode": theme.DEFAULT_THEME_MODE,
    }


def test_apply_and_toggle_theme_with_dummy_app(monkeypatch):
    app = _DummyApp()
    _DummyQApplication._instance = app
    monkeypatch.setattr(theme, "QApplication", _DummyQApplication)

    family, mode = theme.apply_theme(
        family=theme.THEME_FAMILY_ENHANCED_WARM,
        mode=theme.THEME_MODE_LIGHT,
        persist=False,
    )
    assert family == theme.THEME_FAMILY_ENHANCED_WARM
    assert mode == theme.THEME_MODE_LIGHT
    assert app.property("nexgen_theme_family") == theme.THEME_FAMILY_ENHANCED_WARM
    assert app.property("nexgen_theme_mode") == theme.THEME_MODE_LIGHT

    toggled_family, toggled_mode = theme.toggle_theme_mode(persist=False)
    assert toggled_family == theme.THEME_FAMILY_ENHANCED_WARM
    assert toggled_mode == theme.THEME_MODE_DARK
    assert app.property("nexgen_theme_mode") == theme.THEME_MODE_DARK
