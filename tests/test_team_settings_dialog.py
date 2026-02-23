from __future__ import annotations

from dataclasses import dataclass

from ui.team_settings_dialog import (
    TeamSettingsDialog,
    _build_park_lookup,
    _match_park_by_name,
    _normalize_hex_color,
)


@dataclass
class _Park:
    name: str
    park_id: str = "park"
    year: int = 2025


def test_import_team_settings_dialog_headless():
    assert TeamSettingsDialog is not None


def test_normalize_hex_color_returns_uppercase():
    assert _normalize_hex_color("#a1b2c3", "#000000") == "#A1B2C3"


def test_normalize_hex_color_uses_fallback_for_invalid_input():
    assert _normalize_hex_color("123456", "#112233") == "#112233"


def test_match_park_by_name_prefers_exact_match():
    lookup = _build_park_lookup([_Park("Fenway Park"), _Park("Camden Yards")])
    found = _match_park_by_name(lookup, "Fenway Park")
    assert found is not None
    assert found.name == "Fenway Park"


def test_match_park_by_name_supports_partial_name():
    lookup = _build_park_lookup([_Park("Fenway Park"), _Park("Camden Yards")])
    found = _match_park_by_name(lookup, "Fenway")
    assert found is not None
    assert found.name == "Fenway Park"
