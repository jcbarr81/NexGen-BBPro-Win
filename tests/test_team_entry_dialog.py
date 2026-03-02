from __future__ import annotations

from tests.qt_stubs import patch_qt


def test_import_team_entry_dialog_headless():
    patch_qt()
    from ui.team_entry_dialog import TeamEntryDialog  # noqa: F401

    assert TeamEntryDialog is not None


def test_team_entry_dialog_get_structure_trims_values():
    patch_qt()
    from ui.team_entry_dialog import TeamEntryDialog

    class _Field:
        def __init__(self, value: str) -> None:
            self._value = value

        def text(self) -> str:
            return self._value

    dialog = TeamEntryDialog.__new__(TeamEntryDialog)
    dialog._inputs = {
        "East": [
            (_Field("  New York  "), _Field("  Knights  ")),
            (_Field("Boston"), _Field("Pilots")),
        ],
        "West": [
            (_Field("Seattle "), _Field(" Falcons")),
        ],
    }

    structure = dialog.get_structure()

    assert structure == {
        "East": [("New York", "Knights"), ("Boston", "Pilots")],
        "West": [("Seattle", "Falcons")],
    }
