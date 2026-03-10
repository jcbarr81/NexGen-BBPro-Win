from __future__ import annotations

from tests.qt_stubs import patch_qt


class _VisibilityProbe:
    def __init__(self) -> None:
        self.visible = None
        self.enabled = None

    def setVisible(self, value) -> None:
        self.visible = bool(value)

    def setEnabled(self, value) -> None:
        self.enabled = bool(value)


def test_open_change_request_export_dialog_blocked_in_single_player(monkeypatch):
    patch_qt()
    import ui.owner_dashboard as owner_dashboard

    info_calls: list[tuple[str, str]] = []
    opened: list[object] = []

    class _MessageBox:
        @staticmethod
        def information(_parent, title, text):
            info_calls.append((title, text))

    class _DummyDashboard:
        team_id = "AAA"

        def is_change_request_submission_available(self) -> bool:
            return False

    monkeypatch.setattr(owner_dashboard, "QMessageBox", _MessageBox)
    monkeypatch.setattr(owner_dashboard, "show_on_top", lambda window: opened.append(window))

    owner_dashboard.OwnerDashboard.open_change_request_export_dialog(_DummyDashboard())

    assert opened == []
    assert info_calls == [
        (
            "Owner Change Requests",
            "Submit Change Request is only available in multi-owner leagues.",
        )
    ]


def test_open_change_request_export_dialog_opens_in_owner_mode(monkeypatch):
    patch_qt()
    import ui.owner_dashboard as owner_dashboard

    tutorials: list[str] = []
    opened: list[object] = []

    class _DummyDialog:
        def __init__(self, team_id: str, parent: object) -> None:
            self.team_id = team_id
            self.parent = parent

    class _DummyDashboard:
        team_id = "BBB"

        def is_change_request_submission_available(self) -> bool:
            return True

        def show_change_request_tutorial(self) -> None:
            tutorials.append("shown")

    monkeypatch.setattr(owner_dashboard, "ChangeRequestExportDialog", _DummyDialog)
    monkeypatch.setattr(owner_dashboard, "show_on_top", lambda window: opened.append(window))

    dash = _DummyDashboard()
    owner_dashboard.OwnerDashboard.open_change_request_export_dialog(dash)

    assert tutorials == ["shown"]
    assert len(opened) == 1
    assert isinstance(opened[0], _DummyDialog)
    assert opened[0].team_id == "BBB"
    assert opened[0].parent is dash


def test_refresh_change_request_ui_state_updates_actions_and_roster_page():
    patch_qt()
    import ui.owner_dashboard as owner_dashboard

    updates: list[bool] = []

    class _RosterPage:
        def refresh_change_request_visibility(self, enabled: bool) -> None:
            updates.append(bool(enabled))

    class _DummyDashboard:
        def __init__(self) -> None:
            self._submit_change_request_action = _VisibilityProbe()
            self._change_request_tutorial_action = _VisibilityProbe()
            self.pages = {"roster": _RosterPage()}
            self._enabled = False

        def is_change_request_submission_available(self) -> bool:
            return self._enabled

    dash = _DummyDashboard()

    owner_dashboard.OwnerDashboard._refresh_change_request_ui_state(dash)
    assert dash._submit_change_request_action.visible is False
    assert dash._submit_change_request_action.enabled is False
    assert dash._change_request_tutorial_action.visible is False
    assert dash._change_request_tutorial_action.enabled is False
    assert updates == [False]

    dash._enabled = True
    owner_dashboard.OwnerDashboard._refresh_change_request_ui_state(dash)
    assert dash._submit_change_request_action.visible is True
    assert dash._submit_change_request_action.enabled is True
    assert dash._change_request_tutorial_action.visible is True
    assert dash._change_request_tutorial_action.enabled is True
    assert updates == [False, True]


def test_roster_page_refresh_change_request_visibility():
    patch_qt()
    import ui.roster_page as roster_page

    class _Dashboard:
        def is_change_request_submission_available(self) -> bool:
            return False

    page = roster_page.RosterPage.__new__(roster_page.RosterPage)
    page._dashboard = _Dashboard()
    page._change_request_button = _VisibilityProbe()

    roster_page.RosterPage.refresh_change_request_visibility(page)
    assert page._change_request_button.visible is False
    assert page._change_request_button.enabled is False

    roster_page.RosterPage.refresh_change_request_visibility(page, enabled=True)
    assert page._change_request_button.visible is True
    assert page._change_request_button.enabled is True
