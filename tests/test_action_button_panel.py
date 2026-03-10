from __future__ import annotations

from tests.qt_stubs import patch_qt


def test_resolve_action_button_columns_defaults():
    patch_qt()
    import ui.components as components

    assert components.resolve_action_button_columns(None) == 1
    assert components.resolve_action_button_columns(0) == 1
    assert components.resolve_action_button_columns(180) == 1
    assert components.resolve_action_button_columns(520) == 2
    assert components.resolve_action_button_columns(980) == 3
    assert components.resolve_action_button_columns(1800) == 3


def test_resolve_action_button_columns_honors_bounds():
    patch_qt()
    import ui.components as components

    assert (
        components.resolve_action_button_columns(
            900,
            min_columns=2,
            max_columns=4,
            target_button_width=200,
            horizontal_gap=10,
        )
        == 4
    )
    assert (
        components.resolve_action_button_columns(
            210,
            min_columns=2,
            max_columns=4,
            target_button_width=200,
            horizontal_gap=10,
        )
        == 2
    )
